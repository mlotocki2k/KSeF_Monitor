"""
Notification Manager for KSeF Invoice Monitor
Manages multiple notification channels and sends notifications to all enabled channels
"""

import logging
from typing import Any, List, Optional, Dict, Type

logger = logging.getLogger(__name__)


class NotificationManager:
    """
    Facade for managing multiple notification channels

    Initializes all enabled channels and sends notifications to them.
    Gracefully handles failures - one channel failing doesn't stop others.
    """

    def __init__(self, config):
        """
        Initialize notification manager with all configured channels

        Args:
            config: ConfigManager instance or dict with notifications configuration
        """
        self.config = config
        self.notifiers: List = []
        self._initialize_notifiers()
        self._initialize_template_renderer()

    def _initialize_notifiers(self):
        """
        Initialize all enabled notification channels from config

        Loads notifier classes dynamically based on enabled channels list.
        Skips channels that are enabled but not properly configured.
        """
        # Import here to avoid circular dependencies
        from .pushover_notifier import PushoverNotifier
        from .discord_notifier import DiscordNotifier
        from .slack_notifier import SlackNotifier
        from .email_notifier import EmailNotifier
        from .webhook_notifier import WebhookNotifier

        # Get notifications config
        notifications_config = self.config.get("notifications") or {}
        enabled_channels = notifications_config.get("channels") or []

        if not enabled_channels:
            logger.warning("No notification channels enabled - notifications disabled")
            return

        # Map channel names to notifier classes
        channel_map: Dict[str, Type] = {
            "pushover": PushoverNotifier,
            "discord": DiscordNotifier,
            "slack": SlackNotifier,
            "email": EmailNotifier,
            "webhook": WebhookNotifier
        }

        # Initialize each enabled channel
        for channel_name in enabled_channels:
            if channel_name not in channel_map:
                logger.warning(f"Unknown notification channel: {channel_name}")
                continue

            try:
                notifier_class = channel_map[channel_name]
                notifier = notifier_class(self.config)

                if notifier.is_configured:
                    self.notifiers.append(notifier)
                    logger.info(f"✓ {notifier.channel_name} notifier initialized")
                else:
                    logger.warning(f"⚠ {notifier.channel_name} enabled but not configured - skipping")

            except Exception as e:
                logger.error(f"Failed to initialize {channel_name} notifier: {e}", exc_info=True)

        if not self.notifiers:
            logger.warning("No notification channels successfully configured - notifications disabled")

    def _initialize_template_renderer(self):
        """Initialize the Jinja2 template renderer."""
        from ..template_renderer import TemplateRenderer

        notifications_config = self.config.get("notifications") or {}
        custom_templates_dir = notifications_config.get("templates_dir")
        self.template_renderer = TemplateRenderer(custom_templates_dir)

    def send_invoice_notification(self, context: Dict[str, Any]) -> bool:
        """
        Send invoice notification using templates to all enabled channels.

        Args:
            context: Template context dict from InvoiceMonitor.build_template_context()

        Returns:
            True if at least one channel succeeded
        """
        if not self.notifiers:
            logger.debug("No notifiers configured - skipping notification")
            return False

        success_count = 0
        total_count = len(self.notifiers)

        for notifier in self.notifiers:
            try:
                if notifier.render_and_send(context, self.template_renderer):
                    success_count += 1
                    logger.debug(f"✓ {notifier.channel_name} invoice notification sent")
                else:
                    logger.warning(f"⚠ {notifier.channel_name} invoice notification failed")
            except Exception as e:
                logger.error(f"✗ {notifier.channel_name} invoice notification error: {e}", exc_info=True)

        if success_count > 0:
            logger.info(f"Invoice notification sent to {success_count}/{total_count} channel(s)")
            return True
        else:
            logger.error(f"All invoice notification channels failed ({total_count} tried)")
            return False

    def send_notification(self, title: str, message: str, priority: int = 0, url: Optional[str] = None) -> bool:
        """
        Send notification to all enabled channels

        Args:
            title: Notification title
            message: Notification message
            priority: Priority level (-2 to 2)
            url: Optional URL to include

        Returns:
            True if at least one channel succeeded, False if all failed or no channels
        """
        if not self.notifiers:
            logger.debug("No notifiers configured - skipping notification")
            return False

        success_count = 0
        total_count = len(self.notifiers)

        for notifier in self.notifiers:
            try:
                if notifier.send_notification(title, message, priority, url):
                    success_count += 1
                    logger.debug(f"✓ {notifier.channel_name} notification sent")
                else:
                    logger.warning(f"⚠ {notifier.channel_name} notification failed")
            except Exception as e:
                logger.error(f"✗ {notifier.channel_name} notification error: {e}", exc_info=True)

        if success_count > 0:
            logger.info(f"Notification sent successfully to {success_count}/{total_count} channel(s)")
            return True
        else:
            logger.error(f"All notification channels failed ({total_count} tried)")
            return False

    def send_error_notification(self, error_message: str) -> bool:
        """
        Send error notification to all enabled channels with high priority

        Args:
            error_message: Error message to send

        Returns:
            True if at least one channel succeeded
        """
        if not self.notifiers:
            logger.debug("No notifiers configured - skipping error notification")
            return False

        success_count = 0
        total_count = len(self.notifiers)

        for notifier in self.notifiers:
            try:
                if notifier.send_error_notification(error_message):
                    success_count += 1
                    logger.debug(f"✓ {notifier.channel_name} error notification sent")
                else:
                    logger.warning(f"⚠ {notifier.channel_name} error notification failed")
            except Exception as e:
                logger.error(f"✗ {notifier.channel_name} error notification error: {e}", exc_info=True)

        if success_count > 0:
            logger.info(f"Error notification sent to {success_count}/{total_count} channel(s)")
            return True
        else:
            logger.error(f"All error notification channels failed ({total_count} tried)")
            return False

    def test_connection(self) -> bool:
        """
        Test all configured notification channels

        Returns:
            True if at least one channel test succeeded
        """
        if not self.notifiers:
            logger.warning("No notifiers to test")
            return False

        logger.info(f"Testing {len(self.notifiers)} notification channel(s)...")

        success_count = 0
        total_count = len(self.notifiers)

        for notifier in self.notifiers:
            try:
                logger.info(f"Testing {notifier.channel_name}...")
                if notifier.test_connection():
                    logger.info(f"✓ {notifier.channel_name} test PASSED")
                    success_count += 1
                else:
                    logger.warning(f"⚠ {notifier.channel_name} test FAILED")
            except Exception as e:
                logger.error(f"✗ {notifier.channel_name} test ERROR: {e}", exc_info=True)

        logger.info(f"Notification test results: {success_count}/{total_count} passed")
        return success_count > 0

    @property
    def enabled_channels(self) -> List[str]:
        """
        Get list of successfully enabled channel names

        Returns:
            List of channel names (e.g., ["Pushover", "Discord"])
        """
        return [notifier.channel_name for notifier in self.notifiers]

    @property
    def has_channels(self) -> bool:
        """
        Check if any notification channels are configured

        Returns:
            True if at least one channel is enabled
        """
        return len(self.notifiers) > 0
