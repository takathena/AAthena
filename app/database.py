"""
NEXUS IoT - Database Layer (connection)
Schema version 18: multi-user + multi-dashboard (workspace) + analytics tabs + login_failures + audit_log.
Logika migrasi ada di app/migrations.py; modul ini hanya koneksi + init runner.
"""
import os
import sqlite3
from contextlib import contextmanager
from flask import g
from datetime import datetime, timedelta, timezone

WIB = timezone(timedelta(hours=7))


def get_wib_time():
    """Return current WIB time as NAIVE datetime."""
    return datetime.now(WIB).replace(tzinfo=None)


def _configure_connection(conn):
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=30000')
    conn.execute('PRAGMA temp_store=MEMORY')
    conn.execute('PRAGMA cache_size=-64000')
    return conn


def _get_db_path():
    from app.config import Config
    return Config.DB_PATH


def get_db():
    if 'db' not in g:
        db_path = _get_db_path()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        g.db = sqlite3.connect(
            db_path,
            timeout=30.0,
            check_same_thread=False,
            isolation_level='DEFERRED',
        )
        _configure_connection(g.db)
    return g.db


def close_db(error=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


@contextmanager
def get_db_context():
    db_path = _get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(
        db_path,
        timeout=30.0,
        check_same_thread=False,
        isolation_level='DEFERRED',
    )
    _configure_connection(conn)
    try:
        yield conn
    finally:
        conn.close()


SCHEMA_VERSION = 18

# Re-export dari migrasi untuk kompatibilitas import lama.
from app.migrations import MIGRATIONS, WIB_DEFAULT  # noqa: E402
# Re-export fungsi migrasi agar `from app.database import _migrate_*` tetap jalan.
from app.migrations import (  # noqa: E402
    _migrate_v1, _migrate_v2, _migrate_v3, _migrate_v4, _migrate_v5,
    _migrate_v6, _migrate_v7, _migrate_v8, _migrate_v9, _migrate_v10,
    _migrate_v11, _migrate_v12, _migrate_v13, _migrate_v14, _migrate_v15,
    _migrate_v16, _migrate_v17, _migrate_v18, _rebuild_fk_tables,
)


def init_db():
    """Init DB dengan retry loop — aman untuk multi-worker Gunicorn."""
    import time
    from app.utils import process_lock

    max_wait = 60
    start = time.time()

    while True:
        with process_lock('db-init', blocking=False) as got_lock:
            if got_lock:
                _init_db_inner()
                return

        elapsed = time.time() - start
        if elapsed > max_wait:
            raise RuntimeError(
                f"DB init timeout after {max_wait}s — worker lain stuck?"
            )
        time.sleep(1)


def _init_db_inner():
    with get_db_context() as conn:
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at DATETIME DEFAULT (datetime('now', '+7 hours'))
            )
        ''')

        row = cursor.execute('SELECT MAX(version) FROM schema_version').fetchone()
        current_version = row[0] if row and row[0] else 0

        print(f"[DB] Current schema version: {current_version}")

        for version, migrate_fn in MIGRATIONS:
            if current_version < version:
                migrate_fn(cursor)
                cursor.execute('INSERT INTO schema_version (version) VALUES (?)', (version,))
                conn.commit()
                print(f"[DB] Applied migration v{version}")

        conn.commit()
        print(f"[DB] Database initialized! (version {SCHEMA_VERSION})")
