"""
Pushover Notification Service
Sends push notifications via Pushover API
"""

import logging
import requests
from typing import Any, Dict, Optional

from .base_notifier import BaseNotifier

logger = logging.getLogger(__name__)


class PushoverNotifier(BaseNotifier):
    """Send notifications via Pushover mobile app"""

    API_URL = "https://api.pushover.net/1/messages.json"

    def __init__(self, config):
        """
        Initialize Pushover notifier

        Args:
            config: ConfigManager instance or dict with notifications configuration
        """
        super().__init__()
        # Support both new notifications structure and legacy root-level pushover
        notifications_config = config.get("notifications") or {}
        pushover_config = notifications_config.get("pushover") or config.get("pushover") or {}

        self.user_key = pushover_config.get("user_key")
        self.api_token = pushover_config.get("api_token")

        if not self.is_configured:
            logger.debug("Pushover credentials not configured")

    @property
    def is_configured(self) -> bool:
        """Check if Pushover credentials are configured"""
        return bool(self.user_key and self.api_token)

    @property
    def channel_name(self) -> str:
        """Return channel name for logging"""
        return "Pushover"

    def send_notification(self, title: str, message: str, priority: int = 0, url: Optional[str] = None) -> bool:
        """
        Send notification via Pushover

        Args:
            title: Notification title
            message: Notification message
            priority: Priority level (-2 to 2)
                -2: No notification/alert
                -1: Quiet notification
                0: Normal priority (default)
                1: High priority
                2: Emergency (requires acknowledgment)
            url: Optional URL to include in notification

        Returns:
            True if successful, False otherwise
        """
        if not self.is_configured:
            logger.error("Pushover not configured - notification not sent")
            return False

        try:
            payload = {
                "token": self.api_token,
                "user": self.user_key,
                "title": title,
                "message": message[:1024],  # Pushover max message length
                "priority": priority
            }

            if url:
                payload["url"] = url
                payload["url_title"] = "View in KSeF"

            response = self.session.post(self.API_URL, data=payload, timeout=10)
            response.raise_for_status()

            logger.info(f"Pushover notification sent: {title}")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Pushover notification: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Pushover API response status: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending Pushover notification: {e}")
            return False

    def _send_rendered(self, rendered: str, context: Dict[str, Any]) -> bool:
        """Send Pushover notification with rendered text."""
        if not self.is_configured:
            logger.error("Pushover not configured - notification not sent")
            return False

        try:
            payload = {
                "token": self.api_token,
                "user": self.user_key,
                "title": context.get("title", ""),
                "message": rendered[:1024],
                "priority": context.get("priority", 0),
            }
            url = context.get("url")
            if url:
                payload["url"] = url
                payload["url_title"] = "View in KSeF"

            response = self.session.post(self.API_URL, data=payload, timeout=10)
            response.raise_for_status()

            logger.info(f"Pushover notification sent: {context.get('title')}")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Pushover notification: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Pushover API response status: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending Pushover notification: {e}")
            return False

    def send_error_notification(self, error_message: str) -> bool:
        """
        Send error notification with high priority

        Args:
            error_message: Error message to send

        Returns:
            True if successful, False otherwise
        """
        return self.send_notification(
            title="KSeF Monitor Error",
            message=error_message[:1024],  # Pushover max message length
            priority=1  # High priority for errors
        )

    def test_connection(self) -> bool:
        """
        Test Pushover connection by sending a test notification

        Returns:
            True if test successful
        """
        return self.send_notification(
            title="KSeF Monitor Test",
            message="Test notification - Pushover is configured correctly!",
            priority=0
        )
