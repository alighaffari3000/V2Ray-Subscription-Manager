# -*- coding: utf-8 -*-
"""Network safety helpers — SSRF guard for admin-supplied source URLs.

Scan source URLs are fetched server-side by the engine, so an unvalidated URL
like ``http://169.254.169.254/…`` or ``http://127.0.0.1:…`` could reach internal
services. This rejects non-HTTP(S) schemes and any URL that targets a private,
loopback, link-local, or otherwise non-public address.
"""

import ipaddress
import socket
from urllib.parse import urlparse


def _blocked_ip(ip_str) -> bool:
    """True if the IP is not a normal public address (private/loopback/etc.)."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable → treat as unsafe
    # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) before classifying.
    if addr.version == 6 and getattr(addr, 'ipv4_mapped', None):
        addr = addr.ipv4_mapped
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_multicast or addr.is_reserved or addr.is_unspecified
    )


def validate_source_url(url, resolve_dns=True):
    """Validate an admin-supplied scan-source URL.

    Returns (ok, message). Scheme and literal-IP checks always run. Hostname DNS
    resolution (which blocks names pointing at internal IPs) runs only when
    ``resolve_dns`` is True — callers disable it under testing to stay offline.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, 'آدرس نامعتبر است'

    if parsed.scheme not in ('http', 'https'):
        return False, 'فقط آدرس‌های http و https مجاز هستند'

    host = parsed.hostname
    if not host:
        return False, 'آدرس فاقد نام میزبان معتبر است'

    # Literal IP host → classify directly (always, even offline). Also catch
    # integer-encoded IPv4 (e.g. http://2130706433/ == 127.0.0.1), a common
    # SSRF-filter bypass that getaddrinfo would otherwise accept.
    literal = None
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        if host.isdigit():
            try:
                literal = ipaddress.ip_address(int(host))
            except ValueError:
                literal = None

    if literal is not None:
        if _blocked_ip(str(literal)):
            return False, 'آدرس به یک شبکه داخلی/خصوصی اشاره می‌کند و مجاز نیست'
        return True, ''

    if not resolve_dns:
        return True, ''

    # Hostname → resolve and block if ANY resolved address is non-public.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False, 'نام میزبان قابل‌حل نیست (DNS)'
    for info in infos:
        if _blocked_ip(info[4][0]):
            return False, 'آدرس به یک شبکه داخلی/خصوصی اشاره می‌کند و مجاز نیست'
    return True, ''
