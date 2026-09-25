"""Uncached XML/PDF fetches answer 503 instead of blocking in the KSeF limiter."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api import create_app

TOKEN = "t" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}
KSEF = "1234567890-20260101-ABCDEF-12"


def _client(remaining):
    monitor = MagicMock()
    monitor.ksef.rate_limiter.remaining.return_value = {**remaining, "total_calls": 0, "total_waits": 0}
    monitor.ksef.get_invoice_xml.return_value = {"xml_content": "<Faktura/>"}
    return TestClient(create_app(db=None, monitor_instance=monitor, auth_token=TOKEN)), monitor


@pytest.mark.parametrize("remaining", [
    {"1s": 10, "60s": 0, "3600s": 50},     # minute window full
    {"1s": 10, "60s": 30, "3600s": 10},    # hourly reserve for the monitor
])
@pytest.mark.parametrize("kind", ["xml", "pdf"])
def test_exhausted_budget_returns_503(remaining, kind):
    client, monitor = _client(remaining)
    r = client.get(f"/api/v1/invoices/{KSEF}/{kind}", headers=AUTH)
    assert r.status_code == 503
    assert "Retry-After" in r.headers
    monitor.ksef.get_invoice_xml.assert_not_called()


def test_budget_available_fetches_live():
    client, monitor = _client({"1s": 10, "60s": 30, "3600s": 100})
    r = client.get(f"/api/v1/invoices/{KSEF}/xml", headers=AUTH)
    assert r.status_code == 200
    monitor.ksef.get_invoice_xml.assert_called_once()
