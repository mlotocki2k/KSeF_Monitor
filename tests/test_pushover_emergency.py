"""Pushover emergency priority carries the required retry/expire."""

from unittest.mock import MagicMock

import pytest

from app.notifiers.pushover_notifier import PushoverNotifier


def _n():
    n = PushoverNotifier({"notifications": {"pushover": {"user_key": "u", "api_token": "t"}}})
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    n.session.post = MagicMock(return_value=resp)
    return n


@pytest.mark.parametrize("priority,has", [(2, True), (1, False), (0, False)])
def test_emergency_params(priority, has):
    n = _n()
    n.send_notification("t", "m", priority=priority)
    data = n.session.post.call_args.kwargs["data"]
    assert ("retry" in data and "expire" in data) is has
    if has:
        assert data["retry"] >= 30 and data["expire"] <= 10800


def test_emergency_params_template_path():
    n = _n()
    n._send_rendered("msg", {"title": "t", "priority": 2})
    data = n.session.post.call_args.kwargs["data"]
    assert data["retry"] == 60 and data["expire"] == 3600
