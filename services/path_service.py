# -*- coding: utf-8 -*-
"""Path CRUD, random path generation, path validation, enablement toggles."""

import re
import string
import secrets

from database import get_db
from utils.constants import PATH_REGEX, RANDOM_PATH_LENGTH


def get_all_paths():
    """Get all subscription paths ordered by primary first."""
    db = get_db()
    paths = db.execute('SELECT * FROM subscription_paths ORDER BY is_primary DESC, created_at DESC').fetchall()
    db.close()
    return [dict(p) for p in paths]


def get_primary_path():
    """Get the primary subscription path string."""
    db = get_db()
    row = db.execute('SELECT path FROM subscription_paths WHERE is_primary = 1').fetchone()
    db.close()
    return row['path'] if row else 'freeconfigs'


def get_other_paths():
    """Get all non-primary paths."""
    db = get_db()
    rows = db.execute('SELECT * FROM subscription_paths WHERE is_primary = 0 ORDER BY created_at DESC').fetchall()
    db.close()
    return [dict(r) for r in rows]


def find_path_by_value(path_value):
    """Look up a subscription_paths row by path string. Returns dict or None."""
    db = get_db()
    row = db.execute('SELECT * FROM subscription_paths WHERE path = ?', (path_value,)).fetchone()
    db.close()
    return dict(row) if row else None


def generate_random_path():
    """Generate a unique random alphanumeric path."""
    db = get_db()
    while True:
        chars = string.ascii_letters + string.digits
        random_path = ''.join(secrets.choice(chars) for _ in range(RANDOM_PATH_LENGTH))
        existing = db.execute('SELECT 1 FROM subscription_paths WHERE path = ?', (random_path,)).fetchone()
        if not existing:
            break
    db.close()
    return random_path


def validate_path(path_val):
    """Validate a path string against the allowed pattern. Returns (ok, error_msg)."""
    if not path_val:
        return False, 'مسیر نمی\u200cتواند خالی باشد'
    if not re.match(PATH_REGEX, path_val):
        return False, 'مسیر نامعتبر است. فقط حروف انگلیسی و اعداد بین ۳ تا ۳۲ کاراکتر مجاز هستند.'
    return True, ''


def add_path(path_val):
    """Add or set a path as primary. Returns (success, message, path_val)."""
    ok, err = validate_path(path_val)
    if not ok:
        return False, err, path_val

    db = get_db()
    try:
        existing = db.execute('SELECT * FROM subscription_paths WHERE path = ?', (path_val,)).fetchone()
        db.execute('UPDATE subscription_paths SET is_primary = 0')
        if existing:
            db.execute('UPDATE subscription_paths SET is_primary = 1, is_enabled = 1 WHERE path = ?', (path_val,))
        else:
            db.execute('INSERT INTO subscription_paths (path, is_primary, is_enabled) VALUES (?, 1, 1)', (path_val,))
        db.commit()
        return True, 'مسیر سابسکریپشن با موفقیت تغییر کرد.', path_val
    except Exception as e:
        print(f"Error adding subscription path: {e}")
        return False, 'خطا در ذخیره مسیر در دیتابیس', path_val
    finally:
        db.close()


def add_secondary_path(path_val):
    """Add a non-primary subscription path. Returns (success, message)."""
    ok, err = validate_path(path_val)
    if not ok:
        return False, err

    db = get_db()
    try:
        existing = db.execute('SELECT * FROM subscription_paths WHERE path = ?', (path_val,)).fetchone()
        if existing:
            return False, 'این مسیر قبلاً وجود دارد.'
        db.execute('INSERT INTO subscription_paths (path, is_primary, is_enabled) VALUES (?, 0, 1)', (path_val,))
        db.commit()
        return True, 'مسیر جدید با موفقیت اضافه شد.'
    except Exception as e:
        print(f"Error adding subscription path: {e}")
        return False, 'خطا در ذخیره مسیر در دیتابیس'
    finally:
        db.close()


def set_path_enabled(path_id, enabled):
    """Toggle a path's enabled status. Returns (success, message)."""
    enabled_val = 1 if enabled else 0
    db = get_db()
    try:
        path_row = db.execute('SELECT * FROM subscription_paths WHERE id = ?', (path_id,)).fetchone()
        if not path_row:
            return False, 'مسیر پیدا نشد'
        if path_row['is_primary'] == 1 and enabled_val == 0:
            return False, 'مسیر اصلی (Primary) را نمی\u200cتوان غیرفعال کرد.'
        db.execute('UPDATE subscription_paths SET is_enabled = ? WHERE id = ?', (enabled_val, path_id))
        db.commit()
        return True, 'وضعیت مسیر با موفقیت تغییر کرد.'
    except Exception as e:
        print(f"Error setting path enabled status: {e}")
        return False, 'خطا در تغییر وضعیت مسیر'
    finally:
        db.close()


def delete_path(path_id):
    """Delete a non-primary path. Returns (success, message)."""
    db = get_db()
    try:
        path_row = db.execute('SELECT * FROM subscription_paths WHERE id = ?', (path_id,)).fetchone()
        if not path_row:
            return False, 'مسیر پیدا نشد'
        if path_row['is_primary'] == 1:
            return False, 'مسیر اصلی (Primary) را نمی\u200cتوان حذف کرد.'
        db.execute('DELETE FROM subscription_paths WHERE id = ?', (path_id,))
        db.commit()
        return True, 'مسیر با موفقیت حذف شد.'
    except Exception as e:
        print(f"Error deleting path: {e}")
        return False, 'خطا در حذف مسیر'
    finally:
        db.close()