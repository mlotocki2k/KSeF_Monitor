"""
Tests for iOS Push Notifier — sends notifications via Cloudflare Worker to APNs.
"""

import json
from unittest.mock import MagicMock

import pytest
import requests

from app.notifiers.ios_push_notifier import IosPushNotifier


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def ios_push_config():
    """Full config dict with ios_push configured."""
    return {
        "notifications": {
            "ios_push": {
                "worker_url": "https://push.monitorksef.com",
                "instance_id": "550e8400-e29b-41d4-a716-446655440000",
                "instance_key": "abc123def456",
                "timeout": 15,
            }
        }
    }


@pytest.fixture
def notifier(ios_push_config):
    """Configured IosPushNotifier with mocked session."""
    n = IosPushNotifier(ios_push_config)
    n.session = MagicMock()
    return n


@pytest.fixture
def mock_ok_response():
    """Mock 200 OK response from Worker."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"ok": True, "sent": 2, "failed": 0}
    return resp


@pytest.fixture
def unconfigured_notifier():
    """IosPushNotifier without credentials."""
    return IosPushNotifier({"notifications": {"ios_push": {}}})


# ── Configuration ────────────────────────────────────────────────────────────


class TestIosPushConfiguration:
    """Test iOS Push notifier configuration and properties."""

    def test_is_configured_with_all_fields(self):
        config = {
            "notifications": {
                "ios_push": {
                    "worker_url": "https://push.monitorksef.com",
                    "instance_id": "uuid",
                    "instance_key": "key",
                }
            }
        }
        n = IosPushNotifier(config)
        assert n.is_configured is True

    def test_not_configured_without_instance_id(self):
        config = {
            "notifications": {
                "ios_push": {
                    "worker_url": "https://push.monitorksef.com",
                    "instance_key": "abc123",
                }
            }
        }
        n = IosPushNotifier(config)
        assert n.is_configured is False

    def test_not_configured_without_instance_key(self):
        config = {
            "notifications": {
                "ios_push": {
                    "worker_url": "https://push.monitorksef.com",
                    "instance_id": "some-uuid",
                }
            }
        }
        n = IosPushNotifier(config)
        assert n.is_configured is False

    def test_not_configured_empty_config(self, unconfigured_notifier):
        assert unconfigured_notifier.is_configured is False

    def test_not_configured_no_notifications(self):
        n = IosPushNotifier({})
        assert n.is_configured is False

    def test_channel_name(self):
        n = IosPushNotifier({})
        assert n.channel_name == "iOS Push"

    def test_template_channel_override(self):
        """_template_channel must be 'ios_push' (not 'ios push')."""
        n = IosPushNotifier({})
        assert n._template_channel == "ios_push"

    def test_default_worker_url(self):
        config = {
            "notifications": {
                "ios_push": {
                    "instance_id": "uuid",
                    "instance_key": "key",
                }
            }
        }
        n = IosPushNotifier(config)
        assert n.worker_url == "https://push.monitorksef.com"

    def test_default_timeout(self):
        config = {
            "notifications": {
                "ios_push": {
                    "worker_url": "https://push.monitorksef.com",
                    "instance_id": "uuid",
                    "instance_key": "key",
                }
            }
        }
        n = IosPushNotifier(config)
        assert n.timeout == 15


# ── Send Notification ────────────────────────────────────────────────────────


class TestIosPushSendNotification:
    """Test send_notification() method."""

    def test_successful_send(self, notifier, mock_ok_response):
        notifier.session.post.return_value = mock_ok_response
        result = notifier.send_notification("Test Title", "Test Body")
        assert result is True

    def test_auth_headers_present(self, notifier, mock_ok_response):
        notifier.session.post.return_value = mock_ok_response
        notifier.send_notification("Title", "Body")

        call_kwargs = notifier.session.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["X-Instance-Id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert headers["X-Instance-Key"] == "abc123def456"

    def test_payload_structure(self, notifier, mock_ok_response):
        notifier.session.post.return_value = mock_ok_response
        notifier.send_notification("Title", "Body", url="https://example.com")

        call_kwargs = notifier.session.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["title"] == "Title"
        assert payload["body"] == "Body"
        assert payload["data"]["url"] == "https://example.com"
        # v1.2 required fields
        assert "notification_id" in payload["data"]
        assert payload["data"]["type"] == "system"
        assert payload["data"]["invoice_reference"] == "n/a"

    def test_post_url(self, notifier, mock_ok_response):
        notifier.session.post.return_value = mock_ok_response
        notifier.send_notification("Title", "Body")

        call_args = notifier.session.post.call_args
        url = call_args.args[0] if call_args.args else call_args[0][0]
        assert url == "https://push.monitorksef.com/push/send"

    def test_no_redirects(self, notifier, mock_ok_response):
        notifier.session.post.return_value = mock_ok_response
        notifier.send_notification("Title", "Body")

        call_kwargs = notifier.session.post.call_args
        assert call_kwargs.kwargs.get("allow_redirects") is False

    def test_not_configured_returns_false(self, unconfigured_notifier):
        result = unconfigured_notifier.send_notification("Title", "Body")
        assert result is False

    def test_request_exception_returns_false(self, notifier):
        notifier.session.post.side_effect = requests.exceptions.ConnectionError("timeout")
        result = notifier.send_notification("Title", "Body")
        assert result is False

    def test_401_returns_false(self, notifier):
        mock_response = MagicMock()
        mock_response.status_code = 401
        notifier.session.post.return_value = mock_response

        result = notifier.send_notification("Title", "Body")
        assert result is False

    def test_429_returns_false(self, notifier):
        mock_response = MagicMock()
        mock_response.status_code = 429
        notifier.session.post.return_value = mock_response

        result = notifier.send_notification("Title", "Body")
        assert result is False

    def test_body_truncated_to_256(self, notifier, mock_ok_response):
        notifier.session.post.return_value = mock_ok_response

        long_body = "A" * 500
        notifier.send_notification("Title", long_body)

        call_kwargs = notifier.session.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert len(payload["body"]) == 256

    def test_data_always_present_v12(self, notifier, mock_ok_response):
        """v1.2: data is always present with required fields."""
        notifier.session.post.return_value = mock_ok_response
        notifier.send_notification("Title", "Body")

        call_kwargs = notifier.session.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "data" in payload
        assert "notification_id" in payload["data"]
        assert payload["data"]["type"] == "system"
        assert payload["data"]["invoice_reference"] == "n/a"


# ── Send Rendered ────────────────────────────────────────────────────────────


class TestIosPushSendRendered:
    """Test _send_rendered() with JSON template output."""

    def test_valid_json_sent(self, notifier, mock_ok_response):
        notifier.session.post.return_value = mock_ok_response

        rendered = json.dumps({"title": "Test", "body": "Rendered body"})
        context = {"title": "Test"}
        result = notifier._send_rendered(rendered, context)
        assert result is True

    def test_v12_fields_injected(self, notifier, mock_ok_response):
        """v1.2: _send_rendered injects notification_id, type, invoice_reference."""
        notifier.session.post.return_value = mock_ok_response

        rendered = json.dumps({
            "title": "Test", "body": "Body",
            "data": {"ksef_number": "KSeF-123"}
        })
        notifier._send_rendered(rendered, {"title": "Test"})

        call_kwargs = notifier.session.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "notification_id" in payload["data"]
        assert payload["data"]["type"] == "new_invoice"
        assert payload["data"]["ksef_number"] == "KSeF-123"

    def test_invalid_json_returns_false(self, notifier):
        result = notifier._send_rendered("not valid json{", {"title": "Test"})
        assert result is False

    def test_auth_headers_in_rendered(self, notifier, mock_ok_response):
        notifier.session.post.return_value = mock_ok_response

        rendered = json.dumps({"title": "T", "body": "B"})
        notifier._send_rendered(rendered, {"title": "T"})

        call_kwargs = notifier.session.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert "X-Instance-Id" in headers
        assert "X-Instance-Key" in headers

    def test_not_configured_returns_false(self, unconfigured_notifier):
        result = unconfigured_notifier._send_rendered('{"title":"T"}', {})
        assert result is False


# ── Error and Test ───────────────────────────────────────────────────────────


class TestIosPushErrorAndTest:
    """Test send_error_notification() and test_connection()."""

    def test_send_error_delegates(self, notifier, mock_ok_response):
        notifier.session.post.return_value = mock_ok_response

        result = notifier.send_error_notification("Something broke")
        assert result is True

        call_kwargs = notifier.session.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["title"] == "KSeF Monitor Error"

    def test_test_connection(self, notifier, mock_ok_response):
        notifier.session.post.return_value = mock_ok_response

        result = notifier.test_connection()
        assert result is True

        call_kwargs = notifier.session.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["title"] == "KSeF Monitor Test"


# ── F-06: Authorization Header ──────────────────────────────────────────────


class TestIosPushAuthorizationHeader:
    """F-06: Verify Authorization: Bearer {INTERNAL_SECRET} on Worker requests."""

    def test_authorization_header_present(self, mock_ok_response):
        """Authorization header sent when internal_secret configured."""
        config = {
            "notifications": {
                "ios_push": {
                    "worker_url": "https://push.monitorksef.com",
                    "instance_id": "uuid-123",
                    "instance_key": "key-456",
                    "internal_secret": "my-secret",
                }
            }
        }
        n = IosPushNotifier(config)
        n.session = MagicMock()
        n.session.post.return_value = mock_ok_response

        n.send_notification("Title", "Body")

        call_kwargs = n.session.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["Authorization"] == "Bearer my-secret"

    def test_no_authorization_without_secret(self, notifier, mock_ok_response):
        """No Authorization header when internal_secret not set."""
        notifier.session.post.return_value = mock_ok_response
        notifier.send_notification("Title", "Body")

        call_kwargs = notifier.session.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert "Authorization" not in headers

    def test_authorization_in_send_rendered(self, mock_ok_response):
        """Authorization header also present in _send_rendered."""
        config = {
            "notifications": {
                "ios_push": {
                    "worker_url": "https://push.monitorksef.com",
                    "instance_id": "uuid-123",
                    "instance_key": "key-456",
                    "internal_secret": "render-secret",
                }
            }
        }
        n = IosPushNotifier(config)
        n.session = MagicMock()
        n.session.post.return_value = mock_ok_response

        rendered = json.dumps({"title": "T", "body": "B"})
        n._send_rendered(rendered, {"title": "T"})

        call_kwargs = n.session.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["Authorization"] == "Bearer render-secret"

    def test_403_returns_false(self):
        """403 Forbidden returns False."""
        config = {
            "notifications": {
                "ios_push": {
                    "worker_url": "https://push.monitorksef.com",
                    "instance_id": "uuid-123",
                    "instance_key": "key-456",
                }
            }
        }
        n = IosPushNotifier(config)
        n.session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        n.session.post.return_value = mock_resp

        result = n.send_notification("Title", "Body")
        assert result is False
