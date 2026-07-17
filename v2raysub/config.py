# -*- coding: utf-8 -*-
"""Global application configuration (.env loading)."""

import os
from datetime import timedelta
from dotenv import load_dotenv

# بارگذاری متغیرهای محیطی از فایل .env
load_dotenv()

class Config:
    # کلید امنیتی سشن‌ها — باید ثابت و مشترک بین همه workerها باشد.
    # اگر تصادفی تولید شود، هر worker گونیکورن کلید متفاوتی می‌سازد و سشن‌ها
    # به صورت تصادفی نامعتبر می‌شوند؛ پس در نبودش با پیام واضح متوقف می‌شویم.
    SECRET_KEY = os.getenv('SECRET_KEY')
    if not SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY تنظیم نشده است. یک فایل .env بسازید و مقدار SECRET_KEY را در آن قرار دهید.\n"
            "برای تولید کلید: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    # طول عمر سشن ورود
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)

    # فقط وقتی HTTPS فعال است ۱ شود (install.sh بعد از نصب SSL تنظیمش می‌کند)
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', '0') == '1'

    # اطلاعات کاربری ادمین — بدون مقدار پیش‌فرض برای رمز عبور؛
    # اگر تنظیم نشده باشد، ورود با پیام خطا مسدود می‌شود (routes/admin_pages.py)
    ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '')
