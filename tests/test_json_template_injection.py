"""
Shipped JSON notification templates must produce valid JSON whose fields
equal the (untrusted) invoice values — no field injection, no broken payload.
"""

import json

import pytest

from app.template_renderer import TemplateRenderer, json_number_filter

JSON_CHANNELS = ["webhook", "ios_push", "slack", "discord"]

# Buyer identifier of type "Other" is typed in by the invoice issuer.
INJECTED_NIP = '","currency":"EUR'


def _context(**overrides):
    ctx = {
        "ksef_number": "1234567890-20260101-ABCDEF-12",
        "invoice_number": "FV/1/2026",
        "issue_date": "2026-01-01",
        "gross_amount": 123.45,
        "net_amount": 100.37,
        "vat_amount": 23.08,
        "currency": "PLN",
        "seller_name": "ACME\\",
        "seller_nip": INJECTED_NIP,
        "buyer_name": "Line1\nLine2\t\"quoted\"",
        "buyer_nip": INJECTED_NIP,
        "subject_type": "Subject3",
        "schema_type": "FA3",
        "title": "Nowa faktura",
        "priority": 0,
        "priority_emoji": "📋",
        "priority_name": "normal",
        "priority_color": "#36a64f",
        "priority_color_int": 0x3498DB,
        "timestamp": "2026-01-01T00:00:00Z",
        "notification_id": "abc",
        "url": None,
    }
    ctx.update(overrides)
    return ctx


@pytest.mark.parametrize("channel", JSON_CHANNELS)
def test_untrusted_fields_cannot_inject_json(channel):
    rendered = TemplateRenderer().render(channel, _context())
    payload = json.loads(rendered)
    flat = json.dumps(payload, ensure_ascii=False)
    # Injected text survives only as data, never as a key/value pair.
    assert '"currency": "EUR"' not in flat
    if channel in ("webhook", "ios_push"):
        section = payload["invoice"] if channel == "webhook" else payload["data"]
        assert section["currency"] == "PLN"
        assert section["buyer_nip"] == INJECTED_NIP
        assert section["seller_nip"] == INJECTED_NIP
        assert section["seller_name"] == "ACME\\"


@pytest.mark.parametrize("channel", JSON_CHANNELS)
def test_missing_amount_still_valid_json(channel):
    rendered = TemplateRenderer().render(
        channel, _context(gross_amount="N/A", net_amount=None, vat_amount=None)
    )
    payload = json.loads(rendered)
    if channel == "webhook":
        assert payload["invoice"]["gross_amount"] == 0
        assert payload["invoice"]["net_amount"] == 0
    if channel == "ios_push":
        assert payload["data"]["gross_amount"] == 0


@pytest.mark.parametrize("channel", JSON_CHANNELS)
def test_quote_in_currency_and_date_still_valid_json(channel):
    rendered = TemplateRenderer().render(
        channel, _context(currency='PL"N', issue_date='2026"01')
    )
    json.loads(rendered)


def test_json_number_filter():
    assert json_number_filter(12.5) == "12.5"
    assert json_number_filter(7) == "7"
    assert json_number_filter("12.50") == "12.5"
    assert json_number_filter(None) == "0"
    assert json_number_filter("N/A") == "0"
    assert json_number_filter("1,0") == "0"
    assert json_number_filter(float("nan")) == "0"
    assert json_number_filter(float("inf")) == "0"
    assert json_number_filter(True) == "0"
