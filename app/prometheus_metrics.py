"""
Prometheus Metrics for KSeF Invoice Monitor

Exposes monitoring metrics on HTTP endpoint /metrics (default port 8000)
"""

import logging
import threading
from datetime import datetime
from typing import Optional

from prometheus_client import Gauge, Counter, start_http_server

logger = logging.getLogger(__name__)


class PrometheusMetrics:
    """
    Prometheus metrics manager for KSeF Monitor

    Metrics exposed:
    - ksef_last_check_timestamp: Unix timestamp of last KSeF API check
    - ksef_new_invoices_total: Total count of new invoices by subject_type
    - ksef_monitor_up: Health check - 1 if monitor is running
    """

    def __init__(self, port: int = 8000):
        """
        Initialize Prometheus metrics

        Args:
            port: HTTP server port for /metrics endpoint (default: 8000)
        """
        self.port = port
        self._server_started = False

        # Metric: Last check timestamp (gauge - can go up and down)
        self.last_check_timestamp = Gauge(
            'ksef_last_check_timestamp',
            'Unix timestamp of last KSeF API check',
            unit='seconds'
        )

        # Metric: New invoices count by subject type (counter - only goes up)
        self.new_invoices_total = Counter(
            'ksef_new_invoices_total',
            'Total number of new invoices found',
            labelnames=['subject_type']
        )

        # Metric: Monitor health (1 = running, 0 = stopped)
        self.monitor_up = Gauge(
            'ksef_monitor_up',
            'KSeF Monitor health status (1 = running, 0 = stopped)'
        )

        # Initialize as running
        self.monitor_up.set(1)

    def start_server(self):
        """
        Start Prometheus HTTP server in background thread

        Exposes /metrics endpoint on configured port
        """
        if self._server_started:
            logger.warning(f"Prometheus server already running on port {self.port}")
            return

        try:
            # Start HTTP server in daemon thread
            start_http_server(self.port, addr='127.0.0.1')
            self._server_started = True
            logger.info(f"✓ Prometheus metrics server started on port {self.port}")
            logger.info(f"  Metrics endpoint: http://localhost:{self.port}/metrics")
        except OSError as e:
            logger.error(f"Failed to start Prometheus server on port {self.port}: {e}")
            logger.warning("Continuing without Prometheus metrics")

    def update_last_check(self, timestamp: Optional[datetime] = None):
        """
        Update last check timestamp metric

        Args:
            timestamp: Datetime of last check (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now()

        # Convert to Unix timestamp (seconds since epoch)
        unix_timestamp = timestamp.timestamp()
        self.last_check_timestamp.set(unix_timestamp)
        logger.debug(f"Prometheus: Updated last_check_timestamp to {unix_timestamp}")

    def increment_new_invoices(self, subject_type: str, count: int = 1):
        """
        Increment new invoices counter for subject type

        Args:
            subject_type: Invoice subject type (Subject1, Subject2, etc.)
            count: Number of invoices to add (default: 1)
        """
        if count > 0:
            self.new_invoices_total.labels(subject_type=subject_type).inc(count)
            logger.debug(f"Prometheus: Incremented new_invoices_total[{subject_type}] by {count}")

    def set_monitor_up(self, is_up: bool):
        """
        Update monitor health status

        Args:
            is_up: True if monitor is running, False if stopped
        """
        self.monitor_up.set(1 if is_up else 0)
        status = "running" if is_up else "stopped"
        logger.debug(f"Prometheus: Monitor status set to {status}")

    def shutdown(self):
        """
        Mark monitor as stopped
        """
        self.set_monitor_up(False)
        logger.info("Prometheus: Metrics marked as stopped")
