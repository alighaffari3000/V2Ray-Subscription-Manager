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
from database import get_setting
from utils.misc import get_base_url
from services.user_service import (
    get_user, add_user, update_user, delete_user,
    pause_user, resume_user, reset_user, set_user_enabled,
    list_user_devices,
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
        if not token or not secrets.compare_digest(token, configured):
            return jsonify({'success': False, 'error': 'unauthorized',
                            'message': 'Invalid or missing API token.'}), 401
        return f(*args, **kwargs)
    return wrapper


def _serialize(user):
    """Shape a user_service dict into the API's subscription object.

    Adds the full ``sub_url`` (built from the request host, so it matches the
    panel's public domain the bot called) and the live active-device count.
    """
    if not user:
        return None
    active_devices = None
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
        'sub_url': f"{get_base_url(request)}sub/{user['path']}",
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
    ok, message, user = add_user(
        name,
        duration_days=data.get('duration_days', 30),
        custom_path=(data.get('path') or '').strip() or None,
        note=(data.get('note') or '').strip() or None,
        max_devices=data.get('max_devices', 1),
    )
    if not ok:
        return jsonify({'success': False, 'error': 'create_failed', 'message': message}), 400
    return jsonify({'success': True, 'message': message,
                    'subscription': _serialize(user)}), 201


# ─── Read ────────────────────────────────────────────────────────
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
        kwargs['duration_days'] = data.get('duration_days')
    if 'max_devices' in data:
        kwargs['max_devices'] = data.get('max_devices')
    if 'note' in data:
        kwargs['note'] = (data.get('note') or '').strip()
    if 'path' in data:
        kwargs['custom_path'] = (data.get('path') or '').strip()
    ok, message = update_user(sub_id, **kwargs)
    return _mutation_result(ok, message, sub_id)


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
    enabled = bool(data.get('enabled', True))
    return _mutation_result(*set_user_enabled(sub_id, enabled), sub_id)


# ─── Delete ──────────────────────────────────────────────────────
@machine_api_bp.route(f'{API_PREFIX}/subs/<int:sub_id>', methods=['DELETE'])
@machine_api_bp.route(f'{API_PREFIX}/subs/<int:sub_id>/delete', methods=['POST'])
@require_api_token
def delete_sub(sub_id):
    if not get_user(sub_id):
        return _not_found()
    ok, message = delete_user(sub_id)
    return jsonify({'success': ok, 'message': message}), (200 if ok else 400)
