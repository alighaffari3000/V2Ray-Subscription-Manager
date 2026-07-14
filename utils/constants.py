# -*- coding: utf-8 -*-
"""Centralized reusable constants."""

# Status codes used in subscription_logs and API responses
STATUS_SUCCESS = 'SUCCESS'
STATUS_NOT_FOUND = 'NOT_FOUND'
STATUS_DISABLED_PATH = 'DISABLED_PATH'
STATUS_RATE_LIMIT = 'RATE_LIMIT'
STATUS_ERROR = 'ERROR'

# الگوی اعتبارسنجی آدرس‌های سابسکریپشن
PATH_REGEX = r'^[A-Za-z0-9]{3,32}$'

# طول مسیر تصادفی تولید شده
RANDOM_PATH_LENGTH = 16

# Known client identifiers
CLIENTS = ['v2rayNG', 'Nekobox', 'Clash', 'Shadowrocket', 'Sing-box', 'Other']

# Default settings
DEFAULT_OUTPUT_FORMAT = 'base64'
DEFAULT_SORT_ORDER = 'asc'

# Valid choices
VALID_OUTPUT_FORMATS = {'base64', 'plain'}
VALID_SORT_ORDERS = {'asc', 'desc'}
DAYS_MAP = {'7d': 7, '30d': 30, '90d': 90}

# Default subscription path
DEFAULT_PATH = 'freeconfigs'