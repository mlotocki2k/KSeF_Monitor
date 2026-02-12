"""
KSeF Invoice PDF Generator

Converts KSeF invoice XML (FA_VAT format) to PDF following KSeF visual template.
Based on FA_VAT schema from KSeF documentation.
Supports FA(2) schema (http://crd.gov.pl/wzor/2023/06/29/12648/) and older versions.

IMPORTANT: PDF contains ONLY data present in the source XML. No calculations,
no default values, no invented content.
"""

import logging
import os
import re
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

# Font registration (done once at module load)
_FONT_NAME = 'Helvetica'
_FONT_NAME_BOLD = 'Helvetica-Bold'

if REPORTLAB_AVAILABLE:
    _DEJAVU_PATHS = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    ]
    if os.path.exists(_DEJAVU_PATHS[0]):
        try:
            pdfmetrics.registerFont(TTFont('DejaVuSans', _DEJAVU_PATHS[0]))
            if os.path.exists(_DEJAVU_PATHS[1]):
                pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', _DEJAVU_PATHS[1]))
            _FONT_NAME = 'DejaVuSans'
            _FONT_NAME_BOLD = 'DejaVuSans-Bold' if os.path.exists(_DEJAVU_PATHS[1]) else 'DejaVuSans'
            logger.info("DejaVu Sans font registered for Polish character support")
        except Exception as e:
            logger.warning(f"Failed to register DejaVu Sans: {e}")
    else:
        logger.warning("DejaVu Sans not found - Polish characters may not render correctly. "
                       "Install fonts-dejavu-core package.")


class InvoiceXMLParser:
    """Parser for KSeF FA_VAT XML invoices with auto namespace detection"""

    def __init__(self, xml_content: str):
        self.xml_content = xml_content
        self.root = None
        self.NS = {}
        self.parsed_data = {}

    def parse(self) -> Dict:
        """Parse XML and extract invoice data"""
        try:
            self.root = ET.fromstring(self.xml_content)

            # Auto-detect namespace from root element
            ns_match = re.match(r'\{(.+?)\}', self.root.tag)
            if ns_match:
                self.NS = {'fa': ns_match.group(1)}
                logger.debug(f"Detected XML namespace: {ns_match.group(1)}")
            else:
                logger.warning("No namespace detected in XML root element")

            self.parsed_data = {
                'ksef_metadata': {'ksef_number': '', 'ksef_qr_code': ''},
                'invoice_header': self._parse_invoice_header(),
                'seller': self._parse_podmiot('Podmiot1'),
                'buyer': self._parse_podmiot('Podmiot2'),
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

    def _text(self, parent, *tags, default=''):
        """Get text from first matching tag path"""
        if parent is None:
            return default
        for tag in tags:
            elem = parent.find(tag, self.NS)
            if elem is not None and elem.text:
                return elem.text.strip()
        return default

    def _parse_invoice_header(self) -> Dict:
        """Parse invoice header — handles FA(2) schema.
        FA(2): P_1 = data wystawienia, P_6 = data sprzedazy/dostawy.
        """
        header = {}

        naglowek = self.root.find('.//fa:Naglowek', self.NS)
        fa = self.root.find('.//fa:Fa', self.NS)

        if naglowek is not None:
            header['invoice_type'] = self._text(naglowek, 'fa:KodFormularza')
            header['invoice_variant'] = self._text(naglowek, 'fa:WariantFormularza')
            # Try Naglowek for issue date
            header['issue_date'] = self._text(
                naglowek, 'fa:DataWystawieniaFaktury', 'fa:DataWystawienia')

        if fa is not None:
            # Invoice number: P_2
            header['invoice_number'] = self._text(fa, 'fa:P_2')
            # P_1 = Data wystawienia faktury (issue date in FA(2))
            if not header.get('issue_date'):
                header['issue_date'] = self._text(fa, 'fa:P_1')
            # P_6 = Data dokonania/zakończenia dostawy (sale/delivery date)
            header['sale_date'] = self._text(fa, 'fa:P_6')
            # Currency
            header['currency'] = self._text(fa, 'fa:KodWaluty')

        # Fallback: try NrFaktury in header
        if not header.get('invoice_number') and naglowek is not None:
            header['invoice_number'] = self._text(naglowek, 'fa:NrFaktury')

        return header

    def _parse_podmiot(self, podmiot_tag: str) -> Dict:
        """
        Parse Podmiot1 (seller) or Podmiot2 (buyer).
        FA(2): data is in DaneIdentyfikacyjne sub-element.
        """
        subject = {}
        podmiot = self.root.find(f'.//fa:{podmiot_tag}', self.NS)
        if podmiot is None:
            return subject

        # FA(2): NIP/Nazwa inside DaneIdentyfikacyjne
        dane = podmiot.find('fa:DaneIdentyfikacyjne', self.NS)
        if dane is not None:
            subject['nip'] = self._text(dane, 'fa:NIP')
            subject['name'] = self._text(dane, 'fa:NazwaHandlowa', 'fa:Nazwa')
        else:
            # Fallback: direct children or nested Sprzedawca/Nabywca
            for path in [podmiot_tag, 'fa:Sprzedawca', 'fa:Nabywca']:
                sub = podmiot.find(f'fa:{path}', self.NS) if path != podmiot_tag else podmiot
                nip = self._text(sub, 'fa:NIP')
                if nip:
                    subject['nip'] = nip
                    subject['name'] = self._text(sub, 'fa:NazwaHandlowa', 'fa:Nazwa')
                    break

        # Parse address
        subject['address'] = self._parse_address(podmiot)

        return subject

    def _parse_address(self, parent) -> Dict:
        """Parse address — handles AdresL (simplified) and AdresPol (structured) formats"""
        address = {}
        adres = parent.find('fa:Adres', self.NS)
        if adres is None:
            return address

        address['country'] = self._text(adres, 'fa:KodKraju')

        # Try simplified format (AdresL1/AdresL2) — common in FA(2)
        line1 = self._text(adres, 'fa:AdresL1')
        line2 = self._text(adres, 'fa:AdresL2')

        if line1 or line2:
            address['line1'] = line1
            address['line2'] = line2
            return address

        # Try structured format (direct or inside AdresPol/AdresZagr)
        for prefix_path in ['', 'fa:AdresPol/', 'fa:AdresZagr/']:
            ulica = self._text(adres, f'{prefix_path}fa:Ulica')
            miejscowosc = self._text(adres, f'{prefix_path}fa:Miejscowosc')

            if ulica or miejscowosc:
                nr_domu = self._text(adres, f'{prefix_path}fa:NrDomu')
                nr_lokalu = self._text(adres, f'{prefix_path}fa:NrLokalu')
                kod = self._text(adres, f'{prefix_path}fa:KodPocztowy')

                street_line = ulica
                if nr_domu:
                    street_line += f' {nr_domu}'
                if nr_lokalu:
                    street_line += f'/{nr_lokalu}'

                address['line1'] = street_line
                address['line2'] = f'{kod} {miejscowosc}'.strip()
                return address

        return address

    def _parse_invoice_items(self) -> List[Dict]:
        """Parse invoice line items — only fields present in XML"""
        items = []
        wiersze = self.root.findall('.//fa:Fa/fa:FaWiersz', self.NS)

        for idx, wiersz in enumerate(wiersze, 1):
            item = {
                'line_number': idx,
                'name': self._text(wiersz, 'fa:P_7'),
                'quantity': self._text(wiersz, 'fa:P_8A'),
                'unit': self._text(wiersz, 'fa:P_8B'),
                'unit_price_net': self._text(wiersz, 'fa:P_9A'),
                'net_value': self._text(wiersz, 'fa:P_11'),
                'vat_rate': self._text(wiersz, 'fa:P_12'),
                'vat_amount': self._text(wiersz, 'fa:P_11Vat'),
                'gross_value': self._text(wiersz, 'fa:P_11NettoVat')
            }
            items.append(item)

        return items

    def _parse_invoice_summary(self) -> Dict:
        """Parse invoice totals"""
        summary = {}
        fa = self.root.find('.//fa:Fa', self.NS)
        if fa is not None:
            summary['net_total'] = self._text(fa, 'fa:P_13_1')
            summary['vat_total'] = self._text(fa, 'fa:P_14_1')
            summary['gross_total'] = self._text(fa, 'fa:P_15')
        return summary

    def _parse_payment_info(self) -> Dict:
        """Parse payment details — handles FA(2) nested structure.
        In FA(2), FormaPlatnosci/TerminPlatnosci may be inside ZaplataF sub-element.
        """
        payment = {}

        # Platnosc is inside Fa in FA(2)
        platnosc = self.root.find('.//fa:Fa/fa:Platnosc', self.NS)
        if platnosc is None:
            platnosc = self.root.find('.//fa:Platnosc', self.NS)
        if platnosc is None:
            return payment

        # Zaplacono flag (1=tak, 2=nie)
        zaplacono = self._text(platnosc, 'fa:Zaplacono')
        if zaplacono == '1':
            payment['paid'] = 'Tak'
        elif zaplacono == '2':
            payment['paid'] = 'Nie'

        # FormaPlatnosci — try direct and inside ZaplataF
        method_code = self._text(
            platnosc,
            'fa:FormaPlatnosci',
            'fa:ZaplataF/fa:FormaPlatnosci')
        if method_code:
            payment_methods = {
                '1': 'Gotówka', '2': 'Karta', '3': 'Bon',
                '4': 'Czek', '5': 'Kredyt', '6': 'Przelew',
            }
            payment['method'] = payment_methods.get(method_code, method_code)

        # TerminPlatnosci — try direct, nested Termin, and inside ZaplataF
        due_date = self._text(
            platnosc,
            'fa:TerminPlatnosci/fa:Termin',
            'fa:TerminPlatnosci',
            'fa:ZaplataF/fa:TerminPlatnosci')
        if due_date:
            payment['due_date'] = due_date

        # RachunekBankowy
        rachunek = platnosc.find('fa:RachunekBankowy', self.NS)
        if rachunek is None:
            rachunek = platnosc.find('fa:RachunekBankowyFaktury', self.NS)
        if rachunek is not None:
            nr_rb = self._text(rachunek, 'fa:NrRB')
            if nr_rb:
                payment['account_number'] = nr_rb
            bank_name = self._text(rachunek, 'fa:NazwaBanku')
            if bank_name:
                payment['bank_name'] = bank_name

        return payment

    def _parse_annotations(self) -> List[str]:
        """Parse invoice annotations/notes"""
        annotations = []
        # In FA(2), Adnotacje is inside Fa
        adnotacje = self.root.find('.//fa:Fa/fa:Adnotacje', self.NS)
        if adnotacje is None:
            adnotacje = self.root.find('.//fa:Adnotacje', self.NS)
        if adnotacje is None:
            return annotations

        for child in adnotacje:
            if child.text and child.text.strip() and not child.text.strip().isdigit():
                annotations.append(child.text.strip())

        return annotations


class InvoicePDFGenerator:
    """PDF generator for KSeF invoices following official visual template.
    Only renders data present in the parsed XML — no calculations or defaults.
    """

    # Available width: A4 (210mm) - 12mm margins each side = 186mm
    USABLE_WIDTH = 186 * mm

    def __init__(self):
        if not REPORTLAB_AVAILABLE:
            raise ImportError("reportlab library not installed. Install with: pip install reportlab")

        self.font = _FONT_NAME
        self.font_bold = _FONT_NAME_BOLD
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Setup custom paragraph styles for invoice"""
        self.styles.add(ParagraphStyle(
            name='InvoiceHeader',
            fontName=self.font_bold,
            fontSize=16,
            textColor=colors.HexColor('#1a1a1a'),
            spaceAfter=12,
            alignment=1
        ))
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            fontName=self.font_bold,
            fontSize=11,
            textColor=colors.HexColor('#333333'),
            spaceAfter=6,
            spaceBefore=12,
        ))
        self.styles.add(ParagraphStyle(
            name='KSeFMark',
            fontName=self.font,
            fontSize=8,
            textColor=colors.HexColor('#666666'),
            alignment=2
        ))
        self.styles.add(ParagraphStyle(
            name='PartyInfo',
            fontName=self.font,
            fontSize=9,
            leading=12,
        ))
        self.styles.add(ParagraphStyle(
            name='SummaryNormal',
            fontName=self.font,
            fontSize=11,
            alignment=2,
        ))
        self.styles.add(ParagraphStyle(
            name='SummaryBold',
            fontName=self.font_bold,
            fontSize=12,
            alignment=2,
        ))
        self.styles.add(ParagraphStyle(
            name='TableHeader',
            fontName=self.font_bold,
            fontSize=7,
            leading=9,
            alignment=1,
        ))
        self.styles.add(ParagraphStyle(
            name='TableCell',
            fontName=self.font,
            fontSize=7,
            leading=9,
        ))
        self.styles.add(ParagraphStyle(
            name='TableCellRight',
            fontName=self.font,
            fontSize=7,
            leading=9,
            alignment=2,
        ))
        self.styles.add(ParagraphStyle(
            name='TableCellCenter',
            fontName=self.font,
            fontSize=7,
            leading=9,
            alignment=1,
        ))

    def generate(self, invoice_data: Dict, output_path: str = None) -> BytesIO:
        """Generate PDF from parsed invoice data"""
        buffer = BytesIO()

        doc = SimpleDocTemplate(
            buffer if output_path is None else output_path,
            pagesize=A4,
            rightMargin=12*mm,
            leftMargin=12*mm,
            topMargin=15*mm,
            bottomMargin=15*mm
        )

        story = []

        # KSeF watermark
        ksef_num = invoice_data.get('ksef_metadata', {}).get('ksef_number', '')
        ksef_text = f"Faktura z systemu KSeF: {ksef_num}" if ksef_num else "Faktura z systemu KSeF"
        story.append(Paragraph(ksef_text, self.styles['KSeFMark']))
        story.append(Spacer(1, 5*mm))

        story.extend(self._build_invoice_header(invoice_data))
        story.append(Spacer(1, 10*mm))

        story.extend(self._build_parties_section(invoice_data))
        story.append(Spacer(1, 10*mm))

        story.extend(self._build_items_table(invoice_data))
        story.append(Spacer(1, 10*mm))

        story.extend(self._build_summary_section(invoice_data))
        story.append(Spacer(1, 5*mm))

        story.extend(self._build_payment_section(invoice_data))

        if invoice_data.get('annotations'):
            story.append(Spacer(1, 5*mm))
            story.extend(self._build_annotations(invoice_data))

        doc.build(story)

        buffer.seek(0)
        logger.info(f"PDF generated successfully (size: {len(buffer.getvalue())} bytes)")

        return buffer

    def _build_invoice_header(self, data: Dict) -> List:
        """Build invoice header section — only rows with data from XML"""
        elements = []
        header = data.get('invoice_header', {})

        elements.append(Paragraph("FAKTURA VAT", self.styles['InvoiceHeader']))

        info_data = []
        if header.get('invoice_number'):
            info_data.append(['Numer faktury:', header['invoice_number']])
        if header.get('issue_date'):
            info_data.append(['Data wystawienia:', header['issue_date']])
        if header.get('sale_date'):
            info_data.append(['Data sprzedazy:', header['sale_date']])

        if info_data:
            info_table = Table(info_data, colWidths=[50*mm, 80*mm])
            info_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (0, -1), self.font_bold),
                ('FONTNAME', (1, 0), (1, -1), self.font),
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

        parties_data = [[
            self._format_party_info('SPRZEDAWCA', seller),
            self._format_party_info('NABYWCA', buyer)
        ]]

        parties_table = Table(parties_data, colWidths=[93*mm, 93*mm])
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
        """Format party (seller/buyer) information — only data from XML"""
        address = party.get('address', {})

        html = f"<b>{title}</b><br/>"

        name = party.get('name', '')
        if name:
            html += f"{name}<br/>"

        nip = party.get('nip', '')
        if nip:
            html += f"NIP: {nip}<br/>"

        line1 = address.get('line1', '')
        line2 = address.get('line2', '')
        if line1:
            html += f"{line1}<br/>"
        if line2:
            html += f"{line2}<br/>"

        return Paragraph(html, self.styles['PartyInfo'])

    def _build_items_table(self, data: Dict) -> List:
        """Build invoice items table — only columns that have data in XML"""
        elements = []
        items = data.get('items', [])

        if not items:
            return elements

        # Determine which optional columns actually have data in XML
        has_unit = any(item.get('unit') for item in items)
        has_unit_price = any(item.get('unit_price_net') for item in items)
        has_vat_rate = any(item.get('vat_rate') for item in items)
        has_vat_amount = any(item.get('vat_amount') for item in items)
        has_gross_value = any(item.get('gross_value') for item in items)

        # Build column definitions: (header_label, field_key, fixed_width_mm, align)
        # width=None means this column fills remaining space
        columns = [
            ('Lp.', 'line_number', 8, 'center'),
            ('Nazwa towaru/uslugi', 'name', None, 'left'),
            ('Ilosc', 'quantity', 13, 'right'),
        ]
        if has_unit:
            columns.append(('J.m.', 'unit', 11, 'center'))
        if has_unit_price:
            columns.append(('Cena netto', 'unit_price_net', 22, 'right'))
        columns.append(('Wartosc netto', 'net_value', 24, 'right'))
        if has_vat_rate:
            columns.append(('VAT %', 'vat_rate', 13, 'center'))
        if has_vat_amount:
            columns.append(('Kwota VAT', 'vat_amount', 22, 'right'))
        if has_gross_value:
            columns.append(('Wartosc brutto', 'gross_value', 24, 'right'))

        # Calculate name column width = remaining space after fixed columns
        fixed_total = sum(c[2] for c in columns if c[2] is not None)
        name_width_mm = (self.USABLE_WIDTH / mm) - fixed_total

        # Build header row using Paragraph for text wrapping
        header_row = []
        col_widths = []
        for label, _, width_mm, _ in columns:
            header_row.append(Paragraph(label, self.styles['TableHeader']))
            col_widths.append((width_mm if width_mm is not None else name_width_mm) * mm)

        table_data = [header_row]

        # Amount fields that should be formatted with 2 decimal places
        amount_fields = {'unit_price_net', 'net_value', 'vat_amount', 'gross_value'}

        for item in items:
            row = []
            for _, field, _, align in columns:
                value = str(item.get(field, ''))
                if field in amount_fields and value:
                    value = self._format_amount(value)

                if field == 'name':
                    row.append(Paragraph(value, self.styles['TableCell']))
                elif align == 'right':
                    row.append(Paragraph(value, self.styles['TableCellRight']))
                elif align == 'center':
                    row.append(Paragraph(value, self.styles['TableCellCenter']))
                else:
                    row.append(Paragraph(value, self.styles['TableCell']))
            table_data.append(row)

        items_table = Table(table_data, colWidths=col_widths)

        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
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
        """Build invoice summary with totals — only values present in XML"""
        elements = []
        summary = data.get('summary', {})
        header = data.get('invoice_header', {})
        currency = header.get('currency', '')
        currency_suffix = f' {currency}' if currency else ''

        summary_data = []

        net = summary.get('net_total', '')
        if net:
            summary_data.append([
                Paragraph('Wartosc netto:', self.styles['SummaryNormal']),
                Paragraph(f'{self._format_amount(net)}{currency_suffix}', self.styles['SummaryNormal'])
            ])

        vat = summary.get('vat_total', '')
        if vat:
            summary_data.append([
                Paragraph('VAT:', self.styles['SummaryNormal']),
                Paragraph(f'{self._format_amount(vat)}{currency_suffix}', self.styles['SummaryNormal'])
            ])

        gross = summary.get('gross_total', '')
        if gross:
            summary_data.append([
                Paragraph('RAZEM DO ZAPLATY:', self.styles['SummaryBold']),
                Paragraph(f'{self._format_amount(gross)}{currency_suffix}', self.styles['SummaryBold'])
            ])

        if summary_data:
            summary_table = Table(summary_data, colWidths=[120*mm, 66*mm])
            summary_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black),
                ('TOPPADDING', (0, -1), (-1, -1), 8),
            ]))
            elements.append(summary_table)

        return elements

    def _build_payment_section(self, data: Dict) -> List:
        """Build payment information section — only data present in XML"""
        elements = []
        payment = data.get('payment', {})

        # Build rows only from data actually present
        payment_info = []

        if payment.get('method'):
            payment_info.append(['Forma platnosci:', payment['method']])
        if payment.get('due_date'):
            payment_info.append(['Termin platnosci:', payment['due_date']])
        if payment.get('paid'):
            payment_info.append(['Zaplacono:', payment['paid']])
        if payment.get('account_number'):
            account = payment['account_number']
            if payment.get('bank_name'):
                account = f"{payment['bank_name']}: {account}"
            payment_info.append(['Numer konta:', account])

        # Don't show section header if there's no useful payment data
        if not payment_info:
            return elements

        elements.append(Paragraph("PLATNOSC", self.styles['SectionHeader']))

        payment_table = Table(payment_info, colWidths=[50*mm, 136*mm])
        payment_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), self.font_bold),
            ('FONTNAME', (1, 0), (1, -1), self.font),
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
        """Format monetary amount with 2 decimal places.
        Returns empty string if no data.
        """
        if not amount:
            return ''
        try:
            return f"{float(amount):.2f}"
        except (ValueError, TypeError):
            return amount


def generate_invoice_pdf(xml_content: str, ksef_number: str = '', output_path: str = None) -> BytesIO:
    """
    Convenience function to generate PDF from KSeF invoice XML

    Args:
        xml_content: Raw XML string from KSeF API
        ksef_number: KSeF invoice number (optional, for metadata)
        output_path: Optional file path to save PDF

    Returns:
        BytesIO buffer with PDF content
    """
    parser = InvoiceXMLParser(xml_content)
    invoice_data = parser.parse()

    if ksef_number:
        invoice_data['ksef_metadata']['ksef_number'] = ksef_number

    generator = InvoicePDFGenerator()
    pdf_buffer = generator.generate(invoice_data, output_path)

    return pdf_buffer
