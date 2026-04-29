"""
AI Explorer - crawl wszystkich linkow w aplikacji.
Sprawdza:
- 404, 500
- Console errors / pageerror
- Broken images
- Slow pages
- Failed network requests
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

if TYPE_CHECKING:
    from playwright.sync_api import Page


@dataclass
class PageReport:
    url: str
    status: str = "ok"
    title: str = ""
    load_time_ms: int = 0
    console_errors: list[str] = field(default_factory=list)
    failed_requests: list[dict] = field(default_factory=list)
    broken_images: list[str] = field(default_factory=list)
    links_found: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class ExplorerReport:
    pages: list[PageReport] = field(default_factory=list)
    visited: set[str] = field(default_factory=set)
    skipped: list[str] = field(default_factory=list)

    def has_issues(self) -> bool:
        return any(
            p.status != "ok" or p.console_errors or p.failed_requests or p.broken_images or p.error
            for p in self.pages
        )

    def summary(self) -> dict:
        return {
            "total_visited": len(self.pages),
            "ok": sum(1 for p in self.pages if p.status == "ok" and not p.error),
            "with_console_errors": sum(1 for p in self.pages if p.console_errors),
            "with_failed_requests": sum(1 for p in self.pages if p.failed_requests),
            "with_broken_images": sum(1 for p in self.pages if p.broken_images),
            "errored": sum(1 for p in self.pages if p.error),
        }


def normalize_url(url: str, base: str) -> str | None:
    """Konwertuje wzgledny URL na bezwzgledny, filtruje obce domeny."""
    if not url or url.startswith(("javascript:", "mailto:", "tel:", "data:", "#")):
        return None

    abs_url = urljoin(base, url)
    parsed = urlparse(abs_url)
    base_host = urlparse(base).netloc

    if parsed.netloc and parsed.netloc != base_host:
        return None

    # Tnij fragment
    return abs_url.split("#")[0]


def explore_page(page: "Page", url: str, base_url: str) -> PageReport:
    """Odwiedza jedna strone, zbiera issue, zwraca raport."""
    report = PageReport(url=url)
    console_errors: list[str] = []
    failed_requests: list[dict] = []

    def on_console(msg):
        if msg.type in ("error",):
            console_errors.append(msg.text)

    def on_pageerror(exc):
        console_errors.append(f"pageerror: {exc}")

    def on_response(resp):
        if resp.status >= 400:
            failed_requests.append({
                "url": resp.url,
                "status": resp.status,
                "method": resp.request.method,
            })

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.on("response", on_response)

    try:
        response = page.goto(url, wait_until="networkidle", timeout=15000)
        report.title = page.title()

        if response:
            if response.status >= 500:
                report.status = f"error_{response.status}"
            elif response.status >= 400:
                report.status = f"client_error_{response.status}"

        # Zbierz linki na stronie
        links = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => e.getAttribute('href'))"
        )
        report.links_found = [
            normalize_url(href, base_url)
            for href in links
            if normalize_url(href, base_url)
        ]
        report.links_found = list({l for l in report.links_found if l})  # dedup

        # Sprawdz broken images
        broken = page.evaluate("""
            () => {
                const imgs = Array.from(document.querySelectorAll('img'));
                return imgs
                    .filter(img => img.complete && img.naturalWidth === 0 && img.src)
                    .map(img => img.src);
            }
        """)
        report.broken_images = broken

    except Exception as e:
        report.error = str(e)
        report.status = "exception"
    finally:
        report.console_errors = console_errors
        report.failed_requests = failed_requests
        page.remove_listener("console", on_console)
        page.remove_listener("pageerror", on_pageerror)
        page.remove_listener("response", on_response)

    return report


def crawl_app(
    page: "Page",
    start_url: str,
    base_url: str,
    max_pages: int = 30,
    skip_patterns: list[str] | None = None,
) -> ExplorerReport:
    """BFS crawl, max_pages stron."""
    skip_patterns = skip_patterns or ["/ui/logout", "/api/", "/docs", "/redoc", "/openapi.json"]
    report = ExplorerReport()
    queue = [start_url]

    while queue and len(report.pages) < max_pages:
        url = queue.pop(0)
        if url in report.visited:
            continue
        if any(p in url for p in skip_patterns):
            report.skipped.append(url)
            continue

        report.visited.add(url)
        page_report = explore_page(page, url, base_url)
        report.pages.append(page_report)

        for link in page_report.links_found:
            if link not in report.visited and link not in queue:
                queue.append(link)

    return report
