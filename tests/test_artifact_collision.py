"""
Two invoices whose file names collide (same number and date, different
sellers) must each get their own file — never be linked to the other's PDF/XML.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.database import Database, InvoiceArtifact
from app.invoice_monitor import InvoiceMonitor

KA = "9999999999-20260901-AAAAAA-11"
KB = "5555555555-20260901-BBBBBB-22"


def _meta(ksef, seller):
    return {"ksefNumber": ksef, "invoiceNumber": "FV 1/09/2026", "issueDate": "2026-09-01",
            "seller": {"nip": seller, "name": "x"}, "buyer": {"identifier": {"value": "1111111111"}}}


@pytest.fixture
def env(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.create_tables()
    m = InvoiceMonitor.__new__(InvoiceMonitor)
    m.db = db
    m.output_dir = tmp_path / "inv"
    m.folder_structure = ""
    m.file_exists_strategy = "skip"
    m.file_name_pattern = "{type}_{date}_{invoice_number}"
    s = db.get_session()
    ids = {}
    for k, seller in ((KA, "9999999999"), (KB, "5555555555")):
        inv = db.save_invoice(s, {"ksef_number": k, "invoice_number": "FV 1/09/2026",
                                  "subject_type": "Subject2", "issue_date": "2026-09-01",
                                  "seller_nip": seller, "raw_metadata": json.dumps(_meta(k, seller))})
        s.commit()
        ids[k] = inv.id
    yield m, s, ids
    s.close()


def _artifact(s, invoice_id, kind):
    return s.query(InvoiceArtifact).filter_by(invoice_id=invoice_id, artifact_type=kind).first()


@pytest.mark.parametrize("kind,a,b", [("pdf", b"%PDF A", b"%PDF B"), ("xml", "<A/>", "<B/>")])
def test_cache_path_collision_gets_own_file(env, kind, a, b):
    m, s, ids = env
    m.save_artifact_for_invoice(_meta(KA, "9999999999"), "Subject2", kind, a, ids[KA], s)
    s.commit()
    m.save_artifact_for_invoice(_meta(KB, "5555555555"), "Subject2", kind, b, ids[KB], s)
    s.commit()
    pa, pb = _artifact(s, ids[KA], kind).file_path, _artifact(s, ids[KB], kind).file_path
    assert pa != pb
    expected_b = b if isinstance(b, bytes) else b.encode()
    assert Path(pb).read_bytes() == expected_b


def test_same_invoice_again_reuses_its_file(env):
    m, s, ids = env
    first = m.save_artifact_for_invoice(_meta(KA, "9999999999"), "Subject2", "pdf", b"%PDF A", ids[KA], s)
    s.commit()
    again = m.save_artifact_for_invoice(_meta(KA, "9999999999"), "Subject2", "pdf", b"%PDF A", ids[KA], s)
    assert again == first


def test_monitor_save_path_collision(env):
    m, s, ids = env
    m.save_xml, m.save_pdf = True, False
    m.ksef = MagicMock()
    m.ksef.get_invoice_xml.side_effect = lambda k: {"xml_content": f"<Faktura>{k}</Faktura>"}
    m._save_invoice_artifacts(_meta(KA, "9999999999"), "Subject2", ids[KA], s)
    s.commit()
    m._save_invoice_artifacts(_meta(KB, "5555555555"), "Subject2", ids[KB], s)
    s.commit()
    pb = _artifact(s, ids[KB], "xml").file_path
    assert KB in Path(pb).read_text(encoding="utf-8")


def test_json_mode_xml_collision_detected_by_content(env):
    m, s, ids = env
    m.save_xml, m.save_pdf = True, False
    m.ksef = MagicMock()
    m.ksef.get_invoice_xml.side_effect = lambda k: {"xml_content": f"<Faktura>{k}</Faktura>"}
    m._save_invoice_artifacts(_meta(KA, "9999999999"), "Subject2", None, None)
    m._save_invoice_artifacts(_meta(KB, "5555555555"), "Subject2", None, None)
    files = sorted(p.read_text(encoding="utf-8") for p in m.output_dir.rglob("*.xml"))
    assert any(KA in f for f in files) and any(KB in f for f in files)


def test_filename_sanitizer_strips_control_chars():
    out = InvoiceMonitor._sanitize_filename_value("FV 1\nINFO fake log\r\x00x")
    assert "\n" not in out and "\r" not in out and "\x00" not in out
