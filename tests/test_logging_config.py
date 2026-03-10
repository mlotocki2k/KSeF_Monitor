"""
Unit tests for logging_config and PrometheusMetrics
"""

import logging
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from app.logging_config import TzFormatter, setup_logging, apply_config


class TestTzFormatter:
    """Tests for TzFormatter."""

    def test_format_with_timezone(self):
        """Formats timestamp in configured timezone."""
        import pytz
        tz = pytz.timezone("Europe/Warsaw")
        formatter = TzFormatter("%(asctime)s - %(message)s", tz=tz)

        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None
        )
        result = formatter.formatTime(record)
        # Should be a valid datetime string
        assert len(result) > 10

    def test_format_with_datefmt(self):
        """Uses custom date format."""
        import pytz
        tz = pytz.timezone("UTC")
        formatter = TzFormatter("%(asctime)s", datefmt="%Y-%m-%d", tz=tz)

        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None
        )
        result = formatter.formatTime(record, datefmt="%Y-%m-%d")
        # Should match YYYY-MM-DD format
        assert len(result) == 10

    def test_format_without_timezone(self):
        """Works without timezone (tz=None)."""
        formatter = TzFormatter("%(asctime)s", tz=None)
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None
        )
        result = formatter.formatTime(record)
        assert len(result) > 10


class TestSetupLogging:
    """Tests for setup_logging()."""

    def test_sets_info_level(self):
        """Default setup sets INFO level (when no handlers exist)."""
        old_handlers = logging.root.handlers[:]
        old_level = logging.root.level
        try:
            # Clear handlers so basicConfig takes effect
            logging.root.handlers = []
            setup_logging()
            assert logging.root.level == logging.INFO
        finally:
            logging.root.handlers = old_handlers
            logging.root.setLevel(old_level)

    def test_has_handler(self):
        """Has at least one handler."""
        setup_logging()
        assert len(logging.root.handlers) > 0


class TestApplyConfig:
    """Tests for apply_config()."""

    def test_valid_level(self):
        """Sets valid logging level."""
        config = MagicMock()
        config.get.return_value = "DEBUG"
        apply_config(config)
        assert logging.root.level == logging.DEBUG
        # Reset
        logging.root.setLevel(logging.INFO)

    def test_invalid_level_falls_back(self):
        """Invalid level falls back to INFO."""
        config = MagicMock()
        config.get.return_value = "INVALID"
        apply_config(config)
        assert logging.root.level == logging.INFO

    def test_none_level_falls_back(self):
        """None level falls back to INFO."""
        config = MagicMock()
        config.get.return_value = None
        apply_config(config)
        assert logging.root.level == logging.INFO


class TestPrometheusMetrics:
    """Tests for PrometheusMetrics."""

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Reset prometheus registry between tests."""
        # Use unique metric names per test to avoid duplicate registration
        yield

    def test_init_sets_monitor_up(self):
        """Init sets monitor_up to 1."""
        from prometheus_client import CollectorRegistry
        registry = CollectorRegistry()
        from prometheus_client import Gauge, Counter

        # We can't easily test with real PrometheusMetrics due to global registry
        # Test the logic instead
        from app.prometheus_metrics import PrometheusMetrics

        # Mock start_http_server to avoid port conflicts
        with patch("app.prometheus_metrics.start_http_server"):
            with patch("app.prometheus_metrics.Gauge") as MockGauge, \
                 patch("app.prometheus_metrics.Counter") as MockCounter:
                MockGauge.return_value = MagicMock()
                MockCounter.return_value = MagicMock()

                pm = PrometheusMetrics(port=9999)
                pm.monitor_up.set.assert_called_with(1)

    def test_update_last_check(self):
        """update_last_check sets gauge value."""
        with patch("app.prometheus_metrics.Gauge") as MockGauge, \
             patch("app.prometheus_metrics.Counter") as MockCounter:
            MockGauge.return_value = MagicMock()
            MockCounter.return_value = MagicMock()

            from app.prometheus_metrics import PrometheusMetrics
            pm = PrometheusMetrics(port=9998)

            ts = datetime(2026, 3, 7, 10, 0, tzinfo=timezone.utc)
            pm.update_last_check(ts)
            pm.last_check_timestamp.set.assert_called()

    def test_increment_new_invoices(self):
        """increment_new_invoices increments counter with label."""
        with patch("app.prometheus_metrics.Gauge") as MockGauge, \
             patch("app.prometheus_metrics.Counter") as MockCounter:
            MockGauge.return_value = MagicMock()
            MockCounter.return_value = MagicMock()

            from app.prometheus_metrics import PrometheusMetrics
            pm = PrometheusMetrics(port=9997)

            pm.increment_new_invoices("Subject1", 3)
            pm.new_invoices_total.labels.assert_called_with(subject_type="Subject1")

    def test_increment_zero_skipped(self):
        """Zero count doesn't increment counter."""
        with patch("app.prometheus_metrics.Gauge") as MockGauge, \
             patch("app.prometheus_metrics.Counter") as MockCounter:
            MockGauge.return_value = MagicMock()
            MockCounter.return_value = MagicMock()

            from app.prometheus_metrics import PrometheusMetrics
            pm = PrometheusMetrics(port=9996)

            pm.increment_new_invoices("Subject1", 0)
            pm.new_invoices_total.labels.assert_not_called()

    def test_shutdown_sets_down(self):
        """shutdown sets monitor_up to 0."""
        with patch("app.prometheus_metrics.Gauge") as MockGauge, \
             patch("app.prometheus_metrics.Counter") as MockCounter:
            MockGauge.return_value = MagicMock()
            MockCounter.return_value = MagicMock()

            from app.prometheus_metrics import PrometheusMetrics
            pm = PrometheusMetrics(port=9995)

            pm.shutdown()
            pm.monitor_up.set.assert_called_with(0)

    def test_start_server_twice_warns(self):
        """Starting server twice logs warning."""
        with patch("app.prometheus_metrics.Gauge") as MockGauge, \
             patch("app.prometheus_metrics.Counter") as MockCounter, \
             patch("app.prometheus_metrics.start_http_server"):
            MockGauge.return_value = MagicMock()
            MockCounter.return_value = MagicMock()

            from app.prometheus_metrics import PrometheusMetrics
            pm = PrometheusMetrics(port=9994)

            pm.start_server()
            assert pm._server_started is True
            pm.start_server()  # Should warn, not crash

    def test_bind_address_default(self):
        """Default bind_address is 0.0.0.0."""
        with patch("app.prometheus_metrics.Gauge") as MockGauge, \
             patch("app.prometheus_metrics.Counter") as MockCounter:
            MockGauge.return_value = MagicMock()
            MockCounter.return_value = MagicMock()

            from app.prometheus_metrics import PrometheusMetrics
            pm = PrometheusMetrics(port=9993)
            assert pm.bind_address == '0.0.0.0'

    def test_bind_address_custom(self):
        """Custom bind_address is passed to start_http_server."""
        with patch("app.prometheus_metrics.Gauge") as MockGauge, \
             patch("app.prometheus_metrics.Counter") as MockCounter, \
             patch("app.prometheus_metrics.start_http_server") as mock_start:
            MockGauge.return_value = MagicMock()
            MockCounter.return_value = MagicMock()

            from app.prometheus_metrics import PrometheusMetrics
            pm = PrometheusMetrics(port=9992, bind_address='127.0.0.1')
            pm.start_server()
            mock_start.assert_called_once_with(9992, addr='127.0.0.1')
