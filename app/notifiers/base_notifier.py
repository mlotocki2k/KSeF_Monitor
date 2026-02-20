"""
Base Notifier Interface for KSeF Invoice Monitor
All notification channels must implement this interface
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class BaseNotifier(ABC):
    """
    Abstract base class for all notification channels

    All notifiers must implement this interface to ensure consistent behavior
    across different notification platforms (Pushover, Discord, Slack, Email, Webhook)
    """

    @abstractmethod
    def send_notification(self, title: str, message: str, priority: int = 0, url: Optional[str] = None) -> bool:
        """
        Send notification through this channel

        Args:
            title: Notification title
            message: Notification message body
            priority: Priority level (-2 to 2)
                -2: No notification/alert (lowest)
                -1: Quiet notification
                0: Normal priority (default)
                1: High priority
                2: Emergency (highest)
            url: Optional URL to include in notification

        Returns:
            True if notification sent successfully, False otherwise

        Note:
            Implementations should never raise exceptions - always return bool
            Failures should be logged but not propagated
        """
        pass

    @abstractmethod
    def send_error_notification(self, error_message: str) -> bool:
        """
        Send error notification with high priority

        Args:
            error_message: Error message to send

        Returns:
            True if sent successfully, False otherwise

        Note:
            Typically calls send_notification() with priority=1
        """
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        """
        Test connection by sending a test notification

        Returns:
            True if test successful, False otherwise

        Note:
            Should send a low-priority test message to verify configuration
        """
        pass

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """
        Check if notifier is properly configured with required credentials

        Returns:
            True if all required configuration is present, False otherwise

        Note:
            Used by NotificationManager to determine if channel should be enabled
        """
        pass

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """
        Return human-readable channel name for logging

        Returns:
            Channel name (e.g., "Pushover", "Discord", "Slack")
        """
        pass

    # --- Template-based notification methods ---

    @property
    def _template_channel(self) -> str:
        """Template channel key. Override if channel_name differs from template key."""
        return self.channel_name.lower()

    def render_and_send(self, context: Dict[str, Any], template_renderer) -> bool:
        """
        Render template and send notification for an invoice.

        Default implementation renders the template for this channel and
        passes the result to _send_rendered(). On failure, falls back to
        legacy send_notification() with plain text.

        Args:
            context: Template context dictionary from build_template_context()
            template_renderer: TemplateRenderer instance

        Returns:
            True if notification sent successfully
        """
        rendered = template_renderer.render(self._template_channel, context)
        if rendered is None:
            logger.warning(f"Template rendering failed for {self.channel_name}, using fallback")
            return self.send_notification(
                title=context.get("title", ""),
                message=self._build_fallback_message(context),
                priority=context.get("priority", 0),
                url=context.get("url"),
            )
        return self._send_rendered(rendered, context)

    def _send_rendered(self, rendered: str, context: Dict[str, Any]) -> bool:
        """
        Send the rendered template output. Override in subclasses
        for channel-specific handling (e.g., parsing JSON).
        """
        return self.send_notification(
            title=context.get("title", ""),
            message=rendered,
            priority=context.get("priority", 0),
            url=context.get("url"),
        )

    @staticmethod
    def _build_fallback_message(context: Dict[str, Any]) -> str:
        """Build a plain text fallback message from context dict."""
        subject_type = context.get("subject_type", "")
        if subject_type == "Subject1":
            counterparty = f"Do: {context.get('buyer_name', 'N/A')} - NIP {context.get('buyer_nip', 'N/A')}"
        elif subject_type == "Subject2":
            counterparty = f"Od: {context.get('seller_name', 'N/A')} - NIP {context.get('seller_nip', 'N/A')}"
        else:
            counterparty = (
                f"Od: {context.get('seller_name', 'N/A')} - NIP {context.get('seller_nip', 'N/A')}\n"
                f"Do: {context.get('buyer_name', 'N/A')} - NIP {context.get('buyer_nip', 'N/A')}"
            )
        return (
            f"{counterparty}\n"
            f"Nr Faktury: {context.get('invoice_number', 'N/A')}\n"
            f"Data: {context.get('issue_date', 'N/A')}\n"
            f"Brutto: {context.get('gross_amount', 'N/A')} {context.get('currency', 'PLN')}\n"
            f"Numer KSeF: {context.get('ksef_number', 'N/A')}"
        )
