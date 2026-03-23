"""
KSeF Invoice XML Parser

Parses KSeF FA_VAT XML invoices (FA(3) schema) into a structured dict.
Auto-detects XML namespace. Uses defusedxml for secure XML parsing.

Extracted from invoice_pdf_generator.py for reuse across PDF generators
and future multi-schema support (FA(2), PEF, FA_RR in v0.5).

Schema reference:
  XSD: http://crd.gov.pl/wzor/2025/06/25/13775/schemat.xsd
"""

import logging
import re
from defusedxml import ElementTree as ET
from typing import Dict, List

logger = logging.getLogger(__name__)


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
                logger.debug("Detected XML namespace: %s", ns_match.group(1))

            data = {
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
