# -*- coding: utf-8 -*-
"""Raw SQLite connection, schema init, and generic settings helpers."""

import sqlite3
import utils.constants as constants


def get_db():
    """Create and return a new database connection."""
    conn = sqlite3.connect(constants.DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables and run schema migrations."""
    db = get_db()

    db.execute('''
        CREATE TABLE IF NOT EXISTS configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_text TEXT NOT NULL,
            config_type TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active'
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS subscription_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address TEXT NOT NULL,
            user_agent TEXT,
            accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS subscription_paths (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL,
            is_primary INTEGER DEFAULT 0,
            is_enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Column migrations
    _add_column_if_missing(db, 'configs', 'sort_order', 'INTEGER DEFAULT 0')
    _add_column_if_missing(db, 'configs', 'is_enabled', 'INTEGER DEFAULT 1')
    _add_column_if_missing(db, 'subscription_logs', 'status', "TEXT NOT NULL DEFAULT 'SUCCESS'")
    _add_column_if_missing(db, 'subscription_logs', 'request_path', 'TEXT')

    # Ensure default subscription path exists
    paths_count = db.execute('SELECT COUNT(*) as count FROM subscription_paths').fetchone()['count']
    if paths_count == 0:
        db.execute("INSERT INTO subscription_paths (path, is_primary, is_enabled) VALUES ('freeconfigs', 1, 1)")

    # Ensure default output format setting
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('output_format', 'base64')")

    db.commit()
    db.close()


def _add_column_if_missing(db, table, column, col_type):
    """Safely add a column to a table if it doesn't exist."""
    try:
        db.execute(f'SELECT {column} FROM {table} LIMIT 1')
    except sqlite3.OperationalError:
        db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}')


def get_setting(key, default=''):
    """Retrieve a setting value by key."""
    db = get_db()
    result = db.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    db.close()
    return result['value'] if result else default


def set_setting(key, value):
    """Store a setting value."""
    db = get_db()
    db.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    db.commit()
    db.close()