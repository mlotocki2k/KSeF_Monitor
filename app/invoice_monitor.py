"""
Invoice Monitor Service
Main service that coordinates KSeF API polling and notifications
"""

import json
import hashlib
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .scheduler import Scheduler
from .notifiers import NotificationManager
from .invoice_pdf_generator import generate_invoice_pdf, REPORTLAB_AVAILABLE
from .invoice_xml_parser import detect_schema_type, SCHEMA_TYPE_UNKNOWN
from .database import Database, Invoice, InvoiceArtifact

# Optional timezone support
try:
    import pytz
    PYTZ_AVAILABLE = True
except ImportError:
    PYTZ_AVAILABLE = False

logger = logging.getLogger(__name__)


class InvoiceMonitor:
    """Main invoice monitoring service"""

    SUBJECT_TYPE_TITLES = {
        "Subject1": "Nowa faktura sprzedażowa w KSeF",
        "Subject2": "Nowa faktura zakupowa w KSeF",
    }
    DEFAULT_TITLE = "Nowa faktura w KSeF"

    # KSeF API maximum dateRange is 3 months (90 days)
    MAX_DATE_RANGE_DAYS = 90

    def __init__(self, config, ksef_client, notification_manager, prometheus_metrics=None, database=None):
        """
        Initialize invoice monitor

        Args:
            config: ConfigManager instance
            ksef_client: KSeFClient instance
            notification_manager: NotificationManager instance
            prometheus_metrics: PrometheusMetrics instance (optional)
            database: Database instance (optional, enables DB persistence)
        """
        self.config = config
        self.ksef = ksef_client
        self.notifier = notification_manager
        self.metrics = prometheus_metrics
        self.db = database
        self.state_file = Path("/data/last_check.json")
        self.subject_types = config.get("monitoring", "subject_types") or ["Subject1"]
        self.nip = config.get("ksef", "nip") or ""

        # Storage settings
        self.save_xml = config.get("storage", "save_xml", default=False)
        self.save_pdf = config.get("storage", "save_pdf", default=False)
        # Lightweight Polling (v0.6): gdy True, detekcja tylko kolejkuje artefakty
        # jako pending; pobranie XML/PDF dzieje się w osobnej fazie
        # process_pending_artifacts(). Domyślnie inline — bez zmiany zachowania
        # istniejących wdrożeń. Wymaga bazy danych (DB).
        self.lazy_artifacts = bool(config.get("monitoring", "lazy_artifacts", default=False))
        self.artifact_batch_size = config.get("monitoring", "artifact_batch_size", default=50)
        # UPO (Urzędowe Poświadczenie Odbioru) — pobieranie dla faktur sprzedażowych
        # (Subject1). Wymaga tokenu z uprawnieniem Introspection. Opt-in, osobny budżet API.
        self.fetch_upo = bool(config.get("monitoring", "fetch_upo", default=False))
        self._session_invoice_map = None     # cache: ksefNumber -> sessionReference
        self._session_map_ts = 0.0           # czas ostatniego zbudowania mapy
        self._session_map_ttl = 24 * 3600    # TTL cache mapy sesji (24h)
        output_dir = config.get("storage", "output_dir", default="/data/invoices")
        self.output_dir = Path(output_dir)
        self.folder_structure = config.get("storage", "folder_structure", default="")
        self.file_exists_strategy = config.get("storage", "file_exists_strategy", default="skip")
        self.file_name_pattern = config.get("storage", "file_name_pattern", default="{type}_{date}_{invoice_number}")

        # Get timezone from config
        if PYTZ_AVAILABLE:
            self.timezone = config.get_timezone_object()
        else:
            logger.warning("pytz not available - timezone support disabled, using system timezone")
            self.timezone = None

        # Get message priority from notifications section (with fallback to monitoring for backwards compatibility)
        notifications_config = config.get("notifications") or {}
        message_priority = notifications_config.get("message_priority")
        if message_priority is None:
            message_priority = config.get("monitoring", "message_priority", default=0)

        if not isinstance(message_priority, int) or message_priority not in range(-2, 3):
            logger.warning(f"Invalid message_priority '{message_priority}', falling back to 0")
            message_priority = 0
        self.message_priority = message_priority

        # Initialize scheduler with new flexible scheduling system
        schedule_config = config.get("schedule")
        if not schedule_config:
            # Fallback to old check_interval for backwards compatibility
            check_interval = config.get("monitoring", "check_interval")
            if check_interval:
                logger.warning("Using deprecated 'check_interval' - please migrate to 'schedule' configuration")
                schedule_config = {"mode": "simple", "interval": check_interval}
            else:
                logger.warning("No schedule configuration found, using default: 5 minutes")
                schedule_config = {"mode": "minutes", "interval": 5}

        self.scheduler = Scheduler(schedule_config)
        self._manual_trigger = False

        logger.info(f"Invoice Monitor initialized, subject_types: {self.subject_types}, message_priority: {self.message_priority}")

    def _get_now(self) -> datetime:
        """
        Get current datetime in configured timezone

        Returns:
            Timezone-aware datetime object, or naive datetime if pytz not available
        """
        if self.timezone:
            return datetime.now(self.timezone)
        else:
            return datetime.now()

    def _parse_datetime(self, date_string: str) -> datetime:
        """
        Parse datetime string and convert to configured timezone

        Args:
            date_string: ISO format datetime string

        Returns:
            Timezone-aware datetime object in configured timezone
        """
        try:
            dt = datetime.fromisoformat(date_string)

            # If datetime is naive, assume it's in configured timezone
            if dt.tzinfo is None and self.timezone:
                logger.warning(
                    "Naive datetime '%s' in state file — localizing to %s. "
                    "KSeF API v2.2.0/v2.3.0 interprets naive dates as Europe/Warsaw.",
                    date_string, self.timezone
                )
                dt = self.timezone.localize(dt)
            # If datetime has timezone info and we have a configured timezone, convert to it
            elif dt.tzinfo is not None and self.timezone:
                dt = dt.astimezone(self.timezone)

            return dt
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse datetime '{date_string}': {e}")
            raise

    def _cap_date_from(self, date_from: datetime, now: datetime) -> datetime:
        """
        Cap date_from to now - MAX_DATE_RANGE_DAYS.

        KSeF API v2.2.0/v2.3.0 limits dateRange to 3 months. If date_from is older,
        cap it and log a warning about the skipped period.

        Range is inclusive on both ends, so 90 days = (now - date_from).days + 1.
        Subtract MAX-1 to keep the window at the limit, not 1 day past it.
        """
        max_lookback = now - timedelta(days=self.MAX_DATE_RANGE_DAYS - 1)

        if date_from < max_lookback:
            skipped_days = (max_lookback - date_from).days
            logger.warning(
                "last_check is %d days old (%s) — exceeds KSeF API 3-month limit. "
                "Capping date_from to %s. Invoices from the skipped period "
                "(%d days) will NOT be fetched.",
                (now - date_from).days,
                date_from.isoformat(),
                max_lookback.isoformat(),
                skipped_days
            )
            return max_lookback

        return date_from

    # TTL for seen_invoices entries (90 days)
    SEEN_INVOICES_TTL_DAYS = 90

    def load_state(self) -> Dict:
        """
        Load last check state from file.
        Filters out seen_invoices entries older than TTL.
        Handles backward compatibility with old string-only format.

        Returns:
            State dictionary containing last_check timestamp and seen_invoices list
        """
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)

                    # Filter seen_invoices by TTL and migrate old format
                    raw_seen = state.get("seen_invoices", [])
                    cutoff = (datetime.now(timezone.utc) - timedelta(days=self.SEEN_INVOICES_TTL_DAYS)).isoformat()
                    filtered = []
                    for entry in raw_seen:
                        if isinstance(entry, dict) and "h" in entry:
                            # New format: {"h": "sha256...", "ts": "ISO"}
                            if entry.get("ts", "") >= cutoff:
                                filtered.append(entry)
                        # else: old MD5 string format — discard (one-time re-download)
                    state["seen_invoices"] = filtered

                    logger.debug(f"Loaded state: last_check={state.get('last_check')}, "
                               f"seen_invoices={len(filtered)}")
                    return state
        except Exception as e:
            logger.error(f"Failed to load state: {e}")

        return {
            "last_check": None,
            "seen_invoices": []
        }
    
    def save_state(self, state: Dict):
        """
        Save current state to file using atomic write.

        Writes to a temporary file first, then renames to avoid data loss
        if the process is killed mid-write (docker stop, OOM, etc.).

        Args:
            state: State dictionary to save
        """
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = self.state_file.with_suffix('.tmp')
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            tmp_file.rename(self.state_file)
            logger.debug("State saved successfully")
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    def get_invoice_id_hash(self, invoice: Dict) -> str:
        """
        Generate SHA-256 hash for invoice deduplication.
        Uses ksefReferenceNumber as primary key (unique KSeF identifier),
        falls back to ksefNumber if not available.

        Args:
            invoice: Invoice metadata dictionary

        Returns:
            SHA-256 hex digest string
        """
        ksef_ref = invoice.get('ksefReferenceNumber') or invoice.get('ksefNumber', '')
        return hashlib.sha256(ksef_ref.encode()).hexdigest()
    
    def check_for_new_invoices(self):
        """
        Check for new invoices and send notifications.
        Sends one query per subject_type (API accepts only one at a time).
        All dates use configured timezone (default: Europe/Warsaw).

        When database is available:
        - Reads last_check from monitor_state (per NIP + subject_type)
        - Saves invoice metadata to invoices table (dedup by ksef_number)
        - Updates monitor_state after each subject_type pass
        Falls back to JSON state file when DB is not available.
        """
        now = self._get_now()
        use_db = self.db is not None
        db_session = self.db.get_session() if use_db else None

        # Load JSON state only when DB is not active (fallback mode)
        state = {} if use_db else self.load_state()
        found_any = False
        new_invoices_count = {}

        # JSON-based dedup — only used when DB is not available
        seen_entries = state.get("seen_invoices", []) if not use_db else []
        seen_hashes = {e["h"] for e in seen_entries if isinstance(e, dict)} if not use_db else set()

        try:
            for subject_type in self.subject_types:
                new_count, last_ksef_number = self._poll_subject_type(
                    subject_type, db_session, state, seen_hashes, seen_entries, now
                )

                if new_count > 0:
                    found_any = True
                    new_invoices_count[subject_type] = new_count

                # Update monitor_state in DB
                if use_db:
                    self.db.update_monitor_state(
                        session=db_session,
                        nip=self.nip,
                        subject_type=subject_type,
                        last_check=now,
                        last_ksef_number=last_ksef_number,
                        new_invoices=new_count,
                    )

            # Commit DB transaction
            if use_db:
                db_session.commit()

        except Exception:
            if db_session:
                db_session.rollback()
            raise
        finally:
            if db_session:
                db_session.close()

        if not found_any:
            logger.info("No new invoices found")

        self._finalize_check_cycle(use_db, state, seen_entries, now, new_invoices_count)

    def _poll_subject_type(self, subject_type: str, db_session, json_state: Dict,
                           seen_hashes: set, seen_entries: list,
                           now: datetime) -> tuple:
        """Poll KSeF API for a single subject_type and process new invoices.

        Returns:
            Tuple of (new_count, last_ksef_number)
        """
        use_db = db_session is not None
        date_from = self._get_date_from(db_session, subject_type, json_state, now)
        date_to = now

        # Cap date_from to max 90 days back (KSeF API 3-month limit)
        date_from = self._cap_date_from(date_from, now)

        invoices = self.ksef.get_invoices_metadata(date_from, date_to, subject_type)
        new_count = 0
        last_ksef_number = None

        for invoice in invoices:
            ksef_number = invoice.get('ksefNumber', '')

            if not self._is_new_invoice(ksef_number, invoice, use_db, db_session,
                                        seen_hashes, seen_entries, now):
                continue

            new_count += 1
            last_ksef_number = ksef_number

            self._process_new_invoice(invoice, subject_type, use_db, db_session)

        return new_count, last_ksef_number

    def _is_new_invoice(self, ksef_number: str, invoice: Dict, use_db: bool,
                        db_session, seen_hashes: set, seen_entries: list,
                        now: datetime) -> bool:
        """Check if invoice is new (not seen before). Updates dedup state."""
        if use_db:
            existing = db_session.query(Invoice).filter_by(ksef_number=ksef_number).first()
            return existing is None
        else:
            invoice_hash = self.get_invoice_id_hash(invoice)
            if invoice_hash in seen_hashes:
                return False
            seen_hashes.add(invoice_hash)
            seen_entries.append({"h": invoice_hash, "ts": now.isoformat()})
            return True

    def _process_new_invoice(self, invoice: Dict, subject_type: str,
                             use_db: bool, db_session) -> None:
        """Save invoice to DB, send notification, and save artifacts."""
        ksef_number = invoice.get('ksefNumber', '')

        # Save to DB
        invoice_id = None
        if use_db:
            invoice_id = self._save_invoice_to_db(db_session, invoice, subject_type)

        # Send notification
        context = self.build_template_context(invoice, subject_type)
        context["_invoice_id"] = invoice_id  # for notification_log
        success = self.notifier.send_invoice_notification(context)

        safe_ksef_log = str(ksef_number or 'N/A').replace('\n', ' ').replace('\r', ' ')
        if success:
            logger.info("Notification sent [%s] invoice: %s", subject_type, safe_ksef_log)
        else:
            logger.warning("Failed to send notification [%s] invoice: %s", subject_type, safe_ksef_log)

        # Save invoice artifacts (PDF, XML).
        # Lightweight Polling: w trybie lazy detekcja tylko rejestruje artefakty jako
        # pending (Faza 1); faktyczne pobranie XML/PDF dzieje się w
        # process_pending_artifacts() (Faza 2). Wymaga DB; inaczej fallback na inline.
        # Rate limiting jest egzekwowany globalnie przez RateLimiter w ksef_client.
        if self.lazy_artifacts and use_db and invoice_id and (self.save_xml or self.save_pdf):
            self._enqueue_artifacts(db_session, invoice_id)
        else:
            self._save_invoice_artifacts(invoice, subject_type, invoice_id=invoice_id, db_session=db_session)

    def _enqueue_artifacts(self, db_session, invoice_id: int) -> None:
        """Faza 1 (lazy): zarejestruj artefakty jako pending — pobranie w Fazie 2."""
        if self.db is None:
            return
        if self.save_xml:
            self.db.create_artifact(db_session, invoice_id, "xml", status="pending")
        if self.save_pdf:
            self.db.create_artifact(db_session, invoice_id, "pdf", status="pending")

    def _mark_remaining_pending_failed(self, db_session, invoice_id: int, reason: str,
                                       types=("xml", "pdf")) -> None:
        """Oznacz jako failed artefakty faktury, które po próbie wciąż są 'pending'.

        Zwiększa licznik prób (`download_attempts`), dzięki czemu
        `get_pending_artifacts` przestanie je zwracać po 3 nieudanych próbach.
        `types` ogranicza działanie do wybranych typów (UPO ma osobny przebieg).
        """
        pending = (
            db_session.query(InvoiceArtifact)
            .filter_by(invoice_id=invoice_id, status="pending")
            .filter(InvoiceArtifact.artifact_type.in_(types))
            .all()
        )
        for art in pending:
            self.db.mark_artifact_failed(db_session, invoice_id, art.artifact_type, reason)

    def process_pending_artifacts(self, limit: Optional[int] = None) -> int:
        """Faza 2 (lazy artifacts): pobierz XML/PDF dla zakolejkowanych faktur.

        Grupuje pending artefakty per faktura i pobiera je raz na fakturę
        (`_save_invoice_artifacts` pobiera XML i generuje PDF w jednym kroku).
        Limity KSeF API są egzekwowane globalnie przez RateLimiter w ksef_client.

        Returns:
            Liczba faktur, dla których udało się pobrać artefakty.
        """
        if self.db is None:
            return 0

        limit = limit if limit is not None else self.artifact_batch_size
        processed = 0
        session = self.db.get_session()
        try:
            pending = self.db.get_pending_artifacts(session, limit=limit)
            # UPO ma osobny przebieg (process_pending_upo) — tu tylko XML/PDF.
            pending = [a for a in pending if a.artifact_type in ("xml", "pdf")]
            if not pending:
                return 0

            # Grupuj per faktura, zachowując kolejność (created_at z get_pending_artifacts)
            invoice_ids = []
            seen = set()
            for art in pending:
                if art.invoice_id not in seen:
                    seen.add(art.invoice_id)
                    invoice_ids.append(art.invoice_id)

            for invoice_id in invoice_ids:
                inv = session.query(Invoice).filter_by(id=invoice_id).first()
                if inv is None or not inv.raw_metadata:
                    logger.warning(
                        "Pending artifacts: brak raw_metadata dla invoice_id=%s — pomijam",
                        invoice_id,
                    )
                    self._mark_remaining_pending_failed(session, invoice_id, "missing raw_metadata")
                    continue

                try:
                    invoice = json.loads(inv.raw_metadata)
                except (ValueError, TypeError) as e:
                    logger.error(
                        "Pending artifacts: nieprawidłowy raw_metadata dla invoice_id=%s: %s",
                        invoice_id, e,
                    )
                    self._mark_remaining_pending_failed(session, invoice_id, "invalid raw_metadata")
                    continue

                subject_type = inv.subject_type or self.subject_types[0]
                try:
                    self._save_invoice_artifacts(
                        invoice, subject_type, invoice_id=invoice_id, db_session=session
                    )
                    processed += 1
                except Exception as e:
                    logger.error(
                        "Pending artifacts: pobranie nie powiodło się dla invoice_id=%s: %s",
                        invoice_id, e,
                    )

                # Cokolwiek nie zostało pobrane (np. fetch XML zwrócił None) wciąż jest
                # 'pending' → oznacz failed, by zwiększyć licznik prób (bounded retry).
                self._mark_remaining_pending_failed(session, invoice_id, "download did not complete")

            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        if processed:
            logger.info("Faza 2: pobrano artefakty dla %d faktur", processed)
        return processed

    def _build_session_invoice_map(self, force: bool = False) -> dict:
        """Zbuduj (z cache TTL) mapę ksefNumber -> sessionReference z sesji KSeF.

        Listuje sesje online i ich faktury — pozwala odnaleźć sesję, w której
        wystawiono fakturę sprzedażową, aby pobrać jej UPO.
        """
        now = time.time()
        if (not force and self._session_invoice_map is not None
                and (now - self._session_map_ts) < self._session_map_ttl):
            return self._session_invoice_map

        mapping = {}
        for sess in self.ksef.list_sessions(session_type="Online"):
            ref = sess.get("referenceNumber")
            if not ref:
                continue
            for inv in self.ksef.get_session_invoices(ref):
                ksef_number = inv.get("ksefNumber")
                if ksef_number:
                    mapping[ksef_number] = ref

        self._session_invoice_map = mapping
        self._session_map_ts = now
        logger.info("UPO: zbudowano mapę sesji (%d faktur)", len(mapping))
        return mapping

    def _save_upo_xml(self, ksef_number: str, upo_xml: str) -> Optional[Path]:
        """Zapisz UPO XML do {output_dir}/upo/{ksefNumber}.xml (guard path traversal)."""
        upo_dir = self.output_dir / "upo"
        upo_dir.mkdir(parents=True, exist_ok=True)
        target = upo_dir / f"{ksef_number}.xml"
        if not target.resolve().is_relative_to(self.output_dir.resolve()):
            logger.error("UPO: path traversal blocked for %s", ksef_number)
            return None
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write(upo_xml)
        except OSError as e:
            logger.error("UPO: zapis nie powiódł się dla %s: %s", ksef_number, e)
            return None
        return target

    def process_pending_upo(self, limit: Optional[int] = None) -> int:
        """Pobierz UPO dla wykrytych faktur sprzedażowych (Subject1) bez UPO.

        Dla każdej takiej faktury: odnajdź sesję (mapa ksefNumber->sessionRef),
        pobierz UPO (`get_invoice_upo`, z weryfikacją SHA-256), zapisz XML i ustaw
        `has_upo`/`upo_path`. Próby liczone artefaktem typu 'upo' (bounded retry —
        np. KSeF 21178 „UPO not found" może pojawić się z opóźnieniem). Wymaga DB
        oraz `fetch_upo=True`.

        Returns:
            Liczba pobranych UPO.
        """
        if self.db is None or not self.fetch_upo:
            return 0

        limit = limit if limit is not None else self.artifact_batch_size
        processed = 0
        session = self.db.get_session()
        try:
            invoices = (
                session.query(Invoice)
                .filter(Invoice.subject_type == "Subject1", Invoice.has_upo.is_(False))
                .order_by(Invoice.id)
                .limit(limit)
                .all()
            )
            if not invoices:
                return 0

            session_map = None
            for inv in invoices:
                # artefakt 'upo' do liczenia prób (no-op jeśli już istnieje)
                self.db.create_artifact(session, inv.id, "upo", status="pending")
                art = (session.query(InvoiceArtifact)
                       .filter_by(invoice_id=inv.id, artifact_type="upo").first())
                if art and (art.download_attempts or 0) >= 3:
                    continue  # próby wyczerpane

                if session_map is None:
                    session_map = self._build_session_invoice_map()
                session_ref = session_map.get(inv.ksef_number)
                if not session_ref:
                    self.db.mark_artifact_failed(session, inv.id, "upo", "session not found")
                    continue

                upo = self.ksef.get_invoice_upo(session_ref, inv.ksef_number)
                if not upo:
                    self.db.mark_artifact_failed(
                        session, inv.id, "upo", "UPO unavailable (e.g. 21178) or hash mismatch")
                    continue

                path = self._save_upo_xml(inv.ksef_number, upo["upo_xml"])
                if path is None:
                    self.db.mark_artifact_failed(session, inv.id, "upo", "save failed")
                    continue

                inv.has_upo = True
                inv.upo_path = str(path)
                self.db.mark_artifact_downloaded(
                    session, inv.id, "upo", file_path=str(path),
                    file_hash=upo.get("sha256_hash") or None,
                )
                processed += 1

            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        if processed:
            logger.info("UPO: pobrano %d UPO", processed)
        return processed

    def _finalize_check_cycle(self, use_db: bool, state: Dict, seen_entries: list,
                              now: datetime, new_invoices_count: Dict) -> None:
        """Save state and update Prometheus metrics after a check cycle."""
        # Save JSON state only when DB is not active (fallback mode)
        if not use_db:
            state["last_check"] = now.isoformat()
            state["seen_invoices"] = seen_entries[-1000:]
            self.save_state(state)

        # Update Prometheus metrics
        if self.metrics:
            self.metrics.update_last_check(now)
            for subject_type, count in new_invoices_count.items():
                self.metrics.increment_new_invoices(subject_type, count)

            # Update pending artifacts gauge
            if self.db:
                try:
                    session = self.db.get_session()
                    try:
                        pending = self.db.get_pending_artifacts(session, limit=10000)
                        by_type = {}
                        for a in pending:
                            by_type[a.artifact_type] = by_type.get(a.artifact_type, 0) + 1
                        for artifact_type in ("xml", "pdf", "upo"):
                            self.metrics.artifacts_pending.labels(type=artifact_type).set(
                                by_type.get(artifact_type, 0)
                            )
                    finally:
                        session.close()
                except Exception as e:
                    logger.debug("Failed to update artifacts_pending metric: %s", e)
    
    def _get_date_from(self, db_session, subject_type: str, json_state: Dict, now: datetime) -> datetime:
        """Determine date_from for a subject_type. DB has priority over JSON state."""
        if db_session is not None:
            ms = self.db.get_monitor_state(db_session, self.nip, subject_type)
            if ms and ms.last_check:
                dt = ms.last_check
                if dt.tzinfo is None and self.timezone:
                    dt = self.timezone.localize(dt)
                elif dt.tzinfo is not None and self.timezone:
                    dt = dt.astimezone(self.timezone)
                return dt

        # Fallback to JSON state
        if json_state.get("last_check"):
            try:
                return self._parse_datetime(json_state["last_check"])
            except (ValueError, TypeError):
                logger.warning("Invalid last_check date, using 24h ago")

        logger.info("First run - checking last 24 hours")
        return now - timedelta(hours=24)

    def _save_invoice_to_db(self, session, invoice: Dict, subject_type: str) -> Optional[int]:
        """Save invoice metadata to DB. Returns invoice.id (new or existing) or None."""
        try:
            ksef_number = invoice.get('ksefNumber', '')
            seller = invoice.get('seller', {})
            buyer = invoice.get('buyer', {})
            # Buyer NIP is in buyer.identifier.value (API schema: InvoiceMetadataBuyer)
            buyer_identifier = buyer.get("identifier", {})
            buyer_nip = buyer_identifier.get("value")

            invoice_data = {
                "ksef_number": ksef_number,
                "invoice_number": invoice.get("invoiceNumber"),
                "invoice_type": invoice.get("invoiceType"),
                "subject_type": subject_type,
                "form_code": invoice.get("formCode", {}).get("schemaVersion"),
                "issue_date": invoice.get("issueDate"),
                "invoicing_date": self._parse_optional_dt(invoice.get("invoicingDate")),
                "acquisition_date": self._parse_optional_dt(invoice.get("acquisitionDate")),
                "gross_amount": invoice.get("grossAmount"),
                "net_amount": invoice.get("netAmount"),
                "vat_amount": invoice.get("vatAmount"),
                "currency": invoice.get("currency", "PLN"),
                "seller_nip": seller.get("nip", ""),
                "seller_name": seller.get("name"),
                "buyer_nip": buyer_nip,
                "buyer_name": buyer.get("name"),
                "raw_metadata": json.dumps(invoice, ensure_ascii=False, default=str),
            }
            inv = self.db.save_invoice(session, invoice_data)
            if inv:
                return inv.id
            # Duplicate — return existing record's id so artifacts can be linked
            existing = session.query(Invoice).filter_by(ksef_number=ksef_number).first()
            return existing.id if existing else None
        except Exception as e:
            logger.error(f"Failed to save invoice to DB: {e}")
            return None

    @staticmethod
    def _parse_optional_dt(value) -> Optional[datetime]:
        """Parse optional ISO datetime string, return None on failure."""
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _sanitize_field(value, max_length: int = 500) -> str:
        """Sanitize a string field from API: strip null bytes and limit length."""
        return str(value)[:max_length].replace('\x00', '')

    def build_template_context(self, invoice: Dict, subject_type: str) -> Dict[str, Any]:
        """
        Build template context dictionary from invoice metadata.

        All fields from the KSeF API response are flattened into a
        single-level dict for easy access in Jinja2 templates.
        String fields are sanitized to prevent injection via malicious data.

        Args:
            invoice: Invoice metadata dict from KSeF API
            subject_type: Subject type (Subject1 or Subject2)

        Returns:
            Context dictionary for template rendering
        """
        s = self._sanitize_field
        title = self.SUBJECT_TYPE_TITLES.get(subject_type, self.DEFAULT_TITLE)

        priority_emojis = {-2: "🔕", -1: "💤", 0: "📋", 1: "⚠️", 2: "🚨"}
        priority_names = {-2: "lowest", -1: "low", 0: "normal", 1: "high", 2: "urgent"}
        priority_colors = {-2: "#808080", -1: "#808080", 0: "#36a64f", 1: "#ff9900", 2: "#e74c3c"}
        priority_colors_int = {-2: 0x808080, -1: 0x808080, 0: 0x3498db, 1: 0xff9900, 2: 0xe74c3c}

        return {
            "ksef_number": s(invoice.get("ksefNumber", "N/A")),
            "invoice_number": s(invoice.get("invoiceNumber", "N/A")),
            "issue_date": s(invoice.get("issueDate", "N/A"), 30),
            "gross_amount": invoice.get("grossAmount", "N/A"),
            "net_amount": invoice.get("netAmount"),
            "vat_amount": invoice.get("vatAmount"),
            "currency": s(invoice.get("currency", "PLN"), 10),
            "seller_name": s(invoice.get("seller", {}).get("name", "N/A")),
            "seller_nip": s(invoice.get("seller", {}).get("nip", "N/A"), 20),
            "buyer_name": s(invoice.get("buyer", {}).get("name", "N/A")),
            "buyer_nip": s(
                invoice.get("buyer", {}).get("identifier", {}).get("value")
                or invoice.get("buyer", {}).get("nip", "N/A"),
                20
            ),
            "subject_type": subject_type,
            "schema_type": self._detect_schema_type_from_metadata(invoice),
            "title": title,
            "priority": self.message_priority,
            "priority_emoji": priority_emojis.get(self.message_priority, "📋"),
            "priority_name": priority_names.get(self.message_priority, "normal"),
            "priority_color": priority_colors.get(self.message_priority, "#36a64f"),
            "priority_color_int": priority_colors_int.get(self.message_priority, 0x3498db),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "url": None,
            "notification_id": str(uuid.uuid4()),
        }

    @staticmethod
    def _detect_schema_type_from_metadata(invoice: Dict) -> str:
        """Best-effort schema type detection from KSeF API metadata.

        KSeF API metadata may include a 'type' field ('FA', 'FA_RR', 'PEF').
        Falls back to 'FA3' (most common) when not available.
        """
        from .invoice_xml_parser import (
            SCHEMA_TYPE_FA3, SCHEMA_TYPE_FA2, SCHEMA_TYPE_FA_RR, SCHEMA_TYPE_PEF,
        )
        raw_type = (invoice.get('type') or invoice.get('schemaType') or '').upper()
        mapping = {
            'FA': SCHEMA_TYPE_FA3,
            'FA3': SCHEMA_TYPE_FA3,
            'FA2': SCHEMA_TYPE_FA2,
            'FA_RR': SCHEMA_TYPE_FA_RR,
            'FARR': SCHEMA_TYPE_FA_RR,
            'PEF': SCHEMA_TYPE_PEF,
        }
        return mapping.get(raw_type, SCHEMA_TYPE_FA3)

    def _format_date_for_filename(self, date_string: str) -> str:
        """Format date string to YYYYMMDD for filename"""
        try:
            dt = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
            return dt.strftime('%Y%m%d')
        except (ValueError, TypeError):
            # Fallback: strip separators
            return date_string.replace('-', '').replace(':', '').replace('T', '')[:8]

    def _resolve_output_dir(self, invoice: Dict, subject_type: str) -> Path:
        """
        Resolve target directory for invoice artifacts based on folder_structure config.

        Supports placeholders: {year}, {month}, {day}, {type}.
        Returns self.output_dir (flat) if folder_structure is empty or on error.
        """
        if not self.folder_structure:
            return self.output_dir

        issue_date = invoice.get('issueDate', '')
        type_name = 'sprzedaz' if subject_type == 'Subject1' else 'zakup'

        try:
            dt = datetime.fromisoformat(issue_date.replace('Z', '+00:00'))
            year, month, day = dt.strftime('%Y'), dt.strftime('%m'), dt.strftime('%d')
        except (ValueError, TypeError):
            logger.warning(f"Cannot parse issueDate '{issue_date}' for folder structure - using flat directory")
            return self.output_dir

        try:
            subfolder = self.folder_structure.format(
                year=year, month=month, day=day, type=type_name
            )
        except (KeyError, IndexError) as e:
            logger.error(f"Invalid folder_structure pattern '{self.folder_structure}': {e} - using flat directory")
            return self.output_dir

        target = self.output_dir / subfolder

        # Path traversal guard
        if not target.resolve().is_relative_to(self.output_dir.resolve()):
            logger.error(f"Path traversal detected in folder_structure: '{subfolder}' - using flat directory")
            return self.output_dir

        return target

    def _resolve_safe_path(self, path: Path) -> Optional[Path]:
        """Check if file exists and apply configured file_exists_strategy.

        Returns:
            Path to write to, or None if file should be skipped.
        """
        if not path.exists():
            return path

        strategy = self.file_exists_strategy

        if strategy == "skip":
            logger.info(f"File already exists, skipping: {path}")
            return None
        elif strategy == "overwrite":
            logger.warning(f"Overwriting existing file: {path}")
            return path
        elif strategy == "rename":
            stem, suffix = path.stem, path.suffix
            counter = 1
            while counter < 1000:
                new_path = path.parent / f"{stem}_{counter}{suffix}"
                if not new_path.exists():
                    logger.info(f"File exists, saving as: {new_path}")
                    return new_path
                counter += 1
            logger.error(f"Too many renamed copies for {path} - skipping")
            return None

        return path

    @staticmethod
    def _sanitize_filename_value(value: str) -> str:
        """Sanitize a value for safe use in filenames."""
        if not value:
            return "unknown"
        result = str(value)
        for ch in r'/\:*?"<>|':
            result = result.replace(ch, '_')
        result = result.replace('\x00', '')
        result = result.strip('. ')
        return result[:100] or "unknown"

    def _build_file_name(self, invoice: Dict, subject_type: str, file_type: str = "invoice") -> str:
        """
        Build file name from file_name_pattern config.

        Args:
            invoice: Invoice metadata dict from KSeF API
            subject_type: Subject1 or Subject2
            file_type: "invoice"

        Returns:
            File name without extension
        """
        san = self._sanitize_filename_value
        ksef_number = invoice.get('ksefNumber', '')
        safe_ksef = san(ksef_number)
        issue_date = invoice.get('issueDate', '')
        buyer = invoice.get('buyer', {})
        buyer_nip = (
            buyer.get("identifier", {}).get("value")
            or buyer.get("nip", "")
        )

        type_val = "sprz" if subject_type == "Subject1" else "zak"

        placeholders = {
            "type": type_val,
            "date": self._format_date_for_filename(issue_date),
            "ksef": safe_ksef,
            "ksef_short": safe_ksef[-6:] if len(safe_ksef) >= 6 else safe_ksef,
            "invoice_number": san(invoice.get('invoiceNumber', '')),
            "seller_nip": san(invoice.get('seller', {}).get('nip', '')),
            "buyer_nip": san(buyer_nip),
        }

        try:
            return self.file_name_pattern.format(**placeholders)
        except (KeyError, IndexError, ValueError) as e:
            logger.warning(f"file_name_pattern error: {e} — using fallback")
            return f"{type_val}_{placeholders['date']}_{safe_ksef}"

    def _save_invoice_artifacts(self, invoice: Dict, subject_type: str,
                                invoice_id: Optional[int] = None, db_session=None):
        """
        Save PDF and XML for a new invoice (if enabled in config).

        Controlled by storage config:
            save_xml: save XML source files
            save_pdf: generate and save PDF files
            output_dir: directory for saved files (auto-created)

        Args:
            invoice: Invoice metadata from KSeF API
            subject_type: Subject type (Subject1=sprzedażowa, Subject2=zakupowa)
            invoice_id: DB invoice id (optional, for updating artifact paths)
            db_session: DB session (optional)
        """
        if not self.save_xml and not self.save_pdf:
            return

        ksef_number = invoice.get('ksefNumber', '')

        if not ksef_number:
            logger.warning("No KSeF number - skipping artifact saving")
            return

        # Build base filename from configurable pattern
        base_name = self._build_file_name(invoice, subject_type, file_type="invoice")

        # Resolve target directory (may include date-based subfolders)
        target_dir = self._resolve_output_dir(invoice, subject_type)
        target_dir.mkdir(parents=True, exist_ok=True)

        # Path traversal guard: ensure generated filenames stay within output_dir
        resolved_dir = self.output_dir.resolve()
        test_path = (target_dir / f"{base_name}.tmp").resolve()
        if not test_path.is_relative_to(resolved_dir):
            logger.error(f"Path traversal detected for KSeF number: {ksef_number} - skipping")
            return

        # Fetch invoice XML (needed for both XML saving and PDF generation)
        xml_result = self.ksef.get_invoice_xml(ksef_number)
        if not xml_result:
            logger.warning(f"Failed to fetch XML for {ksef_number} - skipping artifact saving")
            return

        xml_content = xml_result['xml_content']

        # Detect schema type for logging and downstream decisions
        schema_type = detect_schema_type(xml_content)
        if schema_type == SCHEMA_TYPE_UNKNOWN:
            logger.warning(
                "Unknown XML schema for invoice %s — XML will be saved but PDF skipped",
                ksef_number,
            )
        else:
            logger.debug("Invoice %s schema: %s", ksef_number, schema_type)

        # Save XML
        if self.save_xml:
            xml_orig_path = target_dir / f"{base_name}.xml"
            xml_path = self._resolve_safe_path(xml_orig_path)
            if xml_path:
                try:
                    with open(xml_path, 'w', encoding='utf-8') as f:
                        f.write(xml_content)
                    logger.info(f"Invoice XML saved: {xml_path}")
                    self._update_artifact_in_db(db_session, invoice_id, "xml", xml_path)
                except Exception as e:
                    logger.error(f"Failed to save XML for {ksef_number}: {e}")
            elif xml_orig_path.exists():
                # File exists on disk but was skipped — mark in DB
                self._update_artifact_in_db(db_session, invoice_id, "xml", xml_orig_path)

        # Generate and save PDF
        if self.save_pdf:
            if REPORTLAB_AVAILABLE:
                pdf_orig_path = target_dir / f"{base_name}.pdf"
                pdf_path = self._resolve_safe_path(pdf_orig_path)
                if pdf_path:
                    try:
                        tz_name = self.config.get_timezone() if hasattr(self.config, 'get_timezone') else ''
                        template_dir = self.config.get("storage", "pdf_templates_dir", default=None)
                        generate_invoice_pdf(xml_content, ksef_number=ksef_number,
                                             output_path=str(pdf_path), environment=self.ksef.environment,
                                             timezone=tz_name, template_dir=template_dir)
                        logger.info(f"Invoice PDF saved: {pdf_path}")
                        self._update_artifact_in_db(db_session, invoice_id, "pdf", pdf_path)
                    except Exception as e:
                        logger.error(f"Failed to generate PDF for {ksef_number}: {e}")
                elif pdf_orig_path.exists():
                    # File exists on disk but was skipped — mark in DB
                    self._update_artifact_in_db(db_session, invoice_id, "pdf", pdf_orig_path)
            else:
                logger.warning("reportlab not available - skipping PDF generation")


    def _update_artifact_in_db(self, db_session, invoice_id: Optional[int],
                               artifact_type: str, file_path: Path):
        """Update artifact flags and paths in DB for a saved file.

        Writes both the inline `Invoice.has_xml/xml_path/has_pdf/pdf_path`
        fields and the dedicated `invoice_artifacts` row (status='downloaded')
        that the API cache lookup queries.
        """
        if not db_session or not invoice_id:
            return
        try:
            inv = db_session.query(Invoice).filter_by(id=invoice_id).first()
            if not inv:
                return
            rel_path = str(file_path)
            if artifact_type == "xml":
                inv.has_xml = True
                inv.xml_path = rel_path
            elif artifact_type == "pdf":
                inv.has_pdf = True
                inv.pdf_path = rel_path
            # Mirror to invoice_artifacts so /api/v1/invoices/{ksef}/{xml|pdf}
            # cache hit path actually finds the file. db.create_artifact is a
            # no-op when the (invoice_id, artifact_type) row already exists.
            try:
                size = file_path.stat().st_size if file_path.exists() else None
            except OSError:
                size = None
            try:
                from app.database import Database  # local import to avoid cycle
            except Exception:
                Database = None
            if self.db is not None:
                self.db.create_artifact(db_session, invoice_id, artifact_type)
                self.db.mark_artifact_downloaded(
                    db_session, invoice_id, artifact_type,
                    file_path=rel_path, file_size=size,
                )
        except Exception as e:
            logger.error(f"Failed to update artifact in DB: {e}")

    def save_artifact_for_invoice(
        self,
        invoice_meta: Dict,
        subject_type: str,
        artifact_type: str,
        content,
        invoice_id: int,
        db_session,
    ) -> Optional[Path]:
        """Persist on-demand-fetched XML or generated PDF to disk + DB.

        Reuses the same path resolution / file_exists_strategy as the live
        polling path so on-demand artifacts land in the same folder layout.

        Args:
            invoice_meta: KSeF v2.4 InvoiceMetadata dict (from raw_metadata).
            subject_type: Subject1 / Subject2 / etc.
            artifact_type: "xml" or "pdf".
            content: str (XML) or bytes (PDF).
            invoice_id: DB Invoice.id.
            db_session: open SQLAlchemy session (caller commits).

        Returns the Path that was written, or None on skip / collision /
        path-traversal guard hit.
        """
        if artifact_type not in ("xml", "pdf"):
            raise ValueError(f"unsupported artifact_type: {artifact_type}")

        ksef_number = invoice_meta.get("ksefNumber") or ""
        if not ksef_number:
            logger.warning("save_artifact: missing ksefNumber, aborting")
            return None

        base_name = self._build_file_name(invoice_meta, subject_type, file_type="invoice")
        target_dir = self._resolve_output_dir(invoice_meta, subject_type)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"save_artifact: cannot mkdir {target_dir}: {e}")
            return None

        # Path traversal guard
        resolved_dir = self.output_dir.resolve()
        test_path = (target_dir / f"{base_name}.tmp").resolve()
        if not test_path.is_relative_to(resolved_dir):
            logger.error(f"save_artifact: path traversal blocked for {ksef_number}")
            return None

        suffix = ".xml" if artifact_type == "xml" else ".pdf"
        orig_path = target_dir / f"{base_name}{suffix}"
        write_path = self._resolve_safe_path(orig_path)
        if write_path is None:
            # `skip` strategy and file already on disk — still register in DB
            # so the next API lookup is a cache hit.
            if orig_path.exists():
                self._update_artifact_in_db(db_session, invoice_id, artifact_type, orig_path)
                return orig_path
            return None

        try:
            if artifact_type == "xml":
                if isinstance(content, bytes):
                    content = content.decode("utf-8")
                with open(write_path, "w", encoding="utf-8") as f:
                    f.write(content)
            else:  # pdf
                if hasattr(content, "read"):
                    content = content.read()
                with open(write_path, "wb") as f:
                    f.write(content)
            logger.info(f"Invoice {artifact_type.upper()} saved (on-demand): {write_path}")
            self._update_artifact_in_db(db_session, invoice_id, artifact_type, write_path)
            return write_path
        except Exception as e:
            logger.error(f"save_artifact: write failed for {ksef_number} {artifact_type}: {e}")
            return None

    def _check_and_drain(self) -> None:
        """Jeden przebieg: detekcja nowych faktur + (w trybie lazy) Faza 2 — pobranie
        zakolejkowanych artefaktów. Błąd Fazy 2 nie przerywa detekcji."""
        self.check_for_new_invoices()
        if self.lazy_artifacts:
            try:
                self.process_pending_artifacts()
            except Exception as e:
                logger.error("Faza 2 (pobieranie artefaktów) nie powiodła się: %s", e, exc_info=True)
        if self.fetch_upo:
            try:
                self.process_pending_upo()
            except Exception as e:
                logger.error("UPO: pobieranie nie powiodło się: %s", e, exc_info=True)

    def run(self):
        """
        Main monitoring loop
        Continuously checks for new invoices at configured intervals
        """
        logger.info("=" * 60)
        logger.info("KSeF Monitor started")
        logger.info("=" * 60)
        logger.info(f"Environment: {self.ksef.environment}")
        nip = self.ksef.nip or ""
        masked_nip = nip[:3] + "****" + nip[-3:] if len(nip) >= 6 else "***"
        logger.info(f"NIP: {masked_nip}")
        logger.info(f"Save XML: {self.save_xml}, Save PDF: {self.save_pdf}")
        if self.save_xml or self.save_pdf:
            logger.info(f"Output directory: {self.output_dir}")
        self.scheduler._log_schedule_info()
        logger.info("=" * 60)

        # Send startup notification
        self.notifier.send_notification(
            title="KSeF Monitor Started",
            message=f"Monitoring invoices for NIP: {self.ksef.nip}",
            priority=-1  # Quiet notification
        )

        while True:
            try:
                if self._manual_trigger:
                    self._manual_trigger = False
                    logger.info("Manual trigger received — checking for new invoices...")
                    self._check_and_drain()
                    logger.info(self.scheduler.get_next_run_info())
                    logger.info("-" * 60)
                elif self.scheduler.should_run():
                    logger.info("Checking for new invoices...")
                    self._check_and_drain()
                    logger.info(self.scheduler.get_next_run_info())
                    logger.info("-" * 60)

            except Exception as e:
                logger.error(f"Error during check: {e}", exc_info=True)

                # Record error in DB monitor_state
                if self.db:
                    try:
                        err_session = self.db.get_session()
                        for st in self.subject_types:
                            self.db.update_monitor_state(
                                session=err_session,
                                nip=self.nip,
                                subject_type=st,
                                last_check=self._get_now(),
                                error=str(e),
                            )
                        err_session.commit()
                    except Exception as db_err:
                        logger.error(f"Failed to record error in DB: {db_err}")
                    finally:
                        err_session.close()

                # Send error notification
                error_msg = f"Error occurred: {str(e)[:200]}"
                self.notifier.send_error_notification(error_msg)

            # Wait until next scheduled run
            self.scheduler.wait_until_next_run()

    def trigger_check(self):
        """Set flag to run an immediate check on next loop iteration."""
        logger.info("On-demand check requested (SIGUSR1)")
        self._manual_trigger = True

    def shutdown(self):
        """
        Clean shutdown
        Revokes KSeF session, marks metrics as stopped, sends shutdown notification.
        Order: revoke first (may take up to 10s), then stop metrics.
        """
        logger.info("Shutting down...")

        # Revoke session first (metrics should remain active during this)
        self.ksef.revoke_current_session()

        # Mark metrics as stopped (after session cleanup)
        if self.metrics:
            self.metrics.shutdown()

        # Send shutdown notification
        self.notifier.send_notification(
            title="KSeF Monitor Stopped",
            message="Invoice monitoring has been stopped",
            priority=-1  # Quiet notification
        )
