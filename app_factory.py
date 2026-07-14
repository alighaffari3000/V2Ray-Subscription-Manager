# -*- coding: utf-8 -*-
"""Flask application factory – creates and configures the app."""

from flask import Flask, redirect, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import Config
from database import init_db
from routes.client import client_bp
from routes.admin_pages import admin_pages_bp
from routes.admin_api import admin_api_bp


def create_app():
    """Create and return a fully configured Flask application."""
    app = Flask(__name__)
    app.secret_key = Config.SECRET_KEY
    app.config['PERMANENT_SESSION_LIFETIME'] = Config.PERMANENT_SESSION_LIFETIME

    # Rate limiting
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["200 per day", "50 per hour"],
        storage_uri="memory://"
    )
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

    return app