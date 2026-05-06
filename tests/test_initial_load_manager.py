"""
Tests for InitialLoadManager.

Uses in-memory SQLite + mocked InvoiceExportManager — no real network calls.
Tests cover: job creation, window splitting, resume, cancellation,
isTruncated cursor advancement, and DB persistence.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, Database, InitialLoadJob
from app.initial_load_manager import InitialLoadManager, MAX_WINDOW_DAYS, _count_windows
from app.invoice_export_manager import ExportResult


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    """In-memory SQLite with all tables."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    class InMemoryDB(Database):
        def __init__(self):
            self.engine = engine
            self.SessionLocal = SessionLocal

    return InMemoryDB()


@pytest.fixture
def mock_config():
    cfg = MagicMock()
    cfg.get.return_value = None
    return cfg


@pytest.fixture
def mock_ksef():
    return MagicMock()


@pytest.fixture
def manager(mock_config, mock_ksef, db):
    return InitialLoadManager(mock_config, mock_ksef, db)


# ── Unit tests: helpers ───────────────────────────────────────────────────────

class TestCountWindows:
    def test_single_window(self):
        start = datetime(2024, 1, 1)
        end = datetime(2024, 2, 1)
        assert _count_windows(start, end, ["Subject1"]) == 1

    def test_multiple_windows(self):
        start = datetime(2024, 1, 1)
        end = datetime(2024, 12, 31)
        count = _count_windows(start, end, ["Subject1"])
        # ceil(365/90) = 5
        assert count == 5

    def test_two_subject_types_doubles(self):
        start = datetime(2024, 1, 1)
        end = datetime(2024, 2, 1)
        assert _count_windows(start, end, ["Subject1", "Subject2"]) == 2

    def test_max_one_window_span(self):
        # end - start = 88 days → effective_end = start + 89d → fits one
        # window (89-day span). 89 calendar days inclusive.
        start = datetime(2024, 1, 1)
        end = start + timedelta(days=88)
        assert _count_windows(start, end, ["Subject1"]) == 1

    def test_one_day_past_window_span_splits(self):
        # end - start = 89 days (90 calendar days inclusive). Effective
        # range overflows the 89-day span → 2 windows; the boundary day
        # gets captured by the second window's `from`.
        start = datetime(2024, 1, 1)
        end = start + timedelta(days=89)
        assert _count_windows(start, end, ["Subject1"]) == 2

    def test_same_day_range_is_one_window(self):
        # User picking start = end means "import this single day". Effective
        # range is 1 day → still 1 window.
        start = datetime(2024, 1, 1)
        assert _count_windows(start, start, ["Subject1"]) == 1


class TestInitialLoadWindowLog:
    """Phase 8: per-window log surfaces success/failure to the GUI."""

    def test_record_and_list_window(self, db):
        session = db.get_session()
        try:
            job = db.create_initial_load_job(
                session, ["Subject1"],
                datetime(2024, 1, 1), datetime(2024, 4, 1),
            )
            session.commit()
            db.record_initial_load_window(
                session,
                job_id=job.id,
                subject_type="Subject1",
                window_start=datetime(2024, 1, 1),
                window_end=datetime(2024, 3, 30),
                status="success",
                imported=12,
                skipped=3,
                duration_ms=4321,
            )
            db.record_initial_load_window(
                session,
                job_id=job.id,
                subject_type="Subject1",
                window_start=datetime(2024, 3, 31),
                window_end=datetime(2024, 4, 1),
                status="failed",
                error_message="KSeF 21405: dateRange must not …",
                duration_ms=120,
            )
            session.commit()
            rows = db.list_initial_load_windows(session, job.id)
            assert len(rows) == 2
            assert rows[0].status == "success"
            assert rows[0].imported == 12
            assert rows[1].status == "failed"
            assert "21405" in rows[1].error_message
            assert rows[1].duration_ms == 120
        finally:
            session.close()

    def test_error_message_truncated_to_1000(self, db):
        session = db.get_session()
        try:
            job = db.create_initial_load_job(
                session, ["Subject1"],
                datetime(2024, 1, 1), datetime(2024, 1, 31),
            )
            session.commit()
            db.record_initial_load_window(
                session,
                job_id=job.id,
                subject_type="Subject1",
                window_start=datetime(2024, 1, 1),
                window_end=datetime(2024, 1, 31),
                status="failed",
                error_message="x" * 5000,
            )
            session.commit()
            rows = db.list_initial_load_windows(session, job.id)
            assert len(rows[0].error_message) == 1000
        finally:
            session.close()


# ── Unit tests: DB CRUD ───────────────────────────────────────────────────────

class TestInitialLoadJobCRUD:
    def test_create_job_defaults(self, db):
        session = db.get_session()
        job = db.create_initial_load_job(
            session,
            subject_types=["Subject1"],
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 3, 31),
            windows_total=2,
        )
        session.commit()
        assert job.id is not None
        assert job.status == "pending"
        assert json.loads(job.subject_types) == ["Subject1"]
        assert job.windows_total == 2
        assert job.windows_completed == 0
        assert job.invoices_imported == 0
        session.close()

    def test_get_active_job(self, db):
        session = db.get_session()
        db.create_initial_load_job(session, ["Subject1"],
                                    datetime(2024, 1, 1), datetime(2024, 3, 31))
        session.commit()
        active = db.get_active_initial_load_job(session)
        assert active is not None
        assert active.status == "pending"
        session.close()

    def test_no_active_job_when_completed(self, db):
        session = db.get_session()
        job = db.create_initial_load_job(session, ["Subject1"],
                                          datetime(2024, 1, 1), datetime(2024, 3, 31))
        job.status = "completed"
        session.commit()
        active = db.get_active_initial_load_job(session)
        assert active is None
        session.close()

    def test_no_active_job_when_cancelled(self, db):
        session = db.get_session()
        job = db.create_initial_load_job(session, ["Subject1"],
                                          datetime(2024, 1, 1), datetime(2024, 3, 31))
        job.status = "cancelled"
        session.commit()
        active = db.get_active_initial_load_job(session)
        assert active is None
        session.close()

    def test_update_progress_status(self, db):
        session = db.get_session()
        job = db.create_initial_load_job(session, ["Subject1"],
                                          datetime(2024, 1, 1), datetime(2024, 3, 31),
                                          windows_total=3)
        session.commit()
        db.update_initial_load_progress(session, job.id,
                                         status="running",
                                         windows_completed_delta=1,
                                         invoices_imported_delta=5,
                                         invoices_skipped_delta=2)
        session.commit()
        updated = db.get_initial_load_job(session, job.id)
        assert updated.status == "running"
        assert updated.windows_completed == 1
        assert updated.invoices_imported == 5
        assert updated.invoices_skipped == 2
        session.close()

    def test_update_progress_accumulates(self, db):
        session = db.get_session()
        job = db.create_initial_load_job(session, ["Subject1"],
                                          datetime(2024, 1, 1), datetime(2024, 6, 30),
                                          windows_total=3)
        session.commit()
        db.update_initial_load_progress(session, job.id, invoices_imported_delta=10)
        db.update_initial_load_progress(session, job.id, invoices_imported_delta=5)
        session.commit()
        job = db.get_initial_load_job(session, job.id)
        assert job.invoices_imported == 15
        session.close()

    def test_cancel_pending_job(self, db):
        session = db.get_session()
        job = db.create_initial_load_job(session, ["Subject1"],
                                          datetime(2024, 1, 1), datetime(2024, 3, 31))
        session.commit()
        cancelled = db.cancel_initial_load_job(session, job.id)
        session.commit()
        assert cancelled is not None
        assert cancelled.status == "cancelled"
        session.close()

    def test_cancel_completed_job_returns_none(self, db):
        session = db.get_session()
        job = db.create_initial_load_job(session, ["Subject1"],
                                          datetime(2024, 1, 1), datetime(2024, 3, 31))
        job.status = "completed"
        session.commit()
        result = db.cancel_initial_load_job(session, job.id)
        assert result is None
        session.close()

    def test_get_latest_job_returns_most_recent(self, db):
        session = db.get_session()
        db.create_initial_load_job(session, ["Subject1"],
                                    datetime(2023, 1, 1), datetime(2023, 6, 1))
        session.commit()
        j2 = db.create_initial_load_job(session, ["Subject2"],
                                         datetime(2024, 1, 1), datetime(2024, 6, 1))
        session.commit()
        latest = db.get_latest_initial_load_job(session)
        assert latest.id == j2.id
        session.close()

    def test_update_nonexistent_job_returns_none(self, db):
        session = db.get_session()
        result = db.update_initial_load_progress(session, "nonexistent-id", status="running")
        assert result is None
        session.close()


# ── Unit tests: manager ───────────────────────────────────────────────────────

class TestInitialLoadManagerStartJob:
    def test_start_job_creates_db_record(self, manager, db):
        with patch.object(manager.export_manager, "run_export",
                          return_value=ExportResult(success=True, invoices=[])):
            job_id = manager.start_job(
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 2, 1),
                subject_types=["Subject1"],
            )

        assert job_id is not None

        # Allow background thread to complete
        import time
        time.sleep(0.5)

        status = manager.get_status(job_id)
        assert status is not None
        assert status["id"] == job_id

    def test_start_job_prevents_duplicate_when_pending_exists(self, manager, db):
        session = db.get_session()
        db.create_initial_load_job(session, ["Subject1"],
                                    datetime(2024, 1, 1), datetime(2024, 2, 1))
        session.commit()
        session.close()

        result = manager.start_job(
            start_date=datetime(2024, 3, 1),
            end_date=datetime(2024, 4, 1),
            subject_types=["Subject1"],
        )
        assert result is None

    def test_get_status_returns_none_when_no_job(self, manager):
        assert manager.get_status() is None

    def test_get_status_with_unknown_id_returns_none(self, manager):
        assert manager.get_status("nonexistent-id") is None


class TestJobToDict:
    def test_progress_pct_50(self, db):
        session = db.get_session()
        job = db.create_initial_load_job(session, ["Subject1"],
                                          datetime(2024, 1, 1), datetime(2024, 3, 31),
                                          windows_total=4)
        db.update_initial_load_progress(session, job.id,
                                         status="running",
                                         windows_completed_delta=2)
        session.commit()
        updated = db.get_initial_load_job(session, job.id)
        d = InitialLoadManager._job_to_dict(updated)
        assert d["progress_pct"] == 50.0
        assert d["windows_completed"] == 2
        assert d["windows_total"] == 4
        session.close()

    def test_zero_windows_total_no_division_error(self, db):
        session = db.get_session()
        job = db.create_initial_load_job(session, ["Subject1"],
                                          datetime(2024, 1, 1), datetime(2024, 1, 2),
                                          windows_total=0)
        session.commit()
        d = InitialLoadManager._job_to_dict(job)
        assert d["progress_pct"] == 0
        session.close()

    def test_subject_types_deserialized(self, db):
        session = db.get_session()
        job = db.create_initial_load_job(session, ["Subject1", "Subject2"],
                                          datetime(2024, 1, 1), datetime(2024, 3, 31))
        session.commit()
        d = InitialLoadManager._job_to_dict(job)
        assert d["subject_types"] == ["Subject1", "Subject2"]
        session.close()


class TestMapExportInvoice:
    def test_maps_basic_fields(self, manager):
        inv = {
            "ksefReferenceNumber": "REF-001",
            "invoiceReferenceNumber": "FV/2024/001",
            "invoicingDate": "2024-03-01T10:00:00Z",
            "grossValue": "1230.00",
            "netValue": "1000.00",
            "vatValue": "230.00",
            "currency": "PLN",
        }
        mapped = manager._map_export_invoice(inv, "Subject1")
        assert mapped["ksef_number"] == "REF-001"
        assert mapped["invoice_number"] == "FV/2024/001"
        assert mapped["subject_type"] == "Subject1"
        assert mapped["gross_amount"] == 1230.0
        assert mapped["source"] == "initial_load"

    def test_handles_missing_optional_fields(self, manager):
        inv = {"ksefReferenceNumber": "REF-002"}
        mapped = manager._map_export_invoice(inv, "Subject2")
        assert mapped["ksef_number"] == "REF-002"
        assert mapped["gross_amount"] is None
        assert mapped["seller_nip"] == ""
        assert mapped["source"] == "initial_load"

    def test_parse_amount_valid_string(self):
        assert InitialLoadManager._parse_amount("1230.00") == 1230.0

    def test_parse_amount_integer(self):
        assert InitialLoadManager._parse_amount(500) == 500.0

    def test_parse_amount_none(self):
        assert InitialLoadManager._parse_amount(None) is None

    def test_parse_amount_invalid_string(self):
        assert InitialLoadManager._parse_amount("invalid") is None


class TestIsTruncatedHandling:
    """Cursor advancement when export result is isTruncated=True."""

    def test_truncated_advances_cursor_to_last_invoicing_date(self, manager, db):
        # Create a real job in DB so update_initial_load_progress doesn't fail
        session = db.get_session()
        job = db.create_initial_load_job(session, ["Subject1"],
                                          datetime(2024, 1, 1), datetime(2024, 4, 1),
                                          windows_total=10)
        job.status = "running"
        session.commit()
        job_id = job.id
        session.close()

        call_count = {"n": 0}
        dates_used = []

        def fake_run_export(subject_type, date_from, date_to, **kwargs):
            call_count["n"] += 1
            dates_used.append((date_from, date_to))

            if call_count["n"] == 1:
                return ExportResult(
                    success=True,
                    invoices=[{"ksefReferenceNumber": "REF-001"}],
                    is_truncated=True,
                    last_invoicing_date="2024-02-15T00:00:00",
                )
            else:
                return ExportResult(
                    success=True,
                    invoices=[{"ksefReferenceNumber": "REF-002"}],
                    is_truncated=False,
                )

        with patch.object(manager.export_manager, "run_export", side_effect=fake_run_export):
            manager._process_subject_type(
                job_id=job_id,
                subject_type="Subject1",
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 4, 1),
                date_type="Invoicing",
            )

        assert call_count["n"] == 2
        # Second window should start at lastInvoicingDate
        assert dates_used[1][0] == datetime(2024, 2, 15)

    def test_non_truncated_advances_by_window_size(self, manager, db):
        session = db.get_session()
        job = db.create_initial_load_job(session, ["Subject1"],
                                          datetime(2024, 1, 1), datetime(2024, 2, 1),
                                          windows_total=2)
        job.status = "running"
        session.commit()
        job_id = job.id
        session.close()

        dates_used = []

        def fake_run_export(subject_type, date_from, date_to, **kwargs):
            dates_used.append((date_from, date_to))
            return ExportResult(success=True, invoices=[], is_truncated=False)

        with patch.object(manager.export_manager, "run_export", side_effect=fake_run_export):
            manager._process_subject_type(
                job_id=job_id,
                subject_type="Subject1",
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 2, 1),
                date_type="Invoicing",
            )

        # Single window. effective_end = end_date + 1day, so date_to passed
        # to run_export is 2024-02-02T00:00 (next-day midnight). KSeF treats
        # `to` as inclusive at the instant — invoices issued anywhere on
        # 2024-02-01 are captured (timestamps < 2024-02-02T00:00).
        assert len(dates_used) == 1
        assert dates_used[0][0] == datetime(2024, 1, 1)
        assert dates_used[0][1] == datetime(2024, 2, 2)
