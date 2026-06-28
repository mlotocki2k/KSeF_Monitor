"""
Unit tests for KSeFClient
"""

import pytest
import json
import base64
import hashlib
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

    def test_session_requests_problem_details_errors(self, mock_config):
        """Client requests consistent application/problem+json error format."""
        c = KSeFClient(mock_config)
        assert c.session.headers.get("X-Error-Format") == "problem-details"

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
        client.rate_limiter.acquire = MagicMock(return_value=0.0)

        mock_response = MagicMock()
        mock_response.status_code = 200
        client.session.request = MagicMock(return_value=mock_response)

        result = client._request_with_retry("GET", "https://example.com")
        assert result.status_code == 200
        assert client.session.request.call_count == 1
        client.rate_limiter.acquire.assert_called_once()

    @patch("app.ksef_client.time.sleep")
    def test_429_retry(self, mock_sleep, client):
        """429 triggers retry with Retry-After header."""
        client.rate_limiter.acquire = MagicMock(return_value=0.0)
        client.rate_limiter.pause_until = MagicMock()

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
        client.rate_limiter.pause_until.assert_called_once_with(5)

    @patch("app.ksef_client.time.sleep")
    def test_429_exhausted(self, mock_sleep, client):
        """Returns 429 after max retries exhausted."""
        client.rate_limiter.acquire = MagicMock(return_value=0.0)
        client.rate_limiter.pause_until = MagicMock()

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
        client.rate_limiter.acquire = MagicMock(return_value=0.0)
        client.rate_limiter.pause_until = MagicMock()

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
        client.rate_limiter.acquire = MagicMock(return_value=0.0)
        client.rate_limiter.pause_until = MagicMock()

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


class TestKSeFClientPublicKeyId:
    """v0.6 — publicKeyId forward-compat for KSeF v2.5.0 public key rotation."""

    @staticmethod
    def _self_signed_cert_b64():
        import base64
        import datetime

        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "KSeF Test Key")])
        nb = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(nb)
            .not_valid_after(nb + datetime.timedelta(days=365))
            .sign(key, hashes.SHA256())
        )
        der = cert.public_bytes(serialization.Encoding.DER)
        return base64.b64encode(der).decode()

    @staticmethod
    def _rsa_public_key():
        from cryptography.hazmat.primitives.asymmetric import rsa

        return rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()

    def test_fetch_public_key_stores_id(self, client):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = [
            {
                "certificate": self._self_signed_cert_b64(),
                "certificateId": "CID",
                "publicKeyId": "A" * 44,
                "usage": ["KsefTokenEncryption"],
            }
        ]
        with patch.object(client, "_request_with_retry", return_value=resp):
            client._fetch_public_key()
        assert client._ksef_public_key is not None
        assert client._ksef_public_key_id == "A" * 44

    def test_authenticate_with_token_sends_public_key_id(self, client):
        client._ksef_public_key = self._rsa_public_key()
        client._ksef_public_key_id = "B" * 44
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "referenceNumber": "R",
            "authenticationToken": {"token": "T"},
        }
        with patch.object(client, "_request_with_retry", return_value=resp) as req:
            client._authenticate_with_token("chal", 123)
        payload = req.call_args.kwargs["json"]
        assert payload["publicKeyId"] == "B" * 44
        assert payload["encryptedToken"]

    def test_authenticate_with_token_omits_id_when_none(self, client):
        client._ksef_public_key = self._rsa_public_key()
        client._ksef_public_key_id = None
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "referenceNumber": "R",
            "authenticationToken": {"token": "T"},
        }
        with patch.object(client, "_request_with_retry", return_value=resp) as req:
            client._authenticate_with_token("chal", 123)
        payload = req.call_args.kwargs["json"]
        assert "publicKeyId" not in payload

    def test_fetch_public_key_snapshot_v25_schema(self, client):
        """v2.5.0 PublicKeyCertificate schema (certificateId + publicKeyId): select
        the KsefTokenEncryption cert among several usages and store ITS publicKeyId."""
        cert_b64 = self._self_signed_cert_b64()
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = [
            {
                "certificate": cert_b64, "certificateId": "SYM",
                "publicKeyId": "X" * 44,
                "validFrom": "2026-01-01T00:00:00Z", "validTo": "2027-01-01T00:00:00Z",
                "usage": ["SymmetricKeyEncryption"],
            },
            {
                "certificate": cert_b64, "certificateId": "TOK",
                "publicKeyId": "Y" * 44,
                "validFrom": "2026-01-01T00:00:00Z", "validTo": "2027-01-01T00:00:00Z",
                "usage": ["KsefTokenEncryption"],
            },
        ]
        with patch.object(client, "_request_with_retry", return_value=resp):
            client._fetch_public_key()
        assert client._ksef_public_key is not None
        assert client._ksef_public_key_id == "Y" * 44  # from the token-encryption cert


class TestKSeFClientUPO:
    """v0.6 §4 — UPO download (sessions listing + SHA-256 integrity verification)."""

    VALID_KSEF = "1234567890-20240101-ABCDEF123456-AB"

    @staticmethod
    def _resp(json_data=None, content=None, headers=None):
        r = MagicMock()
        r.raise_for_status.return_value = None
        if json_data is not None:
            r.json.return_value = json_data
        if content is not None:
            r.content = content
        r.headers = headers or {}
        return r

    def test_verify_sha256_match(self, client):
        data = b"<UPO/>"
        h = base64.b64encode(hashlib.sha256(data).digest()).decode()
        assert client._verify_sha256(data, h) is True

    def test_verify_sha256_mismatch(self, client):
        assert client._verify_sha256(b"<UPO/>", "deadbeef") is False

    def test_verify_sha256_empty_header(self, client):
        assert client._verify_sha256(b"x", "") is False

    def test_list_sessions_returns_list(self, client):
        resp = self._resp(json_data={"sessions": [{"referenceNumber": "S1"}]})
        with patch.object(client, "_make_authenticated_request", return_value=resp) as req:
            out = client.list_sessions("Online")
        assert out == [{"referenceNumber": "S1"}]
        assert req.call_args[0][1].endswith("/v2/sessions")
        assert req.call_args.kwargs["params"]["sessionType"] == "Online"

    def test_list_sessions_auth_fail_returns_empty(self, client):
        with patch.object(client, "_make_authenticated_request", return_value=None):
            assert client.list_sessions() == []

    def test_get_session_invoices_returns_list(self, client):
        resp = self._resp(json_data={"invoices": [{"ksefNumber": "K1", "upoDownloadUrl": "https://x"}]})
        with patch.object(client, "_make_authenticated_request", return_value=resp) as req:
            out = client.get_session_invoices("S1")
        assert out[0]["ksefNumber"] == "K1"
        assert "/v2/sessions/S1/invoices" in req.call_args[0][1]

    def test_get_invoice_upo_happy_verifies_hash(self, client):
        data = b"<UPO>ok</UPO>"
        h = base64.b64encode(hashlib.sha256(data).digest()).decode()
        resp = self._resp(content=data, headers={"x-ms-meta-hash": h})
        with patch.object(client, "_make_authenticated_request", return_value=resp) as req:
            out = client.get_invoice_upo("S1", self.VALID_KSEF)
        assert out["upo_xml"] == "<UPO>ok</UPO>"
        assert out["hash_verified"] is True
        assert out["sha256_hash"] == h
        assert f"/sessions/S1/invoices/ksef/{self.VALID_KSEF}/upo" in req.call_args[0][1]

    def test_get_invoice_upo_hash_mismatch_returns_none(self, client):
        resp = self._resp(content=b"<UPO/>", headers={"x-ms-meta-hash": "AAAA"})
        with patch.object(client, "_make_authenticated_request", return_value=resp):
            assert client.get_invoice_upo("S1", self.VALID_KSEF) is None

    def test_get_invoice_upo_no_header_unverified(self, client):
        resp = self._resp(content=b"<UPO/>", headers={})
        with patch.object(client, "_make_authenticated_request", return_value=resp):
            out = client.get_invoice_upo("S1", self.VALID_KSEF)
        assert out["hash_verified"] is False
        assert out["upo_xml"] == "<UPO/>"

    def test_get_invoice_upo_invalid_ksef_returns_none(self, client):
        with patch.object(client, "_make_authenticated_request") as req:
            assert client.get_invoice_upo("S1", "bad") is None
            req.assert_not_called()
