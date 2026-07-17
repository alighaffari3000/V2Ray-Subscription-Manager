# -*- coding: utf-8 -*-
"""Raw SQLite connection, schema init, and generic settings helpers."""

import sqlite3
import utils.constants as constants


def get_db():
    """Create and return a new database connection."""
    # timeout: wait instead of failing with "database is locked" when another
    # worker/thread is writing; WAL: readers don't block the writer.
    conn = sqlite3.connect(constants.DATABASE, timeout=15)
    conn.execute('PRAGMA journal_mode=WAL')
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

    db.execute('''
        CREATE TABLE IF NOT EXISTS auto_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            priority INTEGER DEFAULT 100,
            is_enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_scan TIMESTAMP,
            last_success TIMESTAMP,
            last_error TEXT,
            failure_count INTEGER DEFAULT 0
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS scan_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_type TEXT NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMP,
            duration_ms INTEGER,
            discovered_count INTEGER DEFAULT 0,
            added_count INTEGER DEFAULT 0,
            disabled_count INTEGER DEFAULT 0,
            deleted_count INTEGER DEFAULT 0,
            status TEXT NOT NULL,
            error_message TEXT,
            worker_version TEXT,
            engine_version TEXT
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS config_health_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_id INTEGER,
            scan_id INTEGER,
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reachable INTEGER,
            latency INTEGER,
            validation TEXT,
            error_message TEXT,
            FOREIGN KEY(config_id) REFERENCES configs(id),
            FOREIGN KEY(scan_id) REFERENCES scan_history(id)
        )
    ''')

    # Column migrations
    _add_column_if_missing(db, 'configs', 'sort_order', 'INTEGER DEFAULT 0')
    _add_column_if_missing(db, 'configs', 'is_enabled', 'INTEGER DEFAULT 1')
    _add_column_if_missing(db, 'configs', 'source', 'TEXT')
    _add_column_if_missing(db, 'configs', 'mode', "TEXT DEFAULT 'manual'")
    _add_column_if_missing(db, 'configs', 'last_check', 'TIMESTAMP')
    _add_column_if_missing(db, 'configs', 'last_success', 'TIMESTAMP')
    _add_column_if_missing(db, 'configs', 'latency', 'INTEGER')
    _add_column_if_missing(db, 'configs', 'consecutive_failures', 'INTEGER DEFAULT 0')
    _add_column_if_missing(db, 'configs', 'health_status', "TEXT DEFAULT 'unknown'")
    _add_column_if_missing(db, 'subscription_logs', 'status', "TEXT NOT NULL DEFAULT 'SUCCESS'")
    _add_column_if_missing(db, 'subscription_logs', 'request_path', 'TEXT')
    
    _add_column_if_missing(db, 'scan_history', 'job_id', 'TEXT')
    _add_column_if_missing(db, 'scan_history', 'total_sources', 'INTEGER DEFAULT 0')
    _add_column_if_missing(db, 'scan_history', 'successful_sources', 'INTEGER DEFAULT 0')
    _add_column_if_missing(db, 'scan_history', 'failed_sources', 'INTEGER DEFAULT 0')
    _add_column_if_missing(db, 'scan_history', 'discovered_configs', 'INTEGER DEFAULT 0')
    _add_column_if_missing(db, 'scan_history', 'working_configs', 'INTEGER DEFAULT 0')
    _add_column_if_missing(db, 'scan_history', 'imported_configs', 'INTEGER DEFAULT 0')
    _add_column_if_missing(db, 'scan_history', 'disabled_configs', 'INTEGER DEFAULT 0')
    _add_column_if_missing(db, 'scan_history', 'deleted_configs', 'INTEGER DEFAULT 0')
    _add_column_if_missing(db, 'scan_history', 'duplicate_configs', 'INTEGER DEFAULT 0')
    _add_column_if_missing(db, 'scan_history', 'scan_duration_ms', 'INTEGER DEFAULT 0')

    # Ensure default subscription path exists
    paths_count = db.execute('SELECT COUNT(*) as count FROM subscription_paths').fetchone()['count']
    if paths_count == 0:
        db.execute("INSERT INTO subscription_paths (path, is_primary, is_enabled) VALUES ('freeconfigs', 1, 1)")

    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('output_format', 'base64')")
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('scan_interval', '300')")
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('health_check_interval', '600')")
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('max_active_configs', '100')")
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('max_new_configs_per_scan', '10')")
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('failure_threshold', '2')")
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('cleanup_policy', 'disable')")
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('fetch_concurrency', '4')")
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('probe_concurrency', '10')")
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('probe_process_concurrency', '2')")

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