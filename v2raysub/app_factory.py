# -*- coding: utf-8 -*-
"""Flask application factory – creates and configures the app."""

from flask import Flask, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from database import init_db
from extensions import limiter
from routes.client import client_bp
from routes.admin_pages import admin_pages_bp
from routes.admin_api import admin_api_bp


def create_app(testing=False):
    """Create and return a fully configured Flask application."""
    app = Flask(__name__)
    if testing:
        app.config['TESTING'] = True
    app.secret_key = Config.SECRET_KEY
    app.config['PERMANENT_SESSION_LIFETIME'] = Config.PERMANENT_SESSION_LIFETIME

    # Session cookie hardening (SameSite=Lax blocks cross-site POSTs → CSRF mitigation)
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = Config.SESSION_COOKIE_SECURE

    # Behind Nginx: resolve real client IP / scheme from X-Forwarded-* headers
    # (rate limiting per real IP, correct https links in the admin panel)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # CSRF protection (disabled in tests so existing tests need not fetch a token).
    # The admin_api blueprint enforces it via a module-level before_request guard;
    # here we just expose the per-session token to templates.
    app.config['CSRF_ENABLED'] = not testing
    from utils.csrf import get_csrf_token

    @app.context_processor
    def _inject_csrf_token():
        return {'csrf_token': get_csrf_token()}

    # Rate limiting (disabled in tests so repeated logins don't hit the limit)
    app.config['RATELIMIT_ENABLED'] = not testing
    limiter.init_app(app)

    # Warn when rate limits are enforced but stored per-worker: with >1 gunicorn
    # worker the login brute-force cap is effectively multiplied and resets on
    # restart. Operators should set RATELIMIT_STORAGE_URI to a shared backend.
    if not testing:
        from extensions import RATELIMIT_STORAGE_URI
        if RATELIMIT_STORAGE_URI.startswith('memory://'):
            import logging
            logging.getLogger(__name__).warning(
                "Rate-limit storage is in-process (memory://); login limits are "
                "per-worker. Set RATELIMIT_STORAGE_URI to a shared backend "
                "(e.g. redis://127.0.0.1:6379) for a global limit across workers."
            )
    # Exempt from *default* limits only — explicit per-route limits
    # (e.g. the login route) still apply.
    limiter.exempt(admin_pages_bp)
    limiter.exempt(admin_api_bp)

    # Register blueprints
    app.register_blueprint(client_bp)
    app.register_blueprint(admin_pages_bp)
    app.register_blueprint(admin_api_bp)

    # Root route – redirect to admin panel
    @app.route('/')
    def index():
        return redirect(url_for('admin_pages.admin'))

    # Initialise database
    with app.app_context():
        init_db()

    # Start background scheduler for scanner automation (unless in testing mode)
    if not app.config.get('TESTING'):
        from services.scheduler import start_scheduler
        start_scheduler(app)

    return app
