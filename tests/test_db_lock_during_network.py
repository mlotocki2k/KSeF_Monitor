"""
Network I/O (XML/UPO download with KSeF 429 back-off, PDF rendering) must not
run inside an open SQLite write transaction — otherwise UI logins, initial-load
progress and API writes fail with "database is locked" for the whole cycle.
"""

import json
import sqlite3
import time
from unittest.mock import MagicMock

from app.database import Base, Database, Invoice
from app.invoice_monitor import InvoiceMonitor


def _monitor(mock_config, tmp_path):
    mock_config.config["monitoring"]["subject_types"] = ["Subject2"]
    mock_config.config["storage"]["save_xml"] = True
    mock_config.config["storage"]["save_pdf"] = False
    mock_config.config["storage"]["output_dir"] = str(tmp_path / "inv")
    db_path = tmp_path / "l.db"
    db = Database(str(db_path))
    Base.metadata.create_all(db.engine)
    ksef = MagicMock()
    ksef.environment = "test"
    ksef.nip = "1234567890"
    nm = MagicMock()
    nm.send_invoice_notification.return_value = True
    m = InvoiceMonitor(mock_config, ksef, nm, MagicMock(), database=db)
    return m, db, db_path


def _probe(db_path, results):
    """Try to take the write lock from another connection (no waiting)."""
    def _side_effect(*_a, **_k):
        conn = sqlite3.connect(str(db_path), timeout=0.2)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
            results.append(True)
        except sqlite3.OperationalError:
            results.append(False)
        finally:
            conn.close()
        return None
    return _side_effect


def test_polling_releases_write_lock_before_xml_download(mock_config, tmp_path, sample_invoice):
    m, _db, db_path = _monitor(mock_config, tmp_path)
    m.ksef.get_invoices_metadata.return_value = [sample_invoice]
    results = []
    m.ksef.get_invoice_xml.side_effect = _probe(db_path, results)
    m.check_for_new_invoices()
    assert results == [True]


def test_artifact_drain_releases_write_lock_before_download(mock_config, tmp_path, sample_invoice):
    m, db, db_path = _monitor(mock_config, tmp_path)
    with db.get_session() as s:
        ids = []
        for i in range(2):
            inv = db.save_invoice(s, {"ksef_number": f"K{i}", "subject_type": "Subject2",
                                      "seller_nip": "1", "raw_metadata": json.dumps(sample_invoice)})
            ids.append(inv.id)
        s.commit()
        for i in ids:
            db.create_artifact(s, i, "xml", status="pending")
        s.commit()
    results = []
    m.ksef.get_invoice_xml.side_effect = _probe(db_path, results)
    m.process_pending_artifacts()
    assert results == [True, True]


def test_upo_drain_releases_write_lock_before_download(mock_config, tmp_path):
    m, db, db_path = _monitor(mock_config, tmp_path)
    m.fetch_upo = True
    with db.get_session() as s:
        for i in range(2):
            db.save_invoice(s, {"ksef_number": f"K{i}", "subject_type": "Subject1", "seller_nip": "1"})
        s.commit()
    m._session_invoice_map, m._session_map_ts = {"K0": "S", "K1": "S"}, time.time()
    results = []
    m.ksef.get_invoice_upo.side_effect = _probe(db_path, results)
    m.process_pending_upo()
    assert results == [True, True]
    with db.get_session() as s:
        assert s.query(Invoice).count() == 2
