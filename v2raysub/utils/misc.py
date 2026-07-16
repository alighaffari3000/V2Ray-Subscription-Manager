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
    """دریافت آدرس پایه سابسکریپشن با در نظر گرفتن پروکسی و پروتکل HTTPS"""
    base_url = request.host_url
    # اگر پشت پروکسی HTTPS هستیم یا آدرس هاست لوکال نیست، از https استفاده می‌کنیم
    if request.headers.get('X-Forwarded-Proto') == 'https' or (not request.host.startswith('127.0.0.1') and not request.host.startswith('localhost')):
        base_url = base_url.replace('http://', 'https://', 1)
    return base_url
