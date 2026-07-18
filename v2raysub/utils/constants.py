# -*- coding: utf-8 -*-
"""Centralized reusable constants."""

import os

# مسیر پایه پروژه (مطلق — تا اجرای برنامه از هر دایرکتوری، دیتابیس اشتباه ساخته نشود)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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

# Known client identifiers. Keep in sync with utils/user_agent.parse_user_agent,
# the single place that classifies a raw User-Agent into one of these names.
CLIENTS = [
    'v2rayNG', 'v2rayN', 'Hiddify', 'NapsternetV', 'Streisand', 'FlClash',
    'Karing', 'Nekobox', 'Clash', 'Shadowrocket', 'Sing-box', 'Browser/Bot',
    'Other',
]

# Default settings
DEFAULT_OUTPUT_FORMAT = 'base64'
DEFAULT_SORT_ORDER = 'asc'

# Valid choices
VALID_OUTPUT_FORMATS = {'base64', 'plain'}
VALID_SORT_ORDERS = {'asc', 'desc'}
DAYS_MAP = {'7d': 7, '30d': 30, '90d': 90}

# Default subscription path
DEFAULT_PATH = 'freeconfigs'

# Database file (absolute path)
DATABASE = os.path.join(BASE_DIR, 'database.db')

# Cross-process coordination files (shared between gunicorn workers)
SCHEDULER_LOCK_FILE = os.path.join(BASE_DIR, 'scheduler.lock')
SCAN_LOCK_FILE = os.path.join(BASE_DIR, 'scan.lock')
SCAN_CANCEL_FLAG = os.path.join(BASE_DIR, 'scan_cancel.flag')