"""
Account page - zmiana hasla.
UWAGA: zmiana hasla loguje wszystkie sesje. Domyslnie SKIPPED chyba ze
KSEF_RUN_DESTRUCTIVE=true.
"""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.auth
class TestAccountPage:
    """Strona ustawien konta - bez modyfikacji."""

    def test_account_page_loads(self, authed_page: Page):
        authed_page.goto("/ui/account")
        authed_page.wait_for_load_state("networkidle")
        assert "/ui/login" not in authed_page.url

    def test_password_change_form_present(self, authed_page: Page):
        authed_page.goto("/ui/account")
        authed_page.wait_for_load_state("networkidle")

        has_current = authed_page.locator("input[name=current_password]").count() > 0
        has_new = authed_page.locator("input[name=new_password]").count() > 0
        assert has_current and has_new, "Brak formularza zmiany hasla"

    def test_password_inputs_are_type_password(self, authed_page: Page):
        authed_page.goto("/ui/account")
        for name in ["current_password", "new_password", "new_password_confirm"]:
            inp = authed_page.locator(f"input[name={name}]")
            if inp.count() > 0:
                assert inp.first.get_attribute("type") == "password", \
                    f"{name} ma type != password!"


@pytest.mark.auth
@pytest.mark.destructive
class TestPasswordChange:
    """ZMIENIA HASLO. Tylko gdy KSEF_RUN_DESTRUCTIVE=true.

    Test:
    1. Zmienia haslo na nowe
    2. Sprawdza ze stara sesja inwalidowana
    3. Loguje sie nowym haslem
    4. Przywraca stare haslo
    """

    def test_change_password_full_cycle(self, authed_page: Page, browser, base_url: str):
        old_pass = os.environ.get("KSEF_TEST_PASS")
        new_pass = f"{old_pass}_NEW_TEMP_2024"

        authed_page.goto("/ui/account")
        authed_page.fill("input[name=current_password]", old_pass)
        authed_page.fill("input[name=new_password]", new_pass)
        if authed_page.locator("input[name=new_password_confirm]").count() > 0:
            authed_page.fill("input[name=new_password_confirm]", new_pass)
        authed_page.click("button[type=submit]")
        authed_page.wait_for_load_state("networkidle")

        # Powinno wylogowac
        authed_page.goto("/ui")
        authed_page.wait_for_url("**/ui/login**", timeout=5000)

        # Loguje sie nowym haslem
        ctx = browser.new_context(base_url=base_url, ignore_https_errors=True)
        new_page = ctx.new_page()
        new_page.goto("/ui/login")
        new_page.fill("input[name=username]", os.environ["KSEF_TEST_USER"])
        new_page.fill("input[name=password]", new_pass)
        new_page.click("button[type=submit]")
        new_page.wait_for_url(lambda u: "/ui/login" not in u, timeout=5000)

        # Cofa zmiana - przywraca stare
        new_page.goto("/ui/account")
        new_page.fill("input[name=current_password]", new_pass)
        new_page.fill("input[name=new_password]", old_pass)
        if new_page.locator("input[name=new_password_confirm]").count() > 0:
            new_page.fill("input[name=new_password_confirm]", old_pass)
        new_page.click("button[type=submit]")
        new_page.wait_for_load_state("networkidle")

        ctx.close()
