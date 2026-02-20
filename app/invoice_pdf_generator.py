"""
KSeF Invoice PDF Generator

Generates PDF from KSeF invoice XML based on official schema and XSL visualization:
  XSD: http://crd.gov.pl/wzor/2025/06/25/13775/schemat.xsd
  XSL: http://crd.gov.pl/wzor/2025/06/25/13775/styl.xsl

PDF contains ONLY data present in the source XML. No calculations, no defaults.
"""

import base64
import hashlib
import logging
import os
import re
from defusedxml import ElementTree as ET
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
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False

logger = logging.getLogger(__name__)

# Font registration — search for a TTF font that supports Polish diacritical marks.
# Priority: DejaVu Sans (Linux/Docker) → Arial Unicode MS (macOS) → Arial (macOS) → Helvetica (fallback, no PL chars)
_FONT_NAME = 'Helvetica'
_FONT_NAME_BOLD = 'Helvetica-Bold'

if REPORTLAB_AVAILABLE:
    # (name, regular_path, bold_path_or_None)
    _FONT_CANDIDATES = [
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

    _font_registered = False
    for _fname, _fpath, _fbold in _FONT_CANDIDATES:
        if not os.path.exists(_fpath):
            continue
        try:
            pdfmetrics.registerFont(TTFont(_fname, _fpath))
            _FONT_NAME = _fname
            _FONT_NAME_BOLD = _fname
            if _fbold and os.path.exists(_fbold):
                bold_name = _fname + '-Bold'
                pdfmetrics.registerFont(TTFont(bold_name, _fbold))
                _FONT_NAME_BOLD = bold_name
            logger.info(f"Font '{_fname}' registered for Polish character support")
            _font_registered = True
            break
        except Exception as e:
            logger.warning(f"Failed to register font '{_fname}': {e}")

    if not _font_registered:
        logger.warning("No TTF font with Polish support found - diacritical marks may not render")

# VAT rate display mapping (from XSL styl.xsl)
VAT_RATE_LABELS = {
    '23': '23%', '22': '22%', '8': '8%', '7': '7%',
    '5': '5%', '4': '4%', '3': '3%',
    '0': '0%',
    'zw': 'zw',
    'oo': 'odwr. obc.',
    'np': 'np',
}

# Payment method mapping (from XSD TFormaPlatnosci)
PAYMENT_METHODS = {
    '1': 'Gotówka', '2': 'Karta', '3': 'Bon',
    '4': 'Czek', '5': 'Kredyt', '6': 'Przelew', '7': 'Mobilna',
}

# Invoice type titles (from XSL NaglowekTytulowy)
INVOICE_TYPE_TITLES = {
    'VAT': 'Faktura VAT',
    'KOR': 'Faktura korygująca',
    'ZAL': 'Faktura zaliczkowa',
    'ROZ': 'Faktura rozliczeniowa',
    'UPR': 'Faktura uproszczona',
    'KOR_ZAL': 'Faktura korygująca zaliczkowa',
    'KOR_ROZ': 'Faktura korygująca rozliczeniowa',
}

# QR code base URLs per environment (from kody-qr.md)
QR_BASE_URLS = {
    'test': 'https://qr-test.ksef.mf.gov.pl',
    'demo': 'https://qr-demo.ksef.mf.gov.pl',
    'prod': 'https://qr.ksef.mf.gov.pl',
}

# VAT summary row definitions: (label, P_13 field, P_14 field)
VAT_SUMMARY_ROWS = [
    ('22% lub 23%', 'P_13_1', 'P_14_1'),
    ('7% lub 8%', 'P_13_2', 'P_14_2'),
    ('5%', 'P_13_3', 'P_14_3'),
    ('0%', 'P_13_6_1', None),
    ('0% WDT', 'P_13_6_2', None),
    ('0% eksport', 'P_13_6_3', None),
    ('zw', 'P_13_7', None),
    ('oo', 'P_13_10', None),
    ('np', 'P_13_8', None),
    ('ryczalt taksowki', 'P_13_4', 'P_14_4'),
    ('marza', 'P_13_11', None),
]


class InvoiceXMLParser:
    """Parser for KSeF FA_VAT XML invoices with auto namespace detection."""

    def __init__(self, xml_content: str):
        self.xml_content = xml_content
        self.root = None
        self.NS = {}

    def parse(self) -> Dict:
        try:
            self.root = ET.fromstring(self.xml_content)
            ns_match = re.match(r'\{(.+?)\}', self.root.tag)
            if ns_match:
                self.NS = {'fa': ns_match.group(1)}
                logger.debug(f"Detected XML namespace: {ns_match.group(1)}")

            data = {
                'ksef_metadata': {'ksef_number': ''},
                'header': self._parse_header(),
                'seller': self._parse_podmiot('Podmiot1'),
                'buyer': self._parse_podmiot('Podmiot2'),
                'items': self._parse_items(),
                'vat_summary': self._parse_vat_summary(),
                'payment': self._parse_payment(),
                'annotations': self._parse_annotations(),
                'footer': self._parse_footer(),
            }
            logger.info("Invoice XML parsed successfully")
            return data
        except ET.ParseError as e:
            logger.error(f"XML parsing error: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to parse invoice XML: {e}")
            raise

    def _text(self, parent, *tags, default=''):
        if parent is None:
            return default
        for tag in tags:
            elem = parent.find(tag, self.NS)
            if elem is not None and elem.text:
                return elem.text.strip()
        return default

    def _parse_header(self) -> Dict:
        h = {}
        naglowek = self.root.find('.//fa:Naglowek', self.NS)
        fa = self.root.find('.//fa:Fa', self.NS)

        if naglowek is not None:
            h['kod_formularza'] = self._text(naglowek, 'fa:KodFormularza')
            h['wariant'] = self._text(naglowek, 'fa:WariantFormularza')
            h['data_wytworzenia'] = self._text(naglowek, 'fa:DataWytworzeniaFa')

        if fa is not None:
            h['rodzaj'] = self._text(fa, 'fa:RodzajFaktury')
            h['kod_waluty'] = self._text(fa, 'fa:KodWaluty')
            h['p2'] = self._text(fa, 'fa:P_2')  # invoice number
            h['p1'] = self._text(fa, 'fa:P_1')  # issue date
            h['p1m'] = self._text(fa, 'fa:P_1M')  # place of issue
            h['p6'] = self._text(fa, 'fa:P_6')  # delivery/service date
            h['p6_od'] = self._text(fa, 'fa:OkresFa/fa:P_6_Od')
            h['p6_do'] = self._text(fa, 'fa:OkresFa/fa:P_6_Do')
            h['p15'] = self._text(fa, 'fa:P_15')  # total due
            h['fp'] = self._text(fa, 'fa:FP')
            h['tp'] = self._text(fa, 'fa:TP')
            h['kurs_waluty_z'] = self._text(fa, 'fa:KursWalutyZ')

        return h

    def _parse_podmiot(self, tag: str) -> Dict:
        s = {}
        podmiot = self.root.find(f'.//fa:{tag}', self.NS)
        if podmiot is None:
            return s

        dane = podmiot.find('fa:DaneIdentyfikacyjne', self.NS)
        if dane is not None:
            s['nip'] = self._text(dane, 'fa:NIP')
            s['nazwa'] = self._text(dane, 'fa:Nazwa')
            s['kod_ue'] = self._text(dane, 'fa:KodUE')
            s['nr_vat_ue'] = self._text(dane, 'fa:NrVatUE')
            s['nr_id'] = self._text(dane, 'fa:NrID')
            s['kod_kraju_id'] = self._text(dane, 'fa:KodKraju')

        s['nr_eori'] = self._text(podmiot, 'fa:NrEORI')
        s['prefiks'] = self._text(podmiot, 'fa:PrefiksPodatnika')

        adres = podmiot.find('fa:Adres', self.NS)
        if adres is not None:
            s['kod_kraju'] = self._text(adres, 'fa:KodKraju')
            s['adres_l1'] = self._text(adres, 'fa:AdresL1')
            s['adres_l2'] = self._text(adres, 'fa:AdresL2')
            s['gln'] = self._text(adres, 'fa:GLN')

        # Contact
        kontakt = podmiot.find('fa:DaneKontaktowe', self.NS)
        if kontakt is not None:
            s['email'] = self._text(kontakt, 'fa:Email')
            s['telefon'] = self._text(kontakt, 'fa:Telefon')

        return s

    def _parse_items(self) -> List[Dict]:
        items = []
        wiersze = self.root.findall('.//fa:Fa/fa:FaWiersz', self.NS)
        for wiersz in wiersze:
            item = {}
            for field, tag in [
                ('nr', 'fa:NrWierszaFa'), ('uu_id', 'fa:UU_ID'),
                ('p7', 'fa:P_7'), ('indeks', 'fa:Indeks'),
                ('p8a', 'fa:P_8A'), ('p8b', 'fa:P_8B'),
                ('p9a', 'fa:P_9A'), ('p9b', 'fa:P_9B'),
                ('p10', 'fa:P_10'),
                ('p11', 'fa:P_11'), ('p11a', 'fa:P_11A'),
                ('p11vat', 'fa:P_11Vat'),
                ('p12', 'fa:P_12'), ('p12_xii', 'fa:P_12_XII'),
                ('p6a', 'fa:P_6A'),
                ('gtin', 'fa:GTIN'), ('pkwiu', 'fa:PKWiU'),
                ('cn', 'fa:CN'), ('pkob', 'fa:PKOB'),
                ('kwota_akcyzy', 'fa:KwotaAkcyzy'),
                ('gtu', 'fa:GTU'), ('procedura', 'fa:Procedura'),
                ('kurs_waluty', 'fa:KursWaluty'),
                ('stan_przed', 'fa:StanPrzed'),
                ('p12_zal_15', 'fa:P_12_Zal_15'),
            ]:
                val = self._text(wiersz, tag)
                if val:
                    item[field] = val
            items.append(item)
        return items

    def _parse_vat_summary(self) -> Dict:
        summary = {}
        fa = self.root.find('.//fa:Fa', self.NS)
        if fa is None:
            return summary
        for field in [
            'P_13_1', 'P_14_1', 'P_14_1W',
            'P_13_2', 'P_14_2', 'P_14_2W',
            'P_13_3', 'P_14_3', 'P_14_3W',
            'P_13_4', 'P_14_4', 'P_14_4W',
            'P_13_5', 'P_14_5',
            'P_13_6_1', 'P_13_6_2', 'P_13_6_3',
            'P_13_7', 'P_13_8', 'P_13_9', 'P_13_10', 'P_13_11',
        ]:
            val = self._text(fa, f'fa:{field}')
            if val:
                summary[field] = val
        return summary

    def _parse_payment(self) -> Dict:
        pay = {}
        platnosc = self.root.find('.//fa:Fa/fa:Platnosc', self.NS)
        if platnosc is None:
            platnosc = self.root.find('.//fa:Platnosc', self.NS)
        if platnosc is None:
            return pay

        pay['zaplacono'] = self._text(platnosc, 'fa:Zaplacono')
        pay['data_zaplaty'] = self._text(platnosc, 'fa:DataZaplaty')
        pay['znacznik_czesciowej'] = self._text(platnosc, 'fa:ZnacznikZaplatyCzesciowej')

        # Partial payments
        czesciowe = platnosc.findall('fa:ZaplataCzesciowa', self.NS)
        if czesciowe:
            pay['zaplaty_czesciowe'] = []
            for zc in czesciowe:
                entry = {}
                entry['kwota'] = self._text(zc, 'fa:KwotaZaplatyCzesciowej')
                entry['data'] = self._text(zc, 'fa:DataZaplatyCzesciowej')
                entry['forma'] = self._text(zc, 'fa:FormaPlatnosci')
                entry['platnosc_inna'] = self._text(zc, 'fa:PlatnoscInna')
                entry['opis'] = self._text(zc, 'fa:OpisPlatnosci')
                pay['zaplaty_czesciowe'].append(entry)

        # Payment terms
        terminy = platnosc.findall('fa:TerminPlatnosci', self.NS)
        if terminy:
            pay['terminy'] = []
            for t in terminy:
                entry = {'termin': self._text(t, 'fa:Termin')}
                opis = t.find('fa:TerminOpis', self.NS)
                if opis is not None:
                    entry['opis_ilosc'] = self._text(opis, 'fa:Ilosc')
                    entry['opis_jednostka'] = self._text(opis, 'fa:Jednostka')
                pay['terminy'].append(entry)

        # Payment form (single)
        pay['forma'] = self._text(platnosc, 'fa:FormaPlatnosci')
        pay['platnosc_inna'] = self._text(platnosc, 'fa:PlatnoscInna')
        pay['opis_platnosci'] = self._text(platnosc, 'fa:OpisPlatnosci')

        # Bank accounts
        rachunki = platnosc.findall('fa:RachunekBankowy', self.NS)
        if rachunki:
            pay['rachunki'] = []
            for r in rachunki:
                entry = {
                    'nr_rb': self._text(r, 'fa:NrRB'),
                    'swift': self._text(r, 'fa:SWIFT'),
                    'nazwa_banku': self._text(r, 'fa:NazwaBanku'),
                    'opis': self._text(r, 'fa:OpisRachunku'),
                }
                pay['rachunki'].append(entry)

        # Factor bank accounts
        rachunki_f = platnosc.findall('fa:RachunekBankowyFaktora', self.NS)
        if rachunki_f:
            pay['rachunki_faktora'] = []
            for r in rachunki_f:
                entry = {
                    'nr_rb': self._text(r, 'fa:NrRB'),
                    'swift': self._text(r, 'fa:SWIFT'),
                    'nazwa_banku': self._text(r, 'fa:NazwaBanku'),
                    'opis': self._text(r, 'fa:OpisRachunku'),
                }
                pay['rachunki_faktora'].append(entry)

        # Skonto
        skonto = platnosc.find('fa:Skonto', self.NS)
        if skonto is not None:
            pay['skonto_warunki'] = self._text(skonto, 'fa:WarunkiSkonta')
            pay['skonto_wysokosc'] = self._text(skonto, 'fa:WysokoscSkonta')

        return pay

    def _parse_annotations(self) -> Dict:
        ann = {}
        adnotacje = self.root.find('.//fa:Fa/fa:Adnotacje', self.NS)
        if adnotacje is None:
            return ann

        ann['p16'] = self._text(adnotacje, 'fa:P_16')
        ann['p17'] = self._text(adnotacje, 'fa:P_17')
        ann['p18'] = self._text(adnotacje, 'fa:P_18')
        ann['p18a'] = self._text(adnotacje, 'fa:P_18A')

        zwolnienie = adnotacje.find('fa:Zwolnienie', self.NS)
        if zwolnienie is not None:
            ann['p19'] = self._text(zwolnienie, 'fa:P_19')
            ann['p19a'] = self._text(zwolnienie, 'fa:P_19A')
            ann['p19b'] = self._text(zwolnienie, 'fa:P_19B')
            ann['p19c'] = self._text(zwolnienie, 'fa:P_19C')

        return ann

    def _parse_footer(self) -> Dict:
        ft = {}
        stopka = self.root.find('.//fa:Stopka', self.NS)
        if stopka is None:
            return ft

        infos = stopka.findall('fa:Informacje', self.NS)
        if infos:
            ft['informacje'] = [self._text(i, 'fa:StopkaFaktury') for i in infos
                                if self._text(i, 'fa:StopkaFaktury')]

        rejestry = stopka.findall('fa:Rejestry', self.NS)
        if rejestry:
            ft['rejestry'] = []
            for r in rejestry:
                entry = {
                    'nazwa': self._text(r, 'fa:PelnaNazwa'),
                    'krs': self._text(r, 'fa:KRS'),
                    'regon': self._text(r, 'fa:REGON'),
                    'bdo': self._text(r, 'fa:BDO'),
                }
                ft['rejestry'].append(entry)

        return ft


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
            topMargin=12*mm, bottomMargin=12*mm)

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
        story.append(Spacer(1, 6*mm))
        story.extend(self._items_table(data))
        story.append(Spacer(1, 4*mm))
        story.extend(self._vat_summary(data))
        story.append(Spacer(1, 4*mm))
        story.extend(self._total_amount(data))
        story.append(Spacer(1, 4*mm))
        story.extend(self._payment(data))
        story.extend(self._annotations(data))
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
                    Paragraph(f'<b>{value}</b>', self.styles['FieldValue'])
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

    def _party_html(self, title: str, p: Dict) -> 'Paragraph':
        h = f'<b>{title}</b><br/>'
        if p.get('nip'):
            prefix = f"{p['prefiks']} " if p.get('prefiks') else ''
            h += f'NIP: {prefix}<b>{p["nip"]}</b><br/>'
        if p.get('kod_ue') and p.get('nr_vat_ue'):
            h += f'VAT UE: {p["kod_ue"]} {p["nr_vat_ue"]}<br/>'
        if p.get('nr_id'):
            h += f'ID: {p.get("kod_kraju_id", "")} {p["nr_id"]}<br/>'
        if p.get('nazwa'):
            h += f'{p["nazwa"]}<br/>'
        if p.get('kod_kraju'):
            h += f'Kod kraju: {p["kod_kraju"]}<br/>'
        if p.get('adres_l1'):
            h += f'{p["adres_l1"]}'
            if p.get('adres_l2'):
                h += f' {p["adres_l2"]}'
            h += '<br/>'
        if p.get('email'):
            h += f'Email: {p["email"]}<br/>'
        if p.get('telefon'):
            h += f'Tel: {p["telefon"]}<br/>'
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
                row.append(Paragraph(str(val), style))
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

        elements = [Paragraph('Podliczenie VAT', self.styles['Section'])]

        header = [
            Paragraph('Stawka VAT', self.styles['TH']),
            Paragraph('Warto\u015b\u0107 netto', self.styles['TH']),
            Paragraph('Kwota VAT', self.styles['TH']),
        ]
        tdata = [header]

        for label, p13_field, p14_field in VAT_SUMMARY_ROWS:
            net = vs.get(p13_field)
            if not net:
                continue
            vat = vs.get(p14_field, '') if p14_field else ''
            tdata.append([
                Paragraph(label, self.styles['TDC']),
                Paragraph(self._fmt_amt(net), self.styles['TDR']),
                Paragraph(self._fmt_amt(vat) if vat else '', self.styles['TDR']),
            ])

        if len(tdata) <= 1:
            return []

        t = Table(tdata, colWidths=[40*mm, 40*mm, 40*mm])
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

        currency = h.get('kod_waluty', '')
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
                    Paragraph(value, self.styles['Small'])
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
        ]
        for key, label in labels:
            val = ann.get(key)
            if val:
                txt = 'Tak' if val == '1' else ('Nie' if val == '2' else val)
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
                        Paragraph(ann[key], self.styles['Small'])
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

    def _footer(self, data: Dict) -> List:
        ft = data.get('footer', {})
        h = data.get('header', {})
        elements = []

        # Footer info
        if ft.get('informacje'):
            elements.append(Spacer(1, 3*mm))
            for info in ft['informacje']:
                elements.append(Paragraph(info, self.styles['Small']))

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
                    elements.append(Paragraph(' | '.join(parts), self.styles['Small']))

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
