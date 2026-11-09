"""NEXUS IoT - FastAPI dependencies (auth, scope workspace, throttle).

Mencerminkan app/auth.py + app/workspace.py untuk FastAPI:
- sesi dibaca dari request.session (SessionMiddleware starlette),
- idle-timeout sama, polling API tidak memperpanjang last_activity,
- scope dashboard dihitung tanpa Flask g/session agar bisa jalan di
  async endpoint; DB sync dijalankan di thread via asyncio.to_thread.
"""
import asyncio
import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_config

limiter = Limiter(key_func=get_remote_address)

ROLE_RANK = {'viewer': 1, 'editor': 2, 'owner': 3}

POLLING_PREFIXES = (
    '/api/v1/dashboard',
    '/api/v1/devices',
    '/api/v1/alerts',
    '/api/v1/dashboards',
    '/api/v1/widgets',
    '/api/v1/analytics-tabs',
    '/api/v1/system',
    '/api/v1/notifications',
    '/api/v1/metrics',
    '/api/v1/chat',
)


# ==========================================
# UTIL ASYNC
# ==========================================
async def run_sync(func, *args, **kwargs):
    """Jalankan helper sync sqlite3 di threadpool (risiko rendah, tetap async endpoint)."""
    return await asyncio.to_thread(func, *args, **kwargs)


async def safe_json(request: Request):
    """request.get_json(silent=True) ala Flask: body invalid/kosong -> None."""
    try:
        return await request.json()
    except Exception:
        return None


def client_ip(request: Request) -> str:
    """IP klien untuk audit/limit. shortcut: di belakang Nginx ambil X-Forwarded-For pertama."""
    forwarded = request.headers.get('x-forwarded-for') or ''
    if forwarded:
        return forwarded.split(',')[0].strip() or 'unknown'
    return (request.client.host if request.client else None) or 'unknown'


# ==========================================
# AUTH (dari app/auth.py)
# ==========================================
def is_api_polling_request(request: Request) -> bool:
    """Polling API tidak memperpanjang sesi -> idle timeout tetap bisa aktif."""
    if request.method.upper() != 'GET':
        return False
    path = request.url.path or ''
    if not path.startswith('/api/'):
        return False
    return path.startswith(POLLING_PREFIXES)


def _session_user(request: Request):
    """Return user_id atau raise HTTPException/redirect sesuai varian pemanggil."""
    return request.session.get('user_id')


def get_current_user(request: Request):
    """Varian API: 401 JSON bila belum login / idle expired."""
    session = request.session
    if 'logged_in' not in session:
        raise HTTPException(status_code=401,
                            detail={'success': False, 'error': 'Unauthorized'})
    config = get_config()
    idle_minutes = config.SESSION_IDLE_TIMEOUT_MINUTES
    now_ts = time.time()
    last_activity = session.get('last_activity')
    if last_activity and idle_minutes > 0:
        if now_ts - last_activity > idle_minutes * 60:
            session.clear()
            raise HTTPException(status_code=401, detail={
                'success': False,
                'error': 'Session expired (idle)',
                'code': 'SESSION_IDLE',
            })
    if not is_api_polling_request(request):
        session['last_activity'] = now_ts
    return {'user_id': session.get('user_id'),
            'username': session.get('username') or ''}


def get_current_user_html(request: Request):
    """Varian HTML: redirect ke /login bila belum login / idle expired."""
    session = request.session
    if 'logged_in' not in session:
        raise HTTPException(status_code=303, headers={'Location': '/login'})
    config = get_config()
    idle_minutes = config.SESSION_IDLE_TIMEOUT_MINUTES
    now_ts = time.time()
    last_activity = session.get('last_activity')
    if last_activity and idle_minutes > 0:
        if now_ts - last_activity > idle_minutes * 60:
            session.clear()
            raise HTTPException(status_code=303, headers={'Location': '/login'})
    if not is_api_polling_request(request):
        session['last_activity'] = now_ts
    return {'user_id': session.get('user_id'),
            'username': session.get('username') or ''}


def require_admin(request: Request):
    """Setelah get_current_user. Satu sumber kebenaran otorisasi admin."""
    user = get_current_user(request)
    if is_admin_sync(user['user_id']):
        return user
    raise HTTPException(status_code=403, detail={
        'success': False,
        'error': 'Hanya admin yang bisa mengakses fitur ini',
    })


def is_admin_sync(user_id) -> bool:
    from app.database import get_db_context
    if not user_id:
        return False
    with get_db_context() as conn:
        row = conn.execute(
            'SELECT is_admin FROM users WHERE id = ?', (user_id,)
        ).fetchone()
    return bool(row and row['is_admin'])


# ==========================================
# LOGIN THROTTLE HOOK (app/login_throttle.py)
# ==========================================
async def check_login_throttle(username: str, ip: str) -> int:
    import app.login_throttle as login_throttle
    return await run_sync(login_throttle.check_locked, username, ip)


async def record_login_failure(username: str, ip: str) -> None:
    import app.login_throttle as login_throttle
    await run_sync(login_throttle.record_failure, username, ip, get_config())


async def clear_login_failures(username: str, ip: str) -> None:
    import app.login_throttle as login_throttle
    await run_sync(login_throttle.clear_failures, username, ip)


def ensure_user_dashboard(user_id, username):
    from app.database import get_db_context
    with get_db_context() as conn:
        existing = conn.execute(
            '''SELECT id FROM dashboards
               WHERE user_id = ?
               ORDER BY is_default DESC, id ASC LIMIT 1''',
            (user_id,)
        ).fetchone()
        if existing:
            return existing['id']
        orphan = conn.execute(
            '''SELECT id FROM dashboards
               WHERE user_id IS NULL
               ORDER BY is_default DESC, id ASC LIMIT 1'''
        ).fetchone()
        if orphan:
            conn.execute(
                'UPDATE dashboards SET user_id = ? WHERE user_id IS NULL',
                (user_id,)
            )
            conn.commit()
            return orphan['id']
        slug = f"u{user_id}-default"
        cur = conn.execute('''
            INSERT INTO dashboards (slug, name, description, icon, is_default, user_id)
            VALUES (?, 'Dashboard Utama', 'Dashboard bawaan', 'fa-chart-pie', 1, ?)
        ''', (slug, user_id))
        conn.commit()
        return cur.lastrowid


def purge_dashboard(conn, dashboard_id):
    """Hapus dashboard beserta isinya (widget, tab, anggota, Telegram)."""
    conn.execute('DELETE FROM widgets WHERE dashboard_id = ?', (dashboard_id,))
    conn.execute('DELETE FROM analytics_tabs WHERE dashboard_id = ?', (dashboard_id,))
    conn.execute('DELETE FROM dashboard_members WHERE dashboard_id = ?', (dashboard_id,))
    conn.execute('DELETE FROM dashboard_telegram WHERE dashboard_id = ?', (dashboard_id,))
    conn.execute('DELETE FROM dashboards WHERE id = ?', (dashboard_id,))


# ==========================================
# WORKSPACE SCOPE (tanpa Flask g/session)
# ==========================================
def role_allows(role, minimum):
    return bool(role) and ROLE_RANK.get(role, 0) >= ROLE_RANK[minimum]


def get_dashboard_role(conn, dashboard_id, user_id):
    if not user_id or dashboard_id is None:
        return 'owner' if (user_id and is_admin_sync(user_id)) else None
    if is_admin_sync(user_id):
        return 'owner'
    row = conn.execute(
        'SELECT user_id FROM dashboards WHERE id = ?', (dashboard_id,)
    ).fetchone()
    if not row:
        return None
    if row['user_id'] == user_id:
        return 'owner'
    m = conn.execute(
        'SELECT role FROM dashboard_members WHERE dashboard_id = ? AND user_id = ?',
        (dashboard_id, user_id)
    ).fetchone()
    return m['role'] if m else None


def accessible_dashboard_ids(conn, user_id, minimum='viewer'):
    if is_admin_sync(user_id):
        return None
    ids = set()
    for r in conn.execute(
        'SELECT id FROM dashboards WHERE user_id = ?', (user_id,)
    ).fetchall():
        ids.add(r['id'])
    for r in conn.execute(
        'SELECT dashboard_id, role FROM dashboard_members WHERE user_id = ?', (user_id,)
    ).fetchall():
        if role_allows(r['role'], minimum):
            ids.add(r['dashboard_id'])
    return sorted(ids)


def resolve_scope(conn, request: Request, user_id, minimum='viewer'):
    """Cermin workspace.resolve_scope; header/query diambil dari Request."""
    raw = request.headers.get('x-dashboard-id') or request.query_params.get('dashboard_id')
    raw = (raw or '').strip().lower()
    admin = is_admin_sync(user_id)
    scope = {'user_id': user_id, 'is_admin': admin,
             'dashboard_ids': None, 'dashboard_id': None, 'error': None}
    if raw in ('', 'all', 'null', 'undefined', '0'):
        scope['dashboard_ids'] = accessible_dashboard_ids(conn, user_id, minimum)
        return scope
    try:
        did = int(raw)
    except (TypeError, ValueError):
        scope['error'] = ('dashboard_id tidak valid', 400)
        return scope
    role = get_dashboard_role(conn, did, user_id)
    if role is None:
        scope['error'] = ('Dashboard tidak ditemukan', 404)
        return scope
    if not role_allows(role, minimum):
        scope['error'] = ('Peran Anda di dashboard ini tidak cukup untuk aksi tersebut', 403)
        return scope
    scope['dashboard_ids'] = [did]
    scope['dashboard_id'] = did
    return scope


def scope_error_response(scope):
    msg, code = scope['error']
    return JSONResponse({'success': False, 'error': msg}, status_code=code)


def dashboard_in_sql(scope, column='dashboard_id'):
    ids = scope['dashboard_ids']
    if ids is None:
        return '1=1', []
    if not ids:
        return '0=1', []
    return f"{column} IN ({','.join('?' * len(ids))})", list(ids)


def device_in_sql(scope, column='device_id'):
    ids = scope['dashboard_ids']
    if ids is None:
        return '1=1', []
    if not ids:
        return '0=1', []
    ph = ','.join('?' * len(ids))
    return (f"{column} IN (SELECT device_id FROM devices WHERE dashboard_id IN ({ph}))",
            list(ids))


def device_role(conn, device_row, user_id):
    if device_row['dashboard_id'] is None:
        return 'owner' if is_admin_sync(user_id) else None
    return get_dashboard_role(conn, device_row['dashboard_id'], user_id)


def load_device(conn, request: Request, user_id, device_id, minimum='viewer', columns='*'):
    """Return (row, None) atau (None, JSONResponse denial)."""
    cols = columns if 'dashboard_id' in columns or columns == '*' else columns + ', dashboard_id'
    row = conn.execute(
        f'SELECT {cols} FROM devices WHERE device_id = ?', (device_id,)
    ).fetchone()
    if not row:
        return None, JSONResponse({'success': False, 'error': 'Device not found'}, status_code=404)
    role = device_role(conn, row, user_id)
    if role is None:
        return None, JSONResponse({'success': False, 'error': 'Device not found'}, status_code=404)
    if not role_allows(role, minimum):
        return None, JSONResponse(
            {'success': False, 'error': 'Anda tidak punya izin untuk mengubah perangkat ini'},
            status_code=403)
    return row, None


def pick_write_dashboard(conn, scope, requested_id=None, minimum='editor'):
    """Return (dashboard_id, None) atau (None, JSONResponse denial)."""
    user_id = scope['user_id']
    did = None
    if requested_id not in (None, '', 0, '0'):
        try:
            did = int(requested_id)
        except (ValueError, TypeError):
            return None, JSONResponse(
                {'success': False, 'error': 'dashboard_id tidak valid'}, status_code=400)
    elif scope['dashboard_id']:
        did = scope['dashboard_id']
    else:
        row = conn.execute(
            'SELECT id FROM dashboards WHERE user_id = ? '
            'ORDER BY is_default DESC, id ASC LIMIT 1', (user_id,)
        ).fetchone()
        did = row['id'] if row else None
    if did is None:
        if is_admin_sync(user_id):
            return None, None
        return None, JSONResponse(
            {'success': False, 'error': 'Anda belum punya dashboard yang boleh diubah'},
            status_code=403)
    exists = conn.execute('SELECT id FROM dashboards WHERE id = ?', (did,)).fetchone()
    if not exists:
        return None, JSONResponse(
            {'success': False, 'error': 'Dashboard tidak ditemukan'}, status_code=404)
    role = get_dashboard_role(conn, did, user_id)
    if role is None:
        return None, JSONResponse(
            {'success': False, 'error': 'Dashboard tidak ditemukan'}, status_code=404)
    if not role_allows(role, minimum):
        return None, JSONResponse(
            {'success': False,
             'error': 'Anda hanya boleh melihat dashboard ini (peran viewer)'},
            status_code=403)
    return did, None


def audit(conn, request: Request, user_id, username, action, detail=''):
    """Cermin workspace.audit dengan ip/username eksplisit (tanpa Flask session)."""
    try:
        from app.database import get_wib_time
        conn.execute(
            'INSERT INTO audit_log (user_id, username, action, detail, ip, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (user_id, username or '', action,
             str(detail)[:2000], client_ip(request) or '', get_wib_time())
        )
    except Exception:
        pass
