"""Channel URLs carrying credentials must use https (or loopback)."""

import logging
from unittest.mock import patch

import pytest

from app.config_manager import ConfigManager


@pytest.fixture
def cm():
    return object.__new__(ConfigManager)


def test_ios_push_worker_url_http_rejected(cm):
    with pytest.raises(ValueError, match="https"):
        cm._validate_channel("ios_push", {"worker_url": "http://push.example.com"})


@pytest.mark.parametrize("url", ["https://push.monitorksef.com", "http://localhost:8787",
                                 "http://127.0.0.1:8787"])
def test_ios_push_worker_url_ok(cm, url):
    cm._validate_channel("ios_push", {"worker_url": url})


def test_slack_http_warns(cm, caplog):
    caplog.set_level(logging.WARNING)
    cm._validate_channel("slack", {"webhook_url": "http://chat.lan/hooks/x"})
    assert "not https" in caplog.text


def test_email_plaintext_login_warns(cm, caplog):
    caplog.set_level(logging.WARNING)
    cm._validate_channel("email", {"smtp_server": "s", "username": "u", "password": "p",
                                   "from_address": "a@b.c", "to_addresses": ["a@b.c"],
                                   "use_tls": False})
    assert "unencrypted" in caplog.text


def test_webhook_lan_receiver_no_https_warning(cm, caplog):
    """Issue #64: allow_private_network marks a deliberate plain-http LAN receiver."""
    caplog.set_level(logging.WARNING)
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("192.168.8.20", 0))]):
        cm._validate_channel("webhook", {"url": "http://receiver.lan:8080/hook",
                                         "allow_private_network": True})
    assert "not https" not in caplog.text


def test_webhook_public_http_warns_even_with_private_flag(cm, caplog):
    caplog.set_level(logging.WARNING)
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]):
        cm._validate_channel("webhook", {"url": "http://public.example/hook",
                                         "allow_private_network": True})
    assert "not https" in caplog.text


@pytest.mark.parametrize("monitoring", [
    {"subject_poll_intervals": {"Subject1": "240"}},
    {"subject_poll_intervals": {"Subject9": 60}},
    {"subject_types": ["Subject1", "Bogus"]},
    {"subject_types": []},
    {"artifact_batch_size": "50"},
    {"artifact_batch_size": True},
])
def test_invalid_monitoring_values_rejected(cm, monitoring):
    with pytest.raises(ValueError):
        cm._validate_monitoring({"monitoring": monitoring})


def test_single_subject_type_string_accepted(cm):
    cfg = {"monitoring": {"subject_types": "Subject2"}}
    cm._validate_monitoring(cfg)
    assert cfg["monitoring"]["subject_types"] == ["Subject2"]


def test_valid_monitoring_values_pass(cm):
    cm._validate_monitoring({"monitoring": {"subject_types": ["Subject1", "Subject2"],
                                            "subject_poll_intervals": {"Subject2": 420.5},
                                            "artifact_batch_size": 50}})
