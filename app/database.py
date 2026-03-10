"""
Database layer for KSeF Invoice Monitor.

SQLite + WAL mode + SQLAlchemy 2.0 ORM.
Phase 1 (v0.3): invoices, monitor_state, notification_log tables.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

logger = logging.getLogger(__name__)


# ── Base ────────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


# ── Models ──────────────────────────────────────────────────────────────────


class Invoice(Base):
    """Invoice metadata from KSeF API. Single source of truth."""

    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Identifiers
    ksef_number: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    invoice_number: Mapped[Optional[str]] = mapped_column(String)
    invoice_hash: Mapped[Optional[str]] = mapped_column(String)

    # Classification
    invoice_type: Mapped[Optional[str]] = mapped_column(String)
    subject_type: Mapped[str] = mapped_column(String, nullable=False)
    form_code: Mapped[Optional[str]] = mapped_column(String)

    # Dates
    issue_date: Mapped[Optional[str]] = mapped_column(String)  # DATE as text (ISO)
    invoicing_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    acquisition_date: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Amounts
    gross_amount: Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    net_amount: Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    vat_amount: Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    currency: Mapped[str] = mapped_column(String, default="PLN")

    # Seller
    seller_nip: Mapped[str] = mapped_column(String, nullable=False)
    seller_name: Mapped[Optional[str]] = mapped_column(String)

    # Buyer
    buyer_nip: Mapped[Optional[str]] = mapped_column(String)
    buyer_name: Mapped[Optional[str]] = mapped_column(String)

    # Metadata flags
    is_self_invoicing: Mapped[bool] = mapped_column(Boolean, default=False)
    has_attachment: Mapped[bool] = mapped_column(Boolean, default=False)

    # Artifact paths (relative)
    has_xml: Mapped[bool] = mapped_column(Boolean, default=False)
    has_pdf: Mapped[bool] = mapped_column(Boolean, default=False)
    has_upo: Mapped[bool] = mapped_column(Boolean, default=False)
    xml_path: Mapped[Optional[str]] = mapped_column(String)
    pdf_path: Mapped[Optional[str]] = mapped_column(String)
    upo_path: Mapped[Optional[str]] = mapped_column(String)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Raw API response (JSON text) for future enrichment
    raw_metadata: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("ix_invoices_lookup", "subject_type", "seller_nip", "issue_date"),
        Index("ix_invoices_buyer", "buyer_nip", "issue_date"),
        Index("ix_invoices_type", "invoice_type"),
        Index("ix_invoices_date", issue_date.desc()),
    )

    def __repr__(self) -> str:
        return f"<Invoice ksef={self.ksef_number!r}>"


class MonitorState(Base):
    """Replaces last_check.json. Per NIP + subject_type state."""

    __tablename__ = "monitor_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    nip: Mapped[str] = mapped_column(String, nullable=False)
    subject_type: Mapped[str] = mapped_column(String, nullable=False)

    # Timestamps
    last_check: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_invoice_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Resume support
    last_ksef_number: Mapped[Optional[str]] = mapped_column(String)

    # Stats cache
    invoices_count: Mapped[int] = mapped_column(Integer, default=0)

    # Error tracking
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    last_error_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Status
    status: Mapped[str] = mapped_column(String, default="active")

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("nip", "subject_type", name="uq_monitor_nip_subject"),
    )

    def __repr__(self) -> str:
        return f"<MonitorState nip={self.nip!r} subject={self.subject_type!r}>"


class NotificationLog(Base):
    """Notification delivery log — dedup, diagnostics, audit."""

    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[Optional[int]] = mapped_column(Integer)  # FK added in phase 2

    # What was sent
    event_type: Mapped[str] = mapped_column(String, nullable=False)  # invoice/startup/shutdown/error/test
    channel: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String)
    priority: Mapped[int] = mapped_column(Integer, default=0)

    # Delivery status
    status: Mapped[str] = mapped_column(String, default="sent")  # sent/failed/skipped
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # Timestamps
    sent_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # Dedup key
    dedup_key: Mapped[Optional[str]] = mapped_column(String)

    __table_args__ = (
        Index("ix_notif_invoice", "invoice_id"),
        Index("ix_notif_sent", sent_at.desc()),
        Index("ix_notif_dedup", "dedup_key", unique=True, sqlite_where=text("dedup_key IS NOT NULL")),
    )

    def __repr__(self) -> str:
        return f"<NotificationLog channel={self.channel!r} event={self.event_type!r}>"


# ── Engine & Session ────────────────────────────────────────────────────────


class Database:
    """Database manager — creates engine, sessions, handles init & migration."""

    def __init__(self, db_path: str = "/data/invoices.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
            echo=False,
        )

        # SQLite pragmas
        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        self.SessionLocal = sessionmaker(bind=self.engine)

        logger.info(f"Database initialized: {self.db_path}")

    def create_tables(self):
        """Create all tables (used only if Alembic is not available)."""
        Base.metadata.create_all(self.engine)
        logger.info("Database tables created")

    def get_session(self) -> Session:
        """Get a new session. Caller must close it."""
        return self.SessionLocal()

    # ── Invoice CRUD ────────────────────────────────────────────────────

    def save_invoice(self, session: Session, invoice_data: Dict[str, Any]) -> Optional[Invoice]:
        """
        Save invoice metadata. Uses INSERT OR IGNORE semantics via
        ksef_number UNIQUE constraint.

        Returns:
            Invoice instance if inserted, None if duplicate.
        """
        ksef_number = invoice_data.get("ksef_number")
        if not ksef_number:
            logger.warning("Cannot save invoice without ksef_number")
            return None

        existing = session.query(Invoice).filter_by(ksef_number=ksef_number).first()
        if existing:
            logger.debug(f"Invoice already in DB: {ksef_number}")
            return None

        invoice = Invoice(**invoice_data)
        session.add(invoice)
        session.flush()
        logger.debug(f"Invoice saved to DB: {ksef_number} (id={invoice.id})")
        return invoice

    # ── Monitor State ───────────────────────────────────────────────────

    def get_monitor_state(self, session: Session, nip: str, subject_type: str) -> Optional[MonitorState]:
        """Get monitor state for NIP + subject_type pair."""
        return (
            session.query(MonitorState)
            .filter_by(nip=nip, subject_type=subject_type)
            .first()
        )

    def update_monitor_state(
        self,
        session: Session,
        nip: str,
        subject_type: str,
        last_check: datetime,
        last_invoice_at: Optional[datetime] = None,
        last_ksef_number: Optional[str] = None,
        new_invoices: int = 0,
        error: Optional[str] = None,
    ) -> MonitorState:
        """Create or update monitor state for NIP + subject_type."""
        state = self.get_monitor_state(session, nip, subject_type)

        if state is None:
            state = MonitorState(
                nip=nip,
                subject_type=subject_type,
                last_check=last_check,
            )
            session.add(state)

        state.last_check = last_check
        state.updated_at = datetime.now(timezone.utc)

        if last_invoice_at:
            state.last_invoice_at = last_invoice_at
        if last_ksef_number:
            state.last_ksef_number = last_ksef_number
        if new_invoices > 0:
            state.invoices_count = (state.invoices_count or 0) + new_invoices

        # Error tracking
        if error:
            state.consecutive_errors = (state.consecutive_errors or 0) + 1
            state.last_error = str(error)[:500]
            state.last_error_at = datetime.now(timezone.utc)
        else:
            state.consecutive_errors = 0

        session.flush()
        return state

    # ── Notification Log ────────────────────────────────────────────────

    def log_notification(
        self,
        session: Session,
        event_type: str,
        channel: str,
        status: str = "sent",
        title: Optional[str] = None,
        priority: int = 0,
        invoice_id: Optional[int] = None,
        error_message: Optional[str] = None,
        dedup_key: Optional[str] = None,
    ) -> Optional[NotificationLog]:
        """Log a notification event. Skips if dedup_key already exists."""
        if dedup_key:
            existing = (
                session.query(NotificationLog)
                .filter_by(dedup_key=dedup_key)
                .first()
            )
            if existing:
                logger.debug(f"Notification dedup hit: {dedup_key}")
                return None

        log_entry = NotificationLog(
            event_type=event_type,
            channel=channel,
            status=status,
            title=title,
            priority=priority,
            invoice_id=invoice_id,
            error_message=error_message[:500] if error_message else None,
            dedup_key=dedup_key,
        )
        session.add(log_entry)
        session.flush()
        return log_entry

    # ── State Migration ─────────────────────────────────────────────────

    def migrate_from_json(self, json_path: Path, nip: str, subject_types: List[str]):
        """
        Migrate last_check.json → monitor_state table.
        Only runs if JSON exists AND monitor_state is empty.
        Renames JSON to .json.migrated after success.
        """
        if not json_path.exists():
            return

        session = self.get_session()
        try:
            count = session.query(MonitorState).count()
            if count > 0:
                logger.debug("monitor_state not empty — skipping JSON migration")
                return

            with open(json_path, "r", encoding="utf-8") as f:
                state = json.load(f)

            last_check_str = state.get("last_check")
            if not last_check_str:
                logger.warning("No last_check in JSON state — skipping migration")
                return

            last_check_dt = datetime.fromisoformat(last_check_str)
            if last_check_dt.tzinfo is None:
                last_check_dt = last_check_dt.replace(tzinfo=timezone.utc)

            for subject_type in subject_types:
                ms = MonitorState(
                    nip=nip,
                    subject_type=subject_type,
                    last_check=last_check_dt,
                    status="active",
                )
                session.add(ms)

            session.commit()

            # Rename old file
            migrated_path = json_path.with_suffix(".json.migrated")
            json_path.rename(migrated_path)
            logger.info(
                f"Migrated last_check.json → DB ({len(subject_types)} state entries). "
                f"Old file renamed to {migrated_path.name}"
            )

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to migrate last_check.json: {e}")
        finally:
            session.close()
