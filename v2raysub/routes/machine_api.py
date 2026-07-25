# -*- coding: utf-8 -*-
"""Token-authenticated machine API (v1) for external clients — e.g. a sales bot.

This is the surface an external client uses to create and manage subscriptions on
the shared config pool. It maps 1:1 onto ``services.user_service`` and deliberately
carries no business logic of its own. Unlike the admin JSON API it has no session
and no CSRF: auth is a single ``Authorization: Bearer <token>`` header compared
against the ``api_token`` setting. When that setting is empty the whole API is
disabled (503) so a fresh install is never open by default.
"""

import os
import secrets
from functools import wraps

from flask import Blueprint, request, jsonify

import utils.constants as constants
from utils.constants import USER_MAX_DURATION_DAYS
from database import get_setting
from utils.misc import get_public_base_url
from services.user_service import (
    get_user, get_user_by_path, get_all_users, add_user, update_user, delete_user,
    extend_user, pause_user, resume_user, reset_user, set_user_enabled,
    list_user_devices, reset_user_devices, delete_user_device,
)

machine_api_bp = Blueprint('machine_api', __name__)

API_PREFIX = '/api/v1'


def _read_version():
    """Panel version from the VERSION file (single source of truth), or 'unknown'."""
    try:
        with open(os.path.join(constants.BASE_DIR, 'VERSION'), encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return 'unknown'


def require_api_token(f):
    """Guard: require a valid ``Authorization: Bearer <token>`` header.

    503 when no token is configured (API disabled), 401 on a missing/wrong one.
    Constant-time compare avoids leaking the token via timing.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        configured = (get_setting('api_token', '') or '').strip()
        if not configured:
            return jsonify({'success': False, 'error': 'api_disabled',
                            'message': 'Machine API is disabled (no token configured).'}), 503
        auth = request.headers.get('Authorization', '')
        token = auth[7:].strip() if auth.startswith('Bearer ') else ''
        # Compare as bytes: compare_digest raises TypeError on non-ASCII str, and
        # headers are attacker-controlled, so a token containing e.g. 'é' would
        # turn this pre-auth path into an unhandled 500 on an unthrottled route.
        if not token or not secrets.compare_digest(token.encode('utf-8'),
                                                  configured.encode('utf-8')):
            return jsonify({'success': False, 'error': 'unauthorized',
                            'message': 'Invalid or missing API token.'}), 401
        return f(*args, **kwargs)
    return wrapper


def _serialize(user, active_devices=None):
    """Shape a user_service dict into the API's subscription object.

    Adds the customer-facing ``sub_url`` and the live active-device count. Pass
    ``active_devices`` to reuse an already-known count (list endpoint) instead of
    querying per row.
    """
    if not user:
        return None
    if active_devices is None:
        try:
            info = list_user_devices(user['id'])
            if info:
                active_devices = info['active_device_count']
        except Exception:
            active_devices = None
    return {
        'id': user['id'],
        'uuid': user.get('uuid'),
        'name': user.get('name'),
        'path': user.get('path'),
        'sub_url': f"{get_public_base_url(request)}sub/{user['path']}",
        'status': user.get('status'),
        'effective_status': user.get('effective_status'),
        'duration_days': user.get('duration_days'),
        'max_devices': user.get('max_devices'),
        'active_device_count': active_devices,
        'remaining_seconds': user.get('remaining_seconds'),
        'remaining_text': user.get('remaining_text'),
        'activated_at': user.get('activated_at'),
        'expire_at': user.get('expire_at'),
        'last_seen': user.get('last_seen'),
        'note': user.get('note'),
        'created_at': user.get('created_at'),
    }


def _not_found():
    return jsonify({'success': False, 'error': 'not_found',
                    'message': 'Subscription not found.'}), 404


def _bad_request(field, message):
    return jsonify({'success': False, 'error': 'invalid_request',
                    'field': field, 'message': message}), 400


def _require_int(data, field, default=None, minimum=None, maximum=None):
    """Read a strictly-integral field. Returns (value, error_response|None).

    A machine API should not guess: JSON booleans (``true`` is an int in Python),
    floats and numeric strings are all rejected rather than silently coerced, so a
    malformed renewal fails loudly instead of quietly applying '1 day'.
    """
    if field not in data or data.get(field) is None:
        return default, None
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        return None, _bad_request(field, f'{field} must be an integer.')
    if minimum is not None and value < minimum:
        return None, _bad_request(field, f'{field} must be >= {minimum}.')
    if maximum is not None and value > maximum:
        return None, _bad_request(field, f'{field} must be <= {maximum}.')
    return value, None


def _require_bool(data, field, default):
    """Read a strict JSON boolean. Returns (value, error_response|None).

    Never truthiness-coerce here: ``bool("false")`` is True, so accepting a string
    would flip a suspend request into an enable — the dangerous direction.
    """
    if field not in data or data.get(field) is None:
        return default, None
    value = data.get(field)
    if not isinstance(value, bool):
        return None, _bad_request(field, f'{field} must be true or false.')
    return value, None


def _mutation_result(ok, message, sub_id):
    """Standard response for a state transition: refresh the sub on success."""
    if not ok:
        return jsonify({'success': False, 'error': 'operation_failed', 'message': message}), 400
    return jsonify({'success': True, 'message': message,
                    'subscription': _serialize(get_user(sub_id))})


# ─── Health ──────────────────────────────────────────────────────
@machine_api_bp.route(f'{API_PREFIX}/health', methods=['GET'])
@require_api_token
def health():
    """Token check + panel version. The bot calls this on startup to verify creds."""
    return jsonify({'ok': True, 'service': 'v2raysub', 'version': _read_version()})


# ─── Create ──────────────────────────────────────────────────────
@machine_api_bp.route(f'{API_PREFIX}/subs', methods=['POST'])
@require_api_token
def create_sub():
    """Create a subscription (a user) on the shared pool. Returns its sub_url."""
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'invalid_name',
                        'message': 'name is required.'}), 400
    custom_path = (data.get('path') or '').strip() or None
    # Validate up front so the only way the create below can fail with a custom
    # path already present is a genuine path conflict — which is what makes the
    # 409 contract below trustworthy.
    duration_days, err = _require_int(data, 'duration_days', default=30,
                                      minimum=0, maximum=USER_MAX_DURATION_DAYS)
    if err:
        return err
    max_devices, err = _require_int(data, 'max_devices', default=1, minimum=0)
    if err:
        return err

    ok, message, user = add_user(
        name,
        duration_days=duration_days,
        custom_path=custom_path,
        note=(data.get('note') or '').strip() or None,
        max_devices=max_devices,
    )
    if not ok:
        # A caller that supplies its own deterministic path (an order id, say) gets
        # a retry-safe create: a duplicate is reported as a distinct, machine-
        # readable conflict carrying the subscription that already exists, so a
        # retried payment webhook recovers the original instead of minting a second
        # subscription or having to string-match an error message.
        if custom_path:
            existing = get_user_by_path(custom_path)
            if existing:
                return jsonify({'success': False, 'error': 'path_taken',
                                'message': message,
                                'subscription': _serialize(existing)}), 409
        return jsonify({'success': False, 'error': 'create_failed', 'message': message}), 400
    return jsonify({'success': True, 'message': message,
                    'subscription': _serialize(user)}), 201


# ─── Read ────────────────────────────────────────────────────────
@machine_api_bp.route(f'{API_PREFIX}/subs', methods=['GET'])
@require_api_token
def list_subs():
    """Every subscription, newest first — for reconciling the client's own records
    against the panel (detecting subs deleted or edited here)."""
    users = get_all_users()
    return jsonify({
        'success': True,
        'count': len(users),
        'subscriptions': [_serialize(u, u.get('active_device_count')) for u in users],
    })


@machine_api_bp.route(f'{API_PREFIX}/subs/<int:sub_id>', methods=['GET'])
@require_api_token
def get_sub(sub_id):
    """Current state: activation, expiry, remaining time, active devices."""
    user = get_user(sub_id)
    if not user:
        return _not_found()
    return jsonify({'success': True, 'subscription': _serialize(user)})


# ─── Update (extend / change device cap / rename) ────────────────
@machine_api_bp.route(f'{API_PREFIX}/subs/<int:sub_id>', methods=['PATCH', 'POST'])
@require_api_token
def update_sub(sub_id):
    """Partial update. Only provided keys change; omitted keys keep their value.

    Duration changes follow the panel's own rules (a not-yet-activated sub just
    stores the new number; an activated one shifts its expiry by the delta).
    """
    if not get_user(sub_id):
        return _not_found()
    data = request.get_json(silent=True) or {}
    kwargs = {}
    if 'name' in data:
        kwargs['name'] = (data.get('name') or '').strip()
    if 'duration_days' in data:
        value, err = _require_int(data, 'duration_days', minimum=0,
                                  maximum=USER_MAX_DURATION_DAYS)
        if err:
            return err
        kwargs['duration_days'] = value
    if 'max_devices' in data:
        value, err = _require_int(data, 'max_devices', minimum=0)
        if err:
            return err
        kwargs['max_devices'] = value
    if 'note' in data:
        kwargs['note'] = (data.get('note') or '').strip()
    if 'path' in data:
        kwargs['custom_path'] = (data.get('path') or '').strip()
    ok, message = update_user(sub_id, **kwargs)
    return _mutation_result(ok, message, sub_id)


# ─── Renewal ─────────────────────────────────────────────────────
@machine_api_bp.route(f'{API_PREFIX}/subs/<int:sub_id>/extend', methods=['POST'])
@require_api_token
def extend_sub(sub_id):
    """Add days to a subscription. Body: ``{"days": 30}``.

    Use this for renewals rather than PATCHing ``duration_days``: an already
    expired subscription restarts from now, so the customer never loses days they
    just paid for.
    """
    if not get_user(sub_id):
        return _not_found()
    data = request.get_json(silent=True) or {}
    days, err = _require_int(data, 'days', minimum=1, maximum=USER_MAX_DURATION_DAYS)
    if err:
        return err
    if days is None:
        return _bad_request('days', 'days is required.')
    return _mutation_result(*extend_user(sub_id, days), sub_id)


# ─── State transitions ───────────────────────────────────────────
@machine_api_bp.route(f'{API_PREFIX}/subs/<int:sub_id>/pause', methods=['POST'])
@require_api_token
def pause_sub(sub_id):
    if not get_user(sub_id):
        return _not_found()
    return _mutation_result(*pause_user(sub_id), sub_id)


@machine_api_bp.route(f'{API_PREFIX}/subs/<int:sub_id>/resume', methods=['POST'])
@require_api_token
def resume_sub(sub_id):
    if not get_user(sub_id):
        return _not_found()
    return _mutation_result(*resume_user(sub_id), sub_id)


@machine_api_bp.route(f'{API_PREFIX}/subs/<int:sub_id>/reset', methods=['POST'])
@require_api_token
def reset_sub(sub_id):
    """Clear activation so the countdown restarts on next fetch (and free devices)."""
    if not get_user(sub_id):
        return _not_found()
    return _mutation_result(*reset_user(sub_id), sub_id)


@machine_api_bp.route(f'{API_PREFIX}/subs/<int:sub_id>/toggle', methods=['POST'])
@require_api_token
def toggle_sub(sub_id):
    """Enable (ACTIVE) or permanently disable (DISABLED). Body: {"enabled": bool}."""
    if not get_user(sub_id):
        return _not_found()
    data = request.get_json(silent=True) or {}
    enabled, err = _require_bool(data, 'enabled', default=True)
    if err:
        return err
    return _mutation_result(*set_user_enabled(sub_id, enabled), sub_id)


# ─── Devices ─────────────────────────────────────────────────────
# The device cap is half of what a plan sells (duration x max_devices), so
# "I hit the device limit" / "I switched phones" is the most likely support
# request. Exposing these lets the external client resolve it on its own.

@machine_api_bp.route(f'{API_PREFIX}/subs/<int:sub_id>/devices', methods=['GET'])
@require_api_token
def list_devices(sub_id):
    """Registered devices (active first), the cap, and the active count."""
    info = list_user_devices(sub_id)
    if info is None:
        return _not_found()
    return jsonify({'success': True, **info})


@machine_api_bp.route(f'{API_PREFIX}/subs/<int:sub_id>/devices/reset', methods=['POST'])
@require_api_token
def reset_devices(sub_id):
    """Forget every device, freeing all slots."""
    # Check existence separately: the service returns the same (False, message)
    # shape for "no such subscription" and for an internal error, and reporting a
    # database failure as 404 would tell the caller to drop a record that still
    # exists.
    if not get_user(sub_id):
        return _not_found()
    ok, message = reset_user_devices(sub_id)
    if not ok:
        return jsonify({'success': False, 'error': 'internal_error',
                        'message': message}), 500
    return jsonify({'success': True, 'message': message})


@machine_api_bp.route(f'{API_PREFIX}/subs/<int:sub_id>/devices/<int:device_id>',
                      methods=['DELETE'])
@machine_api_bp.route(f'{API_PREFIX}/subs/<int:sub_id>/devices/<int:device_id>/delete',
                      methods=['POST'])
@require_api_token
def delete_device(sub_id, device_id):
    """Kick a single device, freeing its slot."""
    info = list_user_devices(sub_id)
    if info is None:
        return _not_found()
    # Establish up front whether the device exists, so a genuine failure below is
    # reported as an internal error rather than as a misleading 404.
    if device_id not in {d['id'] for d in info['devices']}:
        return jsonify({'success': False, 'error': 'device_not_found',
                        'message': 'Device not found.'}), 404
    ok, message = delete_user_device(sub_id, device_id)
    if not ok:
        return jsonify({'success': False, 'error': 'internal_error',
                        'message': message}), 500
    return jsonify({'success': True, 'message': message})


# ─── Delete ──────────────────────────────────────────────────────
@machine_api_bp.route(f'{API_PREFIX}/subs/<int:sub_id>', methods=['DELETE'])
@machine_api_bp.route(f'{API_PREFIX}/subs/<int:sub_id>/delete', methods=['POST'])
@require_api_token
def delete_sub(sub_id):
    if not get_user(sub_id):
        return _not_found()
    ok, message = delete_user(sub_id)
    return jsonify({'success': ok, 'message': message}), (200 if ok else 400)
