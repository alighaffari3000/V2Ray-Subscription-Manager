# -*- coding: utf-8 -*-
"""Client-facing subscription endpoint."""

from flask import Blueprint, request, Response

from services.subscription_service import generate_subscription_content
from services.path_service import find_path_by_value
from services.statistics_service import log_subscription_access
from utils.constants import STATUS_SUCCESS, STATUS_NOT_FOUND, STATUS_DISABLED_PATH

client_bp = Blueprint('client', __name__)


@client_bp.route('/sub/<path:sub_path>')
def subscription(sub_path):
    """Serve the subscription content for a given path."""
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    ua = request.headers.get('User-Agent', '')

    path_row = find_path_by_value(sub_path)

    if not path_row:
        log_subscription_access(ip, ua, STATUS_NOT_FOUND, sub_path)
        return Response("Not Found", status=404, content_type='text/plain; charset=utf-8')

    if not path_row.get('is_enabled'):
        log_subscription_access(ip, ua, STATUS_DISABLED_PATH, sub_path)
        return Response("Not Found", status=404, content_type='text/plain; charset=utf-8')

    content = generate_subscription_content()
    log_subscription_access(ip, ua, STATUS_SUCCESS, sub_path)

    return Response(content, content_type='text/plain; charset=utf-8')