"""
Unit tests for NotificationManager and BaseNotifier
"""

import pytest
from unittest.mock import patch, MagicMock

from app.notifiers.base_notifier import BaseNotifier


class TestBaseNotifierFallbackMessage:
    """Tests for _build_fallback_message()."""

    def test_subject1_message(self):
        """Subject1 shows buyer as counterparty."""
        context = {
            "subject_type": "Subject1",
            "buyer_name": "Klient ABC",
            "buyer_nip": "1234567890",
            "invoice_number": "FV/001",
            "issue_date": "2026-03-01",
            "gross_amount": 1230.00,
            "currency": "PLN",
            "ksef_number": "1234567890-20260301-ABC123-XY",
        }
        msg = BaseNotifier._build_fallback_message(context)
        assert "Do: Klient ABC" in msg
        assert "FV/001" in msg
        assert "1230.0" in msg or "1230" in msg

    def test_subject2_message(self):
        """Subject2 shows seller as counterparty."""
        context = {
            "subject_type": "Subject2",
            "seller_name": "Dostawca XYZ",
            "seller_nip": "9876543210",
            "invoice_number": "FV/002",
            "issue_date": "2026-03-01",
            "gross_amount": 500.00,
            "currency": "PLN",
            "ksef_number": "9876543210-20260301-DEF456-AB",
        }
        msg = BaseNotifier._build_fallback_message(context)
        assert "Od: Dostawca XYZ" in msg
        assert "FV/002" in msg

    def test_unknown_subject_shows_both(self):
        """Unknown subject type shows both seller and buyer."""
        context = {
            "subject_type": "SubjectOther",
            "seller_name": "Seller",
            "seller_nip": "1111111111",
            "buyer_name": "Buyer",
            "buyer_nip": "2222222222",
            "invoice_number": "FV/003",
            "issue_date": "2026-03-01",
            "gross_amount": 100,
            "currency": "PLN",
            "ksef_number": "N/A",
        }
        msg = BaseNotifier._build_fallback_message(context)
        assert "Od: Seller" in msg
        assert "Do: Buyer" in msg

    def test_missing_fields_use_na(self):
        """Missing fields default to N/A."""
        msg = BaseNotifier._build_fallback_message({})
        assert "N/A" in msg


class TestBaseNotifierRenderAndSend:
    """Tests for render_and_send()."""

    def _make_concrete_notifier(self):
        """Create a concrete implementation of BaseNotifier for testing."""
        class TestNotifier(BaseNotifier):
            def __init__(self):
                super().__init__()
                self.sent_messages = []

            def send_notification(self, title, message, priority=0, url=None):
                self.sent_messages.append((title, message, priority, url))
                return True

            def send_error_notification(self, error_message):
                return True

            def test_connection(self):
                return True

            @property
            def is_configured(self):
                return True

            @property
            def channel_name(self):
                return "Test"

        return TestNotifier()

    def test_template_success(self):
        """Successful template rendering calls _send_rendered."""
        notifier = self._make_concrete_notifier()
        renderer = MagicMock()
        renderer.render.return_value = "Rendered content"

        context = {"title": "Test", "priority": 0, "url": None}
        result = notifier.render_and_send(context, renderer)
        assert result is True

    def test_template_failure_uses_fallback(self):
        """Failed template rendering falls back to plain text."""
        notifier = self._make_concrete_notifier()
        renderer = MagicMock()
        renderer.render.return_value = None

        context = {
            "title": "Test", "priority": 0, "url": None,
            "subject_type": "Subject1", "buyer_name": "Buyer",
            "buyer_nip": "1234567890", "invoice_number": "FV/001",
            "issue_date": "2026-01-01", "gross_amount": 100,
            "currency": "PLN", "ksef_number": "N/A"
        }
        result = notifier.render_and_send(context, renderer)
        assert result is True
        assert len(notifier.sent_messages) == 1
        assert "FV/001" in notifier.sent_messages[0][1]


class TestNotificationManager:
    """Tests for NotificationManager."""

    def test_no_channels_configured(self, mock_config):
        """No channels configured means no notifiers."""
        mock_config.config["notifications"]["channels"] = []

        def _get(*keys, default=None):
            value = mock_config.config
            for key in keys:
                if isinstance(key, str) and isinstance(value, dict):
                    value = value.get(key)
                    if value is None:
                        return default
                else:
                    return default
            return value

        mock_config.get = _get

        from app.notifiers.notification_manager import NotificationManager
        nm = NotificationManager(mock_config)
        assert nm.has_channels is False
        assert nm.enabled_channels == []

    def test_send_notification_no_channels(self, mock_config):
        """send_notification returns False when no channels."""
        mock_config.config["notifications"]["channels"] = []

        def _get(*keys, default=None):
            value = mock_config.config
            for key in keys:
                if isinstance(key, str) and isinstance(value, dict):
                    value = value.get(key)
                    if value is None:
                        return default
                else:
                    return default
            return value

        mock_config.get = _get

        from app.notifiers.notification_manager import NotificationManager
        nm = NotificationManager(mock_config)
        assert nm.send_notification("Title", "Message") is False

    def test_send_error_notification_no_channels(self, mock_config):
        """send_error_notification returns False when no channels."""
        mock_config.config["notifications"]["channels"] = []

        def _get(*keys, default=None):
            value = mock_config.config
            for key in keys:
                if isinstance(key, str) and isinstance(value, dict):
                    value = value.get(key)
                    if value is None:
                        return default
                else:
                    return default
            return value

        mock_config.get = _get

        from app.notifiers.notification_manager import NotificationManager
        nm = NotificationManager(mock_config)
        assert nm.send_error_notification("Error") is False

    def test_unknown_channel_skipped(self, mock_config):
        """Unknown channel names are skipped."""
        mock_config.config["notifications"]["channels"] = ["telegram"]

        def _get(*keys, default=None):
            value = mock_config.config
            for key in keys:
                if isinstance(key, str) and isinstance(value, dict):
                    value = value.get(key)
                    if value is None:
                        return default
                else:
                    return default
            return value

        mock_config.get = _get

        from app.notifiers.notification_manager import NotificationManager
        nm = NotificationManager(mock_config)
        assert nm.has_channels is False

    def test_notifier_init_failure_handled(self, mock_config):
        """Failed notifier initialization is handled gracefully."""
        mock_config.config["notifications"]["channels"] = ["pushover"]
        mock_config.config["notifications"]["pushover"] = {}  # missing keys

        def _get(*keys, default=None):
            value = mock_config.config
            for key in keys:
                if isinstance(key, str) and isinstance(value, dict):
                    value = value.get(key)
                    if value is None:
                        return default
                else:
                    return default
            return value

        mock_config.get = _get

        from app.notifiers.notification_manager import NotificationManager
        nm = NotificationManager(mock_config)
        # Pushover without user_key/api_token is not configured
        # It should be skipped without crashing
        # (may or may not have channels depending on is_configured check)


class TestNotificationManagerWithMockedNotifiers:
    """Tests with mocked notifier objects."""

    def test_send_to_all_channels(self, mock_config):
        """Sends to all configured channels."""
        from app.notifiers.notification_manager import NotificationManager

        nm = NotificationManager.__new__(NotificationManager)
        nm.config = mock_config
        nm.db = None
        nm.template_renderer = MagicMock()

        notifier1 = MagicMock()
        notifier1.channel_name = "Channel1"
        notifier1.send_notification.return_value = True

        notifier2 = MagicMock()
        notifier2.channel_name = "Channel2"
        notifier2.send_notification.return_value = True

        nm.notifiers = [notifier1, notifier2]

        result = nm.send_notification("Title", "Message")
        assert result is True
        notifier1.send_notification.assert_called_once()
        notifier2.send_notification.assert_called_once()

    def test_partial_failure_still_succeeds(self, mock_config):
        """One channel failing still returns True if another succeeds."""
        from app.notifiers.notification_manager import NotificationManager

        nm = NotificationManager.__new__(NotificationManager)
        nm.config = mock_config
        nm.db = None

        notifier1 = MagicMock()
        notifier1.channel_name = "Failing"
        notifier1.send_notification.return_value = False

        notifier2 = MagicMock()
        notifier2.channel_name = "Working"
        notifier2.send_notification.return_value = True

        nm.notifiers = [notifier1, notifier2]

        result = nm.send_notification("Title", "Message")
        assert result is True

    def test_all_channels_fail(self, mock_config):
        """All channels failing returns False."""
        from app.notifiers.notification_manager import NotificationManager

        nm = NotificationManager.__new__(NotificationManager)
        nm.config = mock_config
        nm.db = None

        notifier1 = MagicMock()
        notifier1.channel_name = "Failing1"
        notifier1.send_notification.return_value = False

        notifier2 = MagicMock()
        notifier2.channel_name = "Failing2"
        notifier2.send_notification.return_value = False

        nm.notifiers = [notifier1, notifier2]

        result = nm.send_notification("Title", "Message")
        assert result is False

    def test_channel_exception_handled(self, mock_config):
        """Channel raising exception is handled gracefully."""
        from app.notifiers.notification_manager import NotificationManager

        nm = NotificationManager.__new__(NotificationManager)
        nm.config = mock_config
        nm.db = None

        notifier1 = MagicMock()
        notifier1.channel_name = "Crashing"
        notifier1.send_notification.side_effect = RuntimeError("boom")

        notifier2 = MagicMock()
        notifier2.channel_name = "Working"
        notifier2.send_notification.return_value = True

        nm.notifiers = [notifier1, notifier2]

        result = nm.send_notification("Title", "Message")
        assert result is True

    def test_send_invoice_notification(self, mock_config):
        """send_invoice_notification calls render_and_send on each notifier."""
        from app.notifiers.notification_manager import NotificationManager

        nm = NotificationManager.__new__(NotificationManager)
        nm.config = mock_config
        nm.db = None
        nm.template_renderer = MagicMock()

        notifier = MagicMock()
        notifier.channel_name = "Test"
        notifier.render_and_send.return_value = True

        nm.notifiers = [notifier]

        context = {"title": "Test", "priority": 0}
        result = nm.send_invoice_notification(context)
        assert result is True
        notifier.render_and_send.assert_called_once_with(context, nm.template_renderer)

    def test_test_connection(self, mock_config):
        """test_connection tests all channels."""
        from app.notifiers.notification_manager import NotificationManager

        nm = NotificationManager.__new__(NotificationManager)
        nm.config = mock_config

        notifier = MagicMock()
        notifier.channel_name = "Test"
        notifier.test_connection.return_value = True

        nm.notifiers = [notifier]

        assert nm.test_connection() is True
        notifier.test_connection.assert_called_once()

    def test_enabled_channels_property(self, mock_config):
        """enabled_channels returns list of channel names."""
        from app.notifiers.notification_manager import NotificationManager

        nm = NotificationManager.__new__(NotificationManager)

        notifier1 = MagicMock()
        notifier1.channel_name = "Pushover"
        notifier2 = MagicMock()
        notifier2.channel_name = "Discord"

        nm.notifiers = [notifier1, notifier2]

        assert nm.enabled_channels == ["Pushover", "Discord"]
