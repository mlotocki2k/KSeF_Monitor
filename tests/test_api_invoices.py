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


@pytest.fixture
def client_auth():
    """App with auth token configured, no DB."""
    app = create_app(db=None, auth_token="a" * 32)
    return TestClient(app)


class TestKsefNumberValidation:
    """V5-03: path parameter validation on invoice download endpoints."""

    def test_get_invoice_xml_rejects_path_traversal(self, client_auth):
        # Starlette normalises %2F-encoded slashes before routing,
        # so the path traversal attempt never reaches our validator
        # and returns 404 (no route matched). Pydantic may return 422 for
        # other invalid inputs. Neither 404 nor 422 is 200 — both are safe.
        resp = client_auth.get(
            "/api/v1/invoices/..%2F..%2Fetc%2Fpasswd/xml",
            headers={"Authorization": "Bearer " + "a" * 32},
        )
        assert resp.status_code in (404, 422)

    def test_get_invoice_pdf_rejects_bad_chars(self, client_auth):
        resp = client_auth.get(
            "/api/v1/invoices/FAKE%0d%0aX-Bad%3Ahi/pdf",
            headers={"Authorization": "Bearer " + "a" * 32},
        )
        assert resp.status_code == 422

    def test_get_invoice_pdf_rejects_random_string(self, client_auth):
        resp = client_auth.get(
            "/api/v1/invoices/not-a-ksef-number/pdf",
            headers={"Authorization": "Bearer " + "a" * 32},
        )
        assert resp.status_code == 422

    def test_get_invoice_accepts_valid_format(self, client_auth):
        """Valid format should pass validation (may still 404/503 downstream)."""
        resp = client_auth.get(
            "/api/v1/invoices/1234567890-20260101-ABCDEF-01",
            headers={"Authorization": "Bearer " + "a" * 32},
        )
        assert resp.status_code != 422


class TestUpoEndpoint:
    """GET /api/v1/invoices/{ksef}/upo — serves cached UPO XML (v0.6 §4)."""

    KSEF = "1111111111-20260301-AAAAAA-01"

    def _db_with_upo(self, tmp_path, with_file=True):
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        db = InMemoryDB(engine, sessionmaker(bind=engine))

        upo_path = str(tmp_path / "upo.xml")
        if with_file:
            with open(upo_path, "w", encoding="utf-8") as f:
                f.write("<UPO>ok</UPO>")

        s = db.SessionLocal()
        inv = Invoice(
            ksef_number=self.KSEF, invoice_number="FV/1", invoice_type="VAT",
            subject_type="Subject1", issue_date="2026-03-01",
            gross_amount=1.0, net_amount=1.0, vat_amount=0.0, currency="PLN",
            seller_nip="1111111111", seller_name="Test Seller", source="polling",
            has_upo=with_file, upo_path=upo_path if with_file else None,
        )
        s.add(inv)
        s.commit()
        if with_file:
            db.create_artifact(s, inv.id, "upo")
            db.mark_artifact_downloaded(s, inv.id, "upo", file_path=upo_path, file_hash="h")
            s.commit()
        s.close()
        return db

    def test_upo_download_ok(self, tmp_path):
        client = TestClient(create_app(db=self._db_with_upo(tmp_path), auth_token=None))
        resp = client.get(f"/api/v1/invoices/{self.KSEF}/upo")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/xml")
        assert resp.text == "<UPO>ok</UPO>"

    def test_upo_404_when_not_available(self, tmp_path):
        client = TestClient(create_app(db=self._db_with_upo(tmp_path, with_file=False), auth_token=None))
        resp = client.get(f"/api/v1/invoices/{self.KSEF}/upo")
        assert resp.status_code == 404

    def test_upo_404_unknown_invoice(self, tmp_path):
        client = TestClient(create_app(db=self._db_with_upo(tmp_path), auth_token=None))
        resp = client.get("/api/v1/invoices/9999999999-20260301-AAAAAA-99/upo")
        assert resp.status_code == 404

    def test_upo_503_without_db(self):
        client = TestClient(create_app(db=None, auth_token=None))
        resp = client.get(f"/api/v1/invoices/{self.KSEF}/upo")
        assert resp.status_code == 503
