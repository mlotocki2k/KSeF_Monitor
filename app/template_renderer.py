"""
Template Renderer for KSeF Invoice Monitor

Jinja2-based template engine with custom filters for invoice notifications.
Each notification channel (email, slack, discord, pushover, webhook) has its
own template file. Users can override defaults by providing a custom templates
directory in config (notifications.templates_dir).
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

logger = logging.getLogger(__name__)

# Default templates directory (shipped with the application)
DEFAULT_TEMPLATES_DIR = Path(__file__).parent / "templates"


def money_filter(value, currency: str = "PLN") -> str:
    """
    Format monetary value according to Polish norms with currency suffix.

    Usage in template: {{ gross_amount | money }}
                       {{ gross_amount | money("EUR") }}
    """
    try:
        num = float(value)
        formatted = f"{num:,.2f}"
        formatted = formatted.replace(",", "\u00a0").replace(".", ",")
        return f"{formatted} {currency}"
    except (ValueError, TypeError):
        return str(value)


def money_raw_filter(value) -> str:
    """
    Format monetary value without currency suffix.

    Usage in template: {{ gross_amount | money_raw }} {{ currency }}
    """
    try:
        num = float(value)
        formatted = f"{num:,.2f}"
        formatted = formatted.replace(",", "\u00a0").replace(".", ",")
        return formatted
    except (ValueError, TypeError):
        return str(value)


def date_filter(value, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Format date string.

    Usage in template: {{ issue_date | date }}
                       {{ issue_date | date("%d.%m.%Y") }}
    """
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif isinstance(value, datetime):
            dt = value
        else:
            return str(value)
        return dt.strftime(fmt)
    except (ValueError, TypeError):
        return str(value)


def json_escape_filter(value) -> str:
    """
    Escape string for safe inclusion in JSON templates.

    Usage in template: {{ seller_name | json_escape }}
    """
    return json.dumps(str(value))[1:-1]


class TemplateRenderer:
    """
    Jinja2 template renderer for notification channels.

    Loads templates from user-provided directory (if configured)
    with fallback to built-in defaults.
    """

    TEMPLATE_MAP = {
        "email": "email.html.j2",
        "slack": "slack.json.j2",
        "discord": "discord.json.j2",
        "pushover": "pushover.txt.j2",
        "webhook": "webhook.json.j2",
    }

    def __init__(self, custom_templates_dir: Optional[str] = None):
        search_paths = []

        if custom_templates_dir:
            custom_path = Path(custom_templates_dir)
            if custom_path.is_dir():
                search_paths.append(str(custom_path))
                logger.info(f"Custom templates directory: {custom_path}")
            else:
                logger.warning(
                    f"Custom templates directory not found: {custom_path}, "
                    f"using defaults only"
                )

        search_paths.append(str(DEFAULT_TEMPLATES_DIR))

        self.env = Environment(
            loader=FileSystemLoader(search_paths),
            autoescape=select_autoescape(["html"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        self.env.filters["money"] = money_filter
        self.env.filters["money_raw"] = money_raw_filter
        self.env.filters["date"] = date_filter
        self.env.filters["json_escape"] = json_escape_filter

        logger.info(f"TemplateRenderer initialized, search paths: {search_paths}")

    def render(self, channel: str, context: Dict[str, Any]) -> Optional[str]:
        """
        Render template for a given channel.

        Args:
            channel: Channel name (email, slack, discord, pushover, webhook)
            context: Template context dictionary with invoice data

        Returns:
            Rendered template string, or None if rendering fails
        """
        template_name = self.TEMPLATE_MAP.get(channel)
        if not template_name:
            logger.error(f"No template mapping for channel: {channel}")
            return None

        try:
            template = self.env.get_template(template_name)
            return template.render(**context)
        except TemplateNotFound:
            logger.error(f"Template not found for channel '{channel}': {template_name}")
            return None
        except Exception as e:
            logger.error(
                f"Template rendering error for channel '{channel}': {e}",
                exc_info=True,
            )
            return None

    def has_template(self, channel: str) -> bool:
        """Check if a template exists for the given channel."""
        template_name = self.TEMPLATE_MAP.get(channel)
        if not template_name:
            return False
        try:
            self.env.get_template(template_name)
            return True
        except TemplateNotFound:
            return False
