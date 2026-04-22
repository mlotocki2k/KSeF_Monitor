"""SSRF guard — validates outbound URLs for public network only.

Shared by webhook_notifier, CIRFMF PDF generator, and any module that
accepts an admin-configured URL that will be dereferenced with requests.
"""

import ipaddress
import logging
import socket
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}


def is_safe_public_url(url: Optional[str]) -> bool:
    """Return True only if URL is http(s) and resolves to public routable IP(s).

    Rejects empty/None input, non-http(s) schemes, missing hostname,
    and any URL whose A/AAAA records resolve to private, loopback,
    link-local, multicast, reserved, or unspecified addresses.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in _ALLOWED_SCHEMES:
        logger.warning("URL rejected: unsupported scheme %r", parsed.scheme)
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        logger.warning("URL rejected: cannot resolve hostname")
        return False

    for _family, _type, _proto, _canon, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            logger.warning("URL rejected: unparseable IP %r", ip_str[:64])
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            logger.warning("URL rejected: resolves to non-public IP")
            return False
    return True
