# -*- coding: utf-8 -*-
"""Admin JSON API routes (configs, paths, settings, stats, logs)."""

from flask import Blueprint, request, jsonify, session

from services.config_service import (
    add_configs, delete_config, bulk_delete_configs,
    set_config_enabled_status, reorder_configs, renumber_configs
)
from services.path_service import (
    add_path, add_secondary_path as svc_add_secondary_path,
    set_path_enabled, delete_path,
    generate_random_path, get_all_paths, get_primary_path
)
from services.statistics_service import (
    get_stats, get_chart_data, get_usage_stats, get_logs, clear_logs
)
from services.user_service import (
    get_all_users, add_user, update_user, delete_user,
    pause_user, resume_user, reset_user, set_user_enabled,
)
from database import get_setting, set_setting
from utils.misc import get_base_url

admin_api_bp = Blueprint('admin_api', __name__)


def _require_login():
    """Return an error response if user is not logged in, else None."""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'غیرمجاز'}), 401
    return None


def _get_json_safe():
    """Safely get JSON body; returns {} if not JSON or unparseable."""
    return request.get_json(silent=True) or {}


# ─── Config endpoints ────────────────────────────────────────────

@admin_api_bp.route('/adminpanel/add', methods=['POST'])
def add_config():
    err = _require_login()
    if err:
        return err

    config_text = request.form.get('config_text', '').strip()
    if not config_text:
        return jsonify({'success': False, 'message': 'متن کانفیگ نمی‌تواند خالی باشد'})

    added, duplicates, message = add_configs(config_text)
    return jsonify({
        'success': added > 0,
        'message': message,
        'added': added,
        'duplicates': duplicates
    })


@admin_api_bp.route('/adminpanel/delete/<int:config_id>', methods=['POST'])
def delete_config_route(config_id):
    err = _require_login()
    if err:
        return err
    success, message = delete_config(config_id)
    return jsonify({'success': success, 'message': message})


@admin_api_bp.route('/adminpanel/bulk_delete', methods=['POST'])
def bulk_delete():
    err = _require_login()
    if err:
        return err
    data = _get_json_safe()
    ids = data.get('ids', [])
    success, message = bulk_delete_configs(ids)
    return jsonify({'success': success, 'message': message})


# Frontend calls /adminpanel/config/set_enabled/<id>
@admin_api_bp.route('/adminpanel/config/set_enabled/<int:config_id>', methods=['POST'])
def set_enabled(config_id):
    err = _require_login()
    if err:
        return err
    data = _get_json_safe()
    enabled = data.get('enabled', True)
    success, message = set_config_enabled_status(config_id, enabled)
    return jsonify({'success': success, 'message': message})


@admin_api_bp.route('/adminpanel/reorder', methods=['POST'])
def reorder():
    err = _require_login()
    if err:
        return err
    data = _get_json_safe()
    order_list = data.get('order', [])
    success, message = reorder_configs(order_list)
    return jsonify({'success': success, 'message': message})


@admin_api_bp.route('/adminpanel/renumber', methods=['POST'])
def renumber():
    err = _require_login()
    if err:
        return err
    renumber_configs()
    return jsonify({'success': True, 'message': 'شماره‌گذاری مجدد با موفقیت انجام شد'})


# ─── Settings endpoints ──────────────────────────────────────────

# Frontend calls /adminpanel/set_format with form data: format=<value>
@admin_api_bp.route('/adminpanel/set_format', methods=['POST'])
def set_output_format():
    err = _require_login()
    if err:
        return err
    fmt = request.form.get('format') or _get_json_safe().get('format', 'base64')
    if fmt not in ('base64', 'plain'):
        return jsonify({'success': False, 'message': 'فرمت نامعتبر'})
    set_setting('output_format', fmt)
    return jsonify({'success': True, 'message': f'فرمت خروجی به {fmt} تغییر کرد'})


# Frontend calls /adminpanel/set_sort_order with form data: sort_order=<value>
@admin_api_bp.route('/adminpanel/set_sort_order', methods=['POST'])
def set_sort_order():
    err = _require_login()
    if err:
        return err
    order = request.form.get('sort_order') or _get_json_safe().get('sort_order') or _get_json_safe().get('order', 'asc')
    if order not in ('asc', 'desc'):
        return jsonify({'success': False, 'message': 'ترتیب نامعتبر'})
    set_setting('config_sort_order', order)
    return jsonify({'success': True, 'message': f'ترتیب نمایش به {order} تغییر کرد'})


# ─── Path endpoints ──────────────────────────────────────────────

# Frontend calls /adminpanel/paths to list all paths
@admin_api_bp.route('/adminpanel/paths')
def list_paths():
    err = _require_login()
    if err:
        return err
    paths = get_all_paths()
    return jsonify(paths)


@admin_api_bp.route('/adminpanel/paths/set_primary', methods=['POST'])
def set_primary_path():
    err = _require_login()
    if err:
        return err
    new_path = request.form.get('path', '').strip() or _get_json_safe().get('path', '').strip()
    success, message, _ = add_path(new_path)
    return jsonify({'success': success, 'message': message})


# Frontend sends FormData with path=<value> to change the primary subscription path
@admin_api_bp.route('/adminpanel/paths/add', methods=['POST'])
def add_path_route():
    err = _require_login()
    if err:
        return err

    # Accept both form data and JSON
    new_path = request.form.get('path', '').strip()
    if not new_path:
        data = _get_json_safe()
        new_path = data.get('path', '').strip()

    success, message, _ = add_path(new_path)

    result = {'success': success, 'message': message}
    if success:
        result['current_path'] = new_path
        base_url = get_base_url(request)
        result['current_url'] = f"{base_url}sub/{new_path}"

    return jsonify(result)


@admin_api_bp.route('/adminpanel/paths/set_enabled/<int:path_id>', methods=['POST'])
def set_path_enabled_route(path_id):
    err = _require_login()
    if err:
        return err
    data = _get_json_safe()
    enabled = data.get('enabled', True)
    success, message = set_path_enabled(path_id, enabled)
    return jsonify({'success': success, 'message': message})


@admin_api_bp.route('/adminpanel/paths/delete/<int:path_id>', methods=['POST'])
def delete_path_route(path_id):
    err = _require_login()
    if err:
        return err
    success, message = delete_path(path_id)
    return jsonify({'success': success, 'message': message})


# Frontend calls GET /adminpanel/paths/generate_random
@admin_api_bp.route('/adminpanel/paths/generate_random', methods=['GET', 'POST'])
def generate_random_path_route():
    err = _require_login()
    if err:
        return err
    random_path = generate_random_path()
    return jsonify({'success': True, 'path': random_path})


# ─── Stats & Charts ──────────────────────────────────────────────

@admin_api_bp.route('/adminpanel/stats')
def stats():
    err = _require_login()
    if err:
        return err
    return jsonify(get_stats())


# Frontend calls /adminpanel/usage_stats?range=<value>
@admin_api_bp.route('/adminpanel/usage_stats')
def usage_stats():
    err = _require_login()
    if err:
        return err
    range_val = request.args.get('range', '24h')
    return jsonify(get_usage_stats(range_val))


@admin_api_bp.route('/adminpanel/chart_data')
def chart_data():
    err = _require_login()
    if err:
        return err
    daily_range = request.args.get('daily_range', '30d')
    client_range = request.args.get('client_range', '30d')
    data = get_chart_data(daily_range, client_range)
    return jsonify(data)


# ─── Logs ─────────────────────────────────────────────────────────

@admin_api_bp.route('/adminpanel/logs')
def logs():
    err = _require_login()
    if err:
        return err
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    search = request.args.get('search', '')
    status_filter = request.args.get('status', '')

    logs_list, total, total_pages = get_logs(page, per_page, search, status_filter)

    return jsonify(logs_list)


# Frontend calls /adminpanel/clear_logs
@admin_api_bp.route('/adminpanel/clear_logs', methods=['POST'])
def clear_logs_route():
    err = _require_login()
    if err:
        return err
    success, message = clear_logs()
    return jsonify({'success': success, 'message': message})


# ─── Automation Sources endpoints ────────────────────────────

@admin_api_bp.route('/adminpanel/auto_sources/add', methods=['POST'])
def add_auto_source():
    import sqlite3
    from database import get_db
    err = _require_login()
    if err:
        return err
    
    name = request.form.get('name', '').strip()
    url = request.form.get('url', '').strip()
    try:
        priority = int(request.form.get('priority', '100'))
    except ValueError:
        priority = 100
        
    if not name or not url:
        return jsonify({'success': False, 'message': 'نام و آدرس منبع الزامی است'})
        
    db = get_db()
    try:
        db.execute(
            'INSERT INTO auto_sources (name, url, priority, is_enabled) VALUES (?, ?, ?, 1)',
            (name, url, priority)
        )
        db.commit()
        return jsonify({'success': True, 'message': 'منبع خودکار با موفقیت اضافه شد'})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'message': 'منبعی با این آدرس قبلاً ثبت شده است'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'خطا در ذخیره‌سازی: {e}'})
    finally:
        db.close()


@admin_api_bp.route('/adminpanel/auto_sources/delete/<int:source_id>', methods=['POST'])
def delete_auto_source(source_id):
    from database import get_db
    err = _require_login()
    if err:
        return err
    db = get_db()
    try:
        db.execute('DELETE FROM auto_sources WHERE id = ?', (source_id,))
        db.commit()
        return jsonify({'success': True, 'message': 'منبع خودکار با موفقیت حذف شد'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'خطا در حذف منبع: {e}'})
    finally:
        db.close()


@admin_api_bp.route('/adminpanel/auto_sources/toggle/<int:source_id>', methods=['POST'])
def toggle_auto_source(source_id):
    from database import get_db
    err = _require_login()
    if err:
        return err
    data = _get_json_safe()
    enabled = 1 if data.get('enabled', True) else 0
    db = get_db()
    try:
        db.execute('UPDATE auto_sources SET is_enabled = ? WHERE id = ?', (enabled, source_id))
        db.commit()
        return jsonify({'success': True, 'message': 'وضعیت منبع خودکار با موفقیت تغییر کرد'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'خطا در تغییر وضعیت منبع: {e}'})
    finally:
        db.close()


@admin_api_bp.route('/adminpanel/auto_sources/priority/<int:source_id>', methods=['POST'])
def update_auto_source_priority(source_id):
    from database import get_db
    err = _require_login()
    if err:
        return err
    data = _get_json_safe()
    try:
        priority = int(data.get('priority', 100))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'اولویت نامعتبر است'})
        
    db = get_db()
    try:
        db.execute('UPDATE auto_sources SET priority = ? WHERE id = ?', (priority, source_id))
        db.commit()
        return jsonify({'success': True, 'message': 'اولویت منبع با موفقیت به‌روزرسانی شد'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'خطا در بروزرسانی اولویت: {e}'})
    finally:
        db.close()


# ─── Automation Settings endpoint ────────────────────────────

@admin_api_bp.route('/adminpanel/settings/automation', methods=['POST'])
def save_automation_settings():
    from database import get_db
    err = _require_login()
    if err:
        return err
        
    data = request.form if request.form else _get_json_safe()
    
    db = get_db()
    try:
        for key in ['scan_interval', 'health_check_interval', 'max_active_configs', 'max_new_configs_per_scan', 'failure_threshold', 'cleanup_policy']:
            if key in data:
                val = str(data[key]).strip()
                db.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, val))
        # early_stop_enabled is a checkbox; an unchecked box is omitted from the
        # form entirely, so only touch it on a real settings-form submit and
        # treat absence there as "off".
        if any(k in data for k in ['scan_interval', 'max_active_configs', 'early_stop_enabled']):
            raw = str(data.get('early_stop_enabled', '')).strip().lower()
            es_val = '1' if raw in ('1', 'true', 'on', 'yes') else '0'
            db.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', ('early_stop_enabled', es_val))
        db.commit()
        return jsonify({'success': True, 'message': 'تنظیمات اتوماسیون با موفقیت ذخیره شد'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'خطا در ذخیره تنظیمات: {e}'})
    finally:
        db.close()


# ─── Automation Manual Trigger endpoint ────────────────────────

@admin_api_bp.route('/adminpanel/automation/trigger', methods=['POST'])
def trigger_automation():
    err = _require_login()
    if err:
        return err
        
    mode = request.form.get('mode', '').strip() or _get_json_safe().get('mode', '').strip()
    if mode not in ('discovery', 'health_check'):
        return jsonify({'success': False, 'message': 'حالت اسکن نامعتبر است'})
        
    from services.automation_service import AutomationService, is_scan_active
    import threading

    if is_scan_active():
        return jsonify({'success': False, 'message': 'یک اسکن دیگر در حال حاضر در پس‌زمینه در حال اجرا است'})
        
    threading.Thread(
        target=AutomationService.run_scan,
        args=(mode,),
        daemon=True
    ).start()
    
    return jsonify({'success': True, 'message': f'اسکن با موفقیت در پس‌زمینه آغاز شد'})

@admin_api_bp.route('/adminpanel/automation/cancel', methods=['POST'])
def cancel_automation():
    err = _require_login()
    if err:
        return err
        
    from services.automation_service import AutomationService, is_scan_active

    if not is_scan_active():
        return jsonify({'success': False, 'message': 'هیچ اسکن فعالی برای لغو کردن وجود ندارد'})
        
    AutomationService.cancel_scan()
    return jsonify({'success': True, 'message': 'درخواست لغو اسکن با موفقیت ارسال شد'})


# ─── User management endpoints ───────────────────────────────────

def _user_link(user):
    """Attach the full subscription URL to a user dict for the frontend."""
    if user:
        user['sub_url'] = f"{get_base_url(request)}sub/{user['path']}"
    return user


@admin_api_bp.route('/adminpanel/api/users', methods=['GET'])
def list_users():
    err = _require_login()
    if err:
        return err
    users = [_user_link(u) for u in get_all_users()]
    return jsonify(users)


@admin_api_bp.route('/adminpanel/api/users', methods=['POST'])
def create_user():
    err = _require_login()
    if err:
        return err
    data = request.form if request.form else _get_json_safe()
    name = (data.get('name') or '').strip()
    duration_days = data.get('duration_days', 30)
    custom_path = (data.get('path') or '').strip() or None
    note = (data.get('note') or '').strip() or None
    max_devices = data.get('max_devices', 1)

    success, message, user = add_user(
        name, duration_days=duration_days, custom_path=custom_path,
        note=note, max_devices=max_devices
    )
    result = {'success': success, 'message': message}
    if success:
        result['user'] = _user_link(user)
    return jsonify(result)


@admin_api_bp.route('/adminpanel/api/users/<int:user_id>', methods=['PUT', 'POST'])
def edit_user(user_id):
    err = _require_login()
    if err:
        return err
    data = request.form if request.form else _get_json_safe()

    # Only pass through keys that were actually provided, so omitted fields
    # keep their current value instead of being cleared.
    kwargs = {}
    if 'name' in data:
        kwargs['name'] = (data.get('name') or '').strip()
    if 'duration_days' in data:
        kwargs['duration_days'] = data.get('duration_days')
    if 'path' in data:
        kwargs['custom_path'] = (data.get('path') or '').strip()
    if 'note' in data:
        kwargs['note'] = (data.get('note') or '').strip()
    if 'max_devices' in data:
        kwargs['max_devices'] = data.get('max_devices')

    success, message = update_user(user_id, **kwargs)
    return jsonify({'success': success, 'message': message})


@admin_api_bp.route('/adminpanel/api/users/<int:user_id>', methods=['DELETE'])
@admin_api_bp.route('/adminpanel/api/users/<int:user_id>/delete', methods=['POST'])
def remove_user(user_id):
    err = _require_login()
    if err:
        return err
    success, message = delete_user(user_id)
    return jsonify({'success': success, 'message': message})


@admin_api_bp.route('/adminpanel/api/users/<int:user_id>/toggle', methods=['POST'])
def toggle_user(user_id):
    err = _require_login()
    if err:
        return err
    data = _get_json_safe()
    enabled = data.get('enabled', True)
    success, message = set_user_enabled(user_id, enabled)
    return jsonify({'success': success, 'message': message})


@admin_api_bp.route('/adminpanel/api/users/<int:user_id>/pause', methods=['POST'])
def pause_user_route(user_id):
    err = _require_login()
    if err:
        return err
    success, message = pause_user(user_id)
    return jsonify({'success': success, 'message': message})


@admin_api_bp.route('/adminpanel/api/users/<int:user_id>/resume', methods=['POST'])
def resume_user_route(user_id):
    err = _require_login()
    if err:
        return err
    success, message = resume_user(user_id)
    return jsonify({'success': success, 'message': message})


@admin_api_bp.route('/adminpanel/api/users/<int:user_id>/reset', methods=['POST'])
def reset_user_route(user_id):
    err = _require_login()
    if err:
        return err
    success, message = reset_user(user_id)
    return jsonify({'success': success, 'message': message})