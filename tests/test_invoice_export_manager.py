"""
Tests for InvoiceExportManager.

Uses mocked KSeFClient — no real network calls.
Tests cover: key generation, export creation, polling logic,
decryption flow, metadata parsing, and isTruncated handling.
"""

import base64
import io
import json
import os
import zipfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.invoice_export_manager import (
    ExportResult,
    InvoiceExportManager,
    STATUS_PROCESSING,
    STATUS_SUCCESS,
    STATUS_EXPIRED,
    STATUS_RANGE_ERROR,
    STATUS_UNKNOWN_ERROR,
    STATUS_CANCELLED,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_zip_with_metadata(invoices: list) -> bytes:
    """Build _metadata.json inside a zip (uses 'invoices' key per actual implementation)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("_metadata.json", json.dumps({"invoices": invoices}))
    return buf.getvalue()


def _make_rsa_public_key():
    """Generate a real RSA-2048 public key for encryption tests."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    return private_key.public_key()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_ksef():
    client = MagicMock()
    client.base_url = "https://ksef-test.mf.gov.pl/api"
    client.API_VERSION = "v2"
    client.session_token = "test-session-token"
    return client


@pytest.fixture
def manager(mock_ksef):
    return InvoiceExportManager(mock_ksef)


# ── Unit tests ────────────────────────────────────────────────────────────────

class TestExportResult:
    def test_default_values(self):
        r = ExportResult(success=True)
        assert r.invoices == []
        assert r.is_truncated is False
        assert r.error is None
        assert r.reference_number is None

    def test_failed_result(self):
        r = ExportResult(success=False, error="timeout")
        assert not r.success
        assert r.error == "timeout"


class TestInvoiceExportManagerInit:
    def test_client_attribute(self, mock_ksef):
        mgr = InvoiceExportManager(mock_ksef)
        assert mgr.client is mock_ksef

    def test_constants(self):
        assert InvoiceExportManager.POLL_INTERVAL_BASE == 5
        assert InvoiceExportManager.POLL_MAX_ATTEMPTS == 180
        assert InvoiceExportManager.MAX_RETRY_ON_500 == 3


class TestGenerateExportKeys:
    def test_key_sizes(self, manager):
        manager._sym_key_cert_public_key = _make_rsa_public_key()
        aes_key, iv, enc_key_b64, iv_b64 = manager._generate_export_keys()
        assert len(aes_key) == 32   # AES-256
        assert len(iv) == 16        # CBC IV
        base64.b64decode(enc_key_b64)  # valid base64
        base64.b64decode(iv_b64)

    def test_key_randomness(self, manager):
        manager._sym_key_cert_public_key = _make_rsa_public_key()
        aes1, iv1, _, _ = manager._generate_export_keys()
        aes2, iv2, _, _ = manager._generate_export_keys()
        assert aes1 != aes2
        assert iv1 != iv2

    def test_calls_fetch_cert_when_not_cached(self, manager):
        """_generate_export_keys calls _fetch_sym_key_cert if cache is None."""
        assert manager._sym_key_cert_public_key is None

        def fake_fetch():
            manager._sym_key_cert_public_key = _make_rsa_public_key()

        with patch.object(manager, "_fetch_sym_key_cert", side_effect=fake_fetch) as mock_fetch:
            manager._generate_export_keys()
            mock_fetch.assert_called_once()


class TestParseMetadataZip:
    def test_parses_invoice_list(self, manager):
        invoices = [
            {"ksefReferenceNumber": "REF-001", "grossValue": "1230.00"},
            {"ksefReferenceNumber": "REF-002", "grossValue": "500.00"},
        ]
        zip_bytes = _make_zip_with_metadata(invoices)
        result = manager._parse_metadata_zip(zip_bytes)
        assert len(result) == 2
        assert result[0]["ksefReferenceNumber"] == "REF-001"

    def test_empty_invoice_list(self, manager):
        zip_bytes = _make_zip_with_metadata([])
        result = manager._parse_metadata_zip(zip_bytes)
        assert result == []

    def test_flat_list_format(self, manager):
        """_metadata.json can also be a plain list."""
        invoices = [{"ksefReferenceNumber": "REF-003"}]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("_metadata.json", json.dumps(invoices))
        result = manager._parse_metadata_zip(buf.getvalue())
        assert len(result) == 1

    def test_missing_metadata_file_returns_empty(self, manager):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("other.json", '{"foo": "bar"}')
        result = manager._parse_metadata_zip(buf.getvalue())
        assert result == []


class TestDecryptAesCbc:
    def test_roundtrip(self, manager):
        from cryptography.hazmat.primitives.padding import PKCS7
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        key = os.urandom(32)
        iv = os.urandom(16)
        plaintext = b'{"test": "invoice data", "more": "content"}'

        padder = PKCS7(128).padder()
        padded = padder.update(plaintext) + padder.finalize()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        enc = cipher.encryptor()
        ciphertext = enc.update(padded) + enc.finalize()

        result = manager._decrypt_aes_cbc(ciphertext, key, iv)
        assert result == plaintext

    def test_wrong_key_raises(self, manager):
        from cryptography.hazmat.primitives.padding import PKCS7
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        key = os.urandom(32)
        iv = os.urandom(16)
        plaintext = b"hello world padding test data xx"

        padder = PKCS7(128).padder()
        padded = padder.update(plaintext) + padder.finalize()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        enc = cipher.encryptor()
        ciphertext = enc.update(padded) + enc.finalize()

        with pytest.raises(Exception):
            manager._decrypt_aes_cbc(ciphertext, os.urandom(32), iv)


class TestRunExport:
    def test_returns_failure_when_key_generation_fails(self, manager):
        with patch.object(manager, "_fetch_sym_key_cert", side_effect=RuntimeError("no cert")):
            result = manager.run_export(
                subject_type="Subject1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 3, 31),
            )
        assert not result.success
        assert "no cert" in (result.error or "")

    def test_returns_failure_when_create_export_returns_none(self, manager):
        manager._sym_key_cert_public_key = _make_rsa_public_key()
        with patch.object(manager, "_create_export", return_value=None):
            result = manager.run_export(
                subject_type="Subject1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 3, 31),
            )
        assert not result.success
        assert "Failed to create export job" in (result.error or "")

    def test_returns_failure_when_poll_returns_none(self, manager):
        manager._sym_key_cert_public_key = _make_rsa_public_key()
        with patch.object(manager, "_create_export", return_value="REF-123"), \
             patch.object(manager, "_poll_export_status", return_value=None):
            result = manager.run_export(
                subject_type="Subject1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 3, 31),
            )
        assert not result.success
        assert "polling failed" in (result.error or "")

    def test_returns_failure_on_terminal_export_status(self, manager):
        manager._sym_key_cert_public_key = _make_rsa_public_key()
        # Status dict uses nested structure: {"status": {"code": ...}, "package": {...}}
        expired_response = {"status": {"code": STATUS_EXPIRED, "description": "expired"}}
        with patch.object(manager, "_create_export", return_value="REF-123"), \
             patch.object(manager, "_poll_export_status", return_value=expired_response):
            result = manager.run_export(
                subject_type="Subject1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 3, 31),
            )
        assert not result.success

    def test_successful_export_with_invoices(self, manager):
        invoices = [{"ksefReferenceNumber": "REF-001"}]
        # Correct response structure from _poll_export_status
        success_response = {
            "status": {"code": STATUS_SUCCESS, "description": "success"},
            "package": {"invoiceCount": 1, "parts": []},
        }
        with patch.object(manager, "_create_export", return_value="REF-123"), \
             patch.object(manager, "_poll_export_status", return_value=success_response), \
             patch.object(manager, "_download_and_decrypt", return_value=invoices):
            manager._sym_key_cert_public_key = _make_rsa_public_key()
            result = manager.run_export(
                subject_type="Subject1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 3, 31),
            )

        assert result.success
        assert len(result.invoices) == 1
        assert result.reference_number == "REF-123"

    def test_is_truncated_captured(self, manager):
        invoices = [{"ksefReferenceNumber": "REF-001"}]
        success_response = {
            "status": {"code": STATUS_SUCCESS, "description": "success"},
            "package": {
                "invoiceCount": 1,
                "parts": [],
                "isTruncated": True,
                "lastInvoicingDate": "2024-02-15T12:00:00",
            },
        }
        with patch.object(manager, "_create_export", return_value="REF-123"), \
             patch.object(manager, "_poll_export_status", return_value=success_response), \
             patch.object(manager, "_download_and_decrypt", return_value=invoices):
            manager._sym_key_cert_public_key = _make_rsa_public_key()
            result = manager.run_export(
                subject_type="Subject1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 3, 31),
            )

        assert result.is_truncated is True
        assert result.last_invoicing_date == "2024-02-15T12:00:00"

    def test_fmt_dt_no_timezone(self):
        dt = datetime(2024, 3, 15, 10, 30, 45)
        result = InvoiceExportManager._fmt_dt(dt)
        assert result.endswith("Z")
        assert "2024-03-15" in result
