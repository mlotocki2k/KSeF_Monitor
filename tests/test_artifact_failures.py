"""
Artifact problems must not cost invoice rows (re-notification loop), must not
register files that were never written, and must respect pre-0.5.3 file paths.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.database import Base, Database, Invoice, InvoiceArtifact
from app.invoice_monitor import InvoiceMonitor


def _monitor(mock_config, tmp_path):
    mock_config.config["monitoring"]["subject_types"] = ["Subject2"]
    mock_config.config["storage"]["save_xml"] = True
    mock_config.config["storage"]["save_pdf"] = True
    mock_config.config["storage"]["output_dir"] = str(tmp_path / "inv")
    db = Database(str(tmp_path / "m.db"))
    Base.metadata.create_all(db.engine)
    ksef = MagicMock()
    ksef.environment = "test"
    ksef.nip = "1234567890"
    nm = MagicMock()
    nm.send_invoice_notification.return_value = True
    return InvoiceMonitor(mock_config, ksef, nm, MagicMock(), database=db), db, nm


def test_artifact_error_keeps_invoice_and_does_not_renotify(mock_config, tmp_path, sample_invoice):
    m, db, nm = _monitor(mock_config, tmp_path)
    m.ksef.get_invoices_metadata.return_value = [sample_invoice]
    with patch.object(m, "_save_invoice_artifacts", side_effect=PermissionError("EACCES")):
        for _ in range(3):
            m.check_for_new_invoices()
    with db.get_session() as s:
        assert s.query(Invoice).count() == 1
    assert nm.send_invoice_notification.call_count == 1


def test_pdf_not_registered_when_generator_writes_nothing(mock_config, tmp_path, sample_invoice):
    m, db, _nm = _monitor(mock_config, tmp_path)
    m.ksef.get_invoice_xml.return_value = {"xml_content": "<Unknown/>"}
    with db.get_session() as s:
        inv = db.save_invoice(s, {"ksef_number": sample_invoice["ksefNumber"], "subject_type": "Subject2", "seller_nip": "1234567890"})
        s.commit()
        with patch("app.invoice_monitor.generate_invoice_pdf", return_value=None):
            m._save_invoice_artifacts(sample_invoice, "Subject2", inv.id, s)
        s.commit()
        assert s.query(InvoiceArtifact).filter_by(invoice_id=inv.id, artifact_type="pdf").count() == 0
        assert not s.get(Invoice, inv.id).has_pdf


def test_legacy_invoice_path_counts_as_owner(mock_config, tmp_path):
    m, db, _nm = _monitor(mock_config, tmp_path)
    m.file_exists_strategy = "skip"
    meta = lambda k: {"ksefNumber": k, "invoiceNumber": "FV 1", "issueDate": "2026-09-01",  # noqa: E731
                      "seller": {"nip": "1"}, "buyer": {"identifier": {"value": "2"}}}
    with db.get_session() as s:
        a = db.save_invoice(s, {"ksef_number": "A", "subject_type": "Subject2", "seller_nip": "1234567890",
                                "raw_metadata": json.dumps(meta("A"))})
        b = db.save_invoice(s, {"ksef_number": "B", "subject_type": "Subject2", "seller_nip": "1234567890",
                                "raw_metadata": json.dumps(meta("B"))})
        s.commit()
        # pre-0.5.3 row: path only on the invoice, no invoice_artifacts mirror
        target = m._resolve_output_dir(meta("A"), "Subject2")
        target.mkdir(parents=True, exist_ok=True)
        legacy = target / f"{m._build_file_name(meta('A'), 'Subject2')}.pdf"
        legacy.write_bytes(b"%PDF-A")
        s.get(Invoice, a.id).pdf_path = str(legacy)
        s.commit()
        written = m.save_artifact_for_invoice(meta("B"), "Subject2", "pdf", b"%PDF-B", b.id, s)
        assert written != legacy
        assert Path(written).read_bytes() == b"%PDF-B"


def test_null_party_names_are_not_rendered_as_none(mock_config, tmp_path, sample_invoice):
    m, _db, _nm = _monitor(mock_config, tmp_path)
    inv = dict(sample_invoice, seller={"nip": "1", "name": None}, buyer={"name": None})
    ctx = m.build_template_context(inv, "Subject2")
    assert ctx["seller_name"] == "N/A" and ctx["buyer_name"] == "N/A"


def test_invoice_notification_logged_in_cycle_transaction(mock_config, tmp_path, sample_invoice):
    """Codex finding: logging via a 2nd SQLite connection waited on the cycle lock and was dropped."""
    import time as _time
    from app.database import NotificationLog
    from app.notifiers.notification_manager import NotificationManager
    m, db, _nm = _monitor(mock_config, tmp_path)
    m.save_xml = m.save_pdf = False
    manager = NotificationManager(mock_config, database=db)
    channel = MagicMock()
    channel.channel_name = "Webhook"
    channel.render_and_send.return_value = True
    manager.notifiers = [channel]
    m.notifier = manager
    m.ksef.get_invoices_metadata.return_value = [sample_invoice]
    t0 = _time.monotonic()
    m.check_for_new_invoices()
    assert _time.monotonic() - t0 < 3
    with db.get_session() as s:
        logs = s.query(NotificationLog).filter_by(event_type="invoice").all()
        inv = s.query(Invoice).one()
    assert len(logs) == 1 and logs[0].invoice_id == inv.id and logs[0].status == "sent"
