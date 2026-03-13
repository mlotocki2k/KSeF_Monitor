"""
Configuration Manager for KSeF Monitor
Handles loading and validation of JSON configuration with secrets support
"""

import json
import re
import secrets
import sys
import logging
from pathlib import Path
from typing import Dict, Any, Optional

# Handle imports for both package and direct execution
try:
    from .secrets_manager import SecretsManager
except ImportError:
    from app.secrets_manager import SecretsManager

# Optional timezone support
try:
    import pytz
    PYTZ_AVAILABLE = True
except ImportError:
    PYTZ_AVAILABLE = False

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages application configuration from JSON file with secrets support"""
    
    def __init__(self, config_path: str = "/data/config.json"):
        """
        Initialize configuration manager
        
        Args:
            config_path: Path to configuration JSON file
        """
        self.config_path = Path(config_path)
        self.secrets_manager = SecretsManager(config_path)
        self.config = self.load_config()
    
    def load_config(self) -> Dict[str, Any]:
        """
        Load configuration from JSON file with secrets injection
        
        Returns:
            Configuration dictionary
            
        Raises:
            SystemExit: If configuration file is missing or invalid
        """
        if not self.config_path.exists():
            logger.error(f"Configuration file not found: {self.config_path}")
            logger.error("Please create config.json file. See config.example.json for template.")
            sys.exit(1)
        
        try:
            # Load config with secrets injected from environment/Docker secrets
            config = self.secrets_manager.load_config_with_secrets()

            # Migrate legacy config format if needed
            config = self._migrate_legacy_config(config)

            # Validate required fields (including secrets)
            self._validate_config(config)

            logger.info("Configuration loaded successfully")
            return config
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            sys.exit(1)

    def _migrate_legacy_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Migrate legacy configuration format to new multi-channel notifications format

        Args:
            config: Configuration dictionary

        Returns:
            Migrated configuration dictionary
        """
        # Check if we have old-style pushover config at root level without notifications section
        if "pushover" in config and "notifications" not in config:
            logger.warning("=" * 70)
            logger.warning("Detected legacy Pushover-only configuration format")
            logger.warning("Automatically migrating to new multi-channel notifications format")
            logger.warning("Please update your config.json to use the 'notifications' section")
            logger.warning("See examples/config.example.json for the new format")
            logger.warning("=" * 70)

            # Migrate to new format
            config["notifications"] = {
                "channels": ["pushover"],
                "message_priority": config.get("monitoring", {}).get("message_priority", 0),
                "test_notification": config.get("monitoring", {}).get("test_notification", False),
                "pushover": config["pushover"]
            }

            # Remove message_priority and test_notification from monitoring (now in notifications)
            if "monitoring" in config:
                config["monitoring"].pop("message_priority", None)
                config["monitoring"].pop("test_notification", None)

        return config

    def _validate_config(self, config: Dict[str, Any]):
        """
        Validate configuration has required fields

        Args:
            config: Configuration dictionary to validate

        Raises:
            ValueError: If required fields are missing
        """
        required_fields = {
            "ksef": ["environment", "nip", "token"],
            "monitoring": []  # check_interval is deprecated, schedule section is now used
        }

        for section, fields in required_fields.items():
            if section not in config:
                raise ValueError(f"Missing required section: {section}")
            for field in fields:
                if field not in config[section]:
                    raise ValueError(f"Missing required field: {section}.{field}")
                if not config[section][field]:
                    raise ValueError(f"Empty value for required field: {section}.{field}")

        # Validate schedule section (if present, otherwise fallback to deprecated check_interval)
        if "schedule" in config:
            self._validate_schedule(config["schedule"])
        elif "check_interval" not in config.get("monitoring", {}):
            raise ValueError("Missing schedule configuration. Either 'schedule' section or deprecated 'monitoring.check_interval' is required.")

        # Validate notifications section (optional but recommended)
        if "notifications" in config:
            self._validate_notifications(config["notifications"])
        else:
            logger.warning("No 'notifications' section found - notifications disabled")

        # Validate timezone (optional, defaults to Europe/Warsaw)
        self._validate_timezone(config)

        # Set database defaults
        self._apply_database_defaults(config)

        # Set storage defaults
        self._apply_storage_defaults(config)

        # Set rate limit defaults
        self._apply_rate_limit_defaults(config)

        # Set API defaults
        self._apply_api_defaults(config)

    def _validate_schedule(self, schedule: Dict[str, Any]):
        """
        Validate schedule configuration based on mode

        Args:
            schedule: Schedule configuration dictionary

        Raises:
            ValueError: If schedule configuration is invalid
        """
        if "mode" not in schedule:
            raise ValueError("Missing required field: schedule.mode")

        mode = schedule.get("mode", "").lower()

        # Validate interval-based modes (simple, minutes, hourly)
        if mode in ["simple", "minutes", "hourly"]:
            if "interval" not in schedule:
                raise ValueError(f"Missing required field 'interval' for schedule mode '{mode}'")
            if not isinstance(schedule["interval"], (int, float)) or schedule["interval"] <= 0:
                raise ValueError(f"Field 'schedule.interval' must be a positive number for mode '{mode}'")

        # Validate time-based modes (daily, weekly)
        elif mode in ["daily", "weekly"]:
            if "time" not in schedule:
                raise ValueError(f"Missing required field 'time' for schedule mode '{mode}'")

            # Validate time format (can be string or list of strings)
            time_config = schedule["time"]
            if isinstance(time_config, str):
                self._validate_time_format(time_config)
            elif isinstance(time_config, list):
                if not time_config:
                    raise ValueError("Field 'schedule.time' cannot be an empty list")
                for time_str in time_config:
                    if not isinstance(time_str, str):
                        raise ValueError("All items in 'schedule.time' list must be strings")
                    self._validate_time_format(time_str)
            else:
                raise ValueError("Field 'schedule.time' must be a string or list of strings")

            # Additional validation for weekly mode
            if mode == "weekly":
                if "days" not in schedule:
                    raise ValueError("Missing required field 'days' for schedule mode 'weekly'")
                if not isinstance(schedule["days"], list) or not schedule["days"]:
                    raise ValueError("Field 'schedule.days' must be a non-empty list")

        elif mode:
            raise ValueError(f"Invalid schedule mode: '{mode}'. Valid modes: simple, minutes, hourly, daily, weekly")
        else:
            raise ValueError("Field 'schedule.mode' cannot be empty")

    def _validate_time_format(self, time_str: str):
        """
        Validate time string is in HH:MM format

        Args:
            time_str: Time string to validate

        Raises:
            ValueError: If time format is invalid
        """
        try:
            parts = time_str.split(":")
            if len(parts) != 2:
                raise ValueError(f"Invalid time format '{time_str}'. Expected HH:MM")

            hour = int(parts[0])
            minute = int(parts[1])

            if not (0 <= hour < 24):
                raise ValueError(f"Invalid hour in '{time_str}'. Hour must be 0-23")
            if not (0 <= minute < 60):
                raise ValueError(f"Invalid minute in '{time_str}'. Minute must be 0-59")
        except ValueError as e:
            if "invalid literal" in str(e):
                raise ValueError(f"Invalid time format '{time_str}'. Expected HH:MM with numeric values")
            raise

    def _validate_notifications(self, notifications: Dict[str, Any]):
        """
        Validate notifications configuration

        Args:
            notifications: Notifications configuration dictionary

        Raises:
            ValueError: If notifications configuration is invalid
        """
        channels = notifications.get("channels", [])

        if not isinstance(channels, list):
            raise ValueError("Field 'notifications.channels' must be a list")

        if not channels:
            logger.warning("No notification channels enabled in config - notifications disabled")
            return

        # Validate each enabled channel using data-driven rules
        for channel in channels:
            if channel not in self._CHANNEL_VALIDATORS:
                logger.warning(f"Unknown notification channel: '{channel}' - skipping")
                continue

            if channel in notifications:
                self._validate_channel(channel, notifications[channel])

        # Validate optional templates_dir
        templates_dir = notifications.get("templates_dir")
        if templates_dir:
            from pathlib import Path
            if not Path(templates_dir).is_dir():
                logger.warning(
                    f"Custom templates directory not found: {templates_dir}. "
                    f"Built-in defaults will be used."
                )

    # Data-driven channel validation rules
    _CHANNEL_VALIDATORS = {
        "pushover": {"required_warn": ["user_key", "api_token"]},
        "discord":  {"required_warn": ["webhook_url"]},
        "slack":    {"required_warn": ["webhook_url"]},
        "email":    {"required_warn": ["smtp_server", "username", "password",
                                        "from_address", "to_addresses"],
                     "list_fields": ["to_addresses"]},
        "webhook":  {"required_warn": ["url"],
                     "enum_fields": {"method": ["GET", "POST", "PUT"]}},
    }

    def _validate_channel(self, channel_name: str, channel_config: Dict[str, Any]):
        """Validate a notification channel config against its rules."""
        rules = self._CHANNEL_VALIDATORS.get(channel_name, {})

        # Check required fields (warn if missing)
        for field in rules.get("required_warn", []):
            if not channel_config.get(field):
                logger.warning(f"{channel_name.capitalize()} enabled but '{field}' not configured")

        # Check list fields
        for field in rules.get("list_fields", []):
            val = channel_config.get(field)
            if val and not isinstance(val, list):
                raise ValueError(f"Field '{channel_name}.{field}' must be a list")

        # Check enum fields
        for field, valid_values in rules.get("enum_fields", {}).items():
            val = channel_config.get(field, valid_values[0] if valid_values else "").upper()
            if val not in valid_values:
                raise ValueError(
                    f"Invalid {channel_name} {field}: '{val}'. "
                    f"Valid values: {', '.join(valid_values)}"
                )

    def _validate_timezone(self, config: Dict[str, Any]):
        """
        Validate timezone configuration and set default if not provided

        Args:
            config: Configuration dictionary

        Raises:
            ValueError: If timezone is invalid
        """
        # Get timezone from monitoring section or root level
        timezone = config.get("monitoring", {}).get("timezone") or config.get("timezone")

        if not timezone:
            # Set default timezone
            default_tz = "Europe/Warsaw"
            if "monitoring" not in config:
                config["monitoring"] = {}
            config["monitoring"]["timezone"] = default_tz
            logger.info(f"No timezone configured, using default: {default_tz}")
            return

        # Validate timezone if pytz is available
        if PYTZ_AVAILABLE:
            try:
                pytz.timezone(timezone)
                logger.info(f"Timezone configured: {timezone}")
            except pytz.exceptions.UnknownTimeZoneError:
                logger.warning(f"Invalid timezone '{timezone}', falling back to 'Europe/Warsaw'")
                logger.warning(f"Valid timezones: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones")
                config["monitoring"]["timezone"] = "Europe/Warsaw"
        else:
            # pytz not available, accept timezone but warn
            logger.warning("pytz not installed - timezone validation disabled")
            logger.warning("Install pytz for timezone support: pip install pytz")
            logger.info(f"Using configured timezone without validation: {timezone}")

    def _apply_database_defaults(self, config: Dict[str, Any]):
        """Apply defaults for database section."""
        db = config.setdefault("database", {})
        db.setdefault("enabled", True)
        db.setdefault("path", "/data/invoices.db")
        logger.info(f"Database: enabled={db['enabled']}, path={db['path']}")

    def _apply_storage_defaults(self, config: Dict[str, Any]):
        """Apply defaults for storage section (save_xml, save_pdf, output_dir)."""
        storage = config.setdefault("storage", {})
        if "save_xml" not in storage:
            storage["save_xml"] = False
        if "save_pdf" not in storage:
            storage["save_pdf"] = False
        if "output_dir" not in storage:
            storage["output_dir"] = "/data/invoices"

        # Validate file_exists_strategy
        valid_strategies = ("skip", "rename", "overwrite")
        strategy = storage.setdefault("file_exists_strategy", "skip")
        if strategy not in valid_strategies:
            logger.warning(
                f"Invalid file_exists_strategy '{strategy}' - "
                f"allowed values: {', '.join(valid_strategies)}. Falling back to 'skip'."
            )
            storage["file_exists_strategy"] = "skip"

        # Validate and default folder_structure
        storage.setdefault("folder_structure", "")
        folder_structure = storage["folder_structure"]
        if folder_structure:
            # Only allow known placeholders: {year}, {month}, {day}, {type}
            stripped = re.sub(r'\{(year|month|day|type)\}', '', folder_structure)
            if '{' in stripped or '}' in stripped:
                logger.warning(
                    f"Invalid folder_structure '{folder_structure}' - "
                    f"only {{year}}, {{month}}, {{day}}, {{type}} placeholders allowed. "
                    f"Falling back to flat directory."
                )
                storage["folder_structure"] = ""
            else:
                logger.info(f"Storage folder structure: {folder_structure}")

        # Validate and default file_name_pattern
        default_fnp = "{type}_{date}_{invoice_number}"
        storage.setdefault("file_name_pattern", default_fnp)
        file_name_pattern = storage["file_name_pattern"]
        if file_name_pattern:
            allowed_fnp = r'\{(ksef|ksef_short|invoice_number|date|type|seller_nip|buyer_nip)\}'
            stripped_fnp = re.sub(allowed_fnp, '', file_name_pattern)
            if '{' in stripped_fnp or '}' in stripped_fnp:
                logger.warning(
                    f"Invalid file_name_pattern '{file_name_pattern}' - "
                    f"only {{ksef}}, {{ksef_short}}, {{invoice_number}}, {{date}}, {{type}}, "
                    f"{{seller_nip}}, {{buyer_nip}} placeholders allowed. "
                    f"Falling back to default."
                )
                storage["file_name_pattern"] = default_fnp
            else:
                logger.info(f"Storage file name pattern: {file_name_pattern}")

        # Validate optional pdf_templates_dir
        pdf_templates_dir = storage.get("pdf_templates_dir")
        if pdf_templates_dir:
            if not Path(pdf_templates_dir).is_dir():
                logger.warning(
                    f"Custom PDF templates directory not found: {pdf_templates_dir}. "
                    f"Built-in default template will be used."
                )

        logger.info(f"Storage: save_xml={storage['save_xml']}, save_pdf={storage['save_pdf']}, output_dir={storage['output_dir']}")

    def _apply_rate_limit_defaults(self, config: Dict[str, Any]):
        """Apply defaults for KSeF API rate limiting (ksef.rate_limit section)."""
        ksef = config.setdefault("ksef", {})
        rl = ksef.setdefault("rate_limit", {})

        defaults = {"per_second": 10, "per_minute": 30, "per_hour": 120}
        for key, default_val in defaults.items():
            val = rl.setdefault(key, default_val)
            if not isinstance(val, int) or val <= 0:
                logger.warning(
                    f"Invalid rate_limit.{key}={val!r}, falling back to {default_val}"
                )
                rl[key] = default_val

        logger.info(
            f"Rate limits: {rl['per_second']}/s, {rl['per_minute']}/min, {rl['per_hour']}/h"
        )

    def _apply_api_defaults(self, config: Dict[str, Any]):
        """Apply defaults for REST API section."""
        api = config.setdefault("api", {})
        api.setdefault("enabled", False)
        api.setdefault("port", 8080)
        api.setdefault("bind_address", "127.0.0.1")
        api.setdefault("auth_token", "")

        # Rate limiting defaults
        rate_limit = api.setdefault("rate_limit", {})
        rate_limit.setdefault("enabled", True)
        rate_limit.setdefault("default", "60/minute")
        rate_limit.setdefault("trigger", "2/minute")

        # Auto-generate auth token if API enabled without one (F-01 security fix)
        if api["enabled"] and not api["auth_token"]:
            generated_token = secrets.token_urlsafe(48)
            api["auth_token"] = generated_token
            logger.warning("=" * 60)
            logger.warning(
                "API enabled without auth_token — auto-generated:"
            )
            logger.warning("  %s", generated_token)
            logger.warning(
                "Set api.auth_token in config.json or "
                "API_AUTH_TOKEN env var for a persistent token."
            )
            logger.warning("=" * 60)

        if api["enabled"]:
            logger.info(
                f"API: enabled on {api['bind_address']}:{api['port']}, "
                f"auth={'enabled' if api['auth_token'] else 'DISABLED (open access)'}"
            )

    _SENTINEL = object()

    def get(self, *keys, default=_SENTINEL) -> Optional[Any]:
        """
        Get configuration value using dot notation

        Args:
            *keys: Keys to traverse in configuration dictionary
            default: Value to return if key is not found (default: None)

        Returns:
            Configuration value, or default if not found

        Example:
            config.get("ksef", "environment")  # Returns "test"
            config.get("prometheus", "enabled", default=True)
        """
        # Filter out non-string args passed as positional (backwards compat)
        str_keys = []
        fallback = self._SENTINEL
        for k in keys:
            if isinstance(k, str):
                str_keys.append(k)
            else:
                fallback = k

        if default is not self._SENTINEL:
            fallback = default

        value = self.config
        for key in str_keys:
            if not isinstance(value, dict):
                return fallback if fallback is not self._SENTINEL else None
            value = value.get(key)
            if value is None:
                return fallback if fallback is not self._SENTINEL else None
        return value
    
    def get_timezone(self) -> str:
        """
        Get configured timezone

        Returns:
            Timezone string (e.g., "Europe/Warsaw")
        """
        return self.get("monitoring", "timezone") or "Europe/Warsaw"

    def get_timezone_object(self):
        """
        Get timezone as pytz timezone object

        Returns:
            pytz timezone object or None if pytz not available

        Raises:
            ImportError: If pytz is not installed
        """
        if not PYTZ_AVAILABLE:
            raise ImportError("pytz is required for timezone support. Install with: pip install pytz")

        tz_name = self.get_timezone()
        return pytz.timezone(tz_name)

    def reload(self):
        """Reload configuration from file"""
        self.config = self.load_config()
        logger.info("Configuration reloaded")
