"""
Shared constants and utilities for KSeF invoice PDF generation.

Extracted from invoice_pdf_generator.py to eliminate duplication between
the ReportLab generator and xhtml2pdf template renderer.

Constants are derived from official KSeF schema and XSL visualization:
  XSD: http://crd.gov.pl/wzor/2025/06/25/13775/schemat.xsd
  XSL: http://crd.gov.pl/wzor/2025/06/25/13775/styl.xsl
"""

import logging
import os
from typing import Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# VAT rate display mapping (from XSD TStawkaPodatku + XSL styl.xsl)
# ---------------------------------------------------------------------------
VAT_RATE_LABELS: Dict[str, str] = {
    '23': '23%', '22': '22%', '8': '8%', '7': '7%',
    '5': '5%', '4': '4%', '3': '3%',
    '0': '0%', '0 KR': '0%', '0 WDT': '0% WDT', '0 EX': '0% eksport',
    'zw': 'zw',
    'oo': 'odwr. obc.',
    'np': 'np', 'np I': 'np', 'np II': 'np',
}

# ---------------------------------------------------------------------------
# Payment method mapping (from XSD TFormaPlatnosci)
# ---------------------------------------------------------------------------
PAYMENT_METHODS: Dict[str, str] = {
    '1': 'Got\u00f3wka', '2': 'Karta', '3': 'Bon',
    '4': 'Czek', '5': 'Kredyt', '6': 'Przelew', '7': 'Mobilna',
}

# ---------------------------------------------------------------------------
# Invoice type titles (from XSL NaglowekTytulowy)
# ---------------------------------------------------------------------------
INVOICE_TYPE_TITLES: Dict[str, str] = {
    'VAT': 'Faktura VAT',
    'KOR': 'Faktura koryguj\u0105ca',
    'ZAL': 'Faktura zaliczkowa',
    'ROZ': 'Faktura rozliczeniowa',
    'UPR': 'Faktura uproszczona',
    'KOR_ZAL': 'Faktura koryguj\u0105ca zaliczkowa',
    'KOR_ROZ': 'Faktura koryguj\u0105ca rozliczeniowa',
}

# ---------------------------------------------------------------------------
# QR code base URLs per environment (from kody-qr.md)
# ---------------------------------------------------------------------------
QR_BASE_URLS: Dict[str, str] = {
    'test': 'https://qr-test.ksef.mf.gov.pl',
    'demo': 'https://qr-demo.ksef.mf.gov.pl',
    'prod': 'https://qr.ksef.mf.gov.pl',
}

# ---------------------------------------------------------------------------
# VAT summary row definitions: (label, P_13 field, P_14 field, P_14W field)
# ---------------------------------------------------------------------------
VAT_SUMMARY_ROWS: list = [
    ('22% lub 23%', 'P_13_1', 'P_14_1', 'P_14_1W'),
    ('7% lub 8%', 'P_13_2', 'P_14_2', 'P_14_2W'),
    ('5%', 'P_13_3', 'P_14_3', 'P_14_3W'),
    ('0%', 'P_13_6_1', None, None),
    ('0% WDT', 'P_13_6_2', None, None),
    ('0% eksport', 'P_13_6_3', None, None),
    ('zw', 'P_13_7', None, None),
    ('oo', 'P_13_10', None, None),
    ('np', 'P_13_8', None, None),
    ('us\u0142ugi art. 100', 'P_13_9', None, None),
    ('procedura szczeg\u00f3lna', 'P_13_5', 'P_14_5', None),
    ('rycza\u0142t taks\u00f3wki', 'P_13_4', 'P_14_4', 'P_14_4W'),
    ('mar\u017ca', 'P_13_11', None, None),
]

# ---------------------------------------------------------------------------
# Mapping P_12 item rates to their VAT summary P_13 field
# ---------------------------------------------------------------------------
_P12_TO_P13: Dict[str, str] = {
    '22': 'P_13_1', '23': 'P_13_1',
    '7': 'P_13_2', '8': 'P_13_2',
}


def _resolve_vat_summary_labels(items: list) -> dict:
    """Determine actual VAT rate labels from invoice line items.

    For ambiguous summary rows (P_13_1 covers 22%/23%, P_13_2 covers 7%/8%),
    inspect the items' P_12 values to build a precise label.
    """
    labels = {}
    for p13_field in ('P_13_1', 'P_13_2'):
        possible = [p12 for p12, p13 in _P12_TO_P13.items() if p13 == p13_field]
        actual = sorted(
            {it['p12'] for it in items if it.get('p12') in possible},
            key=lambda x: int(x),
        )
        if actual:
            labels[p13_field] = ' / '.join(f'{r}%' for r in actual)
    return labels


# ---------------------------------------------------------------------------
# Font registration for ReportLab — shared between PDF generator and template
# ---------------------------------------------------------------------------

# Font candidates: (name, regular_path, bold_path_or_None)
# Priority: DejaVu Sans (Linux/Docker) > Arial Unicode MS (macOS) > Arial (macOS) > Helvetica (fallback)
_FONT_CANDIDATES: list = [
    ('DejaVuSans', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
    ('DejaVuSans', '/usr/share/fonts/dejavu/DejaVuSans.ttf',
                    '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf'),
    ('DejaVuSans', '/usr/share/fonts/TTF/DejaVuSans.ttf',
                    '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf'),
    ('ArialUnicode', '/Library/Fonts/Arial Unicode.ttf', None),
    ('ArialUnicode', '/System/Library/Fonts/Supplemental/Arial Unicode.ttf', None),
    ('Arial', '/System/Library/Fonts/Supplemental/Arial.ttf',
              '/System/Library/Fonts/Supplemental/Arial Bold.ttf'),
    ('Arial', '/Library/Fonts/Arial.ttf', '/Library/Fonts/Arial Bold.ttf'),
]

# Defaults (Helvetica is always available in ReportLab but lacks Polish chars)
FONT_NAME = 'Helvetica'
FONT_NAME_BOLD = 'Helvetica-Bold'


def register_fonts() -> None:
    """Register a TTF font with Polish character support in ReportLab.

    Updates module-level FONT_NAME and FONT_NAME_BOLD on success.
    Safe to call multiple times — only registers once.
    """
    global FONT_NAME, FONT_NAME_BOLD

    if FONT_NAME != 'Helvetica':
        return  # already registered

    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        return

    for fname, fpath, fbold in _FONT_CANDIDATES:
        if not os.path.exists(fpath):
            continue
        try:
            pdfmetrics.registerFont(TTFont(fname, fpath))
            FONT_NAME = fname
            FONT_NAME_BOLD = fname
            if fbold and os.path.exists(fbold):
                bold_name = fname + '-Bold'
                pdfmetrics.registerFont(TTFont(bold_name, fbold))
                FONT_NAME_BOLD = bold_name
            logger.info("Font '%s' registered for Polish character support", fname)
            return
        except Exception as e:
            logger.warning("Failed to register font '%s': %s", fname, e)

    logger.warning("No TTF font with Polish support found - diacritical marks may not render")


def find_font_paths() -> Dict[str, str]:
    """Find font file paths supporting Polish characters for CSS @font-face.

    Returns dict with 'regular' and optionally 'bold' keys.
    Used by xhtml2pdf template renderer.
    """
    for fname, fpath, fbold in _FONT_CANDIDATES:
        if os.path.exists(fpath):
            result = {'regular': fpath}
            if fbold and os.path.exists(fbold):
                result['bold'] = fbold
            return result
    return {}


# Auto-register fonts on module import (same behavior as before refactoring)
register_fonts()
