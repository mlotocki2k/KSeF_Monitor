"""
Invoice PDF Template Renderer

Generates invoice PDFs from Jinja2 HTML/CSS templates using xhtml2pdf.
Users can customize the invoice appearance by providing a custom template
in their templates directory (storage.pdf_templates_dir in config).

Template resolution order:
1. Custom templates dir (from config)
2. Built-in default (app/templates/invoice_pdf.html.j2)

Fallback: if xhtml2pdf is not available or rendering fails,
the caller should fall back to the ReportLab-based InvoicePDFGenerator.
"""

import base64
import hashlib
import logging
import os
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

# Default templates directory (shipped with the application)
DEFAULT_TEMPLATES_DIR = Path(__file__).parent / "templates"

try:
    import pytz
    PYTZ_AVAILABLE = True
except ImportError:
    PYTZ_AVAILABLE = False

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False

try:
    from xhtml2pdf import pisa
    XHTML2PDF_AVAILABLE = True
except ImportError:
    XHTML2PDF_AVAILABLE = False

# Import shared constants and registered font names from invoice_pdf_generator
from .invoice_pdf_generator import (
    VAT_RATE_LABELS, PAYMENT_METHODS, INVOICE_TYPE_TITLES, QR_BASE_URLS,
    VAT_SUMMARY_ROWS, _FONT_NAME, _FONT_NAME_BOLD,
)

TEMPLATE_NAME = "invoice_pdf.html.j2"


def fmt_amt_filter(val) -> str:
    """
    Format monetary amount according to Polish norms.

    Usage in template: {{ "24000.00" | fmt_amt }}  ->  24 000,00
    """
    if not val:
        return ''
    try:
        num = float(val)
        formatted = f'{num:,.2f}'
        # Polish norms: ',' as decimal separator, non-breaking space as thousands separator
        formatted = formatted.replace(',', '\u00a0').replace('.', ',')
        return formatted
    except (ValueError, TypeError):
        return str(val)


def vat_label_filter(val) -> str:
    """
    Map VAT rate code to display label.

    Usage in template: {{ "23" | vat_label }}  ->  23%
    """
    return VAT_RATE_LABELS.get(str(val), str(val))


def payment_method_filter(val) -> str:
    """
    Map payment method code to Polish name.

    Usage in template: {{ "6" | payment_method }}  ->  Przelew
    """
    return PAYMENT_METHODS.get(str(val), str(val))


class InvoicePDFTemplateRenderer:
    """
    Renders invoice PDF from Jinja2 HTML template using xhtml2pdf.

    Uses the same user-override mechanism as notification templates:
    custom dir (priority) -> built-in defaults.
    """

    def __init__(self, custom_templates_dir: Optional[str] = None):
        search_paths = []

        if custom_templates_dir:
            custom_path = Path(custom_templates_dir)
            if custom_path.is_dir():
                search_paths.append(str(custom_path))
                logger.info(f"Custom PDF templates directory: {custom_path}")
            else:
                logger.warning(
                    f"Custom PDF templates directory not found: {custom_path}, "
                    f"using defaults only"
                )

        search_paths.append(str(DEFAULT_TEMPLATES_DIR))

        self.env = Environment(
            loader=FileSystemLoader(search_paths),
            autoescape=select_autoescape(["html"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # Register custom filters
        self.env.filters["fmt_amt"] = fmt_amt_filter
        self.env.filters["vat_label"] = vat_label_filter
        self.env.filters["payment_method"] = payment_method_filter

    def render(self, invoice_data: Dict, ksef_number: str = '',
               xml_content: str = '', environment: str = '',
               timezone: str = '', output_path: str = None) -> BytesIO:
        """
        Render invoice data to PDF via HTML template.

        Args:
            invoice_data: Parsed invoice data dict from InvoiceXMLParser
            ksef_number: KSeF reference number
            xml_content: Raw XML content (for QR code hash)
            environment: KSeF environment ('test', 'demo', 'prod')
            timezone: IANA timezone name for generation timestamp
            output_path: File path to write PDF (if None, returns BytesIO)

        Returns:
            BytesIO with PDF content
        """
        # Generate QR code data URI
        qr_data_uri = self._generate_qr_data_uri(invoice_data, xml_content, environment)

        # Prepare template context
        context = self._prepare_context(invoice_data, ksef_number, qr_data_uri, timezone)

        # Render Jinja2 template to HTML
        template = self.env.get_template(TEMPLATE_NAME)
        html_content = template.render(**context)

        # Convert HTML to PDF using xhtml2pdf
        buffer = BytesIO()
        pisa_status = pisa.CreatePDF(html_content, dest=buffer, encoding='utf-8')

        if pisa_status.err:
            raise RuntimeError(f"xhtml2pdf rendering failed with {pisa_status.err} error(s)")

        # Write to file if output_path given
        if output_path:
            with open(output_path, 'wb') as f:
                f.write(buffer.getvalue())

        buffer.seek(0)
        logger.info(f"Template PDF generated ({len(buffer.getvalue())} bytes)")
        return buffer

    def _prepare_context(self, invoice_data: Dict, ksef_number: str,
                         qr_data_uri: str, timezone: str) -> Dict:
        """Build the full template context dict."""
        header = invoice_data.get('header', {})
        rodzaj = header.get('rodzaj', 'VAT')
        invoice_type_title = INVOICE_TYPE_TITLES.get(rodzaj, 'Faktura')

        # Determine total label based on invoice type
        if rodzaj in ('ZAL', 'KOR_ZAL'):
            total_label = 'Otrzymana kwota zap\u0142aty:'
        elif rodzaj in ('ROZ', 'KOR_ROZ'):
            total_label = 'Kwota pozosta\u0142a do zap\u0142aty:'
        else:
            total_label = 'Kwota nale\u017cno\u015bci og\u00f3\u0142em:'

        # Generation stamp
        tz_name = timezone or 'Europe/Warsaw'
        now = datetime.now()
        tz_label = ''
        if PYTZ_AVAILABLE:
            try:
                tz = pytz.timezone(tz_name)
                now = datetime.now(tz)
                tz_label = now.strftime('%Z')
            except Exception:
                tz_label = tz_name
        else:
            tz_label = tz_name
        generation_stamp = f'{now.strftime("%y.%m.%d %H:%M:%S")} {tz_label}'

        # Determine which optional item columns have data
        items = invoice_data.get('items', [])
        has_col = {
            'indeks': any(it.get('indeks') for it in items),
            'p8a': any(it.get('p8a') for it in items),
            'p8b': any(it.get('p8b') for it in items),
            'p9a': any(it.get('p9a') for it in items),
            'p9b': any(it.get('p9b') for it in items),
            'p10': any(it.get('p10') for it in items),
            'p11': any(it.get('p11') for it in items),
            'p11a': any(it.get('p11a') for it in items),
            'p11vat': any(it.get('p11vat') for it in items),
            'p12': any(it.get('p12') for it in items),
            'p6a': any(it.get('p6a') for it in items),
        }

        # Build VAT summary rows (only those with data)
        vat_summary = invoice_data.get('vat_summary', {})
        vat_rows = []
        for label, p13_field, p14_field in VAT_SUMMARY_ROWS:
            net = vat_summary.get(p13_field)
            if not net:
                continue
            vat = vat_summary.get(p14_field, '') if p14_field else ''
            vat_rows.append({'label': label, 'net': net, 'vat': vat})

        # Font paths for @font-face (try common locations)
        font_paths = self._find_font_paths()

        # ReportLab-registered font name (from invoice_pdf_generator module init)
        # This ensures CSS uses the same font that ReportLab/xhtml2pdf knows about
        font_name = _FONT_NAME
        font_name_bold = _FONT_NAME_BOLD

        return {
            'header': header,
            'seller': invoice_data.get('seller', {}),
            'buyer': invoice_data.get('buyer', {}),
            'items': items,
            'vat_summary': vat_summary,
            'vat_rows': vat_rows,
            'payment': invoice_data.get('payment', {}),
            'annotations': invoice_data.get('annotations', {}),
            'footer_data': invoice_data.get('footer', {}),
            'ksef_number': ksef_number,
            'qr_code_data_uri': qr_data_uri,
            'invoice_type_title': invoice_type_title,
            'total_label': total_label,
            'generation_stamp': generation_stamp,
            'has_col': has_col,
            'payment_methods': PAYMENT_METHODS,
            'vat_rate_labels': VAT_RATE_LABELS,
            'font_paths': font_paths,
            'font_name': font_name,
            'font_name_bold': font_name_bold,
        }

    @staticmethod
    def _find_font_paths() -> Dict[str, str]:
        """Find font paths supporting Polish characters for CSS @font-face."""
        candidates = [
            # Linux/Docker (DejaVu Sans)
            ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
             '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
            ('/usr/share/fonts/dejavu/DejaVuSans.ttf',
             '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf'),
            ('/usr/share/fonts/TTF/DejaVuSans.ttf',
             '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf'),
            # macOS (Arial Unicode or Arial)
            ('/Library/Fonts/Arial Unicode.ttf', None),
            ('/System/Library/Fonts/Supplemental/Arial Unicode.ttf', None),
            ('/System/Library/Fonts/Supplemental/Arial.ttf',
             '/System/Library/Fonts/Supplemental/Arial Bold.ttf'),
            ('/Library/Fonts/Arial.ttf', '/Library/Fonts/Arial Bold.ttf'),
        ]
        for regular, bold in candidates:
            if os.path.exists(regular):
                result = {'regular': regular}
                if bold and os.path.exists(bold):
                    result['bold'] = bold
                return result
        return {}

    @staticmethod
    def _generate_qr_data_uri(invoice_data: Dict, xml_content: str,
                               environment: str) -> str:
        """
        Generate QR Code Type I as base64 data URI for HTML embedding.

        Returns empty string if QR cannot be generated.
        """
        if not QRCODE_AVAILABLE or not xml_content:
            return ''

        seller_nip = invoice_data.get('seller', {}).get('nip', '')
        issue_date = invoice_data.get('header', {}).get('p1', '')

        if not seller_nip or not issue_date:
            return ''

        # Format date DD-MM-YYYY
        if len(issue_date) >= 10:
            parts = issue_date[:10].split('-')
            if len(parts) == 3:
                date_str = f'{parts[2]}-{parts[1]}-{parts[0]}'
            else:
                return ''
        else:
            return ''

        # SHA-256 hash of XML
        digest = hashlib.sha256(xml_content.encode('utf-8')).digest()
        file_hash = base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')

        env_key = environment.lower() if environment else 'prod'
        base_url = QR_BASE_URLS.get(env_key, QR_BASE_URLS['prod'])
        qr_url = f'{base_url}/invoice/{seller_nip}/{date_str}/{file_hash}'

        try:
            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=3,
                border=1,
            )
            qr.add_data(qr_url)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color='black', back_color='white')

            img_buffer = BytesIO()
            qr_img.save(img_buffer, format='PNG')
            b64 = base64.b64encode(img_buffer.getvalue()).decode('ascii')
            return f'data:image/png;base64,{b64}'
        except Exception as e:
            logger.error(f"Failed to generate QR code data URI: {e}")
            return ''
