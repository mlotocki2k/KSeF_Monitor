"""
Webhook URLs of Slack/Discord/generic webhooks are credentials — they must not
reach the logs through requests' exception messages. The webhook HMAC must be
computed over the exact bytes that are sent.
"""

import hashlib
import hmac
import json
import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.notifiers.discord_notifier import DiscordNotifier
from app.notifiers.slack_notifier import SlackNotifier
from app.notifiers.webhook_notifier import WebhookNotifier

SECRET = "SECRETWEBHOOKTOKEN"


def _cfg(channel, **extra):
    url = {
        "slack": f"https://hooks.slack.com/services/T0/B0/{SECRET}",
        "discord": f"https://discord.com/api/webhooks/1/{SECRET}",
        "webhook": f"https://example.com/hook/{SECRET}",
    }[channel]
    key = "url" if channel == "webhook" else "webhook_url"
    return {"notifications": {channel: {key: url, **extra}}}


def _make(channel, **extra):
    cls = {"slack": SlackNotifier, "discord": DiscordNotifier, "webhook": WebhookNotifier}[channel]
    with patch("app.notifiers.webhook_notifier.is_safe_public_url", return_value=True):
        n = cls(_cfg(channel, **extra))
    if channel == "webhook":
        n._revalidate_url = lambda: True
    return n


ERRORS = [
    requests.exceptions.ConnectionError(
        f"HTTPSConnectionPool: Max retries exceeded with url: /services/T0/B0/{SECRET}"
    ),
    requests.exceptions.HTTPError(f"404 Client Error: Not Found for url: https://x/{SECRET}"),
]


@pytest.fixture
def notifier_log():
    """Capture notifier logs directly — other tests reconfigure app logging
    (propagation / disabled loggers), which would leave caplog empty."""
    records = []

    class _H(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    handler = _H(level=logging.DEBUG)
    names = [f"app.notifiers.{m}" for m in ("slack_notifier", "discord_notifier", "webhook_notifier")]
    saved = []
    for name in names:
        lg = logging.getLogger(name)
        saved.append((lg, lg.level, lg.disabled))
        lg.addHandler(handler)
        lg.setLevel(logging.DEBUG)
        lg.disabled = False
    yield records
    for lg, level, disabled in saved:
        lg.removeHandler(handler)
        lg.setLevel(level)
        lg.disabled = disabled


@pytest.mark.parametrize("channel", ["slack", "discord", "webhook"])
@pytest.mark.parametrize("err", ERRORS, ids=["conn", "http"])
def test_request_errors_do_not_log_webhook_url(channel, err, notifier_log):
    n = _make(channel)
    n.session.post = MagicMock(side_effect=err)

    assert n.send_notification("t", "m") is False
    assert n._send_rendered(json.dumps({"title": "t", "content": "c"}), {"title": "t"}) is False

    text = "\n".join(notifier_log)
    assert SECRET not in text
    assert type(err).__name__ in text


@pytest.mark.parametrize("path", ["plain", "rendered"])
def test_webhook_signature_matches_sent_body(path):
    n = _make("webhook", signing_secret="s3cret")
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    n.session.post = MagicMock(return_value=resp)

    if path == "plain":
        assert n.send_notification("tytuł", "wiadomość") is True
    else:
        assert n._send_rendered('{"title": "tytuł", "n": 1}', {"title": "t"}) is True

    kwargs = n.session.post.call_args.kwargs
    body = kwargs["data"]
    expected = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert kwargs["headers"]["X-Signature"] == f"sha256={expected}"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert json.loads(body)["title"] == "tytuł"
