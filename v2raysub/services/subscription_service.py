# -*- coding: utf-8 -*-
"""Core subscription content generation logic."""

import base64
from urllib.parse import quote

from database import get_setting
from services.config_service import (
    get_all_configs, get_subscription_remark, format_config_remark
)
from services.user_service import get_dummy_status_texts

# Message shown as the config name inside the client when a subscription is
# expired/paused. Kept here so both the route and tests reference one source.
EXPIRED_MESSAGE = '⚠️ اشتراک شما به پایان رسیده است ⚠️'
# Shown when a user hits their device cap and a new device is turned away.
DEVICE_LIMIT_MESSAGE = '⚠️ سقف تعداد دستگاه پر شده است ⚠️'
# Plain-text placeholder for link-preview crawlers/bots — deliberately generic
# (no config, no mention of VPN/subscription) since messengers may surface this
# exact text as the shared link's preview snippet to a real person.
BOT_PLACEHOLDER_MESSAGE = 'Content not available'


def _encode(content):
    """Apply the configured output format (base64 or plain) to raw content."""
    if get_setting('output_format', 'base64') == 'base64':
        return base64.b64encode(content.encode('utf-8')).decode('utf-8')
    return content


def generate_subscription_content(user=None):
    """Generate the subscription file content (base64 or plain).

    When ``user`` is given, two dummy configs are prepended whose names show
    the user's device usage and remaining days — informational only, they
    carry no working proxy.
    """
    configs = get_all_configs()

    config_lines = []
    if user is not None:
        device_text, days_text = get_dummy_status_texts(user)
        config_lines.append(f'trojan://status@127.0.0.1:443#{quote(device_text)}')
        config_lines.append(f'trojan://status@127.0.0.1:443#{quote(days_text)}')

    for i, config in enumerate(configs, 1):
        remark = get_subscription_remark(i, config['config_text'], config['config_type'])
        formatted_config = format_config_remark(config['config_text'], config['config_type'], remark)
        config_lines.append(formatted_config)

    return _encode('\n'.join(config_lines))


def generate_dummy_content(message=EXPIRED_MESSAGE):
    """Build a single invalid config whose name carries a message to the client.

    Used when a user's subscription is expired or paused: the real config list
    is replaced by this one dummy so the client shows the notice as the config
    name. Respects the configured output_format (base64/plain), same as the
    normal subscription output.
    """
    dummy = f'trojan://expired-user@127.0.0.1:443#{quote(message)}'
    return _encode(dummy)