# -*- coding: utf-8 -*-
"""Global application configuration (.env loading)."""

import os
import secrets
from datetime import timedelta
from dotenv import load_dotenv

# بارگذاری متغیرهای محیطی از فایل .env
load_dotenv()

class Config:
    # کلید امنیتی سشن‌ها
    SECRET_KEY = os.getenv('SECRET_KEY')
    if not SECRET_KEY:
        SECRET_KEY = secrets.token_hex(32)

    # طول عمر سشن ورود
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)

    # اطلاعات کاربری ادمین
    ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin')