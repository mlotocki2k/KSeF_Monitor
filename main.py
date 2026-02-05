#!/usr/bin/env python3
"""
KSeF Invoice Monitor - Main Entry Point
Monitors KSeF API for new invoices and sends Pushover notifications

Based on KSeF API v2.0 specification:
https://github.com/CIRFMF/ksef-docs
"""

import os
import sys
import signal
import logging

from app.config_manager import ConfigManager
from app.ksef_client import KSeFClient
from app.pushover_notifier import PushoverNotifier
from app.invoice_monitor import InvoiceMonitor

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
    logger.info("KSeF Invoice Monitor v2.0")
    logger.info("Based on KSeF API v2.0 (github.com/CIRFMF/ksef-docs)")
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
        
        # Initialize Pushover notifier
        logger.info("Initializing Pushover notifier...")
        pushover_notifier = PushoverNotifier(config)
        logger.info("✓ Pushover notifier initialized")
        
        # Test Pushover connection (optional)
        if config.get("monitoring", "test_notification") is True:
            logger.info("Sending test notification...")
            if pushover_notifier.test_connection():
                logger.info("✓ Test notification sent successfully")
            else:
                logger.warning("⚠ Test notification failed")
        
        # Initialize and run monitor
        logger.info("Initializing invoice monitor...")
        monitor = InvoiceMonitor(config, ksef_client, pushover_notifier)
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
