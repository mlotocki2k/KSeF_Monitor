"""
An invoice notification that failed on every channel is retried (bounded),
instead of being lost because the invoice row already exists.
"""

import json
from unittest.mock import MagicMock

from app.database import Base, Database, Invoice, NotificationLog
from app.invoice_monitor import InvoiceMonitor
from app.notifiers.notification_manager import NotificationManager


def _setup(mock_config, tmp_path, sample_invoice):
    db = Database(str(tmp_path / "n.db"))
    Base.metadata.create_all(db.engine)
    ksef = MagicMock()
    ksef.environment = "test"
    ksef.nip = "1234567890"
    manager = NotificationManager(mock_config, database=db)
    channel = MagicMock()
    channel.channel_name = "Pushover"
    manager.notifiers = [channel]
    m = InvoiceMonitor(mock_config, ksef, manager, MagicMock(), database=db)
    m.save_xml = m.save_pdf = False
    ksef.get_invoices_metadata.return_value = [sample_invoice]
    return m, db, channel


def test_failed_notification_is_retried_next_cycle(mock_config, tmp_path, sample_invoice):
    m, db, channel = _setup(mock_config, tmp_path, sample_invoice)
    channel.render_and_send.return_value = False     # outage
    m.check_for_new_invoices()
    channel.render_and_send.return_value = True      # channel back
    assert m.retry_failed_notifications() == 1
    with db.get_session() as s:
        sent = s.query(NotificationLog).filter_by(event_type="invoice", status="sent").count()
    assert sent == 1
    assert m.retry_failed_notifications() == 0       # delivered — no more retries


def test_retries_are_bounded(mock_config, tmp_path, sample_invoice):
    m, _db, channel = _setup(mock_config, tmp_path, sample_invoice)
    channel.render_and_send.return_value = False
    m.check_for_new_invoices()
    for _ in range(10):
        m.retry_failed_notifications()
    assert channel.render_and_send.call_count == m.NOTIFY_RETRY_MAX


def test_initial_load_and_unlogged_invoices_not_retried(mock_config, tmp_path, sample_invoice):
    m, db, channel = _setup(mock_config, tmp_path, sample_invoice)
    with db.get_session() as s:
        db.save_invoice(s, {"ksef_number": "HIST", "subject_type": "Subject2", "seller_nip": "1",
                            "source": "initial_load", "raw_metadata": json.dumps(sample_invoice)})
        db.save_invoice(s, {"ksef_number": "OLD", "subject_type": "Subject2", "seller_nip": "1",
                            "raw_metadata": json.dumps(sample_invoice)})
        s.commit()
        hist = s.query(Invoice).filter_by(ksef_number="HIST").one()
        db.log_notification(session=s, event_type="invoice", channel="pushover",
                            status="failed", invoice_id=hist.id)
        s.commit()
    assert m.retry_failed_notifications() == 0
    channel.render_and_send.assert_not_called()
