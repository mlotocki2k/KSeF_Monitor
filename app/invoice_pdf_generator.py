"""
KSeF Invoice PDF Generator

Converts KSeF invoice XML (FA_VAT format) to PDF following KSeF visual template.
Based on FA_VAT schema from KSeF documentation.
"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, Optional, List
from io import BytesIO

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    )
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

logger = logging.getLogger(__name__)


class InvoiceXMLParser:
    """Parser for KSeF FA_VAT XML invoices"""

    # KSeF FA namespace
    NS = {'fa': 'http://crd.gov.pl/wzor/2023/06/29/12648/'}

    def __init__(self, xml_content: str):
        """
        Initialize parser with XML content

        Args:
            xml_content: Raw XML string from KSeF API
        """
        self.xml_content = xml_content
        self.root = None
        self.parsed_data = {}

    def parse(self) -> Dict:
        """
        Parse XML and extract invoice data

        Returns:
            Dictionary with structured invoice data
        """
        try:
            self.root = ET.fromstring(self.xml_content)

            # Extract all invoice sections
            self.parsed_data = {
                'ksef_metadata': self._parse_ksef_metadata(),
                'invoice_header': self._parse_invoice_header(),
                'seller': self._parse_subject(is_seller=True),
                'buyer': self._parse_subject(is_seller=False),
                'items': self._parse_invoice_items(),
                'summary': self._parse_invoice_summary(),
                'payment': self._parse_payment_info(),
                'annotations': self._parse_annotations()
            }

            logger.info("Invoice XML parsed successfully")
            return self.parsed_data

        except ET.ParseError as e:
            logger.error(f"XML parsing error: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to parse invoice XML: {e}")
            raise

    def _parse_ksef_metadata(self) -> Dict:
        """Parse KSeF-specific metadata"""
        metadata = {}

        # KSeF number is typically in root attributes or specific element
        # This needs to be passed externally as it's not in FA XML itself
        metadata['ksef_number'] = ''
        metadata['ksef_qr_code'] = ''

        return metadata

    def _parse_invoice_header(self) -> Dict:
        """Parse invoice header (Naglowek section)"""
        header = {}

        naglowek = self.root.find('.//fa:Naglowek', self.NS)
        if naglowek is not None:
            header['invoice_type'] = self._get_text(naglowek, 'fa:KodFormularza')
            header['invoice_variant'] = self._get_text(naglowek, 'fa:WariantFormularza')
            header['invoice_number'] = self._get_text(naglowek, 'fa:NrFaktury')
            header['issue_date'] = self._get_text(naglowek, 'fa:DataWystawienia')

        # Additional invoice data from Fa section
        fa = self.root.find('.//fa:Fa', self.NS)
        if fa is not None:
            header['sale_date'] = self._get_text(fa, 'fa:P_1')
            header['currency'] = self._get_text(fa, 'fa:KodWaluty', default='PLN')

        return header

    def _parse_subject(self, is_seller: bool) -> Dict:
        """
        Parse seller or buyer information

        Args:
            is_seller: True for seller (Sprzedawca), False for buyer (Nabywca)
        """
        subject = {}
        tag = 'fa:Sprzedawca' if is_seller else 'fa:Nabywca'

        podmiot = self.root.find(f'.//fa:Podmiot1/{tag}', self.NS)
        if podmiot is None:
            podmiot = self.root.find(f'.//fa:Podmiot2/{tag}', self.NS)

        if podmiot is not None:
            # NIP
            subject['nip'] = self._get_text(podmiot, 'fa:NIP')

            # Company name
            subject['name'] = self._get_text(podmiot, 'fa:NazwaHandlowa')
            if not subject['name']:
                subject['name'] = self._get_text(podmiot, 'fa:Nazwa')

            # Address
            adres = podmiot.find('fa:Adres', self.NS)
            if adres is not None:
                subject['address'] = {
                    'street': self._get_text(adres, 'fa:Ulica'),
                    'building_number': self._get_text(adres, 'fa:NrDomu'),
                    'apartment_number': self._get_text(adres, 'fa:NrLokalu'),
                    'postal_code': self._get_text(adres, 'fa:KodPocztowy'),
                    'city': self._get_text(adres, 'fa:Miejscowosc'),
                    'country': self._get_text(adres, 'fa:KodKraju', default='PL')
                }
            else:
                subject['address'] = {}

        return subject

    def _parse_invoice_items(self) -> List[Dict]:
        """Parse invoice line items (Fa_WierszeTabeli section)"""
        items = []

        # Find all line items
        wiersze = self.root.findall('.//fa:Fa/fa:FaWiersz', self.NS)

        for idx, wiersz in enumerate(wiersze, 1):
            item = {
                'line_number': idx,
                'name': self._get_text(wiersz, 'fa:P_7'),
                'quantity': self._get_text(wiersz, 'fa:P_8A'),
                'unit': self._get_text(wiersz, 'fa:P_8B', default='szt'),
                'unit_price_net': self._get_text(wiersz, 'fa:P_9A'),
                'net_value': self._get_text(wiersz, 'fa:P_11'),
                'vat_rate': self._get_text(wiersz, 'fa:P_12'),
                'vat_amount': self._get_text(wiersz, 'fa:P_11Vat'),
                'gross_value': self._get_text(wiersz, 'fa:P_11NettoVat')
            }
            items.append(item)

        return items

    def _parse_invoice_summary(self) -> Dict:
        """Parse invoice totals and summary"""
        summary = {}

        fa = self.root.find('.//fa:Fa', self.NS)
        if fa is not None:
            # Net totals by VAT rate
            summary['net_total'] = self._get_text(fa, 'fa:P_13_1')
            summary['vat_total'] = self._get_text(fa, 'fa:P_14_1')
            summary['gross_total'] = self._get_text(fa, 'fa:P_15')

            # Payment info
            summary['amount_due'] = self._get_text(fa, 'fa:P_16')
            summary['amount_paid'] = self._get_text(fa, 'fa:P_17', default='0.00')
            summary['amount_remaining'] = self._get_text(fa, 'fa:P_18', default=summary.get('amount_due', '0.00'))

        return summary

    def _parse_payment_info(self) -> Dict:
        """Parse payment details"""
        payment = {}

        platnosc = self.root.find('.//fa:Platnosc', self.NS)
        if platnosc is not None:
            payment['due_date'] = self._get_text(platnosc, 'fa:TerminPlatnosci')
            payment['method'] = self._get_text(platnosc, 'fa:FormaPlatnosci')

            # Bank account
            rachunek = platnosc.find('fa:RachunekBankowy', self.NS)
            if rachunek is not None:
                payment['account_number'] = self._get_text(rachunek, 'fa:NrRB')

        return payment

    def _parse_annotations(self) -> List[str]:
        """Parse invoice annotations/notes"""
        annotations = []

        adnotacje = self.root.findall('.//fa:Adnotacje/fa:P_16', self.NS)
        for adnotacja in adnotacje:
            text = adnotacja.text
            if text:
                annotations.append(text.strip())

        return annotations

    def _get_text(self, parent, tag: str, default: str = '') -> str:
        """
        Safely extract text from XML element

        Args:
            parent: Parent XML element
            tag: Child element tag (with namespace prefix)
            default: Default value if element not found

        Returns:
            Element text or default value
        """
        elem = parent.find(tag, self.NS)
        if elem is not None and elem.text:
            return elem.text.strip()
        return default


class InvoicePDFGenerator:
    """PDF generator for KSeF invoices following official visual template"""

    def __init__(self):
        """Initialize PDF generator"""
        if not REPORTLAB_AVAILABLE:
            raise ImportError("reportlab library not installed. Install with: pip install reportlab")

        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Setup custom paragraph styles for invoice"""
        # Header style
        self.styles.add(ParagraphStyle(
            name='InvoiceHeader',
            parent=self.styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#1a1a1a'),
            spaceAfter=12,
            alignment=1  # Center
        ))

        # Subheader style
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontSize=11,
            textColor=colors.HexColor('#333333'),
            spaceAfter=6,
            spaceBefore=12,
            textTransform='uppercase'
        ))

        # KSeF watermark style
        self.styles.add(ParagraphStyle(
            name='KSeFMark',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#666666'),
            alignment=2  # Right
        ))

    def generate(self, invoice_data: Dict, output_path: str = None) -> BytesIO:
        """
        Generate PDF from parsed invoice data

        Args:
            invoice_data: Parsed invoice data from InvoiceXMLParser
            output_path: Optional file path to save PDF (if None, returns BytesIO)

        Returns:
            BytesIO buffer with PDF content
        """
        buffer = BytesIO()

        # Create PDF document
        doc = SimpleDocTemplate(
            buffer if output_path is None else output_path,
            pagesize=A4,
            rightMargin=15*mm,
            leftMargin=15*mm,
            topMargin=15*mm,
            bottomMargin=15*mm
        )

        # Build PDF content
        story = []

        # KSeF watermark
        story.append(Paragraph("Faktura z systemu KSeF", self.styles['KSeFMark']))
        story.append(Spacer(1, 5*mm))

        # Invoice header
        story.extend(self._build_invoice_header(invoice_data))
        story.append(Spacer(1, 10*mm))

        # Seller and Buyer side by side
        story.extend(self._build_parties_section(invoice_data))
        story.append(Spacer(1, 10*mm))

        # Invoice items table
        story.extend(self._build_items_table(invoice_data))
        story.append(Spacer(1, 10*mm))

        # Summary section
        story.extend(self._build_summary_section(invoice_data))
        story.append(Spacer(1, 5*mm))

        # Payment info
        story.extend(self._build_payment_section(invoice_data))

        # Annotations
        if invoice_data.get('annotations'):
            story.append(Spacer(1, 5*mm))
            story.extend(self._build_annotations(invoice_data))

        # Build PDF
        doc.build(story)

        buffer.seek(0)
        logger.info(f"PDF generated successfully (size: {len(buffer.getvalue())} bytes)")

        return buffer

    def _build_invoice_header(self, data: Dict) -> List:
        """Build invoice header section"""
        elements = []
        header = data.get('invoice_header', {})

        # Main title
        invoice_type = "FAKTURA VAT"
        elements.append(Paragraph(invoice_type, self.styles['InvoiceHeader']))

        # Invoice number and dates
        info_data = [
            ['Numer faktury:', header.get('invoice_number', 'N/A')],
            ['Data wystawienia:', header.get('issue_date', 'N/A')],
            ['Data sprzedaży:', header.get('sale_date', 'N/A')],
        ]

        info_table = Table(info_data, colWidths=[50*mm, 80*mm])
        info_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))

        elements.append(info_table)

        return elements

    def _build_parties_section(self, data: Dict) -> List:
        """Build seller and buyer information section"""
        elements = []
        seller = data.get('seller', {})
        buyer = data.get('buyer', {})

        # Build seller and buyer info side by side
        parties_data = [[
            self._format_party_info('SPRZEDAWCA', seller),
            self._format_party_info('NABYWCA', buyer)
        ]]

        parties_table = Table(parties_data, colWidths=[90*mm, 90*mm])
        parties_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))

        elements.append(parties_table)

        return elements

    def _format_party_info(self, title: str, party: Dict) -> Paragraph:
        """Format party (seller/buyer) information as HTML"""
        address = party.get('address', {})

        html = f"<b>{title}</b><br/>"
        html += f"{party.get('name', 'N/A')}<br/>"
        html += f"NIP: {party.get('nip', 'N/A')}<br/>"

        # Address
        street = address.get('street', '')
        building = address.get('building_number', '')
        apartment = address.get('apartment_number', '')

        if street:
            html += f"{street} {building}"
            if apartment:
                html += f"/{apartment}"
            html += "<br/>"

        postal = address.get('postal_code', '')
        city = address.get('city', '')
        if city:
            html += f"{postal} {city}<br/>"

        return Paragraph(html, self.styles['Normal'])

    def _build_items_table(self, data: Dict) -> List:
        """Build invoice items table"""
        elements = []
        items = data.get('items', [])

        if not items:
            return elements

        # Table header
        header_data = [
            'Lp.',
            'Nazwa towaru/usługi',
            'Ilość',
            'J.m.',
            'Cena netto',
            'Wartość netto',
            'VAT %',
            'Kwota VAT',
            'Wartość brutto'
        ]

        # Table data
        table_data = [header_data]

        for item in items:
            row = [
                str(item.get('line_number', '')),
                item.get('name', ''),
                item.get('quantity', ''),
                item.get('unit', ''),
                self._format_amount(item.get('unit_price_net', '')),
                self._format_amount(item.get('net_value', '')),
                item.get('vat_rate', ''),
                self._format_amount(item.get('vat_amount', '')),
                self._format_amount(item.get('gross_value', ''))
            ]
            table_data.append(row)

        # Create table
        col_widths = [10*mm, 50*mm, 15*mm, 10*mm, 20*mm, 20*mm, 15*mm, 20*mm, 20*mm]
        items_table = Table(table_data, colWidths=col_widths)

        items_table.setStyle(TableStyle([
            # Header style
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),

            # Data style
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # Lp
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),    # Nazwa
            ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),  # Numbers

            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))

        elements.append(items_table)

        return elements

    def _build_summary_section(self, data: Dict) -> List:
        """Build invoice summary with totals"""
        elements = []
        summary = data.get('summary', {})
        header = data.get('invoice_header', {})
        currency = header.get('currency', 'PLN')

        summary_data = [
            ['Wartość netto:', f"{self._format_amount(summary.get('net_total', '0.00'))} {currency}"],
            ['VAT:', f"{self._format_amount(summary.get('vat_total', '0.00'))} {currency}"],
            ['<b>RAZEM DO ZAPŁATY:</b>', f"<b>{self._format_amount(summary.get('gross_total', '0.00'))} {currency}</b>"],
        ]

        summary_table = Table(summary_data, colWidths=[120*mm, 60*mm])
        summary_table.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black),
            ('TOPPADDING', (0, -1), (-1, -1), 8),
        ]))

        elements.append(summary_table)

        return elements

    def _build_payment_section(self, data: Dict) -> List:
        """Build payment information section"""
        elements = []
        payment = data.get('payment', {})

        if not payment:
            return elements

        elements.append(Paragraph("PŁATNOŚĆ", self.styles['SectionHeader']))

        payment_info = []

        if payment.get('due_date'):
            payment_info.append(['Termin płatności:', payment['due_date']])

        if payment.get('method'):
            payment_info.append(['Forma płatności:', payment['method']])

        if payment.get('account_number'):
            payment_info.append(['Numer konta:', payment['account_number']])

        if payment_info:
            payment_table = Table(payment_info, colWidths=[50*mm, 130*mm])
            payment_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            elements.append(payment_table)

        return elements

    def _build_annotations(self, data: Dict) -> List:
        """Build annotations/notes section"""
        elements = []
        annotations = data.get('annotations', [])

        if annotations:
            elements.append(Paragraph("UWAGI", self.styles['SectionHeader']))
            for annotation in annotations:
                elements.append(Paragraph(annotation, self.styles['Normal']))
                elements.append(Spacer(1, 2*mm))

        return elements

    def _format_amount(self, amount: str) -> str:
        """Format monetary amount with 2 decimal places"""
        try:
            return f"{float(amount):.2f}"
        except (ValueError, TypeError):
            return amount or '0.00'


def generate_invoice_pdf(xml_content: str, ksef_number: str = '', output_path: str = None) -> BytesIO:
    """
    Convenience function to generate PDF from KSeF invoice XML

    Args:
        xml_content: Raw XML string from KSeF API
        ksef_number: KSeF invoice number (optional, for metadata)
        output_path: Optional file path to save PDF

    Returns:
        BytesIO buffer with PDF content

    Example:
        >>> from app.ksef_client import KSeFClient
        >>> from app.invoice_pdf_generator import generate_invoice_pdf
        >>>
        >>> client = KSeFClient(config)
        >>> client.authenticate()
        >>>
        >>> result = client.get_invoice_xml("1234567890-20240101-ABCDEF123456-AB")
        >>> pdf_buffer = generate_invoice_pdf(
        ...     result['xml_content'],
        ...     ksef_number=result['ksef_number'],
        ...     output_path="faktura.pdf"
        ... )
    """
    # Parse XML
    parser = InvoiceXMLParser(xml_content)
    invoice_data = parser.parse()

    # Add KSeF number to metadata
    if ksef_number:
        invoice_data['ksef_metadata']['ksef_number'] = ksef_number

    # Generate PDF
    generator = InvoicePDFGenerator()
    pdf_buffer = generator.generate(invoice_data, output_path)

    return pdf_buffer
