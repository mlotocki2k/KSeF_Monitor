"""
Unit tests for PDF generation security: HTML/XML sanitization in InvoiceXMLParser.
"""

import pytest
from app.invoice_pdf_generator import InvoiceXMLParser


class TestSanitizeText:
    """Tests for InvoiceXMLParser._sanitize_text (defense-in-depth)."""

    def test_plain_text_unchanged(self):
        """Plain text passes through unchanged."""
        assert InvoiceXMLParser._sanitize_text("Firma ABC") == "Firma ABC"

    def test_html_tags_stripped(self):
        """HTML tags are removed."""
        assert InvoiceXMLParser._sanitize_text('<script>alert("xss")</script>') == 'alert(&quot;xss&quot;)'

    def test_img_onerror_stripped(self):
        """img onerror payload is stripped."""
        result = InvoiceXMLParser._sanitize_text('<img src=x onerror="fetch(\'evil\')">')
        assert "<img" not in result
        assert "onerror" not in result

    def test_html_entities_escaped(self):
        """HTML special characters are escaped."""
        result = InvoiceXMLParser._sanitize_text('A & B <> "C"')
        assert "&amp;" in result
        assert "&lt;" in result
        assert "&gt;" in result
        assert "&quot;" in result

    def test_reportlab_eval_payload_neutralized(self):
        """ReportLab eval() payloads in span/unichar tags are stripped."""
        payload = '<span color="[[[getattr(pow,__doc__)]]]">text</span>'
        result = InvoiceXMLParser._sanitize_text(payload)
        assert "<span" not in result
        assert "getattr" not in result

    def test_nested_tags_stripped(self):
        """Nested HTML tags are all removed."""
        result = InvoiceXMLParser._sanitize_text('<div><b><script>x</script></b></div>')
        assert "<" not in result or "&lt;" in result

    def test_polish_characters_preserved(self):
        """Polish diacritical marks are preserved."""
        text = "Spółka z ograniczoną odpowiedzialnością"
        assert InvoiceXMLParser._sanitize_text(text) == text

    def test_empty_string(self):
        """Empty string returns empty."""
        assert InvoiceXMLParser._sanitize_text("") == ""

    def test_numeric_values_preserved(self):
        """Numeric values used in invoice amounts pass through."""
        assert InvoiceXMLParser._sanitize_text("1234.56") == "1234.56"

    def test_invoice_number_with_slashes(self):
        """Invoice numbers with slashes are preserved."""
        assert InvoiceXMLParser._sanitize_text("FV/2026/03/001") == "FV/2026/03/001"


class TestXMLParserSanitizesOutput:
    """Integration test: verify _text() sanitizes XML content."""

    MINIMAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
    <Faktura xmlns="http://crd.gov.pl/wzor/2025/06/25/13775/">
        <Naglowek>
            <KodFormularza>FA</KodFormularza>
        </Naglowek>
        <Podmiot1>
            <DaneIdentyfikacyjne>
                <NIP>1234567890</NIP>
                <Nazwa>{seller_name}</Nazwa>
            </DaneIdentyfikacyjne>
        </Podmiot1>
        <Fa>
            <RodzajFaktury>VAT</RodzajFaktury>
            <KodWaluty>PLN</KodWaluty>
            <P_2>FV/001</P_2>
            <P_1>2026-03-10</P_1>
        </Fa>
    </Faktura>"""

    def test_raw_html_in_xml_rejected_by_parser(self):
        """Raw HTML tags in XML are rejected by defusedxml (invalid XML)."""
        xml = self.MINIMAL_XML.format(
            seller_name='<img src=x onerror="alert(1)">Evil Corp'
        )
        parser = InvoiceXMLParser(xml)
        with pytest.raises(Exception):
            parser.parse()

    def test_xml_escaped_html_entities_double_escaped(self):
        """XML-escaped HTML entities get double-escaped by _sanitize_text (defense-in-depth)."""
        # In real XML, &lt;script&gt; is valid text content — XML parser decodes to <script>
        # _sanitize_text must then strip the tag and escape remaining chars
        xml = self.MINIMAL_XML.format(
            seller_name='&lt;script&gt;alert("xss")&lt;/script&gt;Evil Corp'
        )
        parser = InvoiceXMLParser(xml)
        data = parser.parse()
        seller_name = data['seller']['nazwa']
        assert "<script>" not in seller_name
        assert "Evil Corp" in seller_name

    def test_ampersand_in_seller_name_escaped(self):
        """Ampersand in company name is properly escaped for PDF rendering."""
        xml = self.MINIMAL_XML.format(seller_name="Firma A &amp; B Sp. z o.o.")
        parser = InvoiceXMLParser(xml)
        data = parser.parse()
        seller_name = data['seller']['nazwa']
        assert "&amp;" in seller_name  # html.escape converts & to &amp;
        assert "<" not in seller_name

    def test_normal_seller_name_preserved(self):
        """Normal Polish company names pass through correctly."""
        xml = self.MINIMAL_XML.format(seller_name="Spółka ABC Sp. z o.o.")
        parser = InvoiceXMLParser(xml)
        data = parser.parse()
        assert data['seller']['nazwa'] == "Spółka ABC Sp. z o.o."
