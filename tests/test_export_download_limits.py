"""Export part download: https only, hash required, size capped, no zip bomb."""

import base64
import hashlib
import io
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from app.invoice_export_manager import InvoiceExportManager


@pytest.fixture
def mgr():
    return InvoiceExportManager(MagicMock())


def _b64(data):
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


def _resp(data):
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.iter_content.return_value = [data[i:i + 4] for i in range(0, len(data), 4)]
    return r


def _part(data, **kw):
    p = {"url": "https://blob.example/p1?sig=x", "partName": "p1",
         "encryptedPartHash": _b64(data), "encryptedPartSize": len(data)}
    p.update(kw)
    return p


def test_valid_part_downloaded(mgr):
    data = b"0123456789abcdef"
    with patch("app.invoice_export_manager.requests.get", return_value=_resp(data)) as get:
        assert mgr._download_part(_part(data)) == data
    assert get.call_args.kwargs["allow_redirects"] is False


def test_missing_hash_rejected(mgr):
    data = b"abc"
    with patch("app.invoice_export_manager.requests.get", return_value=_resp(data)):
        with pytest.raises(ValueError, match="encryptedPartHash"):
            mgr._download_part(_part(data, encryptedPartHash=""))


def test_http_url_rejected(mgr):
    data = b"abc"
    with pytest.raises(ValueError, match="https"):
        mgr._download_part(_part(data, url="http://blob.example/p1"))


def test_oversized_part_rejected(mgr):
    data = b"x" * 64
    with patch("app.invoice_export_manager.requests.get", return_value=_resp(data)):
        with pytest.raises(ValueError, match="exceeds"):
            mgr._download_part(_part(data, encryptedPartSize=16))


def test_zip_bomb_metadata_rejected(mgr, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("_metadata.json", b"[" + b" " * 5000 + b"]")
    monkeypatch.setattr(InvoiceExportManager, "MAX_METADATA_BYTES", 1000)
    with pytest.raises(ValueError, match="exceeds"):
        mgr._parse_metadata_zip(buf.getvalue())


def test_multipart_package_parts_decrypted_separately(tmp_path):
    """ksef-docs: each part is encrypted separately; decrypt each, then join."""
    import io, json, zipfile
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("_metadata.json", json.dumps({"invoices": [{"ksefNumber": "K1"}, {"ksefNumber": "K2"}]}) + " " * 4000)
    zip_bytes = buf.getvalue()
    key, iv = bytes(range(32)), bytes(16)

    def enc(chunk):
        p = PKCS7(128).padder()
        e = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        return e.update(p.update(chunk) + p.finalize()) + e.finalize()

    half = len(zip_bytes) // 2
    plain = [zip_bytes[:half], zip_bytes[half:]]
    cipher = [enc(c) for c in plain]
    parts = [{"ordinalNumber": i + 1, "partName": f"p{i}", "url": f"https://blob/p{i}",
              "encryptedPartHash": _b64(cipher[i]), "encryptedPartSize": len(cipher[i]),
              "partHash": _b64(plain[i])} for i in range(2)]
    mgr = InvoiceExportManager(MagicMock())
    responses = iter(_resp(c) for c in cipher)
    with patch("app.invoice_export_manager.requests.get", side_effect=lambda *a, **k: next(responses)):
        invoices = mgr._download_and_decrypt({"parts": parts}, key, iv)
    assert [i["ksefNumber"] for i in invoices] == ["K1", "K2"]
