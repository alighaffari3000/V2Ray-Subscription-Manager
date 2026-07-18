# -*- coding: utf-8 -*-
"""User management: CRUD, unique paths, activation-on-first-use, expiry/pause logic.

Time convention (important):
    All timestamps this module writes to the ``users`` table — activated_at,
    expire_at, paused_at, last_seen, updated_at — are stored as naive **UTC**
    strings (``%Y-%m-%d %H:%M:%S``), matching SQLite's ``CURRENT_TIMESTAMP``
    default used for created_at. Every comparison is done against
    ``datetime.utcnow()``. This keeps a row's clocks consistent and makes the
    expiry math immune to the server timezone (the app is pinned to Asia/Tehran)
    and DST. Absolute dates are converted to local time only for admin display.
"""

import re
import uuid
import string
import secrets
from datetime import datetime, timedelta, timezone

from database import get_db
from utils.constants import (
    USER_PATH_REGEX, USER_PATH_LENGTH,
    USER_STATUS_ACTIVE, USER_STATUS_PAUSED, USER_STATUS_DISABLED, USER_STATUS_EXPIRED,
)

_TS_FMT = '%Y-%m-%d %H:%M:%S'


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------
def _utcnow():
    # Naive UTC (matches SQLite CURRENT_TIMESTAMP); avoids the deprecated utcnow().
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utcnow_str():
    return _utcnow().strftime(_TS_FMT)


def _parse(ts):
    """Parse a stored timestamp string to a naive UTC datetime, or None."""
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts
    s = str(ts).strip().replace('T', ' ')
    # drop fractional seconds / trailing timezone markers if present
    s = s.split('.')[0].split('+')[0].strip()
    for fmt in (_TS_FMT, '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _local_offset():
    """Server local offset relative to UTC (app is pinned to Asia/Tehran)."""
    # naive difference; good enough for display conversion
    return datetime.now() - _utcnow()


def _to_local_str(utc_dt):
    """Format a UTC datetime as a local-time display string, or '' if None."""
    if utc_dt is None:
        return ''
    return (utc_dt + _local_offset()).strftime(_TS_FMT)


# ---------------------------------------------------------------------------
# path validation & uniqueness
# ---------------------------------------------------------------------------
def validate_user_path(path_val):
    """Validate a user sub-path. Returns (ok, error_msg)."""
    if not path_val:
        return False, 'مسیر نمی‌تواند خالی باشد'
    if not re.match(USER_PATH_REGEX, path_val):
        return False, ('مسیر نامعتبر است. فقط حروف انگلیسی، اعداد، «_» و «-» '
                       'و بین ۸ تا ۶۴ کاراکتر مجاز است.')
    return True, ''


def _path_taken(db, path_val, exclude_user_id=None):
    """True if path already exists in users OR subscription_paths (cross-table)."""
    if exclude_user_id is None:
        u = db.execute('SELECT 1 FROM users WHERE path = ?', (path_val,)).fetchone()
    else:
        u = db.execute('SELECT 1 FROM users WHERE path = ? AND id != ?',
                       (path_val, exclude_user_id)).fetchone()
    if u:
        return True
    p = db.execute('SELECT 1 FROM subscription_paths WHERE path = ?', (path_val,)).fetchone()
    return bool(p)


def _generate_unique_path(db):
    """Generate a random path unique across both tables."""
    alphabet = string.ascii_letters + string.digits
    while True:
        candidate = ''.join(secrets.choice(alphabet) for _ in range(USER_PATH_LENGTH))
        if not _path_taken(db, candidate):
            return candidate


# ---------------------------------------------------------------------------
# effective status & remaining time (pure, for display)
# ---------------------------------------------------------------------------
def compute_effective_status(user, now=None):
    """Derive the shown status. EXPIRED is computed, never stored."""
    now = now or _utcnow()
    status = user.get('status') or USER_STATUS_ACTIVE
    if status == USER_STATUS_DISABLED:
        return USER_STATUS_DISABLED
    if status == USER_STATUS_PAUSED:
        return USER_STATUS_PAUSED
    expire = _parse(user.get('expire_at'))
    if expire is not None and expire < now:
        return USER_STATUS_EXPIRED
    return USER_STATUS_ACTIVE


def _remaining(user, now=None):
    """Return (remaining_seconds or None, human_text)."""
    now = now or _utcnow()
    expire = _parse(user.get('expire_at'))
    if expire is None:
        return None, 'فعال نشده'
    secs = int((expire - now).total_seconds())
    if secs <= 0:
        return 0, 'منقضی شده'
    days, rem = divmod(secs, 86400)
    hours = rem // 3600
    if days > 0:
        return secs, f'{days} روز و {hours} ساعت'
    minutes = (rem % 3600) // 60
    if hours > 0:
        return secs, f'{hours} ساعت و {minutes} دقیقه'
    return secs, f'{minutes} دقیقه'


def _decorate(user, now=None):
    """Add computed display fields to a user dict."""
    now = now or _utcnow()
    u = dict(user)
    u['effective_status'] = compute_effective_status(u, now)
    secs, human = _remaining(u, now)
    u['remaining_seconds'] = secs
    u['remaining_text'] = human
    u['activated_at_local'] = _to_local_str(_parse(u.get('activated_at')))
    u['expire_at_local'] = _to_local_str(_parse(u.get('expire_at')))
    u['last_seen_local'] = _to_local_str(_parse(u.get('last_seen')))
    return u


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def get_all_users():
    """All users, newest first, with computed display fields."""
    db = get_db()
    try:
        rows = db.execute('SELECT * FROM users ORDER BY created_at DESC, id DESC').fetchall()
    finally:
        db.close()
    now = _utcnow()
    return [_decorate(dict(r), now) for r in rows]


def get_user(user_id):
    """Single user with computed fields, or None."""
    db = get_db()
    try:
        row = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    finally:
        db.close()
    return _decorate(dict(row)) if row else None


def add_user(name, duration_days=30, custom_path=None, note=None, max_devices=1):
    """Create a user with a unique sub-path. Returns (success, message, user|None)."""
    name = (name or '').strip()
    if not name:
        return False, 'نام کاربر نمی‌تواند خالی باشد', None
    try:
        duration_days = int(duration_days)
    except (TypeError, ValueError):
        return False, 'مدت اشتراک باید عدد باشد', None
    if duration_days < 1:
        return False, 'مدت اشتراک باید حداقل ۱ روز باشد', None
    try:
        max_devices = int(max_devices)
    except (TypeError, ValueError):
        max_devices = 1

    db = get_db()
    try:
        if custom_path:
            custom_path = custom_path.strip()
            ok, err = validate_user_path(custom_path)
            if not ok:
                return False, err, None
            if _path_taken(db, custom_path):
                return False, 'این مسیر قبلاً استفاده شده است.', None
            path_val = custom_path
        else:
            path_val = _generate_unique_path(db)

        cur = db.execute(
            '''INSERT INTO users (uuid, name, path, status, duration_days, note, max_devices)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (uuid.uuid4().hex, name, path_val, USER_STATUS_ACTIVE,
             duration_days, note, max_devices)
        )
        db.commit()
        new_id = cur.lastrowid
        row = db.execute('SELECT * FROM users WHERE id = ?', (new_id,)).fetchone()
        return True, 'کاربر با موفقیت ساخته شد.', _decorate(dict(row))
    except Exception as e:
        print(f"Error adding user: {e}")
        return False, 'خطا در ساخت کاربر', None
    finally:
        db.close()


def update_user(user_id, name=None, duration_days=None, custom_path=None,
                note=None, max_devices=None):
    """Edit a user. Recalculates expire_at if duration changes post-activation.
    Returns (success, message)."""
    db = get_db()
    try:
        row = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        if not row:
            return False, 'کاربر پیدا نشد'
        user = dict(row)

        sets, params = [], []

        if name is not None:
            name = name.strip()
            if not name:
                return False, 'نام کاربر نمی‌تواند خالی باشد'
            sets.append('name = ?'); params.append(name)

        if custom_path is not None:
            custom_path = custom_path.strip()
            ok, err = validate_user_path(custom_path)
            if not ok:
                return False, err
            if _path_taken(db, custom_path, exclude_user_id=user_id):
                return False, 'این مسیر قبلاً استفاده شده است.'
            sets.append('path = ?'); params.append(custom_path)

        if note is not None:
            sets.append('note = ?'); params.append(note)

        if max_devices is not None:
            try:
                sets.append('max_devices = ?'); params.append(int(max_devices))
            except (TypeError, ValueError):
                pass

        if duration_days is not None:
            try:
                new_days = int(duration_days)
            except (TypeError, ValueError):
                return False, 'مدت اشتراک باید عدد باشد'
            if new_days < 1:
                return False, 'مدت اشتراک باید حداقل ۱ روز باشد'
            old_days = user['duration_days']
            sets.append('duration_days = ?'); params.append(new_days)
            # If already activated, shift expire_at by the delta so remaining time
            # tracks the new duration. If not activated yet, only the number changes.
            if user['activated_at'] and user['expire_at'] and new_days != old_days:
                expire = _parse(user['expire_at'])
                if expire is not None:
                    new_expire = expire + timedelta(days=(new_days - old_days))
                    sets.append('expire_at = ?'); params.append(new_expire.strftime(_TS_FMT))

        if not sets:
            return True, 'تغییری اعمال نشد'

        sets.append('updated_at = ?'); params.append(_utcnow_str())
        params.append(user_id)
        db.execute(f'UPDATE users SET {", ".join(sets)} WHERE id = ?', params)
        db.commit()
        return True, 'کاربر با موفقیت به‌روزرسانی شد.'
    except Exception as e:
        print(f"Error updating user: {e}")
        return False, 'خطا در به‌روزرسانی کاربر'
    finally:
        db.close()


def delete_user(user_id):
    """Remove a user. Returns (success, message)."""
    db = get_db()
    try:
        row = db.execute('SELECT 1 FROM users WHERE id = ?', (user_id,)).fetchone()
        if not row:
            return False, 'کاربر پیدا نشد'
        db.execute('DELETE FROM users WHERE id = ?', (user_id,))
        db.commit()
        return True, 'کاربر با موفقیت حذف شد.'
    except Exception as e:
        print(f"Error deleting user: {e}")
        return False, 'خطا در حذف کاربر'
    finally:
        db.close()


# ---------------------------------------------------------------------------
# status transitions
# ---------------------------------------------------------------------------
def pause_user(user_id):
    """Freeze the countdown. Returns (success, message)."""
    db = get_db()
    try:
        row = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        if not row:
            return False, 'کاربر پیدا نشد'
        user = dict(row)
        if user['status'] == USER_STATUS_DISABLED:
            return False, 'کاربر غیرفعال است؛ ابتدا آن را فعال کنید.'
        if user['status'] == USER_STATUS_PAUSED:
            return True, 'کاربر از قبل متوقف بود'
        db.execute('UPDATE users SET status = ?, paused_at = ?, updated_at = ? WHERE id = ?',
                   (USER_STATUS_PAUSED, _utcnow_str(), _utcnow_str(), user_id))
        db.commit()
        return True, 'اشتراک کاربر موقتاً متوقف شد.'
    except Exception as e:
        print(f"Error pausing user: {e}")
        return False, 'خطا در توقف کاربر'
    finally:
        db.close()


def resume_user(user_id):
    """Resume a paused user, extending expire_at by the paused span. Returns (success, message)."""
    db = get_db()
    try:
        row = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        if not row:
            return False, 'کاربر پیدا نشد'
        user = dict(row)
        if user['status'] != USER_STATUS_PAUSED:
            return False, 'کاربر در حالت توقف نیست'

        sets = ['status = ?', 'paused_at = ?', 'updated_at = ?']
        params = [USER_STATUS_ACTIVE, None, _utcnow_str()]

        # Only shift time for an already-activated user; a never-activated user
        # hasn't started its countdown, so there is nothing to preserve.
        paused_at = _parse(user['paused_at'])
        expire = _parse(user['expire_at'])
        if user['activated_at'] and paused_at and expire:
            paused_span = _utcnow() - paused_at
            new_expire = expire + paused_span
            sets.insert(0, 'expire_at = ?')
            params.insert(0, new_expire.strftime(_TS_FMT))

        params.append(user_id)
        db.execute(f'UPDATE users SET {", ".join(sets)} WHERE id = ?', params)
        db.commit()
        return True, 'اشتراک کاربر از سر گرفته شد.'
    except Exception as e:
        print(f"Error resuming user: {e}")
        return False, 'خطا در ازسرگیری کاربر'
    finally:
        db.close()


def reset_user(user_id):
    """Clear activation so the countdown restarts on next fetch. Returns (success, message)."""
    db = get_db()
    try:
        row = db.execute('SELECT 1 FROM users WHERE id = ?', (user_id,)).fetchone()
        if not row:
            return False, 'کاربر پیدا نشد'
        db.execute(
            '''UPDATE users SET activated_at = NULL, expire_at = NULL, paused_at = NULL,
               status = ?, updated_at = ? WHERE id = ?''',
            (USER_STATUS_ACTIVE, _utcnow_str(), user_id)
        )
        db.commit()
        return True, 'وضعیت فعال‌سازی کاربر ریست شد.'
    except Exception as e:
        print(f"Error resetting user: {e}")
        return False, 'خطا در ریست کاربر'
    finally:
        db.close()


def set_user_enabled(user_id, enabled):
    """Enable (ACTIVE) or permanently disable (DISABLED) a user. Returns (success, message)."""
    db = get_db()
    try:
        row = db.execute('SELECT 1 FROM users WHERE id = ?', (user_id,)).fetchone()
        if not row:
            return False, 'کاربر پیدا نشد'
        if enabled:
            db.execute('UPDATE users SET status = ?, paused_at = NULL, updated_at = ? WHERE id = ?',
                       (USER_STATUS_ACTIVE, _utcnow_str(), user_id))
            msg = 'کاربر فعال شد.'
        else:
            db.execute('UPDATE users SET status = ?, updated_at = ? WHERE id = ?',
                       (USER_STATUS_DISABLED, _utcnow_str(), user_id))
            msg = 'کاربر غیرفعال شد.'
        db.commit()
        return True, msg
    except Exception as e:
        print(f"Error toggling user: {e}")
        return False, 'خطا در تغییر وضعیت کاربر'
    finally:
        db.close()


# ---------------------------------------------------------------------------
# subscription request resolution (used by routes/client.py)
# ---------------------------------------------------------------------------
def resolve_user_request(sub_path, ip=None, user_agent=None):
    """Resolve a subscription hit for a user path.

    Returns one of:
        None                  -> path is not a user (route should fall back)
        ('disabled', user)    -> respond 404
        ('paused', user)      -> serve the dummy "expired/paused" config
        ('expired', user)     -> serve the dummy config
        ('serve', user)       -> serve the real global config list

    Side effects: atomic activation-on-first-use, and last_seen/last_ip/
    last_user_agent update on every recognized hit.
    """
    db = get_db()
    try:
        row = db.execute('SELECT * FROM users WHERE path = ?', (sub_path,)).fetchone()
        if not row:
            return None
        user = dict(row)
        now_str = _utcnow_str()

        # Record contact on every recognized hit (useful for debugging).
        db.execute(
            'UPDATE users SET last_seen = ?, last_ip = ?, last_user_agent = ? WHERE id = ?',
            (now_str, ip, user_agent, user['id'])
        )
        db.commit()

        status = user['status'] or USER_STATUS_ACTIVE
        if status == USER_STATUS_DISABLED:
            return ('disabled', user)
        if status == USER_STATUS_PAUSED:
            return ('paused', user)

        # ACTIVE: activate on first use, atomically (guards against races).
        if not user['activated_at']:
            now = _utcnow()
            expire = (now + timedelta(days=int(user['duration_days']))).strftime(_TS_FMT)
            db.execute(
                'UPDATE users SET activated_at = ?, expire_at = ? '
                'WHERE id = ? AND activated_at IS NULL',
                (now.strftime(_TS_FMT), expire, user['id'])
            )
            db.commit()
            # Re-read to get the authoritative values (another request may have won).
            user = dict(db.execute('SELECT * FROM users WHERE id = ?', (user['id'],)).fetchone())

        expire = _parse(user['expire_at'])
        if expire is not None and expire < _utcnow():
            return ('expired', user)
        return ('serve', user)
    except Exception as e:
        print(f"Error resolving user request: {e}")
        # On unexpected error, treat as not-a-user so the route can fall back.
        return None
    finally:
        db.close()
