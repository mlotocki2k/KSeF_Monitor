"""
KSeF Invoice PDF Generator (ReportLab fallback)

Generates PDF from KSeF invoice XML using ReportLab.
Used as fallback when xhtml2pdf template rendering is unavailable or fails.

Constants, font registration, and XML parser have been extracted to:
  - app/pdf_constants.py (shared constants, font registration)
  - app/invoice_xml_parser.py (InvoiceXMLParser class)

Schema references:
  XSD: http://crd.gov.pl/wzor/2025/06/25/13775/schemat.xsd
  XSL: http://crd.gov.pl/wzor/2025/06/25/13775/styl.xsl

PDF contains ONLY data present in the source XML. No calculations, no defaults.
"""

import base64
import hashlib
import html
import logging
from datetime import datetime
from typing import Dict, Optional, List
from io import BytesIO

try:
    import pytz
    PYTZ_AVAILABLE = True
except ImportError:
    PYTZ_AVAILABLE = False

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    )
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False

logger = logging.getLogger(__name__)

# Import shared constants and utilities from pdf_constants module
from .pdf_constants import (
    VAT_RATE_LABELS, PAYMENT_METHODS, INVOICE_TYPE_TITLES, QR_BASE_URLS,
    VAT_SUMMARY_ROWS, _P12_TO_P13, _resolve_vat_summary_labels,
    FONT_NAME, FONT_NAME_BOLD,
)

# Import XML parser from dedicated module
from .invoice_xml_parser import InvoiceXMLParser

# Re-export for backward compatibility (existing code imports these from here)
__all__ = [
    'InvoiceXMLParser', 'InvoicePDFGenerator', 'generate_invoice_pdf',
    'VAT_RATE_LABELS', 'PAYMENT_METHODS', 'INVOICE_TYPE_TITLES',
    'QR_BASE_URLS', 'VAT_SUMMARY_ROWS', '_resolve_vat_summary_labels',
    'REPORTLAB_AVAILABLE',
]

# Backward-compatible font name aliases (used by invoice_pdf_template.py)
_FONT_NAME = FONT_NAME
_FONT_NAME_BOLD = FONT_NAME_BOLD


class InvoicePDFGenerator:
    """Generates PDF following official KSeF XSL layout."""

    def __init__(self):
        if not REPORTLAB_AVAILABLE:
            raise ImportError("reportlab not installed")
        self.USABLE_WIDTH = 186 * mm  # A4 (210mm) - 12mm margins each side
        self.font = _FONT_NAME
        self.font_bold = _FONT_NAME_BOLD
        self.styles = getSampleStyleSheet()
        self._setup_styles()

    def _setup_styles(self):
        add = self.styles.add
        add(ParagraphStyle('Title1', fontName=self.font_bold, fontSize=14,
                           alignment=1, spaceAfter=6))
        add(ParagraphStyle('Title2', fontName=self.font_bold, fontSize=11,
                           alignment=1, spaceAfter=4))
        add(ParagraphStyle('KSeFMark', fontName=self.font_bold, fontSize=8,
                           textColor=colors.HexColor('#333333')))
        add(ParagraphStyle('Section', fontName=self.font_bold, fontSize=10,
                           spaceBefore=8, spaceAfter=4))
        add(ParagraphStyle('FieldLabel', fontName=self.font, fontSize=9, leading=11))
        add(ParagraphStyle('FieldValue', fontName=self.font_bold, fontSize=9, leading=11))
        add(ParagraphStyle('PartyInfo', fontName=self.font, fontSize=9, leading=12))
        add(ParagraphStyle('TH', fontName=self.font_bold, fontSize=7, leading=9, alignment=1))
        add(ParagraphStyle('TD', fontName=self.font, fontSize=7, leading=9))
        add(ParagraphStyle('TDR', fontName=self.font, fontSize=7, leading=9, alignment=2))
        add(ParagraphStyle('TDC', fontName=self.font, fontSize=7, leading=9, alignment=1))
        add(ParagraphStyle('SumLabel', fontName=self.font, fontSize=10, alignment=2))
        add(ParagraphStyle('SumBold', fontName=self.font_bold, fontSize=11, alignment=2))
        add(ParagraphStyle('Small', fontName=self.font, fontSize=8, leading=10))
        add(ParagraphStyle('SmallBold', fontName=self.font_bold, fontSize=8, leading=10))

    def generate(self, data: Dict, output_path: str = None,
                 xml_content: str = '', environment: str = '',
                 timezone: str = '') -> BytesIO:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer if output_path is None else output_path,
            pagesize=A4, rightMargin=12*mm, leftMargin=12*mm,
            topMargin=12*mm, bottomMargin=18*mm)

        story = []
        story.extend(self._ksef_branding(data))

        # Build title + info block, with QR code on the right if available
        title_info = self._invoice_title(data) + self._invoice_info(data)
        qr_img = self._build_qr_image(data, xml_content, environment)

        if qr_img and title_info:
            qr_size = 30 * mm
            # Pack title+info elements into inner table (one row per element)
            left_rows = [[el] for el in title_info]
            left_tbl = Table(left_rows,
                             colWidths=[self.USABLE_WIDTH - qr_size - 4*mm])
            left_tbl.setStyle(TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 1),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
            ]))
            # QR with label underneath
            ksef_num = data.get('ksef_metadata', {}).get('ksef_number', '')
            label_para = Paragraph(ksef_num or '', self.styles['Small'])
            qr_inner = Table(
                [[qr_img], [label_para]],
                colWidths=[qr_size],
            )
            qr_inner.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            t = Table(
                [[left_tbl, qr_inner]],
                colWidths=[self.USABLE_WIDTH - qr_size - 2*mm, qr_size + 2*mm],
            )
            t.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            story.append(t)
        else:
            story.extend(title_info)

        story.append(Spacer(1, 6*mm))
        story.extend(self._parties(data))
        story.extend(self._podmiot3_section(data))
        story.extend(self._correction_info(data))
        story.append(Spacer(1, 6*mm))
        story.extend(self._items_table(data))
        story.append(Spacer(1, 4*mm))
        story.extend(self._vat_summary(data))
        story.append(Spacer(1, 4*mm))
        story.extend(self._total_amount(data))
        story.extend(self._rozliczenie_section(data))
        story.append(Spacer(1, 4*mm))
        story.extend(self._zaliczki_section(data))
        story.extend(self._payment(data))
        story.extend(self._annotations(data))
        story.extend(self._dodatkowy_opis_section(data))
        story.extend(self._warunki_transakcji_section(data))
        story.extend(self._zamowienie_section(data))
        story.extend(self._zalacznik_section(data))
        story.extend(self._footer(data))

        page_footer = self._make_page_footer(timezone)
        doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
        buffer.seek(0)
        logger.info(f"PDF generated ({len(buffer.getvalue())} bytes)")
        return buffer

    # --- Section builders ---

    def _ksef_branding(self, data: Dict) -> List:
        ksef_num = data.get('ksef_metadata', {}).get('ksef_number', '')
        if ksef_num:
            branding_para = Paragraph(
                f'Krajowy System <font color="red">e</font>-Faktur '
                f'(KS<font color="red">e</font>F): {ksef_num}',
                self.styles['KSeFMark'])
        else:
            branding_para = Paragraph(
                'Krajowy System <font color="red">e</font>-Faktur '
                '(KS<font color="red">e</font>F)',
                self.styles['KSeFMark'])
        return [branding_para, Spacer(1, 3*mm)]

    def _invoice_title(self, data: Dict) -> List:
        h = data.get('header', {})
        rodzaj = h.get('rodzaj', 'VAT')
        title = INVOICE_TYPE_TITLES.get(rodzaj, 'Faktura')

        elements = [Paragraph(title, self.styles['Title1'])]

        kod = h.get('kod_formularza', '')
        wariant = h.get('wariant', '')
        if kod:
            elements.append(Paragraph(f'{kod} ({wariant})', self.styles['Title2']))

        return elements

    def _invoice_info(self, data: Dict) -> List:
        h = data.get('header', {})
        rows = []

        def add_row(label, value):
            if value:
                rows.append([
                    Paragraph(label, self.styles['FieldLabel']),
                    Paragraph(f'<b>{self._rl_escape(value)}</b>', self.styles['FieldValue'])
                ])

        add_row('Kod waluty:', h.get('kod_waluty'))
        add_row('Numer faktury:', h.get('p2'))
        add_row('Data wystawienia:', h.get('p1'))
        add_row('Miejsce wystawienia:', h.get('p1m'))
        if h.get('p6'):
            add_row('Data dokonania dostawy / wykonania us\u0142ugi:', h.get('p6'))
        if h.get('p6_od') or h.get('p6_do'):
            add_row('Okres faktury od:', h.get('p6_od'))
            add_row('Okres faktury do:', h.get('p6_do'))

        if not rows:
            return []
        t = Table(rows, colWidths=[70*mm, 116*mm])
        t.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 1),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ]))
        return [t]

    def _parties(self, data: Dict) -> List:
        seller = data.get('seller', {})
        buyer = data.get('buyer', {})
        party_data = [[
            self._party_html('<b>SPRZEDAWCA</b>', seller),
            self._party_html('<b>NABYWCA</b>', buyer)
        ]]
        t = Table(party_data, colWidths=[93*mm, 93*mm])
        t.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        return [t]

    @staticmethod
    def _rl_escape(value) -> str:
        """Escape special chars for ReportLab Paragraph XML parser.

        ReportLab Paragraph uses an internal XML/SAX parser that requires
        &amp; for literal ampersands, &lt;/&gt; for angle brackets, etc.
        Without this, raw '&' in company names causes SAXParseException.
        """
        return html.escape(str(value), quote=False) if value else ''

    def _party_html(self, title: str, p: Dict) -> 'Paragraph':
        e = self._rl_escape
        h = f'<b>{title}</b><br/>'
        if p.get('nip'):
            prefix = f"{e(p['prefiks'])} " if p.get('prefiks') else ''
            h += f'NIP: {prefix}<b>{e(p["nip"])}</b><br/>'
        if p.get('kod_ue') and p.get('nr_vat_ue'):
            h += f'VAT UE: {e(p["kod_ue"])} {e(p["nr_vat_ue"])}<br/>'
        if p.get('nr_id'):
            h += f'ID: {e(p.get("kod_kraju_id", ""))} {e(p["nr_id"])}<br/>'
        if p.get('nazwa'):
            h += f'{e(p["nazwa"])}<br/>'
        if p.get('kod_kraju'):
            h += f'Kod kraju: {e(p["kod_kraju"])}<br/>'
        if p.get('adres_l1'):
            h += f'{e(p["adres_l1"])}'
            if p.get('adres_l2'):
                h += f' {e(p["adres_l2"])}'
            h += '<br/>'
        if p.get('nr_eori'):
            h += f'EORI: {e(p["nr_eori"])}<br/>'
        if p.get('gln'):
            h += f'GLN: {e(p["gln"])}<br/>'
        if p.get('email'):
            h += f'Email: {e(p["email"])}<br/>'
        if p.get('telefon'):
            h += f'Tel: {e(p["telefon"])}<br/>'
        return Paragraph(h, self.styles['PartyInfo'])

    def _items_table(self, data: Dict) -> List:
        items = data.get('items', [])
        if not items:
            return []

        # Determine which columns have data
        def has(field):
            return any(it.get(field) for it in items)

        # Column definitions: (header, field, width_mm, align, is_amount)
        cols = [('Lp.', 'nr', 7, 'c', False)]
        cols.append(('Nazwa (rodzaj) towaru lub us\u0142ugi', 'p7', None, 'l', False))
        if has('indeks'):
            cols.append(('Indeks', 'indeks', 15, 'l', False))
        if has('p8a'):
            cols.append(('J.m.', 'p8a', 10, 'c', False))
        if has('p8b'):
            cols.append(('Ilo\u015b\u0107', 'p8b', 13, 'r', True))
        if has('p9a'):
            cols.append(('Cena jedn.\nnetto', 'p9a', 22, 'r', True))
        if has('p9b'):
            cols.append(('Cena jedn.\nbrutto', 'p9b', 22, 'r', True))
        if has('p10'):
            cols.append(('Rabaty/\nopusty', 'p10', 16, 'r', True))
        if has('p11'):
            cols.append(('Wart.\nnetto', 'p11', 22, 'r', True))
        if has('p11a'):
            cols.append(('Wart.\nbrutto', 'p11a', 22, 'r', True))
        if has('p11vat'):
            cols.append(('Kwota VAT', 'p11vat', 20, 'r', True))
        if has('p12'):
            cols.append(('Stawka\nVAT', 'p12', 16, 'c', False))
        if has('p6a'):
            cols.append(('Data\ndost.', 'p6a', 18, 'c', False))

        # Calculate name column width
        fixed = sum(c[2] for c in cols if c[2] is not None)
        name_w = (self.USABLE_WIDTH / mm) - fixed

        header_row = []
        widths = []
        for label, _, w, _, _ in cols:
            header_row.append(Paragraph(label, self.styles['TH']))
            widths.append((w if w is not None else name_w) * mm)

        tdata = [header_row]
        for item in items:
            row = []
            for _, field, _, align, is_amt in cols:
                val = item.get(field, '')
                if is_amt and val:
                    val = self._fmt_amt(val)
                if field == 'p12' and val:
                    val = VAT_RATE_LABELS.get(val, val)
                style = self.styles['TDR'] if align == 'r' else (
                    self.styles['TDC'] if align == 'c' else self.styles['TD'])
                row.append(Paragraph(self._rl_escape(val), style))
            tdata.append(row)

        t = Table(tdata, colWidths=widths)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 2),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        return [t]

    def _vat_summary(self, data: Dict) -> List:
        vs = data.get('vat_summary', {})
        if not vs:
            return []

        resolved = _resolve_vat_summary_labels(data.get('items', []))
        has_w = any(vs.get(f'P_14_{s}W') for s in ('1', '2', '3', '4'))

        elements = [Paragraph('Podliczenie VAT', self.styles['Section'])]

        header = [
            Paragraph('Stawka VAT', self.styles['TH']),
            Paragraph('Warto\u015b\u0107 netto', self.styles['TH']),
            Paragraph('Kwota VAT', self.styles['TH']),
        ]
        if has_w:
            header.append(Paragraph('Kwota VAT (PLN)', self.styles['TH']))
        tdata = [header]

        for label, p13_field, p14_field, p14w_field in VAT_SUMMARY_ROWS:
            net = vs.get(p13_field)
            if not net:
                continue
            display_label = resolved.get(p13_field, label)
            vat = vs.get(p14_field, '') if p14_field else ''
            row = [
                Paragraph(display_label, self.styles['TDC']),
                Paragraph(self._fmt_amt(net), self.styles['TDR']),
                Paragraph(self._fmt_amt(vat) if vat else '', self.styles['TDR']),
            ]
            if has_w:
                vat_w = vs.get(p14w_field, '') if p14w_field else ''
                row.append(Paragraph(self._fmt_amt(vat_w) if vat_w else '', self.styles['TDR']))
            tdata.append(row)

        if len(tdata) <= 1:
            return []

        col_w = [35*mm, 38*mm, 38*mm]
        if has_w:
            col_w.append(38*mm)
        t = Table(tdata, colWidths=col_w)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(t)
        return elements

    def _total_amount(self, data: Dict) -> List:
        h = data.get('header', {})
        p15 = h.get('p15')
        if not p15:
            return []

        currency = self._rl_escape(h.get('kod_waluty', ''))
        currency_suffix = f' {currency}' if currency else ''

        rodzaj = h.get('rodzaj', 'VAT')
        if rodzaj in ('ZAL', 'KOR_ZAL'):
            label = 'Otrzymana kwota zap\u0142aty:'
        elif rodzaj in ('ROZ', 'KOR_ROZ'):
            label = 'Kwota pozosta\u0142a do zap\u0142aty:'
        else:
            label = 'Kwota nale\u017cno\u015bci og\u00f3\u0142em:'

        tdata = [[
            Paragraph(f'<b>{label}</b>', self.styles['SumBold']),
            Paragraph(f'<b>{self._fmt_amt(p15)}{currency_suffix}</b>', self.styles['SumBold']),
        ]]
        t = Table(tdata, colWidths=[120*mm, 66*mm])
        t.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('LINEABOVE', (0, 0), (-1, 0), 1, colors.black),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
        ]))

        elements = [t]

        # Exchange rate note
        kurs = h.get('kurs_waluty_z')
        if kurs and currency:
            elements.append(Paragraph(
                f'Kurs waluty: {kurs} PLN/{currency}', self.styles['Small']))

        return elements

    def _payment(self, data: Dict) -> List:
        pay = data.get('payment', {})
        if not pay:
            return []

        elements = [Paragraph('P\u0142atno\u015b\u0107', self.styles['Section'])]
        rows = []

        def add(label, value):
            if value:
                rows.append([
                    Paragraph(label, self.styles['SmallBold']),
                    Paragraph(self._rl_escape(value), self.styles['Small'])
                ])

        # Paid flag
        if pay.get('zaplacono') == '1':
            add('Zap\u0142acono:', 'Tak')
            add('Data zap\u0142aty:', pay.get('data_zaplaty', ''))

        # Payment form
        forma = pay.get('forma')
        if forma:
            add('Forma p\u0142atno\u015bci:', PAYMENT_METHODS.get(forma, forma))
        if pay.get('platnosc_inna') == '1':
            add('Inna forma p\u0142atno\u015bci:', pay.get('opis_platnosci', ''))

        # Payment terms
        for termin in pay.get('terminy', []):
            add('Termin p\u0142atno\u015bci:', termin.get('termin', ''))

        # Bank accounts
        for r in pay.get('rachunki', []):
            nr = r.get('nr_rb', '')
            if r.get('swift'):
                nr += f' (SWIFT: {r["swift"]})'
            add('Rachunek bankowy:', nr)
            if r.get('nazwa_banku'):
                add('Bank:', r['nazwa_banku'])
            if r.get('opis'):
                add('Opis rachunku:', r['opis'])

        # Factor accounts
        for r in pay.get('rachunki_faktora', []):
            nr = r.get('nr_rb', '')
            if r.get('swift'):
                nr += f' (SWIFT: {r["swift"]})'
            add('Rachunek faktora:', nr)
            if r.get('nazwa_banku'):
                add('Bank faktora:', r['nazwa_banku'])

        # Partial payments
        if pay.get('zaplaty_czesciowe'):
            elements.append(Paragraph('Zap\u0142aty cz\u0119\u015bciowe', self.styles['SmallBold']))
            for zc in pay['zaplaty_czesciowe']:
                forma_txt = PAYMENT_METHODS.get(zc.get('forma', ''), zc.get('forma', ''))
                add('Kwota:', self._fmt_amt(zc.get('kwota', '')))
                add('Data:', zc.get('data', ''))
                if forma_txt:
                    add('Forma:', forma_txt)

        # Skonto
        if pay.get('skonto_warunki'):
            add('Warunki skonta:', pay['skonto_warunki'])
            add('Wysoko\u015b\u0107 skonta:', pay.get('skonto_wysokosc', ''))

        if not rows:
            return []

        t = Table(rows, colWidths=[50*mm, 136*mm])
        t.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 1),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ]))
        elements.append(t)
        return elements

    def _annotations(self, data: Dict) -> List:
        ann = data.get('annotations', {})
        if not ann:
            return []

        elements = [Spacer(1, 3*mm), Paragraph('Adnotacje', self.styles['Section'])]
        rows = []

        labels = [
            ('p16', 'Metoda kasowa'),
            ('p17', 'Samofakturowanie'),
            ('p18', 'Odwrotne obci\u0105\u017cenie'),
            ('p18a', 'Mechanizm podzielonej p\u0142atno\u015bci'),
            ('p23', 'Procedura uproszczona (drugi sprzedawca)'),
        ]
        for key, label in labels:
            val = ann.get(key)
            if val:
                txt = 'Tak' if val == '1' else ('Nie' if val == '2' else self._rl_escape(val))
                rows.append([
                    Paragraph(f'{label}:', self.styles['SmallBold']),
                    Paragraph(txt, self.styles['Small'])
                ])

        # Exemption
        if ann.get('p19') == '1':
            rows.append([
                Paragraph('Zwolnienie od podatku:', self.styles['SmallBold']),
                Paragraph('Tak', self.styles['Small'])
            ])
            for key, label in [('p19a', 'Przepis ustawy'),
                                ('p19b', 'Dyrektywa UE'),
                                ('p19c', 'Inna podstawa')]:
                if ann.get(key):
                    rows.append([
                        Paragraph(f'  {label}:', self.styles['Small']),
                        Paragraph(self._rl_escape(ann[key]), self.styles['Small'])
                    ])

        # Margin scheme (PMarzy)
        if ann.get('p_pmarzy') == '1':
            rows.append([
                Paragraph('Procedura marży:', self.styles['SmallBold']),
                Paragraph('Tak', self.styles['Small'])
            ])
            margin_types = [
                ('p_pmarzy_2', 'Usługi turystyki'),
                ('p_pmarzy_3_1', 'Towary używane'),
                ('p_pmarzy_3_2', 'Dzieła sztuki'),
                ('p_pmarzy_3_3', 'Przedmioty kolekcjonerskie i antyki'),
            ]
            for key, label in margin_types:
                if ann.get(key) == '1':
                    rows.append([
                        Paragraph(f'  {label}:', self.styles['Small']),
                        Paragraph('Tak', self.styles['Small'])
                    ])

        # New transport vehicles
        if ann.get('p22') == '1':
            rows.append([
                Paragraph('Nowy środek transportu:', self.styles['SmallBold']),
                Paragraph('Tak', self.styles['Small'])
            ])
            if ann.get('p_42_5') == '1':
                rows.append([
                    Paragraph('  Art. 42 ust. 5:', self.styles['Small']),
                    Paragraph('Tak', self.styles['Small'])
                ])
            for veh in ann.get('nowe_srodki', []):
                parts = []
                if veh.get('marka'):
                    parts.append(veh['marka'])
                if veh.get('model'):
                    parts.append(veh['model'])
                if veh.get('nr_id'):
                    parts.append(f'Nr ID: {veh["nr_id"]}')
                if veh.get('rok_prod'):
                    parts.append(f'Rok: {veh["rok_prod"]}')
                if veh.get('pojemnosc'):
                    parts.append(f'Poj.: {veh["pojemnosc"]} cm³')
                if veh.get('przebieg'):
                    parts.append(f'Przebieg: {veh["przebieg"]} km')
                if parts:
                    rows.append([
                        Paragraph('  Pojazd:', self.styles['Small']),
                        Paragraph(self._rl_escape(', '.join(parts)), self.styles['Small'])
                    ])

        if not rows:
            return []

        t = Table(rows, colWidths=[60*mm, 126*mm])
        t.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 1),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ]))
        elements.append(t)
        return elements

    # --- New section builders (FA(3) compliance) ---

    def _podmiot3_section(self, data: Dict) -> List:
        """Render Podmiot3 (additional parties)."""
        parties = data.get('podmiot3', [])
        if not parties:
            return []
        elements = [Spacer(1, 3*mm)]
        for p in parties:
            role = self._rl_escape(p.get('opis_roli') or p.get('rola_inna', ''))
            title = f'<b>PODMIOT TRZECI</b>{f" — {role}" if role else ""}'
            elements.append(self._party_html(title, p))
            if p.get('udzial'):
                elements.append(Paragraph(
                    f'Udział: {self._rl_escape(p["udzial"])}%', self.styles['Small']))
        return elements

    def _correction_info(self, data: Dict) -> List:
        """Render correction invoice details."""
        h = data.get('header', {})
        dane = data.get('dane_korygowanej', [])
        if not h.get('przyczyna_korekty') and not dane:
            return []
        elements = [Spacer(1, 3*mm),
                     Paragraph('Dane korekty', self.styles['Section'])]
        rows = []
        if h.get('przyczyna_korekty'):
            rows.append([
                Paragraph('Przyczyna korekty:', self.styles['SmallBold']),
                Paragraph(self._rl_escape(h['przyczyna_korekty']), self.styles['Small'])
            ])
        if h.get('typ_korekty'):
            typ_map = {'1': 'Korekta wartości', '2': 'Korekta danych',
                        '3': 'Korekta wartości i danych'}
            rows.append([
                Paragraph('Typ korekty:', self.styles['SmallBold']),
                Paragraph(self._rl_escape(typ_map.get(h['typ_korekty'], h['typ_korekty'])),
                           self.styles['Small'])
            ])
        for d in dane:
            nr = self._rl_escape(d.get('nr_ksef') or d.get('nr_faktury', ''))
            data_txt = self._rl_escape(d.get('data_wyst', ''))
            rows.append([
                Paragraph('Faktura korygowana:', self.styles['SmallBold']),
                Paragraph(f'{nr} ({data_txt})' if data_txt else nr,
                           self.styles['Small'])
            ])
        if rows:
            t = Table(rows, colWidths=[50*mm, 136*mm])
            t.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 1),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
            ]))
            elements.append(t)
        return elements

    def _rozliczenie_section(self, data: Dict) -> List:
        """Render Rozliczenie (surcharges and deductions)."""
        roz = data.get('rozliczenie', {})
        if not roz:
            return []
        elements = [Spacer(1, 3*mm),
                     Paragraph('Rozliczenie', self.styles['Section'])]
        rows = []

        def add(label, value):
            if value:
                rows.append([
                    Paragraph(label, self.styles['SmallBold']),
                    Paragraph(self._rl_escape(value), self.styles['Small'])
                ])

        for o in roz.get('obciazenia', []):
            add('Obciążenie:', f'{self._fmt_amt(o.get("kwota", ""))} — {o.get("powod", "")}')
        if roz.get('suma_obciazen'):
            add('Suma obciążeń:', self._fmt_amt(roz['suma_obciazen']))
        for o in roz.get('odliczenia', []):
            add('Odliczenie:', f'{self._fmt_amt(o.get("kwota", ""))} — {o.get("powod", "")}')
        if roz.get('suma_odliczen'):
            add('Suma odliczeń:', self._fmt_amt(roz['suma_odliczen']))
        if roz.get('do_zaplaty'):
            add('Do zapłaty:', self._fmt_amt(roz['do_zaplaty']))
        if roz.get('do_rozliczenia'):
            add('Do rozliczenia:', self._fmt_amt(roz['do_rozliczenia']))

        if rows:
            t = Table(rows, colWidths=[50*mm, 136*mm])
            t.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 1),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
            ]))
            elements.append(t)
        return elements

    def _zaliczki_section(self, data: Dict) -> List:
        """Render advance invoice references and partial advance payments."""
        elements = []
        # Advance invoice references
        fz_list = data.get('faktury_zaliczkowe', [])
        if fz_list:
            elements.append(Spacer(1, 3*mm))
            elements.append(Paragraph('Faktury zaliczkowe', self.styles['Section']))
            for fz in fz_list:
                nr = fz.get('nr_ksef') or fz.get('nr_faktury', '')
                if nr:
                    elements.append(Paragraph(self._rl_escape(nr), self.styles['Small']))

        # Partial advance payments
        zc_list = data.get('zaliczki_czesciowe', [])
        if zc_list:
            elements.append(Spacer(1, 3*mm))
            elements.append(Paragraph('Zaliczki częściowe', self.styles['Section']))
            rows = []
            for zc in zc_list:
                parts = []
                if zc.get('p15z'):
                    parts.append(f'Kwota: {self._fmt_amt(zc["p15z"])}')
                if zc.get('p6z'):
                    parts.append(f'Data: {zc["p6z"]}')
                if zc.get('kurs_waluty'):
                    parts.append(f'Kurs: {zc["kurs_waluty"]}')
                if parts:
                    elements.append(Paragraph(self._rl_escape(' | '.join(parts)), self.styles['Small']))

        return elements

    def _dodatkowy_opis_section(self, data: Dict) -> List:
        """Render DodatkowyOpis (additional key-value descriptions)."""
        opisy = data.get('dodatkowy_opis', [])
        if not opisy:
            return []
        elements = [Spacer(1, 3*mm),
                     Paragraph('Informacje dodatkowe', self.styles['Section'])]
        tdata = [[
            Paragraph('Klucz', self.styles['TH']),
            Paragraph('Wartość', self.styles['TH']),
        ]]
        for o in opisy:
            tdata.append([
                Paragraph(self._rl_escape(o.get('klucz', '')), self.styles['TD']),
                Paragraph(self._rl_escape(o.get('wartosc', '')), self.styles['TD']),
            ])
        t = Table(tdata, colWidths=[50*mm, 136*mm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(t)
        return elements

    def _zamowienie_section(self, data: Dict) -> List:
        """Render Zamowienie (order for advance invoices)."""
        zam = data.get('zamowienie', {})
        if not zam:
            return []
        elements = [Spacer(1, 3*mm),
                     Paragraph('Zamówienie', self.styles['Section'])]
        if zam.get('wartosc'):
            elements.append(Paragraph(
                f'Wartość zamówienia: {self._fmt_amt(zam["wartosc"])}',
                self.styles['SmallBold']))
        wiersze = zam.get('wiersze', [])
        if wiersze:
            header = [
                Paragraph('Lp.', self.styles['TH']),
                Paragraph('Nazwa', self.styles['TH']),
                Paragraph('J.m.', self.styles['TH']),
                Paragraph('Ilość', self.styles['TH']),
                Paragraph('Cena netto', self.styles['TH']),
                Paragraph('Wart. netto', self.styles['TH']),
                Paragraph('Stawka', self.styles['TH']),
            ]
            tdata = [header]
            for w in wiersze:
                tdata.append([
                    Paragraph(self._rl_escape(w.get('nr', '')), self.styles['TDC']),
                    Paragraph(self._rl_escape(w.get('p7z', '')), self.styles['TD']),
                    Paragraph(self._rl_escape(w.get('p8az', '')), self.styles['TDC']),
                    Paragraph(self._rl_escape(self._fmt_amt(w.get('p8bz', ''))), self.styles['TDR']),
                    Paragraph(self._rl_escape(self._fmt_amt(w.get('p9az', ''))), self.styles['TDR']),
                    Paragraph(self._rl_escape(self._fmt_amt(w.get('p11z', ''))), self.styles['TDR']),
                    Paragraph(self._rl_escape(VAT_RATE_LABELS.get(w.get('p12z', ''), w.get('p12z', ''))),
                              self.styles['TDC']),
                ])
            t = Table(tdata, colWidths=[10*mm, 60*mm, 15*mm, 20*mm, 27*mm, 27*mm, 20*mm])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]))
            elements.append(t)
        return elements

    def _zalacznik_section(self, data: Dict) -> List:
        """Render Zalacznik (attachment data blocks)."""
        bloki = data.get('zalacznik', [])
        if not bloki:
            return []
        elements = [Spacer(1, 3*mm),
                     Paragraph('Załączniki', self.styles['Section'])]
        for blok in bloki:
            if blok.get('naglowek'):
                elements.append(Paragraph(self._rl_escape(blok['naglowek']), self.styles['SmallBold']))
            for m in blok.get('metadane', []):
                elements.append(Paragraph(
                    f'{self._rl_escape(m.get("klucz", ""))}: {self._rl_escape(m.get("wartosc", ""))}',
                    self.styles['Small']))
            for a in blok.get('akapity', []):
                elements.append(Paragraph(self._rl_escape(a), self.styles['Small']))
            elements.append(Spacer(1, 2*mm))
        return elements

    def _warunki_transakcji_section(self, data: Dict) -> List:
        """Render WarunkiTransakcji (transaction conditions)."""
        wt = data.get('payment', {}).get('warunki_transakcji', {})
        if not wt:
            return []
        elements = [Spacer(1, 3*mm),
                     Paragraph('Warunki transakcji', self.styles['Section'])]
        rows = []

        def add(label, value):
            if value:
                rows.append([
                    Paragraph(label, self.styles['SmallBold']),
                    Paragraph(self._rl_escape(value), self.styles['Small'])
                ])

        for u in wt.get('umowy', []):
            nr = u.get('numer', '')
            data_u = u.get('data', '')
            add('Umowa:', f'{nr} ({data_u})' if data_u else nr)
        for z in wt.get('zamowienia', []):
            nr = z.get('numer', '')
            data_z = z.get('data', '')
            add('Zamówienie:', f'{nr} ({data_z})' if data_z else nr)
        for p in wt.get('nr_partii', []):
            add('Nr partii towaru:', p)
        add('Warunki dostawy:', wt.get('warunki_dostawy'))
        if wt.get('kurs_umowny'):
            waluta = wt.get('waluta_umowna', '')
            add('Kurs umowny:', f'{wt["kurs_umowny"]} {waluta}'.strip())
        for tr in wt.get('transport', []):
            rodzaj = tr.get('rodzaj', '')
            if tr.get('transport_inny') == '1':
                rodzaj = tr.get('opis_innego', 'inny')
            if rodzaj:
                add('Transport:', rodzaj)
            if tr.get('przewoznik_nazwa'):
                add('  Przewoźnik:', tr['przewoznik_nazwa'])
            if tr.get('nr_zlecenia'):
                add('  Nr zlecenia:', tr['nr_zlecenia'])
            ladunek = tr.get('opis_ladunku', '')
            if tr.get('ladunek_inny') == '1':
                ladunek = tr.get('opis_innego_ladunku', 'inny')
            if ladunek:
                add('  Ładunek:', ladunek)
            if tr.get('data_rozp'):
                add('  Rozpoczęcie:', tr['data_rozp'])
            if tr.get('data_zak'):
                add('  Zakończenie:', tr['data_zak'])
        if wt.get('podmiot_posredniczacy') == '1':
            add('Podmiot pośredniczący:', 'Tak (art. 22 ust. 2d)')

        if rows:
            t = Table(rows, colWidths=[50*mm, 136*mm])
            t.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 1),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
            ]))
            elements.append(t)
        return elements

    def _footer(self, data: Dict) -> List:
        ft = data.get('footer', {})
        h = data.get('header', {})
        elements = []

        # Footer info
        if ft.get('informacje'):
            elements.append(Spacer(1, 3*mm))
            for info in ft['informacje']:
                elements.append(Paragraph(self._rl_escape(info), self.styles['Small']))

        # Registries
        if ft.get('rejestry'):
            elements.append(Spacer(1, 2*mm))
            for r in ft['rejestry']:
                parts = []
                if r.get('nazwa'):
                    parts.append(r['nazwa'])
                if r.get('krs'):
                    parts.append(f'KRS: {r["krs"]}')
                if r.get('regon'):
                    parts.append(f'REGON: {r["regon"]}')
                if r.get('bdo'):
                    parts.append(f'BDO: {r["bdo"]}')
                if parts:
                    elements.append(Paragraph(self._rl_escape(' | '.join(parts)), self.styles['Small']))

        # Creation timestamp
        if h.get('data_wytworzenia'):
            elements.append(Spacer(1, 3*mm))
            elements.append(Paragraph(
                f'Data wytworzenia faktury: {h["data_wytworzenia"]}',
                self.styles['Small']))

        return elements

    def _make_page_footer(self, timezone: str = ''):
        """Return a callback that draws generation stamp at the bottom of every page."""
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

        stamp = now.strftime('%y.%m.%d %H:%M:%S')
        text = f'Wygenerowane przez KSeF Monitor v0.3 | {stamp} {tz_label}'
        font = self.font

        def _draw(canvas_obj, doc):
            canvas_obj.saveState()
            canvas_obj.setFont(font, 6)
            canvas_obj.setFillColor(colors.grey)
            page_width = A4[0]
            canvas_obj.drawCentredString(page_width / 2, 5 * mm, text)
            canvas_obj.restoreState()

        return _draw

    # --- QR Code (Type I: Invoice Verification) ---

    @staticmethod
    def _sha256_base64url(data: bytes) -> str:
        """Compute SHA-256 of data, return as Base64URL (no padding)."""
        digest = hashlib.sha256(data).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')

    @staticmethod
    def _format_date_ddmmyyyy(iso_date: str) -> str:
        """Convert YYYY-MM-DD to DD-MM-YYYY for QR URL."""
        if not iso_date or len(iso_date) < 10:
            return ''
        parts = iso_date[:10].split('-')
        if len(parts) == 3:
            return f'{parts[2]}-{parts[1]}-{parts[0]}'
        return ''

    def _build_qr_image(self, data: Dict, xml_content: str,
                        environment: str) -> 'Optional[Image]':
        """
        Build QR Code Type I image (Invoice Verification & Download).

        URL format: {BaseURL}/invoice/{NIP}/{IssueDate DD-MM-YYYY}/{FileHash Base64URL}
        Per: https://github.com/CIRFMF/ksef-docs/blob/main/kody-qr.md

        Returns reportlab Image or None if QR cannot be generated.
        """
        if not QRCODE_AVAILABLE:
            logger.warning("qrcode library not available - skipping QR code")
            return None

        if not xml_content:
            return None

        seller_nip = data.get('seller', {}).get('nip', '')
        issue_date = data.get('header', {}).get('p1', '')

        if not seller_nip or not issue_date:
            logger.warning("Missing seller NIP or issue date - skipping QR code")
            return None

        env_key = environment.lower() if environment else 'prod'
        base_url = QR_BASE_URLS.get(env_key, QR_BASE_URLS['prod'])

        file_hash = self._sha256_base64url(xml_content.encode('utf-8'))
        date_str = self._format_date_ddmmyyyy(issue_date)
        if not date_str:
            logger.warning(f"Cannot format issue date '{issue_date}' for QR code")
            return None

        qr_url = f'{base_url}/invoice/{seller_nip}/{date_str}/{file_hash}'
        logger.debug(f"QR code URL: {qr_url}")

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
            img_buffer.seek(0)

            qr_size = 30 * mm
            return Image(img_buffer, width=qr_size, height=qr_size)
        except Exception as e:
            logger.error(f"Failed to generate QR code: {e}")
            return None

    def _fmt_amt(self, val: str) -> str:
        if not val:
            return ''
        try:
            num = float(val)
            formatted = f'{num:,.2f}'
            # Polish norms: ',' as decimal separator, '\u00a0' (non-breaking space) as thousands separator
            formatted = formatted.replace(',', '\u00a0').replace('.', ',')
            return formatted
        except (ValueError, TypeError):
            return val


try:
    from xhtml2pdf import pisa as _pisa_check
    XHTML2PDF_AVAILABLE = True
except ImportError:
    XHTML2PDF_AVAILABLE = False


def generate_invoice_pdf(xml_content: str, ksef_number: str = '',
                         output_path: str = None, environment: str = '',
                         timezone: str = '',
                         template_dir: str = None) -> BytesIO:
    """Generate PDF from KSeF invoice XML.

    Uses HTML template rendering (xhtml2pdf) when available, with automatic
    fallback to direct ReportLab generation.

    Args:
        xml_content: Raw XML string of the KSeF invoice
        ksef_number: KSeF reference number (shown in header + QR label)
        output_path: File path to write PDF (if None, returns BytesIO)
        environment: KSeF environment ('test', 'demo', 'prod') for QR code URL
        timezone: IANA timezone name for generation timestamp (default: Europe/Warsaw)
        template_dir: Custom PDF template directory (overrides built-in default)
    """
    parser = InvoiceXMLParser(xml_content)
    invoice_data = parser.parse()
    if ksef_number:
        invoice_data['ksef_metadata']['ksef_number'] = ksef_number

    # Try template-based rendering first (xhtml2pdf)
    if XHTML2PDF_AVAILABLE:
        try:
            from .invoice_pdf_template import InvoicePDFTemplateRenderer
            renderer = InvoicePDFTemplateRenderer(custom_templates_dir=template_dir)
            return renderer.render(invoice_data, ksef_number=ksef_number,
                                   xml_content=xml_content, environment=environment,
                                   timezone=timezone, output_path=output_path)
        except Exception as e:
            logger.warning(f"Template PDF rendering failed, falling back to ReportLab: {e}")

    # Fallback: existing ReportLab generator
    generator = InvoicePDFGenerator()
    return generator.generate(invoice_data, output_path,
                              xml_content=xml_content, environment=environment,
                              timezone=timezone)
