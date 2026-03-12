"""
Tests for /api/v1/monitor/* endpoints — health, state, trigger.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import create_app
from app.database import Base, Database, MonitorState


class InMemoryDB(Database):
    def __init__(self, engine, session_factory):
        self.engine = engine
        self.SessionLocal = session_factory
        self.db_path = ":memory:"


@pytest.fixture
def db_with_state():
    """DB with monitor state entries."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = InMemoryDB(engine, SessionLocal)

    session = SessionLocal()
    session.add(MonitorState(
        nip="1111111111",
        subject_type="subject1",
        last_check=datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc),
        invoices_count=42,
        status="active",
    ))
    session.add(MonitorState(
        nip="1111111111",
        subject_type="subject2",
        last_check=datetime(2026, 3, 12, 9, 30, tzinfo=timezone.utc),
        invoices_count=15,
        status="active",
    ))
    session.commit()
    session.close()
    return db


class TestHealthEndpoint:
    """GET /api/v1/monitor/health"""

    def test_health_without_db(self):
        app = create_app(db=None, auth_token=None)
        client = TestClient(app)
        resp = client.get("/api/v1/monitor/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.4.0"
        assert data["db_connected"] is False
        assert data["auth_enabled"] is False

    def test_health_with_db(self, db_with_state):
        app = create_app(db=db_with_state, auth_token=None)
        client = TestClient(app)
        resp = client.get("/api/v1/monitor/health")
        data = resp.json()
        assert data["status"] == "ok"
        assert data["db_connected"] is True

    def test_health_auth_enabled_flag(self):
        app = create_app(db=None, auth_token="a" * 32)
        client = TestClient(app)
        resp = client.get("/api/v1/monitor/health")
        data = resp.json()
        assert data["auth_enabled"] is True


class TestMonitorState:
    """GET /api/v1/monitor/state"""

    def test_returns_all_states(self, db_with_state):
        app = create_app(db=db_with_state, auth_token=None)
        client = TestClient(app)
        resp = client.get("/api/v1/monitor/state")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        nips = [s["nip"] for s in data]
        assert "1111111111" in nips

    def test_state_no_db(self):
        app = create_app(db=None, auth_token=None)
        client = TestClient(app)
        resp = client.get("/api/v1/monitor/state")
        assert resp.status_code == 503


class TestTriggerEndpoint:
    """POST /api/v1/monitor/trigger"""

    def test_trigger_no_monitor(self):
        app = create_app(db=None, monitor_instance=None, auth_token=None)
        client = TestClient(app)
        resp = client.post("/api/v1/monitor/trigger")
        assert resp.status_code == 200
        data = resp.json()
        assert data["triggered"] is False

    def test_trigger_with_scheduler(self):
        mock_monitor = MagicMock()
        mock_scheduler = MagicMock()
        mock_monitor.scheduler = mock_scheduler
        mock_scheduler.force_next_run = MagicMock()

        app = create_app(db=None, monitor_instance=mock_monitor, auth_token=None)
        client = TestClient(app)
        resp = client.post("/api/v1/monitor/trigger")
        assert resp.status_code == 200
        data = resp.json()
        assert data["triggered"] is True
        mock_scheduler.force_next_run.assert_called_once()

    def test_trigger_scheduler_exception(self):
        mock_monitor = MagicMock()
        mock_scheduler = MagicMock()
        mock_monitor.scheduler = mock_scheduler
        mock_scheduler.force_next_run.side_effect = RuntimeError("boom")

        app = create_app(db=None, monitor_instance=mock_monitor, auth_token=None)
        client = TestClient(app)
        resp = client.post("/api/v1/monitor/trigger")
        assert resp.status_code == 200
        data = resp.json()
        assert data["triggered"] is False
