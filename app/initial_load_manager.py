"""
Initial Load Manager for KSeF Monitor.

Orchestrates historical invoice import using the async /invoices/exports API.
Splits the configured date range into ≤90-day windows per subject_type,
calls InvoiceExportManager for each window, and persists progress to the DB
for resume capability.

Design notes:
- One active job at a time (enforced by get_active_initial_load_job).
- Resume: on restart, finds a running/pending job and continues from
  current_window_from / current_subject_type.
- isTruncated handling: if a window is truncated, uses lastInvoicingDate
  as the next window start (per KSeF API spec).
- Thread-safe: uses a simple threading.Event for cancellation signal.
"""

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .database import Database, InitialLoadJob
from .invoice_export_manager import InvoiceExportManager

logger = logging.getLogger(__name__)

# KSeF API hard limit: dateRange ≤ 90 days, treated inclusive on both ends.
# 90 days inclusive = (end - start) days difference of 89 — i.e. timedelta(days=89).
MAX_WINDOW_DAYS = 90
_WINDOW_SPAN = timedelta(days=MAX_WINDOW_DAYS - 1)
_ONE_DAY = timedelta(days=1)


def _count_windows(start: datetime, end: datetime, subject_types: List[str]) -> int:
    """Estimate total window count for progress display."""
    total = 0
    cursor = start
    while cursor < end:
        window_end = min(cursor + _WINDOW_SPAN, end)
        cursor = window_end + _ONE_DAY
        total += 1
    return total * len(subject_types)


class InitialLoadManager:
    """Orchestrates historical invoice import via /invoices/exports."""

    def __init__(self, config, ksef_client, database: Database):
        """
        Args:
            config: ConfigManager instance
            ksef_client: KSeFClient instance
            database: Database instance
        """
        self.config = config
        self.db = database
        self.export_manager = InvoiceExportManager(ksef_client)
        self._cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._active_job_id: Optional[str] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start_job(
        self,
        start_date: datetime,
        end_date: datetime,
        subject_types: List[str],
        date_type: str = "Invoicing",
    ) -> Optional[str]:
        """
        Create and start a new initial load job.

        Returns:
            Job ID string, or None if another job is already active.
        """
        with self._lock:
            session = self.db.get_session()
            try:
                existing = self.db.get_active_initial_load_job(session)
                if existing:
                    logger.warning(
                        "Initial load job already active: %s (status=%s)",
                        existing.id, existing.status,
                    )
                    return None

                windows_total = _count_windows(start_date, end_date, subject_types)
                job = self.db.create_initial_load_job(
                    session=session,
                    subject_types=subject_types,
                    start_date=start_date,
                    end_date=end_date,
                    date_type=date_type,
                    windows_total=windows_total,
                )
                session.commit()
                job_id = job.id
                logger.info(
                    "Initial load job created: %s | %s → %s | types=%s | windows=%d",
                    job_id,
                    start_date.date(),
                    end_date.date(),
                    subject_types,
                    windows_total,
                )
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        self._cancel_event.clear()
        thread = threading.Thread(
            target=self._run_job,
            args=(job_id,),
            name=f"initial-load-{job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return job_id

    def cancel_job(self, job_id: str) -> bool:
        """
        Request cancellation of the running job.

        Returns:
            True if the job was active and cancellation was requested.
        """
        with self._lock:
            if self._active_job_id != job_id:
                # Try DB cancel for jobs that haven't started yet
                session = self.db.get_session()
                try:
                    job = self.db.cancel_initial_load_job(session, job_id)
                    session.commit()
                    return job is not None
                except Exception:
                    session.rollback()
                    return False
                finally:
                    session.close()

        self._cancel_event.set()
        logger.info("Cancellation requested for job %s", job_id)
        return True

    def get_status(self, job_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get status dict for a job.

        Args:
            job_id: Specific job ID, or None to get the latest job.
        """
        session = self.db.get_session()
        try:
            if job_id:
                job = self.db.get_initial_load_job(session, job_id)
            else:
                job = self.db.get_latest_initial_load_job(session)

            if not job:
                return None

            return self._job_to_dict(job)
        finally:
            session.close()

    def list_windows(self, job_id: str) -> Optional[List[Dict[str, Any]]]:
        """Per-window log for a job. Returns None if job doesn't exist."""
        session = self.db.get_session()
        try:
            job = self.db.get_initial_load_job(session, job_id)
            if not job:
                return None
            rows = self.db.list_initial_load_windows(session, job_id)
            return [self._window_to_dict(r) for r in rows]
        finally:
            session.close()

    def resume_interrupted_jobs(self) -> None:
        """
        Called at startup: resume any job left in running state
        (e.g. after container restart).
        """
        session = self.db.get_session()
        try:
            job = self.db.get_active_initial_load_job(session)
            if not job:
                return
            job_id = job.id
            logger.info("Resuming interrupted initial load job %s", job_id)
        finally:
            session.close()

        self._cancel_event.clear()
        thread = threading.Thread(
            target=self._run_job,
            args=(job_id,),
            name=f"initial-load-resume-{job_id[:8]}",
            daemon=True,
        )
        thread.start()

    # ── Internal runner ───────────────────────────────────────────────────────

    def _run_job(self, job_id: str) -> None:
        """Main job runner executed in a background thread."""
        with self._lock:
            self._active_job_id = job_id

        session = self.db.get_session()
        try:
            job = self.db.get_initial_load_job(session, job_id)
            if not job:
                logger.error("Job not found: %s", job_id)
                return

            subject_types: List[str] = json.loads(job.subject_types)
            start_date = job.start_date
            end_date = job.end_date
            date_type = job.date_type

            # Mark running
            self.db.update_initial_load_progress(session, job_id, status="running")
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Failed to start job %s: %s", job_id, e)
            session.close()
            with self._lock:
                self._active_job_id = None
            return
        finally:
            session.close()

        # ── Process windows per subject type ──────────────────────────────────
        try:
            total_imported = 0
            total_skipped = 0
            all_failures: list = []  # (subject_type, start, end, error)

            for subject_type in subject_types:
                if self._cancel_event.is_set():
                    break

                imported, skipped, failures = self._process_subject_type(
                    job_id=job_id,
                    subject_type=subject_type,
                    start_date=start_date,
                    end_date=end_date,
                    date_type=date_type,
                )
                total_imported += imported
                total_skipped += skipped
                for f_start, f_end, f_err in failures:
                    all_failures.append((subject_type, f_start, f_end, f_err))

            # Final status
            failed_count = len(all_failures)
            if self._cancel_event.is_set():
                final_status = "cancelled"
                logger.info(
                    "Job %s cancelled. imported=%d skipped=%d failed_windows=%d",
                    job_id, total_imported, total_skipped, failed_count,
                )
            elif failed_count:
                final_status = "completed_with_errors"
                logger.warning(
                    "Job %s completed with %d failed window(s). imported=%d skipped=%d",
                    job_id, failed_count, total_imported, total_skipped,
                )
            else:
                final_status = "completed"
                logger.info(
                    "Job %s completed. imported=%d skipped=%d",
                    job_id, total_imported, total_skipped,
                )

            # Surface failures to the GUI via error_message — single Text column,
            # so cap to first 5 entries and truncate each error to 200 chars.
            error_summary = None
            if all_failures:
                lines = [
                    f"{failed_count} okno/okien z błędem (pokazano pierwsze {min(5, failed_count)}):"
                ]
                for st, s, e, err in all_failures[:5]:
                    lines.append(f"• {st} [{s} → {e}]: {str(err)[:200]}")
                error_summary = "\n".join(lines)

            session = self.db.get_session()
            try:
                self.db.update_initial_load_progress(
                    session, job_id,
                    status=final_status,
                    error_message=error_summary,
                )
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        except Exception as e:
            logger.error("Job %s failed: %s", job_id, e, exc_info=True)
            session = self.db.get_session()
            try:
                self.db.update_initial_load_progress(
                    session, job_id, status="failed", error_message=str(e)
                )
                session.commit()
            except Exception:
                session.rollback()
            finally:
                session.close()
        finally:
            with self._lock:
                self._active_job_id = None

    def _process_subject_type(
        self,
        job_id: str,
        subject_type: str,
        start_date: datetime,
        end_date: datetime,
        date_type: str,
    ) -> tuple[int, int, list]:
        """
        Process all windows for one subject_type.

        Returns:
            (invoices_imported, invoices_skipped, failures) totals for this
            subject_type. `failures` is a list of (window_start, window_end,
            error) tuples for the GUI / error_message summary.
        """
        imported = 0
        skipped = 0
        failures: list = []
        cursor = start_date

        # Resume: if job has a current_subject_type matching this one,
        # skip ahead to current_window_from
        session = self.db.get_session()
        try:
            job = self.db.get_initial_load_job(session, job_id)
            if (
                job
                and job.current_subject_type == subject_type
                and job.current_window_from is not None
            ):
                resume_from = job.current_window_from
                if resume_from > cursor:
                    logger.info(
                        "Resuming %s from %s (skipping already-processed windows)",
                        subject_type, resume_from.date(),
                    )
                    cursor = resume_from
        finally:
            session.close()

        while cursor < end_date:
            if self._cancel_event.is_set():
                break

            window_start = cursor
            window_end = min(cursor + _WINDOW_SPAN, end_date)
            window_t0 = time.monotonic()

            logger.info(
                "Processing window %s [%s → %s]",
                subject_type, window_start.date(), window_end.date(),
            )

            # Update resume state before processing
            session = self.db.get_session()
            try:
                self.db.update_initial_load_progress(
                    session, job_id,
                    current_window_from=window_start,
                    current_window_to=window_end,
                    current_subject_type=subject_type,
                )
                session.commit()
            except Exception:
                session.rollback()
            finally:
                session.close()

            # Run export for this window
            result = self.export_manager.run_export(
                subject_type=subject_type,
                date_from=window_start,
                date_to=window_end,
                date_type=date_type,
                only_metadata=True,
            )

            if not result.success:
                logger.warning(
                    "Export failed for %s [%s → %s]: %s",
                    subject_type, window_start.date(), window_end.date(), result.error,
                )
                failures.append(
                    (window_start.date(), window_end.date(), result.error or "unknown")
                )
                # Non-fatal: still bump windows_completed so progress UI reaches
                # 100% even if some windows errored (otherwise the job shows
                # "Ukończony 50%" which is just confusing).
                session = self.db.get_session()
                try:
                    self.db.update_initial_load_progress(
                        session, job_id, windows_completed_delta=1,
                    )
                    self.db.record_initial_load_window(
                        session,
                        job_id=job_id,
                        subject_type=subject_type,
                        window_start=window_start,
                        window_end=window_end,
                        status="failed",
                        error_message=result.error or "unknown",
                        duration_ms=int((time.monotonic() - window_t0) * 1000),
                    )
                    session.commit()
                except Exception:
                    session.rollback()
                finally:
                    session.close()
                cursor = window_end + _ONE_DAY
                continue

            # Save invoices to DB
            win_imported, win_skipped = self._save_invoices(result.invoices, subject_type)
            imported += win_imported
            skipped += win_skipped

            # Update progress counters
            session = self.db.get_session()
            try:
                self.db.update_initial_load_progress(
                    session, job_id,
                    windows_completed_delta=1,
                    invoices_imported_delta=win_imported,
                    invoices_skipped_delta=win_skipped,
                )
                self.db.record_initial_load_window(
                    session,
                    job_id=job_id,
                    subject_type=subject_type,
                    window_start=window_start,
                    window_end=window_end,
                    status="success",
                    imported=win_imported,
                    skipped=win_skipped,
                    duration_ms=int((time.monotonic() - window_t0) * 1000),
                )
                session.commit()
            except Exception:
                session.rollback()
            finally:
                session.close()

            logger.info(
                "Window done: %s [%s → %s] imported=%d skipped=%d%s",
                subject_type, window_start.date(), window_end.date(),
                win_imported, win_skipped,
                " (truncated)" if result.is_truncated else "",
            )

            # Advance cursor: use lastInvoicingDate if truncated
            if result.is_truncated and result.last_invoicing_date:
                try:
                    next_from = datetime.fromisoformat(
                        result.last_invoicing_date.replace("Z", "+00:00")
                    )
                    if next_from.tzinfo is not None:
                        next_from = next_from.replace(tzinfo=None)
                    cursor = next_from
                    logger.debug("Truncated window: advancing cursor to %s", cursor)
                except ValueError:
                    cursor = window_end + _ONE_DAY
            else:
                cursor = window_end + _ONE_DAY

        return imported, skipped, failures

    def _save_invoices(self, invoices: List[Dict], subject_type: str) -> tuple[int, int]:
        """
        Persist invoice metadata from export result to DB.

        Returns:
            (imported_count, skipped_count)
        """
        imported = 0
        skipped = 0

        session = self.db.get_session()
        try:
            for inv in invoices:
                invoice_data = self._map_export_invoice(inv, subject_type)
                saved = self.db.save_invoice(session, invoice_data)
                if saved:
                    imported += 1
                else:
                    skipped += 1

            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Failed to save batch of %d invoices: %s", len(invoices), e)
        finally:
            session.close()

        return imported, skipped

    def _map_export_invoice(self, inv: Dict, subject_type: str) -> Dict:
        """Map invoice dict from _metadata.json (KSeF InvoiceMetadata schema) to
        DB Invoice fields. Field names follow OpenAPI v2.4 spec example payload —
        previous mapping used pre-v2.x names (ksefReferenceNumber, grossValue,
        subjectBy/subjectTo, invoiceHash.hashSHA…) that no longer match prod.
        """
        # Parse datetimes (ISO 8601 with timezone)
        def _parse_dt(raw):
            if not raw:
                return None
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return dt.replace(tzinfo=None)
            except (ValueError, AttributeError):
                return None

        invoicing_date = _parse_dt(inv.get("invoicingDate"))
        acquisition_date = _parse_dt(inv.get("acquisitionDate"))

        # ksef_number: primary v2.x field, fallback to legacy alias
        ksef_number = inv.get("ksefNumber") or inv.get("ksefReferenceNumber") or ""

        # invoiceHash is a base64 SHA256 string in v2.x (was nested object pre-v2)
        raw_hash = inv.get("invoiceHash")
        invoice_hash = raw_hash if isinstance(raw_hash, str) else (
            raw_hash.get("hashSHA", {}).get("value")
            if isinstance(raw_hash, dict)
            else None
        )

        # formCode: dict with systemCode/schemaVersion/value
        raw_form = inv.get("formCode")
        form_code = (
            raw_form.get("systemCode") if isinstance(raw_form, dict) else raw_form
        )

        # seller / buyer: nested objects per InvoiceMetadataSeller / InvoiceMetadataBuyer
        seller = inv.get("seller") or {}
        if not isinstance(seller, dict):
            seller = {}
        buyer = inv.get("buyer") or {}
        if not isinstance(buyer, dict):
            buyer = {}
        buyer_id = buyer.get("identifier") or {}
        if not isinstance(buyer_id, dict):
            buyer_id = {}

        return {
            "ksef_number": ksef_number,
            "invoice_number": inv.get("invoiceNumber") or inv.get("invoiceReferenceNumber"),
            "invoice_hash": invoice_hash,
            "invoice_type": inv.get("invoiceType") or inv.get("subjectType"),
            "subject_type": subject_type,
            "form_code": form_code,
            "issue_date": inv.get("issueDate") or inv.get("invoiceReferenceDate"),
            "invoicing_date": invoicing_date,
            "acquisition_date": acquisition_date,
            "gross_amount": self._parse_amount(inv.get("grossAmount") or inv.get("grossValue")),
            "net_amount": self._parse_amount(inv.get("netAmount") or inv.get("netValue")),
            "vat_amount": self._parse_amount(inv.get("vatAmount") or inv.get("vatValue")),
            "currency": inv.get("currency", "PLN"),
            "seller_nip": seller.get("nip") or (
                inv.get("subjectBy", {}).get("issuedByIdentifier", {}).get("identifier", "")
                if isinstance(inv.get("subjectBy"), dict)
                else ""
            ),
            "seller_name": seller.get("name") or (
                inv.get("subjectBy", {}).get("issuedByName", {}).get("fullName")
                if isinstance(inv.get("subjectBy"), dict)
                else None
            ),
            "buyer_nip": buyer_id.get("value") or (
                inv.get("subjectTo", {}).get("issuedToIdentifier", {}).get("identifier")
                if isinstance(inv.get("subjectTo"), dict)
                else None
            ),
            "buyer_name": buyer.get("name") or (
                inv.get("subjectTo", {}).get("issuedToName", {}).get("fullName")
                if isinstance(inv.get("subjectTo"), dict)
                else None
            ),
            "is_self_invoicing": bool(inv.get("isSelfInvoicing", False)),
            "has_attachment": bool(inv.get("hasAttachment", False)),
            "source": "initial_load",
            "raw_metadata": json.dumps(inv, ensure_ascii=False),
        }

    @staticmethod
    def _parse_amount(value) -> Optional[float]:
        """Parse amount string/number to float. Returns None on failure."""
        if value is None:
            return None
        try:
            return float(str(value).replace(",", "."))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _window_to_dict(w) -> Dict[str, Any]:
        """Serialize InitialLoadWindow row to an API-friendly dict."""
        return {
            "id": w.id,
            "subject_type": w.subject_type,
            "window_start": w.window_start.isoformat() if w.window_start else None,
            "window_end": w.window_end.isoformat() if w.window_end else None,
            "status": w.status,
            "imported": w.imported or 0,
            "skipped": w.skipped or 0,
            "error_message": w.error_message,
            "duration_ms": w.duration_ms,
            "created_at": w.created_at.isoformat() if w.created_at else None,
        }

    @staticmethod
    def _job_to_dict(job: "InitialLoadJob") -> Dict[str, Any]:
        """Serialize InitialLoadJob to API-friendly dict."""
        progress_pct = 0
        if job.windows_total and job.windows_total > 0:
            progress_pct = round((job.windows_completed or 0) / job.windows_total * 100, 1)

        return {
            "id": job.id,
            "status": job.status,
            "subject_types": json.loads(job.subject_types) if job.subject_types else [],
            "date_type": job.date_type,
            "start_date": job.start_date.isoformat() if job.start_date else None,
            "end_date": job.end_date.isoformat() if job.end_date else None,
            "current_window_from": job.current_window_from.isoformat() if job.current_window_from else None,
            "current_window_to": job.current_window_to.isoformat() if job.current_window_to else None,
            "current_subject_type": job.current_subject_type,
            "windows_total": job.windows_total or 0,
            "windows_completed": job.windows_completed or 0,
            "progress_pct": progress_pct,
            "invoices_imported": job.invoices_imported or 0,
            "invoices_skipped": job.invoices_skipped or 0,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        }
