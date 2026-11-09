"""
NEXUS IoT - Authentication (Multi-User)
"""
import hmac
import time
from functools import wraps
from flask import (
    session, redirect, url_for, request, jsonify,
    Blueprint, render_template, current_app,
)
from flask_wtf.csrf import validate_csrf, generate_csrf
from werkzeug.security import check_password_hash, generate_password_hash
from app.config import get_config
from app.extensions import limiter
from app.database import get_db_context
from app import login_throttle

auth_bp = Blueprint('auth', __name__)


def _is_api_polling_request():
    """Return True kalau request ini adalah polling API (bukan interaksi user).

    Polling API tidak boleh memperpanjang sesi — kalau tidak, idle timeout
    tidak akan pernah aktif selama tab terbuka.
    """
    method = request.method.upper()
    path = request.path or ''

    if method != 'GET':
        return False

    # Halaman HTML (dashboard, device detail, dsb) => interaksi user
    if not path.startswith('/api/'):
        return False

    # Endpoint API yang tidak boleh memperpanjang sesi
    polling_prefixes = (
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
    return path.startswith(polling_prefixes)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Unauthorized'}), 401
            return redirect(url_for('auth.login_page'))

        config = get_config()
        idle_minutes = config.SESSION_IDLE_TIMEOUT_MINUTES
        now_ts = time.time()
        last_activity = session.get('last_activity')

        if last_activity and idle_minutes > 0:
            idle_seconds = now_ts - last_activity
            if idle_seconds > idle_minutes * 60:
                session.clear()
                if request.path.startswith('/api/'):
                    return jsonify({
                        'success': False,
                        'error': 'Session expired (idle)',
                        'code': 'SESSION_IDLE'
                    }), 401
                return redirect(url_for('auth.login_page'))

        # ✅ FIX: refresh last_activity hanya pada aksi user, bukan polling API
        if not _is_api_polling_request():
            session['last_activity'] = now_ts

        return f(*args, **kwargs)
    return decorated_function


def is_current_user_admin():
    """True jika user di session punya is_admin=1 di tabel users."""
    uid = session.get('user_id')
    if not uid:
        return False
    with get_db_context() as conn:
        row = conn.execute(
            'SELECT is_admin FROM users WHERE id = ?', (uid,)
        ).fetchone()
    return bool(row and row['is_admin'])


def admin_required(f):
    """Batasi route ke admin. Pasang SETELAH @login_required.

    Satu sumber kebenaran untuk otorisasi admin: backend selalu menolak
    non-admin dengan JSON 403, apa pun yang ditampilkan UI.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_current_user_admin():
            return jsonify({
                'success': False,
                'error': 'Hanya admin yang bisa mengakses fitur ini',
            }), 403
        return f(*args, **kwargs)
    return decorated_function


def _authenticate(username, password):
    """Autentikasi HANYA lewat hash di tabel users.

    IOT_USERNAME/IOT_PASSWORD (.env) hanya dipakai sekali sebagai seed admin
    pertama, yaitu ketika tabel users masih kosong. Setelah ada user, password
    .env tidak pernah menimpa atau menggantikan hash yang tersimpan.
    """
    with get_db_context() as conn:
        user = conn.execute(
            'SELECT id, password_hash FROM users WHERE username = ?', (username,)
        ).fetchone()

        if user:
            try:
                if check_password_hash(user['password_hash'], password):
                    return user['id']
            except Exception as e:
                current_app.logger.error(f"Verifikasi password gagal: {e}")
            return None

        total_users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        if total_users > 0:
            return None

        # Seed admin pertama dari .env (perbandingan timing-safe).
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
                '''INSERT INTO users (username, password_hash, display_name, is_admin, role)
                   VALUES (?, ?, 'Administrator', 1, 'superadmin')''',
                (username, generate_password_hash(password))
            )
            conn.commit()
            current_app.logger.info(f"Admin awal '{username}' dibuat dari .env (seed)")
            return cur.lastrowid
        except Exception as e:
            current_app.logger.error(f"Gagal membuat admin awal: {e}")
            return None


def ensure_user_dashboard(user_id, username):
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


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit(lambda: get_config().RATE_LIMIT_LOGIN, methods=['POST'])
def login_page():
    config = get_config()

    if request.method == 'POST':
        csrf_token_form = request.form.get('csrf_token', '').strip()
        if not csrf_token_form:
            return render_template('login.html', error='Sesi tidak valid. Muat ulang halaman.'), 400

        try:
            validate_csrf(csrf_token_form)
        except Exception as e:
            current_app.logger.warning(f"CSRF validation failed: {e}")
            return render_template('login.html', error='Sesi tidak valid. Muat ulang halaman.'), 400

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            return render_template('login.html', error='Username dan password wajib diisi!')

        client_ip = request.remote_addr or 'unknown'

        # Throttle kegagalan per username+IP dan per IP (dibagi antar worker lewat DB).
        # Dicek SEBELUM verifikasi password supaya tebakan tidak diproses selama terkunci.
        try:
            locked_for = login_throttle.check_locked(username, client_ip)
        except Exception as e:
            current_app.logger.error(f"Throttle login gagal dicek: {e}")
            locked_for = 0
        if locked_for > 0:
            minutes = max(1, (locked_for + 59) // 60)
            current_app.logger.warning(
                f"Login diblokir sementara untuk '{username}' dari {client_ip}"
            )
            return render_template(
                'login.html',
                error=f'Terlalu banyak percobaan gagal. Coba lagi dalam {minutes} menit.'
            ), 429

        user_id = _authenticate(username, password)

        if user_id:
            try:
                login_throttle.clear_failures(username, client_ip)
            except Exception as e:
                current_app.logger.error(f"Reset throttle login gagal: {e}")
            session.clear()
            session['logged_in'] = True
            session['user_id'] = user_id
            session['username'] = username
            session['last_activity'] = time.time()
            session.permanent = True

            generate_csrf()

            try:
                ensure_user_dashboard(user_id, username)
            except Exception as e:
                current_app.logger.error(f"ensure_user_dashboard failed: {e}")

            return redirect(url_for('views.dashboard'))

        current_app.logger.warning(
            f"Failed login attempt for user '{username}' from {request.remote_addr}"
        )
        try:
            login_throttle.record_failure(username, client_ip, config)
        except Exception as e:
            current_app.logger.error(f"Gagal mencatat kegagalan login: {e}")
        return render_template('login.html', error='Username atau password salah!')

    return render_template('login.html', error=None)


@auth_bp.route('/logout', methods=['POST'])
def logout():
    # POST + CSRF (CSRFProtect): tidak bisa dipicu dari halaman/gambar lain (M7).
    session.clear()
    return redirect(url_for('auth.login_page'))


@auth_bp.route('/logout', methods=['GET'])
def logout_get_compat():
    # Kompatibilitas bookmark/klien lama: hanya mengarahkan ke login,
    # TANPA mengakhiri sesi.
    return redirect(url_for('auth.login_page'))