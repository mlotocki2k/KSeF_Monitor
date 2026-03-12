"""
Tests for v0.4 database additions: ApiRequestLog, InvoiceArtifact, and their CRUD methods.

Uses in-memory SQLite — no data persisted to disk.
All test data is synthetic (no real NIP/company names).
"""

import pytest
from datetime import datetime, timezone, timedelta

from app.database import (
    Base,
    Database,
    Invoice,
    ApiRequestLog,
    InvoiceArtifact,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db():
    """In-memory SQLite database with all tables created."""
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
def session(db):
    """Fresh session, rolled back after test."""
    s = db.get_session()
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def sample_invoice(session):
    """Insert a sample invoice and return it."""
    inv = Invoice(
        ksef_number="1111111111-20260301-AAAAAA-01",
        invoice_number="FV/TEST/001",
        subject_type="subject1",
        seller_nip="1111111111",
        seller_name="Test Seller Sp. z o.o.",
        buyer_nip="2222222222",
        buyer_name="Test Buyer S.A.",
        issue_date="2026-03-01",
        gross_amount=1230.00,
        net_amount=1000.00,
        vat_amount=230.00,
        currency="PLN",
        source="polling",
    )
    session.add(inv)
    session.flush()
    return inv


# ── ApiRequestLog ────────────────────────────────────────────────────────


class TestApiRequestLog:
    """CRUD for api_request_log table."""

    def test_log_api_request_creates_entry(self, db, session):
        entry = db.log_api_request(
            session,
            endpoint="/api/v1/invoices",
            method="GET",
            nip="1111111111",
            status_code=200,
            response_time_ms=150.5,
            retry_count=0,
            invoices_returned=10,
        )
        assert entry.id is not None
        assert entry.endpoint == "/api/v1/invoices"
        assert entry.method == "GET"
        assert entry.status_code == 200
        assert entry.response_time_ms == 150.5

    def test_log_api_request_truncates_long_endpoint(self, db, session):
        long_endpoint = "x" * 500
        entry = db.log_api_request(session, endpoint=long_endpoint, method="GET")
        assert len(entry.endpoint) == 200

    def test_log_api_request_truncates_long_method(self, db, session):
        entry = db.log_api_request(session, endpoint="/test", method="LONGMETHOD")
        assert len(entry.method) == 10

    def test_log_api_request_optional_fields(self, db, session):
        entry = db.log_api_request(session, endpoint="/test", method="GET")
        assert entry.nip is None
        assert entry.status_code is None
        assert entry.response_time_ms is None
        assert entry.invoices_returned is None

    def test_log_api_request_sets_timestamp(self, db, session):
        entry = db.log_api_request(session, endpoint="/test", method="GET")
        assert entry.requested_at is not None


class TestApiStats:
    """get_api_stats() aggregation."""

    def test_empty_stats(self, db, session):
        result = db.get_api_stats(session, hours=1)
        assert result["total_requests"] == 0
        assert result["error_count"] == 0
        assert result["avg_response_time_ms"] == 0.0
        assert result["period_hours"] == 1

    def test_stats_counts_recent_requests(self, db, session):
        for i in range(5):
            db.log_api_request(
                session,
                endpoint="/test",
                method="GET",
                status_code=200,
                response_time_ms=100.0,
            )
        result = db.get_api_stats(session, hours=1)
        assert result["total_requests"] == 5
        assert result["error_count"] == 0
        assert result["avg_response_time_ms"] == 100.0

    def test_stats_counts_errors(self, db, session):
        db.log_api_request(session, endpoint="/a", method="GET", status_code=200)
        db.log_api_request(session, endpoint="/b", method="GET", status_code=429)
        db.log_api_request(session, endpoint="/c", method="GET", status_code=500)
        result = db.get_api_stats(session, hours=1)
        assert result["total_requests"] == 3
        assert result["error_count"] == 2  # 429 + 500

    def test_stats_respects_period(self, db, session):
        """Only counts requests within the requested time window."""
        # Insert a request with old timestamp
        old_entry = ApiRequestLog(
            endpoint="/old",
            method="GET",
            status_code=200,
            requested_at=datetime.now(timezone.utc) - timedelta(hours=3),
        )
        session.add(old_entry)
        session.flush()

        # Insert a recent request
        db.log_api_request(session, endpoint="/new", method="GET", status_code=200)

        result = db.get_api_stats(session, hours=1)
        assert result["total_requests"] == 1  # Only the recent one


# ── InvoiceArtifact ──────────────────────────────────────────────────────


class TestInvoiceArtifact:
    """CRUD for invoice_artifacts table."""

    def test_create_artifact(self, db, session, sample_invoice):
        art = db.create_artifact(session, sample_invoice.id, "xml")
        assert art is not None
        assert art.invoice_id == sample_invoice.id
        assert art.artifact_type == "xml"
        assert art.status == "pending"
        assert art.download_attempts == 0

    def test_create_artifact_duplicate_returns_none(self, db, session, sample_invoice):
        db.create_artifact(session, sample_invoice.id, "xml")
        dup = db.create_artifact(session, sample_invoice.id, "xml")
        assert dup is None

    def test_create_different_types(self, db, session, sample_invoice):
        xml_art = db.create_artifact(session, sample_invoice.id, "xml")
        pdf_art = db.create_artifact(session, sample_invoice.id, "pdf")
        assert xml_art is not None
        assert pdf_art is not None

    def test_mark_artifact_downloaded(self, db, session, sample_invoice):
        db.create_artifact(session, sample_invoice.id, "xml")
        art = db.mark_artifact_downloaded(
            session,
            sample_invoice.id,
            "xml",
            file_path="/data/invoices/test.xml",
            file_hash="sha256abcdef1234567890",
            file_size=1024,
        )
        assert art.status == "downloaded"
        assert art.file_path == "/data/invoices/test.xml"
        assert art.file_hash == "sha256abcdef1234567890"
        assert art.file_size == 1024
        assert art.download_attempts == 1

    def test_mark_artifact_downloaded_nonexistent(self, db, session, sample_invoice):
        result = db.mark_artifact_downloaded(
            session, sample_invoice.id, "xml", file_path="/test"
        )
        assert result is None

    def test_mark_artifact_failed(self, db, session, sample_invoice):
        db.create_artifact(session, sample_invoice.id, "pdf")
        art = db.mark_artifact_failed(
            session, sample_invoice.id, "pdf", error="Connection timeout"
        )
        assert art.status == "failed"
        assert art.download_attempts == 1
        assert art.last_error == "Connection timeout"

    def test_mark_artifact_failed_nonexistent(self, db, session, sample_invoice):
        result = db.mark_artifact_failed(
            session, sample_invoice.id, "pdf", error="err"
        )
        assert result is None

    def test_mark_artifact_failed_truncates_error(self, db, session, sample_invoice):
        db.create_artifact(session, sample_invoice.id, "xml")
        long_error = "E" * 1000
        art = db.mark_artifact_failed(
            session, sample_invoice.id, "xml", error=long_error
        )
        assert len(art.last_error) == 500


class TestPendingArtifacts:
    """get_pending_artifacts() query."""

    def test_empty_returns_empty_list(self, db, session):
        result = db.get_pending_artifacts(session)
        assert result == []

    def test_returns_pending_artifacts(self, db, session, sample_invoice):
        db.create_artifact(session, sample_invoice.id, "xml")
        db.create_artifact(session, sample_invoice.id, "pdf")
        result = db.get_pending_artifacts(session)
        assert len(result) == 2

    def test_returns_failed_artifacts(self, db, session, sample_invoice):
        db.create_artifact(session, sample_invoice.id, "xml")
        db.mark_artifact_failed(session, sample_invoice.id, "xml", error="err")
        result = db.get_pending_artifacts(session)
        assert len(result) == 1
        assert result[0].status == "failed"

    def test_excludes_downloaded_artifacts(self, db, session, sample_invoice):
        db.create_artifact(session, sample_invoice.id, "xml")
        db.mark_artifact_downloaded(session, sample_invoice.id, "xml", file_path="/p")
        result = db.get_pending_artifacts(session)
        assert len(result) == 0

    def test_excludes_max_attempts(self, db, session, sample_invoice):
        """Artifacts with 3+ download attempts are excluded."""
        db.create_artifact(session, sample_invoice.id, "xml")
        # Fail 3 times
        for _ in range(3):
            db.mark_artifact_failed(session, sample_invoice.id, "xml", error="err")
        result = db.get_pending_artifacts(session)
        assert len(result) == 0

    def test_respects_limit(self, db, session):
        """Limit parameter caps results."""
        for i in range(5):
            inv = Invoice(
                ksef_number=f"1111111111-20260301-AAAAAA-0{i}",
                subject_type="subject1",
                seller_nip="1111111111",
            )
            session.add(inv)
            session.flush()
            db.create_artifact(session, inv.id, "xml")

        result = db.get_pending_artifacts(session, limit=3)
        assert len(result) == 3


class TestInvoiceSourceField:
    """Invoice.source field (v0.4 addition)."""

    def test_default_source_is_polling(self, session):
        inv = Invoice(
            ksef_number="1111111111-20260301-BBBBBB-01",
            subject_type="subject1",
            seller_nip="1111111111",
        )
        session.add(inv)
        session.flush()
        assert inv.source == "polling"

    def test_custom_source(self, session):
        inv = Invoice(
            ksef_number="1111111111-20260301-CCCCCC-01",
            subject_type="subject1",
            seller_nip="1111111111",
            source="initial_load",
        )
        session.add(inv)
        session.flush()
        assert inv.source == "initial_load"
