# -*- coding: utf-8 -*-
"""Admin HTML page routes (login, dashboard)."""

from flask import Blueprint, render_template, request, redirect, url_for, session
from werkzeug.security import check_password_hash

from config import Config
from database import get_setting
from services.path_service import get_primary_path, get_other_paths
from services.config_service import get_all_configs_for_admin
from utils.misc import get_base_url

admin_pages_bp = Blueprint('admin_pages', __name__)

@admin_pages_bp.route('/adminpanel/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('admin_pages.admin'))

    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')

        if not Config.ADMIN_USERNAME or not Config.ADMIN_PASSWORD:
            return render_template('login.html', error='اطلاعات ادمین تنظیم نشده است')

        if username == Config.ADMIN_USERNAME and check_password_hash(Config.ADMIN_PASSWORD, password):
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

    return render_template(
        'admin.html',
        configs=configs,
        total_configs=len(configs),
        primary_path=primary_path,
        other_paths=other_paths,
        output_format=output_format,
        config_sort_order=sort_dir,
        base_url=base_url
    )