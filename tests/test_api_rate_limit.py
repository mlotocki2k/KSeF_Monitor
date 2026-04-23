"""Tests for per-endpoint rate limits (V5-06)."""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.api._limiter as limiter_module
from app.api import create_app

_DEFAULT_LIMITS = {
    "trigger": "2/minute",
    "initial_load_start": "1/hour",
    "push_regenerate": "5/hour",
    "push_reset": "1/hour",
    "invoice_download": "30/minute",
}


def _bearer():
    return {"Authorization": "Bearer " + "a" * 32}


def _make_app(rl_config):
    """Helper to create a fresh app with given rate_limit_config."""
    monitor = MagicMock()
    monitor.trigger_check = MagicMock(return_value=None)
    return create_app(
        auth_token="a" * 32,
        monitor_instance=monitor,
        rate_limit_config=rl_config,
    )


@pytest.fixture(autouse=True)
def reset_limiter():
    """Reset the module-level limiter storage and _endpoint_limits between tests."""
    yield
    # Reset slowapi bucket state
    try:
        limiter_module.limiter.reset()
    except Exception:
        pass
    # Restore default endpoint limits
    limiter_module._endpoint_limits.update(_DEFAULT_LIMITS)
    # Disable limiter (default state) to avoid affecting other test suites
    limiter_module.limiter.enabled = False


@pytest.fixture
def app_rl_tight():
    """App with tight per-endpoint limits for testing."""
    return _make_app(
        {
            "enabled": True,
            "default": "1000/minute",      # high, so only per-endpoint limits fire
            "trigger": "2/minute",
            "invoice_download": "3/minute",
            "push_regenerate": "2/hour",
            "push_reset": "1/hour",
            "initial_load_start": "1/hour",
        }
    )


@pytest.fixture
def client_rl_tight(app_rl_tight):
    return TestClient(app_rl_tight)


class TestTriggerRateLimit:
    def test_trigger_allows_within_limit(self, client_rl_tight):
        r1 = client_rl_tight.post("/api/v1/monitor/trigger", headers=_bearer())
        r2 = client_rl_tight.post("/api/v1/monitor/trigger", headers=_bearer())
        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_trigger_blocks_over_limit(self, client_rl_tight):
        # Consume the 2/minute budget
        client_rl_tight.post("/api/v1/monitor/trigger", headers=_bearer())
        client_rl_tight.post("/api/v1/monitor/trigger", headers=_bearer())
        r3 = client_rl_tight.post("/api/v1/monitor/trigger", headers=_bearer())
        assert r3.status_code == 429


class TestInvoiceDownloadRateLimit:
    def test_xml_blocks_over_limit(self, app_rl_tight):
        # Use raise_server_exceptions=False so DB/monitor errors don't abort the test.
        # We only care that the 4th request gets a 429 (rate limit enforced).
        client = TestClient(app_rl_tight, raise_server_exceptions=False)
        headers = _bearer()
        ksef = "1234567890-20260101-ABCDEF-01"
        # 3/minute budget — consume it (responses may be 404/500, that's OK)
        for _ in range(3):
            client.get(f"/api/v1/invoices/{ksef}/xml", headers=headers)
        resp = client.get(f"/api/v1/invoices/{ksef}/xml", headers=headers)
        assert resp.status_code == 429

    def test_pdf_blocks_over_limit(self, app_rl_tight):
        client = TestClient(app_rl_tight, raise_server_exceptions=False)
        headers = _bearer()
        ksef = "1234567890-20260101-ABCDEF-01"
        # 3/minute budget
        for _ in range(3):
            client.get(f"/api/v1/invoices/{ksef}/pdf", headers=headers)
        resp = client.get(f"/api/v1/invoices/{ksef}/pdf", headers=headers)
        assert resp.status_code == 429


class TestDisabledRateLimit:
    def test_disabled_rate_limit_allows_many(self):
        """When rate_limit.enabled=False, no 429s regardless of count."""
        app = _make_app(
            {"enabled": False, "default": "1/minute", "trigger": "1/minute"}
        )
        client = TestClient(app)
        for _ in range(5):
            resp = client.post("/api/v1/monitor/trigger", headers=_bearer())
            assert resp.status_code == 200
