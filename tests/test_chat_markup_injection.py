"""
Invoice fields come from the issuer: they must not become Slack mrkdwn control
sequences (<!channel>, <url|label> links) or Discord markdown (masked links).
"""

import json
from unittest.mock import MagicMock

from app.notifiers.discord_notifier import DiscordNotifier
from app.notifiers.slack_notifier import SlackNotifier
from app.template_renderer import TemplateRenderer, discord_escape_filter, slack_escape_filter

EVIL = "<!channel> <https://evil.example/pay|https://ksef.mf.gov.pl/zaplac> [Zapłać](https://evil.example)"


def _ctx():
    return {
        "ksef_number": "1234567890-20260101-ABCDEF-12", "invoice_number": "FV/1",
        "issue_date": "2026-01-01", "gross_amount": 10.0, "net_amount": 8.13, "vat_amount": 1.87,
        "currency": "PLN", "seller_name": EVIL, "seller_nip": "1234567890",
        "buyer_name": "B", "buyer_nip": "1111111111", "subject_type": "Subject2",
        "schema_type": "FA3", "title": "Nowa faktura", "priority": 0, "priority_emoji": "📋",
        "priority_name": "normal", "priority_color": "#36a64f", "priority_color_int": 1,
        "timestamp": "2026-01-01T00:00:00Z", "url": None,
    }


def test_slack_template_escapes_mrkdwn():
    payload = json.loads(TemplateRenderer().render("slack", _ctx()))
    text = json.dumps(payload, ensure_ascii=False)
    assert "<!channel>" not in text
    assert "<https://evil" not in text
    assert "&lt;!channel&gt;" in text


def test_discord_template_escapes_markdown_links():
    payload = json.loads(TemplateRenderer().render("discord", _ctx()))
    assert "[Zapłać](https://evil.example)" not in payload["description"]
    assert "\\[Zapłać\\]\\(https://evil.example\\)" in payload["description"]


def test_slack_fallback_message_escaped():
    n = SlackNotifier({"notifications": {"slack": {"webhook_url": "https://hooks.slack.com/services/x"}}})
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    n.session.post = MagicMock(return_value=resp)
    n.send_notification("t", f"Od: {EVIL}")
    body = json.dumps(n.session.post.call_args.kwargs["json"], ensure_ascii=False)
    assert "<!channel> <https" not in body


def test_discord_fallback_message_escaped():
    n = DiscordNotifier({"notifications": {"discord": {"webhook_url": "https://discord.com/api/webhooks/1/x"}}})
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    n.session.post = MagicMock(return_value=resp)
    n.send_notification("t", f"Od: {EVIL}")
    desc = n.session.post.call_args.kwargs["json"]["embeds"][0]["description"]
    assert "[Zapłać](https://evil.example)" not in desc


def test_filters():
    assert slack_escape_filter("a & <b>") == "a &amp; &lt;b&gt;"
    assert discord_escape_filter("[x](y) *b* _i_") == "\\[x\\]\\(y\\) \\*b\\* \\_i\\_"
