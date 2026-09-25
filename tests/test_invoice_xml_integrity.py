"""
Invoice XML is decoded as UTF-8 from the raw bytes (not requests' charset
guess) and checked against the x-ms-meta-hash header when KSeF sends one.
"""

import base64
import hashlib
from unittest.mock import MagicMock

import pytest

from app.ksef_client import KSeFClient

KSEF_NO = "1234567890-20260301-ABCDEF-XY"
XML = '<?xml version="1.0" encoding="UTF-8"?><Faktura><Nazwa>Zażółć gęślą jaźń</Nazwa></Faktura>'


@pytest.fixture
def client(mock_config):
    c = KSeFClient(mock_config)
    c.access_token = "valid-token"
    return c


def _resp(raw: bytes, header=None):
    r = MagicMock()
    r.status_code = 200
    r.content = raw
    r.text = raw.decode("latin-1")  # what a wrong charset guess would give
    r.headers = {"x-ms-meta-hash": header} if header is not None else {}
    r.raise_for_status = MagicMock()
    return r


def _b64sha(raw: bytes) -> str:
    return base64.b64encode(hashlib.sha256(raw).digest()).decode()


def test_decodes_utf8_from_bytes(client):
    raw = XML.encode("utf-8")
    client.session.request = MagicMock(return_value=_resp(raw, _b64sha(raw)))
    result = client.get_invoice_xml(KSEF_NO)
    assert result["xml_content"] == XML
    assert result["hash_verified"] is True


def test_hash_mismatch_rejected(client):
    raw = XML.encode("utf-8")
    client.session.request = MagicMock(return_value=_resp(raw, _b64sha(b"other")))
    assert client.get_invoice_xml(KSEF_NO) is None


def test_missing_hash_header_accepted_unverified(client):
    raw = XML.encode("utf-8")
    client.session.request = MagicMock(return_value=_resp(raw))
    result = client.get_invoice_xml(KSEF_NO)
    assert result["xml_content"] == XML
    assert result["hash_verified"] is False


def test_bom_stripped_from_text(client):
    raw = b"\xef\xbb\xbf" + XML.encode("utf-8")
    client.session.request = MagicMock(return_value=_resp(raw, _b64sha(raw)))
    assert client.get_invoice_xml(KSEF_NO)["xml_content"] == XML
