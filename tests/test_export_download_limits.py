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
