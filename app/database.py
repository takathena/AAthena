"""
NEXUS IoT - Database Layer (connection)
Schema version 19: multi-user + multi-dashboard (workspace) + analytics tabs + login_failures + audit_log.
Logika migrasi ada di app/migrations.py; modul ini hanya koneksi + init runner.
Native async FastAPI: get_db_context() async via aiosqlite (WAL), init_db() untuk lifespan.
"""
import asyncio
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import aiosqlite

WIB = timezone(timedelta(hours=7))


def get_wib_time():
    """Return current WIB time as NAIVE datetime."""
    return datetime.now(WIB).replace(tzinfo=None)


def _configure_sync_connection(conn):
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=30000')
    conn.execute('PRAGMA temp_store=MEMORY')
    conn.execute('PRAGMA cache_size=-64000')
    return conn


async def _configure_async_connection(conn):
    conn.row_factory = aiosqlite.Row
    await conn.execute('PRAGMA journal_mode=WAL')
    await conn.execute('PRAGMA synchronous=NORMAL')
    await conn.execute('PRAGMA foreign_keys=ON')
    await conn.execute('PRAGMA busy_timeout=30000')
    await conn.execute('PRAGMA temp_store=MEMORY')
    await conn.execute('PRAGMA cache_size=-64000')
    return conn


def _get_db_path():
    from app.config import Config
    return Config.DB_PATH


class _DBContext:
    """Dual context manager: `async with` (aiosqlite) dan `with` (sqlite3 legacy).

    Jalur async adalah jalur utama FastAPI; jalur sync dipertahankan agar
    caller lama yang masih sync (alerts, routers, tests lama) tetap jalan.
    """

    def __init__(self):
        self._async_conn = None
        self._sync_conn = None

    def _sync_open(self):
        db_path = _get_db_path()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(
            db_path,
            timeout=30.0,
            check_same_thread=False,
            isolation_level='DEFERRED',
        )
        return _configure_sync_connection(conn)

    async def _async_open(self):
        db_path = _get_db_path()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = await aiosqlite.connect(db_path, timeout=30.0, isolation_level='DEFERRED')
        return await _configure_async_connection(conn)

    def __enter__(self):
        self._sync_conn = self._sync_open()
        return self._sync_conn

    def __exit__(self, exc_type, exc, tb):
        if self._sync_conn is not None:
            self._sync_conn.close()
            self._sync_conn = None
        return False

    async def __aenter__(self):
        self._async_conn = await self._async_open()
        return self._async_conn

    async def __aexit__(self, exc_type, exc, tb):
        if self._async_conn is not None:
            await self._async_conn.close()
            self._async_conn = None
        return False


def get_db_context():
    """Context manager koneksi DB. Gunakan `async with` di kode async."""
    return _DBContext()


def get_db():
    """Kompatibilitas tes/FastAPI lama: return koneksi sync (untuk teardown)."""
    return None


def close_db(error=None):
    """Kompatibilitas conftest/tests: no-op (async CM menutup per call)."""
    return None


SCHEMA_VERSION = 20

# Re-export dari migrasi untuk kompatibilitas import lama.
from app.migrations import MIGRATIONS, WIB_DEFAULT  # noqa: E402, F401
# Re-export fungsi migrasi agar `from app.database import _migrate_*` tetap jalan.
from app.migrations import (  # noqa: E402, F401
    _migrate_v1, _migrate_v2, _migrate_v3, _migrate_v4, _migrate_v5,
    _migrate_v6, _migrate_v7, _migrate_v8, _migrate_v9, _migrate_v10,
    _migrate_v11, _migrate_v12, _migrate_v13, _migrate_v14, _migrate_v15,
    _migrate_v16, _migrate_v17, _migrate_v18, _migrate_v19, _rebuild_fk_tables,
)


async def _init_db_async():
    """Init DB dengan retry loop — aman untuk multi-worker."""
    from app.utils import process_lock

    max_wait = 60
    start = asyncio.get_running_loop().time()

    while True:
        async with process_lock('db-init', blocking=False) as got_lock:
            if got_lock:
                await asyncio.to_thread(_init_db_inner)
                return

        loop = asyncio.get_running_loop()
        elapsed = loop.time() - start
        if elapsed > max_wait:
            raise RuntimeError(
                f"DB init timeout after {max_wait}s — worker lain stuck?"
            )
        await asyncio.sleep(1)


def init_db():
    """Init DB untuk lifespan FastAPI.

    - Di dalam event loop (lifespan): `await init_db()`
    - Di luar event loop (thread sync / script): `init_db()` langsung jalan.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_init_db_async())
    return _init_db_async()


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
