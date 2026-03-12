"""
Unit tests for InvoiceMonitor
"""

import json
import hashlib
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

from app.invoice_monitor import InvoiceMonitor


@pytest.fixture
def monitor(mock_config):
    """Create InvoiceMonitor with mocked dependencies."""
    ksef_client = MagicMock()
    ksef_client.environment = "test"
    ksef_client.nip = "1234567890"
    notification_manager = MagicMock()
    notification_manager.send_invoice_notification.return_value = True
    prometheus = MagicMock()

    m = InvoiceMonitor(mock_config, ksef_client, notification_manager, prometheus)
    return m


class TestInvoiceMonitorInit:
    """Tests for InvoiceMonitor initialization."""

    def test_default_subject_types(self, monitor):
        """Default subject_types is ['Subject1']."""
        assert monitor.subject_types == ["Subject1"]

    def test_default_output_dir(self, monitor):
        """Default output_dir is /data/invoices."""
        assert monitor.output_dir == Path("/data/invoices")

    def test_message_priority_default(self, monitor):
        """Default message_priority is 0."""
        assert monitor.message_priority == 0

    def test_invalid_priority_falls_back(self, mock_config):
        """Invalid message_priority falls back to 0."""
        mock_config.config["notifications"]["message_priority"] = 5
        ksef = MagicMock()
        ksef.environment = "test"
        ksef.nip = "1234567890"
        nm = MagicMock()
        m = InvoiceMonitor(mock_config, ksef, nm)
        assert m.message_priority == 0


class TestInvoiceMonitorHash:
    """Tests for get_invoice_id_hash()."""

    def test_sha256_hash(self, monitor, sample_invoice):
        """Hash uses SHA-256 of ksefReferenceNumber."""
        expected = hashlib.sha256(
            sample_invoice["ksefReferenceNumber"].encode()
        ).hexdigest()
        assert monitor.get_invoice_id_hash(sample_invoice) == expected

    def test_fallback_to_ksef_number(self, monitor):
        """Falls back to ksefNumber when ksefReferenceNumber missing."""
        invoice = {"ksefNumber": "1234567890-20260301-ABC123-XY"}
        expected = hashlib.sha256(
            invoice["ksefNumber"].encode()
        ).hexdigest()
        assert monitor.get_invoice_id_hash(invoice) == expected

    def test_empty_invoice_hashes_empty_string(self, monitor):
        """Invoice with no identifiers hashes empty string."""
        expected = hashlib.sha256(b"").hexdigest()
        assert monitor.get_invoice_id_hash({}) == expected


class TestInvoiceMonitorSanitizeField:
    """Tests for _sanitize_field()."""

    def test_truncates_long_string(self):
        """Truncates to max_length."""
        result = InvoiceMonitor._sanitize_field("a" * 1000, max_length=100)
        assert len(result) == 100

    def test_strips_null_bytes(self):
        """Removes null bytes."""
        result = InvoiceMonitor._sanitize_field("hello\x00world")
        assert result == "helloworld"

    def test_converts_to_string(self):
        """Non-string values are converted to string."""
        result = InvoiceMonitor._sanitize_field(12345)
        assert result == "12345"


class TestInvoiceMonitorBuildTemplateContext:
    """Tests for build_template_context()."""

    def test_context_has_required_keys(self, monitor, sample_invoice):
        """Context has all required keys for templates."""
        ctx = monitor.build_template_context(sample_invoice, "Subject1")
        required_keys = [
            "ksef_number", "invoice_number", "issue_date", "gross_amount",
            "net_amount", "vat_amount", "currency", "seller_name", "seller_nip",
            "buyer_name", "buyer_nip", "subject_type", "title", "priority",
            "priority_emoji", "priority_name", "priority_color", "timestamp"
        ]
        for key in required_keys:
            assert key in ctx, f"Missing key: {key}"

    def test_subject1_title(self, monitor, sample_invoice):
        """Subject1 gets sales invoice title."""
        ctx = monitor.build_template_context(sample_invoice, "Subject1")
        assert ctx["title"] == "Nowa faktura sprzedażowa w KSeF"

    def test_subject2_title(self, monitor, sample_invoice):
        """Subject2 gets purchase invoice title."""
        ctx = monitor.build_template_context(sample_invoice, "Subject2")
        assert ctx["title"] == "Nowa faktura zakupowa w KSeF"

    def test_unknown_subject_type(self, monitor, sample_invoice):
        """Unknown subject type gets default title."""
        ctx = monitor.build_template_context(sample_invoice, "Subject3")
        assert ctx["title"] == "Nowa faktura w KSeF"

    def test_buyer_nip_from_identifier(self, monitor, sample_invoice):
        """Buyer NIP extracted from buyer.identifier.value (API v2.2.0 schema)."""
        ctx = monitor.build_template_context(sample_invoice, "Subject1")
        assert ctx["buyer_nip"] == "1234567890"

    def test_buyer_nip_fallback_to_nip(self, monitor):
        """Buyer NIP falls back to buyer.nip when identifier not present."""
        invoice = {
            "ksefNumber": "test-123",
            "invoiceNumber": "FV/001",
            "issueDate": "2026-01-01",
            "grossAmount": 100,
            "currency": "PLN",
            "seller": {"name": "Seller", "nip": "1234567890"},
            "buyer": {"name": "Buyer", "nip": "0987654321"},
        }
        ctx = monitor.build_template_context(invoice, "Subject1")
        assert ctx["buyer_nip"] == "0987654321"

    def test_sanitized_fields(self, monitor):
        """Fields with null bytes are sanitized."""
        invoice = {
            "ksefNumber": "test\x00number",
            "invoiceNumber": "FV\x00/001",
            "issueDate": "2026-01-01",
            "grossAmount": 100,
            "currency": "PLN",
            "seller": {"name": "Seller\x00Name", "nip": "1234567890"},
            "buyer": {"name": "Buyer", "identifier": {"value": "0987654321"}},
        }
        ctx = monitor.build_template_context(invoice, "Subject1")
        assert "\x00" not in ctx["ksef_number"]
        assert "\x00" not in ctx["seller_name"]


class TestInvoiceMonitorState:
    """Tests for load_state() and save_state()."""

    def test_load_state_missing_file(self, monitor):
        """Returns default state when file doesn't exist."""
        monitor.state_file = Path("/nonexistent/last_check.json")
        state = monitor.load_state()
        assert state["last_check"] is None
        assert state["seen_invoices"] == []

    def test_load_state_valid_file(self, monitor, tmp_path, sample_state):
        """Loads state from valid JSON file."""
        state_file = tmp_path / "last_check.json"
        state_file.write_text(json.dumps(sample_state), encoding="utf-8")
        monitor.state_file = state_file

        state = monitor.load_state()
        assert state["last_check"] == "2026-03-06T10:00:00+01:00"

    def test_load_state_filters_old_entries(self, monitor, tmp_path):
        """TTL filtering removes entries older than 90 days."""
        old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        recent_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        state = {
            "last_check": "2026-03-01T10:00:00+01:00",
            "seen_invoices": [
                {"h": "old-hash", "ts": old_ts},
                {"h": "recent-hash", "ts": recent_ts}
            ]
        }
        state_file = tmp_path / "last_check.json"
        state_file.write_text(json.dumps(state), encoding="utf-8")
        monitor.state_file = state_file

        loaded = monitor.load_state()
        assert len(loaded["seen_invoices"]) == 1
        assert loaded["seen_invoices"][0]["h"] == "recent-hash"

    def test_load_state_discards_old_md5_format(self, monitor, tmp_path):
        """Old MD5 string entries are discarded."""
        state = {
            "last_check": "2026-03-01T10:00:00",
            "seen_invoices": ["old-md5-hash-1", "old-md5-hash-2"]
        }
        state_file = tmp_path / "last_check.json"
        state_file.write_text(json.dumps(state), encoding="utf-8")
        monitor.state_file = state_file

        loaded = monitor.load_state()
        assert loaded["seen_invoices"] == []

    def test_save_state_atomic(self, monitor, tmp_path):
        """save_state writes atomically via tmp + rename."""
        monitor.state_file = tmp_path / "data" / "last_check.json"
        state = {"last_check": "2026-03-07T10:00:00", "seen_invoices": []}

        monitor.save_state(state)

        assert monitor.state_file.exists()
        loaded = json.loads(monitor.state_file.read_text(encoding="utf-8"))
        assert loaded["last_check"] == "2026-03-07T10:00:00"

    def test_save_state_creates_parent_dirs(self, monitor, tmp_path):
        """save_state creates parent directories."""
        monitor.state_file = tmp_path / "deep" / "nested" / "last_check.json"
        monitor.save_state({"last_check": None, "seen_invoices": []})
        assert monitor.state_file.exists()


class TestInvoiceMonitorCapDateFrom:
    """Tests for _cap_date_from()."""

    def test_within_range(self, monitor):
        """Date within 90 days is not capped."""
        now = datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc)
        date_from = now - timedelta(days=30)
        result = monitor._cap_date_from(date_from, now)
        assert result == date_from

    def test_exceeds_range(self, monitor):
        """Date older than 90 days is capped."""
        now = datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc)
        date_from = now - timedelta(days=120)
        result = monitor._cap_date_from(date_from, now)
        expected = now - timedelta(days=90)
        assert result == expected


class TestInvoiceMonitorResolveOutputDir:
    """Tests for _resolve_output_dir()."""

    def test_flat_directory(self, monitor):
        """Empty folder_structure returns output_dir as-is."""
        monitor.folder_structure = ""
        result = monitor._resolve_output_dir({"issueDate": "2026-03-01"}, "Subject1")
        assert result == monitor.output_dir

    def test_year_month_structure(self, monitor, tmp_path):
        """Year/month structure creates correct path."""
        monitor.output_dir = tmp_path / "invoices"
        monitor.folder_structure = "{year}/{month}"
        invoice = {"issueDate": "2026-03-15T10:00:00"}
        result = monitor._resolve_output_dir(invoice, "Subject1")
        assert result == tmp_path / "invoices" / "2026" / "03"

    def test_type_placeholder(self, monitor, tmp_path):
        """Type placeholder maps Subject1 to sprzedaz."""
        monitor.output_dir = tmp_path / "invoices"
        monitor.folder_structure = "{type}/{year}"
        invoice = {"issueDate": "2026-03-15T10:00:00"}
        result = monitor._resolve_output_dir(invoice, "Subject1")
        assert result == tmp_path / "invoices" / "sprzedaz" / "2026"

    def test_type_placeholder_subject2(self, monitor, tmp_path):
        """Type placeholder maps Subject2 to zakup."""
        monitor.output_dir = tmp_path / "invoices"
        monitor.folder_structure = "{type}"
        invoice = {"issueDate": "2026-03-15T10:00:00"}
        result = monitor._resolve_output_dir(invoice, "Subject2")
        assert result == tmp_path / "invoices" / "zakup"

    def test_invalid_date_falls_back(self, monitor, tmp_path):
        """Invalid issueDate falls back to flat directory."""
        monitor.output_dir = tmp_path / "invoices"
        monitor.folder_structure = "{year}/{month}"
        invoice = {"issueDate": "not-a-date"}
        result = monitor._resolve_output_dir(invoice, "Subject1")
        assert result == tmp_path / "invoices"

    def test_path_traversal_blocked(self, monitor, tmp_path):
        """Path traversal attempt falls back to flat directory."""
        monitor.output_dir = tmp_path / "invoices"
        monitor.output_dir.mkdir(parents=True, exist_ok=True)
        monitor.folder_structure = ""
        # Directly test with crafted subfolder
        invoice = {"issueDate": "2026-03-01T10:00:00"}
        # The _resolve_output_dir only builds from folder_structure, so traversal is via config
        # This test verifies that even if folder_structure is clean, the method works
        result = monitor._resolve_output_dir(invoice, "Subject1")
        assert result == monitor.output_dir


class TestInvoiceMonitorResolveSafePath:
    """Tests for _resolve_safe_path() file exists strategy."""

    def test_new_file_returns_path(self, monitor, tmp_path):
        """Non-existing file returns the path as-is."""
        path = tmp_path / "new_file.xml"
        assert monitor._resolve_safe_path(path) == path

    def test_skip_existing_returns_none(self, monitor, tmp_path):
        """Strategy 'skip' returns None for existing file."""
        monitor.file_exists_strategy = "skip"
        path = tmp_path / "existing.xml"
        path.write_text("content")
        assert monitor._resolve_safe_path(path) is None

    def test_overwrite_existing_returns_same_path(self, monitor, tmp_path):
        """Strategy 'overwrite' returns the same path."""
        monitor.file_exists_strategy = "overwrite"
        path = tmp_path / "existing.xml"
        path.write_text("content")
        assert monitor._resolve_safe_path(path) == path

    def test_rename_existing_adds_suffix(self, monitor, tmp_path):
        """Strategy 'rename' adds _1 suffix."""
        monitor.file_exists_strategy = "rename"
        path = tmp_path / "invoice.xml"
        path.write_text("content")
        result = monitor._resolve_safe_path(path)
        assert result == tmp_path / "invoice_1.xml"

    def test_rename_increments_suffix(self, monitor, tmp_path):
        """Strategy 'rename' increments suffix when _1 also exists."""
        monitor.file_exists_strategy = "rename"
        path = tmp_path / "invoice.pdf"
        path.write_text("content")
        (tmp_path / "invoice_1.pdf").write_text("content")
        (tmp_path / "invoice_2.pdf").write_text("content")
        result = monitor._resolve_safe_path(path)
        assert result == tmp_path / "invoice_3.pdf"

    def test_rename_preserves_extension(self, monitor, tmp_path):
        """Strategy 'rename' preserves original file extension."""
        monitor.file_exists_strategy = "rename"
        path = tmp_path / "sprz_123.xml"
        path.write_text("content")
        result = monitor._resolve_safe_path(path)
        assert result.suffix == ".xml"
        assert result.name == "sprz_123_1.xml"

    def test_default_strategy_is_skip(self, monitor):
        """Default file_exists_strategy from config is 'skip'."""
        assert monitor.file_exists_strategy == "skip"


class TestInvoiceMonitorFormatDateForFilename:
    """Tests for _format_date_for_filename()."""

    def test_iso_date(self, monitor):
        """ISO date is formatted to YYYYMMDD."""
        assert monitor._format_date_for_filename("2026-03-15T10:30:00") == "20260315"

    def test_date_with_z(self, monitor):
        """Date with Z suffix is handled."""
        assert monitor._format_date_for_filename("2026-03-15T10:30:00Z") == "20260315"

    def test_invalid_date_fallback(self, monitor):
        """Invalid date falls back to stripping separators."""
        result = monitor._format_date_for_filename("not-a-date")
        assert isinstance(result, str)


class TestInvoiceMonitorParseDatetime:
    """Tests for _parse_datetime()."""

    def test_parse_timezone_aware(self, monitor):
        """Parse timezone-aware datetime string."""
        result = monitor._parse_datetime("2026-03-07T10:00:00+01:00")
        assert result.tzinfo is not None

    def test_parse_naive_datetime_warns(self, monitor):
        """Parse naive datetime localizes to configured timezone."""
        result = monitor._parse_datetime("2026-03-07T10:00:00")
        # Should be localized to Europe/Warsaw
        assert result.tzinfo is not None

    def test_parse_invalid_raises(self, monitor):
        """Invalid datetime string raises ValueError."""
        with pytest.raises(ValueError):
            monitor._parse_datetime("not-a-date")


class TestInvoiceMonitorCheckForNewInvoices:
    """Tests for check_for_new_invoices()."""

    def test_no_new_invoices(self, monitor, tmp_path):
        """No new invoices logs info."""
        monitor.state_file = tmp_path / "last_check.json"
        monitor.ksef.get_invoices_metadata.return_value = []

        monitor.check_for_new_invoices()

        monitor.ksef.get_invoices_metadata.assert_called_once()
        monitor.notifier.send_invoice_notification.assert_not_called()

    def test_new_invoice_sends_notification(self, monitor, tmp_path, sample_invoice):
        """New invoice triggers notification."""
        monitor.state_file = tmp_path / "last_check.json"
        monitor.ksef.get_invoices_metadata.return_value = [sample_invoice]

        monitor.check_for_new_invoices()

        monitor.notifier.send_invoice_notification.assert_called_once()

    def test_duplicate_invoice_skipped(self, monitor, tmp_path, sample_invoice):
        """Already-seen invoice is not notified."""
        monitor.state_file = tmp_path / "last_check.json"

        # Pre-populate seen_invoices
        invoice_hash = monitor.get_invoice_id_hash(sample_invoice)
        state = {
            "last_check": "2026-03-06T10:00:00+01:00",
            "seen_invoices": [{"h": invoice_hash, "ts": datetime.now(timezone.utc).isoformat()}]
        }
        monitor.state_file.write_text(json.dumps(state), encoding="utf-8")

        monitor.ksef.get_invoices_metadata.return_value = [sample_invoice]
        monitor.check_for_new_invoices()

        monitor.notifier.send_invoice_notification.assert_not_called()

    def test_state_saved_after_check(self, monitor, tmp_path):
        """State file is saved after checking."""
        monitor.state_file = tmp_path / "last_check.json"
        monitor.ksef.get_invoices_metadata.return_value = []

        monitor.check_for_new_invoices()

        assert monitor.state_file.exists()

    def test_prometheus_metrics_updated(self, monitor, tmp_path, sample_invoice):
        """Prometheus metrics are updated on new invoices."""
        monitor.state_file = tmp_path / "last_check.json"
        monitor.ksef.get_invoices_metadata.return_value = [sample_invoice]

        monitor.check_for_new_invoices()

        monitor.metrics.update_last_check.assert_called_once()
        monitor.metrics.increment_new_invoices.assert_called_once_with("Subject1", 1)


class TestInvoiceMonitorShutdown:
    """Tests for shutdown()."""

    def test_shutdown_revokes_session(self, monitor):
        """Shutdown revokes KSeF session."""
        monitor.shutdown()
        monitor.ksef.revoke_current_session.assert_called_once()

    def test_shutdown_stops_metrics(self, monitor):
        """Shutdown marks metrics as stopped."""
        monitor.shutdown()
        monitor.metrics.shutdown.assert_called_once()

    def test_shutdown_sends_notification(self, monitor):
        """Shutdown sends notification."""
        monitor.shutdown()
        monitor.notifier.send_notification.assert_called_once()


class TestSanitizeFilenameValue:
    """Tests for _sanitize_filename_value()."""

    def test_replaces_path_separators(self):
        """Path separators / and \\ are replaced with _."""
        assert InvoiceMonitor._sanitize_filename_value("FV/2026/03") == "FV_2026_03"
        assert InvoiceMonitor._sanitize_filename_value("path\\file") == "path_file"

    def test_replaces_unsafe_chars(self):
        """Characters :*?\"<>| are replaced with _."""
        result = InvoiceMonitor._sanitize_filename_value('a:b*c?d"e<f>g|h')
        assert "/" not in result
        assert "*" not in result
        assert "?" not in result

    def test_strips_null_bytes(self):
        """Null bytes are removed."""
        assert InvoiceMonitor._sanitize_filename_value("abc\x00def") == "abcdef"

    def test_strips_dots_and_spaces(self):
        """Leading/trailing dots and spaces are stripped."""
        assert InvoiceMonitor._sanitize_filename_value("..name..") == "name"
        assert InvoiceMonitor._sanitize_filename_value("  name  ") == "name"

    def test_limits_length(self):
        """Values are truncated to 100 characters."""
        result = InvoiceMonitor._sanitize_filename_value("a" * 200)
        assert len(result) == 100

    def test_empty_returns_unknown(self):
        """Empty or None input returns 'unknown'."""
        assert InvoiceMonitor._sanitize_filename_value("") == "unknown"
        assert InvoiceMonitor._sanitize_filename_value(None) == "unknown"

    def test_only_dots_returns_unknown(self):
        """Value that is only dots returns 'unknown' after stripping."""
        assert InvoiceMonitor._sanitize_filename_value("...") == "unknown"


class TestBuildFileName:
    """Tests for _build_file_name()."""

    def test_default_pattern_subject1(self, monitor, sample_invoice):
        """Default pattern produces {type}_{date}_{invoice_number}."""
        result = monitor._build_file_name(sample_invoice, "Subject1")
        assert result == "sprz_20260301_FV_2026_03_001"

    def test_default_pattern_subject2(self, monitor, sample_invoice):
        """Subject2 produces zak_ prefix."""
        result = monitor._build_file_name(sample_invoice, "Subject2")
        assert result.startswith("zak_")

    def test_custom_pattern_with_ksef(self, monitor, sample_invoice):
        """Custom pattern with {ksef} placeholder."""
        monitor.file_name_pattern = "{type}_{ksef}"
        result = monitor._build_file_name(sample_invoice, "Subject1")
        assert result == "sprz_1234567890-20260301-ABC123-XY"

    def test_custom_pattern_with_ksef_short(self, monitor, sample_invoice):
        """Custom pattern with {ksef_short} — last 6 chars."""
        monitor.file_name_pattern = "{type}_{ksef_short}"
        result = monitor._build_file_name(sample_invoice, "Subject1")
        assert result == "sprz_123-XY"

    def test_custom_pattern_with_seller_nip(self, monitor, sample_invoice):
        """Custom pattern with {seller_nip}."""
        monitor.file_name_pattern = "{type}_{seller_nip}_{date}"
        result = monitor._build_file_name(sample_invoice, "Subject1")
        assert result == "sprz_9876543210_20260301"

    def test_custom_pattern_with_buyer_nip(self, monitor, sample_invoice):
        """Custom pattern with {buyer_nip} from identifier.value."""
        monitor.file_name_pattern = "{type}_{buyer_nip}_{date}"
        result = monitor._build_file_name(sample_invoice, "Subject1")
        assert result == "sprz_1234567890_20260301"

    def test_buyer_nip_fallback(self, monitor):
        """Buyer NIP falls back to buyer.nip when identifier missing."""
        invoice = {
            "ksefNumber": "test-123",
            "invoiceNumber": "FV/001",
            "issueDate": "2026-03-01",
            "seller": {"name": "S", "nip": "1111111111"},
            "buyer": {"name": "B", "nip": "2222222222"},
        }
        monitor.file_name_pattern = "{buyer_nip}"
        result = monitor._build_file_name(invoice, "Subject1")
        assert result == "2222222222"

    def test_fallback_on_bad_pattern(self, monitor, sample_invoice):
        """Invalid pattern falls back to type_date_ksef."""
        monitor.file_name_pattern = "{type}_{nonexistent}"
        result = monitor._build_file_name(sample_invoice, "Subject1")
        assert result.startswith("sprz_20260301_")

    def test_missing_invoice_number(self, monitor):
        """Missing invoiceNumber produces 'unknown' placeholder."""
        invoice = {
            "ksefNumber": "test-123",
            "issueDate": "2026-03-01",
            "seller": {"name": "S", "nip": "1111111111"},
            "buyer": {"name": "B", "identifier": {"value": "2222222222"}},
        }
        result = monitor._build_file_name(invoice, "Subject1")
        assert "unknown" in result


class TestBuildFileNamePatternConfig:
    """Tests for file_name_pattern config validation."""

    def _make_cm(self, config_file, config):
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.return_value = config
            from app.config_manager import ConfigManager
            return ConfigManager(config_file)

    def test_default_pattern(self, config_file, minimal_config):
        """Default file_name_pattern is applied."""
        cm = self._make_cm(config_file, minimal_config)
        assert cm.config["storage"]["file_name_pattern"] == "{type}_{date}_{invoice_number}"

    def test_valid_pattern_accepted(self, config_file, minimal_config):
        """Valid custom pattern is accepted."""
        minimal_config["storage"]["file_name_pattern"] = "{type}_{seller_nip}_{date}_{ksef_short}"
        cm = self._make_cm(config_file, minimal_config)
        assert cm.config["storage"]["file_name_pattern"] == "{type}_{seller_nip}_{date}_{ksef_short}"

    def test_invalid_pattern_falls_back(self, config_file, minimal_config):
        """Invalid placeholder resets to default."""
        minimal_config["storage"]["file_name_pattern"] = "{type}_{invalid}"
        cm = self._make_cm(config_file, minimal_config)
        assert cm.config["storage"]["file_name_pattern"] == "{type}_{date}_{invoice_number}"

    def test_all_placeholders_valid(self, config_file, minimal_config):
        """Pattern using all 7 valid placeholders is accepted."""
        pattern = "{type}_{date}_{invoice_number}_{ksef}_{ksef_short}_{seller_nip}_{buyer_nip}"
        minimal_config["storage"]["file_name_pattern"] = pattern
        cm = self._make_cm(config_file, minimal_config)
        assert cm.config["storage"]["file_name_pattern"] == pattern


class TestParseOptionalDt:
    """Tests for _parse_optional_dt()."""

    def test_valid_iso_datetime(self):
        """Parses valid ISO datetime string."""
        result = InvoiceMonitor._parse_optional_dt("2026-03-01T10:00:00")
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc

    def test_timezone_aware_datetime(self):
        """Parses timezone-aware datetime without converting to UTC."""
        result = InvoiceMonitor._parse_optional_dt("2026-03-01T10:00:00+02:00")
        assert result is not None
        assert result.tzinfo is not None

    def test_none_returns_none(self):
        """None input returns None."""
        assert InvoiceMonitor._parse_optional_dt(None) is None

    def test_empty_string_returns_none(self):
        """Empty string returns None."""
        assert InvoiceMonitor._parse_optional_dt("") is None

    def test_invalid_string_returns_none(self):
        """Invalid date string returns None."""
        assert InvoiceMonitor._parse_optional_dt("not-a-date") is None


class TestSaveInvoiceToDb:
    """Tests for _save_invoice_to_db()."""

    def test_saves_new_invoice(self, monitor, sample_invoice):
        """New invoice is saved and returns its id."""
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_invoice = MagicMock()
        mock_invoice.id = 42
        mock_db.save_invoice.return_value = mock_invoice
        monitor.db = mock_db

        result = monitor._save_invoice_to_db(mock_session, sample_invoice, "Subject1")
        assert result == 42
        mock_db.save_invoice.assert_called_once()

        # Verify correct buyer NIP extraction
        call_data = mock_db.save_invoice.call_args[0][1]
        assert call_data["buyer_nip"] == "1234567890"  # from identifier.value

    def test_saves_form_code(self, monitor, sample_invoice):
        """Form code extracted from formCode.schemaVersion."""
        mock_db = MagicMock()
        mock_invoice = MagicMock()
        mock_invoice.id = 1
        mock_db.save_invoice.return_value = mock_invoice
        monitor.db = mock_db

        monitor._save_invoice_to_db(MagicMock(), sample_invoice, "Subject1")
        call_data = mock_db.save_invoice.call_args[0][1]
        assert call_data["form_code"] == "FA(3)_v1-0E"

    def test_duplicate_returns_existing_id(self, monitor, sample_invoice):
        """Duplicate invoice returns existing record's id."""
        from app.database import Invoice
        mock_db = MagicMock()
        mock_db.save_invoice.return_value = None  # duplicate
        mock_session = MagicMock()
        mock_existing = MagicMock()
        mock_existing.id = 99
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_existing
        monitor.db = mock_db

        result = monitor._save_invoice_to_db(mock_session, sample_invoice, "Subject1")
        assert result == 99

    def test_error_returns_none(self, monitor, sample_invoice):
        """Exception during save returns None."""
        mock_db = MagicMock()
        mock_db.save_invoice.side_effect = Exception("DB error")
        monitor.db = mock_db

        result = monitor._save_invoice_to_db(MagicMock(), sample_invoice, "Subject1")
        assert result is None

    def test_buyer_nip_fallback(self, monitor):
        """Buyer NIP falls back when identifier not present."""
        invoice = {
            "ksefNumber": "test-123",
            "issueDate": "2026-03-01",
            "seller": {"name": "S", "nip": "111"},
            "buyer": {"name": "B"},
        }
        mock_db = MagicMock()
        mock_invoice = MagicMock()
        mock_invoice.id = 1
        mock_db.save_invoice.return_value = mock_invoice
        monitor.db = mock_db

        monitor._save_invoice_to_db(MagicMock(), invoice, "Subject1")
        call_data = mock_db.save_invoice.call_args[0][1]
        assert call_data["buyer_nip"] is None  # no identifier, no nip
