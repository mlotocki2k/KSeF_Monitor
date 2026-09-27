"""
Final independent review (codex): an unsaved invoice must not be notified,
the write lock must not span the next subject's KSeF query, a failed push
migration must keep the JSON store, JSON dedup must not forget delivered
invoices after 1000 entries.
"""

import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from app.database import Base, Database, Invoice
from app.invoice_monitor import InvoiceMonitor
from app.push_manager import PushManager
from tests.test_push_manager import _make_config


def _db_monitor(mock_config, tmp_path, subjects):
    mock_config.config["monitoring"]["subject_types"] = subjects
    db_path = tmp_path / "c.db"
    db = Database(str(db_path))
    Base.metadata.create_all(db.engine)
    ksef = MagicMock()
    ksef.environment = "test"
    ksef.nip = "1234567890"
    nm = MagicMock()
    nm.send_invoice_notification.return_value = True
    m = InvoiceMonitor(mock_config, ksef, nm, MagicMock(), database=db)
    m.save_xml = m.save_pdf = False
    return m, db, db_path, nm


def test_failed_invoice_insert_is_not_notified(mock_config, tmp_path, sample_invoice):
    m, db, _p, nm = _db_monitor(mock_config, tmp_path, ["Subject2"])
    m.ksef.get_invoices_metadata.return_value = [sample_invoice]
    with patch.object(db, "save_invoice", side_effect=OperationalError("INSERT", {}, Exception("database is locked"))):
        with pytest.raises(OperationalError):
            m.check_for_new_invoices()
    nm.send_invoice_notification.assert_not_called()
    # next cycle (lock gone) notifies exactly once
    m.check_for_new_invoices()
    assert nm.send_invoice_notification.call_count == 1
    with db.get_session() as s:
        assert s.query(Invoice).count() == 1


def test_write_lock_released_before_next_subject_query(mock_config, tmp_path):
    m, _db, db_path, _nm = _db_monitor(mock_config, tmp_path, ["Subject1", "Subject2"])
    results = []

    def fake(date_from, date_to, subject_type):
        if subject_type == "Subject2":
            conn = sqlite3.connect(str(db_path), timeout=0.2)
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.rollback()
                results.append(True)
            except sqlite3.OperationalError:
                results.append(False)
            finally:
                conn.close()
        return []

    m.ksef.get_invoices_metadata.side_effect = fake
    m.check_for_new_invoices()
    assert results == [True]


@patch.object(PushManager, "_register_instance", return_value=True)
def test_failed_db_migration_keeps_json_store(_reg, tmp_path):
    pm_json = PushManager(_make_config(), data_dir=str(tmp_path))
    saved_id = pm_json.instance_id
    # an already registered instance (no re-registration → no second save)
    cfg_path = tmp_path / "push_config.json"
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    data["registered_at"] = "2026-01-01T00:00:00+00:00"
    cfg_path.write_text(json.dumps(data), encoding="utf-8")
    db = Database(str(tmp_path / "p.db"))
    db.create_tables()
    with patch.object(db, "save_push_instance", side_effect=OperationalError("INSERT", {}, Exception("locked"))):
        PushManager(_make_config(), data_dir=str(tmp_path), db=db)
    assert (tmp_path / "push_config.json").exists()
    # next start (DB healthy) keeps the same credentials
    pm = PushManager(_make_config(), data_dir=str(tmp_path), db=db)
    assert pm.instance_id == saved_id


@patch.object(PushManager, "_register_instance", return_value=True)
def test_regenerated_code_survives_failed_db_save(_reg, tmp_path):
    db = Database(str(tmp_path / "p.db"))
    db.create_tables()
    pm = PushManager(_make_config(), data_dir=str(tmp_path), db=db)
    resp = MagicMock(status_code=200)
    pm.session.post = MagicMock(return_value=resp)
    with patch.object(db, "save_push_instance", side_effect=OperationalError("UPDATE", {}, Exception("locked"))):
        assert pm.regenerate_pairing_code() is True
    new_code = pm.pairing_code
    pm2 = PushManager(_make_config(), data_dir=str(tmp_path), db=db)
    assert pm2.pairing_code == new_code
    # adopted into the DB, fallback file retired
    assert not (tmp_path / "push_config.json").exists()
    pm3 = PushManager(_make_config(), data_dir=str(tmp_path), db=db)
    assert pm3.pairing_code == new_code


@patch.object(PushManager, "_register_instance", return_value=True)
def test_corrupt_fallback_json_does_not_replace_db_credentials(_reg, tmp_path):
    db = Database(str(tmp_path / "p.db"))
    db.create_tables()
    pm = PushManager(_make_config(), data_dir=str(tmp_path), db=db)
    (tmp_path / "push_config.json").write_text("{broken", encoding="utf-8")
    pm2 = PushManager(_make_config(), data_dir=str(tmp_path), db=db)
    assert pm2.instance_id == pm.instance_id and pm2.instance_key == pm.instance_key


@pytest.mark.parametrize("content", [
    # stale fallback (older than the DB row)
    json.dumps({"instance_id": "OLD", "instance_key": "K", "pairing_code": "P",
                "saved_at": "2020-01-01T00:00:00+00:00"}),
    # legacy file without saved_at
    json.dumps({"instance_id": "OLD", "instance_key": "K", "pairing_code": "P"}),
    # incomplete: no pairing code
    json.dumps({"instance_id": "OLD", "instance_key": "K", "saved_at": "2099-01-01T00:00:00+00:00"}),
], ids=["stale", "legacy", "no-pairing-code"])
@patch.object(PushManager, "_register_instance", return_value=True)
def test_untrusted_json_never_replaces_db_credentials(_reg, tmp_path, content):
    db = Database(str(tmp_path / "p.db"))
    db.create_tables()
    pm = PushManager(_make_config(), data_dir=str(tmp_path), db=db)
    (tmp_path / "push_config.json").write_text(content, encoding="utf-8")
    pm2 = PushManager(_make_config(), data_dir=str(tmp_path), db=db)
    assert (pm2.instance_id, pm2.pairing_code) == (pm.instance_id, pm.pairing_code)


@patch.object(PushManager, "_register_instance", return_value=True)
def test_invalid_utf8_json_keeps_db_credentials(_reg, tmp_path):
    db = Database(str(tmp_path / "p.db"))
    db.create_tables()
    pm = PushManager(_make_config(), data_dir=str(tmp_path), db=db)
    (tmp_path / "push_config.json").write_bytes(b"\xff\xfe{")
    pm2 = PushManager(_make_config(), data_dir=str(tmp_path), db=db)
    assert pm2.instance_id == pm.instance_id


@patch.object(PushManager, "_register_instance", return_value=True)
def test_unreadable_json_store_is_not_replaced(_reg, tmp_path):
    from app.push_manager import PushStorageUnavailable
    PushManager(_make_config(), data_dir=str(tmp_path))
    path = tmp_path / "push_config.json"
    before = path.read_text(encoding="utf-8")
    real_open = open

    def _open(file, *a, **k):
        if str(file) == str(path) and "r" in (a[0] if a else k.get("mode", "r")):
            raise PermissionError(13, "Permission denied")
        return real_open(file, *a, **k)

    with patch("builtins.open", _open), pytest.raises(PushStorageUnavailable):
        PushManager(_make_config(), data_dir=str(tmp_path))
    assert path.read_text(encoding="utf-8") == before


@patch.object(PushManager, "_register_instance", return_value=True)
def test_failed_json_write_keeps_previous_file(_reg, tmp_path):
    pm = PushManager(_make_config(), data_dir=str(tmp_path))
    path = tmp_path / "push_config.json"
    before = path.read_text(encoding="utf-8")
    pm.pairing_code = "NEWCODE"
    with patch("app.push_manager.json.dump", side_effect=OSError(28, "No space left on device")):
        pm._save_to_json()
    assert path.read_text(encoding="utf-8") == before
    assert not list(tmp_path.glob("*.tmp"))


def test_json_dedup_keeps_more_than_1000_entries(mock_config, tmp_path, sample_invoice):
    mock_config.config["monitoring"]["subject_types"] = ["Subject2"]
    ksef = MagicMock()
    ksef.environment = "test"
    ksef.nip = "1234567890"
    nm = MagicMock()
    nm.send_invoice_notification.return_value = True
    m = InvoiceMonitor(mock_config, ksef, nm, MagicMock())
    m.save_xml = m.save_pdf = False
    m.state_file = tmp_path / "last_check.json"
    invoices = [dict(sample_invoice, ksefNumber=f"K{i}", ksefReferenceNumber=f"R{i}") for i in range(1001)]
    ksef.get_invoices_metadata.return_value = invoices
    m.check_for_new_invoices()
    assert nm.send_invoice_notification.call_count == 1001
    m.check_for_new_invoices()
    assert nm.send_invoice_notification.call_count == 1001
    assert len(json.loads(m.state_file.read_text(encoding="utf-8"))["seen_invoices"]) == 1001
