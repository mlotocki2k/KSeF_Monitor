"""
Unit tests for KSeFClient
"""

import pytest
import json
import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, PropertyMock

from app.ksef_client import KSeFClient


@pytest.fixture
def client(mock_config):
    """Create KSeFClient with mocked config."""
    return KSeFClient(mock_config)


class TestKSeFClientInit:
    """Tests for KSeFClient initialization."""

    def test_test_environment(self, mock_config):
        """Test environment URL."""
        c = KSeFClient(mock_config)
        assert c.base_url == "https://api-test.ksef.mf.gov.pl"
        assert c.environment == "test"

    def test_prod_environment(self, mock_config):
        """Production environment URL."""
        mock_config.config["ksef"]["environment"] = "prod"
        mock_config.get = lambda *keys, default=None: (
            "prod" if keys == ("ksef", "environment") else
            mock_config.config.get(keys[0], {}).get(keys[1]) if len(keys) == 2 else default
        )
        # Rebuild get to properly handle
        original_config = mock_config.config.copy()
        original_config["ksef"]["environment"] = "prod"

        def _get(*keys, default=None):
            value = original_config
            for key in keys:
                if isinstance(key, str) and isinstance(value, dict):
                    value = value.get(key)
                    if value is None:
                        return default
                else:
                    return default
            return value

        mock_config.get = _get
        c = KSeFClient(mock_config)
        assert c.base_url == "https://api.ksef.mf.gov.pl"

    def test_demo_environment(self, mock_config):
        """Demo environment URL."""
        mock_config.config["ksef"]["environment"] = "demo"

        def _get(*keys, default=None):
            value = mock_config.config
            for key in keys:
                if isinstance(key, str) and isinstance(value, dict):
                    value = value.get(key)
                    if value is None:
                        return default
                else:
                    return default
            return value

        mock_config.get = _get
        c = KSeFClient(mock_config)
        assert c.base_url == "https://api-demo.ksef.mf.gov.pl"

    def test_invalid_date_type_falls_back(self, mock_config):
        """Invalid date_type falls back to Invoicing."""
        mock_config.config["monitoring"]["date_type"] = "Invalid"

        def _get(*keys, default=None):
            value = mock_config.config
            for key in keys:
                if isinstance(key, str) and isinstance(value, dict):
                    value = value.get(key)
                    if value is None:
                        return default
                else:
                    return default
            return value

        mock_config.get = _get
        c = KSeFClient(mock_config)
        assert c.date_type == "Invoicing"


class TestKSeFClientValidateKsefNumber:
    """Tests for _validate_ksef_number()."""

    def test_valid_number(self):
        """Valid KSeF number format."""
        assert KSeFClient._validate_ksef_number("1234567890-20260301-ABCDEF-XY") is True

    def test_valid_number_long_random(self):
        """Valid KSeF number with longer random part."""
        assert KSeFClient._validate_ksef_number("1234567890-20260301-ABCDEF123456-XY") is True

    def test_invalid_nip_length(self):
        """Invalid NIP length."""
        assert KSeFClient._validate_ksef_number("12345-20260301-ABCDEF-XY") is False

    def test_invalid_date_format(self):
        """Invalid date portion."""
        assert KSeFClient._validate_ksef_number("1234567890-2026031-ABCDEF-XY") is False

    def test_too_short_random(self):
        """Random part too short (needs 6+)."""
        assert KSeFClient._validate_ksef_number("1234567890-20260301-ABC-XY") is False

    def test_invalid_suffix(self):
        """Suffix must be 2 alphanumeric chars."""
        assert KSeFClient._validate_ksef_number("1234567890-20260301-ABCDEF-X") is False

    def test_empty_string(self):
        """Empty string is invalid."""
        assert KSeFClient._validate_ksef_number("") is False

    def test_no_separators(self):
        """Number without separators is invalid."""
        assert KSeFClient._validate_ksef_number("123456789020260301ABCDEFXY") is False


class TestKSeFClientExtractApiErrorDetails:
    """Tests for _extract_api_error_details()."""

    def test_problem_json(self):
        """Parse problem+json format."""
        response = MagicMock()
        response.status_code = 401
        response.headers = {"Content-Type": "application/problem+json"}
        response.json.return_value = {
            "reasonCode": "AUTH_EXPIRED",
            "detail": "Token expired",
            "title": "Unauthorized"
        }
        result = KSeFClient._extract_api_error_details(response)
        assert "AUTH_EXPIRED" in result
        assert "Token expired" in result
        assert "401" in result

    def test_exception_response(self):
        """Parse KSeF ExceptionResponse format."""
        response = MagicMock()
        response.status_code = 400
        response.headers = {"Content-Type": "application/json"}
        response.json.return_value = {
            "exception": {
                "exceptionDetailList": [
                    {
                        "exceptionCode": "22001",
                        "exceptionDescription": "Invalid NIP"
                    }
                ]
            }
        }
        result = KSeFClient._extract_api_error_details(response)
        assert "22001" in result
        assert "Invalid NIP" in result

    def test_fallback_status_only(self):
        """Fallback to status code only."""
        response = MagicMock()
        response.status_code = 500
        response.headers = {"Content-Type": "text/plain"}
        response.json.side_effect = ValueError("not json")
        result = KSeFClient._extract_api_error_details(response)
        assert result == "status=500"

    def test_exception_without_details(self):
        """Exception response without detail list."""
        response = MagicMock()
        response.status_code = 400
        response.headers = {"Content-Type": "application/json"}
        response.json.return_value = {
            "exception": {
                "serviceName": "InvoiceService",
                "referenceNumber": "REF-123"
            }
        }
        result = KSeFClient._extract_api_error_details(response)
        assert "InvoiceService" in result
        assert "REF-123" in result


class TestKSeFClientRequestWithRetry:
    """Tests for _request_with_retry() 429 handling."""

    def test_success_no_retry(self, client):
        """Successful request needs no retry."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        client.session.request = MagicMock(return_value=mock_response)

        result = client._request_with_retry("GET", "https://example.com")
        assert result.status_code == 200
        assert client.session.request.call_count == 1

    @patch("app.ksef_client.time.sleep")
    def test_429_retry(self, mock_sleep, client):
        """429 triggers retry with Retry-After header."""
        retry_response = MagicMock()
        retry_response.status_code = 429
        retry_response.headers = {"Retry-After": "5"}
        retry_response.json.return_value = {"status": {"details": []}}

        success_response = MagicMock()
        success_response.status_code = 200

        client.session.request = MagicMock(
            side_effect=[retry_response, success_response]
        )

        result = client._request_with_retry("GET", "https://example.com")
        assert result.status_code == 200
        mock_sleep.assert_called_once_with(5)

    @patch("app.ksef_client.time.sleep")
    def test_429_exhausted(self, mock_sleep, client):
        """Returns 429 after max retries exhausted."""
        retry_response = MagicMock()
        retry_response.status_code = 429
        retry_response.headers = {"Retry-After": "1"}
        retry_response.json.return_value = {"status": {"details": []}}

        client.session.request = MagicMock(return_value=retry_response)

        result = client._request_with_retry("GET", "https://example.com")
        assert result.status_code == 429
        assert client.session.request.call_count == client.MAX_429_RETRIES + 1

    @patch("app.ksef_client.time.sleep")
    def test_429_default_retry_after(self, mock_sleep, client):
        """Uses default retry-after when header missing."""
        retry_response = MagicMock()
        retry_response.status_code = 429
        retry_response.headers = {}
        retry_response.json.return_value = {"status": {"details": []}}

        success_response = MagicMock()
        success_response.status_code = 200

        client.session.request = MagicMock(
            side_effect=[retry_response, success_response]
        )

        client._request_with_retry("GET", "https://example.com")
        mock_sleep.assert_called_once_with(client.DEFAULT_RETRY_AFTER)

    @patch("app.ksef_client.time.sleep")
    def test_429_retry_after_capped(self, mock_sleep, client):
        """Retry-After is capped at MAX_RETRY_AFTER (1800 seconds)."""
        retry_response = MagicMock()
        retry_response.status_code = 429
        retry_response.headers = {"Retry-After": "3600"}
        retry_response.json.return_value = {"status": {"details": []}}

        success_response = MagicMock()
        success_response.status_code = 200

        client.session.request = MagicMock(
            side_effect=[retry_response, success_response]
        )

        client._request_with_retry("GET", "https://example.com")
        mock_sleep.assert_called_once_with(1800)


class TestKSeFClientHandle401Refresh:
    """Tests for _handle_401_refresh()."""

    def test_refresh_succeeds(self, client):
        """Successful refresh returns True."""
        client.refresh_access_token = MagicMock(return_value=True)
        response = MagicMock()
        response.status_code = 401
        response.headers = {"Content-Type": "application/json"}
        response.json.return_value = {}
        assert client._handle_401_refresh(response) is True

    def test_refresh_fails_reauthenticates(self, client):
        """Failed refresh triggers re-authentication."""
        client.refresh_access_token = MagicMock(return_value=False)
        client.authenticate = MagicMock(return_value=True)
        response = MagicMock()
        response.status_code = 401
        response.headers = {"Content-Type": "application/json"}
        response.json.return_value = {}
        assert client._handle_401_refresh(response) is True
        client.authenticate.assert_called_once()

    def test_both_fail(self, client):
        """Both refresh and re-auth fail returns False."""
        client.refresh_access_token = MagicMock(return_value=False)
        client.authenticate = MagicMock(return_value=False)
        response = MagicMock()
        response.status_code = 401
        response.headers = {"Content-Type": "application/json"}
        response.json.return_value = {}
        assert client._handle_401_refresh(response) is False


class TestKSeFClientRefreshToken:
    """Tests for refresh_access_token()."""

    def test_no_refresh_token(self, client):
        """Returns False when no refresh token available."""
        client.refresh_token = None
        assert client.refresh_access_token() is False

    def test_successful_refresh(self, client):
        """Successful token refresh."""
        client.refresh_token = "old-refresh-token"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "accessToken": {"token": "new-access-token"}
        }
        mock_response.raise_for_status = MagicMock()
        client.session.request = MagicMock(return_value=mock_response)

        assert client.refresh_access_token() is True
        assert client.access_token == "new-access-token"


class TestKSeFClientGetInvoiceXml:
    """Tests for get_invoice_xml()."""

    def test_invalid_ksef_number_rejected(self, client):
        """Invalid KSeF number returns None immediately."""
        result = client.get_invoice_xml("invalid-number")
        assert result is None

    def test_successful_fetch(self, client):
        """Successful XML fetch."""
        client.access_token = "valid-token"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<Faktura>...</Faktura>"
        mock_response.headers = {"x-ms-meta-hash": "sha256hash"}
        mock_response.raise_for_status = MagicMock()
        client.session.request = MagicMock(return_value=mock_response)

        result = client.get_invoice_xml("1234567890-20260301-ABCDEF-XY")
        assert result is not None
        assert result["xml_content"] == "<Faktura>...</Faktura>"
        assert result["sha256_hash"] == "sha256hash"

    def test_not_authenticated(self, client):
        """No access token triggers authentication."""
        client.access_token = None
        client.authenticate = MagicMock(return_value=False)

        result = client.get_invoice_xml("1234567890-20260301-ABCDEF-XY")
        assert result is None
        client.authenticate.assert_called_once()


class TestKSeFClientRevokeSession:
    """Tests for revoke_current_session()."""

    def test_no_token_skips(self, client):
        """No access token skips revocation."""
        client.access_token = None
        client.revoke_current_session()
        # Should not raise

    def test_successful_revoke(self, client):
        """Successful session revocation clears tokens."""
        client.access_token = "token"
        client.refresh_token = "refresh"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        client.session.request = MagicMock(return_value=mock_response)

        client.revoke_current_session()
        assert client.access_token is None
        assert client.refresh_token is None
