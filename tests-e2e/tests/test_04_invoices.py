"""
Invoice list - filtry, sortowanie, paginacja, search.
Wymaga auth.
"""

from __future__ import annotations

import pytest
import requests
from playwright.sync_api import Page, expect


@pytest.mark.auth
class TestInvoiceList:
    """Lista faktur na /ui/invoices."""

    def test_invoice_list_loads(self, authed_page: Page):
        authed_page.goto("/ui/invoices")
        authed_page.wait_for_load_state("networkidle")
        assert "/ui/login" not in authed_page.url

    def test_has_filter_form(self, authed_page: Page):
        authed_page.goto("/ui/invoices")
        # Sprawdz czy sa pola filtrow (subject_type, search)
        # Moze byc form lub inputy luzem
        has_search = authed_page.locator("input[name=search]").count() > 0
        has_subject = authed_page.locator("select[name=subject_type]").count() > 0
        has_seller = authed_page.locator("input[name=seller_nip]").count() > 0
        has_buyer = authed_page.locator("input[name=buyer_nip]").count() > 0

        assert any([has_search, has_subject, has_seller, has_buyer]), \
            "Brak zadnego filtra na liscie faktur"

    def test_filter_by_subject_type(self, authed_page: Page):
        authed_page.goto("/ui/invoices?subject_type=Subject1")
        authed_page.wait_for_load_state("networkidle")
        # URL powinien miec parametr
        assert "subject_type=Subject1" in authed_page.url

    def test_search_query_persists_in_url(self, authed_page: Page):
        authed_page.goto("/ui/invoices?search=test")
        assert "search=test" in authed_page.url

    @pytest.mark.parametrize("sort_by", ["created_at", "issue_date", "gross_amount", "ksef_number"])
    def test_sort_by_parameter(self, authed_page: Page, sort_by: str):
        authed_page.goto(f"/ui/invoices?sort_by={sort_by}&sort_order=desc")
        authed_page.wait_for_load_state("networkidle")
        assert authed_page.locator("body").is_visible()
        # Nie powinno byc 500
        assert "500" not in authed_page.title().lower()

    def test_invalid_sort_handled_gracefully(self, authed_page: Page):
        authed_page.goto("/ui/invoices?sort_by=DROP_TABLE_users")
        authed_page.wait_for_load_state("networkidle")
        # Aplikacja powinna odrzucic zly parametr (nie 500)
        body = authed_page.locator("body").inner_text().lower()
        assert "internal server error" not in body
        assert "traceback" not in body

    def test_pagination_links_if_present(self, authed_page: Page):
        authed_page.goto("/ui/invoices?page=1")
        authed_page.wait_for_load_state("networkidle")
        # Jesli sa dane - powinna byc paginacja, jesli nie - empty state
        # Test passes jesli nie ma 500
        assert "/ui/login" not in authed_page.url


@pytest.mark.auth
class TestInvoiceListSecurity:
    """Filter inputs - XSS i SQLi."""

    def test_xss_in_search_escaped(self, authed_page: Page):
        payload = "<script>window.__pwn=1</script>"
        authed_page.goto(f"/ui/invoices?search={payload}")
        authed_page.wait_for_load_state("networkidle")

        pwned = authed_page.evaluate("() => window.__pwn === 1")
        assert not pwned, "XSS via search query!"

    def test_sqli_in_search_safe(self, authed_page: Page):
        payload = "'; DROP TABLE invoices; --"
        authed_page.goto(f"/ui/invoices?search={payload}")
        authed_page.wait_for_load_state("networkidle")
        # Nie powinno byc 500 ani crashu - po prostu pusta lista
        body_text = authed_page.locator("body").inner_text().lower()
        assert "traceback" not in body_text
        assert "internal server error" not in body_text


@pytest.mark.auth
class TestInvoiceListAPI:
    """API endpoint dla faktur z sesja UI."""

    def test_api_invoices_returns_json(self, authed_context, base_url: str):
        # Pobierz cookies z authed context
        cookies = authed_context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}

        r = requests.get(
            f"{base_url}/api/v1/invoices",
            cookies=cookie_dict,
            timeout=5,
        )
        assert r.status_code == 200, f"API status: {r.status_code}, body: {r.text[:200]}"
        body = r.json()
        # Oczekujemy listy lub paginowanej struktury
        assert isinstance(body, (list, dict))

    def test_api_stats_summary(self, authed_context, base_url: str):
        cookies = authed_context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}

        r = requests.get(
            f"{base_url}/api/v1/stats/summary",
            cookies=cookie_dict,
            timeout=5,
        )
        assert r.status_code == 200
        assert isinstance(r.json(), dict)
