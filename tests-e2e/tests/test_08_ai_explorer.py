"""
AI Explorer - automatyczny crawl wszystkich stron w aplikacji.
Wykrywa: 404, 500, console errors, failed requests, broken images.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page

from utils.explorer import crawl_app


REPORTS_DIR = Path(__file__).parent.parent / "reports"


@pytest.mark.explorer
@pytest.mark.auth
@pytest.mark.slow
class TestAIExplorer:
    """Crawl calej aplikacji jako zalogowany user."""

    def test_crawl_authenticated_app(self, authed_page: Page, base_url: str):
        report = crawl_app(
            page=authed_page,
            start_url=f"{base_url}/ui",
            base_url=base_url,
            max_pages=30,
        )

        # Zapisz raport JSON
        report_path = REPORTS_DIR / "explorer_authed.json"
        report_path.parent.mkdir(exist_ok=True)
        with open(report_path, "w") as f:
            json.dump({
                "summary": report.summary(),
                "pages": [
                    {
                        "url": p.url,
                        "title": p.title,
                        "status": p.status,
                        "console_errors": p.console_errors,
                        "failed_requests": p.failed_requests,
                        "broken_images": p.broken_images,
                        "error": p.error,
                    }
                    for p in report.pages
                ],
                "skipped": report.skipped,
            }, f, indent=2, ensure_ascii=False)

        print(f"\n[Explorer] Raport: {report_path}")
        print(f"[Explorer] Summary: {report.summary()}")

        # Soft fail - same w sobie nie blokuje, ale loguje
        problematic = [p for p in report.pages if p.status != "ok" or p.console_errors or p.error]
        if problematic:
            print("\n[Explorer] PROBLEMY:")
            for p in problematic:
                print(f"  - {p.url}: {p.status}, errors={p.console_errors}, exc={p.error}")

        # Hard fail tylko na 5xx i exceptions
        crashes = [p for p in report.pages if p.status.startswith("error_") or p.error]
        assert not crashes, f"Crashe podczas crawlu: {[(p.url, p.status, p.error) for p in crashes]}"


@pytest.mark.explorer
@pytest.mark.public
class TestPublicExplorer:
    """Crawl publicznej czesci - bez auth."""

    def test_crawl_public_pages(self, page: Page, base_url: str):
        report = crawl_app(
            page=page,
            start_url=f"{base_url}/ui/login",
            base_url=base_url,
            max_pages=10,
        )

        report_path = REPORTS_DIR / "explorer_public.json"
        report_path.parent.mkdir(exist_ok=True)
        with open(report_path, "w") as f:
            json.dump({
                "summary": report.summary(),
                "pages": [
                    {
                        "url": p.url,
                        "title": p.title,
                        "status": p.status,
                        "console_errors": p.console_errors,
                        "failed_requests": p.failed_requests,
                        "error": p.error,
                    }
                    for p in report.pages
                ],
            }, f, indent=2, ensure_ascii=False)

        print(f"\n[Explorer Public] Summary: {report.summary()}")

        crashes = [p for p in report.pages if p.status.startswith("error_") or p.error]
        assert not crashes, f"Crashe na publicznych: {crashes}"
