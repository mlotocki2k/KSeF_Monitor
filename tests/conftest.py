"""
Shared fixtures for KSeF Monitor unit tests
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


@pytest.fixture
def minimal_config():
    """Minimal valid configuration dictionary."""
    return {
        "ksef": {
            "environment": "test",
            "nip": "1234567890",
            "token": "test-token-123"
        },
        "monitoring": {
            "subject_types": ["Subject1"],
            "date_type": "Invoicing",
            "timezone": "Europe/Warsaw"
        },
        "schedule": {
            "mode": "minutes",
            "interval": 5
        },
        "notifications": {
            "channels": ["pushover"],
            "message_priority": 0,
            "pushover": {
                "user_key": "test-user-key",
                "api_token": "test-api-token"
            }
        },
        "storage": {
            "save_xml": False,
            "save_pdf": False,
            "output_dir": "/data/invoices",
            "folder_structure": ""
        },
        "prometheus": {
            "enabled": True,
            "port": 8000
        }
    }


@pytest.fixture
def config_file(tmp_path, minimal_config):
    """Write minimal_config to a temp file and return its path."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(minimal_config), encoding="utf-8")
    return str(config_path)


@pytest.fixture
def mock_config(minimal_config):
    """Mock ConfigManager that returns values from minimal_config."""
    config = MagicMock()
    config.config = minimal_config

    def _get(*keys, default=None):
        value = minimal_config
        for key in keys:
            if isinstance(key, str) and isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default
        return value

    config.get = _get
    config.get_timezone.return_value = "Europe/Warsaw"

    try:
        import pytz
        config.get_timezone_object.return_value = pytz.timezone("Europe/Warsaw")
    except ImportError:
        config.get_timezone_object.return_value = None

    return config


@pytest.fixture
def sample_invoice():
    """Sample invoice metadata as returned by KSeF API."""
    return {
        "ksefReferenceNumber": "1234567890-20260301-ABC123-XY",
        "ksefNumber": "1234567890-20260301-ABC123-XY",
        "invoiceNumber": "FV/2026/03/001",
        "issueDate": "2026-03-01T10:00:00",
        "invoicingDate": "2026-03-01T10:00:00",
        "grossAmount": 1230.00,
        "netAmount": 1000.00,
        "vatAmount": 230.00,
        "currency": "PLN",
        "seller": {
            "name": "Firma ABC Sp. z o.o.",
            "nip": "9876543210"
        },
        "buyer": {
            "name": "Klient XYZ S.A.",
            "nip": "1234567890"
        }
    }


@pytest.fixture
def sample_state():
    """Sample state file content."""
    return {
        "last_check": "2026-03-06T10:00:00+01:00",
        "seen_invoices": [
            {"h": "abc123def456", "ts": "2026-03-06T10:00:00+00:00"}
        ]
    }
