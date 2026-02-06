#!/usr/bin/env python3
"""
KSeF Invoice Monitor - Main Entry Point
Monitors KSeF API for new invoices and sends multi-channel notifications

Based on KSeF API v2.0 specification:
https://github.com/CIRFMF/ksef-docs
"""

import os
import sys
import signal
import logging

from app.config_manager import ConfigManager
from app.ksef_client import KSeFClient
from app.notifiers import NotificationManager
from app.invoice_monitor import InvoiceMonitor
from app.prometheus_metrics import PrometheusMetrics

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Global monitor instance for signal handling
monitor = None


def signal_handler(signum, frame):
    """
    Handle shutdown signals gracefully
    
    Args:
        signum: Signal number
        frame: Current stack frame
    """
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    if monitor:
        monitor.shutdown()
    sys.exit(0)


def main():
    """Main entry point"""
    global monitor
    
    logger.info("=" * 70)
    logger.info("KSeF Invoice Monitor v0.2")
    logger.info("Based on KSeF API v2.0 (github.com/CIRFMF/ksef-docs)")
    logger.info("Multi-channel notifications: Pushover, Discord, Slack, Email, Webhook")
    logger.info("=" * 70)
    
    try:
        # Load configuration
        logger.info("Loading configuration...")
        config_path = "/data/config.json" if os.path.exists("/data/config.json") else "config.json"
        config = ConfigManager(config_path)
        logger.info("✓ Configuration loaded")
        
        # Initialize KSeF client
        logger.info("Initializing KSeF client...")
        ksef_client = KSeFClient(config)
        logger.info("✓ KSeF client initialized")

        # Initialize notification manager
        logger.info("Initializing notification channels...")
        notification_manager = NotificationManager(config)
        logger.info("✓ Notification system initialized")

        # Display enabled channels
        if notification_manager.enabled_channels:
            logger.info(f"  Enabled channels: {', '.join(notification_manager.enabled_channels)}")
        else:
            logger.warning("  No notification channels enabled - notifications disabled")

        # Test notification connections (optional)
        notifications_config = config.get("notifications") or {}
        test_notification = notifications_config.get("test_notification")
        if test_notification is None:
            test_notification = config.get("monitoring", "test_notification", False)

        if test_notification is True:
            logger.info("Testing notification channels...")
            if notification_manager.test_connection():
                logger.info("✓ Notification test completed successfully")
            else:
                logger.warning("⚠ Notification test failed for all channels")

        # Initialize Prometheus metrics
        logger.info("Initializing Prometheus metrics...")
        prometheus_port = config.get("prometheus", "port", 8000)
        prometheus_enabled = config.get("prometheus", "enabled", True)

        prometheus_metrics = None
        if prometheus_enabled:
            try:
                prometheus_metrics = PrometheusMetrics(port=prometheus_port)
                prometheus_metrics.start_server()
            except Exception as e:
                logger.warning(f"Failed to initialize Prometheus metrics: {e}")
                logger.info("Continuing without Prometheus monitoring")
        else:
            logger.info("Prometheus metrics disabled in configuration")

        # Initialize and run monitor
        logger.info("Initializing invoice monitor...")
        monitor = InvoiceMonitor(config, ksef_client, notification_manager, prometheus_metrics)
        logger.info("✓ Invoice monitor initialized")
        
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Start monitoring
        monitor.run()
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt...")
        if monitor:
            monitor.shutdown()
        sys.exit(0)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        if monitor:
            monitor.shutdown()
        sys.exit(1)


if __name__ == "__main__":
    main()
