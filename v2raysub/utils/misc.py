# -*- coding: utf-8 -*-
"""Miscellaneous pure helpers for sizes and base URL resolution."""

import os

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
