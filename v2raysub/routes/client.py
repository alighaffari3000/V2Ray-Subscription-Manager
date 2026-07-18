# -*- coding: utf-8 -*-
"""Client-facing subscription endpoint."""

from flask import Blueprint, request, Response

from extensions import limiter
from services.subscription_service import generate_subscription_content, generate_dummy_content
from services.path_service import find_path_by_value
from services.user_service import resolve_user_request
from services.statistics_service import log_subscription_access
from utils.constants import (
    STATUS_SUCCESS, STATUS_NOT_FOUND, STATUS_DISABLED_PATH,
    STATUS_EXPIRED, STATUS_USER_DISABLED, STATUS_USER_PAUSED,
)

client_bp = Blueprint('client', __name__)


def _text(content, status=200):
    return Response(content, status=status, content_type='text/plain; charset=utf-8')


# Explicit per-minute limit instead of the default daily cap: users behind
# CGNAT share one IP, so a "200 per day" cap would cut off whole groups.
@client_bp.route('/sub/<path:sub_path>')
@limiter.limit('30 per minute')
def subscription(sub_path):
    """Serve the subscription content for a given path.

    Resolution order: a per-user path (users table) takes precedence; if the
    path is not a user, fall back to the shared global paths (subscription_paths).
    """
    # ProxyFix resolves the real client IP from X-Forwarded-For behind Nginx
    ip = request.remote_addr
    ua = request.headers.get('User-Agent', '')

    # --- 1) Per-user subscription -------------------------------------------
    resolved = resolve_user_request(sub_path, ip=ip, user_agent=ua)
    if resolved is not None:
        outcome, _user = resolved
        if outcome == 'disabled':
            log_subscription_access(ip, ua, STATUS_USER_DISABLED, sub_path)
            return _text("Not Found", status=404)
        if outcome == 'expired':
            log_subscription_access(ip, ua, STATUS_EXPIRED, sub_path)
            return _text(generate_dummy_content())
        if outcome == 'paused':
            log_subscription_access(ip, ua, STATUS_USER_PAUSED, sub_path)
            return _text(generate_dummy_content())
        # outcome == 'serve'
        log_subscription_access(ip, ua, STATUS_SUCCESS, sub_path)
        return _text(generate_subscription_content())

    # --- 2) Fallback: shared global path -------------------------------------
    path_row = find_path_by_value(sub_path)

    if not path_row:
        log_subscription_access(ip, ua, STATUS_NOT_FOUND, sub_path)
        return _text("Not Found", status=404)

    if not path_row.get('is_enabled'):
        log_subscription_access(ip, ua, STATUS_DISABLED_PATH, sub_path)
        return _text("Not Found", status=404)

    log_subscription_access(ip, ua, STATUS_SUCCESS, sub_path)
    return _text(generate_subscription_content())