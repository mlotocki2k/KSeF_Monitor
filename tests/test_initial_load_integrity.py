"""
Initial load must not report a window as successful when its invoices were
not saved or not fully fetched, and must honor the KSeF dateType enum.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routers.initial_load import StartJobRequest
from app.database import Base, Database, InitialLoadWindow
from app.initial_load_manager import InitialLoadManager, normalize_date_type
from app.invoice_export_manager import ExportResult


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    class InMemoryDB(Database):
        def __init__(self):
            self.engine = engine
            self.SessionLocal = SessionLocal

    return InMemoryDB()


@pytest.fixture
def manager(db):
    cfg = MagicMock()
    cfg.get.return_value = None
    return InitialLoadManager(cfg, MagicMock(), db)


def _job(db):
    s = db.get_session()
    job = db.create_initial_load_job(s, ["Subject1"], datetime(2024, 1, 1),
                                     datetime(2024, 2, 1), windows_total=1)
    job.status = "running"
    s.commit()
    job_id = job.id
    s.close()
    return job_id


def _windows(db):
    with db.get_session() as s:
        return [(w.status, w.imported) for w in s.query(InitialLoadWindow).all()]


def _run(manager, job_id, date_type="Invoicing"):
    return manager._process_subject_type(
        job_id=job_id, subject_type="Subject1",
        start_date=datetime(2024, 1, 1), end_date=datetime(2024, 2, 1),
        date_type=date_type,
    )


def test_save_failure_marks_window_failed(manager, db):
    job_id = _job(db)
    ok = ExportResult(success=True, invoices=[{"ksefNumber": "X"}], is_truncated=False)
    with patch.object(manager.export_manager, "run_export", return_value=ok), \
         patch.object(manager.db, "save_invoice", side_effect=RuntimeError("database is locked")):
        imported, _skipped, failures = _run(manager, job_id)

    assert imported == 0
    assert len(failures) == 1
    assert _windows(db) == [("failed", 0)]


def test_truncated_issue_date_type_uses_last_issue_date(manager, db):
    job_id = _job(db)
    calls = []

    def fake(subject_type, date_from, date_to, **kw):
        calls.append((date_from, kw.get("date_type")))
        if len(calls) == 1:
            return ExportResult(success=True, invoices=[], is_truncated=True,
                                last_issue_date="2024-01-10T00:00:00",
                                last_invoicing_date="2024-01-20T00:00:00")
        return ExportResult(success=True, invoices=[], is_truncated=False)

    with patch.object(manager.export_manager, "run_export", side_effect=fake):
        _run(manager, job_id, date_type="Issue")

    assert calls[1][0] == datetime(2024, 1, 10)
    assert calls[0][1] == "Issue"


def test_truncated_without_last_date_is_failure_not_skip(manager, db):
    job_id = _job(db)
    res = ExportResult(success=True, invoices=[], is_truncated=True)
    with patch.object(manager.export_manager, "run_export", return_value=res):
        _imported, _skipped, failures = _run(manager, job_id)

    assert len(failures) == 1
    assert _windows(db)[-1][0] == "failed"


def test_legacy_issuedate_alias_is_sent_as_issue(manager, db):
    job_id = _job(db)
    res = ExportResult(success=True, invoices=[], is_truncated=False)
    with patch.object(manager.export_manager, "run_export", return_value=res) as run:
        _run(manager, job_id, date_type="IssueDate")
    assert run.call_args.kwargs["date_type"] == "Issue"


def test_job_cancelled_before_thread_start_stays_cancelled(manager, db):
    job_id = _job(db)
    with db.get_session() as s:
        db.cancel_initial_load_job(s, job_id)
        s.commit()
    with patch.object(manager, "_process_subject_type") as proc:
        manager._run_job(job_id)
    proc.assert_not_called()
    with db.get_session() as s:
        assert db.get_initial_load_job(s, job_id).status == "cancelled"


def test_normalize_date_type():
    assert normalize_date_type("Invoicing") == "Invoicing"
    assert normalize_date_type("Issue") == "Issue"
    assert normalize_date_type("IssueDate") == "Issue"
    assert normalize_date_type("PermanentStorage") == "PermanentStorage"
    with pytest.raises(ValueError):
        normalize_date_type("Bogus")


def test_api_accepts_spec_date_types():
    for dt in ("Invoicing", "Issue", "PermanentStorage"):
        StartJobRequest(start_date="2024-01-01", end_date="2024-02-01", date_type=dt)
    with pytest.raises(ValueError):
        StartJobRequest(start_date="2024-01-01", end_date="2024-02-01", date_type="Bogus")


def test_finished_job_is_found_for_autostart(manager, db):
    s = db.get_session()
    job = db.create_initial_load_job(s, ["Subject1", "Subject2"], datetime(2024, 1, 1),
                                     datetime(2024, 6, 1), windows_total=2)
    job.status = "completed_with_errors"
    s.commit()
    s.close()
    found = manager.finished_job_for(datetime(2024, 1, 1), ["Subject2", "Subject1"], "Invoicing")
    assert found is not None
    assert manager.finished_job_for(datetime(2024, 2, 1), ["Subject1", "Subject2"], "Invoicing") is None
    assert manager.finished_job_for(datetime(2024, 1, 1), ["Subject1"], "Invoicing") is None


def test_failed_job_does_not_block_autostart(manager, db):
    s = db.get_session()
    job = db.create_initial_load_job(s, ["Subject1"], datetime(2024, 1, 1), datetime(2024, 6, 1), windows_total=1)
    job.status = "failed"
    s.commit()
    s.close()
    assert manager.finished_job_for(datetime(2024, 1, 1), ["Subject1"], "Invoicing") is None
