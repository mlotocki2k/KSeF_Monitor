"""UPO: exhausted retries do not starve others, stale session map is refreshed,
session listings follow continuationToken."""

import time
from unittest.mock import MagicMock

from app.database import Base, Database, Invoice, InvoiceArtifact
from app.invoice_monitor import InvoiceMonitor
from app.ksef_client import KSeFClient


def _monitor(mock_config, tmp_path):
    db = Database(str(tmp_path / "u.db"))
    Base.metadata.create_all(db.engine)
    ksef = MagicMock()
    ksef.environment = "test"
    ksef.nip = "1234567890"
    m = InvoiceMonitor(mock_config, ksef, MagicMock(), MagicMock(), database=db)
    m.fetch_upo = True
    m.output_dir = tmp_path / "out"
    return m, db


def _invoices(db, n):
    ids = []
    with db.get_session() as s:
        for i in range(n):
            inv = db.save_invoice(s, {"ksef_number": f"K{i}", "subject_type": "Subject1",
                                      "seller_nip": "1234567890"})
            ids.append(inv.id)
        s.commit()
    return ids


def test_exhausted_upo_does_not_starve_later_invoices(mock_config, tmp_path):
    m, db = _monitor(mock_config, tmp_path)
    ids = _invoices(db, 2)
    with db.get_session() as s:
        db.create_artifact(s, ids[0], "upo", status="failed")
        s.query(InvoiceArtifact).filter_by(invoice_id=ids[0]).one().download_attempts = 3
        s.commit()
    m._session_invoice_map, m._session_map_ts = {"K1": "SESS"}, time.time()
    m.ksef.get_invoice_upo.return_value = {"upo_xml": "<UPO/>", "sha256_hash": "x"}
    assert m.process_pending_upo(limit=1) == 1
    m.ksef.get_invoice_upo.assert_called_once_with("SESS", "K1")


def test_stale_cached_map_refreshed_before_counting_a_miss(mock_config, tmp_path):
    m, db = _monitor(mock_config, tmp_path)
    _invoices(db, 1)
    m._session_invoice_map, m._session_map_ts = {}, time.time()  # fresh by TTL, lacks K0
    m.ksef.list_sessions.return_value = [{"referenceNumber": "SESS"}]
    m.ksef.get_session_invoices.return_value = [{"ksefNumber": "K0"}]
    m.ksef.get_invoice_upo.return_value = {"upo_xml": "<UPO/>", "sha256_hash": "x"}
    assert m.process_pending_upo() == 1
    m.ksef.list_sessions.assert_called_once()


def test_session_listings_follow_continuation_token(mock_config):
    c = KSeFClient(mock_config)
    c.access_token = "t"

    def page(items, token):
        r = MagicMock()
        r.raise_for_status.return_value = None
        r.json.return_value = {"sessions": items, "continuationToken": token}
        return r

    c._make_authenticated_request = MagicMock(side_effect=[page([{"referenceNumber": "A"}], "tok"),
                                                           page([{"referenceNumber": "B"}], None)])
    assert [s["referenceNumber"] for s in c.list_sessions()] == ["A", "B"]
    second = c._make_authenticated_request.call_args_list[1]
    assert second.kwargs["headers"] == {"x-continuation-token": "tok"}
