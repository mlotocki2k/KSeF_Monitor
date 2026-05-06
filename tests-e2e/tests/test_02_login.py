"""
Login form tests - walidacja, blad credentials, edge cases.
Bez auth wymaganego (testujemy SAM login).
"""

from __future__ import annotations

import time

import pytest
import requests
from playwright.sync_api import Page, expect


@pytest.mark.public
class TestLoginValidation:
    """Walidacja formularza loginu."""

    def test_empty_form_blocked_by_html5(self, page: Page):
        page.goto("/ui/login")
        page.click("button[type=submit]")
        # HTML5 required - powinien zablokowac submit, dalej na /ui/login
        assert "/ui/login" in page.url

    def test_invalid_credentials_redirect_with_error(self, page: Page):
        """App po blednym loginie: 303 -> /ui/login?error=invalid"""
        page.goto("/ui/login")
        page.fill("input[name=username]", "nonexistent_user_xyz_aitester")
        page.fill("input[name=password]", "wrong_password_123")
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")

        # Po redirect powinien byc na /ui/login z error w query
        assert "/ui/login" in page.url, f"URL: {page.url}"
        # Komunikat o bledzie - albo w URL (?error=invalid) albo w body
        has_error_in_url = "error=" in page.url
        body_text = page.locator("body").inner_text().lower()
        has_error_in_body = any(kw in body_text for kw in [
            "blad", "błąd", "nieprawidlowe", "nieprawidłowe",
            "invalid", "incorrect", "niepoprawne",
        ])
        assert has_error_in_url or has_error_in_body, \
            f"Brak indykatora bledu. URL: {page.url}, body: {body_text[:200]}"

    def test_invalid_credentials_no_session_cookie(self, base_url: str):
        """Po blednym loginie sesja NIE powstaje."""
        s = requests.Session()
        r = s.post(
            f"{base_url}/ui/login",
            data={"username": "fake_user", "password": "fake_pass", "next": "/ui"},
            allow_redirects=False,
            timeout=5,
        )
        # 303 redirect na error
        assert r.status_code == 303
        loc = r.headers.get("location", "")
        assert "error" in loc, f"Brak error w Location: {loc}"
        # Nie powinno byc Set-Cookie z mksef_session
        cookies = [c for c in s.cookies if c.name == "mksef_session"]
        assert not cookies, "Sesja powstala mimo zlych credentials!"

    def test_login_form_action_post(self, page: Page):
        page.goto("/ui/login")
        form = page.locator("form").first
        assert form.get_attribute("method").lower() == "post"
        assert form.get_attribute("action") == "/ui/login"


@pytest.mark.public
@pytest.mark.security
class TestLoginSecurity:
    """Security loginu - XSS, SQLi, CSRF, headers."""

    def test_xss_in_username_not_executed(self, page: Page, console_capture: list):
        page.goto("/ui/login")
        page.fill("input[name=username]", "<script>window.__pwned=true</script>")
        page.fill("input[name=password]", "x")
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")

        # Nie powinno byc executed
        pwned = page.evaluate("() => window.__pwned === true")
        assert not pwned, "XSS executed! Critical security issue"

    def test_sql_injection_in_username_safe(self, page: Page):
        page.goto("/ui/login")
        page.fill("input[name=username]", "admin' OR '1'='1")
        page.fill("input[name=password]", "anything")
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")

        # Nie zaloguje sie - powinien zostac na loginie
        assert "/ui/login" in page.url

    def test_security_headers_on_login(self, base_url: str):
        r = requests.get(f"{base_url}/ui/login", timeout=5)
        headers = {k.lower(): v for k, v in r.headers.items()}

        # FastAPI/Starlette + middleware - sprawdz najwazniejsze
        # X-Content-Type-Options nosniff
        assert headers.get("x-content-type-options", "").lower() == "nosniff", \
            f"Brak X-Content-Type-Options: nosniff. Headers: {dict(r.headers)}"

    def test_session_cookie_is_httponly(self, base_url: str):
        """Po nieudanym loginie nie powinno byc sesji, ale po setup powinno."""
        s = requests.Session()
        r = s.get(f"{base_url}/ui/login", timeout=5)
        # Sprawdz tylko czy ew. cookies sa httponly - jak sie pojawi mksef_session
        for c in s.cookies:
            if c.name == "mksef_session":
                # python requests nie ma direct httponly check, sprawdzamy raw
                # nazwa pola: rest['HttpOnly'] w cookie._rest
                assert c._rest.get("HttpOnly") is not None or c.has_nonstandard_attr("HttpOnly"), \
                    "mksef_session NIE jest HttpOnly!"


@pytest.mark.public
@pytest.mark.destructive
@pytest.mark.slow
class TestLoginRateLimit:
    """Rate limit: 5 prob/min na /ui/login."""

    def test_rate_limit_kicks_in_after_5_attempts(self, base_url: str):
        s = requests.Session()
        # 6 prob - 6ta powinna dostac 429
        last_status = 200
        for i in range(7):
            r = s.post(
                f"{base_url}/ui/login",
                data={"username": f"ratelimit_test_{i}", "password": "x", "next": "/ui"},
                allow_redirects=False,
                timeout=5,
            )
            last_status = r.status_code
            if r.status_code == 429:
                break
            time.sleep(0.1)

        assert last_status == 429, \
            f"Po 7 probach rate limit nie zadzialal. Last: {last_status}"
