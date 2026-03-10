#!/usr/bin/env python3
"""
KSeF Monitor — Database Administration Tool

Usage:
    python db_admin.py status                  # DB overview: tables, counts, size
    python db_admin.py invoices [--limit N]    # List invoices (newest first)
    python db_admin.py invoice <ksef_number>   # Show invoice details
    python db_admin.py state                   # Show monitor_state per NIP+subject
    python db_admin.py notifications [--limit N]  # Show notification log
    python db_admin.py stats                   # Aggregate statistics
    python db_admin.py errors                  # Show recent errors from monitor_state
    python db_admin.py search <query>          # Search invoices by ksef_number, seller, buyer
    python db_admin.py set-last-check <nip> <datetime>    # Set last_check date for NIP
    python db_admin.py delete-last-check <nip>           # Delete monitor_state for NIP
    python db_admin.py delete-invoices [--nip NIP] [--before DATE] [--all]  # Delete invoices
    python db_admin.py cleanup-notifications [--days N]  # Delete old notification logs
    python db_admin.py export-invoices [--format csv|json] [--output FILE]  # Export invoices
    python db_admin.py reset-errors            # Reset consecutive_errors counters
    python db_admin.py vacuum                  # SQLite VACUUM (compact DB file)
"""

import argparse
import csv
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import func, inspect, text
from app.database import Database, Invoice, MonitorState, NotificationLog


def _default_db_path() -> str:
    """Auto-detect DB path: /data/invoices.db (Docker) or data/invoices.db (local)."""
    # Docker container: /data directory exists and is writable
    if Path("/data").is_dir():
        return "/data/invoices.db"
    return "data/invoices.db"


def get_db(args) -> Database:
    """Get Database instance from --db argument. Creates tables if missing."""
    db = Database(args.db)
    db.create_tables()
    return db


def file_size_str(path: str) -> str:
    """Human-readable file size."""
    try:
        size = Path(path).stat().st_size
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
    except OSError:
        return "N/A"


# ── Commands ────────────────────────────────────────────────────────────────


def cmd_status(args):
    """Show database overview."""
    db = get_db(args)
    session = db.get_session()

    print(f"Database: {db.db_path}")
    print(f"File size: {file_size_str(str(db.db_path))}")

    # WAL mode check
    wal = session.execute(text("PRAGMA journal_mode")).scalar()
    print(f"Journal mode: {wal}")

    # Table info
    insp = inspect(db.engine)
    tables = insp.get_table_names()
    print(f"\nTables ({len(tables)}):")
    for table in sorted(tables):
        if table == "alembic_version":
            ver = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
            print(f"  {table:30s}  migration: {ver}")
        else:
            count = session.execute(text(f"SELECT COUNT(*) FROM [{table}]")).scalar()
            print(f"  {table:30s}  {count:>8,} rows")

    # Indexes
    print(f"\nIndexes:")
    for table in sorted(tables):
        for idx in insp.get_indexes(table):
            unique = " UNIQUE" if idx.get("unique") else ""
            cols = ", ".join(str(c) for c in idx["column_names"])
            print(f"  {idx['name']:40s} ON {table}({cols}){unique}")

    session.close()


def cmd_invoices(args):
    """List invoices."""
    db = get_db(args)
    session = db.get_session()

    query = session.query(Invoice).order_by(Invoice.created_at.desc())
    if args.subject:
        query = query.filter(Invoice.subject_type == args.subject)
    if args.nip:
        query = query.filter(
            (Invoice.seller_nip == args.nip) | (Invoice.buyer_nip == args.nip)
        )

    invoices = query.limit(args.limit).all()

    if not invoices:
        print("No invoices found.")
        session.close()
        return

    # Header
    print(f"{'ID':>5}  {'KSeF Number':40s}  {'Type':8s}  {'Subject':9s}  "
          f"{'Issue Date':12s}  {'Gross':>12s}  {'Seller NIP':12s}  {'Buyer NIP':12s}  "
          f"{'XML':3s} {'PDF':3s} {'UPO':3s}")
    print("-" * 160)

    for inv in invoices:
        gross = f"{inv.gross_amount:,.2f}" if inv.gross_amount else "N/A"
        print(f"{inv.id:>5}  {(inv.ksef_number or '')[:40]:40s}  "
              f"{(inv.invoice_type or '-'):8s}  {inv.subject_type:9s}  "
              f"{(inv.issue_date or '-'):12s}  {gross:>12s}  "
              f"{(inv.seller_nip or '-'):12s}  {(inv.buyer_nip or '-'):12s}  "
              f"{'✓' if inv.has_xml else '·':3s} "
              f"{'✓' if inv.has_pdf else '·':3s} "
              f"{'✓' if inv.has_upo else '·':3s}")

    total = session.query(func.count(Invoice.id)).scalar()
    print(f"\nShowing {len(invoices)} of {total} invoices")
    session.close()


def cmd_invoice_detail(args):
    """Show single invoice details."""
    db = get_db(args)
    session = db.get_session()

    inv = session.query(Invoice).filter(
        (Invoice.ksef_number == args.ksef_number) | (Invoice.id == _safe_int(args.ksef_number))
    ).first()

    if not inv:
        print(f"Invoice not found: {args.ksef_number}")
        session.close()
        return

    fields = [
        ("ID", inv.id),
        ("KSeF Number", inv.ksef_number),
        ("Invoice Number", inv.invoice_number),
        ("Invoice Type", inv.invoice_type),
        ("Subject Type", inv.subject_type),
        ("Form Code", inv.form_code),
        ("Issue Date", inv.issue_date),
        ("Invoicing Date", inv.invoicing_date),
        ("Acquisition Date", inv.acquisition_date),
        ("Gross Amount", inv.gross_amount),
        ("Net Amount", inv.net_amount),
        ("VAT Amount", inv.vat_amount),
        ("Currency", inv.currency),
        ("", ""),
        ("Seller NIP", inv.seller_nip),
        ("Seller Name", inv.seller_name),
        ("Buyer NIP", inv.buyer_nip),
        ("Buyer Name", inv.buyer_name),
        ("", ""),
        ("Self-invoicing", inv.is_self_invoicing),
        ("Has Attachment", inv.has_attachment),
        ("", ""),
        ("Has XML", inv.has_xml),
        ("XML Path", inv.xml_path),
        ("Has PDF", inv.has_pdf),
        ("PDF Path", inv.pdf_path),
        ("Has UPO", inv.has_upo),
        ("UPO Path", inv.upo_path),
        ("", ""),
        ("Created At", inv.created_at),
        ("Updated At", inv.updated_at),
        ("Invoice Hash", inv.invoice_hash),
    ]

    for label, value in fields:
        if label == "":
            print()
        else:
            print(f"  {label:20s}: {value}")

    # Show notifications for this invoice
    notifs = session.query(NotificationLog).filter_by(invoice_id=inv.id).all()
    if notifs:
        print(f"\n  Notifications ({len(notifs)}):")
        for n in notifs:
            print(f"    [{n.sent_at}] {n.channel:10s} {n.status:6s} {n.event_type}")

    session.close()


def cmd_state(args):
    """Show monitor_state."""
    db = get_db(args)
    session = db.get_session()

    states = session.query(MonitorState).order_by(MonitorState.nip).all()

    if not states:
        print("No monitor state entries found.")
        session.close()
        return

    for s in states:
        print(f"NIP: {s.nip}  |  {s.subject_type}  |  Status: {s.status}")
        print(f"  Last check:      {s.last_check}")
        print(f"  Last invoice at: {s.last_invoice_at or 'N/A'}")
        print(f"  Last KSeF #:     {s.last_ksef_number or 'N/A'}")
        print(f"  Invoices count:  {s.invoices_count}")

        if s.consecutive_errors > 0:
            print(f"  ⚠ Consecutive errors: {s.consecutive_errors}")
            print(f"    Last error:    {s.last_error}")
            print(f"    Error at:      {s.last_error_at}")

        print(f"  Updated at:      {s.updated_at}")
        print()

    session.close()


def cmd_notifications(args):
    """Show notification log."""
    db = get_db(args)
    session = db.get_session()

    query = session.query(NotificationLog).order_by(NotificationLog.sent_at.desc())
    if args.channel:
        query = query.filter(NotificationLog.channel == args.channel)
    if args.status:
        query = query.filter(NotificationLog.status == args.status)

    logs = query.limit(args.limit).all()

    if not logs:
        print("No notification logs found.")
        session.close()
        return

    print(f"{'ID':>5}  {'Sent At':22s}  {'Event':10s}  {'Channel':10s}  "
          f"{'Status':7s}  {'InvID':>5s}  {'Title':30s}  {'Error'}")
    print("-" * 130)

    for n in logs:
        title = (n.title or "")[:30]
        error = (n.error_message or "")[:40]
        print(f"{n.id:>5}  {str(n.sent_at):22s}  {n.event_type:10s}  "
              f"{n.channel:10s}  {n.status:7s}  {(n.invoice_id or ''):>5}  "
              f"{title:30s}  {error}")

    total = session.query(func.count(NotificationLog.id)).scalar()
    print(f"\nShowing {len(logs)} of {total} notifications")
    session.close()


def cmd_stats(args):
    """Show aggregate statistics."""
    db = get_db(args)
    session = db.get_session()

    # Invoice stats
    total = session.query(func.count(Invoice.id)).scalar()
    print(f"=== Invoice Statistics ===")
    print(f"Total invoices: {total}")

    if total > 0:
        # Per subject_type
        for st in ("Subject1", "Subject2"):
            count = session.query(func.count(Invoice.id)).filter(Invoice.subject_type == st).scalar()
            gross = session.query(func.sum(Invoice.gross_amount)).filter(Invoice.subject_type == st).scalar()
            print(f"  {st}: {count} invoices, gross total: {gross or 0:,.2f} PLN")

        # Per month (last 6 months)
        print(f"\n  Monthly breakdown (last 6 months):")
        for i in range(6):
            dt = datetime.now() - timedelta(days=30 * i)
            month_str = dt.strftime("%Y-%m")
            count = session.query(func.count(Invoice.id)).filter(
                Invoice.issue_date.like(f"{month_str}%")
            ).scalar()
            if count > 0:
                gross = session.query(func.sum(Invoice.gross_amount)).filter(
                    Invoice.issue_date.like(f"{month_str}%")
                ).scalar()
                print(f"    {month_str}: {count} invoices, {gross or 0:,.2f} PLN")

        # Top sellers
        print(f"\n  Top 5 sellers:")
        top_sellers = (
            session.query(Invoice.seller_nip, Invoice.seller_name, func.count(Invoice.id).label("cnt"))
            .group_by(Invoice.seller_nip)
            .order_by(func.count(Invoice.id).desc())
            .limit(5)
            .all()
        )
        for nip, name, cnt in top_sellers:
            print(f"    {nip:12s}  {(name or 'N/A')[:30]:30s}  {cnt} invoices")

        # Artifact coverage
        xml_count = session.query(func.count(Invoice.id)).filter(Invoice.has_xml == True).scalar()
        pdf_count = session.query(func.count(Invoice.id)).filter(Invoice.has_pdf == True).scalar()
        upo_count = session.query(func.count(Invoice.id)).filter(Invoice.has_upo == True).scalar()
        print(f"\n  Artifacts: XML={xml_count}/{total}  PDF={pdf_count}/{total}  UPO={upo_count}/{total}")

    # Notification stats
    notif_total = session.query(func.count(NotificationLog.id)).scalar()
    print(f"\n=== Notification Statistics ===")
    print(f"Total notifications: {notif_total}")

    if notif_total > 0:
        for status in ("sent", "failed", "skipped"):
            count = session.query(func.count(NotificationLog.id)).filter(
                NotificationLog.status == status
            ).scalar()
            if count > 0:
                print(f"  {status}: {count}")

        print(f"\n  Per channel:")
        channels = (
            session.query(NotificationLog.channel, NotificationLog.status, func.count(NotificationLog.id))
            .group_by(NotificationLog.channel, NotificationLog.status)
            .all()
        )
        for ch, st, cnt in channels:
            print(f"    {ch:10s} {st:7s}: {cnt}")

    session.close()


def cmd_errors(args):
    """Show monitor_state entries with errors."""
    db = get_db(args)
    session = db.get_session()

    states = session.query(MonitorState).filter(MonitorState.consecutive_errors > 0).all()

    if not states:
        print("No errors in monitor_state. All clear!")
        session.close()
        return

    for s in states:
        print(f"⚠ NIP: {s.nip}  |  {s.subject_type}  |  Status: {s.status}")
        print(f"  Consecutive errors: {s.consecutive_errors}")
        print(f"  Last error:         {s.last_error}")
        print(f"  Error at:           {s.last_error_at}")
        print(f"  Last successful:    {s.last_check}")
        print()

    # Recent failed notifications
    failed = (
        session.query(NotificationLog)
        .filter(NotificationLog.status == "failed")
        .order_by(NotificationLog.sent_at.desc())
        .limit(10)
        .all()
    )
    if failed:
        print(f"Last {len(failed)} failed notifications:")
        for n in failed:
            print(f"  [{n.sent_at}] {n.channel}: {n.error_message or 'unknown error'}")

    session.close()


def cmd_search(args):
    """Search invoices by ksef_number, seller_name, buyer_name, NIP."""
    db = get_db(args)
    session = db.get_session()

    q = f"%{args.query}%"
    results = (
        session.query(Invoice)
        .filter(
            (Invoice.ksef_number.like(q))
            | (Invoice.invoice_number.like(q))
            | (Invoice.seller_name.like(q))
            | (Invoice.buyer_name.like(q))
            | (Invoice.seller_nip.like(q))
            | (Invoice.buyer_nip.like(q))
        )
        .order_by(Invoice.created_at.desc())
        .limit(args.limit)
        .all()
    )

    if not results:
        print(f"No invoices matching '{args.query}'")
        session.close()
        return

    print(f"Found {len(results)} invoice(s) matching '{args.query}':\n")
    for inv in results:
        gross = f"{inv.gross_amount:,.2f}" if inv.gross_amount else "N/A"
        print(f"  [{inv.id}] {inv.ksef_number}")
        print(f"       {inv.subject_type}  |  {inv.issue_date}  |  {gross} {inv.currency}")
        print(f"       Seller: {inv.seller_name} ({inv.seller_nip})")
        print(f"       Buyer:  {inv.buyer_name} ({inv.buyer_nip})")
        print()

    session.close()


def cmd_set_last_check(args):
    """Set last_check date for a NIP."""
    db = get_db(args)
    session = db.get_session()

    # Parse datetime
    try:
        dt = datetime.fromisoformat(args.datetime)
    except ValueError:
        print(f"Invalid datetime format: {args.datetime}")
        print("Expected: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS")
        session.close()
        return

    states = session.query(MonitorState).filter(MonitorState.nip == args.nip).all()

    if not states:
        print(f"No monitor_state entries for NIP: {args.nip}")
        session.close()
        return

    for s in states:
        old_val = s.last_check
        s.last_check = dt.isoformat()
        s.updated_at = datetime.now(timezone.utc)
        print(f"  {s.nip} ({s.subject_type}): {old_val} → {dt.isoformat()}")

    session.commit()
    print(f"\nUpdated last_check for {len(states)} entry/entries.")
    session.close()


def cmd_delete_last_check(args):
    """Delete monitor_state entries for a NIP."""
    db = get_db(args)
    session = db.get_session()

    states = session.query(MonitorState).filter(MonitorState.nip == args.nip).all()

    if not states:
        print(f"No monitor_state entries for NIP: {args.nip}")
        session.close()
        return

    print(f"Found {len(states)} monitor_state entry/entries for NIP {args.nip}:")
    for s in states:
        print(f"  {s.subject_type}: last_check={s.last_check}, invoices_count={s.invoices_count}")

    if not args.yes:
        answer = input(f"\nDelete these entries? Monitor will start fresh for this NIP. [y/N] ")
        if answer.lower() != "y":
            print("Aborted.")
            session.close()
            return

    count = session.query(MonitorState).filter(MonitorState.nip == args.nip).delete()
    session.commit()
    print(f"Deleted {count} monitor_state entry/entries.")
    session.close()


def cmd_delete_invoices(args):
    """Delete invoices from database."""
    db = get_db(args)
    session = db.get_session()

    query = session.query(Invoice)
    filters = []

    if args.nip:
        query = query.filter(
            (Invoice.seller_nip == args.nip) | (Invoice.buyer_nip == args.nip)
        )
        filters.append(f"NIP={args.nip}")

    if args.before:
        try:
            before_dt = datetime.fromisoformat(args.before)
            query = query.filter(Invoice.created_at < before_dt)
            filters.append(f"created before {args.before}")
        except ValueError:
            print(f"Invalid date format: {args.before}")
            print("Expected: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS")
            session.close()
            return

    if args.ksef_number:
        query = query.filter(Invoice.ksef_number == args.ksef_number)
        filters.append(f"ksef_number={args.ksef_number}")

    if not filters and not args.all:
        print("Safety: specify at least one filter (--nip, --before, --ksef-number) or --all")
        session.close()
        return

    count = query.count()

    if count == 0:
        print("No invoices match the given criteria.")
        session.close()
        return

    filter_desc = ", ".join(filters) if filters else "ALL invoices"
    print(f"Found {count} invoice(s) matching: {filter_desc}")

    # Show sample
    sample = query.order_by(Invoice.created_at.desc()).limit(5).all()
    for inv in sample:
        print(f"  [{inv.id}] {inv.ksef_number}  {inv.issue_date}  "
              f"{inv.seller_nip} → {inv.buyer_nip}")
    if count > 5:
        print(f"  ... and {count - 5} more")

    if not args.yes:
        answer = input(f"\nDelete {count} invoice(s) and their notification logs? [y/N] ")
        if answer.lower() != "y":
            print("Aborted.")
            session.close()
            return

    # Delete related notification logs first
    invoice_ids = [inv.id for inv in query.all()]
    if invoice_ids:
        notif_count = session.query(NotificationLog).filter(
            NotificationLog.invoice_id.in_(invoice_ids)
        ).delete(synchronize_session="fetch")
        print(f"Deleted {notif_count} related notification log(s).")

    deleted = query.delete(synchronize_session="fetch")
    session.commit()
    print(f"Deleted {deleted} invoice(s).")
    session.close()


def cmd_cleanup_notifications(args):
    """Delete notification logs older than N days."""
    db = get_db(args)
    session = db.get_session()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    count = session.query(NotificationLog).filter(NotificationLog.sent_at < cutoff).count()

    if count == 0:
        print(f"No notifications older than {args.days} days.")
        session.close()
        return

    if not args.yes:
        answer = input(f"Delete {count} notification logs older than {args.days} days? [y/N] ")
        if answer.lower() != "y":
            print("Aborted.")
            session.close()
            return

    session.query(NotificationLog).filter(NotificationLog.sent_at < cutoff).delete()
    session.commit()
    print(f"Deleted {count} notification log entries.")
    session.close()


def cmd_export_invoices(args):
    """Export invoices to CSV or JSON."""
    db = get_db(args)
    session = db.get_session()

    invoices = session.query(Invoice).order_by(Invoice.issue_date.desc()).all()

    if not invoices:
        print("No invoices to export.")
        session.close()
        return

    columns = [
        "id", "ksef_number", "invoice_number", "invoice_type", "subject_type",
        "form_code", "issue_date", "gross_amount", "net_amount", "vat_amount",
        "currency", "seller_nip", "seller_name", "buyer_nip", "buyer_name",
        "has_xml", "has_pdf", "has_upo", "created_at",
    ]

    if args.format == "json":
        data = []
        for inv in invoices:
            row = {col: getattr(inv, col) for col in columns}
            row["created_at"] = str(row["created_at"])
            row["gross_amount"] = float(row["gross_amount"]) if row["gross_amount"] else None
            row["net_amount"] = float(row["net_amount"]) if row["net_amount"] else None
            row["vat_amount"] = float(row["vat_amount"]) if row["vat_amount"] else None
            data.append(row)

        output = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns)
        writer.writeheader()
        for inv in invoices:
            row = {col: getattr(inv, col) for col in columns}
            writer.writerow(row)
        output = buf.getvalue()

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Exported {len(invoices)} invoices to {args.output}")
    else:
        print(output)

    session.close()


def cmd_reset_errors(args):
    """Reset consecutive_errors counters in monitor_state."""
    db = get_db(args)
    session = db.get_session()

    count = session.query(MonitorState).filter(MonitorState.consecutive_errors > 0).count()
    if count == 0:
        print("No error counters to reset.")
        session.close()
        return

    if not args.yes:
        answer = input(f"Reset error counters for {count} monitor state(s)? [y/N] ")
        if answer.lower() != "y":
            print("Aborted.")
            session.close()
            return

    session.query(MonitorState).filter(MonitorState.consecutive_errors > 0).update({
        MonitorState.consecutive_errors: 0,
        MonitorState.last_error: None,
        MonitorState.last_error_at: None,
        MonitorState.status: "active",
    })
    session.commit()
    print(f"Reset error counters for {count} monitor state(s).")
    session.close()


def cmd_vacuum(args):
    """Run SQLite VACUUM to compact DB file."""
    db = get_db(args)
    before = file_size_str(str(db.db_path))

    session = db.get_session()
    session.execute(text("VACUUM"))
    session.commit()
    session.close()

    after = file_size_str(str(db.db_path))
    print(f"VACUUM complete: {before} → {after}")


def _safe_int(value):
    """Try to parse int, return -1 on failure."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return -1


# ── CLI ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="KSeF Monitor — Database Administration Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", default=_default_db_path(),
                        help="Path to SQLite database (default: auto-detect)")

    sub = parser.add_subparsers(dest="command", help="Command to run")

    # status
    sub.add_parser("status", help="Database overview: tables, counts, size")

    # invoices
    p = sub.add_parser("invoices", help="List invoices (newest first)")
    p.add_argument("--limit", "-n", type=int, default=20, help="Max rows (default: 20)")
    p.add_argument("--subject", choices=["Subject1", "Subject2"], help="Filter by subject type")
    p.add_argument("--nip", help="Filter by NIP (seller or buyer)")

    # invoice detail
    p = sub.add_parser("invoice", help="Show single invoice details")
    p.add_argument("ksef_number", help="KSeF number or DB id")

    # state
    sub.add_parser("state", help="Show monitor_state per NIP + subject")

    # notifications
    p = sub.add_parser("notifications", help="Show notification log")
    p.add_argument("--limit", "-n", type=int, default=30, help="Max rows (default: 30)")
    p.add_argument("--channel", help="Filter by channel (e.g., pushover)")
    p.add_argument("--status", choices=["sent", "failed", "skipped"], help="Filter by status")

    # stats
    sub.add_parser("stats", help="Aggregate statistics")

    # errors
    sub.add_parser("errors", help="Show recent errors")

    # search
    p = sub.add_parser("search", help="Search invoices")
    p.add_argument("query", help="Search term (ksef_number, name, NIP)")
    p.add_argument("--limit", "-n", type=int, default=20, help="Max results")

    # set-last-check
    p = sub.add_parser("set-last-check", help="Set last_check date for a NIP")
    p.add_argument("nip", help="NIP number")
    p.add_argument("datetime", help="New datetime (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)")

    # delete-last-check
    p = sub.add_parser("delete-last-check", help="Delete monitor_state for a NIP")
    p.add_argument("nip", help="NIP number")
    p.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    # delete-invoices
    p = sub.add_parser("delete-invoices", help="Delete invoices from database")
    p.add_argument("--nip", help="Filter by NIP (seller or buyer)")
    p.add_argument("--before", help="Delete invoices created before date (YYYY-MM-DD)")
    p.add_argument("--ksef-number", help="Delete specific invoice by KSeF number")
    p.add_argument("--all", action="store_true", help="Delete ALL invoices (requires confirmation)")
    p.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    # cleanup-notifications
    p = sub.add_parser("cleanup-notifications", help="Delete old notification logs")
    p.add_argument("--days", type=int, default=90, help="Delete older than N days (default: 90)")
    p.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    # export-invoices
    p = sub.add_parser("export-invoices", help="Export invoices to file")
    p.add_argument("--format", choices=["csv", "json"], default="csv", help="Output format")
    p.add_argument("--output", "-o", help="Output file path (stdout if omitted)")

    # reset-errors
    p = sub.add_parser("reset-errors", help="Reset error counters in monitor_state")
    p.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    # vacuum
    sub.add_parser("vacuum", help="SQLite VACUUM (compact DB file)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "status": cmd_status,
        "invoices": cmd_invoices,
        "invoice": cmd_invoice_detail,
        "state": cmd_state,
        "notifications": cmd_notifications,
        "stats": cmd_stats,
        "errors": cmd_errors,
        "search": cmd_search,
        "set-last-check": cmd_set_last_check,
        "delete-last-check": cmd_delete_last_check,
        "delete-invoices": cmd_delete_invoices,
        "cleanup-notifications": cmd_cleanup_notifications,
        "export-invoices": cmd_export_invoices,
        "reset-errors": cmd_reset_errors,
        "vacuum": cmd_vacuum,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
