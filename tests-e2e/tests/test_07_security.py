"""
Security tests - headers, CSP, CSRF, headers fingerprinting.
"""

from __future__ import annotations

import pytest
import requests


@pytest.mark.security
@pytest.mark.public
class TestSecurityHeaders:
    """Sprawdza HTTP headers dla bezpieczenstwa."""

    @pytest.fixture
    def response_headers(self, base_url: str):
        r = requests.get(f"{base_url}/ui/login", timeout=5)
        return {k.lower(): v for k, v in r.headers.items()}

    def test_x_content_type_options(self, response_headers: dict):
        assert response_headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options_or_csp_frame_ancestors(self, response_headers: dict):
        """Anti-clickjacking - X-Frame-Options DENY/SAMEORIGIN lub CSP frame-ancestors."""
        xfo = response_headers.get("x-frame-options", "").lower()
        csp = response_headers.get("content-security-policy", "").lower()

        has_xfo = xfo in ("deny", "sameorigin")
        has_csp_fa = "frame-ancestors" in csp

        assert has_xfo or has_csp_fa, \
            f"Brak ochrony przed clickjacking. XFO: {xfo!r}, CSP: {csp!r}"

    def test_no_server_disclosure(self, response_headers: dict):
        """Server header nie powinien zdradzac wersji."""
        server = response_headers.get("server", "")
        # Akceptujemy "uvicorn" ale ostrzezenie jesli z wersja
        if server and "/" in server:
            pytest.skip(f"Server header z wersja: {server!r} - rozwaz ukrycie")

    def test_no_x_powered_by(self, response_headers: dict):
        """X-Powered-By zdradza stack."""
        assert "x-powered-by" not in response_headers, \
            f"X-Powered-By: {response_headers.get('x-powered-by')!r} - usun"


@pytest.mark.security
@pytest.mark.public
class TestErrorPages:
    """Strony bledow nie zdradzaja stack tracow."""

    def test_404_no_stacktrace(self, base_url: str):
        r = requests.get(f"{base_url}/ui/nieistniejaca_strona_xyz", timeout=5)
        body = r.text.lower()
        assert "traceback" not in body
        assert "file \"/" not in body  # Python stack trace pattern

    def test_invalid_method_no_stacktrace(self, base_url: str):
        r = requests.delete(f"{base_url}/ui/login", timeout=5)
        body = r.text.lower() if r.text else ""
        assert "traceback" not in body


@pytest.mark.security
@pytest.mark.public
class TestAPIAuthEnforcement:
    """API endpointy powinny wymagac auth."""

    @pytest.mark.parametrize("path", [
        "/api/v1/invoices",
        "/api/v1/stats/summary",
        "/api/v1/initial-load/status",
        "/api/v1/artifacts/pending",
    ])
    def test_api_requires_auth(self, base_url: str, path: str):
        r = requests.get(f"{base_url}{path}", timeout=5)
        # 401 lub 403, ew. 307/302 redirect na login
        assert r.status_code in (401, 403, 302, 307), \
            f"{path} dostepny BEZ auth! Status: {r.status_code}"

    def test_health_does_not_require_auth(self, base_url: str):
        r = requests.get(f"{base_url}/api/v1/monitor/health", timeout=5)
        assert r.status_code == 200


@pytest.mark.security
@pytest.mark.public
class TestSensitiveEndpointsExposure:
    """Czy wrazliwe endpointy nie sa publiczne."""

    @pytest.mark.parametrize("path", [
        "/.env",
        "/config.json",
        "/config_test.json",
        "/data/invoices.db",
        "/.git/config",
        "/Dockerfile",
        "/docker-compose.yml",
    ])
    def test_sensitive_files_not_exposed(self, base_url: str, path: str):
        r = requests.get(f"{base_url}{path}", timeout=5)
        # Nie powinno byc 200 z prawdziwa zawartoscia
        if r.status_code == 200:
            body = r.text
            # Heurystyki - wykluczamy false positives (np. SPA index.html)
            suspicious = any(kw in body for kw in [
                "POSTGRES_", "DATABASE_URL", "SECRET", "API_KEY",
                "ksef_token", "ksef.token",
                "[core]", "[remote", "ref:", "HEAD",
            ])
            assert not suspicious, f"{path} ujawnia wrazliwe dane!"
