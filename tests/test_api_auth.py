"""
Tests for API authentication — Bearer token auth with hmac.compare_digest.

Covers:
- No token configured = open access
- Missing/invalid/correct token
- Health endpoint exempt from auth
- Docs endpoints exempt from auth
"""

import pytest
from fastapi.testclient import TestClient

from app.api import create_app


@pytest.fixture
def app_open():
    """App without auth token (open access)."""
    return create_app(db=None, auth_token=None)


@pytest.fixture
def app_auth():
    """App with auth token configured."""
    return create_app(db=None, auth_token="a" * 32)


@pytest.fixture
def client_open(app_open):
    return TestClient(app_open)


@pytest.fixture
def client_auth(app_auth):
    return TestClient(app_auth)


class TestOpenAccess:
    """When auth_token is None, all endpoints are accessible."""

    def test_health_accessible(self, client_open):
        resp = client_open.get("/api/v1/monitor/health")
        assert resp.status_code == 200

    def test_invoices_accessible_without_db(self, client_open):
        resp = client_open.get("/api/v1/invoices")
        # 503 because db=None, not 401
        assert resp.status_code == 503

    def test_stats_accessible_without_db(self, client_open):
        resp = client_open.get("/api/v1/stats/summary")
        assert resp.status_code == 503


class TestTokenAuth:
    """When auth_token is set, endpoints require Bearer token."""

    def test_health_exempt_from_auth(self, client_auth):
        """Health endpoint accessible without token."""
        resp = client_auth.get("/api/v1/monitor/health")
        assert resp.status_code == 200

    def test_docs_exempt_from_auth(self, client_auth):
        """Swagger docs accessible without token."""
        resp = client_auth.get("/docs")
        assert resp.status_code == 200

    def test_missing_auth_header_returns_401(self, client_auth):
        resp = client_auth.get("/api/v1/invoices")
        assert resp.status_code == 401
        assert "Authorization" in resp.json()["detail"]

    def test_wrong_auth_scheme_returns_401(self, client_auth):
        resp = client_auth.get(
            "/api/v1/invoices",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert resp.status_code == 401

    def test_wrong_token_returns_401(self, client_auth):
        resp = client_auth.get(
            "/api/v1/invoices",
            headers={"Authorization": "Bearer wrong-token-value"},
        )
        assert resp.status_code == 401
        assert "Invalid" in resp.json()["detail"]

    def test_correct_token_grants_access(self, client_auth):
        """Correct token passes auth (503 from missing DB, not 401)."""
        resp = client_auth.get(
            "/api/v1/invoices",
            headers={"Authorization": "Bearer " + "a" * 32},
        )
        # Should be 503 (no db), not 401
        assert resp.status_code == 503

    def test_post_trigger_requires_auth(self, client_auth):
        resp = client_auth.post("/api/v1/monitor/trigger")
        assert resp.status_code == 401

    def test_post_trigger_with_token(self, client_auth):
        resp = client_auth.post(
            "/api/v1/monitor/trigger",
            headers={"Authorization": "Bearer " + "a" * 32},
        )
        # Not 401 — monitor not available returns 200 with triggered=false
        assert resp.status_code == 200


class TestSecurityHeaders:
    """Security headers present on all responses (V5-05)."""

    def test_nosniff_header(self, client_open):
        resp = client_open.get("/api/v1/monitor/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_frame_deny_header(self, client_open):
        resp = client_open.get("/api/v1/monitor/health")
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_cache_control_header(self, client_open):
        resp = client_open.get("/api/v1/monitor/health")
        assert resp.headers.get("Cache-Control") == "no-store"

    def test_security_headers_on_auth_failure(self, client_auth):
        """Security headers present even on 401 responses."""
        resp = client_auth.get("/api/v1/invoices")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_xcto_nosniff(self, client_open):
        resp = client_open.get("/api/v1/monitor/health")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"

    def test_xfo_deny(self, client_open):
        resp = client_open.get("/api/v1/monitor/health")
        assert resp.headers["X-Frame-Options"] == "DENY"

    def test_csp_default_self(self, client_open):
        resp = client_open.get("/api/v1/monitor/health")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_hsts_max_age(self, client_open):
        resp = client_open.get("/api/v1/monitor/health")
        hsts = resp.headers.get("Strict-Transport-Security", "")
        assert "max-age=" in hsts
        assert "includeSubDomains" in hsts

    def test_referrer_policy(self, client_open):
        resp = client_open.get("/api/v1/monitor/health")
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client_open):
        resp = client_open.get("/api/v1/monitor/health")
        pp = resp.headers.get("Permissions-Policy", "")
        assert "geolocation=()" in pp


class TestGenericErrorHandler:
    """Internal errors return generic message, no stack trace."""

    def test_500_response_is_generic(self, app_open):
        """Unhandled exception returns generic error, not stack trace."""

        @app_open.get("/api/v1/test-error")
        def raise_error():
            raise RuntimeError("secret internal detail")

        client = TestClient(app_open, raise_server_exceptions=False)
        resp = client.get("/api/v1/test-error")
        assert resp.status_code == 500
        body = resp.json()
        assert body["detail"] == "Internal server error"
        assert "secret" not in str(body)


class TestUiAuth:
    """V5-01 + V5-12: UI routes redirect to /ui/login when unauthenticated."""

    def test_ui_redirects_to_login(self, app_auth):
        """GET /ui without auth should 303 to /ui/login."""
        client = TestClient(app_auth, follow_redirects=False)
        resp = client.get("/ui")
        assert resp.status_code == 303
        assert resp.headers["location"].startswith("/ui/login")

    def test_ui_invoices_redirects_to_login(self, app_auth):
        client = TestClient(app_auth, follow_redirects=False)
        resp = client.get("/ui/invoices")
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_ui_push_redirects_to_login(self, app_auth):
        client = TestClient(app_auth, follow_redirects=False)
        resp = client.get("/ui/push")
        assert resp.status_code == 303

    def test_ui_accessible_with_bearer(self, app_auth):
        """Bearer header still works (integrations / curl)."""
        client = TestClient(app_auth, raise_server_exceptions=False)
        resp = client.get(
            "/ui", headers={"Authorization": f"Bearer {'a' * 32}"}
        )
        assert resp.status_code != 401
        assert resp.status_code != 303

    def test_invoice_pdf_requires_auth(self, client_auth):
        """V5-03: /invoices/{ksef}/pdf must not bypass auth."""
        resp = client_auth.get(
            "/api/v1/invoices/1234567890-20260101-ABCDEF-01/pdf"
        )
        assert resp.status_code == 401

    def test_invoice_xml_requires_auth(self, client_auth):
        resp = client_auth.get(
            "/api/v1/invoices/1234567890-20260101-ABCDEF-01/xml"
        )
        assert resp.status_code == 401

    def test_push_devices_requires_auth(self, client_auth):
        resp = client_auth.get("/api/v1/push/devices")
        assert resp.status_code == 401

    def test_ksef_status_requires_auth(self, client_auth):
        resp = client_auth.get("/api/v1/monitor/ksef-status")
        assert resp.status_code == 401


class TestUiCookieSession:
    """V5-12: HttpOnly cookie session for browser UI."""

    TOKEN = "a" * 32

    def test_login_form_public(self, client_auth):
        """GET /ui/login is accessible without auth."""
        resp = client_auth.get("/ui/login")
        assert resp.status_code == 200
        assert "Token" in resp.text

    def test_login_with_correct_token_sets_cookie(self, app_auth):
        client = TestClient(app_auth, follow_redirects=False)
        resp = client.post("/ui/login", data={"token": self.TOKEN, "next": "/ui"})
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui"
        cookie = resp.cookies.get("mksef_session")
        assert cookie == self.TOKEN

    def test_login_with_wrong_token_redirects_with_error(self, app_auth):
        client = TestClient(app_auth, follow_redirects=False)
        resp = client.post("/ui/login", data={"token": "wrong", "next": "/ui"})
        assert resp.status_code == 303
        assert "error=invalid" in resp.headers["location"]
        assert resp.cookies.get("mksef_session") is None

    def test_cookie_grants_ui_access(self, app_auth):
        client = TestClient(app_auth, raise_server_exceptions=False)
        client.cookies.set("mksef_session", self.TOKEN)
        resp = client.get("/ui")
        assert resp.status_code != 401
        assert resp.status_code != 303

    def test_cookie_grants_api_access(self, app_auth):
        """Cookie also authorizes API endpoints (browser fetch from UI)."""
        client = TestClient(app_auth)
        client.cookies.set("mksef_session", self.TOKEN)
        resp = client.get("/api/v1/monitor/ksef-status")
        assert resp.status_code != 401

    def test_wrong_cookie_value_rejected(self, app_auth):
        client = TestClient(app_auth, follow_redirects=False)
        client.cookies.set("mksef_session", "wrong")
        resp = client.get("/ui")
        assert resp.status_code == 303

    def test_logout_clears_cookie_and_redirects(self, app_auth):
        client = TestClient(app_auth, follow_redirects=False)
        client.cookies.set("mksef_session", self.TOKEN)
        resp = client.post("/ui/logout")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/login"
        set_cookie = resp.headers.get("set-cookie", "")
        assert "mksef_session" in set_cookie
        assert ("Max-Age=0" in set_cookie) or ('expires=' in set_cookie.lower())

    def test_login_next_redirect_safe(self, app_auth):
        """next= parameter must be restricted to /ui paths (open-redirect guard)."""
        client = TestClient(app_auth, follow_redirects=False)
        resp = client.post(
            "/ui/login",
            data={"token": self.TOKEN, "next": "https://evil.example/x"},
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui"

    def test_login_protocol_relative_next_rejected(self, app_auth):
        client = TestClient(app_auth, follow_redirects=False)
        resp = client.post(
            "/ui/login", data={"token": self.TOKEN, "next": "//evil.example"}
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui"

    def test_cookie_is_httponly(self, app_auth):
        client = TestClient(app_auth, follow_redirects=False)
        resp = client.post("/ui/login", data={"token": self.TOKEN})
        set_cookie = resp.headers.get("set-cookie", "").lower()
        assert "httponly" in set_cookie
        assert "samesite=strict" in set_cookie

    def test_login_endpoint_exempt_from_auth(self, client_auth):
        """Even with auth required, /ui/login GET stays public."""
        resp = client_auth.get("/ui/login")
        assert resp.status_code == 200

    def test_login_redirects_to_ui_when_no_auth_configured(self, app_open):
        """If server has no auth_token, /ui/login just bounces to /ui."""
        client = TestClient(app_open, follow_redirects=False)
        resp = client.get("/ui/login")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui"


class TestUiPublicOptIn:
    """V5-01: api.ui_public=True lets UI bypass auth (legacy/reverse-proxy mode)."""

    def test_ui_public_opt_in_allows_ui(self):
        from app.api import create_app
        from fastapi.testclient import TestClient
        app = create_app(auth_token="a" * 32, ui_public=True)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/ui")
        # UI may 500 (template error, no db) — but NOT 401
        assert resp.status_code != 401

    def test_ui_public_still_protects_api(self):
        """ui_public must NOT widen the bypass beyond /ui."""
        from app.api import create_app
        from fastapi.testclient import TestClient
        app = create_app(auth_token="a" * 32, ui_public=True)
        client = TestClient(app)
        resp = client.get("/api/v1/push/devices")
        assert resp.status_code == 401
        resp2 = client.get("/api/v1/invoices/1-1-1-1/pdf")
        assert resp2.status_code == 401
