"""
Conftest dla AI testera Monitor KSeF.

Fixtures:
- base_url: URL aplikacji (z env)
- auth_state: zalogowana sesja (cookies) - cached per session
- authed_page: Page z aktywna sesja
- console_capture: zbiera console errors podczas testu
- network_capture: zbiera failed requests
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv
from playwright.sync_api import Browser, BrowserContext, Page, Playwright


HERE = Path(__file__).parent
load_dotenv(HERE / ".env", override=False)

BASE_URL = os.environ.get("KSEF_BASE_URL", "http://test.krzewiny.net:8888").rstrip("/")
TEST_USER = os.environ.get("KSEF_TEST_USER", "")
TEST_PASS = os.environ.get("KSEF_TEST_PASS", "")
HEADED = os.environ.get("KSEF_HEADED", "false").lower() in ("1", "true", "yes")
SLOWMO = int(os.environ.get("KSEF_SLOWMO", "0"))
TIMEOUT = int(os.environ.get("KSEF_TIMEOUT", "10000"))
RUN_DESTRUCTIVE = os.environ.get("KSEF_RUN_DESTRUCTIVE", "false").lower() in ("1", "true", "yes")

AUTH_STATE_PATH = HERE / "reports" / ".auth-state.json"
SCREENSHOTS_DIR = HERE / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True, parents=True)


def pytest_configure(config: pytest.Config) -> None:
    """Pokazuje konfiguracje na starcie."""
    print(f"\n{'='*70}")
    print(f"AI Tester Monitor KSeF")
    print(f"{'='*70}")
    print(f"  BASE_URL:      {BASE_URL}")
    print(f"  TEST_USER:     {TEST_USER or '(brak - skipping auth tests)'}")
    print(f"  HEADED:        {HEADED}")
    print(f"  SLOWMO:        {SLOWMO}ms")
    print(f"  TIMEOUT:       {TIMEOUT}ms")
    print(f"  DESTRUCTIVE:   {RUN_DESTRUCTIVE}")
    print(f"{'='*70}\n")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-skip auth tests jesli brak credentials, destructive jesli flaga off."""
    skip_auth = pytest.mark.skip(reason="Brak KSEF_TEST_USER/KSEF_TEST_PASS w env (auth tests skipped)")
    skip_destructive = pytest.mark.skip(reason="KSEF_RUN_DESTRUCTIVE=false")

    creds_set = bool(TEST_USER and TEST_PASS)
    for item in items:
        if "auth" in item.keywords and not creds_set:
            item.add_marker(skip_auth)
        if "destructive" in item.keywords and not RUN_DESTRUCTIVE:
            item.add_marker(skip_destructive)


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def browser_type_launch_args() -> dict[str, Any]:
    return {
        "headless": not HEADED,
        "slow_mo": SLOWMO,
    }


@pytest.fixture(scope="session")
def browser_context_args(base_url: str) -> dict[str, Any]:
    return {
        "base_url": base_url,
        "ignore_https_errors": True,
        "viewport": {"width": 1440, "height": 900},
        "user_agent": "Mozilla/5.0 (compatible; KSeF-AI-Tester/1.0; +https://ksef-monitor)",
        "locale": "pl-PL",
        "timezone_id": "Europe/Warsaw",
    }


@pytest.fixture(scope="session")
def auth_state(browser: Browser, base_url: str) -> str | None:
    """
    Loguje raz na sesje, zapisuje cookies do JSON, pozniej re-uzywane.
    Zwraca sciezke do storage state lub None jesli brak credentials/login fail.

    Wazne: skip (nie raise) gdy login fail - ze KASKADA 40+ errors zamiast jednej.
    Failure jest jasnie zaraportowany do stdout.
    """
    if not (TEST_USER and TEST_PASS):
        return None

    context = browser.new_context(base_url=base_url, ignore_https_errors=True)
    page = context.new_page()
    page.set_default_timeout(TIMEOUT)

    try:
        page.goto(f"{base_url}/ui/login")
        page.fill("input[name=username]", TEST_USER)
        page.fill("input[name=password]", TEST_PASS)
        page.click("button[type=submit]")

        # Czekamy na navigation - bezpieczniej niz wait_for_url z lambda
        try:
            page.wait_for_url(
                lambda url: "/ui/login" not in url,
                timeout=5000,
            )
        except Exception:
            pass  # timeout - sprawdzimy URL ponizej

        if "/ui/login" in page.url:
            # Login failed - prawdopodobnie zle credentials
            current_url = page.url
            print(f"\n{'!'*70}")
            print(f"!!! LOGIN FAILED dla user={TEST_USER!r}")
            print(f"!!! URL po probie: {current_url}")
            if "error=" in current_url:
                print(f"!!! App zwrocila error w URL - credentials niepoprawne.")
            print(f"!!! Sprawdz .env: KSEF_TEST_USER, KSEF_TEST_PASS")
            print(f"!!! Wszystkie testy auth zostana SKIPPED.")
            print(f"{'!'*70}\n")
            context.close()
            return None

        context.storage_state(path=str(AUTH_STATE_PATH))
        context.close()
        return str(AUTH_STATE_PATH)
    except Exception as e:
        print(f"\n!!! Login crashed: {e}")
        try:
            context.close()
        except Exception:
            pass
        return None


@pytest.fixture
def authed_context(browser: Browser, auth_state: str | None, base_url: str) -> BrowserContext:
    """Context z zalogowana sesja."""
    if not auth_state:
        pytest.skip("Brak auth_state - skip auth-required test")

    context = browser.new_context(
        base_url=base_url,
        storage_state=auth_state,
        ignore_https_errors=True,
        viewport={"width": 1440, "height": 900},
        locale="pl-PL",
    )
    yield context
    context.close()


@pytest.fixture
def authed_page(authed_context: BrowserContext) -> Page:
    """Page z aktywna sesja, gotowa do nawigacji."""
    page = authed_context.new_page()
    page.set_default_timeout(TIMEOUT)
    yield page
    page.close()


@pytest.fixture
def console_capture(page: Page) -> list[dict[str, str]]:
    """Lapie wszystkie console.log/warn/error."""
    msgs: list[dict[str, str]] = []
    page.on("console", lambda msg: msgs.append({"type": msg.type, "text": msg.text, "url": page.url}))
    page.on("pageerror", lambda exc: msgs.append({"type": "pageerror", "text": str(exc), "url": page.url}))
    return msgs


@pytest.fixture
def network_capture(page: Page) -> list[dict[str, Any]]:
    """Lapie failed network requests (4xx, 5xx)."""
    failed: list[dict[str, Any]] = []

    def on_response(response):
        if response.status >= 400:
            failed.append({
                "url": response.url,
                "status": response.status,
                "method": response.request.method,
            })

    page.on("response", on_response)
    return failed


@pytest.fixture
def screenshot_on_failure(page: Page, request: pytest.FixtureRequest):
    """Auto-screenshot przy failure."""
    yield
    if request.node.rep_call.failed if hasattr(request.node, "rep_call") else False:
        path = SCREENSHOTS_DIR / f"FAIL_{request.node.name}_{int(time.time())}.png"
        page.screenshot(path=str(path), full_page=True)
        print(f"\n[FAIL screenshot] {path}")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Hook do propagacji wyniku do fixtures."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)
