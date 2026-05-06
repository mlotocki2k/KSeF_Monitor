"""
Invoice detail page - PDF generation, XML download.
Wymaga ze JEST przynajmniej jedna faktura w bazie.
"""

from __future__ import annotations

import pytest
import requests
from playwright.sync_api import Page


@pytest.fixture
def first_invoice_ksef_number(authed_context, base_url: str) -> str | None:
    """Pobiera ksef_number pierwszej faktury z API. None = brak faktur (skip)."""
    cookies = authed_context.cookies()
    cookie_dict = {c["name"]: c["value"] for c in cookies}

    r = requests.get(f"{base_url}/api/v1/invoices?limit=1", cookies=cookie_dict, timeout=5)
    if r.status_code != 200:
        return None

    body = r.json()
    items = body if isinstance(body, list) else body.get("items", [])
    if not items:
        return None
    return items[0].get("ksef_number") or items[0].get("ksefReferenceNumber")


@pytest.mark.auth
class TestInvoiceDetail:
    """Detail page /ui/invoices/{ksef_number}."""

    def test_detail_loads_for_existing_invoice(self, authed_page: Page, first_invoice_ksef_number):
        if not first_invoice_ksef_number:
            pytest.skip("Brak faktur w bazie - skip detail test")

        authed_page.goto(f"/ui/invoices/{first_invoice_ksef_number}")
        authed_page.wait_for_load_state("networkidle")

        assert "/ui/login" not in authed_page.url
        body = authed_page.locator("body").inner_text()
        # KSeF number powinien byc na stronie
        # (krotsza wersja - fmt_filter ksef_short pokazuje ostatnie 10 znakow)
        assert first_invoice_ksef_number[-10:] in body or first_invoice_ksef_number in body, \
            "Brak ksef_number na stronie szczegolow"

    def test_detail_404_for_nonexistent(self, authed_page: Page):
        authed_page.goto("/ui/invoices/NONEXISTENT-FAKE-KSEF-NUMBER-XYZ")
        authed_page.wait_for_load_state("networkidle")
        # Oczekujemy 404 lub przekierowania na liste z bledem
        # Sprawdz status response albo komunikat na stronie
        body = authed_page.locator("body").inner_text().lower()
        # Nie 500
        assert "internal server error" not in body
        assert "traceback" not in body


@pytest.mark.auth
class TestInvoicePDF:
    """PDF generation."""

    def test_pdf_endpoint_returns_pdf(self, authed_context, base_url: str, first_invoice_ksef_number):
        if not first_invoice_ksef_number:
            pytest.skip("Brak faktur")

        cookies = authed_context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}

        r = requests.get(
            f"{base_url}/api/v1/invoices/{first_invoice_ksef_number}/pdf",
            cookies=cookie_dict,
            timeout=15,
        )
        assert r.status_code == 200, f"PDF endpoint: {r.status_code}"
        # PDF magic bytes
        assert r.content[:4] == b"%PDF", "Response nie jest PDFem"
        # Content-Type
        assert "pdf" in r.headers.get("content-type", "").lower()

    def test_xml_endpoint_returns_xml(self, authed_context, base_url: str, first_invoice_ksef_number):
        if not first_invoice_ksef_number:
            pytest.skip("Brak faktur")

        cookies = authed_context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}

        r = requests.get(
            f"{base_url}/api/v1/invoices/{first_invoice_ksef_number}/xml",
            cookies=cookie_dict,
            timeout=10,
        )
        assert r.status_code == 200
        # XML - zaczyna sie od < (po BOM/whitespace)
        content = r.text.strip()
        assert content.startswith("<"), f"Nie XML: {content[:100]}"


@pytest.mark.auth
@pytest.mark.security
class TestInvoiceDetailSecurity:
    """Path traversal, IDOR, etc."""

    @pytest.mark.parametrize("payload", [
        "../etc/passwd",
        "../../config.json",
        "..%2Fetc%2Fpasswd",
        "%2E%2E%2Fetc%2Fpasswd",
    ])
    def test_path_traversal_blocked(self, authed_context, base_url: str, payload: str):
        """App nie powinno wyciekac plikow systemowych - 404 albo bezpieczna strona."""
        cookies = authed_context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}

        import requests
        r = requests.get(
            f"{base_url}/ui/invoices/{payload}",
            cookies=cookie_dict,
            timeout=5,
            allow_redirects=False,
        )
        # Akceptujemy 404 (norm), 422 (validation), 400 (bad req), 303 (redirect)
        # Nie OK: 200 z zawartoscia plikow systemowych
        assert r.status_code in (400, 404, 422, 303), \
            f"Niespodziewany status {r.status_code} dla {payload}"
        # Nawet jesli 200 - nie ma byc plikow systemowych
        body = r.text.lower()
        assert "root:x:0:0" not in body, "Wyciek /etc/passwd!"
        assert "/bin/bash" not in body
        assert "postgres_password" not in body
        assert "ksef_token" not in body
