"""
Unit tests for TemplateRenderer and custom Jinja2 filters
"""

import json
import pytest
from datetime import datetime
from pathlib import Path

from app.template_renderer import (
    TemplateRenderer,
    money_filter,
    money_raw_filter,
    date_filter,
    json_escape_filter,
)


class TestMoneyFilter:
    """Tests for money_filter()."""

    def test_basic_format(self):
        """Basic amount formatting with PLN."""
        result = money_filter(1234.56)
        assert "1\u00a0234,56" in result
        assert "PLN" in result

    def test_custom_currency(self):
        """Custom currency code."""
        result = money_filter(100, currency="EUR")
        assert "100,00" in result
        assert "EUR" in result

    def test_large_number(self):
        """Thousands separator for large numbers."""
        result = money_filter(1234567.89)
        # Should have non-breaking space as thousands separator
        assert "\u00a0" in result

    def test_zero(self):
        """Zero amount."""
        result = money_filter(0)
        assert "0,00" in result
        assert "PLN" in result

    def test_string_number(self):
        """String number is converted."""
        result = money_filter("1234.56")
        assert "1\u00a0234,56" in result

    def test_invalid_value(self):
        """Invalid value returns as string."""
        result = money_filter("not-a-number")
        assert result == "not-a-number"

    def test_none_value(self):
        """None value returns 'None'."""
        result = money_filter(None)
        assert result == "None"


class TestMoneyRawFilter:
    """Tests for money_raw_filter()."""

    def test_no_currency_suffix(self):
        """No currency code appended."""
        result = money_raw_filter(1234.56)
        assert "PLN" not in result
        assert "1\u00a0234,56" in result

    def test_invalid_value(self):
        """Invalid value returns as string."""
        assert money_raw_filter("abc") == "abc"


class TestDateFilter:
    """Tests for date_filter()."""

    def test_iso_string(self):
        """ISO date string is formatted."""
        result = date_filter("2026-03-07T10:30:00")
        assert "2026-03-07" in result
        assert "10:30:00" in result

    def test_custom_format(self):
        """Custom date format."""
        result = date_filter("2026-03-07T10:30:00", fmt="%d.%m.%Y")
        assert result == "07.03.2026"

    def test_iso_with_z(self):
        """ISO date with Z suffix."""
        result = date_filter("2026-03-07T10:30:00Z")
        assert "2026-03-07" in result

    def test_datetime_object(self):
        """datetime object is formatted."""
        dt = datetime(2026, 3, 7, 10, 30)
        result = date_filter(dt)
        assert "2026-03-07" in result

    def test_invalid_value(self):
        """Invalid value returns as string."""
        result = date_filter("not-a-date")
        assert result == "not-a-date"

    def test_none_value(self):
        """None returns 'None'."""
        assert date_filter(None) == "None"

    def test_integer_value(self):
        """Integer returns string of integer."""
        assert date_filter(12345) == "12345"


class TestJsonEscapeFilter:
    """Tests for json_escape_filter()."""

    def test_quotes_escaped(self):
        """Double quotes are escaped."""
        result = json_escape_filter('hello "world"')
        assert '\\"' in result

    def test_newlines_escaped(self):
        """Newlines are escaped."""
        result = json_escape_filter("hello\nworld")
        assert "\\n" in result

    def test_backslash_escaped(self):
        """Backslashes are escaped."""
        result = json_escape_filter("path\\to\\file")
        assert "\\\\" in result

    def test_normal_string(self):
        """Normal string passes through."""
        assert json_escape_filter("hello world") == "hello world"

    def test_non_string_value(self):
        """Non-string is converted to string first."""
        result = json_escape_filter(12345)
        assert result == "12345"


class TestTemplateRenderer:
    """Tests for TemplateRenderer class."""

    def test_init_with_default_templates(self):
        """Initializes with built-in templates."""
        renderer = TemplateRenderer()
        assert renderer.env is not None

    def test_has_template_pushover(self):
        """Built-in pushover template exists."""
        renderer = TemplateRenderer()
        assert renderer.has_template("pushover") is True

    def test_has_template_email(self):
        """Built-in email template exists."""
        renderer = TemplateRenderer()
        assert renderer.has_template("email") is True

    def test_has_template_slack(self):
        """Built-in slack template exists."""
        renderer = TemplateRenderer()
        assert renderer.has_template("slack") is True

    def test_has_template_discord(self):
        """Built-in discord template exists."""
        renderer = TemplateRenderer()
        assert renderer.has_template("discord") is True

    def test_has_template_webhook(self):
        """Built-in webhook template exists."""
        renderer = TemplateRenderer()
        assert renderer.has_template("webhook") is True

    def test_has_template_unknown(self):
        """Unknown channel returns False."""
        renderer = TemplateRenderer()
        assert renderer.has_template("telegram") is False

    def test_render_pushover(self):
        """Render pushover template with context."""
        renderer = TemplateRenderer()
        context = {
            "title": "Test",
            "ksef_number": "1234567890-20260301-ABC123-XY",
            "invoice_number": "FV/001",
            "issue_date": "2026-03-01",
            "gross_amount": 1230.00,
            "net_amount": 1000.00,
            "vat_amount": 230.00,
            "currency": "PLN",
            "seller_name": "Seller",
            "seller_nip": "9876543210",
            "buyer_name": "Buyer",
            "buyer_nip": "1234567890",
            "subject_type": "Subject1",
            "priority": 0,
            "priority_emoji": "📋",
            "priority_name": "normal",
            "priority_color": "#36a64f",
            "priority_color_int": 0x36a64f,
            "timestamp": "2026-03-07T10:00:00",
            "url": None,
        }
        result = renderer.render("pushover", context)
        assert result is not None
        assert "FV/001" in result or "1234567890" in result

    def test_render_unknown_channel(self):
        """Unknown channel returns None."""
        renderer = TemplateRenderer()
        assert renderer.render("telegram", {}) is None

    def test_custom_templates_dir(self, tmp_path):
        """Custom templates directory is used when valid."""
        # Create a custom template
        template = tmp_path / "pushover.txt.j2"
        template.write_text("CUSTOM: {{ title }}")

        renderer = TemplateRenderer(str(tmp_path))
        result = renderer.render("pushover", {"title": "Hello"})
        assert result == "CUSTOM: Hello"

    def test_custom_dir_not_found_falls_back(self):
        """Non-existent custom dir falls back to defaults."""
        renderer = TemplateRenderer("/nonexistent/templates")
        # Should still have built-in templates
        assert renderer.has_template("pushover") is True

    def test_filters_registered(self):
        """Custom filters are registered in Jinja2 environment."""
        renderer = TemplateRenderer()
        assert "money" in renderer.env.filters
        assert "money_raw" in renderer.env.filters
        assert "date" in renderer.env.filters
        assert "json_escape" in renderer.env.filters
