"""
Secrets Manager for KSeF Invoice Monitor
Handles secure loading of sensitive credentials from various sources
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class SecretsManager:
    """
    Manages secure loading of secrets from multiple sources
    Priority order:
    1. Environment variables
    2. Docker secrets
    3. Config file
    """
    
    def __init__(self, config_path: str = "/data/config.json"):
        """
        Initialize secrets manager
        
        Args:
            config_path: Path to configuration file
        """
        self.config_path = Path(config_path)
        self.docker_secrets_path = Path("/run/secrets")
        
    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get secret value from available sources in priority order
        
        Args:
            key: Secret key to retrieve
            default: Default value if not found
            
        Returns:
            Secret value or default
        """
        # 1. Check environment variable
        env_value = os.getenv(key)
        if env_value:
            logger.debug(f"Secret '{key}' loaded from environment variable")
            return env_value
        
        # 2. Check Docker secrets
        docker_secret = self._read_docker_secret(key.lower())
        if docker_secret:
            logger.debug(f"Secret '{key}' loaded from Docker secret")
            return docker_secret
        
        # 3. Return default
        return default
    
    def _read_docker_secret(self, secret_name: str) -> Optional[str]:
        """
        Read secret from Docker secrets directory
        
        Args:
            secret_name: Name of the secret file
            
        Returns:
            Secret value or None
        """
        secret_file = self.docker_secrets_path / secret_name
        if secret_file.exists():
            try:
                with open(secret_file, 'r') as f:
                    return f.read().strip()
            except Exception as e:
                logger.warning(f"Failed to read Docker secret '{secret_name}': {e}")
        return None
    
    def load_config_with_secrets(self) -> Dict[str, Any]:
        """
        Load configuration and replace sensitive values with secrets
        
        Returns:
            Configuration dictionary with secrets injected
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Replace sensitive values with secrets
            config = self._inject_secrets(config)
            
            return config
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            raise
    
    def _inject_secrets(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Inject secrets into configuration

        Args:
            config: Configuration dictionary

        Returns:
            Configuration with secrets injected
        """
        # KSeF token
        ksef_token = self.get_secret("KSEF_TOKEN")
        if ksef_token:
            config.setdefault("ksef", {})["token"] = ksef_token
            logger.info("KSeF token loaded from secure source")

        # Pushover credentials (support both old and new structure)
        pushover_user = self.get_secret("PUSHOVER_USER_KEY")
        if pushover_user:
            # Inject into new notifications structure
            config.setdefault("notifications", {}).setdefault("pushover", {})["user_key"] = pushover_user
            # Also inject into old structure for backwards compatibility
            config.setdefault("pushover", {})["user_key"] = pushover_user
            logger.info("Pushover user key loaded from secure source")

        pushover_token = self.get_secret("PUSHOVER_API_TOKEN")
        if pushover_token:
            # Inject into new notifications structure
            config.setdefault("notifications", {}).setdefault("pushover", {})["api_token"] = pushover_token
            # Also inject into old structure for backwards compatibility
            config.setdefault("pushover", {})["api_token"] = pushover_token
            logger.info("Pushover API token loaded from secure source")

        # Discord credentials
        discord_webhook = self.get_secret("DISCORD_WEBHOOK_URL")
        if discord_webhook:
            config.setdefault("notifications", {}).setdefault("discord", {})["webhook_url"] = discord_webhook
            logger.info("Discord webhook URL loaded from secure source")

        # Slack credentials
        slack_webhook = self.get_secret("SLACK_WEBHOOK_URL")
        if slack_webhook:
            config.setdefault("notifications", {}).setdefault("slack", {})["webhook_url"] = slack_webhook
            logger.info("Slack webhook URL loaded from secure source")

        # Email credentials
        email_password = self.get_secret("EMAIL_PASSWORD")
        if email_password:
            config.setdefault("notifications", {}).setdefault("email", {})["password"] = email_password
            logger.info("Email password loaded from secure source")

        # Webhook credentials (optional - for Authorization header)
        webhook_token = self.get_secret("WEBHOOK_TOKEN")
        if webhook_token:
            webhook_config = config.setdefault("notifications", {}).setdefault("webhook", {})
            headers = webhook_config.setdefault("headers", {})
            headers["Authorization"] = f"Bearer {webhook_token}"
            logger.info("Webhook token loaded from secure source")

        return config
    
    def validate_secrets(self, config: Dict[str, Any]) -> bool:
        """
        Validate that all required secrets are present
        
        Args:
            config: Configuration dictionary
            
        Returns:
            True if all secrets are present
        """
        required_secrets = [
            ("ksef", "token"),
            ("pushover", "user_key"),
            ("pushover", "api_token")
        ]
        
        missing = []
        for section, key in required_secrets:
            if not config.get(section, {}).get(key):
                missing.append(f"{section}.{key}")
        
        if missing:
            logger.error(f"Missing required secrets: {', '.join(missing)}")
            return False
        
        return True
