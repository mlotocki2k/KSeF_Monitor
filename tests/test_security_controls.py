"""
Unit tests for security controls introduced by the security audit.
Covers: email HTML escaping, SSRF redirect blocking, auth failure metrics callback.
"""

import pytest
from unittest.mock import MagicMock, patch

from app.notifiers.email_notifier import EmailNotifier
from app.notifiers.discord_notifier import DiscordNotifier
from app.notifiers.slack_notifier import SlackNotifier


# --- Email HTML Escaping (F-04) ---

class TestEmailHTMLEscaping:
    """Verify that email fallback renderer escapes HTML in user-controlled fields."""

    def _make_notifier(self):
        config = {
            "notifications": {
                "email": {
                    "smtp_server": "smtp.example.com",
                    "smtp_port": 587,
                    "username": "test@example.com",
                    "password": "secret",
                    "from_address": "test@example.com",
                    "to_addresses": ["dest@example.com"],
                }
            }
        }
        return EmailNotifier(config)

    def test_title_html_escaped(self):
        """HTML tags in title are escaped, not rendered."""
        notifier = self._make_notifier()
        html = notifier._create_html_message(
            title='<script>alert("xss")</script>',
            message="Normal message",
            priority=0,
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_message_html_escaped(self):
        """HTML tags in message body are escaped."""
        notifier = self._make_notifier()
        html = notifier._create_html_message(
            title="Normal title",
            message='<img src=x onerror="fetch(evil)">',
            priority=0,
        )
        assert "<img" not in html
        assert "&lt;img" in html

    def test_url_quotes_escaped(self):
        """Quotes in URL are escaped to &quot; preventing attribute breakout."""
        notifier = self._make_notifier()
        html = notifier._create_html_message(
            title="Title",
            message="Message",
            priority=0,
            url='https://evil.com" onclick="alert(1)',
        )
        # Quotes are escaped — in HTML5, &quot; inside double-quoted attr does NOT close it
        assert "&quot;" in html
        # The raw literal " onclick=" must not appear unescaped
        assert '" onclick="' not in html

    def test_newlines_converted_to_br(self):
        """Newlines in message become <br> tags."""
        notifier = self._make_notifier()
        html = notifier._create_html_message(
            title="Title",
            message="Line 1\nLine 2",
            priority=0,
        )
        assert "<br>" in html

    def test_ampersand_in_title_escaped(self):
        """Ampersand in title is properly escaped."""
        notifier = self._make_notifier()
        html = notifier._create_html_message(
            title="Firma A & B",
            message="msg",
            priority=0,
        )
        assert "Firma A &amp; B" in html


# --- SSRF Redirect Blocking (N-03) ---

class TestDiscordRedirectBlocking:
    """Verify Discord notifier disables HTTP redirects."""

    def _make_notifier(self):
        config = {
            "notifications": {
                "discord": {
                    "webhook_url": "https://discord.com/api/webhooks/123/abc",
                }
            }
        }
        return DiscordNotifier(config)

    @patch("app.notifiers.discord_notifier.BaseNotifier.__init__", return_value=None)
    def test_send_notification_no_redirects(self, mock_init):
        """send_notification passes allow_redirects=False."""
        notifier = self._make_notifier()
        notifier.session = MagicMock()
        notifier.session.post.return_value = MagicMock(status_code=204, raise_for_status=MagicMock())

        notifier.send_notification("Title", "Message")

        _, kwargs = notifier.session.post.call_args
        assert kwargs.get("allow_redirects") is False

    @patch("app.notifiers.discord_notifier.BaseNotifier.__init__", return_value=None)
    def test_send_rendered_no_redirects(self, mock_init):
        """_send_rendered passes allow_redirects=False."""
        notifier = self._make_notifier()
        notifier.session = MagicMock()
        notifier.session.post.return_value = MagicMock(status_code=204, raise_for_status=MagicMock())

        notifier._send_rendered('{"title": "Test", "description": "msg", "color": 0}', {"title": "Test"})

        _, kwargs = notifier.session.post.call_args
        assert kwargs.get("allow_redirects") is False


class TestSlackRedirectBlocking:
    """Verify Slack notifier disables HTTP redirects."""

    def _make_notifier(self):
        config = {
            "notifications": {
                "slack": {
                    "webhook_url": "https://hooks.slack.com/services/T00/B00/xxx",
                }
            }
        }
        return SlackNotifier(config)

    @patch("app.notifiers.slack_notifier.BaseNotifier.__init__", return_value=None)
    def test_send_notification_no_redirects(self, mock_init):
        """send_notification passes allow_redirects=False."""
        notifier = self._make_notifier()
        notifier.session = MagicMock()
        notifier.session.post.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())

        notifier.send_notification("Title", "Message")

        _, kwargs = notifier.session.post.call_args
        assert kwargs.get("allow_redirects") is False

    @patch("app.notifiers.slack_notifier.BaseNotifier.__init__", return_value=None)
    def test_send_rendered_no_redirects(self, mock_init):
        """_send_rendered passes allow_redirects=False."""
        notifier = self._make_notifier()
        notifier.session = MagicMock()
        notifier.session.post.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())

        notifier._send_rendered('{"text": "test"}', {"title": "Test"})

        _, kwargs = notifier.session.post.call_args
        assert kwargs.get("allow_redirects") is False


# --- Auth Failure Metrics Callback (N-02) ---

class TestAuthFailureCallback:
    """Verify KSeFClient.on_auth_failure callback fires on auth failure."""

    def test_on_auth_failure_called_on_401_reauth_failure(self):
        """Callback fires when _handle_401_refresh exhausts all retry paths."""
        from app.ksef_client import KSeFClient

        config = MagicMock()
        config.get.side_effect = lambda *a, **kw: {
            ("ksef", "environment"): "test",
            ("ksef", "nip"): "1234567890",
            ("ksef", "token"): "test-token",
            ("monitoring", "date_type"): "Invoicing",
        }.get(a, kw.get("default"))

        client = KSeFClient(config)
        callback = MagicMock()
        client.on_auth_failure = callback

        # Mock both refresh and authenticate to fail
        client.refresh_access_token = MagicMock(return_value=False)
        client.authenticate = MagicMock(return_value=False)

        mock_response = MagicMock()
        mock_response.status_code = 401

        result = client._handle_401_refresh(mock_response)

        assert result is False
        callback.assert_called_once_with(401)

    def test_on_auth_failure_not_called_on_success(self):
        """Callback does NOT fire when refresh succeeds."""
        from app.ksef_client import KSeFClient

        config = MagicMock()
        config.get.side_effect = lambda *a, **kw: {
            ("ksef", "environment"): "test",
            ("ksef", "nip"): "1234567890",
            ("ksef", "token"): "test-token",
            ("monitoring", "date_type"): "Invoicing",
        }.get(a, kw.get("default"))

        client = KSeFClient(config)
        callback = MagicMock()
        client.on_auth_failure = callback

        # Mock refresh to succeed
        client.refresh_access_token = MagicMock(return_value=True)

        mock_response = MagicMock()
        mock_response.status_code = 401

        result = client._handle_401_refresh(mock_response)

        assert result is True
        callback.assert_not_called()

    def test_on_auth_failure_called_on_initial_auth_exception(self):
        """Callback fires when authenticate() raises an exception."""
        from app.ksef_client import KSeFClient

        config = MagicMock()
        config.get.side_effect = lambda *a, **kw: {
            ("ksef", "environment"): "test",
            ("ksef", "nip"): "1234567890",
            ("ksef", "token"): "test-token",
            ("monitoring", "date_type"): "Invoicing",
        }.get(a, kw.get("default"))

        client = KSeFClient(config)
        callback = MagicMock()
        client.on_auth_failure = callback

        # Mock _get_challenge to raise an exception (simulating initial auth failure)
        client._get_challenge = MagicMock(side_effect=Exception("connection refused"))

        result = client.authenticate()

        assert result is False
        callback.assert_called_once_with(0)
