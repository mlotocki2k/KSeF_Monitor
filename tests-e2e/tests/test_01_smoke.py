"""
Smoke tests - sanity check ze aplikacja w ogole dziala.
Bez auth, szybkie, must-pass.

UWAGA: Aplikacja moze byc w trybie 'ui_public=True' (reverse proxy mode)
gdzie /ui/* sa dostepne bez sesji. Tylko /ui/account zawsze wymaga loginu.
Adaptujemy testy do faktycznego zachowania.
"""

from __future__ import annotations

import pytest
import requests
from playwright.sync_api import Page, expect


@pytest.mark.smoke
@pytest.mark.public
class TestHealthCheck:
    """API health endpoint."""

    def test_health_endpoint_returns_200(self, base_url: str):
        r = requests.get(f"{base_url}/api/v1/monitor/health", timeout=5)
        assert r.status_code == 200

    def test_health_response_shape(self, base_url: str):
        r = requests.get(f"{base_url}/api/v1/monitor/health", timeout=5)
        body = r.json()
        assert body.get("status") == "ok"
        assert "version" in body
        assert body.get("db_connected") is True

    def test_openapi_schema_either_available_or_blocked(self, base_url: str):
        """OpenAPI moze byc 200 (dev) lub 404 (prod, dobry security default)."""
        r = requests.get(f"{base_url}/openapi.json", timeout=5)
        assert r.status_code in (200, 404), f"Niespodziewany status: {r.status_code}"
        if r.status_code == 200:
            schema = r.json()
            assert schema.get("openapi", "").startswith("3.")


@pytest.mark.smoke
@pytest.mark.public
class TestRoutingBehavior:
    """Sprawdza faktyczne zachowanie routingu - nie zaklada redirectow."""

    def test_root_returns_known_status(self, base_url: str):
        """/ zwraca 401 (API) lub 303 (redirect) lub 200 (dashboard) - zalezy od trybu."""
        r = requests.get(f"{base_url}/", timeout=5, allow_redirects=False)
        assert r.status_code in (200, 303, 401, 404), \
            f"Niespodziewany status / : {r.status_code}"

    def test_ui_responds(self, base_url: str):
        """/ui zwraca 200 (dashboard, gdy ui_public) lub 303 (redirect na login)."""
        r = requests.get(f"{base_url}/ui", timeout=5, allow_redirects=False)
        assert r.status_code in (200, 303), f"Status: {r.status_code}"
        if r.status_code == 303:
            loc = r.headers.get("location", "")
            assert "/ui/login" in loc, f"Redirect na: {loc!r}"

    def test_ui_account_requires_auth(self, base_url: str):
        """/ui/account ZAWSZE wymaga loginu - jedyne na 100% chronione UI."""
        r = requests.get(f"{base_url}/ui/account", timeout=5, allow_redirects=False)
        assert r.status_code == 303, f"/ui/account powinno przekierowac. Status: {r.status_code}"
        loc = r.headers.get("location", "")
        assert "/ui/login" in loc, f"Redirect na: {loc!r} (oczekiwane /ui/login)"

    def test_login_page_renders(self, page: Page):
        page.goto("/ui/login")
        expect(page).to_have_title("Logowanie — Monitor KSeF")
        expect(page.locator("form[action='/ui/login']")).to_be_visible()
        expect(page.locator("input[name=username]")).to_be_visible()
        expect(page.locator("input[name=password]")).to_be_visible()
        expect(page.locator("button[type=submit]")).to_be_visible()

    def test_login_form_has_required_fields(self, page: Page):
        page.goto("/ui/login")
        username = page.locator("input[name=username]")
        password = page.locator("input[name=password]")
        assert username.get_attribute("required") is not None
        assert password.get_attribute("required") is not None
        assert password.get_attribute("type") == "password"
        assert username.get_attribute("autocomplete") == "username"
        assert password.get_attribute("autocomplete") == "current-password"

    def test_login_has_hidden_next_field(self, page: Page):
        page.goto("/ui/login")
        next_input = page.locator("input[name=next]")
        assert next_input.count() == 1
        # Default - powinien byc /ui
        assert next_input.get_attribute("value") == "/ui"

    def test_login_preserves_next_param(self, page: Page):
        """Przy GET /ui/login?next=/ui/invoices field 'next' powinien zachowac wartosc."""
        page.goto("/ui/login?next=/ui/invoices")
        next_input = page.locator("input[name=next]")
        val = next_input.get_attribute("value")
        # App moze sanityzowac - akceptujemy /ui/invoices albo /ui (default)
        assert val in ("/ui/invoices", "/ui"), f"next value: {val!r}"


@pytest.mark.smoke
@pytest.mark.public
class TestStaticAssets:
    """CSS, favicon, ikony dostepne."""

    @pytest.mark.parametrize("asset", [
        "/ui/static/tailwind.min.css",
        "/ui/static/favicon.png",
        "/ui/static/icon-64.png",
    ])
    def test_static_asset_loads(self, base_url: str, asset: str):
        r = requests.get(f"{base_url}{asset}", timeout=5)
        assert r.status_code == 200, f"{asset}: {r.status_code}"
        assert len(r.content) > 0


@pytest.mark.smoke
class TestNoConsoleErrorsOnLogin:
    """Login page - 0 console errors."""

    def test_no_js_errors_on_login_page(self, page: Page, console_capture: list):
        page.goto("/ui/login")
        page.wait_for_load_state("networkidle")
        errors = [m for m in console_capture if m["type"] in ("error", "pageerror")]
        assert not errors, f"Console errors: {errors}"

    def test_no_failed_requests_on_login(self, page: Page, network_capture: list):
        from urllib.parse import urlparse
        page.goto("/ui/login")
        page.wait_for_load_state("networkidle")
        # Match by exact host via urlparse (not substring — `in` would let
        # test.krzewiny.net.evil.example pass) or, for relative URLs with
        # no host, by /ui/ path. Closes CodeQL "Incomplete URL substring
        # sanitization" (#9).
        ours = []
        for r in network_capture:
            parsed = urlparse(r["url"])
            if parsed.hostname == "test.krzewiny.net":
                ours.append(r)
            elif not parsed.hostname and parsed.path.startswith("/ui/"):
                ours.append(r)
        assert not ours, f"Failed requests: {ours}"
