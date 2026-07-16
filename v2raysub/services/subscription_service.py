# -*- coding: utf-8 -*-
"""Core subscription content generation logic."""

import base64
from database import get_setting
from services.config_service import (
    get_all_configs, get_subscription_remark, format_config_remark
)


def generate_subscription_content():
    """Generate the subscription file content (base64 or plain)."""
    configs = get_all_configs()
    output_format = get_setting('output_format', 'base64')

    config_lines = []
    for i, config in enumerate(configs, 1):
        remark = get_subscription_remark(i, config['config_text'], config['config_type'])
        formatted_config = format_config_remark(config['config_text'], config['config_type'], remark)
        config_lines.append(formatted_config)

    content = '\n'.join(config_lines)

    if output_format == 'base64':
        content_bytes = content.encode('utf-8')
        encoded_content = base64.b64encode(content_bytes).decode('utf-8')
        return encoded_content
    else:
        return content