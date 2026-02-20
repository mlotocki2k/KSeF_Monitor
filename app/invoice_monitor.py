"""
Invoice Monitor Service
Main service that coordinates KSeF API polling and notifications
"""

import json
import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from .scheduler import Scheduler
from .notifiers import NotificationManager
from .invoice_pdf_generator import generate_invoice_pdf, REPORTLAB_AVAILABLE

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

    def __init__(self, config, ksef_client, notification_manager, prometheus_metrics=None):
        """
        Initialize invoice monitor

        Args:
            config: ConfigManager instance
            ksef_client: KSeFClient instance
            notification_manager: NotificationManager instance
            prometheus_metrics: PrometheusMetrics instance (optional)
        """
        self.config = config
        self.ksef = ksef_client
        self.notifier = notification_manager
        self.metrics = prometheus_metrics
        self.state_file = Path("/data/last_check.json")
        self.subject_types = config.get("monitoring", "subject_types") or ["Subject1"]

        # Storage settings
        self.save_xml = config.get("storage", "save_xml", default=False)
        self.save_pdf = config.get("storage", "save_pdf", default=False)
        output_dir = config.get("storage", "output_dir", default="/data/invoices")
        self.output_dir = Path(output_dir)

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
                dt = self.timezone.localize(dt)
            # If datetime has timezone info and we have a configured timezone, convert to it
            elif dt.tzinfo is not None and self.timezone:
                dt = dt.astimezone(self.timezone)

            return dt
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse datetime '{date_string}': {e}")
            raise

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
        Save current state to file
        
        Args:
            state: State dictionary to save
        """
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
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
        """
        state = self.load_state()

        now = self._get_now()
        if state.get("last_check"):
            try:
                date_from = self._parse_datetime(state["last_check"])
            except (ValueError, TypeError):
                logger.warning("Invalid last_check date, using 24h ago")
                date_from = now - timedelta(hours=24)
        else:
            date_from = now - timedelta(hours=24)
            logger.info("First run - checking last 24 hours")

        date_to = now
        seen_entries = state.get("seen_invoices", [])
        seen_hashes = {e["h"] for e in seen_entries if isinstance(e, dict)}
        found_any = False

        # Track new invoices per subject type for Prometheus
        new_invoices_count = {}

        for subject_type in self.subject_types:
            invoices = self.ksef.get_invoices_metadata(date_from, date_to, subject_type)
            title = self.SUBJECT_TYPE_TITLES.get(subject_type, self.DEFAULT_TITLE)
            new_count = 0

            for invoice in invoices:
                invoice_hash = self.get_invoice_id_hash(invoice)
                if invoice_hash in seen_hashes:
                    continue

                seen_hashes.add(invoice_hash)
                seen_entries.append({"h": invoice_hash, "ts": now.isoformat()})
                found_any = True
                new_count += 1

                context = self.build_template_context(invoice, subject_type)
                success = self.notifier.send_invoice_notification(context)

                safe_ksef_log = str(invoice.get('ksefNumber', 'N/A')).replace('\n', ' ').replace('\r', ' ')
                if success:
                    logger.info(f"Notification sent [{subject_type}] invoice: {safe_ksef_log}")
                else:
                    logger.warning(f"Failed to send notification [{subject_type}] invoice: {safe_ksef_log}")

                # Save invoice artifacts (PDF, XML, UPO)
                self._save_invoice_artifacts(invoice, subject_type)

            # Store count for this subject type
            if new_count > 0:
                new_invoices_count[subject_type] = new_count

        if not found_any:
            logger.info("No new invoices found")

        # Save timestamp in ISO format (includes timezone if available)
        state["last_check"] = now.isoformat()
        state["seen_invoices"] = seen_entries[-1000:]
        self.save_state(state)

        # Update Prometheus metrics
        if self.metrics:
            self.metrics.update_last_check(now)
            for subject_type, count in new_invoices_count.items():
                self.metrics.increment_new_invoices(subject_type, count)
    
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
            "buyer_nip": s(invoice.get("buyer", {}).get("nip", "N/A"), 20),
            "subject_type": subject_type,
            "title": title,
            "priority": self.message_priority,
            "priority_emoji": priority_emojis.get(self.message_priority, "📋"),
            "priority_name": priority_names.get(self.message_priority, "normal"),
            "priority_color": priority_colors.get(self.message_priority, "#36a64f"),
            "priority_color_int": priority_colors_int.get(self.message_priority, 0x3498db),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "url": None,
        }
    
    def _format_date_for_filename(self, date_string: str) -> str:
        """Format date string to YYYYMMDD for filename"""
        try:
            dt = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
            return dt.strftime('%Y%m%d')
        except (ValueError, TypeError):
            # Fallback: strip separators
            return date_string.replace('-', '').replace(':', '').replace('T', '')[:8]

    def _save_invoice_artifacts(self, invoice: Dict, subject_type: str):
        """
        Save PDF, XML and UPO for a new invoice (if enabled in config).

        Controlled by storage config:
            save_xml: save XML source files
            save_pdf: generate and save PDF files
            output_dir: directory for saved files (auto-created)

        Args:
            invoice: Invoice metadata from KSeF API
            subject_type: Subject type (Subject1=sprzedażowa, Subject2=zakupowa)
        """
        if not self.save_xml and not self.save_pdf:
            return

        ksef_number = invoice.get('ksefNumber', '')
        issue_date = invoice.get('issueDate', '')

        if not ksef_number:
            logger.warning("No KSeF number - skipping artifact saving")
            return

        # Determine type prefix
        prefix = 'sprz' if subject_type == 'Subject1' else 'zak'

        # Format date and sanitize KSeF number for filename
        date_str = self._format_date_for_filename(issue_date)
        safe_ksef = ksef_number.replace('/', '_').replace('\\', '_')

        # Build base filename
        base_name = f"{prefix}_{safe_ksef}_{date_str}"

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Path traversal guard: ensure generated filenames stay within output_dir
        resolved_dir = self.output_dir.resolve()
        test_path = (self.output_dir / f"{base_name}.tmp").resolve()
        if not str(test_path).startswith(str(resolved_dir) + os.sep):
            logger.error(f"Path traversal detected for KSeF number: {ksef_number} - skipping")
            return

        # Fetch invoice XML (needed for both XML saving and PDF generation)
        xml_result = self.ksef.get_invoice_xml(ksef_number)
        if not xml_result:
            logger.warning(f"Failed to fetch XML for {ksef_number} - skipping artifact saving")
            return

        xml_content = xml_result['xml_content']

        # Save XML
        if self.save_xml:
            xml_path = self.output_dir / f"{base_name}.xml"
            try:
                with open(xml_path, 'w', encoding='utf-8') as f:
                    f.write(xml_content)
                logger.info(f"Invoice XML saved: {xml_path}")
            except Exception as e:
                logger.error(f"Failed to save XML for {ksef_number}: {e}")

        # Generate and save PDF
        if self.save_pdf:
            if REPORTLAB_AVAILABLE:
                try:
                    pdf_path = str(self.output_dir / f"{base_name}.pdf")
                    tz_name = self.config.get_timezone() if hasattr(self.config, 'get_timezone') else ''
                    template_dir = self.config.get("storage", "pdf_templates_dir", default=None)
                    generate_invoice_pdf(xml_content, ksef_number=ksef_number,
                                         output_path=pdf_path, environment=self.ksef.environment,
                                         timezone=tz_name, template_dir=template_dir)
                    logger.info(f"Invoice PDF saved: {pdf_path}")
                except Exception as e:
                    logger.error(f"Failed to generate PDF for {ksef_number}: {e}")
            else:
                logger.warning("reportlab not available - skipping PDF generation")

        # For sales invoices (Subject1), fetch and save UPO (XML-based, follows save_xml flag)
        if self.save_xml and subject_type == 'Subject1':
            try:
                upo_result = self.ksef.get_invoice_upo(ksef_number)
                if upo_result:
                    upo_path = self.output_dir / f"UPO_{base_name}.xml"
                    with open(upo_path, 'w', encoding='utf-8') as f:
                        f.write(upo_result['xml_content'])
                    logger.info(f"UPO saved: {upo_path}")
                else:
                    logger.info(f"No UPO available yet for {ksef_number}")
            except Exception as e:
                logger.error(f"Failed to fetch/save UPO for {ksef_number}: {e}")

    def run(self):
        """
        Main monitoring loop
        Continuously checks for new invoices at configured intervals
        """
        logger.info("=" * 60)
        logger.info("KSeF Invoice Monitor started")
        logger.info("=" * 60)
        logger.info(f"Environment: {self.ksef.environment}")
        logger.info(f"NIP: {self.ksef.nip}")
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
                if self.scheduler.should_run():
                    logger.info("Checking for new invoices...")
                    self.check_for_new_invoices()
                    logger.info(self.scheduler.get_next_run_info())
                    logger.info("-" * 60)

            except Exception as e:
                logger.error(f"Error during check: {e}", exc_info=True)

                # Send error notification
                error_msg = f"Error occurred: {str(e)[:200]}"
                self.notifier.send_error_notification(error_msg)

            # Wait until next scheduled run
            self.scheduler.wait_until_next_run()
    
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
