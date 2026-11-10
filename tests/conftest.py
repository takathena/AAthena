"""Fixture bersama untuk tes AAguard IoT (FastAPI).

Env harus di-set SEBELUM `app` diimpor, karena app/config.py membaca
env saat import.
"""
import os
import re
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix='aaguard-tests-')
os.environ['FLASK_ENV'] = 'testing'
os.environ['SECRET_KEY'] = 'test-secret-key-for-testing-only-32chars-minimum'
os.environ['IOT_USERNAME'] = 'admin'
os.environ['IOT_PASSWORD'] = 'AdminPass-12345'
os.environ['DB_PATH'] = os.path.join(_TMP, 'boot.db')
os.environ['LOG_FILE'] = os.path.join(_TMP, 'aaguard.log')
os.environ['AAGUARD_LOCK_DIR'] = _TMP
os.environ['BACKUP_DIR'] = os.path.join(_TMP, 'backup')

# app/config.py memanggil load_dotenv() saat import. Tanpa ini, file .env
# sungguhan di root repo ikut terbaca dan test yang bergantung pada "env var
# tidak di-set" ikut gagal (mis. test SESSION_COOKIE_SECURE vs ENABLE_HSTS).
# Test harus hermetik: hanya env yang disetel di sini/oleh monkeypatch yang berlaku.
os.environ['PYTHON_DOTENV_DISABLED'] = '1'

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

from app.main import app as fastapi_app  # noqa: E402
from app.config import Config  # noqa: E402
from app.database import close_db, get_db_context, init_db  # noqa: E402
from app.utils import generate_api_key, hash_api_key  # noqa: E402
from app import alerts as alerts_module  # noqa: E402


class CompatResponse:
    """Bungkus httpx.Response agar tes lama (idiom Flask) tetap jalan."""

    def __init__(self, resp):
        object.__setattr__(self, '_resp', resp)
        object.__setattr__(self, 'status_code', resp.status_code)
        object.__setattr__(self, 'headers', resp.headers)
        object.__setattr__(self, 'text', resp.text)
        object.__setattr__(self, 'content', resp.content)

    def get_json(self):
        try:
            return self._resp.json()
        except Exception:
            return None

    def get_data(self, as_text=False):
        return self._resp.text if as_text else self._resp.content

    def json(self):
        return self._resp.json()

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, '_resp'), name)


class CompatClient:
    """TestClient Starlette + CSRF otomatis (sama seperti X-CSRFToken di UI)."""

    def __init__(self, app):
        self._tc = TestClient(app, raise_server_exceptions=False)

    @property
    def cookies(self):
        return self._tc.cookies

    @cookies.setter
    def cookies(self, value):
        self._tc.cookies = value

    def _headers_for(self, method, url, headers):
        h = dict(headers or {})
        if method.upper() in ('GET', 'HEAD', 'OPTIONS'):
            return h
        path = str(url).split('?')[0]
        if (method.upper() == 'POST' and path == '/api/v1/data') or path == '/login':
            return h
        if 'x-csrftoken' in {k.lower() for k in h}:
            return h
        try:
            tok = self._tc.cookies.get('csrf_token')
        except Exception:
            tok = None
        if tok:
            h['X-CSRFToken'] = tok
        return h

    def _call(self, method, url, **kwargs):
        headers = kwargs.pop('headers', None)
        kwargs['headers'] = self._headers_for(method, url, headers)
        fn = getattr(self._tc, method.lower())
        return CompatResponse(fn(url, **kwargs))

    def get(self, url, **kwargs):
        return self._call('GET', url, **kwargs)

    def post(self, url, **kwargs):
        return self._call('POST', url, **kwargs)

    def put(self, url, **kwargs):
        return self._call('PUT', url, **kwargs)

    def delete(self, url, **kwargs):
        return self._call('DELETE', url, **kwargs)

    def patch(self, url, **kwargs):
        return self._call('PATCH', url, **kwargs)


def _cookie_token(client):
    try:
        tok = client.cookies.get('csrf_token')
    except Exception:
        tok = None
    return tok or ''


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / 'iot.db')
    monkeypatch.setattr(Config, 'DB_PATH', path)
    return path


@pytest.fixture
def app(db_path):
    from app.deps import limiter
    alerts_module.invalidate_global_rules_cache()
    prev_enabled = limiter.enabled
    limiter.enabled = False
    try:
        limiter.reset()
    except Exception:
        pass
    init_db()
    yield fastapi_app
    close_db()
    try:
        limiter.reset()
    except Exception:
        pass
    limiter.enabled = prev_enabled
    alerts_module.invalidate_global_rules_cache()


def _login_session(client, user_id, username):
    """Compat lama (Flask session_transaction). FastAPI: pakai form login.

    Hanya disediakan agar modul lama tetap bisa diimpor; panggilannya
    hanya valid lewat admin_client/user_client.
    """
    raise RuntimeError(
        'Flask session_transaction sudah diganti FastAPI login form; '
        'pakai admin_client/user_client')


def _make_user(username, password, is_admin):
    with get_db_context() as conn:
        cur = conn.execute(
            'INSERT INTO users (username, password_hash, display_name, is_admin) '
            'VALUES (?, ?, ?, ?)',
            (username, generate_password_hash(password), username, 1 if is_admin else 0),
        )
        conn.commit()
        return cur.lastrowid


def _login_via_form(client, username, password):
    """Login lewat POST /login FastAPI (cookie session + csrf_token)."""
    client.get('/login')
    token = _cookie_token(client)
    if not token:
        html = client.get('/login').text
        m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html) or \
            re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html)
        token = m.group(1) if m else ''
    return client.post('/login', data={
        'username': username, 'password': password, 'csrf_token': token,
    })


@pytest.fixture
def admin_client(app):
    _make_user('adm1', 'AdminPass-12345', True)
    client = CompatClient(app)
    _login_via_form(client, 'adm1', 'AdminPass-12345')
    return client


@pytest.fixture
def user_client(app):
    _make_user('usr1', 'UserPass-12345', False)
    client = CompatClient(app)
    _login_via_form(client, 'usr1', 'UserPass-12345')
    return client


@pytest.fixture
def anon_client(app):
    return CompatClient(app)


@pytest.fixture
def make_device(app):
    """Buat device langsung di DB; return API key (plain)."""
    def _make(device_id='dev-1', device_name='Device 1', device_type='ESP32',
              alert_rules_json=None, expected_interval=60, offline_timeout=900):
        api_key = generate_api_key()
        with get_db_context() as conn:
            conn.execute(
                'INSERT INTO devices (device_id, device_name, device_type, '
                'api_key, api_key_hash, alert_rules, expected_interval, offline_timeout) '
                'VALUES (?, ?, ?, NULL, ?, ?, ?, ?)',
                (device_id, device_name, device_type, hash_api_key(api_key),
                 alert_rules_json, expected_interval, offline_timeout),
            )
            conn.commit()
        return api_key
    return _make


def csrf_token(client):
    """Ambil token CSRF dari cookie sesudah GET /login (FastAPI double-submit)."""
    tok = _cookie_token(client)
    if tok:
        return tok
    text = ''
    try:
        text = client.get('/login').text
    except Exception:
        try:
            text = client.get('/login').get_data(as_text=True)
        except Exception:
            text = ''
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', text) or \
        re.search(r'value="([^"]+)"[^>]*name="csrf_token"', text)
    if m:
        return m.group(1)
    return _cookie_token(client)


def post_data(client, device_id, api_key, data, sensor_type='sensor'):
    return client.post('/api/v1/data', json={
        'device_id': device_id,
        'api_key': api_key,
        'sensor_type': sensor_type,
        'data': data,
    })


def active_alert_types(device_id):
    with get_db_context() as conn:
        rows = conn.execute(
            'SELECT alert_type FROM alerts WHERE device_id = ? AND is_active = 1',
            (device_id,),
        ).fetchall()
    return {r['alert_type'] for r in rows}
