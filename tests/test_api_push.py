"""Tests for /api/v1/push/** endpoints — masking + auth gating (V5-02)."""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api import create_app


@pytest.fixture
def mock_push_manager():
    pm = MagicMock()
    pm.pairing_info = {
        "instance_id": "abc-123",
        "pairing_code_masked": "A\u2026F",
        "registered_at": "2026-04-21T00:00:00Z",
        "is_registered": True,
    }
    pm.pairing_info_sensitive = {
        "instance_id": "abc-123",
        "pairing_code": "ABCD1234ABCD1234",
        "registered_at": "2026-04-21T00:00:00Z",
        "is_registered": True,
        "qr_data_uri": "data:image/png;base64,XXX",
    }
    return pm


@pytest.fixture
def app_with_push(mock_push_manager):
    return create_app(auth_token="a" * 32, push_manager=mock_push_manager)


@pytest.fixture
def client_with_push(app_with_push):
    return TestClient(app_with_push)


def _bearer():
    return {"Authorization": "Bearer " + "a" * 32}


class TestPushSetupMasking:
    def test_setup_requires_auth(self, client_with_push):
        """After Task 4, /push/setup is no longer whitelisted."""
        resp = client_with_push.get("/api/v1/push/setup")
        assert resp.status_code == 401

    def test_setup_returns_masked_only(self, client_with_push):
        resp = client_with_push.get("/api/v1/push/setup", headers=_bearer())
        assert resp.status_code == 200
        body = resp.json()
        assert "pairing_code_masked" in body
        assert "pairing_code" not in body
        assert "qr_data_uri" not in body
        assert body["pairing_code_masked"] == "A\u2026F"


class TestPushPairingFullReveal:
    def test_pairing_requires_auth(self, client_with_push):
        resp = client_with_push.get("/api/v1/push/pairing")
        assert resp.status_code == 401

    def test_pairing_returns_full_with_auth(self, client_with_push):
        resp = client_with_push.get("/api/v1/push/pairing", headers=_bearer())
        assert resp.status_code == 200
        body = resp.json()
        assert body["pairing_code"] == "ABCD1234ABCD1234"
        assert body["qr_data_uri"].startswith("data:image/png;base64,")


class TestPushSetup503:
    def test_setup_503_when_no_push_manager(self):
        app = create_app(auth_token="a" * 32)
        client = TestClient(app)
        resp = client.get("/api/v1/push/setup", headers=_bearer())
        assert resp.status_code == 503

    def test_pairing_503_when_no_push_manager(self):
        app = create_app(auth_token="a" * 32)
        client = TestClient(app)
        resp = client.get("/api/v1/push/pairing", headers=_bearer())
        assert resp.status_code == 503
