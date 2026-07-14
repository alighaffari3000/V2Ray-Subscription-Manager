#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entry point – simply creates the app, initializes database, and runs it."""

from app_factory import create_app
from database import init_db

app = create_app()

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=False)