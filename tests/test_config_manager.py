"""
Unit tests for ConfigManager
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestConfigManagerLoadConfig:
    """Tests for config loading and validation."""

    def test_load_valid_config(self, config_file, minimal_config):
        """Load a valid config file successfully."""
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.return_value = minimal_config
            from app.config_manager import ConfigManager
            cm = ConfigManager(config_file)
            assert cm.config["ksef"]["environment"] == "test"
            assert cm.config["ksef"]["nip"] == "1234567890"

    def test_missing_config_file_exits(self, tmp_path):
        """Missing config file should cause sys.exit."""
        with patch("app.config_manager.SecretsManager"):
            from app.config_manager import ConfigManager
            with pytest.raises(SystemExit):
                ConfigManager(str(tmp_path / "nonexistent.json"))

    def test_invalid_json_exits(self, tmp_path):
        """Invalid JSON should cause sys.exit."""
        bad_file = tmp_path / "config.json"
        bad_file.write_text("{invalid json", encoding="utf-8")
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.side_effect = json.JSONDecodeError("err", "doc", 0)
            from app.config_manager import ConfigManager
            with pytest.raises(SystemExit):
                ConfigManager(str(bad_file))

    def test_missing_ksef_section_raises(self, config_file, minimal_config):
        """Missing 'ksef' section should raise ValueError (caught as sys.exit)."""
        del minimal_config["ksef"]
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.return_value = minimal_config
            from app.config_manager import ConfigManager
            with pytest.raises(SystemExit):
                ConfigManager(config_file)

    def test_empty_token_raises(self, config_file, minimal_config):
        """Empty token value should raise ValueError (caught as sys.exit)."""
        minimal_config["ksef"]["token"] = ""
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.return_value = minimal_config
            from app.config_manager import ConfigManager
            with pytest.raises(SystemExit):
                ConfigManager(config_file)


class TestConfigManagerGet:
    """Tests for get() method with dot notation."""

    def test_get_nested_value(self, config_file, minimal_config):
        """Get nested config value."""
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.return_value = minimal_config
            from app.config_manager import ConfigManager
            cm = ConfigManager(config_file)
            assert cm.get("ksef", "environment") == "test"

    def test_get_missing_key_returns_default(self, config_file, minimal_config):
        """Missing key returns default value."""
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.return_value = minimal_config
            from app.config_manager import ConfigManager
            cm = ConfigManager(config_file)
            assert cm.get("nonexistent", "key", default="fallback") == "fallback"

    def test_get_missing_key_returns_none(self, config_file, minimal_config):
        """Missing key without default returns None."""
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.return_value = minimal_config
            from app.config_manager import ConfigManager
            cm = ConfigManager(config_file)
            assert cm.get("nonexistent") is None

    def test_get_single_section(self, config_file, minimal_config):
        """Get entire section as dict."""
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.return_value = minimal_config
            from app.config_manager import ConfigManager
            cm = ConfigManager(config_file)
            ksef = cm.get("ksef")
            assert isinstance(ksef, dict)
            assert ksef["nip"] == "1234567890"


class TestConfigManagerValidateSchedule:
    """Tests for schedule validation."""

    def _make_cm(self, config_file, config):
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.return_value = config
            from app.config_manager import ConfigManager
            return ConfigManager(config_file)

    def test_valid_minutes_schedule(self, config_file, minimal_config):
        """Valid minutes schedule passes validation."""
        cm = self._make_cm(config_file, minimal_config)
        assert cm.config["schedule"]["mode"] == "minutes"

    def test_valid_daily_schedule(self, config_file, minimal_config):
        """Valid daily schedule passes validation."""
        minimal_config["schedule"] = {"mode": "daily", "time": "09:00"}
        cm = self._make_cm(config_file, minimal_config)
        assert cm.config["schedule"]["mode"] == "daily"

    def test_valid_weekly_schedule(self, config_file, minimal_config):
        """Valid weekly schedule passes validation."""
        minimal_config["schedule"] = {
            "mode": "weekly",
            "days": ["monday", "friday"],
            "time": ["09:00", "17:00"]
        }
        cm = self._make_cm(config_file, minimal_config)
        assert cm.config["schedule"]["mode"] == "weekly"

    def test_invalid_mode_raises(self, config_file, minimal_config):
        """Invalid schedule mode raises ValueError."""
        minimal_config["schedule"] = {"mode": "invalid"}
        with pytest.raises(SystemExit):
            self._make_cm(config_file, minimal_config)

    def test_missing_interval_raises(self, config_file, minimal_config):
        """Missing interval for interval-based mode raises ValueError."""
        minimal_config["schedule"] = {"mode": "minutes"}
        with pytest.raises(SystemExit):
            self._make_cm(config_file, minimal_config)

    def test_negative_interval_raises(self, config_file, minimal_config):
        """Negative interval raises ValueError."""
        minimal_config["schedule"] = {"mode": "minutes", "interval": -1}
        with pytest.raises(SystemExit):
            self._make_cm(config_file, minimal_config)

    def test_missing_time_for_daily_raises(self, config_file, minimal_config):
        """Missing time for daily mode raises ValueError."""
        minimal_config["schedule"] = {"mode": "daily"}
        with pytest.raises(SystemExit):
            self._make_cm(config_file, minimal_config)

    def test_missing_days_for_weekly_raises(self, config_file, minimal_config):
        """Missing days for weekly mode raises ValueError."""
        minimal_config["schedule"] = {"mode": "weekly", "time": "09:00"}
        with pytest.raises(SystemExit):
            self._make_cm(config_file, minimal_config)

    def test_invalid_time_format_raises(self, config_file, minimal_config):
        """Invalid time format raises ValueError."""
        minimal_config["schedule"] = {"mode": "daily", "time": "25:00"}
        with pytest.raises(SystemExit):
            self._make_cm(config_file, minimal_config)


class TestConfigManagerValidateTimeFormat:
    """Tests for _validate_time_format."""

    def _get_cm_class(self):
        from app.config_manager import ConfigManager
        return ConfigManager

    def test_valid_time(self):
        """Valid HH:MM format passes."""
        CM = self._get_cm_class()
        # Should not raise
        CM._validate_time_format(None, "09:30")
        CM._validate_time_format(None, "00:00")
        CM._validate_time_format(None, "23:59")

    def test_invalid_hour(self):
        """Hour > 23 raises ValueError."""
        CM = self._get_cm_class()
        with pytest.raises(ValueError, match="Invalid hour"):
            CM._validate_time_format(None, "24:00")

    def test_invalid_minute(self):
        """Minute > 59 raises ValueError."""
        CM = self._get_cm_class()
        with pytest.raises(ValueError, match="Invalid minute"):
            CM._validate_time_format(None, "12:60")

    def test_non_numeric(self):
        """Non-numeric time raises ValueError."""
        CM = self._get_cm_class()
        with pytest.raises(ValueError):
            CM._validate_time_format(None, "ab:cd")

    def test_wrong_format(self):
        """Wrong separator raises ValueError."""
        CM = self._get_cm_class()
        with pytest.raises(ValueError, match="Invalid time format"):
            CM._validate_time_format(None, "0930")


class TestConfigManagerLegacyMigration:
    """Tests for legacy config migration."""

    def test_migrate_old_pushover_config(self, config_file, minimal_config):
        """Old-style pushover config is migrated to notifications section."""
        # Simulate old format: pushover at root, no notifications
        old_config = {
            "ksef": minimal_config["ksef"],
            "monitoring": {
                "subject_types": ["Subject1"],
                "date_type": "Invoicing",
                "timezone": "Europe/Warsaw",
                "message_priority": 1,
                "test_notification": True
            },
            "schedule": minimal_config["schedule"],
            "pushover": {
                "user_key": "old-key",
                "api_token": "old-token"
            }
        }
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.return_value = old_config
            from app.config_manager import ConfigManager
            cm = ConfigManager(config_file)
            assert "notifications" in cm.config
            assert cm.config["notifications"]["channels"] == ["pushover"]
            assert cm.config["notifications"]["pushover"]["user_key"] == "old-key"
            # message_priority moved from monitoring to notifications
            assert cm.config["notifications"]["message_priority"] == 1


class TestConfigManagerStorageDefaults:
    """Tests for storage section defaults."""

    def test_defaults_applied(self, config_file, minimal_config):
        """Storage defaults applied when not present."""
        del minimal_config["storage"]
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.return_value = minimal_config
            from app.config_manager import ConfigManager
            cm = ConfigManager(config_file)
            assert cm.config["storage"]["save_xml"] is False
            assert cm.config["storage"]["save_pdf"] is False
            assert cm.config["storage"]["output_dir"] == "/data/invoices"

    def test_valid_folder_structure(self, config_file, minimal_config):
        """Valid folder_structure with known placeholders passes."""
        minimal_config["storage"]["folder_structure"] = "{year}/{month}"
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.return_value = minimal_config
            from app.config_manager import ConfigManager
            cm = ConfigManager(config_file)
            assert cm.config["storage"]["folder_structure"] == "{year}/{month}"

    def test_invalid_folder_structure_falls_back(self, config_file, minimal_config):
        """Invalid placeholder in folder_structure resets to empty string."""
        minimal_config["storage"]["folder_structure"] = "{year}/{invalid}"
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.return_value = minimal_config
            from app.config_manager import ConfigManager
            cm = ConfigManager(config_file)
            assert cm.config["storage"]["folder_structure"] == ""


class TestConfigManagerTimezone:
    """Tests for timezone validation."""

    def test_default_timezone(self, config_file, minimal_config):
        """Default timezone applied when not configured."""
        del minimal_config["monitoring"]["timezone"]
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.return_value = minimal_config
            from app.config_manager import ConfigManager
            cm = ConfigManager(config_file)
            assert cm.get_timezone() == "Europe/Warsaw"

    def test_valid_custom_timezone(self, config_file, minimal_config):
        """Valid custom timezone is accepted."""
        minimal_config["monitoring"]["timezone"] = "US/Eastern"
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.return_value = minimal_config
            from app.config_manager import ConfigManager
            cm = ConfigManager(config_file)
            assert cm.get_timezone() == "US/Eastern"

    def test_invalid_timezone_falls_back(self, config_file, minimal_config):
        """Invalid timezone falls back to Europe/Warsaw."""
        minimal_config["monitoring"]["timezone"] = "Invalid/TZ"
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.return_value = minimal_config
            from app.config_manager import ConfigManager
            cm = ConfigManager(config_file)
            # _validate_timezone overwrites the invalid value in the config dict
            assert cm.config["monitoring"]["timezone"] == "Europe/Warsaw"


class TestConfigManagerNotificationValidation:
    """Tests for notification channel validation."""

    def _make_cm(self, config_file, config):
        with patch("app.config_manager.SecretsManager") as MockSM:
            MockSM.return_value.load_config_with_secrets.return_value = config
            from app.config_manager import ConfigManager
            return ConfigManager(config_file)

    def test_invalid_webhook_method_raises(self, config_file, minimal_config):
        """Invalid webhook HTTP method raises ValueError."""
        minimal_config["notifications"]["channels"] = ["webhook"]
        minimal_config["notifications"]["webhook"] = {
            "url": "https://example.com/hook",
            "method": "DELETE"
        }
        with pytest.raises(SystemExit):
            self._make_cm(config_file, minimal_config)

    def test_email_to_addresses_must_be_list(self, config_file, minimal_config):
        """email.to_addresses must be a list."""
        minimal_config["notifications"]["channels"] = ["email"]
        minimal_config["notifications"]["email"] = {
            "smtp_server": "smtp.example.com",
            "username": "user",
            "password": "pass",
            "from_address": "from@example.com",
            "to_addresses": "not-a-list@example.com"
        }
        with pytest.raises(SystemExit):
            self._make_cm(config_file, minimal_config)

    def test_channels_not_list_raises(self, config_file, minimal_config):
        """channels must be a list."""
        minimal_config["notifications"]["channels"] = "pushover"
        with pytest.raises(SystemExit):
            self._make_cm(config_file, minimal_config)
