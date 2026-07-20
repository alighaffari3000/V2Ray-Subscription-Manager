# -*- coding: utf-8 -*-
"""Core subscription content generation logic."""

import base64
from urllib.parse import quote

from database import get_setting
from services.config_service import (
    get_all_configs, get_subscription_remark, format_config_remark
)

# Message shown as the config name inside the client when a subscription is
# expired/paused. Kept here so both the route and tests reference one source.
EXPIRED_MESSAGE = '⚠️ اشتراک شما به پایان رسیده است ⚠️'
# Shown when a user hits their device cap and a new device is turned away.
DEVICE_LIMIT_MESSAGE = '⚠️ سقف تعداد دستگاه پر شده است ⚠️'


def _encode(content):
    """Apply the configured output format (base64 or plain) to raw content."""
    if get_setting('output_format', 'base64') == 'base64':
        return base64.b64encode(content.encode('utf-8')).decode('utf-8')
    return content


def generate_subscription_content():
    """Generate the subscription file content (base64 or plain)."""
    configs = get_all_configs()

    config_lines = []
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