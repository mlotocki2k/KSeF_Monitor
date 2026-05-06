"""
Auth flow - testy wymagajace zalogowanej sesji.
Login -> dashboard -> nawigacja -> logout.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.auth
class TestDashboard:
    """Dashboard - strona glowna po zalogowaniu."""

    def test_dashboard_loads(self, authed_page: Page):
        import re
        authed_page.goto("/ui")
        # Nie powinno przekierowac na login
        expect(authed_page).not_to_have_url(re.compile(r"/ui/login"))
        expect(authed_page.locator("body")).to_be_visible()

    def test_dashboard_title_contains_ksef(self, authed_page: Page):
        authed_page.goto("/ui")
        title = authed_page.title()
        assert "KSeF" in title or "Monitor" in title, f"Unexpected title: {title}"

    def test_dashboard_has_navigation(self, authed_page: Page):
        authed_page.goto("/ui")
        # Powinny byc linki do innych sekcji
        body = authed_page.locator("body").inner_text().lower()
        # Co najmniej jeden z tych terminow powinien byc na dashboardzie
        nav_keywords = ["faktur", "invoice", "konto", "wyloguj", "monitor"]
        assert any(kw in body for kw in nav_keywords), \
            f"Brak nawigacji. Body: {body[:500]}"

    def test_no_console_errors_on_dashboard(self, authed_page: Page):
        msgs: list[dict] = []
        authed_page.on("console", lambda m: msgs.append({"type": m.type, "text": m.text}))
        authed_page.on("pageerror", lambda e: msgs.append({"type": "pageerror", "text": str(e)}))

        authed_page.goto("/ui")
        authed_page.wait_for_load_state("networkidle")

        errors = [m for m in msgs if m["type"] in ("error", "pageerror")]
        assert not errors, f"Console errors: {errors}"


@pytest.mark.auth
class TestNavigation:
    """Nawigacja miedzy stronami po zalogowaniu."""

    @pytest.mark.parametrize("path,must_contain_one_of", [
        ("/ui", ["dashboard", "monitor", "faktur"]),
        ("/ui/invoices", ["faktur", "invoice", "lista"]),
        ("/ui/initial-load", ["import", "load", "historic"]),
        ("/ui/account", ["konto", "account", "haslo", "hasło"]),
        ("/ui/push", ["push", "ios", "powiadom", "qr"]),
    ])
    def test_protected_pages_load(self, authed_page: Page, path: str, must_contain_one_of: list[str]):
        authed_page.goto(path)
        authed_page.wait_for_load_state("networkidle")

        assert "/ui/login" not in authed_page.url, \
            f"Niespodziewany redirect na login dla {path}"

        body = authed_page.locator("body").inner_text().lower()
        assert any(kw in body for kw in must_contain_one_of), \
            f"{path}: brak oczekiwanej tresci. Body: {body[:300]}"


@pytest.mark.auth
@pytest.mark.destructive
class TestLogout:
    """Logout flow."""

    def test_logout_clears_session(self, authed_page: Page):
        authed_page.goto("/ui")

        # Znajdz form/button do logoutu
        logout_form = authed_page.locator("form[action*='logout']").first
        if logout_form.count() > 0:
            logout_form.locator("button[type=submit]").first.click()
        else:
            # Fallback - POST bezposrednio
            authed_page.evaluate("""
                fetch('/ui/logout', {method: 'POST', credentials: 'include'})
            """)
            authed_page.goto("/ui")

        authed_page.wait_for_load_state("networkidle")
        # Po logout - dostep do /ui powinien przekierowac na login
        authed_page.goto("/ui")
        authed_page.wait_for_url("**/ui/login**", timeout=5000)
        assert "/ui/login" in authed_page.url


@pytest.mark.auth
class TestSessionPersistence:
    """Sesja persystuje miedzy zadaniami w tej samej karcie."""

    def test_session_works_across_pages(self, authed_page: Page):
        for path in ["/ui", "/ui/invoices", "/ui/account", "/ui"]:
            authed_page.goto(path)
            authed_page.wait_for_load_state("networkidle")
            assert "/ui/login" not in authed_page.url, \
                f"Sesja zgubiona przy nawigacji do {path}"
