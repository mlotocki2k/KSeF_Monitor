"""
Generic Webhook Notification Service
Sends notifications to custom HTTP/HTTPS endpoints
"""

import logging
import requests
from datetime import datetime
from typing import Optional, Dict

from .base_notifier import BaseNotifier

logger = logging.getLogger(__name__)


class WebhookNotifier(BaseNotifier):
    """Send notifications to generic webhooks with configurable HTTP method and headers"""

    # Priority level names for JSON payload
    PRIORITY_NAMES = {
        -2: "lowest",
        -1: "low",
        0: "normal",
        1: "high",
        2: "urgent",
    }

    def __init__(self, config):
        """
        Initialize Webhook notifier

        Args:
            config: ConfigManager instance or dict with notifications configuration
        """
        notifications_config = config.get("notifications") or {}
        webhook_config = notifications_config.get("webhook") or {}

        self.url = webhook_config.get("url")
        self.method = webhook_config.get("method", "POST").upper()
        self.headers = webhook_config.get("headers", {})
        self.timeout = webhook_config.get("timeout", 10)

        # Ensure Content-Type is set for JSON payloads
        if "Content-Type" not in self.headers:
            self.headers["Content-Type"] = "application/json"

        if not self.is_configured:
            logger.debug("Webhook URL not configured")

    @property
    def is_configured(self) -> bool:
        """Check if webhook URL is configured"""
        return bool(self.url)

    @property
    def channel_name(self) -> str:
        """Return channel name for logging"""
        return "Webhook"

    def send_notification(self, title: str, message: str, priority: int = 0, url: Optional[str] = None) -> bool:
        """
        Send notification to webhook endpoint

        Args:
            title: Notification title
            message: Notification message
            priority: Priority level (-2 to 2)
            url: Optional URL to include in payload

        Returns:
            True if successful, False otherwise
        """
        if not self.is_configured:
            logger.error("Webhook not configured - notification not sent")
            return False

        try:
            # Build JSON payload
            payload = {
                "title": title,
                "message": message,
                "priority": priority,
                "priority_name": self.PRIORITY_NAMES.get(priority, "normal"),
                "timestamp": datetime.utcnow().isoformat(),
                "source": "ksef-monitor"
            }

            # Add URL if provided
            if url:
                payload["url"] = url

            # Send request based on configured method
            if self.method == "POST":
                response = requests.post(
                    self.url,
                    json=payload,
                    headers=self.headers,
                    timeout=self.timeout
                )
            elif self.method == "PUT":
                response = requests.put(
                    self.url,
                    json=payload,
                    headers=self.headers,
                    timeout=self.timeout
                )
            elif self.method == "GET":
                # For GET, send as query parameters
                response = requests.get(
                    self.url,
                    params=payload,
                    headers=self.headers,
                    timeout=self.timeout
                )
            else:
                logger.error(f"Unsupported HTTP method: {self.method}")
                return False

            response.raise_for_status()

            logger.info(f"Webhook notification sent ({self.method}): {title}")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send webhook notification: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Webhook response: {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending webhook notification: {e}")
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
            message=error_message,
            priority=1  # High priority
        )

    def test_connection(self) -> bool:
        """
        Test webhook by sending a test notification

        Returns:
            True if test successful
        """
        return self.send_notification(
            title="KSeF Monitor Test",
            message="Test notification - Webhook integration is configured correctly!",
            priority=0
        )
