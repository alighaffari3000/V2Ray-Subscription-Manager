# -*- coding: utf-8 -*-
"""User-Agent client classification."""


def parse_user_agent(ua_string):
    """Classify a User-Agent string into a known client name."""
    if not ua_string:
        return 'Other'
    ua_lower = ua_string.lower()
    if 'v2rayng' in ua_lower:
        return 'v2rayNG'
    elif 'nekobox' in ua_lower:
        return 'Nekobox'
    elif 'clash' in ua_lower:
        return 'Clash'
    elif 'shadowrocket' in ua_lower:
        return 'Shadowrocket'
    elif 'sing-box' in ua_lower:
        return 'Sing-box'
    else:
        return 'Other'