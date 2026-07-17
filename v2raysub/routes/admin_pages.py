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
from utils.misc import get_base_url

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

@admin_pages_bp.route('/adminpanel/logout')
def logout():
    session.clear()
    return redirect(url_for('admin_pages.login'))

@admin_pages_bp.route('/adminpanel')
def admin():
    if not session.get('logged_in'):
        return redirect(url_for('admin_pages.login'))

    configs = get_all_configs_for_admin()
    primary_path = get_primary_path()
    other_paths = get_other_paths()
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

    db.close()

    return render_template(
        'admin.html',
        configs=configs,
        total_configs=len(configs),
        primary_path=primary_path,
        other_paths=other_paths,
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
        early_stop_enabled=early_stop_enabled
    )