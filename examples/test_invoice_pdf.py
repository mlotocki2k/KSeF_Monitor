#!/usr/bin/env python3
"""
Test script for KSeF Invoice PDF Generation
**IN DEVELOPMENT** - Not yet integrated with main application

This script demonstrates how to:
1. Fetch invoice XML from KSeF API
2. Convert XML to PDF

Usage:
    python test_invoice_pdf.py <ksef_number>

Example:
    python test_invoice_pdf.py 1234567890-20240101-ABCDEF123456-AB

Requirements:
    - Uncomment reportlab in requirements.txt
    - pip install reportlab
    - Configure config.json with valid KSeF credentials
"""

import sys
import os
import argparse
import logging
from pathlib import Path

# Add app directory to path
sys.path.insert(0, os.path.dirname(__file__))

from app.config_manager import ConfigManager
from app.ksef_client import KSeFClient
from app.invoice_pdf_generator import generate_invoice_pdf
from app.logging_config import setup_logging, apply_config

# Configure logging (timezone applied after config is loaded)
setup_logging()

logger = logging.getLogger(__name__)


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description='Generate PDF from KSeF invoice',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate PDF for invoice
  python test_invoice_pdf.py 1234567890-20240101-ABCDEF123456-AB

  # Save to specific file
  python test_invoice_pdf.py 1234567890-20240101-ABCDEF123456-AB --output faktura.pdf

  # Use custom config file
  python test_invoice_pdf.py 1234567890-20240101-ABCDEF123456-AB --config /path/to/config.json

Notes:
  - Requires reportlab: pip install reportlab
  - Requires valid KSeF credentials in config.json
  - Invoice must exist and be accessible with your credentials
        """
    )

    parser.add_argument(
        'ksef_number',
        help='KSeF invoice number (e.g., 1234567890-20240101-ABCDEF123456-AB)'
    )
    parser.add_argument(
        '-o', '--output',
        help='Output PDF file path (default: invoice_<ksef_number>.pdf)',
        default=None
    )
    parser.add_argument(
        '-c', '--config',
        help='Path to config.json (default: ./config.json or /data/config.json)',
        default=None
    )
    parser.add_argument(
        '--xml-only',
        help='Only fetch and save XML without generating PDF',
        action='store_true'
    )
    parser.add_argument(
        '--debug',
        help='Enable debug logging',
        action='store_true'
    )

    args = parser.parse_args()

    # Set debug logging if requested
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Check reportlab availability
    if not args.xml_only:
        try:
            import reportlab
            logger.info(f"reportlab version: {reportlab.Version}")
        except ImportError:
            logger.error("reportlab is not installed!")
            logger.error("Install it with: pip install reportlab")
            logger.error("Or run with --xml-only to just fetch XML")
            return 1

    # Validate KSeF number format
    ksef_number = args.ksef_number
    if not _validate_ksef_number(ksef_number):
        logger.error(f"Invalid KSeF number format: {ksef_number}")
        logger.error("Expected format: 1234567890-20240101-ABCDEF123456-AB")
        return 1

    try:
        # Load configuration
        logger.info("Loading configuration...")
        config_path = args.config or _find_config_path()
        if not config_path or not os.path.exists(config_path):
            logger.error(f"Config file not found: {config_path}")
            logger.error("Create config.json from examples/config.example.json")
            return 1

        config = ConfigManager(config_path)
        apply_config(config)
        logger.info(f"✓ Configuration loaded from {config_path}")

        # Initialize KSeF client
        logger.info("Initializing KSeF client...")
        ksef_client = KSeFClient(config)
        logger.info(f"✓ KSeF client initialized ({ksef_client.environment} environment)")

        # Authenticate
        logger.info("Authenticating with KSeF...")
        if not ksef_client.authenticate():
            logger.error("Authentication failed!")
            logger.error("Check your KSeF token and NIP in config.json")
            return 1
        logger.info("✓ Authentication successful")

        # Fetch invoice XML
        logger.info(f"Fetching invoice XML for: {ksef_number}")
        result = ksef_client.get_invoice_xml(ksef_number)

        if not result:
            logger.error("Failed to fetch invoice XML!")
            logger.error("Possible reasons:")
            logger.error("  - Invoice does not exist")
            logger.error("  - You don't have permission to access this invoice")
            logger.error("  - Invalid KSeF number format")
            return 1

        xml_content = result['xml_content']
        sha256_hash = result['sha256_hash']

        logger.info(f"✓ Invoice XML fetched ({len(xml_content)} bytes)")
        if sha256_hash:
            logger.info(f"  SHA-256: {sha256_hash}")

        # Save XML if requested
        if args.xml_only:
            xml_filename = f"invoice_{ksef_number.replace('/', '_')}.xml"
            with open(xml_filename, 'w', encoding='utf-8') as f:
                f.write(xml_content)
            logger.info(f"✓ XML saved to: {xml_filename}")
            return 0

        # Generate PDF
        logger.info("Generating PDF...")
        output_path = args.output or f"invoice_{ksef_number.replace('/', '_')}.pdf"

        pdf_buffer = generate_invoice_pdf(
            xml_content=xml_content,
            ksef_number=ksef_number,
            output_path=output_path
        )

        logger.info(f"✓ PDF generated successfully: {output_path}")
        logger.info(f"  File size: {os.path.getsize(output_path)} bytes")

        # Also save XML alongside PDF
        xml_path = output_path.replace('.pdf', '.xml')
        with open(xml_path, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        logger.info(f"✓ XML saved to: {xml_path}")

        logger.info("")
        logger.info("=" * 70)
        logger.info("SUCCESS! Invoice PDF generated successfully")
        logger.info("=" * 70)
        logger.info(f"PDF:  {output_path}")
        logger.info(f"XML:  {xml_path}")
        logger.info(f"KSeF: {ksef_number}")
        logger.info("=" * 70)

        return 0

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=args.debug)
        return 1


def _validate_ksef_number(ksef_number: str) -> bool:
    """
    Validate KSeF number format

    Expected format: NIP-YYYYMMDD-RANDOM-XX
    Example: 1234567890-20240101-ABCDEF123456-AB
    """
    parts = ksef_number.split('-')
    if len(parts) != 4:
        return False

    # Basic validation
    nip, date, random_part, suffix = parts

    # NIP should be 10 digits
    if not (nip.isdigit() and len(nip) == 10):
        return False

    # Date should be 8 digits (YYYYMMDD)
    if not (date.isdigit() and len(date) == 8):
        return False

    # Random part should be alphanumeric
    if not (random_part.isalnum() and len(random_part) >= 6):
        return False

    # Suffix should be 2 uppercase letters
    if not (suffix.isalpha() and suffix.isupper() and len(suffix) == 2):
        return False

    return True


def _find_config_path() -> str:
    """Find config.json in common locations"""
    possible_paths = [
        'config.json',
        '/data/config.json',
        'examples/config.example.json'
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return path

    return 'config.json'


if __name__ == '__main__':
    sys.exit(main())
