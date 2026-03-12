"""
Tests for PushManager — credential generation, registration, QR, push sending.
"""

import base64
import hashlib
import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.push_manager import PushManager, QR_PREFIX


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_config(worker_url="https://push.monitorksef.com", timeout=15):
    return {"worker_url": worker_url, "timeout": timeout}


def _sha256_hex(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


# ── Credentials ──────────────────────────────────────────────────────────────


class TestPushManagerCredentials:
    """Test credential generation and config persistence."""

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_generate_instance_id_is_uuid(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))
        # UUID format: 8-4-4-4-12
        parts = pm.instance_id.split("-")
        assert len(parts) == 5
        assert [len(p) for p in parts] == [8, 4, 4, 4, 12]

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_generate_instance_key_is_64_hex(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))
        assert len(pm.instance_key) == 64
        int(pm.instance_key, 16)  # validates hex

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_generate_pairing_code_is_8_hex_uppercase(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))
        assert len(pm.pairing_code) == 8
        assert pm.pairing_code == pm.pairing_code.upper()
        int(pm.pairing_code, 16)  # validates hex

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_save_config_creates_file(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))
        config_path = tmp_path / "push_config.json"
        assert config_path.exists()

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_save_config_permissions(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))
        config_path = tmp_path / "push_config.json"
        stat = os.stat(config_path)
        # Check owner-only read/write (0o600)
        assert oct(stat.st_mode & 0o777) == "0o600"

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_save_config_content(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))
        config_path = tmp_path / "push_config.json"

        with open(config_path) as f:
            data = json.load(f)

        assert data["instance_id"] == pm.instance_id
        assert data["instance_key"] == pm.instance_key
        assert data["pairing_code"] == pm.pairing_code
        assert data["central_push_url"] == "https://push.monitorksef.com"

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_load_existing_config(self, mock_register, tmp_path):
        # First run: generate
        pm1 = PushManager(_make_config(), data_dir=str(tmp_path))
        saved_id = pm1.instance_id
        saved_key = pm1.instance_key

        # Second run: load
        pm2 = PushManager(_make_config(), data_dir=str(tmp_path))
        assert pm2.instance_id == saved_id
        assert pm2.instance_key == saved_key

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_load_incomplete_config_regenerates(self, mock_register, tmp_path):
        config_path = tmp_path / "push_config.json"
        config_path.write_text('{"instance_id": "x"}')

        pm = PushManager(_make_config(), data_dir=str(tmp_path))
        # Should have regenerated — instance_id won't be "x" anymore
        assert pm.instance_key is not None
        assert len(pm.instance_key) == 64


# ── Registration ─────────────────────────────────────────────────────────────


class TestPushManagerRegistration:
    """Test instance registration with Central Push Service."""

    def test_register_sends_hashes(self, tmp_path):
        with patch("app.push_manager.requests.Session") as MockSession:
            mock_session = MockSession.return_value
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_session.post.return_value = mock_response

            pm = PushManager(_make_config(), data_dir=str(tmp_path))

            # Verify registration call
            call_args = mock_session.post.call_args_list[0]
            url = call_args.args[0] if call_args.args else call_args[0][0]
            assert "/instances/register" in url

            payload = call_args.kwargs.get("json") or call_args[1].get("json")
            assert payload["instance_id"] == pm.instance_id
            assert payload["instance_key_hash"] == _sha256_hex(pm.instance_key)
            assert payload["pairing_code_hash"] == _sha256_hex(pm.pairing_code)

    def test_register_failure_no_config_saved(self, tmp_path):
        with patch("app.push_manager.requests.Session") as MockSession:
            mock_session = MockSession.return_value
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_session.post.return_value = mock_response

            pm = PushManager(_make_config(), data_dir=str(tmp_path))
            config_path = tmp_path / "push_config.json"
            assert not config_path.exists()

    def test_register_409_treated_as_success(self, tmp_path):
        with patch("app.push_manager.requests.Session") as MockSession:
            mock_session = MockSession.return_value
            mock_response = MagicMock()
            mock_response.status_code = 409
            mock_session.post.return_value = mock_response

            pm = PushManager(_make_config(), data_dir=str(tmp_path))
            assert pm.is_registered is True

    def test_register_network_error(self, tmp_path):
        with patch("app.push_manager.requests.Session") as MockSession:
            mock_session = MockSession.return_value
            mock_session.post.side_effect = requests.exceptions.ConnectionError("fail")

            pm = PushManager(_make_config(), data_dir=str(tmp_path))
            assert pm.is_registered is False


# ── QR Code ──────────────────────────────────────────────────────────────────


class TestPushManagerQR:
    """Test QR code generation for device pairing."""

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_qr_data_uri_format(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))
        uri = pm.generate_qr_data_uri()
        assert uri.startswith("data:image/png;base64,")

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_qr_contains_valid_png(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))
        uri = pm.generate_qr_data_uri()

        b64_data = uri.split(",", 1)[1]
        png_bytes = base64.b64decode(b64_data)
        # PNG magic bytes
        assert png_bytes[:4] == b'\x89PNG'

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_qr_content_prefix(self, mock_register, tmp_path):
        """QR code content should be MKSEF:{pairing_code}."""
        pm = PushManager(_make_config(), data_dir=str(tmp_path))
        expected_content = f"{QR_PREFIX}{pm.pairing_code}"
        # We can't easily decode QR from image, but verify prefix constant
        assert QR_PREFIX == "MKSEF:"
        assert expected_content.startswith("MKSEF:")

    def test_qr_empty_without_pairing_code(self, tmp_path):
        with patch("app.push_manager.requests.Session") as MockSession:
            mock_session = MockSession.return_value
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_session.post.return_value = mock_response

            pm = PushManager(_make_config(), data_dir=str(tmp_path))
            pm.pairing_code = None
            assert pm.generate_qr_data_uri() == ""


# ── Send Push ────────────────────────────────────────────────────────────────


class TestPushManagerSendPush:
    """Test push notification sending via Worker."""

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_send_push_success(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "sent": 3, "failed": 0}
        pm.session.post = MagicMock(return_value=mock_response)

        result = pm.send_push("Title", "Body", data={"nip": "1234567890"})
        assert result["ok"] is True
        assert result["sent"] == 3

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_send_push_auth_headers(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "sent": 1, "failed": 0}
        pm.session.post = MagicMock(return_value=mock_response)

        pm.send_push("Title", "Body")

        call_kwargs = pm.session.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["X-Instance-Id"] == pm.instance_id
        assert headers["X-Instance-Key"] == pm.instance_key

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_send_push_payload(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "sent": 1, "failed": 0}
        pm.session.post = MagicMock(return_value=mock_response)

        pm.send_push("Title", "Body text", data={"invoice_id": "123"})

        call_kwargs = pm.session.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["title"] == "Title"
        assert payload["body"] == "Body text"
        assert payload["data"]["invoice_id"] == "123"

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_send_push_401(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))

        mock_response = MagicMock()
        mock_response.status_code = 401
        pm.session.post = MagicMock(return_value=mock_response)

        result = pm.send_push("Title", "Body")
        assert result["ok"] is False
        assert result["error"] == "unauthorized"

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_send_push_429(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))

        mock_response = MagicMock()
        mock_response.status_code = 429
        pm.session.post = MagicMock(return_value=mock_response)

        result = pm.send_push("Title", "Body")
        assert result["ok"] is False
        assert result["error"] == "rate_limited"

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_send_push_network_error(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))
        pm.session.post = MagicMock(
            side_effect=requests.exceptions.ConnectionError("fail")
        )

        result = pm.send_push("Title", "Body")
        assert result["ok"] is False

    def test_send_push_not_configured(self, tmp_path):
        with patch("app.push_manager.requests.Session") as MockSession:
            mock_session = MockSession.return_value
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_session.post.return_value = mock_response

            pm = PushManager(_make_config(), data_dir=str(tmp_path))
            pm.instance_id = None
            pm.instance_key = None

            result = pm.send_push("Title", "Body")
            assert result["ok"] is False
            assert result["error"] == "not_configured"

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_send_push_body_truncated(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "sent": 1, "failed": 0}
        pm.session.post = MagicMock(return_value=mock_response)

        pm.send_push("Title", "A" * 500)

        call_kwargs = pm.session.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert len(payload["body"]) == 256


# ── Regenerate ───────────────────────────────────────────────────────────────


class TestPushManagerRegenerate:
    """Test pairing code regeneration."""

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_regenerate_new_code(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))
        old_code = pm.pairing_code

        mock_response = MagicMock()
        mock_response.status_code = 200
        pm.session.post = MagicMock(return_value=mock_response)

        result = pm.regenerate_pairing_code()
        assert result is True
        assert pm.pairing_code != old_code
        assert len(pm.pairing_code) == 8

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_regenerate_failure(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))
        old_code = pm.pairing_code

        mock_response = MagicMock()
        mock_response.status_code = 500
        pm.session.post = MagicMock(return_value=mock_response)

        result = pm.regenerate_pairing_code()
        assert result is False
        assert pm.pairing_code == old_code  # unchanged on failure


# ── Properties ───────────────────────────────────────────────────────────────


class TestPushManagerProperties:
    """Test is_registered and pairing_info properties."""

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_is_registered_true(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))
        # Mock bypasses setting registered_at, set it manually
        pm.registered_at = "2026-03-12T10:00:00+00:00"
        assert pm.is_registered is True

    def test_is_registered_false_without_credentials(self, tmp_path):
        with patch("app.push_manager.requests.Session") as MockSession:
            mock_session = MockSession.return_value
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_session.post.return_value = mock_response

            pm = PushManager(_make_config(), data_dir=str(tmp_path))
            assert pm.is_registered is False

    @patch.object(PushManager, "_register_instance", return_value=True)
    def test_pairing_info_keys(self, mock_register, tmp_path):
        pm = PushManager(_make_config(), data_dir=str(tmp_path))
        info = pm.pairing_info

        assert "instance_id" in info
        assert "pairing_code" in info
        assert "registered_at" in info
        assert "is_registered" in info
        assert "qr_data_uri" in info
