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
            "monitoring": ["check_interval"]
        }
        
        for section, fields in required_fields.items():
            if section not in config:
                raise ValueError(f"Missing required section: {section}")
            for field in fields:
                if field not in config[section]:
                    raise ValueError(f"Missing required field: {section}.{field}")
                if not config[section][field]:
                    raise ValueError(f"Empty value for required field: {section}.{field}")
    
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
