# -*- coding: utf-8 -*-
"""VMess/VLESS/Trojan/Shadowsocks/Hysteria2 decoders, flag extractors, and identity calculators."""

import base64
import json
import re
from urllib.parse import urlparse, urlunparse, quote, unquote

def safe_b64decode(b64_str):
    """رمزگشایی ایمن base64 با تصحیح پدینگ و نویسه‌های URL-safe"""
    try:
        b64_clean = b64_str.strip().replace('-', '+').replace('_', '/')
        missing_padding = len(b64_clean) % 4
        if missing_padding:
            b64_clean += '=' * (4 - missing_padding)
        return base64.b64decode(b64_clean.encode('utf-8')).decode('utf-8')
    except Exception as e:
        print(f"Error in safe_b64decode: {e}")
        return None

# اسکیماهای کانفیگ شناخته‌شده در ابتدای هر خط سابسکریپشن.
CONFIG_SCHEME_RE = re.compile(
    r'^(?:vmess|vless|trojan|ss|ssr|hysteria2?|hy2|tuic)://',
    re.IGNORECASE,
)

def count_configs_in_text(raw_text):
    """تعداد کانفیگ‌های داخل بدنه‌ی خام یک سابسکریپشن را می‌شمارد.

    بدنه ممکن است کل‌بدنه base64 باشد یا متن خام خط‌به‌خط. اگر متن مستقیم شامل
    هیچ URI کانفیگی نبود، یک‌بار کل بدنه را base64-decode می‌کنیم. سپس خطوطی که با
    یک اسکیمای کانفیگ شناخته‌شده شروع می‌شوند شمرده می‌شوند. (بدون تست سلامت —
    فقط شمارش خام «چند کانفیگ در این لینک هست».)
    """
    if not raw_text:
        return 0
    text = raw_text.strip()
    # اگر بدنه base64 است و هیچ URI مستقیمی ندارد، یک‌بار decode کن.
    if not CONFIG_SCHEME_RE.search(text):
        decoded = safe_b64decode(text)
        if decoded and CONFIG_SCHEME_RE.search(decoded):
            text = decoded
    return sum(1 for line in text.splitlines() if CONFIG_SCHEME_RE.match(line.strip()))

def extract_flags(text):
    """استخراج تمامی پرچم‌های کشورها و مناطق موجود در متن"""
    # الگوی پرچم‌های دو حرفی (مثل 🇩🇪) و پرچم‌های منطقه‌ای پیچیده (مثل انگلستان 🏴󠁧󠁢󠁥󠁮󠁧󠁿)
    flag_pattern = '[\U0001F1E6-\U0001F1FF]{2}|\U0001F3F4[\U000E0061-\U000E007F]+'
    flags = re.findall(flag_pattern, text)
    return "".join(flags) if flags else ""

def country_code_to_flag(code):
    """تبدیل کد دوحرفی کشور (ISO 3166-1 alpha-2 مثل «DE») به ایموجی پرچم (🇩🇪).

    هر حرف A–Z به نویسه‌ی Regional Indicator متناظرش نگاشت می‌شود. ورودی نامعتبر
    (خالی، غیر دوحرفی، یا شامل نویسه‌ی غیر A–Z) رشته‌ی خالی برمی‌گرداند.
    """
    if not code:
        return ""
    code = code.strip().upper()
    if len(code) != 2 or not all('A' <= ch <= 'Z' for ch in code):
        return ""
    return "".join(chr(0x1F1E6 + (ord(ch) - ord('A'))) for ch in code)

def clean_remark(remark):
    """حذف شماره‌گذاری‌های قبلی از ابتدای نام"""
    # حذف الگوهایی مثل "1. ", "10 - ", "5 "
    return re.sub(r'^\d+[\.\-\)\s]+\s*', '', remark).strip()

def detect_config_type(config_text):
    """تشخیص نوع کانفیگ"""
    config_lower = config_text.lower()
    if config_lower.startswith('vmess://'):
        return 'vmess'
    elif config_lower.startswith('vless://'):
        return 'vless'
    elif config_lower.startswith('trojan://'):
        return 'trojan'
    elif config_lower.startswith('ss://'):
        return 'shadowsocks'
    elif config_lower.startswith('hysteria2://') or config_lower.startswith('hy2://'):
        return 'hysteria2'
    else:
        return None

def extract_remark(config_text, config_type):
    """استخراج نام (remark) از کانفیگ"""
    try:
        if config_type == 'vmess':
            b64 = config_text[8:]
            decoded = safe_b64decode(b64)
            if decoded:
                data = json.loads(decoded)
                return data.get('ps', 'Config')
            return "Config"
            
        elif config_type in ['vless', 'trojan', 'hysteria2']:
            parsed = urlparse(config_text)
            return unquote(parsed.fragment)
            
        elif config_type == 'shadowsocks':
             if '#' in config_text:
                 remark = config_text.split('#', 1)[1]
                 return unquote(remark)
             return "Config"
             
    except Exception:
        return "Config"
    
    return "Config"

def get_config_identity(config_text, config_type):
    """
    دریافت هویت منحصر به فرد کانفیگ (نام تمیز شده + جزئیات فنی)
    برای تشخیص تکراری بودن استفاده می‌شود.
    """
    try:
        # استخراج نام و تمیز کردن آن
        raw_remark = extract_remark(config_text, config_type)
        clean_name = clean_remark(raw_remark)
        
        if config_type == 'vmess':
            if config_text.startswith('vmess://'):
                b64 = config_text[8:]
                decoded = safe_b64decode(b64)
                if decoded:
                    data = json.loads(decoded)
                    details = data.copy()
                    if 'ps' in details:
                         del details['ps']
                    # مقایسه بر اساس JSON مرتب شده فیلدهای فنی
                    return (clean_name, json.dumps(details, sort_keys=True))
            
        elif config_type in ['vless', 'trojan', 'shadowsocks', 'hysteria2']:
            # برای پروتکل‌های مبتنی بر URL، بخش قبل از # نشان‌دهنده جزئیات فنی است
            details = config_text.split('#', 1)[0] if '#' in config_text else config_text
            
            # نرمال‌سازی پروتکل hysteria2 (برخی کلاینت‌ها از hy2 استفاده می‌کنند)
            if details.startswith('hy2://'):
                details = 'hysteria2://' + details[6:]
                
            return (clean_name, details)
            
    except Exception:
        pass
    
    # در صورت بروز خطا، کل متن را به عنوان هویت در نظر می‌گیریم
    return (None, config_text)

def format_config_remark(config_text, config_type, new_remark):
    """
    تغییر نام (remark) کانفیگ به یک نام جدید (تابع محض - بدون تغییر دیتابیس)
    """
    try:
        if config_type == 'vmess':
            if config_text.startswith('vmess://'):
                b64 = config_text[8:]
                decoded = safe_b64decode(b64)
                if decoded:
                    try:
                        data = json.loads(decoded)
                        data['ps'] = new_remark
                        # Re-encode base64
                        new_b64 = base64.b64encode(json.dumps(data, ensure_ascii=False).encode('utf-8')).decode('utf-8')
                        return f"vmess://{new_b64}"
                    except:
                        pass
                return config_text

        elif config_type in ['vless', 'trojan', 'hysteria2']:
            try:
                parsed = urlparse(config_text)
                new_parsed = parsed._replace(fragment=quote(new_remark))
                return urlunparse(new_parsed)
            except:
                return config_text

        elif config_type == 'shadowsocks':
             try:
                 if '#' in config_text:
                     main_part, _ = config_text.split('#', 1)
                 else:
                     main_part = config_text
                 return f"{main_part}#{quote(new_remark)}"
             except:
                 return config_text
                 
    except Exception as e:
        print(f"Error in format_config_remark: {e}")
        return config_text
        
    return config_text

def get_subscription_remark(index, config_text, config_type, country_code=None):
    """
    تولید نام کانفیگ برای سابسکریپشن.

    اولویت انتخاب پرچم:
      ۱) کشوری که موتور اسکن (GeoIP) تشخیص داده — «تشخیص خودمان» و معتبرترین منبع.
      ۲) اگر GeoIP نداشتیم، پرچمی که خودِ نام اصلی کانفیگ داشته باشد حفظ می‌شود.
      ۳) در غیر این صورت فقط شماره‌ی ردیف.
    """
    try:
        geo_flag = country_code_to_flag(country_code)
        if geo_flag:
            return f"{geo_flag} {index}"
        raw_remark = extract_remark(config_text, config_type)
        flags_str = extract_flags(raw_remark)
        if flags_str:
            return f"{flags_str} {index}"
    except Exception as e:
        print(f"Error in get_subscription_remark: {e}")

    return f"{index}"
