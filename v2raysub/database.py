# -*- coding: utf-8 -*-
"""Raw SQLite connection, schema init, and generic settings helpers."""

import sqlite3
import uuid
from contextlib import contextmanager
import utils.constants as constants


def get_db():
    """Create and return a new database connection."""
    # timeout: wait instead of failing with "database is locked" when another
    # worker/thread is writing; WAL: readers don't block the writer.
    conn = sqlite3.connect(constants.DATABASE, timeout=15)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_session():
    """Yield a DB connection and guarantee it is closed, even on exception.

    Prefer this over ``get_db()`` + manual ``close()``: a raised error (e.g.
    "database is locked") between open and close would otherwise leak the
    connection and its WAL lock until garbage collection.
    """
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()


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
        CREATE TABLE IF NOT EXISTS backup_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            operation TEXT NOT NULL,
            user TEXT,
            status TEXT NOT NULL,
            duration REAL,
            backup_size INTEGER,
            error_message TEXT,
            delivery_status TEXT,
            checksum TEXT
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT UNIQUE,
            name TEXT NOT NULL,
            path TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            duration_days INTEGER NOT NULL DEFAULT 30,
            activated_at TIMESTAMP,
            expire_at TIMESTAMP,
            paused_at TIMESTAMP,
            note TEXT,
            max_devices INTEGER DEFAULT 1,
            last_seen TIMESTAMP,
            last_user_agent TEXT,
            last_ip TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        CREATE TABLE IF NOT EXISTS user_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fingerprint TEXT NOT NULL,
            first_seen TIMESTAMP NOT NULL,
            last_seen TIMESTAMP NOT NULL,
            network TEXT,
            last_ip TEXT,
            user_agent TEXT,
            hits INTEGER DEFAULT 0,
            UNIQUE(user_id, fingerprint)
        )
    ''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_user_devices_user ON user_devices(user_id, last_seen)')

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

    # Migrate legacy shared paths into unlimited (deletable) users, then drop the
    # subscription_paths rows so the "public link" concept no longer exists and a
    # deleted user can't be resurrected by the row. Fresh installs seed nothing,
    # so a new panel starts with no links until the admin creates a user.
    for row in db.execute('SELECT path, is_primary FROM subscription_paths').fetchall():
        exists = db.execute('SELECT 1 FROM users WHERE path = ?', (row['path'],)).fetchone()
        if not exists:
            name = 'لینک عمومی' if row['is_primary'] else row['path']
            db.execute(
                "INSERT INTO users (uuid, name, path, status, duration_days, activated_at, note) "
                "VALUES (?, ?, ?, 'ACTIVE', 0, CURRENT_TIMESTAMP, 'مهاجرت‌شده از لینک عمومی')",
                (uuid.uuid4().hex, name, row['path'])
            )
        db.execute('DELETE FROM subscription_paths WHERE path = ?', (row['path'],))

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
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('scan_timeout', '1200')")

    # Device-limit knobs: how long a device slot stays "active" (rolling window),
    # and an optional grace window after activation during which the cap is not
    # enforced. See DEVICE_LIMIT_ROADMAP.md and services/user_service.py.
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('device_window_days', '7')")
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('device_grace_hours', '0')")

    # Seed backup configurations
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('backup_scheduled_enabled', '0')")
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('backup_interval', 'daily')")
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('backup_retention_max', '30')")
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('backup_telegram_enabled', '0')")
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('backup_telegram_bot_token', '')")
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('backup_telegram_chat_id', '')")
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('backup_telegram_api_server', 'https://api.telegram.org')")

    # Retention: drop subscription access logs older than this many days (0 = keep
    # forever). subscription_logs grows one row per hit and was unbounded before.
    db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('logs_retention_days', '90')")

    # Indexes for the hot query paths. subscription_logs is scanned by
    # request_path (per-user history) and by accessed_at (dashboard "today"
    # counters and retention pruning); configs is filtered by status/enabled.
    db.execute("CREATE INDEX IF NOT EXISTS idx_sublogs_request_path ON subscription_logs(request_path)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_sublogs_accessed_at ON subscription_logs(accessed_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_sublogs_status ON subscription_logs(status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_configs_status_enabled ON configs(status, is_enabled)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_users_path ON users(path)")

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
    with db_session() as db:
        result = db.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    return result['value'] if result else default


def set_setting(key, value):
    """Store a setting value."""
    with db_session() as db:
        db.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        db.commit()