"""
Invoice Monitor Service
Main service that coordinates KSeF API polling and notifications
"""

import json
import hashlib
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

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
        self.pdf_dir = self.state_file.parent / "pdf"
        self.subject_types = config.get("monitoring", "subject_types") or ["Subject1"]

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

    def load_state(self) -> Dict:
        """
        Load last check state from file
        
        Returns:
            State dictionary containing last_check timestamp and seen_invoices list
        """
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    logger.debug(f"Loaded state: last_check={state.get('last_check')}, "
                               f"seen_invoices={len(state.get('seen_invoices', []))}")
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
    
    def get_invoice_hash(self, invoice: Dict) -> str:
        """
        Generate unique hash for invoice to track duplicates
        
        Args:
            invoice: Invoice metadata dictionary
            
        Returns:
            MD5 hash string
        """
        # Create a unique identifier based on invoice data
        # KSeF number is unique for each invoice
        ksef_number = invoice.get('ksefNumber', '')
        invoice_ref = invoice.get('invoiceNumber', '')
        identifier = f"{ksef_number}_{invoice_ref}"
        return hashlib.md5(identifier.encode()).hexdigest()
    
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
        seen_invoices = set(state.get("seen_invoices", []))
        found_any = False

        # Track new invoices per subject type for Prometheus
        new_invoices_count = {}

        for subject_type in self.subject_types:
            invoices = self.ksef.get_invoices_metadata(date_from, date_to, subject_type)
            title = self.SUBJECT_TYPE_TITLES.get(subject_type, self.DEFAULT_TITLE)
            new_count = 0

            for invoice in invoices:
                invoice_hash = self.get_invoice_hash(invoice)
                if invoice_hash in seen_invoices:
                    continue

                seen_invoices.add(invoice_hash)
                found_any = True
                new_count += 1

                message = self.format_invoice_message(invoice, subject_type)
                success = self.notifier.send_notification(
                    title=title,
                    message=message,
                    priority=self.message_priority
                )

                if success:
                    logger.info(f"Notification sent [{subject_type}] invoice: {invoice.get('ksefNumber')}")
                else:
                    logger.warning(f"Failed to send notification [{subject_type}] invoice: {invoice.get('ksefNumber')}")

                # Save invoice artifacts (PDF, XML, UPO)
                self._save_invoice_artifacts(invoice, subject_type)

            # Store count for this subject type
            if new_count > 0:
                new_invoices_count[subject_type] = new_count

        if not found_any:
            logger.info("No new invoices found")

        # Save timestamp in ISO format (includes timezone if available)
        state["last_check"] = now.isoformat()
        state["seen_invoices"] = list(seen_invoices)[-1000:]
        self.save_state(state)

        # Update Prometheus metrics
        if self.metrics:
            self.metrics.update_last_check(now)
            for subject_type, count in new_invoices_count.items():
                self.metrics.increment_new_invoices(subject_type, count)
    
    def format_invoice_message(self, invoice: Dict, subject_type: str) -> str:
        """
        Format invoice data for notification message.
        Counterparty line depends on subject_type:
            Subject1 (sprzedażowa) -> "Do:" (buyer)
            Subject2 (zakupowa)    -> "Od:" (seller)
            other                  -> both "Od:" and "Do:"
        """
        ksef_number = invoice.get('ksefNumber', 'N/A')
        invoice_ref = invoice.get('invoiceNumber', 'N/A')
        issue_date = invoice.get('issueDate', 'N/A')
        gross_value = invoice.get('grossAmount','N/A')

        seller_name = invoice.get('seller', {}).get("name", 'N/A')
        seller_nip = invoice.get('seller', {}).get("nip", 'N/A')
        buyer_name = invoice.get('buyer', {}).get("name", 'N/A')
        buyer_nip = invoice.get('buyer', {}).get("nip", 'N/A')


        try:
            if issue_date != 'N/A':
                dt = datetime.fromisoformat(issue_date.replace('Z', '+00:00'))
                issue_date = dt.strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            pass

        if subject_type == "Subject1":
            counterparty = f"Do: {buyer_name} - NIP {buyer_nip}"
        elif subject_type == "Subject2":
            counterparty = f"Od: {seller_name} - NIP {seller_nip}"
        else:
            counterparty = (
                f"Od: {seller_name} - NIP {seller_nip}\n"
                f"Do: {buyer_name} - NIP {buyer_nip}"
            )

        message = (
            f"{counterparty}\n"
            f"Nr Faktury: {invoice_ref}\n"
            f"Data: {issue_date}\n"
            f"Brutto: {gross_value}\n"
            f"Numer KSeF: {ksef_number}"
        )

        return message
    
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
        Save PDF, XML and UPO for a new invoice.

        Files are saved to /data/pdf/ with naming:
            <type>_<ksef_number>_<date>.pdf
            <type>_<ksef_number>_<date>.xml
            UPO_<type>_<ksef_number>_<date>.xml  (only for Subject1)

        Args:
            invoice: Invoice metadata from KSeF API
            subject_type: Subject type (Subject1=sprzedażowa, Subject2=zakupowa)
        """
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
        self.pdf_dir.mkdir(parents=True, exist_ok=True)

        # Fetch invoice XML
        xml_result = self.ksef.get_invoice_xml(ksef_number)
        if not xml_result:
            logger.warning(f"Failed to fetch XML for {ksef_number} - skipping artifact saving")
            return

        xml_content = xml_result['xml_content']

        # Save XML
        xml_path = self.pdf_dir / f"{base_name}.xml"
        try:
            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write(xml_content)
            logger.info(f"Invoice XML saved: {xml_path}")
        except Exception as e:
            logger.error(f"Failed to save XML for {ksef_number}: {e}")

        # Generate and save PDF
        if REPORTLAB_AVAILABLE:
            try:
                pdf_path = str(self.pdf_dir / f"{base_name}.pdf")
                generate_invoice_pdf(xml_content, ksef_number=ksef_number, output_path=pdf_path)
                logger.info(f"Invoice PDF saved: {pdf_path}")
            except Exception as e:
                logger.error(f"Failed to generate PDF for {ksef_number}: {e}")
        else:
            logger.warning("reportlab not available - skipping PDF generation")

        # For sales invoices (Subject1), fetch and save all UPOs
        if subject_type == 'Subject1':
            try:
                upo_result = self.ksef.get_invoice_upo(ksef_number)
                if upo_result:
                    upo_path = self.pdf_dir / f"UPO_{base_name}.xml"
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
        logger.info(f"PDF/XML output: {self.pdf_dir}")
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
        Revokes KSeF session and sends shutdown notification
        """
        logger.info("Shutting down...")

        # Mark metrics as stopped
        if self.metrics:
            self.metrics.shutdown()

        # Revoke session
        self.ksef.revoke_current_session()

        # Send shutdown notification
        self.notifier.send_notification(
            title="KSeF Monitor Stopped",
            message="Invoice monitoring has been stopped",
            priority=-1  # Quiet notification
        )
