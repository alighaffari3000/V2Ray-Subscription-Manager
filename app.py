print(">>> REAL APP.PY LOADED <<<")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import check_password_hash, generate_password_hash
import sqlite3
import base64
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import secrets
import json
import re
from urllib.parse import urlparse, urlunparse, quote, unquote

# بارگذاری متغیرهای محیطی
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(32))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)

# تنظیم rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# تنظیمات پایگاه داده
DATABASE = 'database.db'

def get_db():
    """اتصال به پایگاه داده"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def get_base_url():
    """دریافت آدرس پایه سابسکریپشن با در نظر گرفتن پروکسی و پروتکل HTTPS"""
    base_url = request.host_url
    # اگر پشت پروکسی HTTPS هستیم یا آدرس هاست لوکال نیست، از https استفاده می‌کنیم
    if request.headers.get('X-Forwarded-Proto') == 'https' or (not request.host.startswith('127.0.0.1') and not request.host.startswith('localhost')):
        base_url = base_url.replace('http://', 'https://', 1)
    return base_url

def init_db():
    """ایجاد جداول پایگاه داده"""
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                config_text TEXT NOT NULL,
                config_type TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active'
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        
        db.execute('''
            CREATE TABLE IF NOT EXISTS subscription_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT NOT NULL,
                user_agent TEXT,
                accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        db.execute('''
            CREATE TABLE IF NOT EXISTS subscription_paths (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                is_primary INTEGER DEFAULT 0,
                is_enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # بررسی وجود ستون sort_order
        try:
            db.execute('SELECT sort_order FROM configs LIMIT 1')
        except sqlite3.OperationalError:
            db.execute('ALTER TABLE configs ADD COLUMN sort_order INTEGER DEFAULT 0')

        # بررسی وجود ستون is_enabled در configs
        try:
            db.execute('SELECT is_enabled FROM configs LIMIT 1')
        except sqlite3.OperationalError:
            db.execute('ALTER TABLE configs ADD COLUMN is_enabled INTEGER DEFAULT 1')

        # بررسی وجود ستون status در subscription_logs
        try:
            db.execute('SELECT status FROM subscription_logs LIMIT 1')
        except sqlite3.OperationalError:
            db.execute("ALTER TABLE subscription_logs ADD COLUMN status TEXT NOT NULL DEFAULT 'SUCCESS'")

        # بررسی وجود ستون request_path در subscription_logs
        try:
            db.execute('SELECT request_path FROM subscription_logs LIMIT 1')
        except sqlite3.OperationalError:
            db.execute("ALTER TABLE subscription_logs ADD COLUMN request_path TEXT")

        # بررسی وجود مسیر پیش‌فرض سابسکریپشن و ایجاد آن در صورت نیاز
        paths_count = db.execute('SELECT COUNT(*) as count FROM subscription_paths').fetchone()['count']
        if paths_count == 0:
            db.execute("INSERT INTO subscription_paths (path, is_primary, is_enabled) VALUES ('freeconfigs', 1, 1)")
            
        # تنظیم فرمت پیش‌فرض
        db.execute('''
            INSERT OR IGNORE INTO settings (key, value) VALUES ('output_format', 'base64')
        ''')
        db.commit()
        db.close()
        
    # اطمینان از شماره‌گذاری صحیح در شروع برنامه
    try:
        renumber_configs()
    except Exception as e:
        print(f"Error in initial renumbering: {e}")

def get_setting(key, default=''):
    """دریافت تنظیمات"""
    db = get_db()
    result = db.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    db.close()
    return result['value'] if result else default

def set_setting(key, value):
    """ذخیره تنظیمات"""
    db = get_db()
    db.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    db.commit()
    db.close()

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
        return 'unknown'

def parse_configs(text):
    """جدا کردن کانفیگ‌های چندتایی"""
    lines = text.strip().split('\n')
    configs = []
    for line in lines:
        line = line.strip()
        if line and (line.startswith('vmess://') or line.startswith('vless://') or 
                     line.startswith('trojan://') or line.startswith('ss://') or
                     line.startswith('hysteria2://') or line.startswith('hy2://')):
            config_type = detect_config_type(line)
            configs.append({'text': line, 'type': config_type})
    return configs

def get_all_configs():
    """دریافت تمام کانفیگ‌های فعال و فعال‌سازی شده برای سابسکریپشن"""
    db = get_db()
    try:
        configs = db.execute(
            'SELECT * FROM configs WHERE status = "active" AND is_enabled = 1 ORDER BY sort_order ASC, created_at ASC'
        ).fetchall()
    except Exception as e:
        print(f"Error in get_all_configs: {e}")
        # Fallback if is_enabled or sort_order does not exist
        try:
            configs = db.execute(
                'SELECT * FROM configs WHERE status = "active" ORDER BY created_at ASC'
            ).fetchall()
        except:
            configs = []
    db.close()
    return configs
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

def extract_flags(text):
    """استخراج تمامی پرچم‌های کشورها و مناطق موجود در متن"""
    # الگوی پرچم‌های دو حرفی (مثل 🇩🇪) و پرچم‌های منطقه‌ای پیچیده (مثل انگلستان 🏴󠁧󠁢󠁥󠁮󠁧󠁿)
    flag_pattern = '[\U0001F1E6-\U0001F1FF]{2}|\U0001F3F4[\U000E0061-\U000E007F]+'
    flags = re.findall(flag_pattern, text)
    return "".join(flags) if flags else ""

def clean_remark(remark):
    """حذف شماره‌گذاری‌های قبلی از ابتدای نام"""
    # حذف الگوهایی مثل "1. ", "10 - ", "5 "
    return re.sub(r'^\d+[\.\-\)\s]+\s*', '', remark).strip()

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

def get_subscription_remark(index, config_text, config_type):
    """
    تولید نام کانفیگ برای سابسکریپشن
    اگر در نام اصلی کانفیگ پرچم کشور وجود داشته باشد، آن را حفظ می‌کند.
    """
    try:
        raw_remark = extract_remark(config_text, config_type)
        flags_str = extract_flags(raw_remark)
        if flags_str:
            return f"{flags_str} {index}"
    except Exception as e:
        print(f"Error in get_subscription_remark: {e}")
        
    return f"{index}"

def renumber_configs():
    """شماره‌گذاری مجدد فیلد sort_order برای کانفیگ‌های فعال"""
    db = get_db()
    try:
        configs = db.execute(
            'SELECT id FROM configs WHERE status = "active" ORDER BY sort_order ASC, created_at ASC'
        ).fetchall()
        for i, config in enumerate(configs, 1):
            db.execute(
                'UPDATE configs SET sort_order = ? WHERE id = ?',
                (i, config['id'])
            )
        db.commit()
    except Exception as e:
        print(f"Error in renumber_configs: {e}")
    finally:
        db.close()

def generate_subscription_content():
    """تولید محتوای فایل سابسکریپشن"""
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
# روت اصلی - ریدایرکت به پنل
@app.route('/')
def index():
    return redirect(url_for('admin_panel'))

# صفحه لاگین
@app.route('/adminpanel/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin_username = os.getenv('ADMIN_USERNAME')
        admin_password = os.getenv('ADMIN_PASSWORD')
        
        if username == admin_username and password == admin_password:
            session.permanent = True
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('admin_panel'))
        else:
            return render_template('login.html', error='نام کاربری یا رمز عبور اشتباه است')
    
    return render_template('login.html')

# خروج از حساب
@app.route('/adminpanel/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# پنل مدیریتی
@app.route('/adminpanel')
def admin_panel():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    db = get_db()
    configs_rows = db.execute(
        'SELECT * FROM configs WHERE status = "active" ORDER BY sort_order ASC, created_at ASC'
    ).fetchall()
    
    # دریافت مسیرهای سابسکریپشن
    primary_row = db.execute('SELECT path FROM subscription_paths WHERE is_primary = 1').fetchone()
    primary_path = primary_row['path'] if primary_row else 'freeconfigs'
    
    other_paths = db.execute('SELECT * FROM subscription_paths WHERE is_primary = 0 ORDER BY created_at DESC').fetchall()
    db.close()
    
    # پردازش کانفیگ‌ها برای نمایش با نام تمیز
    configs = []
    for row in configs_rows:
        c = dict(row)
        c['remark'] = clean_remark(extract_remark(c['config_text'], c['config_type']))
        configs.append(c)
        
    output_format = get_setting('output_format', 'base64')
    total_configs = len(configs)
    
    # آدرس پایه
    base_url = get_base_url()
    
    return render_template('admin.html', 
                         configs=configs, 
                         total_configs=total_configs,
                         output_format=output_format,
                         primary_path=primary_path,
                         other_paths=other_paths,
                         base_url=base_url)

# افزودن کانفیگ
@app.route('/adminpanel/add', methods=['POST'])
def add_config():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'غیرمجاز'}), 401
    
    config_text = request.form.get('config_text', '').strip()
    
    if not config_text:
        return jsonify({'success': False, 'message': 'متن کانفیگ خالی است'})
    
    # جدا کردن کانفیگ‌های چندتایی
    configs = parse_configs(config_text)
    
    if not configs:
        return jsonify({'success': False, 'message': 'هیچ کانفیگ معتبری پیدا نشد'})
    
    db = get_db()
    
    # دریافت هویت کانفیگ‌های موجود برای بررسی تکراری بودن
    existing_rows = db.execute('SELECT config_text, config_type FROM configs WHERE status="active"').fetchall()
    existing_identities = set()
    for row in existing_rows:
        identity = get_config_identity(row['config_text'], row['config_type'])
        existing_identities.add(identity)
    
    # تعیین شماره شروع (بزرگترین sort_order + 1)
    max_sort_row = db.execute('SELECT MAX(sort_order) as max_val FROM configs WHERE status="active"').fetchone()
    max_sort = max_sort_row['max_val'] if max_sort_row else 0
    start_order = (max_sort if max_sort is not None else 0) + 1
    
    added_count = 0
    duplicates_count = 0
    
    for config in configs:
        identity = get_config_identity(config['text'], config['type'])
        
        if identity in existing_identities:
            duplicates_count += 1
            continue
            
        # ذخیره کانفیگ بدون تغییر متن اصلی
        current_order = start_order + added_count
        db.execute(
            'INSERT INTO configs (config_text, config_type, sort_order, is_enabled) VALUES (?, ?, ?, 1)',
            (config['text'], config['type'], current_order)
        )
        
        # اضافه کردن هویت جدید به مجموعه برای جلوگیری از تکرار در یک پچ
        existing_identities.add(identity)
        added_count += 1
    
    db.commit()
    db.close()
    
    # اگر هیچ کانفیگی اضافه نشد و همگی تکراری بودند
    if added_count == 0 and duplicates_count > 0:
        return jsonify({
            'success': False, 
            'message': 'این کانفیگ تکراری است و قبلاً اضافه شده است' if duplicates_count == 1 else f'تمام {duplicates_count} کانفیگ وارد شده تکراری هستند'
        })
    
    # اگر کلاً هیچ کانفیگی اضافه نشد (مثلاً همگی نامعتبر بودند که در بالا چک شده، اما محض احتیاط)
    if added_count == 0:
         return jsonify({'success': False, 'message': 'هیچ کانفیگ جدیدی اضافه نشد'})

    # اطمینان از ترتیب صحیح (و رفع باگ‌های احتمالی)
    renumber_configs()
    
    message = f'{added_count} کانفیگ با موفقیت اضافه شد'
    if duplicates_count > 0:
        message += f' ({duplicates_count} مورد تکراری نادیده گرفته شد)'
    
    return jsonify({
        'success': True, 
        'message': message,
        'count': added_count
    })

# فعال یا غیرفعال کردن یک کانفیگ
@app.route('/adminpanel/config/set_enabled/<int:config_id>', methods=['POST'])
def set_config_enabled(config_id):
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'غیرمجاز'}), 401
        
    data = request.json or {}
    enabled_val = 1 if data.get('enabled') else 0
    
    db = get_db()
    try:
        config_row = db.execute('SELECT * FROM configs WHERE id = ?', (config_id,)).fetchone()
        if not config_row:
            return jsonify({'success': False, 'message': 'کانفیگ پیدا نشد'})
            
        db.execute('UPDATE configs SET is_enabled = ? WHERE id = ?', (enabled_val, config_id))
        db.commit()
        
        # شماره‌گذاری مجدد برای ترتیب در سابسکریپشن
        renumber_configs()
        
        return jsonify({'success': True, 'message': 'وضعیت کانفیگ با موفقیت تغییر کرد.'})
    except Exception as e:
        print(f"Error setting config enabled status: {e}")
        return jsonify({'success': False, 'message': 'خطا در تغییر وضعیت کانفیگ'})
    finally:
        db.close()

# حذف کانفیگ
@app.route('/adminpanel/delete/<int:config_id>', methods=['POST'])
def delete_config(config_id):
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'غیرمجاز'}), 401
    
    db = get_db()
    db.execute('UPDATE configs SET status = "deleted" WHERE id = ?', (config_id,))
    db.commit()
    db.execute('UPDATE configs SET status = "deleted" WHERE id = ?', (config_id,))
    db.commit()
    db.close()
    
    # شماره‌گذاری مجدد برای پر کردن جای خالی
    renumber_configs()
    
    return jsonify({'success': True, 'message': 'کانفیگ با موفقیت حذف شد'})

# تغییر ترتیب کانفیگ‌ها
@app.route('/adminpanel/reorder', methods=['POST'])
def reorder_configs():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'غیرمجاز'}), 401
    
    try:
        order_list = request.json.get('order', [])
        if not order_list:
            return jsonify({'success': False, 'message': 'لیست ترتیب خالی است'})
            
        db = get_db()
        # آپدیت sort_order بر اساس لیست دریافتی
        for index, config_id in enumerate(order_list, 1):
            db.execute('UPDATE configs SET sort_order = ? WHERE id = ?', (index, config_id))
            
        db.commit()
        db.close()
        
        # بروزرسانی متن کانفیگ‌ها بر اساس ترتیب جدید
        renumber_configs()
        
        return jsonify({'success': True, 'message': 'ترتیب با موفقیت ذخیره شد'})
    except Exception as e:
        print(f"Error in reorder: {e}")
        return jsonify({'success': False, 'message': 'خطا در ذخیره ترتیب'})

# تغییر فرمت خروجی
@app.route('/adminpanel/set_format', methods=['POST'])
def set_format():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'غیرمجاز'}), 401
    
    output_format = request.form.get('format', 'base64')
    
    if output_format not in ['base64', 'plain']:
        return jsonify({'success': False, 'message': 'فرمت نامعتبر'})
    
    set_setting('output_format', output_format)
    
    return jsonify({'success': True, 'message': 'فرمت با موفقیت تغییر کرد'})

# لینک سابسکریپشن عمومی پویا
@app.route('/sub/<path:sub_path>')
def subscription(sub_path):
    user_agent = request.headers.get('User-Agent', '')
    if request.headers.get('X-Forwarded-For'):
        ip = request.headers.get('X-Forwarded-For').split(',')[0]
    else:
        ip = request.remote_addr

    db = get_db()
    path_row = db.execute('SELECT * FROM subscription_paths WHERE path = ?', (sub_path,)).fetchone()
    
    if not path_row:
        try:
            db.execute(
                "INSERT INTO subscription_logs (ip_address, user_agent, status, request_path) VALUES (?, ?, 'NOT_FOUND', ?)",
                (ip, user_agent, sub_path)
            )
            db.commit()
        except Exception as e:
            print(f"Error logging NOT_FOUND subscription access: {e}")
        db.close()
        return "Not Found", 404
        
    if not path_row['is_enabled']:
        try:
            db.execute(
                "INSERT INTO subscription_logs (ip_address, user_agent, status, request_path) VALUES (?, ?, 'DISABLED_PATH', ?)",
                (ip, user_agent, sub_path)
            )
            db.commit()
        except Exception as e:
            print(f"Error logging DISABLED_PATH subscription access: {e}")
        db.close()
        return "Not Found", 404

    try:
        db.execute(
            "INSERT INTO subscription_logs (ip_address, user_agent, status, request_path) VALUES (?, ?, 'SUCCESS', ?)",
            (ip, user_agent, sub_path)
        )
        db.commit()
    except Exception as e:
        print(f"Error logging SUCCESS subscription access: {e}")
    db.close()

    content = generate_subscription_content()
    output_format = get_setting('output_format', 'base64')
    
    response = Response(content, mimetype='text/plain; charset=utf-8')
    response.headers['Content-Disposition'] = 'inline; filename=subscription.txt'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Expires'] = '0'

    if output_format == 'base64':
        response.headers['Subscription-Userinfo'] = 'upload=0; download=0; total=0; expire=0'
        response.headers['Profile-Update-Interval'] = '24'
        
    return response

# هندلر محدودیت نرخ درخواست (Rate Limiting)
@app.errorhandler(429)
def ratelimit_handler(e):
    user_agent = request.headers.get('User-Agent', '')
    if request.headers.get('X-Forwarded-For'):
        ip = request.headers.get('X-Forwarded-For').split(',')[0]
    else:
        ip = request.remote_addr
    
    req_path = request.path.replace('/sub/', '', 1) if request.path.startswith('/sub/') else request.path
    
    try:
        db = get_db()
        db.execute(
            "INSERT INTO subscription_logs (ip_address, user_agent, status, request_path) VALUES (?, ?, 'RATE_LIMIT', ?)",
            (ip, user_agent, req_path)
        )
        db.commit()
        db.close()
    except Exception as ex:
        print(f"Error logging RATE_LIMIT subscription access: {ex}")
        
    return jsonify(error="Too Many Requests", message=str(e.description)), 429

# دریافت لیست مسیرهای سابسکریپشن
@app.route('/adminpanel/paths', methods=['GET'])
def get_paths():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'غیرمجاز'}), 401
    
    db = get_db()
    paths = db.execute('SELECT * FROM subscription_paths ORDER BY is_primary DESC, created_at DESC').fetchall()
    db.close()
    
    path_list = []
    for p in paths:
        path_dict = dict(p)
        path_dict['url'] = get_base_url() + 'sub/' + p['path']
        path_list.append(path_dict)
        
    return jsonify(path_list)

# تولید مسیر تصادفی و یکتا
@app.route('/adminpanel/paths/generate_random', methods=['GET'])
def generate_random_path_endpoint():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'غیرمجاز'}), 401
    
    import string
    db = get_db()
    
    # تلاش برای تولید مسیر تصادفی تا زمانی که یکتا باشد
    while True:
        length = 16
        chars = string.ascii_letters + string.digits
        random_path = ''.join(secrets.choice(chars) for _ in range(length))
        
        # بررسی یکتا بودن در دیتابیس
        existing = db.execute('SELECT 1 FROM subscription_paths WHERE path = ?', (random_path,)).fetchone()
        if not existing:
            break
            
    db.close()
    return jsonify({'success': True, 'path': random_path})

# افزودن یا تغییر مسیر اصلی سابسکریپشن
@app.route('/adminpanel/paths/add', methods=['POST'])
def add_path():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'غیرمجاز'}), 401
        
    path_val = request.form.get('path', '').strip()
    if not path_val:
        return jsonify({'success': False, 'message': 'مسیر نمی‌تواند خالی باشد'})
        
    # اعتبارسنجی الگو
    if not re.match(r'^[A-Za-z0-9]{3,32}$', path_val):
        return jsonify({'success': False, 'message': 'مسیر نامعتبر است. فقط حروف انگلیسی و اعداد بین ۳ تا ۳۲ کاراکتر مجاز هستند.'})
        
    db = get_db()
    
    try:
        # بررسی تکراری بودن
        existing = db.execute('SELECT * FROM subscription_paths WHERE path = ?', (path_val,)).fetchone()
        
        # غیرفعال کردن primary برای همه مسیرها
        db.execute('UPDATE subscription_paths SET is_primary = 0')
        
        if existing:
            # اگر وجود دارد، آن را به عنوان primary فعال می‌کنیم
            db.execute('UPDATE subscription_paths SET is_primary = 1, is_enabled = 1 WHERE path = ?', (path_val,))
        else:
            # ثبت به عنوان مسیر جدید primary
            db.execute('INSERT INTO subscription_paths (path, is_primary, is_enabled) VALUES (?, 1, 1)', (path_val,))
            
        db.commit()
        
        current_url = get_base_url() + 'sub/' + path_val
        return jsonify({
            'success': True, 
            'message': 'مسیر سابسکریپشن با موفقیت تغییر کرد.',
            'current_url': current_url,
            'current_path': path_val
        })
    except Exception as e:
        print(f"Error adding subscription path: {e}")
        return jsonify({'success': False, 'message': 'خطا در ذخیره مسیر در دیتابیس'})
    finally:
        db.close()

# فعال یا غیرفعال کردن یک مسیر
@app.route('/adminpanel/paths/set_enabled/<int:path_id>', methods=['POST'])
def set_path_enabled(path_id):
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'غیرمجاز'}), 401
        
    data = request.json or {}
    enabled_val = 1 if data.get('enabled') else 0
    
    db = get_db()
    try:
        path_row = db.execute('SELECT * FROM subscription_paths WHERE id = ?', (path_id,)).fetchone()
        if not path_row:
            return jsonify({'success': False, 'message': 'مسیر پیدا نشد'})
            
        if path_row['is_primary'] == 1 and enabled_val == 0:
            return jsonify({'success': False, 'message': 'مسیر اصلی (Primary) را نمی‌توان غیرفعال کرد.'})
            
        db.execute('UPDATE subscription_paths SET is_enabled = ? WHERE id = ?', (enabled_val, path_id))
        db.commit()
        return jsonify({'success': True, 'message': 'وضعیت مسیر با موفقیت تغییر کرد.'})
    except Exception as e:
        print(f"Error setting path enabled status: {e}")
        return jsonify({'success': False, 'message': 'خطا در تغییر وضعیت مسیر'})
    finally:
        db.close()

# حذف یک مسیر سابسکریپشن
@app.route('/adminpanel/paths/delete/<int:path_id>', methods=['POST'])
def delete_path(path_id):
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'غیرمجاز'}), 401
        
    db = get_db()
    try:
        path_row = db.execute('SELECT * FROM subscription_paths WHERE id = ?', (path_id,)).fetchone()
        if not path_row:
            return jsonify({'success': False, 'message': 'مسیر پیدا نشد'})
            
        if path_row['is_primary'] == 1:
            return jsonify({'success': False, 'message': 'مسیر اصلی (Primary) را نمی‌توان حذف کرد.'})
            
        db.execute('DELETE FROM subscription_paths WHERE id = ?', (path_id,))
        db.commit()
        return jsonify({'success': True, 'message': 'مسیر با موفقیت حذف شد.'})
    except Exception as e:
        print(f"Error deleting path: {e}")
        return jsonify({'success': False, 'message': 'خطا در حذف مسیر'})
    finally:
        db.close()

def get_file_size_formatted(path):
    try:
        size = os.path.getsize(path)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
    except:
        return "0 B"
    return "0 B"

def parse_user_agent(ua_string):
    if not ua_string:
        return 'Other'
    ua_lower = ua_string.lower()
    if 'v2rayng' in ua_lower:
        return 'v2rayNG'
    elif 'nekobox' in ua_lower:
        return 'Nekobox'
    elif 'clash' in ua_lower:
        return 'Clash'
    elif 'shadowrocket' in ua_lower:
        return 'Shadowrocket'
    elif 'sing-box' in ua_lower:
        return 'Sing-box'
    else:
        return 'Other'

# API برای دریافت آمار
@app.route('/adminpanel/stats')
def get_stats():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'غیرمجاز'}), 401
    
    db = get_db()
    
    # آمار کانفیگ‌ها
    total_configs = db.execute('SELECT COUNT(*) as count FROM configs WHERE status != "deleted"').fetchone()['count']
    active_configs = db.execute('SELECT COUNT(*) as count FROM configs WHERE status = "active" AND is_enabled = 1').fetchone()['count']
    disabled_configs = db.execute('SELECT COUNT(*) as count FROM configs WHERE status = "active" AND is_enabled = 0').fetchone()['count']
    
    # آمار پروتکل‌ها (فقط فعال و روشن‌ها)
    vmess = db.execute('SELECT COUNT(*) as count FROM configs WHERE status = "active" AND is_enabled = 1 AND config_type = "vmess"').fetchone()['count']
    vless = db.execute('SELECT COUNT(*) as count FROM configs WHERE status = "active" AND is_enabled = 1 AND config_type = "vless"').fetchone()['count']
    trojan = db.execute('SELECT COUNT(*) as count FROM configs WHERE status = "active" AND is_enabled = 1 AND config_type = "trojan"').fetchone()['count']
    hysteria2 = db.execute('SELECT COUNT(*) as count FROM configs WHERE status = "active" AND is_enabled = 1 AND config_type = "hysteria2"').fetchone()['count']
    
    # آمار دانلودهای امروز (با وضعیت SUCCESS)
    today_downloads = db.execute("SELECT COUNT(*) as count FROM subscription_logs WHERE status = 'SUCCESS' AND date(accessed_at) = date('now', 'localtime')").fetchone()['count']
    today_unique = db.execute("SELECT COUNT(DISTINCT ip_address) as count FROM subscription_logs WHERE status = 'SUCCESS' AND date(accessed_at) = date('now', 'localtime')").fetchone()['count']
    
    # حجم دیتابیس
    db_size = get_file_size_formatted(DATABASE)
    
    # کل لاگ‌های دانلود
    total_logs = db.execute('SELECT COUNT(*) as count FROM subscription_logs').fetchone()['count']
    
    # پر درخواست‌ترین مسیر سابسکریپشن
    most_requested_row = db.execute("SELECT request_path, COUNT(*) as count FROM subscription_logs WHERE status = 'SUCCESS' AND request_path IS NOT NULL AND request_path != '' GROUP BY request_path ORDER BY count DESC LIMIT 1").fetchone()
    most_requested_path = most_requested_row['request_path'] if most_requested_row else "ندارد"
    
    # آمار مسیرهای سابسکریپشن
    primary_row = db.execute('SELECT path FROM subscription_paths WHERE is_primary = 1').fetchone()
    primary_path = primary_row['path'] if primary_row else "نامشخص"
    
    additional_enabled = db.execute('SELECT COUNT(*) as count FROM subscription_paths WHERE is_primary = 0 AND is_enabled = 1').fetchone()['count']
    paths_disabled = db.execute('SELECT COUNT(*) as count FROM subscription_paths WHERE is_enabled = 0').fetchone()['count']
    
    # آمار کلاینت‌ها (بر اساس User-Agent)
    logs_ua = db.execute('SELECT user_agent FROM subscription_logs').fetchall()
    client_counts = {
        'v2rayNG': 0,
        'Nekobox': 0,
        'Clash': 0,
        'Shadowrocket': 0,
        'Sing-box': 0,
        'Other': 0
    }
    for log in logs_ua:
        client = parse_user_agent(log['user_agent'])
        client_counts[client] += 1
        
    db.close()
    
    return jsonify({
        'total': total_configs, # backward compatibility
        'total_configs': total_configs,
        'active_configs': active_configs,
        'disabled_configs': disabled_configs,
        'vmess': vmess,
        'vless': vless,
        'trojan': trojan,
        'hysteria2': hysteria2,
        'today_downloads': today_downloads,
        'today_unique': today_unique,
        'db_size': db_size,
        'total_logs': total_logs,
        'most_requested_path': most_requested_path,
        'primary_path': primary_path,
        'additional_enabled': additional_enabled,
        'paths_disabled': paths_disabled,
        'client_stats': client_counts
    })
# API آمار بازدید
@app.route('/adminpanel/usage_stats')
def get_usage_stats():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'غیرمجاز'}), 401
    
    time_range = request.args.get('range', '24h')
    db = get_db()
    
    # 1. آمار امروز
    today_unique = db.execute("SELECT COUNT(DISTINCT ip_address) as count FROM subscription_logs WHERE date(accessed_at) = date('now', 'localtime')").fetchone()['count']
    today_total = db.execute("SELECT COUNT(*) as count FROM subscription_logs WHERE date(accessed_at) = date('now', 'localtime')").fetchone()['count']
    
    # 2. داده‌های نمودار
    chart_data = [] # Total views
    unique_data = [] # Unique IPs
    labels = []
    
    if time_range == '24h':
        # 24 ساعت گذشته - گروه بندی بر اساس ساعت
        query = """
            SELECT strftime('%H:00', accessed_at, 'localtime') as hour, 
                   COUNT(*) as count,
                   COUNT(DISTINCT ip_address) as unique_count
            FROM subscription_logs 
            WHERE accessed_at >= datetime('now', '-1 day', 'localtime')
            GROUP BY hour
            ORDER BY accessed_at
        """
        rows = db.execute(query).fetchall()
        
        # پر کردن ساعت‌های خالی
        data_dict = {row['hour']: row['count'] for row in rows}
        unique_dict = {row['hour']: row['unique_count'] for row in rows}
        
        now = datetime.now()
        for i in range(24):
            time_point = (now - timedelta(hours=i)).strftime('%H:00')
            labels.insert(0, time_point)
            chart_data.insert(0, data_dict.get(time_point, 0))
            unique_data.insert(0, unique_dict.get(time_point, 0))
            
    elif time_range == '7d':
        # 7 روز گذشته - گروه بندی بر اساس روز
        query = """
            SELECT date(accessed_at, 'localtime') as day, 
                   COUNT(*) as count,
                   COUNT(DISTINCT ip_address) as unique_count
            FROM subscription_logs 
            WHERE accessed_at >= datetime('now', '-7 days', 'localtime')
            GROUP BY day
            ORDER BY day
        """
        rows = db.execute(query).fetchall()
        
        data_dict = {row['day']: row['count'] for row in rows}
        unique_dict = {row['day']: row['unique_count'] for row in rows}
        
        now = datetime.now()
        for i in range(7):
            day_point = (now - timedelta(days=i)).strftime('%Y-%m-%d')
            labels.insert(0, day_point)
            chart_data.insert(0, data_dict.get(day_point, 0))
            unique_data.insert(0, unique_dict.get(day_point, 0))
            
    elif time_range == '30d':
        # 30 روز گذشته
        query = """
            SELECT date(accessed_at, 'localtime') as day, 
                   COUNT(*) as count,
                   COUNT(DISTINCT ip_address) as unique_count
            FROM subscription_logs 
            WHERE accessed_at >= datetime('now', '-30 days', 'localtime')
            GROUP BY day
            ORDER BY day
        """
        rows = db.execute(query).fetchall()
        
        data_dict = {row['day']: row['count'] for row in rows}
        unique_dict = {row['day']: row['unique_count'] for row in rows}
        
        now = datetime.now()
        for i in range(30):
            day_point = (now - timedelta(days=i)).strftime('%Y-%m-%d')
            labels.insert(0, day_point)
            chart_data.insert(0, data_dict.get(day_point, 0))
            unique_data.insert(0, unique_dict.get(day_point, 0))
    
    db.close()
    
    return jsonify({
        'today_unique': today_unique,
        'today_total': today_total,
        'labels': labels,
        'data': chart_data,
        'unique_data': unique_data
    })

# حذف دسته جمعی
@app.route('/adminpanel/bulk_delete', methods=['POST'])
def bulk_delete():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'غیرمجاز'}), 401
    
    try:
        data = request.json
        ids = data.get('ids', [])
        
        if not ids:
            return jsonify({'success': False, 'message': 'هیچ موردی انتخاب نشده است'})
            
        db = get_db()
        # استفاده از Placeholders برای امنیت
        placeholders = ','.join(['?'] * len(ids))
        query = f'UPDATE configs SET status = "deleted" WHERE id IN ({placeholders})'
        db.execute(query, ids)
        db.commit()
        db.close()
        
        # شماره‌گذاری مجدد
        renumber_configs()
        
        return jsonify({'success': True, 'message': f'{len(ids)} کانفیگ با موفقیت حذف شدند'})
    except Exception as e:
        print(f"Error in bulk delete: {e}")
        return jsonify({'success': False, 'message': 'خطا در حذف موارد'})

# دریافت لاگ‌ها
@app.route('/adminpanel/logs')
def get_logs():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'غیرمجاز'}), 401
    
    db = get_db()
    
    # اطمینان از وجود جدول
    db.execute('''
        CREATE TABLE IF NOT EXISTS subscription_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address TEXT NOT NULL,
            user_agent TEXT,
            accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    logs = db.execute('SELECT * FROM subscription_logs ORDER BY accessed_at DESC LIMIT 100').fetchall()
    db.close()
    
    return jsonify([dict(log) for log in logs])

# پاک کردن لاگ‌ها
@app.route('/adminpanel/clear_logs', methods=['POST'])
def clear_logs():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'غیرمجاز'}), 401
        
    db = get_db()
    db.execute('DELETE FROM subscription_logs')
    db.commit()
    db.close()
    
    return jsonify({'success': True, 'message': 'تاریخچه بازدید پاک شد'})

if __name__ == '__main__':
    init_db()
    # برای production از gunicorn استفاده کنید
    #app.run(host='127.0.0.1', port=5000, debug=False)
    app.run(host='127.0.0.1', port=5000, debug=True)

