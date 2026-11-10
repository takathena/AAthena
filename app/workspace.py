"""
AAguard IoT - Workspace (dashboard = ruang kerja)

Async FastAPI murni:

Satu sumber kebenaran untuk:
  - peran per dashboard (owner / editor / viewer) + admin yang selalu bebas,
  - lingkup data (scope) sebuah request: dashboard mana yang sedang dilihat,
  - penyimpanan token bot Telegram per dashboard (terenkripsi),
  - audit log aksi sensitif.

Aturan akses:
  owner  : pemilik dashboard (dashboards.user_id). Boleh semuanya, termasuk
           mengatur anggota, Telegram, dan menghapus dashboard.
  editor : anggota. Boleh menambah/ubah/hapus perangkat, widget, tab, kartu.
  viewer : anggota. Hanya melihat.
  admin  : (users.is_admin) diperlakukan sebagai owner di semua dashboard.

DB lewat `get_db_async()` (aiosqlite), dengan PRAGMA yang sama seperti
`get_db_context` sync di app/database.py: WAL + busy_timeout=30000
(plus synchronous NORMAL, foreign_keys ON, temp_store MEMORY,
cache_size -64000).
"""
import base64
import hashlib
import logging
import os
from contextlib import asynccontextmanager

import aiosqlite

logger = logging.getLogger('aaguard')

ROLE_RANK = {'viewer': 1, 'editor': 2, 'owner': 3}
MEMBER_ROLES = ('viewer', 'editor')


# ==========================================
# DB ASYNC (aiosqlite, PRAGMA sama dengan app/database.py)
# ==========================================
def _db_path():
    from app.config import Config
    return Config.DB_PATH


async def _configure_async_conn(conn):
    conn.row_factory = aiosqlite.Row
    await conn.execute('PRAGMA journal_mode=WAL')
    await conn.execute('PRAGMA synchronous=NORMAL')
    await conn.execute('PRAGMA foreign_keys=ON')
    await conn.execute('PRAGMA busy_timeout=30000')
    await conn.execute('PRAGMA temp_store=MEMORY')
    await conn.execute('PRAGMA cache_size=-64000')
    return conn


@asynccontextmanager
async def get_db_async():
    """Pengganti `get_db_context` sync berbasis aiosqlite."""
    db_path = _db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = await aiosqlite.connect(
        db_path, timeout=30.0, isolation_level='DEFERRED')
    await _configure_async_conn(conn)
    try:
        yield conn
    finally:
        await conn.close()


async def _one(conn, sql, params=()):
    return await (await conn.execute(sql, params)).fetchone()


async def _all(conn, sql, params=()):
    return await (await conn.execute(sql, params)).fetchall()


async def _exec(conn, sql, params=()):
    return await conn.execute(sql, params)


# ==========================================
# USER / ADMIN
# ==========================================
async def is_admin_user(conn, user_id):
    if not user_id:
        return False
    row = await _one(
        conn, 'SELECT is_admin FROM users WHERE id = ?', (user_id,))
    return bool(row and row['is_admin'])


# ==========================================
# PERAN
# ==========================================
async def get_dashboard_role(conn, dashboard_id, user_id):
    """Return 'owner' | 'editor' | 'viewer' | None."""
    if not user_id or dashboard_id is None:
        return 'owner' if (user_id and await is_admin_user(conn, user_id)) else None
    if await is_admin_user(conn, user_id):
        return 'owner'
    row = await _one(
        conn, 'SELECT user_id FROM dashboards WHERE id = ?', (dashboard_id,))
    if not row:
        return None
    if row['user_id'] == user_id:
        return 'owner'
    m = await _one(
        conn,
        'SELECT role FROM dashboard_members WHERE dashboard_id = ? AND user_id = ?',
        (dashboard_id, user_id),
    )
    return m['role'] if m else None


def role_allows(role, minimum):
    return bool(role) and ROLE_RANK.get(role, 0) >= ROLE_RANK[minimum]


async def accessible_dashboard_ids(conn, user_id, minimum='viewer'):
    """Daftar id dashboard yang boleh diakses dengan peran minimal.

    Return None bila admin (artinya: semua dashboard, termasuk perangkat
    yang belum punya dashboard).
    """
    if await is_admin_user(conn, user_id):
        return None
    ids = set()
    for r in await _all(
            conn, 'SELECT id FROM dashboards WHERE user_id = ?', (user_id,)):
        ids.add(r['id'])
    for r in await _all(
            conn,
            'SELECT dashboard_id, role FROM dashboard_members WHERE user_id = ?',
            (user_id,)):
        if role_allows(r['role'], minimum):
            ids.add(r['dashboard_id'])
    return sorted(ids)


# ==========================================
# SCOPE REQUEST
# ==========================================
def dashboard_in_sql(scope, column='dashboard_id'):
    """Potongan SQL: `<column> IN (...)` untuk kolom yang berisi dashboard id."""
    ids = scope['dashboard_ids']
    if ids is None:
        return '1=1', []
    if not ids:
        return '0=1', []
    return f"{column} IN ({','.join('?' * len(ids))})", list(ids)


def device_in_sql(scope, column='device_id'):
    """Potongan SQL: `<column> IN (perangkat dalam scope)` untuk kolom device_id."""
    ids = scope['dashboard_ids']
    if ids is None:
        return '1=1', []
    if not ids:
        return '0=1', []
    ph = ','.join('?' * len(ids))
    return (f"{column} IN (SELECT device_id FROM devices WHERE dashboard_id IN ({ph}))",
            list(ids))


async def resolve_scope(conn, request, user_id, minimum='viewer'):
    """Cermin deps.resolve_scope berbasis aiosqlite.

    Header/query diambil dari Request FastAPI. Return dict scope
    {'user_id', 'is_admin', 'dashboard_ids', 'dashboard_id', 'error'}.
    """
    raw = request.headers.get('x-dashboard-id') or request.query_params.get('dashboard_id')
    raw = (raw or '').strip().lower()
    admin = await is_admin_user(conn, user_id)
    scope = {'user_id': user_id, 'is_admin': admin,
             'dashboard_ids': None, 'dashboard_id': None, 'error': None}
    if raw in ('', 'all', 'null', 'undefined', '0'):
        scope['dashboard_ids'] = await accessible_dashboard_ids(conn, user_id, minimum)
        return scope
    try:
        did = int(raw)
    except (TypeError, ValueError):
        scope['error'] = ('dashboard_id tidak valid', 400)
        return scope
    role = await get_dashboard_role(conn, did, user_id)
    if role is None:
        scope['error'] = ('Dashboard tidak ditemukan', 404)
        return scope
    if not role_allows(role, minimum):
        scope['error'] = ('Peran Anda di dashboard ini tidak cukup untuk aksi tersebut', 403)
        return scope
    scope['dashboard_ids'] = [did]
    scope['dashboard_id'] = did
    return scope


# ==========================================
# AKSES PER PERANGKAT / KARTU
# ==========================================
async def device_allowed(conn, scope, device_id):
    """True bila perangkat termasuk dalam scope request (dashboard terpilih / yang boleh diakses)."""
    ids = scope['dashboard_ids']
    if ids is None:
        return True
    if not ids:
        return False
    row = await _one(
        conn,
        f"SELECT 1 FROM devices WHERE device_id = ? AND dashboard_id IN ({','.join('?' * len(ids))})",
        [device_id] + list(ids),
    )
    return row is not None


async def device_role(conn, device_row, user_id):
    """Peran user pada dashboard pemilik perangkat. Perangkat tanpa dashboard = admin saja."""
    if device_row['dashboard_id'] is None:
        return 'owner' if await is_admin_user(conn, user_id) else None
    return await get_dashboard_role(conn, device_row['dashboard_id'], user_id)


# ==========================================
# TOKEN TELEGRAM (terenkripsi)
# ==========================================
_ENC_PREFIX = 'enc:v1:'


def _fernet():
    from cryptography.fernet import Fernet
    from app.config import get_config
    config = get_config()
    secret = getattr(config, 'TELEGRAM_TOKEN_KEY', None) or config.SECRET_KEY
    if not secret:
        raise RuntimeError('SECRET_KEY / TELEGRAM_TOKEN_KEY belum di-set')
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode('utf-8')).digest())
    return Fernet(key)


def encrypt_token(plain):
    return _ENC_PREFIX + _fernet().encrypt(plain.encode('utf-8')).decode('ascii')


def decrypt_token(stored):
    if not stored:
        return ''
    if not stored.startswith(_ENC_PREFIX):
        return stored
    from cryptography.fernet import InvalidToken
    try:
        return _fernet().decrypt(stored[len(_ENC_PREFIX):].encode('ascii')).decode('utf-8')
    except InvalidToken:
        logger.error('Token Telegram tidak bisa didekripsi (SECRET_KEY berubah?)')
        return ''


def mask_token(plain):
    if not plain:
        return ''
    return '••••' + plain[-4:] if len(plain) > 4 else '••••'


async def get_dashboard_telegram(conn, dashboard_id):
    """Konfigurasi Telegram dashboard (token sudah didekripsi) atau None."""
    row = await _one(
        conn,
        'SELECT dashboard_id, bot_token_enc, chat_id, enabled FROM dashboard_telegram '
        'WHERE dashboard_id = ?',
        (dashboard_id,),
    )
    if not row:
        return None
    return {
        'dashboard_id': row['dashboard_id'],
        'token': decrypt_token(row['bot_token_enc']),
        'chat_id': row['chat_id'] or '',
        'enabled': bool(row['enabled']),
    }
