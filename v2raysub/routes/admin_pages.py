# -*- coding: utf-8 -*-
"""Admin HTML page routes (login, dashboard)."""

from hmac import compare_digest

from flask import Blueprint, render_template, request, redirect, url_for, session
from werkzeug.security import check_password_hash

from config import Config
from extensions import limiter
from database import get_setting
from services.path_service import get_primary_path, get_other_paths
from services.config_service import get_all_configs_for_admin
from services.user_service import get_all_users
from utils.misc import get_base_url
from utils.csrf import validate_csrf

admin_pages_bp = Blueprint('admin_pages', __name__)


def _verify_password(stored, password):
    """Verify the admin password.

    Supports both a Werkzeug hash (produced by install.sh) and a plaintext
    value in .env; plaintext is compared in constant time.
    """
    if stored.startswith(('pbkdf2:', 'scrypt:', 'argon2')):
        return check_password_hash(stored, password)
    return compare_digest(stored.encode('utf-8'), password.encode('utf-8'))


@admin_pages_bp.route('/adminpanel/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute', methods=['POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('admin_pages.admin'))

    if request.method == 'POST':
        # CSRF: the login form carries a hidden token issued on the GET render.
        from flask import current_app
        if current_app.config.get('CSRF_ENABLED', True):
            sent = request.form.get('csrf_token', '')
            expected = session.get('csrf_token', '')
            if not expected or not compare_digest(str(sent), str(expected)):
                return render_template('login.html', error='نشست منقضی شده است. صفحه را تازه‌سازی کرده و دوباره تلاش کنید.')

        username = request.form.get('username', '')
        password = request.form.get('password', '')

        if not Config.ADMIN_USERNAME or not Config.ADMIN_PASSWORD:
            return render_template('login.html', error='اطلاعات ادمین تنظیم نشده است')

        if username == Config.ADMIN_USERNAME and _verify_password(Config.ADMIN_PASSWORD, password):
            session['logged_in'] = True
            session.permanent = True
            return redirect(url_for('admin_pages.admin'))
        return render_template('login.html', error='نام کاربری یا رمز عبور اشتباه است')

    return render_template('login.html')

@admin_pages_bp.route('/adminpanel/logout', methods=['POST'])
def logout():
    # POST-only + CSRF so a cross-site GET can't force a logout.
    err = validate_csrf()
    if err:
        return err
    session.clear()
    return redirect(url_for('admin_pages.login'))

@admin_pages_bp.route('/adminpanel')
def admin():
    if not session.get('logged_in'):
        return redirect(url_for('admin_pages.login'))

    configs = get_all_configs_for_admin()
    primary_path = get_primary_path()
    other_paths = get_other_paths()
    users = get_all_users()
    output_format = get_setting('output_format', 'base64')
    sort_dir = get_setting('config_sort_order', 'asc').lower()
    base_url = get_base_url(request)

    # Fetch automation settings and data
    from database import get_db
    db = get_db()
    
    auto_sources = db.execute('SELECT * FROM auto_sources ORDER BY priority DESC, created_at ASC').fetchall()
    scan_history = db.execute('SELECT * FROM scan_history ORDER BY started_at DESC LIMIT 5').fetchall()
    
    manual_count = db.execute("SELECT COUNT(*) as count FROM configs WHERE mode = 'manual' AND status = 'active'").fetchone()['count']
    auto_count = db.execute("SELECT COUNT(*) as count FROM configs WHERE mode = 'auto' AND status = 'active'").fetchone()['count']
    healthy_count = db.execute("SELECT COUNT(*) as count FROM configs WHERE health_status = 'healthy' AND status = 'active' AND is_enabled = 1").fetchone()['count']
    unhealthy_count = db.execute("SELECT COUNT(*) as count FROM configs WHERE health_status = 'unhealthy' AND status = 'active'").fetchone()['count']
    
    scan_interval = get_setting('scan_interval', '300')
    health_check_interval = get_setting('health_check_interval', '600')
    max_active_configs = get_setting('max_active_configs', '100')
    max_new_configs_per_scan = get_setting('max_new_configs_per_scan', '10')
    failure_threshold = get_setting('failure_threshold', '2')
    cleanup_policy = get_setting('cleanup_policy', 'disable')
    early_stop_enabled = get_setting('early_stop_enabled', '1')
    scan_timeout = get_setting('scan_timeout', '1200')
    device_window_days = get_setting('device_window_days', '7')
    device_grace_hours = get_setting('device_grace_hours', '0')

    # Backup Settings
    backup_scheduled_enabled = get_setting('backup_scheduled_enabled', '0')
    backup_interval = get_setting('backup_interval', 'daily')
    backup_scheduled_type = get_setting('backup_scheduled_type', 'standard')
    backup_retention_max = get_setting('backup_retention_max', '30')
    backup_telegram_enabled = get_setting('backup_telegram_enabled', '0')
    backup_telegram_bot_token = get_setting('backup_telegram_bot_token', '')
    backup_telegram_chat_id = get_setting('backup_telegram_chat_id', '')
    backup_telegram_api_server = get_setting('backup_telegram_api_server', 'https://api.telegram.org')

    db.close()

    return render_template(
        'admin.html',
        configs=configs,
        total_configs=len(configs),
        primary_path=primary_path,
        other_paths=other_paths,
        users=users,
        total_users=len(users),
        output_format=output_format,
        config_sort_order=sort_dir,
        base_url=base_url,
        auto_sources=auto_sources,
        scan_history=scan_history,
        manual_count=manual_count,
        auto_count=auto_count,
        healthy_count=healthy_count,
        unhealthy_count=unhealthy_count,
        scan_interval=scan_interval,
        health_check_interval=health_check_interval,
        max_active_configs=max_active_configs,
        max_new_configs_per_scan=max_new_configs_per_scan,
        failure_threshold=failure_threshold,
        cleanup_policy=cleanup_policy,
        early_stop_enabled=early_stop_enabled,
        scan_timeout=scan_timeout,
        device_window_days=device_window_days,
        device_grace_hours=device_grace_hours,
        backup_scheduled_enabled=backup_scheduled_enabled,
        backup_interval=backup_interval,
        backup_scheduled_type=backup_scheduled_type,
        backup_retention_max=backup_retention_max,
        backup_telegram_enabled=backup_telegram_enabled,
        backup_telegram_bot_token=backup_telegram_bot_token,
        backup_telegram_chat_id=backup_telegram_chat_id,
        backup_telegram_api_server=backup_telegram_api_server
    )