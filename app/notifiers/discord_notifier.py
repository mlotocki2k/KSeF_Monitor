"""
Discord Notification Service
Sends notifications via Discord webhooks with rich embeds
"""

import json
import logging
import requests
from datetime import datetime
from typing import Any, Dict, Optional

from .base_notifier import BaseNotifier

logger = logging.getLogger(__name__)


class DiscordNotifier(BaseNotifier):
    """Send notifications to Discord via webhooks"""

    # Priority to color mapping (Discord embed colors)
    PRIORITY_COLORS = {
        -2: 0x808080,  # Gray - no alert
        -1: 0x808080,  # Gray - quiet
        0: 0x3498db,   # Blue - normal
        1: 0xff9900,   # Orange - high priority
        2: 0xe74c3c,   # Red - emergency
    }

    def __init__(self, config):
        """
        Initialize Discord notifier

        Args:
            config: ConfigManager instance or dict with notifications configuration
        """
        notifications_config = config.get("notifications") or {}
        discord_config = notifications_config.get("discord") or {}

        self.webhook_url = discord_config.get("webhook_url")
        self.username = discord_config.get("username", "KSeF Monitor")
        self.avatar_url = discord_config.get("avatar_url", "")
        self.timeout = discord_config.get("timeout", 10)

        if not self.is_configured:
            logger.debug("Discord webhook URL not configured")

    @property
    def is_configured(self) -> bool:
        """Check if Discord webhook URL is configured"""
        return bool(self.webhook_url)

    @property
    def channel_name(self) -> str:
        """Return channel name for logging"""
        return "Discord"

    def send_notification(self, title: str, message: str, priority: int = 0, url: Optional[str] = None) -> bool:
        """
        Send notification to Discord via webhook

        Args:
            title: Notification title
            message: Notification message
            priority: Priority level (-2 to 2) - mapped to embed colors
            url: Optional URL to include in embed

        Returns:
            True if successful, False otherwise
        """
        if not self.is_configured:
            logger.error("Discord not configured - notification not sent")
            return False

        try:
            # Get color based on priority
            color = self.PRIORITY_COLORS.get(priority, 0x3498db)

            # Build embed
            embed = {
                "title": title[:256],  # Discord title max length
                "description": message[:4096],  # Discord description max length
                "color": color,
                "timestamp": datetime.utcnow().isoformat(),
                "footer": {
                    "text": "KSeF Invoice Monitor"
                }
            }

            # Add URL if provided
            if url:
                embed["url"] = url

            # Build payload
            payload = {
                "username": self.username,
                "embeds": [embed]
            }

            if self.avatar_url:
                payload["avatar_url"] = self.avatar_url

            # Send to Discord
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()

            logger.info(f"Discord notification sent: {title}")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Discord notification: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Discord API response: {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending Discord notification: {e}")
            return False

    def _send_rendered(self, rendered: str, context: Dict[str, Any]) -> bool:
        """Send Discord notification from rendered JSON template."""
        if not self.is_configured:
            logger.error("Discord not configured - notification not sent")
            return False

        try:
            embed = json.loads(rendered)
            payload = {
                "username": self.username,
                "embeds": [embed],
            }
            if self.avatar_url:
                payload["avatar_url"] = self.avatar_url

            response = requests.post(self.webhook_url, json=payload, timeout=self.timeout)
            response.raise_for_status()

            logger.info(f"Discord notification sent: {context.get('title')}")
            return True

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from Discord template: {e}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Discord notification: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Discord API response: {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending Discord notification: {e}")
            return False

    def send_error_notification(self, error_message: str) -> bool:
        """
        Send error notification with high priority (orange/red embed)

        Args:
            error_message: Error message to send

        Returns:
            True if successful, False otherwise
        """
        return self.send_notification(
            title="🚨 KSeF Monitor Error",
            message=error_message[:4096],  # Discord max
            priority=1  # High priority (orange)
        )

    def test_connection(self) -> bool:
        """
        Test Discord webhook by sending a test notification

        Returns:
            True if test successful
        """
        return self.send_notification(
            title="✅ KSeF Monitor Test",
            message="Test notification - Discord integration is configured correctly!",
            priority=0
        )
