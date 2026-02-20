"""
Generic Webhook Notification Service
Sends notifications to custom HTTP/HTTPS endpoints
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import requests
import socket
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse

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
        super().__init__()
        notifications_config = config.get("notifications") or {}
        webhook_config = notifications_config.get("webhook") or {}

        raw_url = webhook_config.get("url")
        self.url = raw_url if self._validate_webhook_url(raw_url) else None
        self.method = webhook_config.get("method", "POST").upper()
        self.headers = webhook_config.get("headers", {})
        self.timeout = webhook_config.get("timeout", 10)
        self.signing_secret = webhook_config.get("signing_secret")

        # Ensure Content-Type is set for JSON payloads
        if "Content-Type" not in self.headers:
            self.headers["Content-Type"] = "application/json"

        if not self.is_configured:
            logger.debug("Webhook URL not configured")

    @staticmethod
    def _validate_webhook_url(url: str) -> bool:
        """Validate webhook URL to prevent SSRF attacks on internal services."""
        if not url:
            return False
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ('https', 'http'):
                logger.warning(f"Webhook URL rejected: unsupported scheme '{parsed.scheme}'")
                return False
            hostname = parsed.hostname
            if not hostname:
                return False
            # Resolve hostname and check all IPs
            try:
                addr_info = socket.getaddrinfo(hostname, None)
                for family, _, _, _, sockaddr in addr_info:
                    ip = ipaddress.ip_address(sockaddr[0])
                    if ip.is_private or ip.is_loopback or ip.is_link_local:
                        logger.warning(f"Webhook URL rejected: resolves to private/internal IP")
                        return False
            except socket.gaierror:
                logger.warning(f"Webhook URL rejected: cannot resolve hostname")
                return False
            return True
        except Exception:
            return False

    @property
    def is_configured(self) -> bool:
        """Check if webhook URL is configured"""
        return bool(self.url)

    def _sign_payload(self, payload_bytes: bytes) -> Dict[str, str]:
        """Compute HMAC-SHA256 signature header for payload if signing_secret is set."""
        if not self.signing_secret:
            return {}
        signature = hmac.new(
            self.signing_secret.encode('utf-8'),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        return {"X-Signature": f"sha256={signature}"}

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

            # Compute HMAC signature if signing_secret is configured
            payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
            headers = {**self.headers, **self._sign_payload(payload_bytes)}

            # Send request based on configured method
            if self.method == "POST":
                response = self.session.post(
                    self.url, json=payload, headers=headers, timeout=self.timeout
                )
            elif self.method == "PUT":
                response = self.session.put(
                    self.url, json=payload, headers=headers, timeout=self.timeout
                )
            elif self.method == "GET":
                # For GET, send as query parameters
                response = self.session.get(
                    self.url, params=payload, headers=headers, timeout=self.timeout
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
                logger.error(f"Webhook response status: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending webhook notification: {e}")
            return False

    def _send_rendered(self, rendered: str, context: Dict[str, Any]) -> bool:
        """Send webhook with rendered JSON payload."""
        if not self.is_configured:
            logger.error("Webhook not configured - notification not sent")
            return False

        try:
            payload = json.loads(rendered)
            payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
            headers = {**self.headers, **self._sign_payload(payload_bytes)}

            if self.method == "POST":
                response = self.session.post(self.url, json=payload, headers=headers, timeout=self.timeout)
            elif self.method == "PUT":
                response = self.session.put(self.url, json=payload, headers=headers, timeout=self.timeout)
            elif self.method == "GET":
                response = self.session.get(self.url, params=payload, headers=headers, timeout=self.timeout)
            else:
                logger.error(f"Unsupported HTTP method: {self.method}")
                return False

            response.raise_for_status()

            logger.info(f"Webhook notification sent ({self.method}): {context.get('title')}")
            return True

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from webhook template: {e}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send webhook notification: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Webhook response status: {e.response.status_code}")
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
