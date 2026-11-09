"""
NEXUS IoT - Dashboard & Analytics Management (Workspace)

Dashboard = ruang kerja: memiliki perangkat, anggota (viewer/editor), dan
konfigurasi Telegram sendiri. Hak akses dihitung di app/workspace.py.
"""
import re
import json
import logging

from flask import Blueprint, request, jsonify, session

from app.auth import login_required, ensure_user_dashboard
from app.database import get_db_context, get_wib_time
from app.utils import safe_json_loads
from app.extensions import limiter
from app.config import get_config
from app import workspace as ws

logger = logging.getLogger('nexus')

dashboards_bp = Blueprint('dashboards', __name__, url_prefix='/api/v1')

SLUG_RE = re.compile(r'^[a-z0-9\-]+$')
TOKEN_RE = re.compile(r'^\d{5,}:[A-Za-z0-9_-]{20,}$')
CHAT_ID_RE = re.compile(r'^(-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,63})$')
VALID_WIDGET_TYPES = {
    'line_chart', 'bar_chart', 'area_chart',
    'doughnut_chart', 'pie_chart', 'polar_area', 'radar_chart',
    'horizontal_bar', 'stacked_bar', 'stacked_area',
}


def _get_user_id():
    return session.get('user_id')


def _validate_slug(slug):
    return bool(slug) and SLUG_RE.match(slug) and len(slug) <= 64


def _no_session():
    return jsonify({'success': False, 'error': 'Session invalid, re-login'}), 401


def _forbidden(msg='Anda tidak punya izin untuk aksi ini'):
    return jsonify({'success': False, 'error': msg}), 403


def _check_dashboard(conn, dashboard_id, user_id, minimum='viewer'):
    """Return None bila boleh, atau (response, status) siap dikembalikan.

    Tidak punya akses sama sekali -> 404 (tidak membocorkan keberadaan).
    Punya akses tapi peran kurang -> 403.
    """
    role = ws.get_dashboard_role(conn, dashboard_id, user_id)
    if role is None:
        return jsonify({'success': False, 'error': 'Dashboard not found'}), 404
    if not ws.role_allows(role, minimum):
        return _forbidden('Peran Anda di dashboard ini tidak cukup untuk aksi tersebut')
    return None


def _check_widget(conn, widget_id, user_id, minimum='editor'):
    row = conn.execute(
        'SELECT dashboard_id FROM widgets WHERE id = ?', (widget_id,)
    ).fetchone()
    if not row:
        return jsonify({'success': False, 'error': 'Widget not found'}), 404
    return _check_dashboard(conn, row['dashboard_id'], user_id, minimum)


def _check_tab(conn, tab_id, user_id, minimum='editor'):
    row = conn.execute(
        'SELECT dashboard_id FROM analytics_tabs WHERE id = ?', (tab_id,)
    ).fetchone()
    if not row:
        return jsonify({'success': False, 'error': 'Tab not found'}), 404
    return _check_dashboard(conn, row['dashboard_id'], user_id, minimum)


def _device_visible(conn, device_id, user_id):
    """True bila device_id kosong atau perangkat itu boleh dilihat user."""
    if not device_id:
        return True
    row = conn.execute(
        'SELECT dashboard_id FROM devices WHERE device_id = ?', (device_id,)
    ).fetchone()
    if not row:
        return False
    return ws.device_role(conn, row, user_id) is not None


def _find_dashboard_by_slug(conn, slug, user_id):
    """Cari dashboard via slug: milik sendiri diutamakan, lalu yang dibagikan."""
    rows = conn.execute(
        'SELECT * FROM dashboards WHERE slug = ? ORDER BY (user_id = ?) DESC, id ASC',
        (slug, user_id)
    ).fetchall()
    for r in rows:
        if ws.get_dashboard_role(conn, r['id'], user_id):
            return r
    return None


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


# ==========================================
# DASHBOARDS
# ==========================================
def _list_rows(conn, user_id):
    return conn.execute(_LIST_SQL, {'uid': user_id}).fetchall()


@dashboards_bp.route('/dashboards', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def list_dashboards():
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    with get_db_context() as conn:
        rows = _list_rows(conn, user_id)

    # Auto-create kalau user belum punya dashboard sama sekali
    if not rows:
        username = session.get('username', 'user')
        try:
            ensure_user_dashboard(user_id, username)
            with get_db_context() as conn:
                rows = _list_rows(conn, user_id)
        except Exception as e:
            logger.error(f"Auto-create dashboard failed: {e}")

    return jsonify({'success': True, 'dashboards': [dict(r) for r in rows]}), 200


@dashboards_bp.route('/dashboards', methods=['POST'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def create_dashboard():
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    slug_input = (data.get('slug') or '').strip().lower().replace(' ', '-')

    if not name:
        return jsonify({'success': False, 'error': 'Nama dashboard wajib diisi'}), 400

    if slug_input and not _validate_slug(slug_input):
        return jsonify({'success': False, 'error': 'Slug hanya huruf kecil, angka, dan dash'}), 400

    if not slug_input:
        slug_input = re.sub(r'[^a-z0-9\-]+', '-', name.lower()).strip('-') or 'dashboard'
    slug_input = slug_input[:60]

    with get_db_context() as conn:
        # Slug unik secara global: dashboard bisa dibagikan, jadi URL /d/<slug>
        # tidak boleh ambigu antar pemilik.
        base, i = slug_input, 2
        while conn.execute('SELECT 1 FROM dashboards WHERE slug = ?', (slug_input,)).fetchone():
            slug_input = f"{base}-{i}"
            i += 1

        # Dashboard baru benar-benar kosong: tanpa perangkat, tab, maupun widget.
        cur = conn.execute("""
            INSERT INTO dashboards
            (slug, name, description, icon, is_default, user_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, ?, ?, ?)
        """, (
            slug_input, name,
            data.get('description', ''),
            data.get('icon', 'fa-chart-line'),
            user_id,
            get_wib_time(), get_wib_time()
        ))
        conn.commit()
        new_id = cur.lastrowid

    logger.info(f"Dashboard created: id={new_id} user={user_id} slug={slug_input}")
    return jsonify({'success': True, 'id': new_id, 'slug': slug_input}), 201


def _widgets_of(conn, dashboard_id):
    rows = conn.execute("""
        SELECT * FROM widgets WHERE dashboard_id = ?
        ORDER BY grid_y ASC, grid_x ASC
    """, (dashboard_id,)).fetchall()
    out = []
    for w in rows:
        wd = dict(w)
        wd['config'] = safe_json_loads(wd['config'])
        out.append(wd)
    return out


@dashboards_bp.route('/dashboards/<int:dashboard_id>', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_dashboard_detail(dashboard_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    with get_db_context() as conn:
        denied = _check_dashboard(conn, dashboard_id, user_id, 'viewer')
        if denied:
            return denied
        dash = dict(conn.execute('SELECT * FROM dashboards WHERE id = ?', (dashboard_id,)).fetchone())
        dash['role'] = ws.get_dashboard_role(conn, dashboard_id, user_id)
        widgets = _widgets_of(conn, dashboard_id)

    return jsonify({'success': True, 'dashboard': dash, 'widgets': widgets}), 200


@dashboards_bp.route('/dashboards/slug/<slug>', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_dashboard_by_slug(slug):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    with get_db_context() as conn:
        dash = _find_dashboard_by_slug(conn, slug, user_id)
        if not dash:
            return jsonify({'success': False, 'error': 'Dashboard not found'}), 404
        d = dict(dash)
        d['role'] = ws.get_dashboard_role(conn, dash['id'], user_id)
        widgets = _widgets_of(conn, dash['id'])

    return jsonify({'success': True, 'dashboard': d, 'widgets': widgets}), 200


@dashboards_bp.route('/dashboards/<int:dashboard_id>', methods=['PUT'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def update_dashboard(dashboard_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    data = request.get_json(silent=True) or {}

    with get_db_context() as conn:
        denied = _check_dashboard(conn, dashboard_id, user_id, 'owner')
        if denied:
            return denied

        conn.execute("""
            UPDATE dashboards SET
                name = COALESCE(?, name),
                description = COALESCE(?, description),
                icon = COALESCE(?, icon),
                updated_at = ?
            WHERE id = ?
        """, (
            data.get('name'),
            data.get('description'),
            data.get('icon'),
            get_wib_time(),
            dashboard_id
        ))
        conn.commit()

    return jsonify({'success': True}), 200


@dashboards_bp.route('/dashboards/<int:dashboard_id>/set-default', methods=['POST'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def set_default_dashboard(dashboard_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    with get_db_context() as conn:
        denied = _check_dashboard(conn, dashboard_id, user_id, 'viewer')
        if denied:
            return denied

        dash = conn.execute(
            'SELECT user_id FROM dashboards WHERE id = ?', (dashboard_id,)
        ).fetchone()
        if dash['user_id'] != user_id:
            return _forbidden('Hanya dashboard milik sendiri yang bisa dijadikan default')

        now = get_wib_time()
        conn.execute(
            'UPDATE dashboards SET is_default = 0, updated_at = ? WHERE user_id = ? AND is_default = 1',
            (now, user_id)
        )
        conn.execute(
            'UPDATE dashboards SET is_default = 1, updated_at = ? WHERE id = ?',
            (now, dashboard_id)
        )
        conn.commit()

    logger.info(f"Dashboard {dashboard_id} set as default for user {user_id}")
    return jsonify({'success': True}), 200


def purge_dashboard(conn, dashboard_id):
    """Hapus dashboard beserta isinya (widget, tab, anggota, Telegram).

    Pemanggil bertanggung jawab memastikan perangkatnya sudah dipindah/dihapus.
    """
    conn.execute('DELETE FROM widgets WHERE dashboard_id = ?', (dashboard_id,))
    conn.execute('DELETE FROM analytics_tabs WHERE dashboard_id = ?', (dashboard_id,))
    conn.execute('DELETE FROM dashboard_members WHERE dashboard_id = ?', (dashboard_id,))
    conn.execute('DELETE FROM dashboard_telegram WHERE dashboard_id = ?', (dashboard_id,))
    conn.execute('DELETE FROM dashboards WHERE id = ?', (dashboard_id,))


@dashboards_bp.route('/dashboards/<int:dashboard_id>', methods=['DELETE'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def delete_dashboard(dashboard_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    with get_db_context() as conn:
        denied = _check_dashboard(conn, dashboard_id, user_id, 'owner')
        if denied:
            return denied

        dash = conn.execute(
            'SELECT id, is_default FROM dashboards WHERE id = ?', (dashboard_id,)
        ).fetchone()
        if dash['is_default']:
            return jsonify({'success': False, 'error': 'Dashboard default tidak bisa dihapus'}), 400

        device_count = conn.execute(
            'SELECT COUNT(*) FROM devices WHERE dashboard_id = ?', (dashboard_id,)
        ).fetchone()[0]
        if device_count:
            return jsonify({
                'success': False,
                'error': (f'Dashboard masih berisi {device_count} perangkat. '
                          'Hapus perangkatnya dulu (atau minta admin memindahkannya), '
                          'supaya data sensor tidak hilang tanpa disengaja.'),
                'device_count': device_count,
            }), 409

        purge_dashboard(conn, dashboard_id)
        ws.audit(conn, 'dashboard.delete', f'dashboard_id={dashboard_id}')
        conn.commit()

    logger.info(f"Dashboard deleted: id={dashboard_id} user={user_id}")
    return jsonify({'success': True}), 200


# ==========================================
# ANGGOTA DASHBOARD (berbagi akses)
# ==========================================
@dashboards_bp.route('/dashboards/<int:dashboard_id>/members', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def list_members(dashboard_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    with get_db_context() as conn:
        denied = _check_dashboard(conn, dashboard_id, user_id, 'owner')
        if denied:
            return denied
        owner = conn.execute("""
            SELECT u.id, u.username, u.display_name FROM dashboards d
            JOIN users u ON u.id = d.user_id WHERE d.id = ?
        """, (dashboard_id,)).fetchone()
        rows = conn.execute("""
            SELECT m.user_id, m.role, m.created_at, u.username, u.display_name
            FROM dashboard_members m JOIN users u ON u.id = m.user_id
            WHERE m.dashboard_id = ? ORDER BY u.username
        """, (dashboard_id,)).fetchall()

    return jsonify({
        'success': True,
        'owner': dict(owner) if owner else None,
        'members': [dict(r) for r in rows],
    }), 200


@dashboards_bp.route('/dashboards/<int:dashboard_id>/members', methods=['PUT'])
@login_required
@limiter.limit("30 per minute")
def upsert_member(dashboard_id):
    """Body: {username, role: viewer|editor}. Menambah anggota atau mengubah perannya."""
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    role = (data.get('role') or 'viewer').strip().lower()

    if role not in ws.MEMBER_ROLES:
        return jsonify({'success': False, 'error': 'Peran harus viewer atau editor'}), 400
    if not username:
        return jsonify({'success': False, 'error': 'Username wajib diisi'}), 400

    with get_db_context() as conn:
        denied = _check_dashboard(conn, dashboard_id, user_id, 'owner')
        if denied:
            return denied

        target = conn.execute(
            'SELECT id, username FROM users WHERE username = ?', (username,)
        ).fetchone()
        if not target:
            return jsonify({'success': False, 'error': 'User tidak ditemukan'}), 404

        dash = conn.execute('SELECT user_id FROM dashboards WHERE id = ?', (dashboard_id,)).fetchone()
        if target['id'] == dash['user_id']:
            return jsonify({'success': False, 'error': 'User itu sudah menjadi pemilik dashboard'}), 400

        conn.execute("""
            INSERT INTO dashboard_members (dashboard_id, user_id, role, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (dashboard_id, user_id) DO UPDATE SET role = excluded.role
        """, (dashboard_id, target['id'], role, get_wib_time()))
        ws.audit(conn, 'dashboard.member.set',
                 f"dashboard_id={dashboard_id} user={target['username']} role={role}")
        conn.commit()

    return jsonify({'success': True, 'user_id': target['id'], 'role': role}), 200


@dashboards_bp.route('/dashboards/<int:dashboard_id>/members/<int:member_id>', methods=['DELETE'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def remove_member(dashboard_id, member_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    with get_db_context() as conn:
        # Pemilik boleh mengeluarkan anggota; anggota boleh keluar sendiri.
        if member_id == user_id:
            if ws.get_dashboard_role(conn, dashboard_id, user_id) is None:
                return jsonify({'success': False, 'error': 'Dashboard not found'}), 404
        else:
            denied = _check_dashboard(conn, dashboard_id, user_id, 'owner')
            if denied:
                return denied

        r = conn.execute(
            'DELETE FROM dashboard_members WHERE dashboard_id = ? AND user_id = ?',
            (dashboard_id, member_id)
        )
        if r.rowcount:
            ws.audit(conn, 'dashboard.member.remove',
                     f'dashboard_id={dashboard_id} user_id={member_id}')
        conn.commit()

    if not r.rowcount:
        return jsonify({'success': False, 'error': 'Anggota tidak ditemukan'}), 404
    return jsonify({'success': True}), 200


# ==========================================
# TELEGRAM PER DASHBOARD
# ==========================================
def _telegram_payload(conn, dashboard_id):
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


@dashboards_bp.route('/dashboards/<int:dashboard_id>/telegram', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_dashboard_telegram_config(dashboard_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()
    with get_db_context() as conn:
        denied = _check_dashboard(conn, dashboard_id, user_id, 'owner')
        if denied:
            return denied
        payload = _telegram_payload(conn, dashboard_id)
    # Token utuh TIDAK pernah dikirim ke frontend.
    return jsonify({'success': True, 'telegram': payload}), 200


@dashboards_bp.route('/dashboards/<int:dashboard_id>/telegram', methods=['PUT'])
@login_required
@limiter.limit("20 per minute")
def set_dashboard_telegram_config(dashboard_id):
    """Body: {bot_token?, chat_id, enabled}. bot_token kosong = pertahankan token lama."""
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    data = request.get_json(silent=True) or {}
    new_token = (data.get('bot_token') or '').strip()
    chat_id = str(data.get('chat_id') or '').strip()
    enabled = 1 if data.get('enabled', True) else 0

    if new_token and not TOKEN_RE.match(new_token):
        return jsonify({'success': False, 'error': 'Format token bot tidak valid (contoh: 123456:ABC...)'}), 400
    if not chat_id or not CHAT_ID_RE.match(chat_id):
        return jsonify({'success': False, 'error': 'Chat ID tidak valid (angka, atau @namachannel)'}), 400

    with get_db_context() as conn:
        denied = _check_dashboard(conn, dashboard_id, user_id, 'owner')
        if denied:
            return denied

        existing = conn.execute(
            'SELECT bot_token_enc FROM dashboard_telegram WHERE dashboard_id = ?', (dashboard_id,)
        ).fetchone()

        if new_token:
            try:
                token_enc = ws.encrypt_token(new_token)
            except Exception as e:
                logger.error(f"Enkripsi token Telegram gagal: {type(e).__name__}")
                return jsonify({
                    'success': False,
                    'error': 'Server belum bisa mengenkripsi token (paket cryptography belum terpasang?)',
                }), 500
        elif existing and existing['bot_token_enc']:
            token_enc = existing['bot_token_enc']
        else:
            return jsonify({'success': False, 'error': 'Token bot wajib diisi'}), 400

        conn.execute("""
            INSERT INTO dashboard_telegram (dashboard_id, bot_token_enc, chat_id, enabled, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (dashboard_id) DO UPDATE SET
                bot_token_enc = excluded.bot_token_enc,
                chat_id = excluded.chat_id,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
        """, (dashboard_id, token_enc, chat_id, enabled, get_wib_time()))
        ws.audit(conn, 'dashboard.telegram.set',
                 f"dashboard_id={dashboard_id} enabled={enabled} token_changed={bool(new_token)}")
        conn.commit()
        payload = _telegram_payload(conn, dashboard_id)

    return jsonify({'success': True, 'telegram': payload}), 200


@dashboards_bp.route('/dashboards/<int:dashboard_id>/telegram', methods=['DELETE'])
@login_required
@limiter.limit("20 per minute")
def delete_dashboard_telegram_config(dashboard_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()
    with get_db_context() as conn:
        denied = _check_dashboard(conn, dashboard_id, user_id, 'owner')
        if denied:
            return denied
        conn.execute('DELETE FROM dashboard_telegram WHERE dashboard_id = ?', (dashboard_id,))
        ws.audit(conn, 'dashboard.telegram.delete', f'dashboard_id={dashboard_id}')
        conn.commit()
    return jsonify({'success': True}), 200


@dashboards_bp.route('/dashboards/<int:dashboard_id>/telegram/test', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def test_dashboard_telegram(dashboard_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()
    with get_db_context() as conn:
        denied = _check_dashboard(conn, dashboard_id, user_id, 'owner')
        if denied:
            return denied
        cfg = ws.get_dashboard_telegram(conn, dashboard_id)

    if not cfg or not cfg['token'] or not cfg['chat_id']:
        return jsonify({'success': False, 'error': 'Telegram dashboard ini belum dikonfigurasi'}), 400

    from app.notifier import send_test_notification
    try:
        result = send_test_notification(token=cfg['token'], chat_id=cfg['chat_id'])
    except Exception as e:
        logger.error(f"Test Telegram dashboard gagal: {type(e).__name__}")
        return jsonify({'success': False, 'error': 'Gagal mengirim pesan tes'}), 500

    tg = result.get('telegram', {})
    if tg.get('success'):
        return jsonify({'success': True}), 200
    return jsonify({'success': False, 'error': tg.get('error') or 'Gagal mengirim pesan tes'}), 502


# ==========================================
# ANALYTICS TABS
# ==========================================
@dashboards_bp.route('/dashboards/<int:dashboard_id>/analytics-tabs', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def list_analytics_tabs(dashboard_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    with get_db_context() as conn:
        denied = _check_dashboard(conn, dashboard_id, user_id, 'viewer')
        if denied:
            return denied

        rows = conn.execute("""
            SELECT t.*, COUNT(w.id) AS widget_count
            FROM analytics_tabs t
            LEFT JOIN widgets w ON w.analytics_tab_id = t.id
            WHERE t.dashboard_id = ?
            GROUP BY t.id
            ORDER BY t.position ASC, t.id ASC
        """, (dashboard_id,)).fetchall()

    return jsonify({'success': True, 'tabs': [dict(r) for r in rows]}), 200


@dashboards_bp.route('/dashboards/<int:dashboard_id>/analytics-tabs', methods=['POST'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def create_analytics_tab(dashboard_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'Nama tab wajib diisi'}), 400

    with get_db_context() as conn:
        denied = _check_dashboard(conn, dashboard_id, user_id, 'editor')
        if denied:
            return denied

        row = conn.execute(
            'SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM analytics_tabs WHERE dashboard_id = ?',
            (dashboard_id,)
        ).fetchone()
        next_pos = row['next_pos']

        cur = conn.execute("""
            INSERT INTO analytics_tabs (dashboard_id, name, icon, position, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            dashboard_id, name,
            data.get('icon', 'fa-chart-line'),
            next_pos,
            get_wib_time(), get_wib_time()
        ))
        conn.commit()
        new_id = cur.lastrowid

    return jsonify({
        'success': True,
        'id': new_id, 'name': name,
        'position': next_pos,
        'widget_count': 0,
    }), 201


@dashboards_bp.route('/analytics-tabs/<int:tab_id>', methods=['PUT'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def update_analytics_tab(tab_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    data = request.get_json(silent=True) or {}

    with get_db_context() as conn:
        denied = _check_tab(conn, tab_id, user_id, 'editor')
        if denied:
            return denied

        fields, params = [], []
        for col in ['name', 'icon', 'position']:
            if col in data:
                fields.append(f'{col} = ?')
                params.append(data[col])

        if fields:
            fields.append('updated_at = ?')
            params.append(get_wib_time())
            params.append(tab_id)
            conn.execute(f'UPDATE analytics_tabs SET {", ".join(fields)} WHERE id = ?', params)
            conn.commit()

    return jsonify({'success': True}), 200


@dashboards_bp.route('/analytics-tabs/<int:tab_id>', methods=['DELETE'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def delete_analytics_tab(tab_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    with get_db_context() as conn:
        denied = _check_tab(conn, tab_id, user_id, 'editor')
        if denied:
            return denied

        conn.execute('DELETE FROM widgets WHERE analytics_tab_id = ?', (tab_id,))
        conn.execute('DELETE FROM analytics_tabs WHERE id = ?', (tab_id,))
        conn.commit()

    return jsonify({'success': True}), 200


@dashboards_bp.route('/dashboards/<int:dashboard_id>/analytics-tabs/<int:tab_id>/widgets', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def list_tab_widgets(dashboard_id, tab_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    with get_db_context() as conn:
        denied = _check_dashboard(conn, dashboard_id, user_id, 'viewer')
        if denied:
            return denied

        rows = conn.execute("""
            SELECT * FROM widgets
            WHERE dashboard_id = ? AND analytics_tab_id = ?
            ORDER BY grid_y ASC, grid_x ASC
        """, (dashboard_id, tab_id)).fetchall()

    widget_list = []
    for w in rows:
        wd = dict(w)
        wd['config'] = safe_json_loads(wd['config'])
        widget_list.append(wd)

    return jsonify({'success': True, 'widgets': widget_list}), 200


# ==========================================
# WIDGETS
# ==========================================
@dashboards_bp.route('/dashboards/<int:dashboard_id>/widgets', methods=['POST'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def create_widget(dashboard_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    data = request.get_json(silent=True) or {}

    widget_type = data.get('widget_type', 'line_chart')
    if widget_type not in VALID_WIDGET_TYPES:
        return jsonify({'success': False, 'error': 'widget_type tidak valid'}), 400

    tab_id = data.get('analytics_tab_id')
    try:
        tab_id_int = int(tab_id) if tab_id not in (None, '', 0, '0') else None
    except (ValueError, TypeError):
        tab_id_int = None

    with get_db_context() as conn:
        denied = _check_dashboard(conn, dashboard_id, user_id, 'editor')
        if denied:
            return denied

        if not _device_visible(conn, data.get('device_id'), user_id):
            return jsonify({'success': False, 'error': 'Perangkat tidak ditemukan'}), 400

        if tab_id_int is not None:
            tab = conn.execute(
                'SELECT id FROM analytics_tabs WHERE id = ? AND dashboard_id = ?',
                (tab_id_int, dashboard_id)
            ).fetchone()
            if not tab:
                return jsonify({'success': False, 'error': 'Tab tidak ditemukan'}), 400

        cur = conn.execute("""
            INSERT INTO widgets
            (dashboard_id, widget_type, title, device_id, config,
             grid_x, grid_y, grid_w, grid_h, analytics_tab_id,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            dashboard_id,
            widget_type,
            data.get('title', 'Untitled'),
            data.get('device_id'),
            json.dumps(data.get('config', {})),
            int(data.get('grid_x', 0)),
            int(data.get('grid_y', 0)),
            int(data.get('grid_w', 2)),
            int(data.get('grid_h', 2)),
            tab_id_int,
            get_wib_time(), get_wib_time()
        ))
        conn.commit()
        widget_id = cur.lastrowid

    return jsonify({'success': True, 'id': widget_id}), 201


@dashboards_bp.route('/widgets/<int:widget_id>', methods=['PUT'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def update_widget(widget_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    data = request.get_json(silent=True) or {}

    with get_db_context() as conn:
        denied = _check_widget(conn, widget_id, user_id, 'editor')
        if denied:
            return denied

        if 'device_id' in data and not _device_visible(conn, data.get('device_id'), user_id):
            return jsonify({'success': False, 'error': 'Perangkat tidak ditemukan'}), 400

        fields, params = [], []
        for col in ['title', 'device_id', 'widget_type',
                    'grid_x', 'grid_y', 'grid_w', 'grid_h']:
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

    return jsonify({'success': True}), 200


@dashboards_bp.route('/widgets/<int:widget_id>', methods=['DELETE'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def delete_widget(widget_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    with get_db_context() as conn:
        denied = _check_widget(conn, widget_id, user_id, 'editor')
        if denied:
            return denied

        conn.execute('DELETE FROM widgets WHERE id = ?', (widget_id,))
        conn.commit()

    return jsonify({'success': True}), 200


@dashboards_bp.route('/dashboards/<int:dashboard_id>/layout', methods=['PUT'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def save_dashboard_layout(dashboard_id):
    user_id = _get_user_id()
    if not user_id:
        return _no_session()

    data = request.get_json(silent=True) or {}
    layout = data.get('layout', [])

    if not isinstance(layout, list):
        return jsonify({'success': False, 'error': 'layout harus array'}), 400

    updated = 0
    with get_db_context() as conn:
        denied = _check_dashboard(conn, dashboard_id, user_id, 'editor')
        if denied:
            return denied

        now = get_wib_time()
        for idx, item in enumerate(layout):
            # Tanpa cek ini, elemen non-dict (mis. string) membuat item.get()
            # melempar AttributeError → 500, padahal input pengguna → 400.
            if not isinstance(item, dict):
                return jsonify({
                    'success': False,
                    'error': f'layout[{idx}] harus berupa object',
                }), 400
            wid = item.get('id')
            if not wid:
                continue
            result = conn.execute("""
                UPDATE widgets
                SET grid_x=?, grid_y=?, grid_w=?, grid_h=?, updated_at=?
                WHERE id = ? AND dashboard_id = ?
            """, (
                int(item.get('x', 0)),
                int(item.get('y', 0)),
                int(item.get('w', 2)),
                int(item.get('h', 2)),
                now, wid, dashboard_id
            ))
            if result.rowcount > 0:
                updated += 1
        conn.commit()

    return jsonify({'success': True, 'updated': updated}), 200
