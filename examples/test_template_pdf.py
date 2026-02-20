#!/usr/bin/env python3
"""
Generate a test PDF invoice using the HTML/CSS template renderer (xhtml2pdf).

Produces the same invoice as test_dummy_pdf.py but via the template-based
pipeline, allowing visual comparison between ReportLab and template output.

Usage:
    python examples/test_template_pdf.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.invoice_pdf_generator import InvoiceXMLParser

DUMMY_XML = '''\
<?xml version="1.0" encoding="UTF-8"?>
<Faktura xmlns="http://crd.gov.pl/wzor/2025/06/25/13775/">
  <Naglowek>
    <KodFormularza>FA</KodFormularza>
    <WariantFormularza>3</WariantFormularza>
    <DataWytworzeniaFa>2026-02-18T10:30:00</DataWytworzeniaFa>
  </Naglowek>
  <Podmiot1>
    <DaneIdentyfikacyjne>
      <NIP>5213000099</NIP>
      <Nazwa>Testowa Firma Sp. z o.o.</Nazwa>
    </DaneIdentyfikacyjne>
    <Adres>
      <KodKraju>PL</KodKraju>
      <AdresL1>ul. Marszalkowska 10</AdresL1>
      <AdresL2>00-001 Warszawa</AdresL2>
    </Adres>
  </Podmiot1>
  <Podmiot2>
    <DaneIdentyfikacyjne>
      <NIP>1234567890</NIP>
      <Nazwa>Odbiorca Testowy S.A.</Nazwa>
    </DaneIdentyfikacyjne>
    <Adres>
      <KodKraju>PL</KodKraju>
      <AdresL1>ul. Dluga 25/3</AdresL1>
      <AdresL2>31-100 Krakow</AdresL2>
    </Adres>
  </Podmiot2>
  <Fa>
    <KodWaluty>PLN</KodWaluty>
    <P_1>2026-02-18</P_1>
    <P_1M>Warszawa</P_1M>
    <P_2>FV/2026/02/001</P_2>
    <P_6>2026-02-15</P_6>
    <RodzajFaktury>VAT</RodzajFaktury>
    <FaWiersz>
      <NrWierszaFa>1</NrWierszaFa>
      <P_7>Uslugi programistyczne - luty 2026</P_7>
      <P_8A>godz.</P_8A>
      <P_8B>160</P_8B>
      <P_9A>150.00</P_9A>
      <P_11>24000.00</P_11>
      <P_11Vat>5520.00</P_11Vat>
      <P_12>23</P_12>
    </FaWiersz>
    <FaWiersz>
      <NrWierszaFa>2</NrWierszaFa>
      <P_7>Hosting i utrzymanie serwera - luty 2026</P_7>
      <P_8A>szt.</P_8A>
      <P_8B>1</P_8B>
      <P_9A>500.00</P_9A>
      <P_11>500.00</P_11>
      <P_11Vat>115.00</P_11Vat>
      <P_12>23</P_12>
    </FaWiersz>
    <P_13_1>24500.00</P_13_1>
    <P_14_1>5635.00</P_14_1>
    <P_15>30135.00</P_15>
    <Adnotacje>
      <P_16>2</P_16>
      <P_17>2</P_17>
      <P_18>2</P_18>
      <P_18A>1</P_18A>
      <Zwolnienie>
        <P_19>2</P_19>
      </Zwolnienie>
    </Adnotacje>
    <Platnosc>
      <TerminPlatnosci>
        <Termin>2026-03-04</Termin>
      </TerminPlatnosci>
      <FormaPlatnosci>6</FormaPlatnosci>
      <RachunekBankowy>
        <NrRB>61109010140000071219812874</NrRB>
        <SWIFT>WBKPPLPP</SWIFT>
        <NazwaBanku>Santander Bank Polska S.A.</NazwaBanku>
        <OpisRachunku>Rachunek glowny PLN</OpisRachunku>
      </RachunekBankowy>
    </Platnosc>
  </Fa>
  <Stopka>
    <Informacje>
      <StopkaFaktury>Prosimy o terminowa zaplate na wskazany rachunek bankowy.</StopkaFaktury>
    </Informacje>
    <Rejestry>
      <PelnaNazwa>Testowa Firma Sp. z o.o.</PelnaNazwa>
      <KRS>0000123456</KRS>
      <REGON>123456789</REGON>
    </Rejestry>
  </Stopka>
</Faktura>
'''

KSEF_NUMBER = '5213000099-20260218-A1B2C3D4E5F6-XY'


def main():
    try:
        from app.invoice_pdf_template import InvoicePDFTemplateRenderer, XHTML2PDF_AVAILABLE
    except ImportError:
        print("ERROR: Cannot import InvoicePDFTemplateRenderer")
        print("Make sure you are running from the project root directory")
        sys.exit(1)

    if not XHTML2PDF_AVAILABLE:
        print("ERROR: xhtml2pdf is not installed")
        print("Install with: pip install xhtml2pdf")
        sys.exit(1)

    # Parse XML
    parser = InvoiceXMLParser(DUMMY_XML)
    invoice_data = parser.parse()
    invoice_data['ksef_metadata']['ksef_number'] = KSEF_NUMBER

    # Generate template-based PDF
    output_file = os.path.join(os.path.dirname(__file__), 'test_output_template.pdf')
    print(f"Generating template-based PDF: {output_file}")
    print(f"KSeF number: {KSEF_NUMBER}")

    renderer = InvoicePDFTemplateRenderer()
    renderer.render(
        invoice_data,
        ksef_number=KSEF_NUMBER,
        xml_content=DUMMY_XML,
        environment='test',
        timezone='Europe/Warsaw',
        output_path=output_file,
    )

    size = os.path.getsize(output_file)
    print(f"Template PDF generated successfully: {output_file} ({size} bytes)")
    print()
    print("Compare with ReportLab PDF:")
    print("  python examples/test_dummy_pdf.py  -> test_output_przelew.pdf")
    print("  python examples/test_template_pdf.py -> test_output_template.pdf")


if __name__ == '__main__':
    main()
