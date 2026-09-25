"""
A failed or incomplete KSeF query must never advance last_check — otherwise the
queried window is skipped for good and its invoices are lost.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
import pytz
import requests

from app.database import Base, Database, Invoice, MonitorState
from app.invoice_monitor import InvoiceMonitor
from app.ksef_client import KSeFClient, KSeFQueryError

WARSAW = pytz.timezone("Europe/Warsaw")


# ── KSeFClient.get_invoices_metadata ─────────────────────────────────────────


def _page(invoices, has_more, truncated=False):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "invoices": invoices, "hasMore": has_more, "isTruncated": truncated,
    }
    return resp


def _inv(n, date="2026-09-01T10:00:00+00:00"):
    return {"ksefNumber": f"1234567890-20260901-{n:08X}-00", "invoicingDate": date}


@pytest.fixture
def client(mock_config):
    c = KSeFClient(mock_config)
    c.access_token = "token"
    return c


def _query(client):
    now = datetime.now(timezone.utc)
    return client.get_invoices_metadata(now - timedelta(days=1), now, "Subject1")


def test_network_error_mid_pagination_raises(client):
    client._make_authenticated_request = MagicMock(side_effect=[
        _page([_inv(1)], has_more=True),
        requests.exceptions.ConnectionError("boom"),
    ])
    with pytest.raises(KSeFQueryError):
        _query(client)


def test_http_error_raises(client):
    bad = _page([], has_more=False)
    bad.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
    client._make_authenticated_request = MagicMock(return_value=bad)
    with pytest.raises(KSeFQueryError):
        _query(client)


def test_auth_failure_raises(client):
    # _make_authenticated_request returns the on_failure sentinel on auth failure
    client._make_authenticated_request = MagicMock(
        side_effect=lambda *a, **kw: kw["on_failure"]
    )
    with pytest.raises(KSeFQueryError):
        _query(client)


def test_initial_auth_failure_raises(client):
    client.access_token = None
    client.authenticate = MagicMock(return_value=False)
    with pytest.raises(KSeFQueryError):
        _query(client)


def test_truncation_after_10000_records_is_followed(client):
    size = client.PAGINATION_PAGE_SIZE
    pages = []
    for p in range(10_000 // size):
        last = p == 10_000 // size - 1
        pages.append(_page([_inv(p * size + i) for i in range(size)],
                           has_more=True, truncated=last))
    late = _inv(999_999, date="2026-09-02T10:00:00+00:00")
    pages.append(_page([late], has_more=False))
    client._make_authenticated_request = MagicMock(side_effect=pages)

    result = _query(client)

    assert late in result


# ── InvoiceMonitor state handling ────────────────────────────────────────────


def _monitor(mock_config, tmp_path, subject_types=("Subject1",)):
    mock_config.config["monitoring"]["subject_types"] = list(subject_types)
    db = Database(str(tmp_path / "m.db"))
    Base.metadata.create_all(db.engine)
    ksef = MagicMock()
    ksef.environment = "test"
    ksef.nip = "1234567890"
    nm = MagicMock()
    nm.send_invoice_notification.return_value = True
    m = InvoiceMonitor(mock_config, ksef, nm, MagicMock(), database=db)
    return m, db


def _seed_state(m, db, subject_type, last_check):
    with db.get_session() as s:
        db.update_monitor_state(s, nip=m.nip, subject_type=subject_type,
                                last_check=last_check)
        s.commit()


def _state(db, subject_type):
    with db.get_session() as s:
        return s.query(MonitorState).filter_by(subject_type=subject_type).one()


def test_failed_query_keeps_last_check(mock_config, tmp_path):
    m, db = _monitor(mock_config, tmp_path)
    before = datetime(2026, 9, 20, 8, 0, 0)
    _seed_state(m, db, "Subject1", before)
    m.ksef.get_invoices_metadata.side_effect = KSeFQueryError("KSeF 500")

    with pytest.raises(KSeFQueryError):
        m.check_for_new_invoices()

    st = _state(db, "Subject1")
    assert st.last_check == before
    assert st.consecutive_errors == 1
    assert "KSeF 500" in st.last_error


def test_one_subject_failing_does_not_block_the_other(mock_config, tmp_path, sample_invoice):
    m, db = _monitor(mock_config, tmp_path, subject_types=("Subject1", "Subject2"))
    before = datetime(2026, 9, 20, 8, 0, 0)
    _seed_state(m, db, "Subject1", before)
    _seed_state(m, db, "Subject2", before)

    def fake(date_from, date_to, subject_type):
        if subject_type == "Subject1":
            raise KSeFQueryError("KSeF 500")
        return [sample_invoice]

    m.ksef.get_invoices_metadata.side_effect = fake

    with pytest.raises(KSeFQueryError):
        m.check_for_new_invoices()

    assert _state(db, "Subject1").last_check == before
    assert _state(db, "Subject2").last_check > before
    with db.get_session() as s:
        assert s.query(Invoice).count() == 1


def test_cycle_error_does_not_advance_last_check(mock_config, tmp_path):
    m, db = _monitor(mock_config, tmp_path)
    before = datetime(2026, 9, 20, 8, 0, 0)
    _seed_state(m, db, "Subject1", before)

    m._record_cycle_error(RuntimeError("database is locked"))

    st = _state(db, "Subject1")
    assert st.last_check == before
    assert st.consecutive_errors == 1


def test_json_mode_failed_query_keeps_last_check(mock_config, tmp_path):
    ksef = MagicMock()
    ksef.environment = "test"
    ksef.nip = "1234567890"
    m = InvoiceMonitor(mock_config, ksef, MagicMock(), MagicMock())
    m.state_file = tmp_path / "last_check.json"
    m.state_file.write_text('{"last_check": "2026-09-20T08:00:00+02:00"}', encoding="utf-8")
    ksef.get_invoices_metadata.side_effect = KSeFQueryError("KSeF 500")

    with pytest.raises(KSeFQueryError):
        m.check_for_new_invoices()

    assert m.load_state()["last_check"] == "2026-09-20T08:00:00+02:00"


def test_ambiguous_dst_last_check_resolves_to_earlier_instant(mock_config, tmp_path):
    m, db = _monitor(mock_config, tmp_path)
    # 2026-10-25 02:30 happens twice in Warsaw (CEST 00:30Z, then CET 01:30Z).
    _seed_state(m, db, "Subject1", datetime(2026, 10, 25, 2, 30))
    with db.get_session() as s:
        last = m._get_last_check(s, "Subject1", {})
    assert last.astimezone(timezone.utc) == datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)


# ── Prometheus endpoint labels ───────────────────────────────────────────────


@pytest.mark.parametrize("path,label", [
    ("/v2/invoices/ksef/1234567890-20260901-ABCDEF123456-7F", "/v2/invoices/ksef/{id}"),
    ("/v2/auth/20260925-AU-2A4B6C8D10-1A2B3C4D5E-6F", "/v2/auth/{id}"),
    ("/v2/sessions/20260925-SO-ABC123-00/invoices?pageSize=10", "/v2/sessions/{id}/invoices"),
    ("/v2/invoices/query/metadata", "/v2/invoices/query/metadata"),
    ("/v2/auth/token/refresh", "/v2/auth/token/refresh"),
])
def test_metrics_endpoint_label_bounded(client, path, label):
    assert client._metrics_endpoint(client.base_url + path) == label


def test_metrics_endpoint_label_external_url(client):
    assert client._metrics_endpoint("https://blob.example/x?sig=SECRET") == "external"
