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
