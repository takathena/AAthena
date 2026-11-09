"""NEXUS IoT - FastAPI dashboards/widgets/tabs (dari app/dashboards.py)."""
import json
import logging
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import get_config
from app.deps import (audit, get_current_user, get_dashboard_role, limiter,
                      role_allows, run_sync, safe_json)
from app.utils import safe_json_loads

logger = logging.getLogger('nexus')
router = APIRouter(prefix='/api/v1', tags=['dashboards'])

SLUG_RE = re.compile(r'^[a-z0-9\-]+$')
TOKEN_RE = re.compile(r'^\d{5,}:[A-Za-z0-9_-]{20,}$')
CHAT_ID_RE = re.compile(r'^(-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,63})$')
VALID_WIDGET_TYPES = {
    'line_chart', 'bar_chart', 'area_chart',
    'doughnut_chart', 'pie_chart', 'polar_area', 'radar_chart',
    'horizontal_bar', 'stacked_bar', 'stacked_area',
}

_LIST_SQL = '''
    SELECT d.id, d.slug, d.name, d.description, d.icon, d.user_id,
           d.created_at, d.updated_at,
           CASE WHEN d.user_id = :uid THEN d.is_default ELSE 0 END AS is_default,
           CASE WHEN d.user_id = :uid THEN 'owner' ELSE m.role END AS role,
           COALESCE(NULLIF(u.display_name, ''), u.username) AS owner_name,
           (SELECT COUNT(*) FROM widgets w WHERE w.dashboard_id = d.id) AS widget_count,
           (SELECT COUNT(*) FROM devices dv WHERE dv.dashboard_id = d.id) AS device_count,
           (SELECT COUNT(*) FROM dashboard_members dm WHERE dm.dashboard_id = d.id) AS member_count
    FROM dashboards d
    LEFT JOIN users u ON u.id = d.user_id
    LEFT JOIN dashboard_members m ON m.dashboard_id = d.id AND m.user_id = :uid
    WHERE d.user_id = :uid OR m.user_id = :uid
    ORDER BY (d.user_id = :uid) DESC, is_default DESC, d.created_at ASC
'''


def _validate_slug(slug):
    return bool(slug) and SLUG_RE.match(slug) and len(slug) <= 64


def _forbidden(msg='Anda tidak punya izin untuk aksi ini'):
    return JSONResponse({'success': False, 'error': msg}, status_code=403)


def _check_dashboard(conn, dashboard_id, user_id, minimum='viewer'):
    role = get_dashboard_role(conn, dashboard_id, user_id)
    if role is None:
        return JSONResponse({'success': False, 'error': 'Dashboard not found'}, status_code=404)
    if not role_allows(role, minimum):
        return _forbidden('Peran Anda di dashboard ini tidak cukup untuk aksi tersebut')
    return None


def _check_widget(conn, widget_id, user_id, minimum='editor'):
    row = conn.execute('SELECT dashboard_id FROM widgets WHERE id = ?', (widget_id,)).fetchone()
    if not row:
        return JSONResponse({'success': False, 'error': 'Widget not found'}, status_code=404)
    return _check_dashboard(conn, row['dashboard_id'], user_id, minimum)


def _check_tab(conn, tab_id, user_id, minimum='editor'):
    row = conn.execute('SELECT dashboard_id FROM analytics_tabs WHERE id = ?', (tab_id,)).fetchone()
    if not row:
        return JSONResponse({'success': False, 'error': 'Tab not found'}, status_code=404)
    return _check_dashboard(conn, row['dashboard_id'], user_id, minimum)


def _device_visible(conn, device_id, user_id):
    if not device_id:
        return True
    row = conn.execute('SELECT dashboard_id FROM devices WHERE device_id = ?', (device_id,)).fetchone()
    if not row:
        return False
    from app.deps import device_role
    return device_role(conn, row, user_id) is not None


def _find_dashboard_by_slug(conn, slug, user_id):
    rows = conn.execute(
        'SELECT * FROM dashboards WHERE slug = ? ORDER BY (user_id = ?) DESC, id ASC',
        (slug, user_id)).fetchall()
    for r in rows:
        if get_dashboard_role(conn, r['id'], user_id):
            return r
    return None


def _widgets_of(conn, dashboard_id):
    rows = conn.execute(
        'SELECT * FROM widgets WHERE dashboard_id = ? ORDER BY grid_y ASC, grid_x ASC',
        (dashboard_id,)).fetchall()
    out = []
    for w in rows:
        wd = dict(w)
        wd['config'] = safe_json_loads(wd['config'])
        out.append(wd)
    return out


def _telegram_payload(conn, dashboard_id):
    from app import workspace as ws
    cfg = ws.get_dashboard_telegram(conn, dashboard_id)
    config = get_config()
    fallback = bool(config.NOTIFY_ENABLED and config.TELEGRAM_ENABLED
                    and config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)
    return {
        'configured': bool(cfg and cfg['token'] and cfg['chat_id']),
        'enabled': bool(cfg and cfg['enabled']),
        'token_masked': ws.mask_token(cfg['token']) if cfg else '',
        'chat_id': cfg['chat_id'] if cfg else '',
        'default_bot_available': fallback,
    }


def _purge_dashboard(conn, dashboard_id):
    conn.execute('DELETE FROM widgets WHERE dashboard_id = ?', (dashboard_id,))
    conn.execute('DELETE FROM analytics_tabs WHERE dashboard_id = ?', (dashboard_id,))
    conn.execute('DELETE FROM dashboard_members WHERE dashboard_id = ?', (dashboard_id,))
    conn.execute('DELETE FROM dashboard_telegram WHERE dashboard_id = ?', (dashboard_id,))
    conn.execute('DELETE FROM dashboards WHERE id = ?', (dashboard_id,))


# ==========================================
# DASHBOARDS
# ==========================================
@router.get('/dashboards')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def list_dashboards(request: Request):
    from app.database import get_db_context
    user = get_current_user(request)
    user_id, username = user['user_id'], user['username']

    def _do():
        with get_db_context() as conn:
            rows = conn.execute(_LIST_SQL, {'uid': user_id}).fetchall()
        if not rows:
            try:
                from app.deps import ensure_user_dashboard
                ensure_user_dashboard(user_id, username)
                with get_db_context() as conn:
                    rows = conn.execute(_LIST_SQL, {'uid': user_id}).fetchall()
            except Exception as e:
                logger.error(f'Auto-create dashboard failed: {e}')
        return [dict(r) for r in rows]

    rows = await run_sync(_do)
    return JSONResponse({'success': True, 'dashboards': rows})


@router.post('/dashboards')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def create_dashboard(request: Request):
    from app.database import get_db_context, get_wib_time
    user = get_current_user(request)
    user_id = user['user_id']
    data = await safe_json(request) or {}
    name = (data.get('name') or '').strip()
    slug_input = (data.get('slug') or '').strip().lower().replace(' ', '-')
    if not name:
        return JSONResponse({'success': False, 'error': 'Nama dashboard wajib diisi'}, status_code=400)
    if slug_input and not _validate_slug(slug_input):
        return JSONResponse({'success': False, 'error': 'Slug hanya huruf kecil, angka, dan dash'}, status_code=400)
    if not slug_input:
        slug_input = re.sub(r'[^a-z0-9\-]+', '-', name.lower()).strip('-') or 'dashboard'
    slug_input = slug_input[:60]

    def _find_free():
        with get_db_context() as conn:
            s = slug_input
            base, i = s, 2
            while conn.execute('SELECT 1 FROM dashboards WHERE slug = ?', (s,)).fetchone():
                s = f'{base}-{i}'
                i += 1
            return s
    slug_final = await run_sync(_find_free)

    def _insert():
        with get_db_context() as conn:
            cur = conn.execute(
                'INSERT INTO dashboards (slug, name, description, icon, is_default, user_id, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, 0, ?, ?, ?)',
                (slug_final, name, data.get('description', ''),
                 data.get('icon', 'fa-chart-line'), user_id,
                 get_wib_time(), get_wib_time()))
            conn.commit()
            return cur.lastrowid

    new_id = await run_sync(_insert)
    logger.info(f'Dashboard created: id={new_id} user={user_id} slug={slug_final}')
    return JSONResponse({'success': True, 'id': new_id, 'slug': slug_final}, status_code=201)


@router.get('/dashboards/{dashboard_id}')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_dashboard_detail(dashboard_id: int, request: Request):
    from app.database import get_db_context
    user = get_current_user(request)

    def _do():
        with get_db_context() as conn:
            denied = _check_dashboard(conn, dashboard_id, user['user_id'], 'viewer')
            if denied:
                return denied, None, None
            dash = dict(conn.execute('SELECT * FROM dashboards WHERE id = ?', (dashboard_id,)).fetchone())
            dash['role'] = get_dashboard_role(conn, dashboard_id, user['user_id'])
            return None, dash, _widgets_of(conn, dashboard_id)

    denied, dash, widgets = await run_sync(_do)
    if denied:
        return denied
    return JSONResponse({'success': True, 'dashboard': dash, 'widgets': widgets})


@router.get('/dashboards/slug/{slug}')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_dashboard_by_slug(slug: str, request: Request):
    from app.database import get_db_context
    user = get_current_user(request)

    def _do():
        with get_db_context() as conn:
            dash = _find_dashboard_by_slug(conn, slug, user['user_id'])
            if not dash:
                return JSONResponse({'success': False, 'error': 'Dashboard not found'}, status_code=404), None, None
            d = dict(dash)
            d['role'] = get_dashboard_role(conn, dash['id'], user['user_id'])
            return None, d, _widgets_of(conn, dash['id'])

    denied, d, widgets = await run_sync(_do)
    if denied:
        return denied
    return JSONResponse({'success': True, 'dashboard': d, 'widgets': widgets})


@router.put('/dashboards/{dashboard_id}')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def update_dashboard(dashboard_id: int, request: Request):
    from app.database import get_db_context, get_wib_time
    user = get_current_user(request)
    data = await safe_json(request) or {}

    def _do():
        with get_db_context() as conn:
            denied = _check_dashboard(conn, dashboard_id, user['user_id'], 'owner')
            if denied:
                return denied
            conn.execute(
                'UPDATE dashboards SET name = COALESCE(?, name), description = COALESCE(?, description), '
                'icon = COALESCE(?, icon), updated_at = ? WHERE id = ?',
                (data.get('name'), data.get('description'), data.get('icon'),
                 get_wib_time(), dashboard_id))
            conn.commit()
        return None

    denied = await run_sync(_do)
    if denied:
        return denied
    return JSONResponse({'success': True})


@router.post('/dashboards/{dashboard_id}/set-default')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def set_default_dashboard(dashboard_id: int, request: Request):
    from app.database import get_db_context, get_wib_time
    user = get_current_user(request)

    def _do():
        with get_db_context() as conn:
            denied = _check_dashboard(conn, dashboard_id, user['user_id'], 'viewer')
            if denied:
                return denied
            dash = conn.execute('SELECT user_id FROM dashboards WHERE id = ?', (dashboard_id,)).fetchone()
            if dash['user_id'] != user['user_id']:
                return _forbidden('Hanya dashboard milik sendiri yang bisa dijadikan default')
            now = get_wib_time()
            conn.execute('UPDATE dashboards SET is_default = 0, updated_at = ? WHERE user_id = ? AND is_default = 1',
                         (now, user['user_id']))
            conn.execute('UPDATE dashboards SET is_default = 1, updated_at = ? WHERE id = ?',
                         (now, dashboard_id))
            conn.commit()
        return None

    denied = await run_sync(_do)
    if denied:
        return denied
    logger.info(f"Dashboard {dashboard_id} set as default for user {user['user_id']}")
    return JSONResponse({'success': True})


@router.delete('/dashboards/{dashboard_id}')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def delete_dashboard(dashboard_id: int, request: Request):
    from app.database import get_db_context
    user = get_current_user(request)

    def _do():
        with get_db_context() as conn:
            denied = _check_dashboard(conn, dashboard_id, user['user_id'], 'owner')
            if denied:
                return denied
            dash = conn.execute('SELECT id, is_default FROM dashboards WHERE id = ?', (dashboard_id,)).fetchone()
            if dash['is_default']:
                return JSONResponse({'success': False, 'error': 'Dashboard default tidak bisa dihapus'}, status_code=400)
            device_count = conn.execute(
                'SELECT COUNT(*) FROM devices WHERE dashboard_id = ?', (dashboard_id,)).fetchone()[0]
            if device_count:
                return JSONResponse({
                    'success': False,
                    'error': (f'Dashboard masih berisi {device_count} perangkat. '
                              'Hapus perangkatnya dulu (atau minta admin memindahkannya), '
                              'supaya data sensor tidak hilang tanpa disengaja.'),
                    'device_count': device_count,
                }, status_code=409)
            _purge_dashboard(conn, dashboard_id)
            audit(conn, request, user['user_id'], user['username'], 'dashboard.delete',
                  f'dashboard_id={dashboard_id}')
            conn.commit()
        return None

    denied = await run_sync(_do)
    if denied:
        return denied
    logger.info(f"Dashboard deleted: id={dashboard_id} user={user['user_id']}")
    return JSONResponse({'success': True})


# ==========================================
# ANGGOTA DASHBOARD
# ==========================================
@router.get('/dashboards/{dashboard_id}/members')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def list_members(dashboard_id: int, request: Request):
    from app.database import get_db_context
    user = get_current_user(request)

    def _do():
        with get_db_context() as conn:
            denied = _check_dashboard(conn, dashboard_id, user['user_id'], 'owner')
            if denied:
                return denied, None, None
            owner = conn.execute(
                'SELECT u.id, u.username, u.display_name FROM dashboards d '
                'JOIN users u ON u.id = d.user_id WHERE d.id = ?', (dashboard_id,)).fetchone()
            rows = conn.execute(
                'SELECT m.user_id, m.role, m.created_at, u.username, u.display_name '
                'FROM dashboard_members m JOIN users u ON u.id = m.user_id '
                'WHERE m.dashboard_id = ? ORDER BY u.username', (dashboard_id,)).fetchall()
            return None, (dict(owner) if owner else None), [dict(r) for r in rows]

    denied, owner, members = await run_sync(_do)
    if denied:
        return denied
    return JSONResponse({'success': True, 'owner': owner, 'members': members})


@router.put('/dashboards/{dashboard_id}/members')
@limiter.limit('30 per minute')
async def upsert_member(dashboard_id: int, request: Request):
    from app.database import get_db_context, get_wib_time
    from app import workspace as ws
    user = get_current_user(request)
    data = await safe_json(request) or {}
    username = (data.get('username') or '').strip()
    role = (data.get('role') or 'viewer').strip().lower()
    if role not in ws.MEMBER_ROLES:
        return JSONResponse({'success': False, 'error': 'Peran harus viewer atau editor'}, status_code=400)
    if not username:
        return JSONResponse({'success': False, 'error': 'Username wajib diisi'}, status_code=400)

    def _do():
        with get_db_context() as conn:
            denied = _check_dashboard(conn, dashboard_id, user['user_id'], 'owner')
            if denied:
                return denied, None, None
            target = conn.execute('SELECT id, username FROM users WHERE username = ?', (username,)).fetchone()
            if not target:
                return JSONResponse({'success': False, 'error': 'User tidak ditemukan'}, status_code=404), None, None
            dash = conn.execute('SELECT user_id FROM dashboards WHERE id = ?', (dashboard_id,)).fetchone()
            if target['id'] == dash['user_id']:
                return JSONResponse({'success': False, 'error': 'User itu sudah menjadi pemilik dashboard'}, status_code=400), None, None
            conn.execute(
                'INSERT INTO dashboard_members (dashboard_id, user_id, role, created_at) VALUES (?, ?, ?, ?) '
                'ON CONFLICT (dashboard_id, user_id) DO UPDATE SET role = excluded.role',
                (dashboard_id, target['id'], role, get_wib_time()))
            audit(conn, request, user['user_id'], user['username'], 'dashboard.member.set',
                  f"dashboard_id={dashboard_id} user={target['username']} role={role}")
            conn.commit()
            return None, target['id'], role

    denied, target_id, out_role = await run_sync(_do)
    if denied:
        return denied
    return JSONResponse({'success': True, 'user_id': target_id, 'role': out_role})


@router.delete('/dashboards/{dashboard_id}/members/{member_id}')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def remove_member(dashboard_id: int, member_id: int, request: Request):
    from app.database import get_db_context
    user = get_current_user(request)

    def _do():
        with get_db_context() as conn:
            if member_id == user['user_id']:
                if get_dashboard_role(conn, dashboard_id, user['user_id']) is None:
                    return JSONResponse({'success': False, 'error': 'Dashboard not found'}, status_code=404), 0
            else:
                denied = _check_dashboard(conn, dashboard_id, user['user_id'], 'owner')
                if denied:
                    return denied, 0
            r = conn.execute(
                'DELETE FROM dashboard_members WHERE dashboard_id = ? AND user_id = ?',
                (dashboard_id, member_id))
            if r.rowcount:
                audit(conn, request, user['user_id'], user['username'], 'dashboard.member.remove',
                      f'dashboard_id={dashboard_id} user_id={member_id}')
            conn.commit()
            return None, r.rowcount

    denied, count = await run_sync(_do)
    if denied:
        return denied
    if not count:
        return JSONResponse({'success': False, 'error': 'Anggota tidak ditemukan'}, status_code=404)
    return JSONResponse({'success': True})


# ==========================================
# TELEGRAM PER DASHBOARD
# ==========================================
@router.get('/dashboards/{dashboard_id}/telegram')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_dashboard_telegram_config(dashboard_id: int, request: Request):
    from app.database import get_db_context
    user = get_current_user(request)

    def _do():
        with get_db_context() as conn:
            denied = _check_dashboard(conn, dashboard_id, user['user_id'], 'owner')
            if denied:
                return denied, None
            return None, _telegram_payload(conn, dashboard_id)

    denied, payload = await run_sync(_do)
    if denied:
        return denied
    return JSONResponse({'success': True, 'telegram': payload})


@router.put('/dashboards/{dashboard_id}/telegram')
@limiter.limit('20 per minute')
async def set_dashboard_telegram_config(dashboard_id: int, request: Request):
    from app.database import get_db_context, get_wib_time
    from app import workspace as ws
    user = get_current_user(request)
    data = await safe_json(request) or {}
    new_token = (data.get('bot_token') or '').strip()
    chat_id = str(data.get('chat_id') or '').strip()
    enabled = 1 if data.get('enabled', True) else 0
    if new_token and not TOKEN_RE.match(new_token):
        return JSONResponse({'success': False, 'error': 'Format token bot tidak valid (contoh: 123456:ABC...)'}, status_code=400)
    if not chat_id or not CHAT_ID_RE.match(chat_id):
        return JSONResponse({'success': False, 'error': 'Chat ID tidak valid (angka, atau @namachannel)'}, status_code=400)

    def _do():
        with get_db_context() as conn:
            denied = _check_dashboard(conn, dashboard_id, user['user_id'], 'owner')
            if denied:
                return denied, None
            existing = conn.execute(
                'SELECT bot_token_enc FROM dashboard_telegram WHERE dashboard_id = ?', (dashboard_id,)).fetchone()
            if new_token:
                try:
                    token_enc = ws.encrypt_token(new_token)
                except Exception as e:
                    logger.error(f'Enkripsi token Telegram gagal: {type(e).__name__}')
                    return JSONResponse({
                        'success': False,
                        'error': 'Server belum bisa mengenkripsi token (paket cryptography belum terpasang?)',
                    }, status_code=500), None
            elif existing and existing['bot_token_enc']:
                token_enc = existing['bot_token_enc']
            else:
                return JSONResponse({'success': False, 'error': 'Token bot wajib diisi'}, status_code=400), None
            conn.execute(
                'INSERT INTO dashboard_telegram (dashboard_id, bot_token_enc, chat_id, enabled, updated_at) '
                'VALUES (?, ?, ?, ?, ?) ON CONFLICT (dashboard_id) DO UPDATE SET '
                'bot_token_enc = excluded.bot_token_enc, chat_id = excluded.chat_id, '
                'enabled = excluded.enabled, updated_at = excluded.updated_at',
                (dashboard_id, token_enc, chat_id, enabled, get_wib_time()))
            audit(conn, request, user['user_id'], user['username'], 'dashboard.telegram.set',
                  f'dashboard_id={dashboard_id} enabled={enabled} token_changed={bool(new_token)}')
            conn.commit()
            return None, _telegram_payload(conn, dashboard_id)

    denied, payload = await run_sync(_do)
    if denied:
        return denied
    return JSONResponse({'success': True, 'telegram': payload})


@router.delete('/dashboards/{dashboard_id}/telegram')
@limiter.limit('20 per minute')
async def delete_dashboard_telegram_config(dashboard_id: int, request: Request):
    from app.database import get_db_context
    user = get_current_user(request)

    def _do():
        with get_db_context() as conn:
            denied = _check_dashboard(conn, dashboard_id, user['user_id'], 'owner')
            if denied:
                return denied
            conn.execute('DELETE FROM dashboard_telegram WHERE dashboard_id = ?', (dashboard_id,))
            audit(conn, request, user['user_id'], user['username'], 'dashboard.telegram.delete',
                  f'dashboard_id={dashboard_id}')
            conn.commit()
        return None

    denied = await run_sync(_do)
    if denied:
        return denied
    return JSONResponse({'success': True})


@router.post('/dashboards/{dashboard_id}/telegram/test')
@limiter.limit('10 per minute')
async def test_dashboard_telegram(dashboard_id: int, request: Request):
    from app.database import get_db_context
    from app import workspace as ws
    user = get_current_user(request)

    def _do():
        with get_db_context() as conn:
            denied = _check_dashboard(conn, dashboard_id, user['user_id'], 'owner')
            if denied:
                return denied, None
            return None, ws.get_dashboard_telegram(conn, dashboard_id)

    denied, cfg = await run_sync(_do)
    if denied:
        return denied
    if not cfg or not cfg['token'] or not cfg['chat_id']:
        return JSONResponse({'success': False, 'error': 'Telegram dashboard ini belum dikonfigurasi'}, status_code=400)
    from app.notifier import send_test_notification
    try:
        result = await run_sync(send_test_notification, token=cfg['token'], chat_id=cfg['chat_id'])
    except Exception as e:
        logger.error(f"Test Telegram dashboard gagal: {type(e).__name__}")
        return JSONResponse({'success': False, 'error': 'Gagal mengirim pesan tes'}, status_code=500)
    tg = (result or {}).get('telegram', {})
    if tg.get('success'):
        return JSONResponse({'success': True})
    return JSONResponse({'success': False, 'error': tg.get('error') or 'Gagal mengirim pesan tes'}, status_code=502)


# ==========================================
# ANALYTICS TABS
# ==========================================
@router.get('/dashboards/{dashboard_id}/analytics-tabs')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def list_analytics_tabs(dashboard_id: int, request: Request):
    from app.database import get_db_context
    user = get_current_user(request)

    def _do():
        with get_db_context() as conn:
            denied = _check_dashboard(conn, dashboard_id, user['user_id'], 'viewer')
            if denied:
                return denied, None
            rows = conn.execute(
                'SELECT t.*, COUNT(w.id) AS widget_count FROM analytics_tabs t '
                'LEFT JOIN widgets w ON w.analytics_tab_id = t.id '
                'WHERE t.dashboard_id = ? GROUP BY t.id ORDER BY t.position ASC, t.id ASC',
                (dashboard_id,)).fetchall()
            return None, [dict(r) for r in rows]

    denied, tabs = await run_sync(_do)
    if denied:
        return denied
    return JSONResponse({'success': True, 'tabs': tabs})


@router.post('/dashboards/{dashboard_id}/analytics-tabs')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def create_analytics_tab(dashboard_id: int, request: Request):
    from app.database import get_db_context, get_wib_time
    user = get_current_user(request)
    data = await safe_json(request) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return JSONResponse({'success': False, 'error': 'Nama tab wajib diisi'}, status_code=400)

    def _do():
        with get_db_context() as conn:
            denied = _check_dashboard(conn, dashboard_id, user['user_id'], 'editor')
            if denied:
                return denied, None, None
            row = conn.execute(
                'SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM analytics_tabs WHERE dashboard_id = ?',
                (dashboard_id,)).fetchone()
            next_pos = row['next_pos']
            cur = conn.execute(
                'INSERT INTO analytics_tabs (dashboard_id, name, icon, position, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (dashboard_id, name, data.get('icon', 'fa-chart-line'), next_pos,
                 get_wib_time(), get_wib_time()))
            conn.commit()
            return None, cur.lastrowid, next_pos

    denied, new_id, next_pos = await run_sync(_do)
    if denied:
        return denied
    return JSONResponse({'success': True, 'id': new_id, 'name': name, 'position': next_pos, 'widget_count': 0}, status_code=201)


@router.put('/analytics-tabs/{tab_id}')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def update_analytics_tab(tab_id: int, request: Request):
    from app.database import get_db_context, get_wib_time
    user = get_current_user(request)
    data = await safe_json(request) or {}

    def _do():
        with get_db_context() as conn:
            denied = _check_tab(conn, tab_id, user['user_id'], 'editor')
            if denied:
                return denied
            fields, params = [], []
            for col in ('name', 'icon', 'position'):
                if col in data:
                    fields.append(f'{col} = ?')
                    params.append(data[col])
            if fields:
                fields.append('updated_at = ?')
                params.append(get_wib_time())
                params.append(tab_id)
                conn.execute(f'UPDATE analytics_tabs SET {", ".join(fields)} WHERE id = ?', params)
                conn.commit()
        return None

    denied = await run_sync(_do)
    if denied:
        return denied
    return JSONResponse({'success': True})


@router.delete('/analytics-tabs/{tab_id}')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def delete_analytics_tab(tab_id: int, request: Request):
    from app.database import get_db_context
    user = get_current_user(request)

    def _do():
        with get_db_context() as conn:
            denied = _check_tab(conn, tab_id, user['user_id'], 'editor')
            if denied:
                return denied
            conn.execute('DELETE FROM widgets WHERE analytics_tab_id = ?', (tab_id,))
            conn.execute('DELETE FROM analytics_tabs WHERE id = ?', (tab_id,))
            conn.commit()
        return None

    denied = await run_sync(_do)
    if denied:
        return denied
    return JSONResponse({'success': True})


@router.get('/dashboards/{dashboard_id}/analytics-tabs/{tab_id}/widgets')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def list_tab_widgets(dashboard_id: int, tab_id: int, request: Request):
    from app.database import get_db_context
    user = get_current_user(request)

    def _do():
        with get_db_context() as conn:
            denied = _check_dashboard(conn, dashboard_id, user['user_id'], 'viewer')
            if denied:
                return denied, None
            rows = conn.execute(
                'SELECT * FROM widgets WHERE dashboard_id = ? AND analytics_tab_id = ? '
                'ORDER BY grid_y ASC, grid_x ASC', (dashboard_id, tab_id)).fetchall()
            out = []
            for w in rows:
                wd = dict(w)
                wd['config'] = safe_json_loads(wd['config'])
                out.append(wd)
            return None, out

    denied, widgets = await run_sync(_do)
    if denied:
        return denied
    return JSONResponse({'success': True, 'widgets': widgets})


# ==========================================
# WIDGETS
# ==========================================
@router.post('/dashboards/{dashboard_id}/widgets')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def create_widget(dashboard_id: int, request: Request):
    from app.database import get_db_context, get_wib_time
    user = get_current_user(request)
    data = await safe_json(request) or {}
    widget_type = data.get('widget_type', 'line_chart')
    if widget_type not in VALID_WIDGET_TYPES:
        return JSONResponse({'success': False, 'error': 'widget_type tidak valid'}, status_code=400)
    tab_id = data.get('analytics_tab_id')
    try:
        tab_id_int = int(tab_id) if tab_id not in (None, '', 0, '0') else None
    except (ValueError, TypeError):
        tab_id_int = None

    def _do():
        with get_db_context() as conn:
            denied = _check_dashboard(conn, dashboard_id, user['user_id'], 'editor')
            if denied:
                return denied, None
            if not _device_visible(conn, data.get('device_id'), user['user_id']):
                return JSONResponse({'success': False, 'error': 'Perangkat tidak ditemukan'}, status_code=400), None
            if tab_id_int is not None:
                tab = conn.execute(
                    'SELECT id FROM analytics_tabs WHERE id = ? AND dashboard_id = ?',
                    (tab_id_int, dashboard_id)).fetchone()
                if not tab:
                    return JSONResponse({'success': False, 'error': 'Tab tidak ditemukan'}, status_code=400), None
            cur = conn.execute(
                'INSERT INTO widgets (dashboard_id, widget_type, title, device_id, config, '
                'grid_x, grid_y, grid_w, grid_h, analytics_tab_id, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (dashboard_id, widget_type, data.get('title', 'Untitled'), data.get('device_id'),
                 json.dumps(data.get('config', {})),
                 int(data.get('grid_x', 0)), int(data.get('grid_y', 0)),
                 int(data.get('grid_w', 2)), int(data.get('grid_h', 2)),
                 tab_id_int, get_wib_time(), get_wib_time()))
            conn.commit()
            return None, cur.lastrowid

    denied, wid = await run_sync(_do)
    if denied:
        return denied
    return JSONResponse({'success': True, 'id': wid}, status_code=201)


@router.put('/widgets/{widget_id}')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def update_widget(widget_id: int, request: Request):
    from app.database import get_db_context, get_wib_time
    user = get_current_user(request)
    data = await safe_json(request) or {}

    def _do():
        with get_db_context() as conn:
            denied = _check_widget(conn, widget_id, user['user_id'], 'editor')
            if denied:
                return denied
            if 'device_id' in data and not _device_visible(conn, data.get('device_id'), user['user_id']):
                return JSONResponse({'success': False, 'error': 'Perangkat tidak ditemukan'}, status_code=400)
            fields, params = [], []
            for col in ('title', 'device_id', 'widget_type', 'grid_x', 'grid_y', 'grid_w', 'grid_h'):
                if col in data:
                    fields.append(f'{col} = ?')
                    params.append(data[col])
            if 'config' in data:
                fields.append('config = ?')
                params.append(json.dumps(data['config']))
            if fields:
                fields.append('updated_at = ?')
                params.append(get_wib_time())
                params.append(widget_id)
                conn.execute(f'UPDATE widgets SET {", ".join(fields)} WHERE id = ?', params)
                conn.commit()
        return None

    denied = await run_sync(_do)
    if denied:
        return denied
    return JSONResponse({'success': True})


@router.delete('/widgets/{widget_id}')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def delete_widget(widget_id: int, request: Request):
    from app.database import get_db_context
    user = get_current_user(request)

    def _do():
        with get_db_context() as conn:
            denied = _check_widget(conn, widget_id, user['user_id'], 'editor')
            if denied:
                return denied
            conn.execute('DELETE FROM widgets WHERE id = ?', (widget_id,))
            conn.commit()
        return None

    denied = await run_sync(_do)
    if denied:
        return denied
    return JSONResponse({'success': True})


@router.put('/dashboards/{dashboard_id}/layout')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def save_dashboard_layout(dashboard_id: int, request: Request):
    from app.database import get_db_context, get_wib_time
    user = get_current_user(request)
    data = await safe_json(request) or {}
    layout = data.get('layout', [])
    if not isinstance(layout, list):
        return JSONResponse({'success': False, 'error': 'layout harus array'}, status_code=400)

    def _do():
        with get_db_context() as conn:
            denied = _check_dashboard(conn, dashboard_id, user['user_id'], 'editor')
            if denied:
                return denied, 0
            now = get_wib_time()
            updated = 0
            for idx, item in enumerate(layout):
                if not isinstance(item, dict):
                    return JSONResponse({
                        'success': False, 'error': f'layout[{idx}] harus berupa object',
                    }, status_code=400), 0
                wid = item.get('id')
                if not wid:
                    continue
                result = conn.execute(
                    'UPDATE widgets SET grid_x = ?, grid_y = ?, grid_w = ?, grid_h = ?, updated_at = ? '
                    'WHERE id = ? AND dashboard_id = ?',
                    (int(item.get('x', 0)), int(item.get('y', 0)),
                     int(item.get('w', 2)), int(item.get('h', 2)), now, wid, dashboard_id))
                if result.rowcount > 0:
                    updated += 1
            conn.commit()
            return None, updated

    denied, updated = await run_sync(_do)
    if denied:
        return denied
    return JSONResponse({'success': True, 'updated': updated})
