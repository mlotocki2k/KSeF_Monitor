"""
Email Notification Service
Sends notifications via SMTP with HTML formatting
"""

import logging
import re
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any, Dict, Optional, List

from .base_notifier import BaseNotifier

logger = logging.getLogger(__name__)


class EmailNotifier(BaseNotifier):
    """Send notifications via email using SMTP"""

    _EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

    # Priority to X-Priority header mapping (email standard)
    PRIORITY_HEADER = {
        -2: "5",  # Lowest
        -1: "5",  # Low
        0: "3",   # Normal
        1: "2",   # High
        2: "1",   # Highest
    }

    def __init__(self, config):
        """
        Initialize Email notifier

        Args:
            config: ConfigManager instance or dict with notifications configuration
        """
        super().__init__()
        notifications_config = config.get("notifications") or {}
        email_config = notifications_config.get("email") or {}

        self.smtp_server = email_config.get("smtp_server")
        self.smtp_port = email_config.get("smtp_port", 587)
        self.use_tls = email_config.get("use_tls", True)
        self.username = email_config.get("username")
        self.password = email_config.get("password")
        self.from_address = email_config.get("from_address")
        self.to_addresses = email_config.get("to_addresses", [])
        self.timeout = email_config.get("timeout", 30)

        # Validate email addresses at init time
        self._validate_addresses()

        if not self.is_configured:
            logger.debug("Email SMTP configuration incomplete")

    def _validate_addresses(self):
        """Validate email address format at startup."""
        if self.from_address and not self._EMAIL_RE.match(self.from_address):
            logger.warning(f"Invalid from_address format: {self.from_address}")
            self.from_address = None
        invalid = [a for a in self.to_addresses if not self._EMAIL_RE.match(a)]
        if invalid:
            logger.warning(f"Removing invalid to_addresses: {invalid}")
            self.to_addresses = [a for a in self.to_addresses if self._EMAIL_RE.match(a)]

    @property
    def is_configured(self) -> bool:
        """Check if Email is properly configured"""
        return bool(
            self.smtp_server and
            self.username and
            self.password and
            self.from_address and
            self.to_addresses
        )

    @property
    def channel_name(self) -> str:
        """Return channel name for logging"""
        return "Email"

    def _create_html_message(self, title: str, message: str, priority: int, url: Optional[str] = None) -> str:
        """
        Create HTML-formatted email message

        Args:
            title: Message title
            message: Message body
            priority: Priority level
            url: Optional URL to include

        Returns:
            HTML-formatted email body
        """
        # Priority badge styling
        priority_styles = {
            -2: ("🔕 Lowest", "#808080"),
            -1: ("💤 Low", "#808080"),
            0: ("📋 Normal", "#36a64f"),
            1: ("⚠️ High", "#ff9900"),
            2: ("🚨 Emergency", "#e74c3c"),
        }
        badge_text, badge_color = priority_styles.get(priority, ("📋 Normal", "#36a64f"))

        # Convert newlines to HTML breaks
        html_message = message.replace("\n", "<br>")

        # Build HTML
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #f4f4f4; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
                .priority {{ background-color: {badge_color}; color: white; padding: 5px 10px; border-radius: 3px; display: inline-block; margin-bottom: 10px; }}
                .content {{ background-color: #ffffff; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }}
                .footer {{ margin-top: 20px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 12px; }}
                .button {{ background-color: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block; margin-top: 10px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="priority">{badge_text}</div>
                    <h2 style="margin: 10px 0 0 0;">{title}</h2>
                </div>
                <div class="content">
                    <p>{html_message}</p>
                    {f'<a href="{url}" class="button">View in KSeF</a>' if url else ''}
                </div>
                <div class="footer">
                    <p>KSeF Invoice Monitor</p>
                    <p>This is an automated notification. Please do not reply to this email.</p>
                </div>
            </div>
        </body>
        </html>
        """
        return html

    def send_notification(self, title: str, message: str, priority: int = 0, url: Optional[str] = None) -> bool:
        """
        Send notification via email

        Args:
            title: Email subject
            message: Email message
            priority: Priority level (-2 to 2) - mapped to X-Priority header
            url: Optional URL to include in email

        Returns:
            True if successful, False otherwise
        """
        if not self.is_configured:
            logger.error("Email not configured - notification not sent")
            return False

        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"[KSeF Monitor] {title}"
            msg['From'] = self.from_address
            msg['To'] = ', '.join(self.to_addresses)
            msg['X-Priority'] = self.PRIORITY_HEADER.get(priority, "3")

            # Plain text fallback
            text_content = f"{title}\n\n{message}"
            if url:
                text_content += f"\n\nView in KSeF: {url}"
            part1 = MIMEText(text_content, 'plain')

            # HTML version
            html_content = self._create_html_message(title, message, priority, url)
            part2 = MIMEText(html_content, 'html')

            # Attach both parts (plain text should be first)
            msg.attach(part1)
            msg.attach(part2)

            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=self.timeout) as server:
                if self.use_tls:
                    server.starttls(context=ssl.create_default_context())
                server.login(self.username, self.password)
                server.sendmail(self.from_address, self.to_addresses, msg.as_string())

            logger.info(f"Email notification sent to {len(self.to_addresses)} recipient(s): {title}")
            return True

        except smtplib.SMTPException as e:
            logger.error(f"SMTP error sending email notification: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending email notification: {e}")
            return False

    def _send_rendered(self, rendered: str, context: Dict[str, Any]) -> bool:
        """Send email with rendered HTML template as body."""
        if not self.is_configured:
            logger.error("Email not configured - notification not sent")
            return False

        try:
            title = context.get("title", "")
            priority = context.get("priority", 0)

            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"[KSeF Monitor] {title}"
            msg['From'] = self.from_address
            msg['To'] = ', '.join(self.to_addresses)
            msg['X-Priority'] = self.PRIORITY_HEADER.get(priority, "3")

            # Plain text fallback
            text_content = f"{title}\n\n{self._build_fallback_message(context)}"
            msg.attach(MIMEText(text_content, 'plain'))

            # HTML from template
            msg.attach(MIMEText(rendered, 'html'))

            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=self.timeout) as server:
                if self.use_tls:
                    server.starttls(context=ssl.create_default_context())
                server.login(self.username, self.password)
                server.sendmail(self.from_address, self.to_addresses, msg.as_string())

            logger.info(f"Email notification sent to {len(self.to_addresses)} recipient(s): {title}")
            return True

        except smtplib.SMTPException as e:
            logger.error(f"SMTP error sending email notification: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending email notification: {e}")
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
        Test email configuration by sending a test notification

        Returns:
            True if test successful
        """
        return self.send_notification(
            title="KSeF Monitor Test",
            message="Test notification - Email integration is configured correctly!",
            priority=0
        )
