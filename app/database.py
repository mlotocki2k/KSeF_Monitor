"""
Database layer for KSeF Monitor.

SQLite + WAL mode + SQLAlchemy 2.0 ORM.
Phase 1 (v0.3): invoices, monitor_state, notification_log tables.
Phase 2 (v0.4): api_request_log, invoice_artifacts tables.
Phase 3 (v0.5): push_instances table.
Phase 4 (v0.5): initial_load_jobs table.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
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

    # Source tracking (v0.4)
    source: Mapped[Optional[str]] = mapped_column(String, default="polling")

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


class ApiRequestLog(Base):
    """Log of KSeF Monitor API requests — for rate limiting diagnostics and stats.

    Only stores technical metadata (endpoint, status, timing).
    No request/response bodies — they may contain tokens or invoice data.
    """

    __tablename__ = "api_request_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    nip: Mapped[Optional[str]] = mapped_column(String)

    status_code: Mapped[Optional[int]] = mapped_column(Integer)
    response_time_ms: Mapped[Optional[float]] = mapped_column(Float)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    invoices_returned: Mapped[Optional[int]] = mapped_column(Integer)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("ix_api_log_requested", requested_at.desc()),
        Index("ix_api_log_endpoint", "endpoint", "status_code"),
    )

    def __repr__(self) -> str:
        return f"<ApiRequestLog {self.method} {self.endpoint} status={self.status_code}>"


class InvoiceArtifact(Base):
    """Tracks download status of invoice artifacts (XML, PDF).

    Supports resumable downloads: pending artifacts can be retried
    in subsequent check cycles without re-downloading completed ones.
    """

    __tablename__ = "invoice_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    invoice_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("invoices.id"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # xml, pdf, upo

    # Status: pending -> downloaded | failed | skipped
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    download_attempts: Mapped[int] = mapped_column(Integer, default=0)

    # File info (populated on successful download)
    file_path: Mapped[Optional[str]] = mapped_column(String)
    file_hash: Mapped[Optional[str]] = mapped_column(String)  # SHA-256
    file_size: Mapped[Optional[int]] = mapped_column(Integer)

    # Error tracking
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("invoice_id", "artifact_type", name="uq_artifact_invoice_type"),
        Index("ix_artifact_status", "status"),
        Index("ix_artifact_invoice", "invoice_id"),
    )

    def __repr__(self) -> str:
        return f"<InvoiceArtifact invoice_id={self.invoice_id} type={self.artifact_type!r} status={self.status!r}>"


class PushInstance(Base):
    """Push notification instance credentials for iOS pairing.

    Stores instance_id, instance_key, pairing_code for Central Push Service
    registration. Designed for multi-instance support (one row per NIP or
    monitoring scope).
    """

    __tablename__ = "push_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    instance_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    instance_key: Mapped[str] = mapped_column(String, nullable=False)
    pairing_code: Mapped[str] = mapped_column(String, nullable=False)
    central_push_url: Mapped[str] = mapped_column(
        String, nullable=False, default="https://push.monitorksef.com"
    )
    registered_at: Mapped[Optional[str]] = mapped_column(String)

    # For future multi-instance: link to NIP or scope
    label: Mapped[Optional[str]] = mapped_column(String)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<PushInstance id={self.instance_id!r} label={self.label!r}>"


class InitialLoadJob(Base):
    """Tracks historical invoice import jobs using the /invoices/exports async API.

    Each job covers a date range split into ≤90-day windows per subject_type.
    Supports resume: current_window_from/to + current_subject_type allow restart
    after interruption without re-importing already-processed windows.

    Status flow: pending → running → completed | failed | cancelled
    """

    __tablename__ = "initial_load_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # Job config (immutable after creation)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    subject_types: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    date_type: Mapped[str] = mapped_column(String, nullable=False, default="Invoicing")
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Resume state (updated as windows are processed)
    current_window_from: Mapped[Optional[datetime]] = mapped_column(DateTime)
    current_window_to: Mapped[Optional[datetime]] = mapped_column(DateTime)
    current_subject_type: Mapped[Optional[str]] = mapped_column(String)

    # Progress counters
    windows_total: Mapped[int] = mapped_column(Integer, default=0)
    windows_completed: Mapped[int] = mapped_column(Integer, default=0)
    invoices_imported: Mapped[int] = mapped_column(Integer, default=0)
    invoices_skipped: Mapped[int] = mapped_column(Integer, default=0)

    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_initial_load_jobs_status", "status"),
        Index("ix_initial_load_jobs_created", created_at.desc()),
    )

    def __repr__(self) -> str:
        return f"<InitialLoadJob id={self.id!r} status={self.status!r}>"


# Phase 8 (v0.5.3 hotfix): per-window log for initial load jobs.
# Surfaces success/failure of each date-range chunk to the GUI so the
# operator no longer has to grep stderr to diagnose partial imports.


class InitialLoadWindow(Base):
    """One row per processed window of an InitialLoadJob."""

    __tablename__ = "initial_load_windows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("initial_load_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)  # success | failed
    imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        Index("ix_initial_load_windows_job_created", "job_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<InitialLoadWindow job={self.job_id[:8]} {self.subject_type} "
            f"[{self.window_start.date()}→{self.window_end.date()}] {self.status}>"
        )


# Phase 5 (v0.5.1): UI user accounts + sessions (V5-13).
# Self-hosted-style auth — no SSH/CLI needed for first-run, web setup wizard.


class UiUser(Base):
    """Browser-UI user account. Distinct from `api.auth_token` (Bearer key for
    integrations). Created via /ui/setup wizard on first launch."""

    __tablename__ = "ui_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)  # bcrypt
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    __table_args__ = (
        Index("ix_ui_users_username", "username", unique=True),
    )

    def __repr__(self) -> str:
        return f"<UiUser id={self.id} username={self.username!r}>"


class UiLoginAttempt(Base):
    """Per-username failed-login counter + temporary lockout (V5-13 → U-03).

    Distinct from per-IP rate limit (slowapi `5/minute`) — keyed by username
    so a botnet rotating IPs cannot bypass the lockout. Lockout is always
    time-bounded (15 min) to keep DoS-via-lockout impact bounded; sliding
    window auto-resets the counter when no fails arrived in the last window.
    """

    __tablename__ = "ui_login_attempts"

    username: Mapped[str] = mapped_column(String(64), primary_key=True)
    failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    def __repr__(self) -> str:
        return (
            f"<UiLoginAttempt user={self.username!r} fails={self.failed_count}"
            f" locked_until={self.locked_until}>"
        )


class UiSession(Base):
    """Browser session — opaque random ID stored in HttpOnly cookie. Decoupled
    from password_hash so password change can revoke other sessions cleanly."""

    __tablename__ = "ui_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # uuid4 hex
    user_id: Mapped[int] = mapped_column(
        ForeignKey("ui_users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    # SHA-256 of User-Agent at session creation (U-04). Nullable: only
    # populated when api.session_strict_binding is enabled. Stored as hash,
    # not raw UA, so a leaked DB doesn't expose the user's browser fingerprint.
    ua_hash: Mapped[Optional[str]] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_ui_sessions_user", "user_id"),
        Index("ix_ui_sessions_expires", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<UiSession id={self.id[:8]}… user_id={self.user_id}>"


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
        """Ensure the DB schema exists and is tracked by alembic.

        Runs `Base.metadata.create_all` for pristine DBs, then delegates to
        `_migrate_schema` which invokes alembic (stamp-at-head or upgrade).
        """
        Base.metadata.create_all(self.engine)
        self._migrate_schema()
        logger.info("Database tables created")

    def _migrate_schema(self):
        """Apply alembic migrations to bring DB schema to head (v0.4 F-07).

        Previously built ALTER TABLE statements via f-string interpolation —
        an anti-pattern flagged as F-07.  Now delegates to alembic, which is a
        hard dependency of this project.

        Strategy:
        - If tables already exist but alembic_version is absent (fresh install
          bootstrapped by create_all), stamp to head so future upgrades work.
        - Otherwise run upgrade(head) normally (e.g. incremental production
          upgrade, or the very first run with no tables at all).

        NOTE for existing production DBs created before v0.5:
        Those DBs have no alembic_version row.  This code will stamp them at
        head rather than replaying migrations.  If columns added by intermediate
        migrations are missing, the operator must run:
            alembic stamp <known-revision>
            alembic upgrade head
        manually.
        """
        try:
            from alembic import command
            from alembic.config import Config
            from sqlalchemy import inspect as sa_inspect
        except ImportError:
            logger.error("alembic not installed — schema may be out of date")
            return

        try:
            project_root = Path(__file__).resolve().parent.parent
            alembic_cfg = Config(str(project_root / "alembic.ini"))
            # Override sqlalchemy.url so each Database instance (e.g. test
            # fixtures using tmp_path) targets the correct file.
            alembic_cfg.set_main_option(
                "sqlalchemy.url", f"sqlite:///{self.db_path}"
            )

            inspector = sa_inspect(self.engine)
            table_names = inspector.get_table_names()
            has_tables = bool(table_names)
            has_alembic_version = "alembic_version" in table_names

            if has_tables and not has_alembic_version:
                # create_all already built the latest schema; just stamp so
                # alembic knows the DB is at head.
                # WARN: for v0.4→v0.5 upgrades on existing prod DBs, this skips
                # column-level migrations from phases 1-4. Operator must run
                # `alembic stamp <known-rev>; alembic upgrade head` manually
                # BEFORE this code path runs.
                non_alembic_tables = {t for t in table_names if t != "alembic_version"}
                if non_alembic_tables - set(Base.metadata.tables.keys()):
                    logger.warning(
                        "Detected unknown tables %s in DB without alembic_version — "
                        "possible stale schema. Stamping at head may skip needed "
                        "migrations; review 'alembic stamp' docs before upgrading.",
                        non_alembic_tables - set(Base.metadata.tables.keys()),
                    )
                command.stamp(alembic_cfg, "head")
                logger.info("Alembic version stamped to head (fresh DB)")
            else:
                # Either a pristine DB with no tables (alembic creates them)
                # or an existing tracked DB that needs incremental upgrades.
                command.upgrade(alembic_cfg, "head")
                logger.info("Alembic upgrade to head complete")
        except Exception as e:
            logger.error("Alembic migration failed: %s", e)
            # create_all already put the tables in place, so the app can still
            # start; schema drift is possible for incremental upgrades.

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

    # ── API Request Log ────────────────────────────────────────────────

    def log_api_request(
        self,
        session: Session,
        endpoint: str,
        method: str,
        nip: Optional[str] = None,
        status_code: Optional[int] = None,
        response_time_ms: Optional[float] = None,
        retry_count: int = 0,
        invoices_returned: Optional[int] = None,
    ) -> ApiRequestLog:
        """Log a KSeF API request for diagnostics and rate limit monitoring."""
        entry = ApiRequestLog(
            endpoint=endpoint[:200],
            method=method[:10],
            nip=nip,
            status_code=status_code,
            response_time_ms=response_time_ms,
            retry_count=retry_count,
            invoices_returned=invoices_returned,
        )
        session.add(entry)
        session.flush()
        return entry

    def get_api_stats(self, session: Session, hours: int = 1) -> Dict[str, Any]:
        """Get API request statistics for the last N hours."""
        cutoff = datetime.now(timezone.utc)
        from datetime import timedelta
        cutoff = cutoff - timedelta(hours=hours)

        rows = (
            session.query(ApiRequestLog)
            .filter(ApiRequestLog.requested_at >= cutoff)
            .all()
        )

        total = len(rows)
        errors = sum(1 for r in rows if r.status_code and r.status_code >= 400)
        avg_time = (
            sum(r.response_time_ms for r in rows if r.response_time_ms) / total
            if total > 0
            else 0.0
        )

        return {
            "total_requests": total,
            "error_count": errors,
            "avg_response_time_ms": round(avg_time, 1),
            "period_hours": hours,
        }

    # ── Invoice Artifacts ────────────────────────────────────────────────

    def create_artifact(
        self,
        session: Session,
        invoice_id: int,
        artifact_type: str,
        status: str = "pending",
    ) -> Optional[InvoiceArtifact]:
        """Create an artifact record. Returns None if already exists (UNIQUE constraint)."""
        existing = (
            session.query(InvoiceArtifact)
            .filter_by(invoice_id=invoice_id, artifact_type=artifact_type)
            .first()
        )
        if existing:
            return None

        artifact = InvoiceArtifact(
            invoice_id=invoice_id,
            artifact_type=artifact_type,
            status=status,
        )
        session.add(artifact)
        session.flush()
        return artifact

    def mark_artifact_downloaded(
        self,
        session: Session,
        invoice_id: int,
        artifact_type: str,
        file_path: str,
        file_hash: Optional[str] = None,
        file_size: Optional[int] = None,
    ) -> Optional[InvoiceArtifact]:
        """Mark an artifact as successfully downloaded."""
        artifact = (
            session.query(InvoiceArtifact)
            .filter_by(invoice_id=invoice_id, artifact_type=artifact_type)
            .first()
        )
        if not artifact:
            return None

        artifact.status = "downloaded"
        artifact.file_path = file_path
        artifact.file_hash = file_hash
        artifact.file_size = file_size
        artifact.download_attempts = (artifact.download_attempts or 0) + 1
        artifact.updated_at = datetime.now(timezone.utc)
        session.flush()
        return artifact

    def mark_artifact_failed(
        self,
        session: Session,
        invoice_id: int,
        artifact_type: str,
        error: str,
    ) -> Optional[InvoiceArtifact]:
        """Mark an artifact download as failed."""
        artifact = (
            session.query(InvoiceArtifact)
            .filter_by(invoice_id=invoice_id, artifact_type=artifact_type)
            .first()
        )
        if not artifact:
            return None

        artifact.status = "failed"
        artifact.download_attempts = (artifact.download_attempts or 0) + 1
        artifact.last_error = str(error)[:500]
        artifact.updated_at = datetime.now(timezone.utc)
        session.flush()
        return artifact

    def get_pending_artifacts(
        self, session: Session, limit: int = 50
    ) -> List[InvoiceArtifact]:
        """Get artifacts that need downloading, ordered by creation time."""
        return (
            session.query(InvoiceArtifact)
            .filter(InvoiceArtifact.status.in_(["pending", "failed"]))
            .filter(InvoiceArtifact.download_attempts < 3)
            .order_by(InvoiceArtifact.created_at)
            .limit(limit)
            .all()
        )

    # ── Push Instances ────────────────────────────────────────────────

    def get_push_instance(self, session: Session, label: Optional[str] = None) -> Optional[PushInstance]:
        """Get push instance by label (None = default instance)."""
        return (
            session.query(PushInstance)
            .filter_by(label=label)
            .first()
        )

    def save_push_instance(
        self,
        session: Session,
        instance_id: str,
        instance_key: str,
        pairing_code: str,
        central_push_url: str,
        registered_at: Optional[str] = None,
        label: Optional[str] = None,
    ) -> PushInstance:
        """Create or update push instance credentials."""
        existing = self.get_push_instance(session, label=label)
        if existing:
            existing.instance_id = instance_id
            existing.instance_key = instance_key
            existing.pairing_code = pairing_code
            existing.central_push_url = central_push_url
            existing.registered_at = registered_at
            existing.updated_at = datetime.now(timezone.utc)
            session.flush()
            return existing

        instance = PushInstance(
            instance_id=instance_id,
            instance_key=instance_key,
            pairing_code=pairing_code,
            central_push_url=central_push_url,
            registered_at=registered_at,
            label=label,
        )
        session.add(instance)
        session.flush()
        return instance

    def update_push_pairing_code(
        self, session: Session, pairing_code: str, label: Optional[str] = None
    ) -> Optional[PushInstance]:
        """Update pairing code for existing push instance."""
        instance = self.get_push_instance(session, label=label)
        if not instance:
            return None
        instance.pairing_code = pairing_code
        instance.updated_at = datetime.now(timezone.utc)
        session.flush()
        return instance

    def delete_push_instance(self, session: Session, label: Optional[str] = None) -> bool:
        """Delete push instance by label (None = default). Returns True if deleted."""
        instance = self.get_push_instance(session, label=label)
        if not instance:
            return False
        session.delete(instance)
        session.flush()
        return True

    # ── Initial Load Jobs ────────────────────────────────────────────────

    def create_initial_load_job(
        self,
        session: Session,
        subject_types: List[str],
        start_date: datetime,
        end_date: datetime,
        date_type: str = "Invoicing",
        windows_total: int = 0,
    ) -> "InitialLoadJob":
        """Create a new initial load job in pending state."""
        job = InitialLoadJob(
            subject_types=json.dumps(subject_types),
            start_date=start_date,
            end_date=end_date,
            date_type=date_type,
            windows_total=windows_total,
        )
        session.add(job)
        session.flush()
        logger.info("Created initial load job %s (%d windows)", job.id, windows_total)
        return job

    def get_initial_load_job(self, session: Session, job_id: str) -> Optional["InitialLoadJob"]:
        """Get job by ID."""
        return session.query(InitialLoadJob).filter_by(id=job_id).first()

    def get_active_initial_load_job(self, session: Session) -> Optional["InitialLoadJob"]:
        """Get the currently running or pending job (at most one at a time)."""
        return (
            session.query(InitialLoadJob)
            .filter(InitialLoadJob.status.in_(["pending", "running"]))
            .order_by(InitialLoadJob.created_at.desc())
            .first()
        )

    def get_latest_initial_load_job(self, session: Session) -> Optional["InitialLoadJob"]:
        """Get most recently created job regardless of status."""
        return (
            session.query(InitialLoadJob)
            .order_by(InitialLoadJob.created_at.desc())
            .first()
        )

    def update_initial_load_progress(
        self,
        session: Session,
        job_id: str,
        status: Optional[str] = None,
        current_window_from: Optional[datetime] = None,
        current_window_to: Optional[datetime] = None,
        current_subject_type: Optional[str] = None,
        windows_completed_delta: int = 0,
        invoices_imported_delta: int = 0,
        invoices_skipped_delta: int = 0,
        error_message: Optional[str] = None,
    ) -> Optional["InitialLoadJob"]:
        """Update job progress after processing a window."""
        job = self.get_initial_load_job(session, job_id)
        if not job:
            return None

        if status is not None:
            job.status = status
        if current_window_from is not None:
            job.current_window_from = current_window_from
        if current_window_to is not None:
            job.current_window_to = current_window_to
        if current_subject_type is not None:
            job.current_subject_type = current_subject_type
        if windows_completed_delta:
            job.windows_completed = (job.windows_completed or 0) + windows_completed_delta
        if invoices_imported_delta:
            job.invoices_imported = (job.invoices_imported or 0) + invoices_imported_delta
        if invoices_skipped_delta:
            job.invoices_skipped = (job.invoices_skipped or 0) + invoices_skipped_delta
        if error_message is not None:
            job.error_message = str(error_message)[:1000]

        job.updated_at = datetime.now(timezone.utc)
        session.flush()
        return job

    def cancel_initial_load_job(self, session: Session, job_id: str) -> Optional["InitialLoadJob"]:
        """Cancel a pending or running job."""
        job = self.get_initial_load_job(session, job_id)
        if not job or job.status not in ("pending", "running"):
            return None
        job.status = "cancelled"
        job.updated_at = datetime.now(timezone.utc)
        session.flush()
        logger.info("Cancelled initial load job %s", job_id)
        return job

    # ── Initial-load window log (phase 8) ───────────────────────────────

    def record_initial_load_window(
        self,
        session: Session,
        job_id: str,
        subject_type: str,
        window_start: datetime,
        window_end: datetime,
        status: str,
        imported: int = 0,
        skipped: int = 0,
        error_message: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> "InitialLoadWindow":
        """Append a row to initial_load_windows. status is 'success' | 'failed'."""
        row = InitialLoadWindow(
            job_id=job_id,
            subject_type=subject_type,
            window_start=window_start,
            window_end=window_end,
            status=status,
            imported=imported,
            skipped=skipped,
            error_message=str(error_message)[:1000] if error_message else None,
            duration_ms=duration_ms,
        )
        session.add(row)
        session.flush()
        return row

    def list_initial_load_windows(
        self, session: Session, job_id: str, limit: int = 500,
    ) -> List["InitialLoadWindow"]:
        """Return windows for a job, oldest first."""
        return (
            session.query(InitialLoadWindow)
            .filter(InitialLoadWindow.job_id == job_id)
            .order_by(InitialLoadWindow.created_at.asc())
            .limit(limit)
            .all()
        )

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
