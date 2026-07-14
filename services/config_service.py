# -*- coding: utf-8 -*-
"""Config CRUD, toggles, duplicate check, renumbering."""

from database import get_db, get_setting
from utils.config_parser import (
    detect_config_type,
    clean_remark,
    extract_remark,
    get_config_identity,
    format_config_remark,
    get_subscription_remark
)

def parse_configs(text):
    """Split multi-line text into individual config dicts."""
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

def renumber_configs():
    """Re-number sort_order for all active configs sequentially."""
    db = get_db()
    try:
        configs = db.execute(
            'SELECT id FROM configs WHERE status = "active" ORDER BY sort_order ASC, created_at ASC'
        ).fetchall()
        for i, cfg in enumerate(configs, 1):
            db.execute('UPDATE configs SET sort_order = ? WHERE id = ?', (i, cfg['id']))
        db.commit()
    except Exception as e:
        print(f"Error in renumber_configs: {e}")
    finally:
        db.close()

def get_all_configs():
    """Get all active and enabled configs for the subscription output."""
    db = get_db()
    sort_dir = get_setting('config_sort_order', 'asc').lower()
    order_sql = 'DESC' if sort_dir == 'desc' else 'ASC'
    try:
        configs = db.execute(
            f'SELECT * FROM configs WHERE status = "active" AND is_enabled = 1 '
            f'ORDER BY sort_order {order_sql}, created_at {order_sql}'
        ).fetchall()
    except Exception as e:
        print(f"Error in get_all_configs: {e}")
        try:
            configs = db.execute(
                f'SELECT * FROM configs WHERE status = "active" ORDER BY created_at {order_sql}'
            ).fetchall()
        except Exception:
            configs = []
    db.close()
    return configs

def get_all_configs_for_admin():
    """Get all active configs (including disabled) for admin panel display."""
    db = get_db()
    sort_dir = get_setting('config_sort_order', 'asc').lower()
    order_sql = 'DESC' if sort_dir == 'desc' else 'ASC'
    configs_rows = db.execute(
        f'SELECT * FROM configs WHERE status = "active" '
        f'ORDER BY sort_order {order_sql}, created_at {order_sql}'
    ).fetchall()
    db.close()

    configs = []
    for row in configs_rows:
        c = dict(row)
        c['remark'] = clean_remark(extract_remark(c['config_text'], c['config_type']))
        configs.append(c)
    return configs

def add_configs(config_text):
    """Parse, deduplicate, and insert configs. Returns (added_count, duplicates_count, message)."""
    parsed = parse_configs(config_text)
    if not parsed:
        return 0, 0, 'هیچ کانفیگ معتبری پیدا نشد'

    db = get_db()

    # Build set of existing identities
    existing_rows = db.execute('SELECT config_text, config_type FROM configs WHERE status="active"').fetchall()
    existing_identities = set()
    for row in existing_rows:
        identity = get_config_identity(row['config_text'], row['config_type'])
        existing_identities.add(identity)

    max_sort_row = db.execute('SELECT MAX(sort_order) as max_val FROM configs WHERE status="active"').fetchone()
    max_sort = max_sort_row['max_val'] if max_sort_row else 0
    start_order = (max_sort if max_sort is not None else 0) + 1

    added_count = 0
    duplicates_count = 0

    for cfg in parsed:
        identity = get_config_identity(cfg['text'], cfg['type'])
        if identity in existing_identities:
            duplicates_count += 1
            continue
        current_order = start_order + added_count
        db.execute(
            'INSERT INTO configs (config_text, config_type, sort_order, is_enabled) VALUES (?, ?, ?, 1)',
            (cfg['text'], cfg['type'], current_order)
        )
        existing_identities.add(identity)
        added_count += 1

    db.commit()
    db.close()

    if added_count > 0:
        renumber_configs()

    # Build response message
    if added_count == 0 and duplicates_count > 0:
        if duplicates_count == 1:
            msg = 'این کانفیگ تکراری است و قبلاً اضافه شده است'
        else:
            msg = f'تمام {duplicates_count} کانفیگ وارد شده تکراری هستند'
        return added_count, duplicates_count, msg

    if added_count == 0:
        return 0, 0, 'هیچ کانفیگ جدیدی اضافه نشد'

    msg = f'{added_count} کانفیگ با موفقیت اضافه شد'
    if duplicates_count > 0:
        msg += f' ({duplicates_count} مورد تکراری نادیده گرفته شد)'
    return added_count, duplicates_count, msg

def set_config_enabled_status(config_id, enabled):
    """Toggle a config's enabled status. Returns (success, message)."""
    enabled_val = 1 if enabled else 0
    db = get_db()
    try:
        config_row = db.execute('SELECT * FROM configs WHERE id = ?', (config_id,)).fetchone()
        if not config_row:
            return False, 'کانفیگ پیدا نشد'
        db.execute('UPDATE configs SET is_enabled = ? WHERE id = ?', (enabled_val, config_id))
        db.commit()
        renumber_configs()
        return True, 'وضعیت کانفیگ با موفقیت تغییر کرد.'
    except Exception as e:
        print(f"Error setting config enabled status: {e}")
        return False, 'خطا در تغییر وضعیت کانفیگ'
    finally:
        db.close()

def delete_config(config_id):
    """Soft-delete a config. Returns (success, message)."""
    db = get_db()
    db.execute('UPDATE configs SET status = "deleted" WHERE id = ?', (config_id,))
    db.commit()
    db.close()
    renumber_configs()
    return True, 'کانفیگ با موفقیت حذف شد'

def bulk_delete_configs(ids):
    """Soft-delete multiple configs. Returns (success, message)."""
    if not ids:
        return False, 'هیچ موردی انتخاب نشده است'
    db = get_db()
    try:
        placeholders = ','.join(['?'] * len(ids))
        query = f'UPDATE configs SET status = "deleted" WHERE id IN ({placeholders})'
        db.execute(query, ids)
        db.commit()
        db.close()
        renumber_configs()
        return True, f'{len(ids)} کانفیگ با موفقیت حذف شدند'
    except Exception as e:
        print(f"Error in bulk delete: {e}")
        db.close()
        return False, 'خطا در حذف موارد'

def reorder_configs(order_list):
    """Reorder configs based on a list of IDs. Returns (success, message)."""
    if not order_list:
        return False, 'لیست ترتیب خالی است'
    db = get_db()
    try:
        for index, config_id in enumerate(order_list, 1):
            db.execute('UPDATE configs SET sort_order = ? WHERE id = ?', (index, config_id))
        db.commit()
        db.close()
        renumber_configs()
        return True, 'ترتیب با موفقیت ذخیره شد'
    except Exception as e:
        print(f"Error in reorder: {e}")
        db.close()
        return False, 'خطا در ذخیره ترتیب'