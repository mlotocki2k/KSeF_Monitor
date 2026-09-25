"""
Invoice PDF rendering: the Polish-capable TTF font must be embedded, and
nothing outside the font/template directories (or the network) may be read.
"""

import base64
import re
from io import BytesIO

import pytest

from app.invoice_pdf_template import _pdf_link_callback, _pdf_resource_policy
from app.pdf_constants import find_font_paths

try:
    from xhtml2pdf import pisa
except ImportError:  # pragma: no cover
    pisa = None

pytestmark = pytest.mark.skipif(pisa is None, reason="xhtml2pdf not installed")

# 1x1 transparent PNG
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _fonts(pdf: bytes):
    return set(re.findall(rb"/BaseFont\s*/([A-Za-z0-9+\-_,]+)", pdf))


@pytest.mark.skipif(not find_font_paths(), reason="no Polish-capable TTF font on this host")
def test_polish_font_is_embedded():
    from app.invoice_pdf_generator import generate_invoice_pdf
    from tests.test_multi_schema_parser import MINIMAL_FA3_XML

    xml = MINIMAL_FA3_XML.replace("Sprzedawca Sp. z o.o.", "Zażółć gęślą jaźń ŁÓDŹ")
    buf = generate_invoice_pdf(xml, ksef_number="1234567890-20260101-ABCDEF-12")
    pdf = buf.read() if hasattr(buf, "read") else buf
    fonts = _fonts(pdf)
    assert fonts - {b"Helvetica", b"Helvetica-Bold", b"ZapfDingbats"}, fonts


@pytest.mark.parametrize("uri", [
    "/etc/passwd",
    "file:///etc/passwd",
    "http://169.254.169.254/latest/meta-data/",
    "https://example.com/x.png",
])
def test_callback_blocks_foreign_resources(uri):
    assert _pdf_link_callback(uri, None) == "data:,"


def test_callback_blocks_traversal_out_of_template_dir():
    from app.invoice_pdf_template import DEFAULT_TEMPLATES_DIR
    uri = str(DEFAULT_TEMPLATES_DIR) + "/../../../../etc/passwd"
    assert _pdf_link_callback(uri, None) == "data:,"


def test_callback_allows_data_uri_and_font():
    assert _pdf_link_callback("data:image/png;base64,AAAA", None).startswith("data:image/png")
    fonts = find_font_paths()
    if fonts:
        assert _pdf_link_callback(fonts["regular"], None) != "data:,"


def test_local_image_outside_roots_not_embedded(tmp_path):
    img = tmp_path / "secret.png"
    img.write_bytes(PNG)
    html = f'<html><body><p>x</p><img src="{img}" width="10" height="10"></body></html>'
    out = BytesIO()
    pisa.CreatePDF(html, dest=out, link_callback=_pdf_link_callback,
                   resource_policy=_pdf_resource_policy())
    assert b"/Subtype /Image" not in out.getvalue()


def test_policy_denies_network():
    policy = _pdf_resource_policy()
    assert policy.allow_remote is False


def test_custom_template_dir_asset_allowed(tmp_path):
    """docs/PDF_TEMPLATES.md: <img src="/data/pdf_templates/logo.png"> next to a custom template."""
    logo = tmp_path / "logo.png"
    logo.write_bytes(PNG)
    assert _pdf_link_callback(str(logo), None) == "data:,"
    assert _pdf_link_callback(str(logo), None, (str(tmp_path),)) == str(logo.resolve())
    out = BytesIO()
    html = f"<html><body><img src=\"{logo}\" width=\"10\" height=\"10\"></body></html>"
    pisa.CreatePDF(html, dest=out, link_callback=lambda u, r: _pdf_link_callback(u, r, (str(tmp_path),)),
                   resource_policy=_pdf_resource_policy((str(tmp_path),)))
    assert b"/Subtype /Image" in out.getvalue()


def test_renderer_passes_custom_dir(tmp_path):
    from app.invoice_pdf_template import InvoicePDFTemplateRenderer
    assert InvoicePDFTemplateRenderer(str(tmp_path))._extra_dirs == (str(tmp_path),)
    assert InvoicePDFTemplateRenderer(str(tmp_path / "missing"))._extra_dirs == ()
