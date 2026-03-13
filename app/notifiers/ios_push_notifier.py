"""
iOS Push Notifier for KSeF Monitor

Sends push notifications to iOS devices via Central Push Service (Cloudflare Worker).
The Worker relays notifications to Apple Push Notification service (APNs).

Authentication: X-Instance-Id + X-Instance-Key headers (not Bearer token).
Payload: {title, body, data} — Worker builds the APNs 'aps' envelope.
"""

import json
import logging
import uuid
from typing import Any, Dict, Optional

import requests

from .base_notifier import BaseNotifier

logger = logging.getLogger(__name__)


class IosPushNotifier(BaseNotifier):
    """Send iOS push notifications via Central Push Service (Cloudflare Worker).

    Architecture:
        KSeF Monitor → POST /push/send → Worker (push.monitorksef.com) → APNs → iOS

    The Worker handles:
        - APNs authentication (JWT with .p8 key)
        - Device token management (KV storage)
        - Building APNs payload (aps envelope)

    This notifier only sends {title, body, data} to the Worker endpoint.
    """

    def __init__(self, config):
        """
        Initialize iOS Push notifier.

        Args:
            config: ConfigManager instance or dict with notifications configuration
        """
        super().__init__()
        notifications_config = config.get("notifications") or {}
        ios_push_config = notifications_config.get("ios_push") or {}

        self.worker_url = ios_push_config.get(
            "worker_url", "https://push.monitorksef.com"
        )
        self.instance_id = ios_push_config.get("instance_id")
        self.instance_key = ios_push_config.get("instance_key")
        self.timeout = ios_push_config.get("timeout", 15)

    @property
    def is_configured(self) -> bool:
        """Check if iOS Push is properly configured with instance credentials."""
        return bool(self.worker_url and self.instance_id and self.instance_key)

    @property
    def channel_name(self) -> str:
        """Return human-readable channel name for logging."""
        return "iOS Push"

    @property
    def _template_channel(self) -> str:
        """Template channel key — override required.

        channel_name.lower() would give 'ios push' (with space),
        but template map uses 'ios_push' (with underscore).
        """
        return "ios_push"

    def send_notification(
        self,
        title: str,
        message: str,
        priority: int = 0,
        url: Optional[str] = None,
    ) -> bool:
        """
        Send notification via Central Push Service to all paired iOS devices.

        Args:
            title: Notification title
            message: Notification message body (truncated to 256 chars for APNs)
            priority: Priority level (-2 to 2) — mapped by Worker to APNs priority
            url: Optional URL for notification action

        Returns:
            True if notification sent successfully, False otherwise
        """
        if not self.is_configured:
            logger.error("iOS Push not configured — missing instance credentials")
            return False

        try:
            # v1.2: data with required fields
            data: Dict[str, Any] = {
                "notification_id": str(uuid.uuid4()),
                "type": "system",
                "invoice_reference": "n/a",
            }
            if url:
                data["url"] = url

            payload: Dict[str, Any] = {
                "title": title,
                "body": message[:256],
                "data": data,
            }

            headers = {
                "X-Instance-Id": self.instance_id,
                "X-Instance-Key": self.instance_key,
                "Content-Type": "application/json",
            }

            response = self.session.post(
                f"{self.worker_url}/push/send",
                json=payload,
                headers=headers,
                timeout=self.timeout,
                allow_redirects=False,
            )

            if response.status_code == 200:
                result = response.json()
                sent = result.get("sent", 0)
                logger.info("iOS Push notification sent to %d device(s): %s", sent, title)
                return True

            elif response.status_code == 401:
                logger.error(
                    "iOS Push auth failed — instance_key is invalid or expired"
                )
                return False

            elif response.status_code == 429:
                logger.warning("iOS Push rate limited by Central Push Service")
                return False

            else:
                response.raise_for_status()
                return False  # unreachable, but explicit

        except requests.exceptions.RequestException as e:
            logger.error("Failed to send iOS Push notification: %s", e)
            return False
        except Exception as e:
            logger.error("Unexpected error sending iOS Push notification: %s", e)
            return False

    def _send_rendered(self, rendered: str, context: Dict[str, Any]) -> bool:
        """Send iOS Push notification from rendered JSON template.

        Parses the rendered template as JSON and sends it to the Worker.
        Template output must match Worker API: {title, body, data?}.
        """
        if not self.is_configured:
            logger.error("iOS Push not configured")
            return False

        try:
            payload = json.loads(rendered)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON from iOS Push template: %s", e)
            return False

        # v1.2: required fields in data — set from context, not template
        if "data" not in payload:
            payload["data"] = {}
        payload["data"]["notification_id"] = str(uuid.uuid4())
        payload["data"]["type"] = "new_invoice"
        payload["data"]["invoice_reference"] = context.get("ksef_number") or "n/a"

        try:
            headers = {
                "X-Instance-Id": self.instance_id,
                "X-Instance-Key": self.instance_key,
                "Content-Type": "application/json",
            }

            response = self.session.post(
                f"{self.worker_url}/push/send",
                json=payload,
                headers=headers,
                timeout=self.timeout,
                allow_redirects=False,
            )

            if response.status_code == 200:
                result = response.json()
                sent = result.get("sent", 0)
                logger.info(
                    "iOS Push notification sent to %d device(s): %s",
                    sent,
                    context.get("title"),
                )
                return True

            elif response.status_code == 401:
                logger.error(
                    "iOS Push auth failed — instance_key is invalid or expired"
                )
                return False

            elif response.status_code == 429:
                logger.warning("iOS Push rate limited by Central Push Service")
                return False

            else:
                response.raise_for_status()
                return False

        except requests.exceptions.RequestException as e:
            logger.error("Failed to send iOS Push notification: %s", e)
            return False
        except Exception as e:
            logger.error("Unexpected error sending iOS Push notification: %s", e)
            return False

    def send_error_notification(self, error_message: str) -> bool:
        """Send error notification with high priority."""
        return self.send_notification(
            title="KSeF Monitor Error",
            message=error_message[:256],
            priority=1,
        )

    def test_connection(self) -> bool:
        """Test iOS Push connection by sending a test notification."""
        return self.send_notification(
            title="KSeF Monitor Test",
            message="Test notification — iOS Push is configured correctly!",
            priority=0,
        )
