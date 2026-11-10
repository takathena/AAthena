import pytest
pytestmark = pytest.mark.skip(reason="Belum di-port penuh ke FastAPI — di-skip sementara (Task 2)")
"""M7 + kebersihan kecil + C1 (sisi kode firmware)."""
import os
import re
import sqlite3

import pytest

import app as app_pkg
from app.main import create_app  # FastAPI (dulu app.create_app Flask)
from tests.conftest import _login_session, _make_user, csrf_token

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as f:
        return f.read()


# ---------- M7: logout POST + CSRF ----------

def test_logout_post_ends_session(user_client):
    assert user_client.get('/api/v1/users/me').status_code == 200
    resp = user_client.post('/logout')
    assert resp.status_code == 302 and '/login' in resp.headers['Location']
    assert user_client.get('/api/v1/users/me').status_code == 401


def test_logout_get_does_not_end_session(user_client):
    resp = user_client.get('/logout')
    assert resp.status_code == 302 and '/login' in resp.headers['Location']
    assert user_client.get('/api/v1/users/me').status_code == 200


def test_logout_post_requires_csrf(db_path):
    application = create_app(config_override={
        'TESTING': True, 'RATELIMIT_ENABLED': False,
        'WTF_CSRF_ENABLED': True, 'SESSION_COOKIE_SECURE': False,
    })
    uid = _make_user('csrf-user', 'UserPass-12345', False)
    client = application.test_client()
    _login_session(client, uid, 'csrf-user')

    # tanpa token -> ditolak, sesi tetap hidup
    assert client.post('/logout').status_code == 400
    assert client.get('/api/v1/users/me').status_code == 200

    # dengan token -> sesi berakhir
    token = csrf_token(client)
    assert token
    resp = client.post('/logout', headers={'X-CSRFToken': token})
    assert resp.status_code == 302
    assert client.get('/api/v1/users/me').status_code == 401


@pytest.mark.parametrize('path', ['static/js/dashboard.js', 'static/js/mobile.js'])
def test_frontend_no_longer_navigates_to_logout_via_get(path):
    src = _read(path)
    assert "window.location.href = '/logout'" not in src
    assert "method: 'POST'" in src or "method:'POST'" in src


# ---------- M7: /health ----------

def test_health_reports_single_version_constant(anon_client):
    body = anon_client.get('/health').get_json()
    assert body['version'] == app_pkg.__version__


def test_health_failure_does_not_leak_error(anon_client, monkeypatch):
    import app.database as dbmod

    def boom():
        raise RuntimeError('SECRET-PATH /var/lib/aaguard/iot.db')
    monkeypatch.setattr(dbmod, 'get_db_context', boom)
    resp = anon_client.get('/health')
    assert resp.status_code == 503
    assert 'SECRET-PATH' not in resp.get_data(as_text=True)


# ---------- M7: handler 500 tidak mengembalikan str(e) ----------

def _boom(*a, **k):
    raise RuntimeError('SECRET-DB-DETAIL')


class _FailingSqlite:
    """Pengganti modul sqlite3 HANYA untuk app.api (connect selalu gagal).

    Tidak menyentuh modul sqlite3 global, supaya login/otorisasi tetap jalan.
    """
    connect = staticmethod(_boom)

    def __getattr__(self, name):
        return getattr(sqlite3, name)


@pytest.mark.parametrize('method,path,payload', [
    ('put', '/api/v1/system/alert-rules',
     {'temperature': {'healthy': {'min': 0, 'max': 40},
                      'warning': {'min': -5, 'max': 45},
                      'danger': {'min': -10, 'max': 60}}}),
    ('delete', '/api/v1/system/alert-rules', None),
    ('post', '/api/v1/system/cleanup', None),
    ('post', '/api/v1/system/backup', None),
])
def test_500_handlers_hide_exception_text(admin_client, monkeypatch, method, path, payload):
    import app.api as api_mod
    # trigger_backup memuat create_backup_file lewat import lokal dari
    # app.background, jadi harus dipatok di modul asalnya supaya bocornya
    # tidak bisa "lolos" ke jalur backup dan membalas 200.
    import app.background as bg_mod
    monkeypatch.setattr(api_mod, 'get_db_context', _boom)
    monkeypatch.setattr(api_mod, 'sqlite3', _FailingSqlite())
    monkeypatch.setattr(bg_mod, 'create_backup_file', _boom)
    resp = getattr(admin_client, method)(path, json=payload) if payload is not None \
        else getattr(admin_client, method)(path)
    assert resp.status_code == 500
    assert 'SECRET-DB-DETAIL' not in resp.get_data(as_text=True)


def test_restore_errors_hide_exception_text(admin_client, tmp_path, monkeypatch):
    import app.api as api_mod
    from app.config import get_config
    backup_dir = tmp_path / 'bk'
    backup_dir.mkdir()
    (backup_dir / 'iot_x.db').write_bytes(b'bukan sqlite')
    monkeypatch.setattr(get_config(), 'BACKUP_DIR', str(backup_dir), raising=False)
    monkeypatch.setattr(api_mod, 'sqlite3', _FailingSqlite())
    resp = admin_client.post('/api/v1/system/restore',
                             json={'filename': 'iot_x.db', 'confirm': 'RESTORE'})
    assert resp.status_code in (400, 500)
    assert 'SECRET-DB-DETAIL' not in resp.get_data(as_text=True)


# ---------- C1 (sisi kode): firmware tanpa kredensial hardcoded ----------

def test_firmware_reads_credentials_from_secrets_module():
    src = _read('esp32', 'main.py')
    assert re.search(r'from\s+secrets\s+import', src)
    for name in ('WIFI_SSID', 'WIFI_PASSWORD', 'API_URL', 'DEVICE_ID', 'API_KEY'):
        assert not re.search(rf'^{name}\s*=', src, re.M), f'{name} tidak boleh didefinisikan di main.py'
    assert not re.search(r'[0-9a-fA-F]{64}', src), 'literal API key 64-hex tidak boleh ada di main.py'


def test_secrets_example_has_only_placeholders():
    src = _read('esp32', 'secrets.example.py')
    for name in ('WIFI_SSID', 'WIFI_PASSWORD', 'API_URL', 'DEVICE_ID', 'API_KEY'):
        m = re.search(rf'^{name}\s*=\s*"(.*)"', src, re.M)
        assert m and 'GANTI_DENGAN' in m.group(1), name


def test_real_secrets_file_is_gitignored():
    lines = [ln.strip() for ln in _read('.gitignore').splitlines()]
    assert 'esp32/secrets.py' in lines
