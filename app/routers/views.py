"""NEXUS IoT - FastAPI web views + login/logout (dari app/views.py + app/auth.py)."""
import logging
import os
import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_config
from app.deps import (check_login_throttle, clear_login_failures, client_ip,
                      get_current_user_html, limiter, record_login_failure,
                      run_sync)

logger = logging.getLogger('nexus')
router = APIRouter(tags=['views'])

templates = Jinja2Templates(directory=os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '../../templates'))


def _tpl(request: Request, name: str, **context):
    # Tandatangan FastAPI agar request selalu tersedia di template.
    def url_for(endpoint, filename=None):
        # shortcut: hanya 'static' yang dipakai template bawaan.
        if endpoint == 'static':
            return f'/static/{filename}'
        return '/'

    def csrf_token():
        return request.cookies.get('csrf_token', '')

    from app.chat import llm_configured
    context.update(
        request=request,
        url_for=url_for,
        csrf_token=csrf_token,
        chat_enabled=llm_configured(),
    )
    return templates.TemplateResponse(request, name, context)


def _default_dashboard(conn, user_id):
    return conn.execute(
        'SELECT id, slug FROM dashboards WHERE user_id = ? '
        'ORDER BY is_default DESC, id ASC LIMIT 1', (user_id,)).fetchone()


def _find_dashboard_by_slug(conn, slug, user_id):
    from app.deps import get_dashboard_role
    rows = conn.execute(
        'SELECT * FROM dashboards WHERE slug = ? ORDER BY (user_id = ?) DESC, id ASC',
        (slug, user_id)).fetchall()
    for r in rows:
        if get_dashboard_role(conn, r['id'], user_id):
            return r
    return None


def _is_admin(conn, user_id):
    from app.deps import is_admin_sync
    return is_admin_sync(user_id)


@router.get('/', response_class=HTMLResponse)
async def dashboard(request: Request):
    from app.database import get_db_context
    user = get_current_user_html(request)

    def _do():
        with get_db_context() as conn:
            d = _default_dashboard(conn, user['user_id']) if user['user_id'] else None
            admin = _is_admin(conn, user['user_id'])
            return (d['id'] if d else ''), admin

    dashboard_id, admin = await run_sync(_do)
    return _tpl(request, 'dashboard.html', dashboard_slug=None, dashboard_id=dashboard_id,
                view_all=False, is_admin=admin)


@router.get('/d/{slug}', response_class=HTMLResponse)
async def dashboard_by_slug(slug: str, request: Request):
    from fastapi import HTTPException as _HE
    from app.database import get_db_context
    user = get_current_user_html(request)
    if not user['user_id']:
        raise _HE(401)

    def _do():
        with get_db_context() as conn:
            dash = _find_dashboard_by_slug(conn, slug, user['user_id'])
            if not dash:
                return None, None
            return dash, _is_admin(conn, user['user_id'])

    dash, admin = await run_sync(_do)
    if not dash:
        from app.main import _html_error
        return HTMLResponse(
            '<!doctype html><html><head><meta charset="utf-8">'
            '<title>404 Halaman Tidak Ditemukan</title></head><body>'
            '<h1>404 Halaman Tidak Ditemukan</h1>'
            '<p>Alamat yang Anda tuju tidak ada di sistem ini.</p></body></html>',
            status_code=404)
    return _tpl(request, 'dashboard.html', dashboard_slug=dash['slug'],
                dashboard_id=dash['id'], view_all=False, is_admin=admin)


@router.get('/all', response_class=HTMLResponse)
async def dashboard_all(request: Request):
    from fastapi import HTTPException as _HE
    from app.database import get_db_context
    user = get_current_user_html(request)

    def _do():
        with get_db_context() as conn:
            if not _is_admin(conn, user['user_id']):
                return None, None
            d = _default_dashboard(conn, user['user_id'])
            return d, True

    d, admin = await run_sync(_do)
    if not admin:
        raise _HE(404)
    try:
        from app.main import _html_error
        if not d:
            return _html_error(404, 'Halaman Tidak Ditemukan',
                               'Alamat yang Anda tuju tidak ada di sistem ini.')
    except Exception:
        pass
    return _tpl(request, 'dashboard.html', dashboard_slug=d['slug'] if d else None,
                dashboard_id='all', view_all=True, is_admin=True)


@router.get('/mobile', response_class=HTMLResponse)
async def mobile_dashboard(request: Request):
    from app.database import get_db_context
    user = get_current_user_html(request)

    def _do():
        with get_db_context() as conn:
            d = _default_dashboard(conn, user['user_id']) if user['user_id'] else None
            return d['id'] if d else ''

    dashboard_id = await run_sync(_do)
    return _tpl(request, 'mobile.html', dashboard_id=dashboard_id)


@router.get('/device/{device_id}', response_class=HTMLResponse)
async def device_detail(device_id: str, request: Request):
    get_current_user_html(request)
    return _tpl(request, 'device_detail.html', device_id=device_id)


# ==========================================
# AUTH (login/logout)
# ==========================================
def _authenticate_sync(username: str, password: str):
    """Cermin app/auth.py (hash users / seed .env). Dipanggil via run_sync."""
    import hmac
    from werkzeug.security import check_password_hash, generate_password_hash
    from app.database import get_db_context
    with get_db_context() as conn:
        user = conn.execute(
            'SELECT id, password_hash FROM users WHERE username = ?', (username,)).fetchone()
        if user:
            try:
                if check_password_hash(user['password_hash'], password):
                    return user['id']
            except Exception as e:
                logger.error(f'Verifikasi password gagal: {e}')
            return None
        total_users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        if total_users > 0:
            return None
        config = get_config()
        env_user = config.IOT_USERNAME or ''
        env_pass = config.IOT_PASSWORD or ''
        if not env_user or not env_pass:
            return None
        same_user = hmac.compare_digest(username.encode('utf-8'), env_user.encode('utf-8'))
        same_pass = hmac.compare_digest(password.encode('utf-8'), env_pass.encode('utf-8'))
        if not (same_user and same_pass):
            return None
        try:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, display_name, is_admin, role) "
                "VALUES (?, ?, 'Administrator', 1, 'superadmin')",
                (username, generate_password_hash(password)))
            conn.commit()
            logger.info(f"Admin awal '{username}' dibuat dari .env (seed)")
            return cur.lastrowid
        except Exception as e:
            logger.error(f'Gagal membuat admin awal: {e}')
            return None


@router.get('/login', response_class=HTMLResponse)
async def login_page(request: Request):
    token = request.cookies.get('csrf_token', '')
    if not token:
        token = _new_csrf()
    # Taruh token ke cookie request agar _tpl (csrf_token()) membacanya.
    request.cookies['csrf_token'] = token
    resp = _tpl(request, 'login.html', error=None)
    # Cookie CSRF harus ada sebelum POST (double-submit).
    config = get_config()
    resp.set_cookie('csrf_token', token, httponly=False,
                    samesite=config.SESSION_COOKIE_SAMESITE.lower(),
                    secure=bool(config.SESSION_COOKIE_SECURE))
    return resp


@router.post('/login', response_class=HTMLResponse)
@limiter.limit(get_config().RATE_LIMIT_LOGIN)
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...),
                       csrf_token: str = Form(default='')):
    from app.auth import ensure_user_dashboard
    config = get_config()
    if not (csrf_token or '').strip():
        return _tpl(request, 'login.html', error='Sesi tidak valid. Muat ulang halaman.')
    # CSRF double-submit ala Flask: form token harus sama dengan cookie.
    if csrf_token.strip() != request.cookies.get('csrf_token', ''):
        logger.warning('CSRF validation failed (login)')
        return _tpl(request, 'login.html', error='Sesi tidak valid. Muat ulang halaman.')

    username = (username or '').strip()
    if not username or not password:
        return _tpl(request, 'login.html', error='Username dan password wajib diisi!')

    ip = client_ip(request)
    try:
        locked_for = await check_login_throttle(username, ip)
    except Exception as e:
        logger.error(f'Throttle login gagal dicek: {e}')
        locked_for = 0
    if locked_for > 0:
        minutes = max(1, (locked_for + 59) // 60)
        logger.warning(f"Login diblokir sementara untuk '{username}' dari {ip}")
        return _tpl(request, 'login.html',
                    error=f'Terlalu banyak percobaan gagal. Coba lagi dalam {minutes} menit.')

    user_id = await run_sync(_authenticate_sync, username, password)
    if user_id:
        try:
            await clear_login_failures(username, ip)
        except Exception as e:
            logger.error(f'Reset throttle login gagal: {e}')
        session = request.session
        session.clear()
        session['logged_in'] = True
        session['user_id'] = user_id
        session['username'] = username
        session['last_activity'] = time.time()
        try:
            await run_sync(ensure_user_dashboard, user_id, username)
        except Exception as e:
            logger.error(f'ensure_user_dashboard failed: {e}')
        resp = RedirectResponse(url='/', status_code=303)
        resp.set_cookie('csrf_token', _new_csrf(), httponly=False,
                        samesite=config.SESSION_COOKIE_SAMESITE.lower(),
                        secure=bool(config.SESSION_COOKIE_SECURE))
        return resp

    logger.warning(f"Failed login attempt for user '{username}'")
    try:
        await record_login_failure(username, ip)
    except Exception as e:
        logger.error(f'Gagal mencatat kegagalan login: {e}')
    return _tpl(request, 'login.html', error='Username atau password salah!')


def _new_csrf():
    import secrets
    return secrets.token_urlsafe(32)


@router.post('/logout')
async def logout_post(request: Request):
    request.session.clear()
    return RedirectResponse(url='/login', status_code=303)


@router.get('/logout')
async def logout_get_compat(request: Request):
    return RedirectResponse(url='/login', status_code=303)
