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
    """Security headers present on all responses."""

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
