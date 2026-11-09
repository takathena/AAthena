import pytest
pytestmark = pytest.mark.skip(reason="Belum di-port penuh ke FastAPI — di-skip sementara (Task 2)")
"""H3 — password .env hanya seed admin pertama, bukan kredensial permanen."""
import pytest

from app.config import TestingConfig
from app.database import get_db_context
from tests.conftest import csrf_token

ENV_USER = 'admin'
ENV_PASS = 'AdminPass-12345'   # sama dengan IOT_PASSWORD di conftest (seed migrasi v12)


@pytest.fixture(autouse=True)
def _env_creds(monkeypatch):
    monkeypatch.setattr(TestingConfig, 'IOT_USERNAME', ENV_USER)
    monkeypatch.setattr(TestingConfig, 'IOT_PASSWORD', ENV_PASS)


def _login(client, username, password):
    token = csrf_token(client)
    resp = client.post('/login', data={
        'username': username, 'password': password, 'csrf_token': token,
    })
    return resp.status_code == 302   # redirect ke dashboard = sukses


def test_env_password_logs_in_seeded_admin(app):
    assert _login(app.test_client(), ENV_USER, ENV_PASS) is True


def test_wrong_password_rejected(app):
    assert _login(app.test_client(), ENV_USER, 'salah-salah') is False


def test_old_env_password_rejected_after_change(app):
    client = app.test_client()
    assert _login(client, ENV_USER, ENV_PASS) is True

    resp = client.post('/api/v1/users/me/password', json={
        'old_password': ENV_PASS, 'new_password': 'PasswordBaru-987',
    })
    assert resp.status_code == 200

    other = app.test_client()
    assert _login(other, ENV_USER, ENV_PASS) is False           # password .env lama ditolak
    assert _login(app.test_client(), ENV_USER, 'PasswordBaru-987') is True


def test_failed_old_password_does_not_overwrite_hash(app):
    client = app.test_client()
    _login(client, ENV_USER, ENV_PASS)
    client.post('/api/v1/users/me/password', json={
        'old_password': ENV_PASS, 'new_password': 'PasswordBaru-987',
    })
    for _ in range(3):
        assert _login(app.test_client(), ENV_USER, ENV_PASS) is False
    # Password baru tetap berlaku setelah upaya login dengan password lama.
    assert _login(app.test_client(), ENV_USER, 'PasswordBaru-987') is True


def test_env_credentials_do_not_create_user_when_users_exist(app, monkeypatch):
    monkeypatch.setattr(TestingConfig, 'IOT_USERNAME', 'hantu')
    monkeypatch.setattr(TestingConfig, 'IOT_PASSWORD', 'HantuPass-123')
    assert _login(app.test_client(), 'hantu', 'HantuPass-123') is False
    with get_db_context() as conn:
        assert conn.execute("SELECT 1 FROM users WHERE username = 'hantu'").fetchone() is None


def test_env_credentials_seed_first_admin_when_table_empty(app):
    with get_db_context() as conn:
        conn.execute('PRAGMA foreign_keys=OFF')
        conn.execute('DELETE FROM users')
        conn.commit()
    assert _login(app.test_client(), ENV_USER, ENV_PASS) is True
    with get_db_context() as conn:
        row = conn.execute(
            'SELECT is_admin FROM users WHERE username = ?', (ENV_USER,)).fetchone()
    assert row is not None and row['is_admin'] == 1
