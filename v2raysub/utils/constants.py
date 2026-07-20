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
# User-subscription outcomes (see services/user_service.py, routes/client.py)
STATUS_EXPIRED = 'EXPIRED'
STATUS_USER_DISABLED = 'USER_DISABLED'
STATUS_USER_PAUSED = 'USER_PAUSED'
STATUS_DEVICE_LIMIT = 'DEVICE_LIMIT'  # device cap reached — served the dummy config

# Device fingerprint network granularity: collapse each IP to its network block
# so one device on a churning mobile IP stays a single device (see utils/misc.py).
DEVICE_NETWORK_PREFIX_V4 = 24
DEVICE_NETWORK_PREFIX_V6 = 48

# الگوی اعتبارسنجی آدرس‌های سابسکریپشن (مسیرهای سراسری)
PATH_REGEX = r'^[A-Za-z0-9]{3,32}$'

# الگوی اعتبارسنجی مسیر کاربران (زیرخط و خط‌تیره مجاز، حداقل ۸ کاراکتر)
USER_PATH_REGEX = r'^[A-Za-z0-9_-]{8,64}$'

# وضعیت‌های کاربر که ادمین تعیین می‌کند (EXPIRED محاسبه‌ای است و ذخیره نمی‌شود)
USER_STATUS_ACTIVE = 'ACTIVE'
USER_STATUS_PAUSED = 'PAUSED'
USER_STATUS_DISABLED = 'DISABLED'
USER_STATUS_EXPIRED = 'EXPIRED'  # مشتق در زمان خواندن، نه یک مقدار ذخیره‌شده

# طول مسیر تصادفی تولید شده
RANDOM_PATH_LENGTH = 16

# طول مسیر تصادفی تولیدشده برای کاربران
USER_PATH_LENGTH = 12

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