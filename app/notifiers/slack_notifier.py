"""
Slack Notification Service
Sends notifications via Slack Incoming Webhooks with Block Kit formatting
"""

import json
import logging
import requests
from typing import Any, Dict, Optional

from .base_notifier import BaseNotifier

logger = logging.getLogger(__name__)


class SlackNotifier(BaseNotifier):
    """Send notifications to Slack via Incoming Webhooks"""

    # Priority to color and emoji mapping
    PRIORITY_CONFIG = {
        -2: {"color": "#808080", "emoji": "🔕", "prefix": ""},  # Gray, no alert
        -1: {"color": "#808080", "emoji": "💤", "prefix": ""},  # Gray, quiet
        0: {"color": "#36a64f", "emoji": "📋", "prefix": ""},  # Green, normal
        1: {"color": "#ff9900", "emoji": "⚠️", "prefix": ""},  # Orange, high
        2: {"color": "#e74c3c", "emoji": "🚨", "prefix": "<!channel> "},  # Red, emergency with mention
    }

    def __init__(self, config):
        """
        Initialize Slack notifier

        Args:
            config: ConfigManager instance or dict with notifications configuration
        """
        super().__init__()
        notifications_config = config.get("notifications") or {}
        slack_config = notifications_config.get("slack") or {}

        self.webhook_url = slack_config.get("webhook_url")
        self.username = slack_config.get("username", "KSeF Monitor")
        self.icon_emoji = slack_config.get("icon_emoji", ":receipt:")
        self.timeout = slack_config.get("timeout", 10)

        if not self.is_configured:
            logger.debug("Slack webhook URL not configured")

    @property
    def is_configured(self) -> bool:
        """Check if Slack webhook URL is configured"""
        return bool(self.webhook_url)

    @property
    def channel_name(self) -> str:
        """Return channel name for logging"""
        return "Slack"

    def send_notification(self, title: str, message: str, priority: int = 0, url: Optional[str] = None) -> bool:
        """
        Send notification to Slack via webhook

        Args:
            title: Notification title
            message: Notification message
            priority: Priority level (-2 to 2) - mapped to colors and mentions
            url: Optional URL to include as button

        Returns:
            True if successful, False otherwise
        """
        if not self.is_configured:
            logger.error("Slack not configured - notification not sent")
            return False

        try:
            # Get priority config
            priority_cfg = self.PRIORITY_CONFIG.get(priority, self.PRIORITY_CONFIG[0])
            emoji = priority_cfg["emoji"]
            color = priority_cfg["color"]
            prefix = priority_cfg["prefix"]

            # Build message text with emoji
            text = f"{emoji} *{title}*"
            if prefix:  # Add mention for high priority
                text = f"{prefix}{text}"

            # Build blocks for rich formatting
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{emoji} {title}"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": message
                    }
                }
            ]

            # Add button if URL provided
            if url:
                blocks.append({
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "View in KSeF"
                            },
                            "url": url
                        }
                    ]
                })

            # Build payload
            payload = {
                "username": self.username,
                "icon_emoji": self.icon_emoji,
                "text": text,  # Fallback for notifications
                "blocks": blocks,
                "attachments": [
                    {
                        "color": color,
                        "fallback": message
                    }
                ]
            }

            # Send to Slack
            response = self.session.post(
                self.webhook_url,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()

            logger.info(f"Slack notification sent: {title}")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Slack notification: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Slack API response status: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending Slack notification: {e}")
            return False

    def _send_rendered(self, rendered: str, context: Dict[str, Any]) -> bool:
        """Send Slack notification from rendered JSON template."""
        if not self.is_configured:
            logger.error("Slack not configured - notification not sent")
            return False

        try:
            payload = json.loads(rendered)
            payload["username"] = self.username
            payload["icon_emoji"] = self.icon_emoji

            response = self.session.post(self.webhook_url, json=payload, timeout=self.timeout)
            response.raise_for_status()

            logger.info(f"Slack notification sent: {context.get('title')}")
            return True

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from Slack template: {e}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Slack notification: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Slack API response status: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending Slack notification: {e}")
            return False

    def send_error_notification(self, error_message: str) -> bool:
        """
        Send error notification with high priority (orange color, warning emoji)

        Args:
            error_message: Error message to send

        Returns:
            True if successful, False otherwise
        """
        return self.send_notification(
            title="KSeF Monitor Error",
            message=error_message,
            priority=1  # High priority (orange, with warning emoji)
        )

    def test_connection(self) -> bool:
        """
        Test Slack webhook by sending a test notification

        Returns:
            True if test successful
        """
        return self.send_notification(
            title="KSeF Monitor Test",
            message="Test notification - Slack integration is configured correctly!",
            priority=0
        )
