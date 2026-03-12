"""
Tests for /api/v1/invoices endpoints — pagination, filtering, sorting, detail.

Uses in-memory SQLite with seeded test data.
All data is synthetic — no real NIP or company names.
"""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import create_app
from app.database import Base, Database, Invoice


class InMemoryDB(Database):
    """Database backed by in-memory SQLite for testing."""

    def __init__(self, engine, session_factory):
        self.engine = engine
        self.SessionLocal = session_factory
        self.db_path = ":memory:"


@pytest.fixture
def seeded_db():
    """In-memory DB with 15 test invoices."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = InMemoryDB(engine, SessionLocal)

    session = SessionLocal()
    for i in range(1, 16):
        inv = Invoice(
            ksef_number=f"1111111111-20260301-AAAAAA-{i:02d}",
            invoice_number=f"FV/2026/03/{i:03d}",
            invoice_type="VAT",
            subject_type="subject1" if i <= 10 else "subject2",
            issue_date=f"2026-03-{i:02d}",
            gross_amount=100.0 * i,
            net_amount=81.30 * i,
            vat_amount=18.70 * i,
            currency="PLN",
            seller_nip="1111111111",
            seller_name="Test Seller Sp. z o.o.",
            buyer_nip="2222222222" if i <= 12 else "3333333333",
            buyer_name="Test Buyer S.A." if i <= 12 else "Other Buyer Sp. z o.o.",
            source="polling",
            created_at=datetime(2026, 3, i, 10, 0, tzinfo=timezone.utc),
        )
        session.add(inv)
    session.commit()
    session.close()
    return db


@pytest.fixture
def client(seeded_db):
    app = create_app(db=seeded_db, auth_token=None)
    return TestClient(app)


class TestListInvoices:
    """GET /api/v1/invoices"""

    def test_default_pagination(self, client):
        resp = client.get("/api/v1/invoices")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 15
        assert data["page"] == 1
        assert data["per_page"] == 20
        assert len(data["items"]) == 15

    def test_custom_page_size(self, client):
        resp = client.get("/api/v1/invoices?per_page=5")
        data = resp.json()
        assert len(data["items"]) == 5
        assert data["pages"] == 3

    def test_page_2(self, client):
        resp = client.get("/api/v1/invoices?per_page=5&page=2")
        data = resp.json()
        assert len(data["items"]) == 5
        assert data["page"] == 2

    def test_last_page(self, client):
        resp = client.get("/api/v1/invoices?per_page=5&page=3")
        data = resp.json()
        assert len(data["items"]) == 5
        assert data["page"] == 3

    def test_beyond_last_page(self, client):
        resp = client.get("/api/v1/invoices?per_page=5&page=100")
        data = resp.json()
        assert len(data["items"]) == 0

    def test_per_page_max_100(self, client):
        resp = client.get("/api/v1/invoices?per_page=200")
        assert resp.status_code == 422  # FastAPI validation error

    def test_per_page_min_1(self, client):
        resp = client.get("/api/v1/invoices?per_page=0")
        assert resp.status_code == 422


class TestListInvoicesFiltering:
    """Filtering parameters."""

    def test_filter_by_subject_type(self, client):
        resp = client.get("/api/v1/invoices?subject_type=subject1")
        data = resp.json()
        assert data["total"] == 10
        for item in data["items"]:
            assert item["subject_type"] == "subject1"

    def test_filter_by_seller_nip(self, client):
        resp = client.get("/api/v1/invoices?seller_nip=1111111111")
        data = resp.json()
        assert data["total"] == 15

    def test_filter_by_buyer_nip(self, client):
        resp = client.get("/api/v1/invoices?buyer_nip=3333333333")
        data = resp.json()
        assert data["total"] == 3

    def test_invalid_nip_format(self, client):
        resp = client.get("/api/v1/invoices?seller_nip=123")
        assert resp.status_code == 400
        assert "seller_nip" in resp.json()["detail"]

    def test_filter_by_date_range(self, client):
        resp = client.get("/api/v1/invoices?issue_date_from=2026-03-05&issue_date_to=2026-03-10")
        data = resp.json()
        assert data["total"] == 6

    def test_search_by_invoice_number(self, client):
        resp = client.get("/api/v1/invoices?search=FV/2026/03/001")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["invoice_number"] == "FV/2026/03/001"

    def test_search_by_seller_name(self, client):
        resp = client.get("/api/v1/invoices?search=Test Seller")
        data = resp.json()
        assert data["total"] == 15

    def test_search_truncated_to_100_chars(self, client):
        """Search term longer than 100 chars doesn't crash."""
        resp = client.get(f"/api/v1/invoices?search={'x' * 200}")
        assert resp.status_code == 200


class TestListInvoicesSorting:
    """Sorting parameters."""

    def test_sort_by_created_at_desc(self, client):
        resp = client.get("/api/v1/invoices?sort_by=created_at&sort_order=desc")
        data = resp.json()
        dates = [item["created_at"] for item in data["items"]]
        assert dates == sorted(dates, reverse=True)

    def test_sort_by_gross_amount_asc(self, client):
        resp = client.get("/api/v1/invoices?sort_by=gross_amount&sort_order=asc")
        data = resp.json()
        amounts = [item["gross_amount"] for item in data["items"]]
        assert amounts == sorted(amounts)

    def test_sort_by_ksef_number(self, client):
        resp = client.get("/api/v1/invoices?sort_by=ksef_number&sort_order=asc")
        data = resp.json()
        numbers = [item["ksef_number"] for item in data["items"]]
        assert numbers == sorted(numbers)

    def test_invalid_sort_field(self, client):
        resp = client.get("/api/v1/invoices?sort_by=password")
        assert resp.status_code == 422


class TestGetInvoice:
    """GET /api/v1/invoices/{ksef_number}"""

    def test_existing_invoice(self, client):
        resp = client.get("/api/v1/invoices/1111111111-20260301-AAAAAA-01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ksef_number"] == "1111111111-20260301-AAAAAA-01"
        assert data["invoice_number"] == "FV/2026/03/001"
        assert data["gross_amount"] == 100.0

    def test_nonexistent_invoice(self, client):
        resp = client.get("/api/v1/invoices/0000000000-20260301-ZZZZZZ-99")
        assert resp.status_code == 404

    def test_detail_has_extra_fields(self, client):
        """Detail response includes fields not in summary."""
        resp = client.get("/api/v1/invoices/1111111111-20260301-AAAAAA-01")
        data = resp.json()
        assert "net_amount" in data
        assert "vat_amount" in data
        assert "source" in data

    def test_no_internal_ids_in_response(self, client):
        """Response must not leak internal database IDs."""
        resp = client.get("/api/v1/invoices/1111111111-20260301-AAAAAA-01")
        data = resp.json()
        assert "id" not in data
        assert "raw_metadata" not in data
        assert "xml_path" not in data
        assert "pdf_path" not in data


class TestNoDatabase:
    """Endpoints return 503 when DB is unavailable."""

    def test_list_invoices_no_db(self):
        app = create_app(db=None)
        client = TestClient(app)
        resp = client.get("/api/v1/invoices")
        assert resp.status_code == 503

    def test_get_invoice_no_db(self):
        app = create_app(db=None)
        client = TestClient(app)
        resp = client.get("/api/v1/invoices/1111111111-20260301-AAAAAA-01")
        assert resp.status_code == 503
