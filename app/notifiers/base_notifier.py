"""
Base Notifier Interface for KSeF Invoice Monitor
All notification channels must implement this interface
"""

from abc import ABC, abstractmethod
from typing import Optional


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
