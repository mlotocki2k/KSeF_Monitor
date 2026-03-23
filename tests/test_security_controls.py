"""
Unit tests for security controls introduced by the security audit.
Covers: email HTML escaping, SSRF redirect blocking, auth failure metrics callback.
"""

import os
import pytest
from unittest.mock import MagicMock, patch

from app.config_manager import ConfigManager
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


# --- P2 Security Fixes ---


class TestSandboxedEnvironment:
    """F-11: Verify Jinja2 SandboxedEnvironment is used."""

    def test_template_renderer_uses_sandbox(self):
        from jinja2.sandbox import SandboxedEnvironment
        from app.template_renderer import TemplateRenderer

        renderer = TemplateRenderer()
        assert isinstance(renderer.env, SandboxedEnvironment)

    def test_pdf_template_uses_sandbox(self, tmp_path):
        from jinja2.sandbox import SandboxedEnvironment
        from app.invoice_pdf_template import InvoicePDFTemplateRenderer

        renderer = InvoicePDFTemplateRenderer()
        assert isinstance(renderer.env, SandboxedEnvironment)

    def test_sandbox_blocks_ssti(self, tmp_path):
        """SandboxedEnvironment blocks __class__ access."""
        from jinja2.sandbox import SandboxedEnvironment, SecurityError
        from jinja2 import FileSystemLoader

        # Create a malicious template
        tmpl = tmp_path / "evil.txt"
        tmpl.write_text('{{ "".__class__.__mro__ }}')

        env = SandboxedEnvironment(loader=FileSystemLoader(str(tmp_path)))
        template = env.get_template("evil.txt")
        with pytest.raises(SecurityError):
            template.render()

    def test_sandbox_allows_normal_templates(self):
        """SandboxedEnvironment allows standard template constructs."""
        from app.template_renderer import TemplateRenderer

        renderer = TemplateRenderer()
        context = {
            "title": "Test Invoice",
            "ksef_number": "KSeF-123",
            "invoice_number": "FV/001",
            "issue_date": "2026-01-01",
            "seller_name": "Firma Sp. z o.o.",
            "seller_nip": "1234567890",
            "buyer_name": "Klient S.A.",
            "buyer_nip": "0987654321",
            "net_amount": 1000.00,
            "vat_amount": 230.00,
            "gross_amount": 1230.00,
            "currency": "PLN",
            "subject_type": "Subject2",
            "priority": 0,
        }
        result = renderer.render("pushover", context)
        assert result is not None
        assert "Firma Sp. z o.o." in result


class TestAuthTokenAutoGeneration:
    """F-01: Verify auth_token auto-generation when API enabled without token."""

    def test_auto_generates_when_empty(self):
        from app.config_manager import ConfigManager

        config = ConfigManager.__new__(ConfigManager)
        raw = {"api": {"enabled": True, "auth_token": ""}}
        config._apply_api_defaults(raw)
        token = raw["api"]["auth_token"]
        assert len(token) >= 32
        assert token != ""

    def test_preserves_user_token(self):
        from app.config_manager import ConfigManager

        config = ConfigManager.__new__(ConfigManager)
        raw = {"api": {"enabled": True, "auth_token": "my-custom-token-" + "x" * 32}}
        config._apply_api_defaults(raw)
        assert raw["api"]["auth_token"] == "my-custom-token-" + "x" * 32

    def test_no_generation_when_disabled(self):
        from app.config_manager import ConfigManager

        config = ConfigManager.__new__(ConfigManager)
        raw = {"api": {"enabled": False, "auth_token": ""}}
        config._apply_api_defaults(raw)
        assert raw["api"]["auth_token"] == ""

    def test_rate_limit_defaults_applied(self):
        from app.config_manager import ConfigManager

        config = ConfigManager.__new__(ConfigManager)
        raw = {"api": {}}
        config._apply_api_defaults(raw)
        assert raw["api"]["rate_limit"]["enabled"] is True
        assert raw["api"]["rate_limit"]["default"] == "60/minute"
        assert raw["api"]["rate_limit"]["trigger"] == "2/minute"


class TestSecretsManagerApiToken:
    """F-01: Verify API_AUTH_TOKEN injection via secrets_manager."""

    def test_api_auth_token_injected(self):
        from app.secrets_manager import SecretsManager

        sm = SecretsManager.__new__(SecretsManager)
        sm.get_secret = MagicMock(side_effect=lambda key: "test-api-token-xyz" if key == "API_AUTH_TOKEN" else None)

        config = {"api": {}}
        sm._inject_secrets(config)
        assert config["api"]["auth_token"] == "test-api-token-xyz"


class TestRateLimiting:
    """F-07: Verify rate limiting middleware integration."""

    def test_rate_limit_disabled_by_default(self):
        from app.api import create_app

        app = create_app()
        assert app.state.limiter.enabled is False

    def test_rate_limit_enabled_via_config(self):
        from app.api import create_app

        app = create_app(rate_limit_config={"enabled": True, "default": "10/minute"})
        assert app.state.limiter.enabled is True

    def test_rate_limit_429_when_exceeded(self):
        from fastapi.testclient import TestClient
        from app.api import create_app

        app = create_app(rate_limit_config={"enabled": True, "default": "2/minute"})
        client = TestClient(app)

        # Exhaust rate limit with 3 requests (limit is 2/min)
        responses = [client.get("/api/v1/stats/summary") for _ in range(3)]
        status_codes = [r.status_code for r in responses]
        assert 429 in status_codes, f"Expected 429 in {status_codes}"


# --- P3/P4 Security Fixes ---


class TestDocsDisabled:
    """F-02: Verify /docs, /redoc, /openapi.json can be disabled."""

    def test_docs_enabled_by_default(self):
        from fastapi.testclient import TestClient
        from app.api import create_app

        app = create_app()
        client = TestClient(app)
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_docs_disabled(self):
        from fastapi.testclient import TestClient
        from app.api import create_app

        app = create_app(docs_enabled=False)
        client = TestClient(app)
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404


class TestPrometheusBindAddress:
    """F-03: Verify Prometheus default bind is 127.0.0.1, not 0.0.0.0."""

    def test_default_bind_localhost(self):
        from app.prometheus_metrics import PrometheusMetrics
        import inspect

        sig = inspect.signature(PrometheusMetrics.__init__)
        default = sig.parameters["bind_address"].default
        assert default == "127.0.0.1"


class TestEmailCRLFInjection:
    """F-06: Verify CRLF stripping in email Subject header."""

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

    @patch("smtplib.SMTP")
    def test_crlf_stripped_from_subject(self, mock_smtp):
        notifier = self._make_notifier()
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        notifier.send_notification(
            title="Test\r\nBcc: attacker@evil.com",
            message="body",
        )

        # Verify sendmail was called (notification sent)
        mock_server.sendmail.assert_called_once()
        raw_msg = mock_server.sendmail.call_args[0][2]
        # Subject must not contain CRLF
        assert "\r\nBcc:" not in raw_msg.split("Subject:")[1].split("\n")[0]

    @patch("smtplib.SMTP")
    def test_newline_replaced_with_space(self, mock_smtp):
        notifier = self._make_notifier()
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        notifier.send_notification(title="Line1\nLine2", message="body")
        mock_server.sendmail.assert_called_once()
        raw_msg = mock_server.sendmail.call_args[0][2]
        # Subject line should contain "Line1 Line2" (newline replaced with space)
        assert "Line1 Line2" in raw_msg


class TestHealthInfoLeak:
    """F-09: Verify auth_enabled removed from health response."""

    def test_health_no_auth_enabled_field(self):
        from fastapi.testclient import TestClient
        from app.api import create_app

        app = create_app(auth_token="x" * 32)
        client = TestClient(app)
        resp = client.get("/api/v1/monitor/health")
        data = resp.json()
        assert "auth_enabled" not in data

    def test_health_response_schema_no_auth(self):
        from app.api.schemas import HealthResponse

        fields = HealthResponse.model_fields
        assert "auth_enabled" not in fields


class TestCORSWildcardRejection:
    """F-10: Verify CORS wildcard rejected when auth_token is set."""

    def test_wildcard_rejected_with_auth(self):
        from fastapi.testclient import TestClient
        from app.api import create_app

        app = create_app(auth_token="x" * 32, cors_origins=["*"])
        client = TestClient(app)
        # CORS preflight should NOT get Access-Control-Allow-Origin
        resp = client.options(
            "/api/v1/monitor/health",
            headers={"Origin": "https://evil.com", "Access-Control-Request-Method": "GET"},
        )
        assert "access-control-allow-origin" not in resp.headers

    def test_wildcard_allowed_without_auth(self):
        from fastapi.testclient import TestClient
        from app.api import create_app

        app = create_app(auth_token=None, cors_origins=["*"])
        client = TestClient(app)
        resp = client.get(
            "/api/v1/monitor/health",
            headers={"Origin": "https://example.com"},
        )
        assert resp.headers.get("access-control-allow-origin") == "*"

    def test_specific_origin_allowed_with_auth(self):
        from fastapi.testclient import TestClient
        from app.api import create_app

        app = create_app(auth_token="x" * 32, cors_origins=["https://myapp.com"])
        client = TestClient(app)
        resp = client.get(
            "/api/v1/monitor/health",
            headers={"Origin": "https://myapp.com"},
        )
        assert resp.headers.get("access-control-allow-origin") == "https://myapp.com"


# --- Re-audit Fixes (R-01, R-02, R-03) ---


def _minimal_config(**overrides):
    """Build a minimal valid config dict for ConfigManager tests."""
    base = {
        "ksef": {"nip": "1234567890", "token": "x", "environment": "test"},
        "monitoring": {},
        "schedule": {"mode": "minutes", "interval": 30},
    }
    for key, val in overrides.items():
        if isinstance(val, dict) and key in base and isinstance(base[key], dict):
            base[key].update(val)
        else:
            base[key] = val
    return base


class TestTokenLogTruncation:
    """R-01: Verify auto-generated auth token is not logged in full."""

    def test_token_logged_truncated(self):
        """Auto-generated token must be truncated to first 8 chars in log."""
        import json
        import tempfile

        config_data = _minimal_config(
            api={"enabled": True, "auth_token": ""},
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(config_data, f)
            f.flush()

            with patch("app.config_manager.logger") as mock_logger:
                cm = ConfigManager(f.name)
                token = cm.get("api", "auth_token")
                assert len(token) > 8, "Token should be longer than 8 chars"

                # Full token must NOT appear in any warning log
                warning_calls = [
                    str(call) for call in mock_logger.warning.call_args_list
                ]
                for call_str in warning_calls:
                    assert token not in call_str, (
                        "Full token must not appear in log"
                    )

                # Truncated form (first 8 chars) MUST appear
                truncated = token[:8]
                found_truncated = any(
                    truncated in str(call)
                    for call in mock_logger.warning.call_args_list
                )
                assert found_truncated, (
                    f"Truncated token '{truncated}...' not found in log"
                )

        os.unlink(f.name)

    def test_token_not_in_info_logs(self):
        """Full token must not appear in any info-level log either."""
        import json
        import tempfile

        config_data = _minimal_config(
            api={"enabled": True, "auth_token": ""},
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(config_data, f)
            f.flush()

            with patch("app.config_manager.logger") as mock_logger:
                cm = ConfigManager(f.name)
                token = cm.get("api", "auth_token")

                info_calls = [
                    str(call) for call in mock_logger.info.call_args_list
                ]
                for call_str in info_calls:
                    assert token not in call_str, (
                        "Full token must not appear in info logs"
                    )

        os.unlink(f.name)


class TestDocsAutoDisableProd:
    """R-02: Verify docs_enabled auto-disabled in production environment."""

    def test_docs_disabled_in_prod(self):
        """When ksef.environment == 'prod', docs_enabled defaults to False."""
        import json
        import tempfile

        config_data = _minimal_config(
            ksef={"nip": "1234567890", "token": "x", "environment": "prod"},
            api={"enabled": True},
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(config_data, f)
            f.flush()

            cm = ConfigManager(f.name)
            assert cm.get("api", "docs_enabled") is False

        os.unlink(f.name)

    def test_docs_enabled_in_test(self):
        """When ksef.environment == 'test', docs_enabled defaults to True."""
        import json
        import tempfile

        config_data = _minimal_config(
            api={"enabled": True},
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(config_data, f)
            f.flush()

            cm = ConfigManager(f.name)
            assert cm.get("api", "docs_enabled") is True

        os.unlink(f.name)

    def test_explicit_docs_enabled_overrides_prod(self):
        """Explicit docs_enabled=True in config overrides prod auto-disable."""
        import json
        import tempfile

        config_data = _minimal_config(
            ksef={"nip": "1234567890", "token": "x", "environment": "prod"},
            api={"enabled": True, "docs_enabled": True},
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(config_data, f)
            f.flush()

            cm = ConfigManager(f.name)
            assert cm.get("api", "docs_enabled") is True

        os.unlink(f.name)


class TestApiWiredInMain:
    """R-03: Verify REST API is wired into main.py startup."""

    def test_main_has_api_wiring(self):
        """main.py must contain API startup code: create_app, APIServer, conditional guard."""
        import inspect
        import main as main_module

        source = inspect.getsource(main_module.main)
        assert 'api_config.get("enabled")' in source
        assert "create_app" in source
        assert "APIServer" in source
        assert "api_server.start()" in source

    def test_api_import_works(self):
        """Verify create_app and APIServer can be imported as main.py does."""
        from app.api import create_app
        from app.api.server import APIServer

        assert callable(create_app)
        assert callable(APIServer)
