# -*- coding: utf-8 -*-
"""Client-facing subscription endpoint."""

from base64 import b64encode

from flask import Blueprint, request, Response

from database import get_setting
from extensions import limiter
from services.subscription_service import (
    generate_subscription_content, generate_dummy_content, DEVICE_LIMIT_MESSAGE,
)
from services.user_service import resolve_user_request, get_subscription_headers
from services.statistics_service import log_subscription_access
from utils.constants import (
    STATUS_SUCCESS, STATUS_NOT_FOUND,
    STATUS_EXPIRED, STATUS_USER_DISABLED, STATUS_USER_PAUSED, STATUS_DEVICE_LIMIT,
)

client_bp = Blueprint('client', __name__)


def _text(content, status=200):
    return Response(content, status=status, content_type='text/plain; charset=utf-8')


# Explicit per-minute limit instead of the default daily cap: users behind
# CGNAT share one IP, so a "200 per day" cap would cut off whole groups.
@client_bp.route('/sub/<path:sub_path>')
@limiter.limit('30 per minute')
def subscription(sub_path):
    """Serve the subscription content for a per-user path.

    Every link is a user (the public/shared-path concept was removed); an
    unknown path is a 404.
    """
    # ProxyFix resolves the real client IP from X-Forwarded-For behind Nginx
    ip = request.remote_addr
    ua = request.headers.get('User-Agent', '')

    resolved = resolve_user_request(sub_path, ip=ip, user_agent=ua)
    if resolved is None:
        log_subscription_access(ip, ua, STATUS_NOT_FOUND, sub_path)
        return _text("Not Found", status=404)

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
    if outcome == 'device_limit':
        log_subscription_access(ip, ua, STATUS_DEVICE_LIMIT, sub_path)
        return _text(generate_dummy_content(DEVICE_LIMIT_MESSAGE))
    # outcome == 'serve'
    log_subscription_access(ip, ua, STATUS_SUCCESS, sub_path)
    resp = _text(generate_subscription_content(_user))
    profile_title, expire_ts = get_subscription_headers(_user)
    resp.headers['Profile-Title'] = 'base64:' + b64encode(profile_title.encode('utf-8')).decode('ascii')
    resp.headers['Profile-Update-Interval'] = get_setting('profile_update_interval_hours', '6')
    if expire_ts is not None:
        resp.headers['Subscription-Userinfo'] = f'expire={expire_ts}'
    return resp