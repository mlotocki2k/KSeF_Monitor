"""Tests for app._ssrf_guard — shared SSRF validation."""
from unittest.mock import patch

import pytest

from app._ssrf_guard import is_safe_public_url


class TestIsSafePublicUrl:
    def test_public_https_url_allowed(self):
        # No mock: real DNS to a known public hostname. Skip if no network.
        try:
            result = is_safe_public_url("https://example.com/webhook")
        except Exception:
            pytest.skip("no network")
        assert result is True

    def test_http_scheme_allowed(self):
        # DNS-bound test; mock for determinism
        with patch("app._ssrf_guard.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
            assert is_safe_public_url("http://example.com/") is True

    def test_other_scheme_rejected(self):
        assert is_safe_public_url("file:///etc/passwd") is False
        assert is_safe_public_url("ftp://example.com") is False
        assert is_safe_public_url("gopher://example.com") is False

    def test_missing_hostname_rejected(self):
        assert is_safe_public_url("https:///path") is False

    def test_empty_url_rejected(self):
        assert is_safe_public_url("") is False
        assert is_safe_public_url(None) is False

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_private_ipv4_rejected(self, mock_gai):
        mock_gai.return_value = [(2, 1, 6, "", ("10.0.0.1", 0))]
        assert is_safe_public_url("https://internal.local/") is False

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_loopback_rejected(self, mock_gai):
        mock_gai.return_value = [(2, 1, 6, "", ("127.0.0.1", 0))]
        assert is_safe_public_url("https://localhost/") is False

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_link_local_rejected(self, mock_gai):
        mock_gai.return_value = [(2, 1, 6, "", ("169.254.169.254", 0))]
        assert is_safe_public_url("https://metadata.internal/") is False

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_dns_failure_rejected(self, mock_gai):
        import socket as _socket
        mock_gai.side_effect = _socket.gaierror()
        assert is_safe_public_url("https://does-not-exist.invalid/") is False

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_ipv6_loopback_rejected(self, mock_gai):
        mock_gai.return_value = [(10, 1, 6, "", ("::1", 0, 0, 0))]
        assert is_safe_public_url("https://ipv6-local/") is False

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_multicast_rejected(self, mock_gai):
        mock_gai.return_value = [(2, 1, 6, "", ("224.0.0.1", 0))]
        assert is_safe_public_url("https://mcast.example/") is False

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_unparseable_ip_rejected(self, mock_gai):
        """R8: IPv6 scope-id or malformed IP should reject, not silently pass."""
        mock_gai.return_value = [(10, 1, 6, "", ("fe80::1%eth0", 0, 0, 0))]
        assert is_safe_public_url("https://scoped.ipv6/") is False


class TestAllowPrivateOverride:
    """Issue #64: opt-in override for private ranges (webhooks on a LAN).

    The override relaxes ONLY the is_private check — every other class of
    non-public address stays blocked. Note that 169.254.169.254 (cloud
    metadata) has is_private == True in Python's ipaddress, so a blanket
    bypass would expose IMDS; it must stay blocked via is_link_local.
    """

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_default_still_rejects_private(self, mock_gai):
        """Default arg keeps the pre-#64 behaviour."""
        mock_gai.return_value = [(2, 1, 6, "", ("10.0.0.5", 0))]
        assert is_safe_public_url("https://internal.local/") is False

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_rfc1918_allowed_with_override(self, mock_gai):
        mock_gai.return_value = [(2, 1, 6, "", ("192.168.8.10", 0))]
        assert is_safe_public_url("https://nas.lan/hook", allow_private=True) is True

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_docker_bridge_allowed_with_override(self, mock_gai):
        mock_gai.return_value = [(2, 1, 6, "", ("172.17.0.2", 0))]
        assert is_safe_public_url("http://receiver:8080/hook", allow_private=True) is True

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_ipv6_ula_allowed_with_override(self, mock_gai):
        mock_gai.return_value = [(10, 1, 6, "", ("fd00::1", 0, 0, 0))]
        assert is_safe_public_url("https://ula.lan/", allow_private=True) is True

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_cloud_metadata_still_rejected_with_override(self, mock_gai):
        """169.254.169.254 is is_private=True — must stay blocked as link-local."""
        mock_gai.return_value = [(2, 1, 6, "", ("169.254.169.254", 0))]
        assert is_safe_public_url("https://metadata.internal/", allow_private=True) is False

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_loopback_still_rejected_with_override(self, mock_gai):
        mock_gai.return_value = [(2, 1, 6, "", ("127.0.0.1", 0))]
        assert is_safe_public_url("https://localhost/", allow_private=True) is False

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_ipv6_loopback_still_rejected_with_override(self, mock_gai):
        mock_gai.return_value = [(10, 1, 6, "", ("::1", 0, 0, 0))]
        assert is_safe_public_url("https://ipv6-local/", allow_private=True) is False

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_multicast_still_rejected_with_override(self, mock_gai):
        mock_gai.return_value = [(2, 1, 6, "", ("224.0.0.1", 0))]
        assert is_safe_public_url("https://mcast.example/", allow_private=True) is False

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_unparseable_ip_still_rejected_with_override(self, mock_gai):
        mock_gai.return_value = [(10, 1, 6, "", ("fe80::1%eth0", 0, 0, 0))]
        assert is_safe_public_url("https://scoped.ipv6/", allow_private=True) is False

    def test_non_http_scheme_still_rejected_with_override(self):
        assert is_safe_public_url("file:///etc/passwd", allow_private=True) is False

    @patch("app._ssrf_guard.socket.getaddrinfo")
    def test_mixed_records_reject_if_any_blocked(self, mock_gai):
        """Public A + loopback AAAA: still rejected even with the override."""
        mock_gai.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 0)),
            (10, 1, 6, "", ("::1", 0, 0, 0)),
        ]
        assert is_safe_public_url("https://mixed.example/", allow_private=True) is False
