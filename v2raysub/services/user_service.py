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

from database import get_db, get_setting
from utils.constants import (
    USER_PATH_REGEX, USER_PATH_LENGTH,
    USER_STATUS_ACTIVE, USER_STATUS_PAUSED, USER_STATUS_DISABLED, USER_STATUS_EXPIRED,
)
from utils.misc import device_fingerprint

_TS_FMT = '%Y-%m-%d %H:%M:%S'


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------
def _utcnow():
    # Naive UTC (matches SQLite CURRENT_TIMESTAMP); avoids the deprecated utcnow().
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utcnow_str():
    return _utcnow().strftime(_TS_FMT)


def _device_window_cutoff(now=None):
    """Timestamp string before which a device slot is considered stale/free."""
    now = now or _utcnow()
    try:
        window_days = int(get_setting('device_window_days', '7'))
    except (TypeError, ValueError):
        window_days = 7
    return (now - timedelta(days=window_days)).strftime(_TS_FMT)


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
    if int(user.get('duration_days') or 0) == 0:
        return None, 'نامحدود'
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
        now = _utcnow()
        cutoff = _device_window_cutoff(now)
        counts = {
            r['user_id']: r['c'] for r in db.execute(
                'SELECT user_id, COUNT(*) AS c FROM user_devices '
                'WHERE last_seen >= ? GROUP BY user_id', (cutoff,)
            ).fetchall()
        }
    finally:
        db.close()
    result = []
    for r in rows:
        u = _decorate(dict(r), now)
        u['active_device_count'] = counts.get(u['id'], 0)
        result.append(u)
    return result


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
    if duration_days < 0:
        return False, 'مدت اشتراک نمی‌تواند منفی باشد', None
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
            if new_days < 0:
                return False, 'مدت اشتراک نمی‌تواند منفی باشد'
            old_days = user['duration_days']
            sets.append('duration_days = ?'); params.append(new_days)
            # Recompute expiry only for an already-activated user; a not-yet-activated
            # user just stores the new number (expiry is set on first use).
            if user['activated_at'] and new_days != old_days:
                if new_days == 0:
                    sets.append('expire_at = NULL')  # became unlimited
                elif old_days == 0:
                    # was unlimited → count the new span from activation
                    act = _parse(user['activated_at']) or _utcnow()
                    sets.append('expire_at = ?')
                    params.append((act + timedelta(days=new_days)).strftime(_TS_FMT))
                else:
                    # finite → finite: shift by the delta (preserves pause credit)
                    expire = _parse(user['expire_at'])
                    if expire is not None:
                        sets.append('expire_at = ?')
                        params.append((expire + timedelta(days=(new_days - old_days))).strftime(_TS_FMT))

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
        db.execute('DELETE FROM user_devices WHERE user_id = ?', (user_id,))
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
        # Reset restarts the lifecycle -> free the device slots too.
        db.execute('DELETE FROM user_devices WHERE user_id = ?', (user_id,))
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
# User-Agent substrings identifying link-preview crawlers / bots (Telegram,
# Twitter/X, Discord, Slack, Facebook, WhatsApp, search engines, ...). These
# fetch the subscription link to build a preview and are not real client
# devices, so they must not consume a per-user device slot. No real VPN client
# UA (v2rayNG, Nekobox, Clash, Streisand, sing-box, Hiddify, ...) contains these.
_BOT_UA_MARKERS = (
    'bot', 'crawler', 'spider', 'preview', 'facebookexternalhit', 'whatsapp',
)


def is_bot_user_agent(user_agent):
    """True if the User-Agent looks like a link-preview crawler / bot."""
    if not user_agent:
        return False
    ua = user_agent.lower()
    return any(marker in ua for marker in _BOT_UA_MARKERS)


def _allow_device(db, user, ip, user_agent):
    """Enforce the per-user device cap using a rolling-window of fingerprints.

    A device = the IP network block (/24) only — an "IP limit". Switching
    client apps on one connection sends several UAs but stays one device; the
    UA is still recorded per device, it just doesn't create a new slot. A
    device counts as an active "slot" only if seen within ``device_window_days``.
    An already-known
    device is always refreshed and allowed; a brand-new device is allowed only
    while free slots remain, otherwise rejected (caller serves the dummy config).

    Callers must route preview crawlers/bots (``is_bot_user_agent``) to a
    separate neutral response before reaching this function — they're never
    registered as a device, but they must not receive the real config either,
    since a spoofed bot-like User-Agent would otherwise bypass the cap entirely.

    Returns True to serve the real list, False to serve the device-limit dummy.
    Fails open (True) on unlimited caps, missing IPs, or any unexpected error.
    """
    max_dev = int(user['max_devices'] or 0)
    if max_dev <= 0:
        return True  # 0 = unlimited
    fp, net = device_fingerprint(ip)
    if net == 'unknown':
        return True  # can't identify the network -> don't punish a real user

    now = _utcnow()
    now_str = now.strftime(_TS_FMT)
    try:
        dev = db.execute(
            'SELECT id FROM user_devices WHERE user_id = ? AND fingerprint = ?',
            (user['id'], fp)
        ).fetchone()
        if dev:
            db.execute(
                'UPDATE user_devices SET last_seen = ?, last_ip = ?, '
                'user_agent = ?, network = ?, hits = hits + 1 WHERE id = ?',
                (now_str, ip, user_agent, net, dev['id'])
            )
            db.commit()
            return True  # known device — never blocked

        # Optional grace: don't enforce the cap right after activation, but still
        # register the device so it's part of the known set going forward.
        try:
            grace_hours = int(get_setting('device_grace_hours', '0'))
        except (TypeError, ValueError):
            grace_hours = 0
        in_grace = False
        if grace_hours > 0:
            activated = _parse(user['activated_at'])
            if activated is not None and (now - activated) < timedelta(hours=grace_hours):
                in_grace = True

        cutoff = _device_window_cutoff(now)
        active = db.execute(
            'SELECT COUNT(*) AS c FROM user_devices '
            'WHERE user_id = ? AND last_seen >= ?',
            (user['id'], cutoff)
        ).fetchone()['c']

        if in_grace or active < max_dev:
            # UNIQUE(user_id, fingerprint) guards against a concurrent double-insert.
            db.execute(
                'INSERT OR IGNORE INTO user_devices '
                '(user_id, fingerprint, first_seen, last_seen, network, last_ip, user_agent, hits) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, 1)',
                (user['id'], fp, now_str, now_str, net, ip, user_agent)
            )
            db.commit()
            return True
        return False
    except Exception as e:
        print(f"Error enforcing device limit: {e}")
        return True  # fail open


def resolve_user_request(sub_path, ip=None, user_agent=None):
    """Resolve a subscription hit for a user path.

    Returns one of:
        None                  -> path is not a user (route should fall back)
        ('disabled', user)    -> respond 404
        ('paused', user)      -> serve the dummy "expired/paused" config
        ('expired', user)     -> serve the dummy config
        ('device_limit', user) -> serve the device-limit dummy config
        ('bot', user)         -> serve a neutral placeholder, no config
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
            dur = int(user['duration_days'] or 0)
            # duration 0 = unlimited: activate but never set an expiry.
            expire = None if dur <= 0 else (now + timedelta(days=dur)).strftime(_TS_FMT)
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

        # Link-preview crawlers (Telegram/WhatsApp/etc. fetching a shared link)
        # are served a neutral placeholder — never the real config, and never
        # counted as a device. Without this, spoofing a bot-like User-Agent
        # would bypass the device cap entirely.
        if is_bot_user_agent(user_agent):
            return ('bot', user)

        # Device cap: register/refresh this device, block only a *new* device
        # once the rolling-window slots are full. Known devices are never blocked.
        if not _allow_device(db, user, ip, user_agent):
            return ('device_limit', user)
        return ('serve', user)
    except Exception as e:
        print(f"Error resolving user request: {e}")
        # On unexpected error, treat as not-a-user so the route can fall back.
        return None
    finally:
        db.close()


def get_user_history(user_id, limit=200):
    """Per-user access history from subscription_logs (matched by the user's
    path), newest first, plus the last-seen snapshot. Returns None if the user
    doesn't exist."""
    db = get_db()
    try:
        u = db.execute(
            'SELECT name, path, last_user_agent, last_ip, last_seen FROM users WHERE id = ?',
            (user_id,)
        ).fetchone()
        if not u:
            return None
        rows = db.execute(
            "SELECT datetime(accessed_at, 'localtime') AS at, ip_address, user_agent, status "
            "FROM subscription_logs WHERE request_path = ? "
            "ORDER BY accessed_at DESC LIMIT ?",
            (u['path'], limit)
        ).fetchall()
        # Distinct user-agents this user has connected with.
        uas = db.execute(
            "SELECT user_agent, COUNT(*) AS hits, MAX(datetime(accessed_at,'localtime')) AS last_at "
            "FROM subscription_logs WHERE request_path = ? AND user_agent IS NOT NULL AND user_agent != '' "
            "GROUP BY user_agent ORDER BY last_at DESC",
            (u['path'],)
        ).fetchall()
        return {
            'name': u['name'],
            'path': u['path'],
            'last_user_agent': u['last_user_agent'],
            'last_ip': u['last_ip'],
            'last_seen': _to_local_str(_parse(u['last_seen'])),
            'user_agents': [dict(r) for r in uas],
            'history': [dict(r) for r in rows],
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# dummy status configs (see [subscription_service.generate_subscription_content])
# ---------------------------------------------------------------------------
def get_dummy_status_texts(user):
    """Build the two display-only strings shown as fake configs at the top of
    a served subscription: current device usage and remaining time. Callers
    turn these into dummy config remarks (see subscription_service.py)."""
    max_dev = int(user.get('max_devices') or 0)
    if max_dev > 0:
        db = get_db()
        try:
            cutoff = _device_window_cutoff()
            count = db.execute(
                'SELECT COUNT(*) AS c FROM user_devices WHERE user_id = ? AND last_seen >= ?',
                (user['id'], cutoff)
            ).fetchone()['c']
        finally:
            db.close()
        device_text = f'{count} / {max_dev} دستگاه'
    else:
        device_text = 'دستگاه: نامحدود'

    secs, _ = _remaining(user)
    if secs is None:
        days_text = 'روز باقی مانده: نامحدود'
    else:
        days = -(-secs // 86400)  # ceil: any leftover time counts as a full day
        warn = '🔴 ' if days <= 3 else ''
        days_text = f'{warn}روز باقی مانده: {days} روز'

    return device_text, days_text


def get_subscription_headers(user):
    """Values for the standard subscription-info HTTP headers that clients
    like Hiddify, v2rayN/v2rayNG and Nekoray read natively (not from a config
    name): ``Profile-Title`` (shown as the subscription's display name — we
    put the device count here since there's no standard field for it) and the
    ``expire`` field of ``Subscription-Userinfo`` (remaining days is a
    well-known parameter clients already render on their own).

    Returns (profile_title_text, expire_unix_ts_or_None). Traffic fields
    (upload/download/total) are deliberately omitted: quota is unlimited, and
    sending total=0 gets misread by some clients as "no quota left" instead
    of "unlimited".
    """
    device_text, _ = get_dummy_status_texts(user)
    expire = _parse(user.get('expire_at'))
    expire_ts = int(expire.replace(tzinfo=timezone.utc).timestamp()) if expire else None
    return device_text, expire_ts


# ---------------------------------------------------------------------------
# device management (see DEVICE_LIMIT_ROADMAP.md)
# ---------------------------------------------------------------------------
def list_user_devices(user_id):
    """Registered devices for a user (active-first). Returns None if no user.

    Each device carries an ``is_active`` flag (seen within the rolling window)
    and localized first/last-seen strings. Also returns the cap and the count
    of currently-active devices."""
    db = get_db()
    try:
        u = db.execute('SELECT max_devices FROM users WHERE id = ?', (user_id,)).fetchone()
        if not u:
            return None
        now = _utcnow()
        cutoff = _device_window_cutoff(now)
        rows = db.execute(
            'SELECT id, fingerprint, network, last_ip, user_agent, hits, '
            'first_seen, last_seen FROM user_devices '
            'WHERE user_id = ? ORDER BY last_seen DESC',
            (user_id,)
        ).fetchall()
        devices = []
        active = 0
        for r in rows:
            d = dict(r)
            is_active = (str(d['last_seen']) >= cutoff)
            if is_active:
                active += 1
            d['is_active'] = is_active
            d['first_seen_local'] = _to_local_str(_parse(d['first_seen']))
            d['last_seen_local'] = _to_local_str(_parse(d['last_seen']))
            devices.append(d)
        return {
            'max_devices': int(u['max_devices'] or 0),
            'active_device_count': active,
            'devices': devices,
        }
    finally:
        db.close()


def reset_user_devices(user_id):
    """Forget all of a user's devices, freeing every slot. Returns (ok, msg)."""
    db = get_db()
    try:
        if not db.execute('SELECT 1 FROM users WHERE id = ?', (user_id,)).fetchone():
            return False, 'کاربر پیدا نشد'
        db.execute('DELETE FROM user_devices WHERE user_id = ?', (user_id,))
        db.commit()
        return True, 'دستگاه‌های کاربر پاک شدند.'
    except Exception as e:
        print(f"Error resetting user devices: {e}")
        return False, 'خطا در پاک‌کردن دستگاه‌ها'
    finally:
        db.close()


def delete_user_device(user_id, device_id):
    """Kick a single device (frees its slot). Returns (ok, msg)."""
    db = get_db()
    try:
        row = db.execute(
            'SELECT 1 FROM user_devices WHERE id = ? AND user_id = ?',
            (device_id, user_id)
        ).fetchone()
        if not row:
            return False, 'دستگاه پیدا نشد'
        db.execute('DELETE FROM user_devices WHERE id = ? AND user_id = ?', (device_id, user_id))
        db.commit()
        return True, 'دستگاه حذف شد.'
    except Exception as e:
        print(f"Error deleting user device: {e}")
        return False, 'خطا در حذف دستگاه'
    finally:
        db.close()


def cleanup_stale_devices(retention_days=30):
    """Prune device rows far past the active window to cap table growth.
    Mirrors the health-history retention in automation_service."""
    db = get_db()
    try:
        cutoff = (_utcnow() - timedelta(days=retention_days)).strftime(_TS_FMT)
        db.execute('DELETE FROM user_devices WHERE last_seen < ?', (cutoff,))
        db.commit()
    except Exception as e:
        print(f"Error cleaning up stale devices: {e}")
    finally:
        db.close()
