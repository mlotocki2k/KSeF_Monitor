"""
Configuration Manager for KSeF Invoice Monitor
Handles loading and validation of JSON configuration with secrets support
"""

import json
import sys
import logging
from pathlib import Path
from typing import Dict, Any, Optional

# Handle imports for both package and direct execution
try:
    from .secrets_manager import SecretsManager
except ImportError:
    from app.secrets_manager import SecretsManager

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
            
            # Validate required fields
            self._validate_config(config)
            
            # Validate secrets are present
            if not self.secrets_manager.validate_secrets(config):
                logger.error("Configuration validation failed - missing secrets")
                sys.exit(1)
            
            logger.info("Configuration loaded successfully")
            return config
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            sys.exit(1)
    
    def _validate_config(self, config: Dict[str, Any]):
        """
        Validate configuration has required fields

        Args:
            config: Configuration dictionary to validate

        Raises:
            ValueError: If required fields are missing
        """
        required_fields = {
            "ksef": ["environment", "nip"],  # token validated separately by secrets_manager
            "pushover": [],  # credentials validated separately by secrets_manager
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
    
    def get(self, *keys: str) -> Optional[Any]:
        """
        Get configuration value using dot notation
        
        Args:
            *keys: Keys to traverse in configuration dictionary
            
        Returns:
            Configuration value or None if not found
            
        Example:
            config.get("ksef", "environment")  # Returns "test"
        """
        value = self.config
        for key in keys:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
            if value is None:
                return None
        return value
    
    def reload(self):
        """Reload configuration from file"""
        self.config = self.load_config()
        logger.info("Configuration reloaded")
