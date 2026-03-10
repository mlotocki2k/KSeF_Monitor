"""
Notification system for KSeF Invoice Monitor

This package provides a flexible multi-channel notification system supporting:
- Pushover (mobile notifications)
- Discord (team collaboration)
- Slack (enterprise teams)
- Email (SMTP-based notifications)
- Webhook (custom integrations)

Usage:
    from app.notifiers import NotificationManager

    manager = NotificationManager(config)
    manager.send_notification("Title", "Message", priority=0)
"""

from .base_notifier import BaseNotifier
from .notification_manager import NotificationManager

# Notifier implementations will be imported dynamically by NotificationManager
# to avoid circular dependencies

__all__ = [
    "BaseNotifier",
    "NotificationManager",
]
