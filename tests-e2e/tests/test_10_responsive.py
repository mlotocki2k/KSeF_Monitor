"""
Responsive tests - mobile, tablet, desktop viewports.
Sprawdza ze:
- Strona renderuje sie bez horizontal scroll
- Wszystkie kluczowe elementy widoczne
- Brak overflow content
- Screenshots dla wizualnego review
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page


SCREENSHOTS_DIR = Path(__file__).parent.parent / "screenshots"

VIEWPORTS = {
    "mobile_iphone_se": {"width": 375, "height": 667},
    "mobile_iphone_14": {"width": 390, "height": 844},
    "tablet_ipad": {"width": 768, "height": 1024},
    "desktop_laptop": {"width": 1366, "height": 768},
    "desktop_full_hd": {"width": 1920, "height": 1080},
}


@pytest.mark.responsive
@pytest.mark.public
class TestResponsiveLogin:
    """Login page we wszystkich viewportach."""

    @pytest.mark.parametrize("viewport_name,viewport", list(VIEWPORTS.items()))
    def test_login_responsive(self, browser: Browser, base_url: str, viewport_name: str, viewport: dict):
        ctx = browser.new_context(base_url=base_url, viewport=viewport, ignore_https_errors=True)
        page = ctx.new_page()
        try:
            page.goto("/ui/login")
            page.wait_for_load_state("networkidle")

            # Screenshot
            SCREENSHOTS_DIR.mkdir(exist_ok=True, parents=True)
            page.screenshot(
                path=str(SCREENSHOTS_DIR / f"login_{viewport_name}.png"),
                full_page=True,
            )

            # Sprawdz brak horizontal scroll
            scroll_x = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert scroll_x <= 1, f"Horizontal scroll w {viewport_name}: {scroll_x}px"

            # Form widoczny
            form = page.locator("form[action='/ui/login']")
            assert form.is_visible(), f"Form niewidoczny w {viewport_name}"

            # Submit button widoczny
            submit = page.locator("button[type=submit]")
            assert submit.is_visible(), f"Submit niewidoczny w {viewport_name}"
        finally:
            ctx.close()


@pytest.mark.responsive
@pytest.mark.auth
class TestResponsiveAuthed:
    """Authed pages we wszystkich viewportach."""

    @pytest.mark.parametrize("path,name", [
        ("/ui", "dashboard"),
        ("/ui/invoices", "invoices"),
    ])
    @pytest.mark.parametrize("viewport_name,viewport", [
        ("mobile", {"width": 375, "height": 667}),
        ("desktop", {"width": 1440, "height": 900}),
    ])
    def test_responsive_screenshots(
        self,
        browser: Browser,
        auth_state,
        base_url: str,
        path: str,
        name: str,
        viewport_name: str,
        viewport: dict,
    ):
        if not auth_state:
            pytest.skip("Brak auth")

        ctx = browser.new_context(
            base_url=base_url,
            storage_state=auth_state,
            viewport=viewport,
            ignore_https_errors=True,
        )
        page = ctx.new_page()
        try:
            page.goto(path)
            page.wait_for_load_state("networkidle")

            SCREENSHOTS_DIR.mkdir(exist_ok=True, parents=True)
            page.screenshot(
                path=str(SCREENSHOTS_DIR / f"{name}_{viewport_name}.png"),
                full_page=True,
            )

            scroll_x = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert scroll_x <= 5, f"Horizontal scroll na {path} ({viewport_name}): {scroll_x}px"
        finally:
            ctx.close()
