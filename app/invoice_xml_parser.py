"""
KSeF Invoice XML Parser — multi-schema support.

Auto-detects schema type from XML namespace and dispatches to the correct
parser.  Supported schemas (KSeF API v2.4.0):

  FA(3)   — Faktura VAT (current)        crd.gov.pl/wzor/2025/…/13775/
  FA(2)   — Faktura VAT (legacy)         crd.gov.pl/wzor/202x/…
  FA_RR   — Faktura VAT RR (farmer)      crd.gov.pl/wzor/2024/…/12978/  v1-0E
                                         crd.gov.pl/wzor/2025/…/13836/  v1-1E
  PEF     — PEPPOL UBL Invoice           urn:oasis:names:spec:ubl:…:Invoice-2
  UNKNOWN — any other namespace          → minimal extraction, no PDF

Public API:
  detect_schema_type(xml_content) -> str
  create_invoice_xml_parser(xml_content) -> BaseInvoiceXMLParser
  InvoiceXMLParser           — FA(3) / FA(2) parser (backward-compatible)
  FA_RRInvoiceXMLParser      — FA_RR parser (extends FA3)
  PEFInvoiceXMLParser        — PEPPOL UBL parser
  FallbackInvoiceXMLParser   — safe fallback for unknown schemas

Schema references (XSD):
  FA(3): http://crd.gov.pl/wzor/2025/06/25/13775/schemat.xsd
  FA(2): http://crd.gov.pl/wzor/2023/06/29/12648/schemat.xsd
  FA_RR v1-0E: http://crd.gov.pl/wzor/2024/02/19/12978/schemat.xsd
  FA_RR v1-1E: http://crd.gov.pl/wzor/2025/01/23/13836/schemat.xsd
  PEF: urn:oasis:names:specification:ubl:schema:xsd:Invoice-2
"""

import logging
import re
from defusedxml import ElementTree as ET
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Schema namespace registry ──────────────────────────────────────────────────

# FA(3) — current FA VAT schema (various publish dates, always schema ID 13775)
_FA3_NAMESPACES = frozenset({
    'http://crd.gov.pl/wzor/2025/06/25/13775/',
    'http://crd.gov.pl/wzor/2025/06/25/13773/',
})

# FA(2) — older FA VAT schema versions
_FA2_NAMESPACES = frozenset({
    'http://crd.gov.pl/wzor/2023/06/29/12648/',
    'http://crd.gov.pl/wzor/2022/01/05/10649/',
    'http://crd.gov.pl/wzor/2021/10/13/9851/',
    'http://crd.gov.pl/wzor/2022/05/17/11155/',
    'http://crd.gov.pl/wzor/2023/03/20/12197/',
})

# FA_RR — Faktura VAT RR (farmer flat-rate VAT invoice)
_FA_RR_NAMESPACES = frozenset({
    'http://crd.gov.pl/wzor/2024/02/19/12978/',   # v1-0E
    'http://crd.gov.pl/wzor/2025/01/23/13836/',   # v1-1E (mandatory from 01.04.2026)
})

# PEF — PEPPOL / UBL invoices (public procurement)
_PEF_NAMESPACES = frozenset({
    'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2',
    'urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2',
})

SCHEMA_TYPE_FA3 = 'FA3'
SCHEMA_TYPE_FA2 = 'FA2'
SCHEMA_TYPE_FA_RR = 'FA_RR'
SCHEMA_TYPE_PEF = 'PEF'
SCHEMA_TYPE_UNKNOWN = 'UNKNOWN'


def detect_schema_type(xml_content: str) -> str:
    """Detect KSeF invoice schema type from XML namespace.

    Returns one of: 'FA3', 'FA2', 'FA_RR', 'PEF', 'UNKNOWN'.
    """
    try:
        root = ET.fromstring(xml_content)
        ns_match = re.match(r'\{(.+?)\}', root.tag)
        namespace = ns_match.group(1) if ns_match else ''
    except Exception:
        return SCHEMA_TYPE_UNKNOWN

    if namespace in _FA3_NAMESPACES:
        return SCHEMA_TYPE_FA3
    if namespace in _FA2_NAMESPACES:
        return SCHEMA_TYPE_FA2
    if namespace in _FA_RR_NAMESPACES:
        return SCHEMA_TYPE_FA_RR
    if namespace in _PEF_NAMESPACES:
        return SCHEMA_TYPE_PEF

    # Pattern-based fallback
    if 'crd.gov.pl' in namespace:
        # Unknown CRD namespace → treat as FA2 (structurally compatible)
        logger.warning("Unknown CRD namespace '%s' — treating as FA2", namespace)
        return SCHEMA_TYPE_FA2
    if any(kw in namespace.lower() for kw in ('peppol', 'oasis', 'ubl')):
        return SCHEMA_TYPE_PEF

    logger.warning("Unrecognised XML namespace '%s'", namespace)
    return SCHEMA_TYPE_UNKNOWN


def create_invoice_xml_parser(xml_content: str) -> 'BaseInvoiceXMLParser':
    """Factory: return the appropriate parser for the given XML content."""
    schema = detect_schema_type(xml_content)
    if schema in (SCHEMA_TYPE_FA3, SCHEMA_TYPE_FA2):
        parser = InvoiceXMLParser(xml_content)
        parser._schema_type = schema  # pre-set so schema_type works before parse()
        return parser
    if schema == SCHEMA_TYPE_FA_RR:
        return FA_RRInvoiceXMLParser(xml_content)
    if schema == SCHEMA_TYPE_PEF:
        return PEFInvoiceXMLParser(xml_content)
    return FallbackInvoiceXMLParser(xml_content)


class BaseInvoiceXMLParser:
    """Shared interface for all schema parsers."""

    def parse(self) -> Dict:
        raise NotImplementedError

    @property
    def schema_type(self) -> str:
        raise NotImplementedError


class InvoiceXMLParser(BaseInvoiceXMLParser):
    """Parser for KSeF FA_VAT XML invoices — handles both FA(3) and FA(2).

    FA(2) and FA(3) share the same element names; only the namespace URI differs.
    Auto-namespace detection ensures correct prefix mapping for both versions.
    """

    def __init__(self, xml_content: str):
        self.xml_content = xml_content
        self.root = None
        self.NS = {}
        self._schema_type: Optional[str] = None

    @property
    def schema_type(self) -> str:
        return self._schema_type or SCHEMA_TYPE_FA3

    def parse(self) -> Dict:
        try:
            self.root = ET.fromstring(self.xml_content)
            ns_match = re.match(r'\{(.+?)\}', self.root.tag)
            if ns_match:
                namespace = ns_match.group(1)
                self.NS = {'fa': namespace}
                logger.debug("Detected XML namespace: %s", namespace)
                # Determine exact schema type
                if namespace in _FA2_NAMESPACES or (
                    'crd.gov.pl' in namespace and namespace not in _FA3_NAMESPACES
                    and namespace not in _FA_RR_NAMESPACES
                ):
                    self._schema_type = SCHEMA_TYPE_FA2
                else:
                    self._schema_type = SCHEMA_TYPE_FA3

            data = {
                'schema_type': self._schema_type,
                'ksef_metadata': {'ksef_number': ''},
                'header': self._parse_header(),
                'seller': self._parse_podmiot('Podmiot1'),
                'buyer': self._parse_podmiot('Podmiot2'),
                'podmiot3': self._parse_podmiot3(),
                'items': self._parse_items(),
                'vat_summary': self._parse_vat_summary(),
                'payment': self._parse_payment(),
                'annotations': self._parse_annotations(),
                'dodatkowy_opis': self._parse_dodatkowy_opis(),
                'dane_korygowanej': self._parse_dane_fa_korygowanej(),
                'faktury_zaliczkowe': self._parse_faktury_zaliczkowe(),
                'zaliczki_czesciowe': self._parse_zaliczki_czesciowe(),
                'rozliczenie': self._parse_rozliczenie(),
                'zamowienie': self._parse_zamowienie(),
                'zalacznik': self._parse_zalacznik(),
                'footer': self._parse_footer(),
            }
            logger.info("Invoice XML parsed successfully")
            return data
        except ET.ParseError as e:
            logger.error("XML parsing error: %s", e)
            raise
        except Exception as e:
            logger.error("Failed to parse invoice XML: %s", e)
            raise

    @staticmethod
    def _sanitize_text(value: str) -> str:
        """Strip HTML tags to prevent injection in PDF rendering.

        Only strips tags -- does NOT html.escape(). Both rendering paths
        handle escaping themselves: Jinja2 autoescape for xhtml2pdf,
        ReportLab Paragraph for the fallback path.
        """
        return re.sub(r'<[^>]+>', '', value)

    def _text(self, parent, *tags, default=''):
        if parent is None:
            return default
        for tag in tags:
            elem = parent.find(tag, self.NS)
            if elem is not None and elem.text:
                return self._sanitize_text(elem.text.strip())
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
            # Correction invoice fields
            h['przyczyna_korekty'] = self._text(fa, 'fa:PrzyczynaKorekty')
            h['typ_korekty'] = self._text(fa, 'fa:TypKorekty')
            h['nr_fa_korekty'] = self._text(fa, 'fa:NrFaKorekty')

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

        # WarunkiTransakcji
        wt = self.root.find('.//fa:Fa/fa:WarunkiTransakcji', self.NS)
        if wt is not None:
            pay['warunki_transakcji'] = self._parse_warunki_transakcji(wt)

        return pay

    def _parse_warunki_transakcji(self, wt) -> Dict:
        """Parse WarunkiTransakcji (transaction conditions)."""
        result = {}
        # Contracts
        umowy = wt.findall('fa:Umowy', self.NS)
        if umowy:
            result['umowy'] = []
            for u in umowy:
                entry = {
                    'data': self._text(u, 'fa:DataUmowy'),
                    'numer': self._text(u, 'fa:NrUmowy'),
                }
                if any(v for v in entry.values()):
                    result['umowy'].append(entry)
        # Orders
        zamowienia = wt.findall('fa:Zamowienia', self.NS)
        if zamowienia:
            result['zamowienia'] = []
            for z in zamowienia:
                entry = {
                    'data': self._text(z, 'fa:DataZamowienia'),
                    'numer': self._text(z, 'fa:NrZamowienia'),
                }
                if any(v for v in entry.values()):
                    result['zamowienia'].append(entry)
        # Batch numbers
        partie = wt.findall('fa:NrPartiiTowaru', self.NS)
        if partie:
            result['nr_partii'] = [self._sanitize_text(p.text.strip()) for p in partie
                                    if p.text and p.text.strip()]
        # Delivery terms (Incoterms)
        result['warunki_dostawy'] = self._text(wt, 'fa:WarunkiDostawy')
        # Contractual exchange rate
        result['kurs_umowny'] = self._text(wt, 'fa:KursUmowny')
        result['waluta_umowna'] = self._text(wt, 'fa:WalutaUmowna')
        # Transport
        transporty = wt.findall('fa:Transport', self.NS)
        if transporty:
            result['transport'] = []
            for tr in transporty:
                t_entry = {}
                t_entry['rodzaj'] = self._text(tr, 'fa:RodzajTransportu')
                t_entry['transport_inny'] = self._text(tr, 'fa:TransportInny')
                t_entry['opis_innego'] = self._text(tr, 'fa:OpisInnegoTransportu')
                t_entry['nr_zlecenia'] = self._text(tr, 'fa:NrZleceniaTransportu')
                t_entry['opis_ladunku'] = self._text(tr, 'fa:OpisLadunku')
                t_entry['ladunek_inny'] = self._text(tr, 'fa:LadunekInny')
                t_entry['opis_innego_ladunku'] = self._text(tr, 'fa:OpisInnegoLadunku')
                t_entry['jednostka_opakowania'] = self._text(tr, 'fa:JednostkaOpakowania')
                t_entry['data_rozp'] = self._text(tr, 'fa:DataGodzRozpTransportu')
                t_entry['data_zak'] = self._text(tr, 'fa:DataGodzZakTransportu')
                # Carrier
                przewoznik = tr.find('fa:Przewoznik', self.NS)
                if przewoznik is not None:
                    dane = przewoznik.find('fa:DaneIdentyfikacyjne', self.NS)
                    if dane is not None:
                        t_entry['przewoznik_nazwa'] = self._text(dane, 'fa:Nazwa')
                        t_entry['przewoznik_nip'] = self._text(dane, 'fa:NIP')
                if any(v for v in t_entry.values()):
                    result['transport'].append(t_entry)
        # Intermediary
        result['podmiot_posredniczacy'] = self._text(wt, 'fa:PodmiotPosredniczacy')
        return result

    def _parse_annotations(self) -> Dict:
        ann = {}
        adnotacje = self.root.find('.//fa:Fa/fa:Adnotacje', self.NS)
        if adnotacje is None:
            return ann

        ann['p16'] = self._text(adnotacje, 'fa:P_16')
        ann['p17'] = self._text(adnotacje, 'fa:P_17')
        ann['p18'] = self._text(adnotacje, 'fa:P_18')
        ann['p18a'] = self._text(adnotacje, 'fa:P_18A')
        ann['p23'] = self._text(adnotacje, 'fa:P_23')

        zwolnienie = adnotacje.find('fa:Zwolnienie', self.NS)
        if zwolnienie is not None:
            ann['p19'] = self._text(zwolnienie, 'fa:P_19')
            ann['p19a'] = self._text(zwolnienie, 'fa:P_19A')
            ann['p19b'] = self._text(zwolnienie, 'fa:P_19B')
            ann['p19c'] = self._text(zwolnienie, 'fa:P_19C')

        # Margin scheme (PMarzy)
        pmarzy = adnotacje.find('fa:PMarzy', self.NS)
        if pmarzy is not None:
            ann['p_pmarzy'] = self._text(pmarzy, 'fa:P_PMarzy')
            ann['p_pmarzy_2'] = self._text(pmarzy, 'fa:P_PMarzy_2')
            ann['p_pmarzy_3_1'] = self._text(pmarzy, 'fa:P_PMarzy_3_1')
            ann['p_pmarzy_3_2'] = self._text(pmarzy, 'fa:P_PMarzy_3_2')
            ann['p_pmarzy_3_3'] = self._text(pmarzy, 'fa:P_PMarzy_3_3')

        # New transport vehicles (NoweSrodkiTransportu)
        nst = adnotacje.find('fa:NoweSrodkiTransportu', self.NS)
        if nst is not None:
            ann['p22'] = self._text(nst, 'fa:P_22')
            ann['p_42_5'] = self._text(nst, 'fa:P_42_5')
            vehicles = nst.findall('fa:NowySrodekTransportu', self.NS)
            if vehicles:
                ann['nowe_srodki'] = []
                for v in vehicles:
                    veh = {}
                    for fld, tag in [
                        ('p22a', 'fa:P_22A'), ('marka', 'fa:P_22BMK'),
                        ('model', 'fa:P_22BMD'), ('pojemnosc', 'fa:P_22BK'),
                        ('nr_id', 'fa:P_22BNR'), ('rok_prod', 'fa:P_22BRP'),
                        ('masa', 'fa:P_22B'), ('przebieg', 'fa:P_22B1'),
                        ('data_dopuszczenia', 'fa:P_22C'),
                        ('liczba_godz', 'fa:P_22D'),
                    ]:
                        val = self._text(v, tag)
                        if val:
                            veh[fld] = val
                    if veh:
                        ann['nowe_srodki'].append(veh)

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

    def _parse_podmiot3(self) -> List[Dict]:
        """Parse Podmiot3 (additional parties)."""
        parties = []
        for p3 in self.root.findall('.//fa:Podmiot3', self.NS):
            entry = {}
            dane = p3.find('fa:DaneIdentyfikacyjne', self.NS)
            if dane is not None:
                entry['nip'] = self._text(dane, 'fa:NIP')
                entry['nazwa'] = self._text(dane, 'fa:Nazwa')
                entry['kod_ue'] = self._text(dane, 'fa:KodUE')
                entry['nr_vat_ue'] = self._text(dane, 'fa:NrVatUE')
                entry['nr_id'] = self._text(dane, 'fa:NrID')
            adres = p3.find('fa:Adres', self.NS)
            if adres is not None:
                entry['kod_kraju'] = self._text(adres, 'fa:KodKraju')
                entry['adres_l1'] = self._text(adres, 'fa:AdresL1')
                entry['adres_l2'] = self._text(adres, 'fa:AdresL2')
            entry['nr_eori'] = self._text(p3, 'fa:NrEORI')
            entry['rola_inna'] = self._text(p3, 'fa:Rola/fa:RolaInna')
            entry['opis_roli'] = self._text(p3, 'fa:Rola/fa:OpisRoli')
            entry['udzial'] = self._text(p3, 'fa:Udzial')
            entry['nr_klienta'] = self._text(p3, 'fa:NrKlienta')
            if any(v for v in entry.values()):
                parties.append(entry)
        return parties

    def _parse_dodatkowy_opis(self) -> List[Dict]:
        """Parse DodatkowyOpis key-value pairs."""
        result = []
        fa = self.root.find('.//fa:Fa', self.NS)
        if fa is None:
            return result
        for do in fa.findall('fa:DodatkowyOpis', self.NS):
            klucz = self._text(do, 'fa:Klucz')
            wartosc = self._text(do, 'fa:Wartosc')
            if klucz or wartosc:
                result.append({'klucz': klucz, 'wartosc': wartosc})
        return result

    def _parse_dane_fa_korygowanej(self) -> List[Dict]:
        """Parse DaneFaKorygowanej (corrected invoice references)."""
        result = []
        fa = self.root.find('.//fa:Fa', self.NS)
        if fa is None:
            return result
        for dfk in fa.findall('fa:DaneFaKorygowanej', self.NS):
            entry = {
                'nr_ksef': self._text(dfk, 'fa:NrKSeFFaKorygowanej'),
                'nr_faktury': self._text(dfk, 'fa:NrFaKorygowanej'),
                'data_wyst': self._text(dfk, 'fa:DataWystFaKorygowanej'),
            }
            if any(v for v in entry.values()):
                result.append(entry)
        return result

    def _parse_faktury_zaliczkowe(self) -> List[Dict]:
        """Parse FakturaZaliczkowa (advance invoice references)."""
        result = []
        fa = self.root.find('.//fa:Fa', self.NS)
        if fa is None:
            return result
        for fz in fa.findall('fa:FakturaZaliczkowa', self.NS):
            entry = {
                'nr_ksef': self._text(fz, 'fa:NrKSeFFaZaliczkowej'),
                'nr_faktury': self._text(fz, 'fa:NrFaZaliczkowej'),
            }
            if any(v for v in entry.values()):
                result.append(entry)
        return result

    def _parse_zaliczki_czesciowe(self) -> List[Dict]:
        """Parse ZaliczkaCzesciowa (partial advance payments under Fa)."""
        result = []
        fa = self.root.find('.//fa:Fa', self.NS)
        if fa is None:
            return result
        for zc in fa.findall('fa:ZaliczkaCzesciowa', self.NS):
            entry = {
                'p6z': self._text(zc, 'fa:P_6Z'),
                'p15z': self._text(zc, 'fa:P_15Z'),
                'kurs_waluty': self._text(zc, 'fa:KursWalutyZW'),
            }
            if any(v for v in entry.values()):
                result.append(entry)
        return result

    def _parse_rozliczenie(self) -> Dict:
        """Parse Rozliczenie (surcharges and deductions)."""
        roz = {}
        rozliczenie = self.root.find('.//fa:Fa/fa:Rozliczenie', self.NS)
        if rozliczenie is None:
            return roz
        # Surcharges
        obciazenia = rozliczenie.findall('fa:Obciazenia', self.NS)
        if obciazenia:
            roz['obciazenia'] = []
            for o in obciazenia:
                roz['obciazenia'].append({
                    'kwota': self._text(o, 'fa:Kwota'),
                    'powod': self._text(o, 'fa:Powod'),
                })
        roz['suma_obciazen'] = self._text(rozliczenie, 'fa:SumaObciazen')
        # Deductions
        odliczenia = rozliczenie.findall('fa:Odliczenia', self.NS)
        if odliczenia:
            roz['odliczenia'] = []
            for o in odliczenia:
                roz['odliczenia'].append({
                    'kwota': self._text(o, 'fa:Kwota'),
                    'powod': self._text(o, 'fa:Powod'),
                })
        roz['suma_odliczen'] = self._text(rozliczenie, 'fa:SumaOdliczen')
        roz['do_zaplaty'] = self._text(rozliczenie, 'fa:DoZaplaty')
        roz['do_rozliczenia'] = self._text(rozliczenie, 'fa:DoRozliczenia')
        return roz

    def _parse_zamowienie(self) -> Dict:
        """Parse Zamowienie (order for advance invoices)."""
        zam = {}
        zamowienie = self.root.find('.//fa:Zamowienie', self.NS)
        if zamowienie is None:
            return zam
        zam['wartosc'] = self._text(zamowienie, 'fa:WartoscZamowienia')
        wiersze = zamowienie.findall('fa:ZamowienieWiersz', self.NS)
        if wiersze:
            zam['wiersze'] = []
            for w in wiersze:
                entry = {}
                for field, tag in [
                    ('nr', 'fa:NrWierszaZam'), ('p7z', 'fa:P_7Z'),
                    ('indeks', 'fa:IndeksZ'), ('p8az', 'fa:P_8AZ'),
                    ('p8bz', 'fa:P_8BZ'), ('p9az', 'fa:P_9AZ'),
                    ('p11z', 'fa:P_11NettoZ'), ('p11vatz', 'fa:P_11VatZ'),
                    ('p12z', 'fa:P_12Z'),
                ]:
                    val = self._text(w, tag)
                    if val:
                        entry[field] = val
                zam['wiersze'].append(entry)
        return zam

    def _parse_zalacznik(self) -> List[Dict]:
        """Parse Zalacznik (attachment data blocks)."""
        result = []
        for blok in self.root.findall('.//fa:Zalacznik/fa:BlokDanych', self.NS):
            entry = {'naglowek': self._text(blok, 'fa:ZNaglowek')}
            # Metadata
            meta = blok.findall('fa:MetaDane', self.NS)
            if meta:
                entry['metadane'] = []
                for m in meta:
                    entry['metadane'].append({
                        'klucz': self._text(m, 'fa:Klucz'),
                        'wartosc': self._text(m, 'fa:Wartosc'),
                    })
            # Text paragraphs
            tekst = blok.find('fa:Tekst', self.NS)
            if tekst is not None:
                akapity = tekst.findall('fa:Akapit', self.NS)
                if akapity:
                    entry['akapity'] = [self._sanitize_text(a.text.strip()) for a in akapity
                                        if a.text and a.text.strip()]
            if any(v for k, v in entry.items() if k != 'naglowek'):
                result.append(entry)
        return result


# ── FA_RR parser ───────────────────────────────────────────────────────────────

class FA_RRInvoiceXMLParser(InvoiceXMLParser):
    """Parser for FA_RR (Faktura VAT RR) — farmer flat-rate VAT invoices.

    Extends InvoiceXMLParser with FA_RR-specific sections:
    - farmer data (Podmiot2 = farmer/supplier, Podmiot1 = buyer)
    - declaration (OswiadczenieDostawcy)
    - FA_RR-specific VAT fields (KwotaVatRR, StawkaVatRR)

    Schema refs:
      v1-0E: http://crd.gov.pl/wzor/2024/02/19/12978/schemat.xsd
      v1-1E: http://crd.gov.pl/wzor/2025/01/23/13836/schemat.xsd
    """

    @property
    def schema_type(self) -> str:
        return SCHEMA_TYPE_FA_RR

    def parse(self) -> Dict:
        data = super().parse()
        data['schema_type'] = SCHEMA_TYPE_FA_RR

        # FA_RR: Podmiot1 = kupujący (nabywca), Podmiot2 = rolnik (dostawca)
        # Re-label roles to match FA_RR semantics
        data['farmer'] = data.pop('buyer', {})   # Podmiot2 = farmer
        data['buyer'] = data.pop('seller', {})   # Podmiot1 = actual buyer

        # FA_RR-specific VAT
        data['fa_rr'] = self._parse_fa_rr_fields()

        return data

    def _parse_fa_rr_fields(self) -> Dict:
        """Parse FA_RR-specific fields."""
        result = {}
        fa = self.root.find('.//fa:Fa', self.NS)
        if fa is None:
            return result

        # RR-specific VAT fields
        result['kwota_vat_rr'] = self._text(fa, 'fa:KwotaVatRR')
        result['stawka_vat_rr'] = self._text(fa, 'fa:StawkaVatRR')
        result['p15_rr'] = self._text(fa, 'fa:P_15RR')
        result['data_odbioru'] = self._text(fa, 'fa:DataOdbioru')

        # Farmer declaration
        oswiad = self.root.find('.//fa:OswiadczenieDostawcy', self.NS)
        if oswiad is not None:
            result['oswiadczenie'] = {
                'imie_nazwisko': self._text(oswiad, 'fa:ImieNazwiskoOsoba'),
                'nr_dowodu': self._text(oswiad, 'fa:NrDowoduOsoba'),
                'data': self._text(oswiad, 'fa:DataOswiadczenia'),
                'tresc': self._text(oswiad, 'fa:OswiadczenieRolnika'),
            }

        # Farmer identification (may have PESEL instead of NIP)
        farmer_dane = self.root.find('.//fa:Podmiot2/fa:DaneIdentyfikacyjne', self.NS)
        if farmer_dane is not None:
            result['farmer_pesel'] = self._text(farmer_dane, 'fa:PESEL')
            result['farmer_nr_id'] = self._text(farmer_dane, 'fa:NrID')

        return result


# ── PEF parser ─────────────────────────────────────────────────────────────────

class PEFInvoiceXMLParser(BaseInvoiceXMLParser):
    """Parser for PEF (PEPPOL UBL) invoices used in public procurement.

    Extracts basic invoice metadata from PEPPOL UBL Invoice-2 XML.
    Maps UBL elements to the common output dict used by PDF generators.

    Schema refs:
      UBL Invoice-2: urn:oasis:names:specification:ubl:schema:xsd:Invoice-2
      UBL CreditNote-2: urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2
    """

    _UBL_NS = 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'
    _CBC = 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'
    _CAC = 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'

    def __init__(self, xml_content: str):
        self.xml_content = xml_content
        self.root = None
        self._ns: Dict[str, str] = {}

    @property
    def schema_type(self) -> str:
        return SCHEMA_TYPE_PEF

    @staticmethod
    def _sanitize(value: str) -> str:
        return re.sub(r'<[^>]+>', '', value) if value else ''

    def _cbc(self, parent, local_name: str, default: str = '') -> str:
        if parent is None:
            return default
        el = parent.find(f'{{{self._CBC}}}{local_name}')
        if el is not None and el.text:
            return self._sanitize(el.text.strip())
        return default

    def _cac(self, parent, local_name: str):
        if parent is None:
            return None
        return parent.find(f'{{{self._CAC}}}{local_name}')

    def parse(self) -> Dict:
        try:
            self.root = ET.fromstring(self.xml_content)
        except ET.ParseError as e:
            logger.error("PEF XML parsing error: %s", e)
            raise

        invoice_number = self._cbc(self.root, 'ID')
        issue_date = self._cbc(self.root, 'IssueDate')
        due_date = self._cbc(self.root, 'DueDate')
        currency = self._cbc(self.root, 'DocumentCurrencyCode', 'PLN')
        note = self._cbc(self.root, 'Note')

        # Supplier (AccountingSupplierParty/Party)
        supplier_party = self._cac(self._cac(self.root, 'AccountingSupplierParty'), 'Party')
        seller = self._parse_pef_party(supplier_party)

        # Buyer (AccountingCustomerParty/Party)
        buyer_party = self._cac(self._cac(self.root, 'AccountingCustomerParty'), 'Party')
        buyer = self._parse_pef_party(buyer_party)

        # Totals (LegalMonetaryTotal)
        totals = self._cac(self.root, 'LegalMonetaryTotal')
        gross_amount = self._cbc(totals, 'PayableAmount') if totals is not None else ''
        tax_exclusive = self._cbc(totals, 'TaxExclusiveAmount') if totals is not None else ''

        # Tax total
        tax_total = self._cac(self.root, 'TaxTotal')
        vat_amount = self._cbc(tax_total, 'TaxAmount') if tax_total is not None else ''

        # Line items
        items = self._parse_pef_lines()

        logger.info("PEF invoice XML parsed successfully (ID=%s)", invoice_number)

        return {
            'schema_type': SCHEMA_TYPE_PEF,
            'ksef_metadata': {'ksef_number': ''},
            'header': {
                'p2': invoice_number,
                'p1': issue_date,
                'p6': due_date,
                'kod_waluty': currency,
                'p15': gross_amount,
                'rodzaj': 'PEF',
                'note': note,
            },
            'seller': seller,
            'buyer': buyer,
            'items': items,
            'vat_summary': {
                'TaxAmount': vat_amount,
                'TaxExclusiveAmount': tax_exclusive,
                'PayableAmount': gross_amount,
            },
            'payment': {},
            'annotations': {},
            'dodatkowy_opis': [],
            'dane_korygowanej': [],
            'faktury_zaliczkowe': [],
            'zaliczki_czesciowe': [],
            'rozliczenie': {},
            'zamowienie': {},
            'zalacznik': [],
            'footer': {},
            'podmiot3': [],
        }

    def _parse_pef_party(self, party) -> Dict:
        if party is None:
            return {}

        result: Dict = {}

        # Name
        party_name_el = self._cac(party, 'PartyName')
        result['nazwa'] = self._cbc(party_name_el, 'Name') if party_name_el is not None else ''

        # Tax (NIP/VAT)
        party_tax = self._cac(party, 'PartyTaxScheme')
        if party_tax is not None:
            company_id = self._cbc(party_tax, 'CompanyID')
            # Strip country prefix for NIP
            result['nip'] = re.sub(r'^PL', '', company_id) if company_id else ''

        # Legal entity registration name
        legal = self._cac(party, 'PartyLegalEntity')
        if legal is not None and not result.get('nazwa'):
            result['nazwa'] = self._cbc(legal, 'RegistrationName')

        # Address
        postal = self._cac(party, 'PostalAddress')
        if postal is not None:
            street = self._cbc(postal, 'StreetName')
            city = self._cbc(postal, 'CityName')
            zip_code = self._cbc(postal, 'PostalZone')
            country_el = self._cac(postal, 'Country')
            country = self._cbc(country_el, 'IdentificationCode') if country_el is not None else ''
            result['kod_kraju'] = country
            addr_parts = [p for p in [street, f'{zip_code} {city}'.strip()] if p]
            result['adres_l1'] = addr_parts[0] if addr_parts else ''
            result['adres_l2'] = addr_parts[1] if len(addr_parts) > 1 else ''

        # Contact
        contact = self._cac(party, 'Contact')
        if contact is not None:
            result['email'] = self._cbc(contact, 'ElectronicMail')
            result['telefon'] = self._cbc(contact, 'Telephone')

        return result

    def _parse_pef_lines(self) -> List[Dict]:
        items = []
        for line in self.root.findall(f'{{{self._CAC}}}InvoiceLine'):
            item: Dict = {}
            item['nr'] = self._cbc(line, 'ID')
            item['p11'] = self._cbc(line, 'LineExtensionAmount')  # net amount

            # Item details
            item_el = self._cac(line, 'Item')
            if item_el is not None:
                item['p7'] = self._cbc(item_el, 'Name')  # description
                item['p8a'] = self._cbc(item_el, 'Description')

            # Price
            price_el = self._cac(line, 'Price')
            if price_el is not None:
                item['p9a'] = self._cbc(price_el, 'PriceAmount')  # unit price

            # Quantity
            item['p8b'] = self._cbc(line, 'InvoicedQuantity')

            # Tax
            tax_total = self._cac(line, 'TaxTotal')
            if tax_total is not None:
                item['p11vat'] = self._cbc(tax_total, 'TaxAmount')
                tax_sub = self._cac(tax_total, 'TaxSubtotal')
                if tax_sub is not None:
                    tax_cat = self._cac(tax_sub, 'TaxCategory')
                    if tax_cat is not None:
                        item['p12'] = self._cbc(tax_cat, 'Percent')  # VAT rate %

            if any(v for v in item.values()):
                items.append(item)
        return items


# ── Fallback parser ────────────────────────────────────────────────────────────

class FallbackInvoiceXMLParser(BaseInvoiceXMLParser):
    """Minimal parser for unrecognised XML schemas.

    Attempts to extract a few common fields from arbitrary XML.
    PDF generation will be skipped for UNKNOWN schema type.
    """

    def __init__(self, xml_content: str):
        self.xml_content = xml_content

    @property
    def schema_type(self) -> str:
        return SCHEMA_TYPE_UNKNOWN

    def parse(self) -> Dict:
        logger.warning("Using FallbackInvoiceXMLParser — XML schema not recognised")
        try:
            root = ET.fromstring(self.xml_content)
        except ET.ParseError as e:
            logger.error("Fallback XML parse error: %s", e)
            return self._empty_data()

        # Best-effort: grab any text from common-looking tags
        ns_match = re.match(r'\{(.+?)\}', root.tag)
        namespace = ns_match.group(1) if ns_match else ''

        data = self._empty_data()
        data['header']['raw_root_tag'] = root.tag
        data['header']['raw_namespace'] = namespace
        return data

    @staticmethod
    def _empty_data() -> Dict:
        return {
            'schema_type': SCHEMA_TYPE_UNKNOWN,
            'ksef_metadata': {'ksef_number': ''},
            'header': {'rodzaj': 'UNKNOWN', 'p2': '', 'p1': '', 'p15': '', 'kod_waluty': 'PLN'},
            'seller': {},
            'buyer': {},
            'items': [],
            'vat_summary': {},
            'payment': {},
            'annotations': {},
            'dodatkowy_opis': [],
            'dane_korygowanej': [],
            'faktury_zaliczkowe': [],
            'zaliczki_czesciowe': [],
            'rozliczenie': {},
            'zamowienie': {},
            'zalacznik': [],
            'footer': {},
            'podmiot3': [],
        }
