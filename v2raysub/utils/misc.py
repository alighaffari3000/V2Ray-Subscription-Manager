# -*- coding: utf-8 -*-
"""Miscellaneous pure helpers for sizes and base URL resolution."""

import os
import hashlib
import ipaddress
import utils.constants as constants

def get_file_size_formatted(filepath):
    """حجم فایل به صورت خوانا"""
    try:
        size_bytes = os.path.getsize(filepath)
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
    except:
        return "0 B"

def get_base_url(request):
    """دریافت آدرس پایه سابسکریپشن.

    ProxyFix (در app_factory) پروتکل واقعی را از X-Forwarded-Proto تشخیص می‌دهد؛
    بنابراین اگر SSL نصب نشده باشد، لینک http می‌ماند و لینک https خراب ساخته نمی‌شود.
    """
    return request.host_url


def get_public_base_url(request):
    """Canonical customer-facing base URL for subscription links.

    Prefers the ``public_base_url`` setting when an admin has set one, otherwise
    falls back to the requesting host. The override matters because a
    subscription link is handed to customers but is built while serving whoever
    *asked* for it: an external client (e.g. a sales bot) calling the machine API
    over ``http://127.0.0.1:5000`` would otherwise mint links pointing at
    localhost — broken for every customer, and broken silently.

    Empty setting (the default, and every existing install) = unchanged behaviour.
    """
    from database import get_setting  # local import: avoids an import cycle at module load
    configured = (get_setting('public_base_url', '') or '').strip()
    if not configured:
        return get_base_url(request)
    return configured if configured.endswith('/') else configured + '/'


def network_key(ip):
    """Collapse an IP to its network block for device fingerprinting.

    IPv4 -> /24 (e.g. "5.201.130.0/24"), IPv6 -> /48. A device on a churning
    mobile IP within the same block stays a single device. Returns "unknown"
    for a missing/unparseable IP so the caller can fail open.
    """
    if not ip:
        return 'unknown'
    raw = ip.strip()
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return 'unknown'
    prefix = (constants.DEVICE_NETWORK_PREFIX_V4 if addr.version == 4
              else constants.DEVICE_NETWORK_PREFIX_V6)
    net = ipaddress.ip_network(f'{raw}/{prefix}', strict=False)
    return str(net)


def device_fingerprint(ip):
    """Device identity = the IP network block only (an "IP limit").

    Returns (fingerprint, network) where network is the human-readable block.
    User-Agent is intentionally excluded from the identity: one person on one
    connection who tries several client apps sends several UAs but stays a
    single device. The UA is still recorded per-device for display, it just
    doesn't create a new slot. Everyone behind the same /24 counts as one
    device (accepted trade-off — see DEVICE_LIMIT_ROADMAP.md).
    """
    net = network_key(ip)
    fp = hashlib.sha256(net.encode('utf-8')).hexdigest()[:16]
    return fp, net
