"""db_admin CLI: delete-invoices with artifacts, CSV export formula safety."""

import csv
import io
from argparse import Namespace

import db_admin
from app.database import Database, Invoice, InvoiceArtifact


def _db(tmp_path):
    path = str(tmp_path / "admin.db")
    db = Database(path)
    db.create_tables()
    return db, path


def _invoice(session, ksef, seller_name="ACME"):
    inv = Invoice(ksef_number=ksef, subject_type="Subject2", seller_nip="1234567890",
                  seller_name=seller_name, invoice_number="FV/1")
    session.add(inv)
    session.flush()
    return inv


def test_delete_invoices_with_artifacts(tmp_path, capsys):
    db, path = _db(tmp_path)
    with db.get_session() as s:
        inv = _invoice(s, "1234567890-20260101-ABCDEF-12")
        s.add(InvoiceArtifact(invoice_id=inv.id, artifact_type="xml", status="downloaded"))
        s.commit()

    db_admin.cmd_delete_invoices(Namespace(db=path, nip=None, before=None, ksef_number=None,
                                           all=True, yes=True))

    with db.get_session() as s:
        assert s.query(Invoice).count() == 0
        assert s.query(InvoiceArtifact).count() == 0


def test_csv_export_neutralizes_formulas(tmp_path):
    db, path = _db(tmp_path)
    with db.get_session() as s:
        _invoice(s, "1234567890-20260101-ABCDEF-12", seller_name='=HYPERLINK("http://x","y")')
        s.commit()
    out = tmp_path / "out.csv"

    db_admin.cmd_export_invoices(Namespace(db=path, format="csv", output=str(out)))

    rows = list(csv.DictReader(io.StringIO(out.read_text(encoding="utf-8"))))
    assert rows[0]["seller_name"].startswith("'=")
