# -*- coding: utf-8 -*-
"""Lightweight, dependency-free CSRF protection.

A per-session random token is issued and exposed to the admin templates. Every
state-changing request (POST/PUT/PATCH/DELETE) must echo it back, either in the
``X-CSRF-Token`` header (used by the panel's fetch() calls) or a ``csrf_token``
form field (used by the login form). The session cookie is already
``SameSite=Lax`` + ``HttpOnly``; this token is the defense-in-depth layer.
"""

import secrets
from hmac import compare_digest

from flask import session, request, jsonify, current_app

_SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')


def get_csrf_token():
    """Return the session's CSRF token, creating one on first use."""
    token = session.get('csrf_token')
    if not token:
        token = secrets.token_hex(32)
        session['csrf_token'] = token
    return token


def validate_csrf():
    """Validate the CSRF token on state-changing requests.

    Returns a Flask error response (to be returned by the caller) when the token
    is missing or wrong, else ``None``. A no-op when ``CSRF_ENABLED`` is False
    (tests) or for safe HTTP methods.
    """
    if not current_app.config.get('CSRF_ENABLED', True):
        return None
    if request.method in _SAFE_METHODS:
        return None

    sent = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
    expected = session.get('csrf_token', '')
    if not expected or not sent or not compare_digest(str(sent), str(expected)):
        return jsonify({'success': False, 'message': 'توکن CSRF نامعتبر یا منقضی شده است. صفحه را تازه‌سازی کنید.'}), 403
    return None
