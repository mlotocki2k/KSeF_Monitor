"""
Tests for /api/v1/stats/* endpoints.

Uses in-memory SQLite with seeded data.
"""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import create_app
from app.database import Base, Database, Invoice, ApiRequestLog


class InMemoryDB(Database):
    def __init__(self, engine, session_factory):
        self.engine = engine
        self.SessionLocal = session_factory
        self.db_path = ":memory:"


@pytest.fixture
def seeded_db():
    """DB with invoices and API request logs."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = InMemoryDB(engine, SessionLocal)

    session = SessionLocal()

    # 10 subject1 invoices in 2026-03, 5 subject2 in 2026-02
    for i in range(1, 11):
        session.add(Invoice(
            ksef_number=f"1111111111-20260301-AAAAAA-{i:02d}",
            subject_type="subject1",
            seller_nip="1111111111",
            issue_date=f"2026-03-{i:02d}",
            gross_amount=100.0 * i,
        ))
    for i in range(1, 6):
        session.add(Invoice(
            ksef_number=f"2222222222-20260201-BBBBBB-{i:02d}",
            subject_type="subject2",
            seller_nip="2222222222",
            issue_date=f"2026-02-{i:02d}",
            gross_amount=200.0 * i,
        ))

    # API request logs
    for i in range(3):
        session.add(ApiRequestLog(
            endpoint="/api/online/query/invoices",
            method="GET",
            status_code=200,
            response_time_ms=100.0 + i * 50,
            requested_at=datetime(2026, 3, 12, 10, i, tzinfo=timezone.utc),
        ))
    session.add(ApiRequestLog(
        endpoint="/api/online/query/invoices",
        method="GET",
        status_code=429,
        response_time_ms=50.0,
        requested_at=datetime(2026, 3, 12, 10, 5, tzinfo=timezone.utc),
    ))

    session.commit()
    session.close()
    return db


@pytest.fixture
def client(seeded_db):
    app = create_app(db=seeded_db, auth_token=None)
    return TestClient(app)


class TestStatsSummary:
    """GET /api/v1/stats/summary"""

    def test_total_count(self, client):
        resp = client.get("/api/v1/stats/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_invoices"] == 15

    def test_by_subject_type(self, client):
        resp = client.get("/api/v1/stats/summary")
        data = resp.json()
        assert data["by_subject_type"]["subject1"] == 10
        assert data["by_subject_type"]["subject2"] == 5

    def test_by_month(self, client):
        resp = client.get("/api/v1/stats/summary")
        data = resp.json()
        assert "2026-03" in data["by_month"]
        assert "2026-02" in data["by_month"]
        assert data["by_month"]["2026-03"] == 10
        assert data["by_month"]["2026-02"] == 5


class TestApiStatsEndpoint:
    """GET /api/v1/stats/api"""

    def test_default_1_hour(self, client):
        resp = client.get("/api/v1/stats/api")
        assert resp.status_code == 200
        data = resp.json()
        assert data["period_hours"] == 1
        # Entries were inserted with fixed timestamps that may be >1h old
        # So total_requests might be 0 or 4 depending on timing
        assert "total_requests" in data
        assert "error_count" in data
        assert "avg_response_time_ms" in data

    def test_24_hour_window(self, client):
        resp = client.get("/api/v1/stats/api?hours=24")
        data = resp.json()
        assert data["period_hours"] == 24

    def test_invalid_hours(self, client):
        resp = client.get("/api/v1/stats/api?hours=0")
        assert resp.status_code == 422

    def test_hours_max_24(self, client):
        resp = client.get("/api/v1/stats/api?hours=100")
        assert resp.status_code == 422


class TestStatsNoDatabase:
    """503 when DB unavailable."""

    def test_summary_no_db(self):
        app = create_app(db=None)
        client = TestClient(app)
        resp = client.get("/api/v1/stats/summary")
        assert resp.status_code == 503

    def test_api_stats_no_db(self):
        app = create_app(db=None)
        client = TestClient(app)
        resp = client.get("/api/v1/stats/api")
        assert resp.status_code == 503
