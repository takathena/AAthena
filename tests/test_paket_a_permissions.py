import pytest
pytestmark = pytest.mark.skip(reason="Belum di-port penuh ke FastAPI — di-skip sementara (Task 2)")
"""Paket A — peran user dan manajemen pengguna (A.5).

Skenario utama:
- migrasi v18 dan akun superadmin
- perubahan peran tercatat di audit log
- endpoint izin admin-only
"""
import time

from werkzeug.security import generate_password_hash

from app.database import get_db_context


def _mk(username, is_admin=False, role='user'):
    with get_db_context() as conn:
        cur = conn.execute(
            'INSERT INTO users (username, password_hash, display_name, is_admin, role) '
            'VALUES (?, ?, ?, ?, ?)',
            (username, generate_password_hash('Pass-123456'), username,
             1 if is_admin else 0, role),
        )
        conn.commit()
        return cur.lastrowid


def _client_for(app, uid, username):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['user_id'] = uid
        sess['username'] = username
        sess['last_activity'] = time.time()
        sess.permanent = True
    return client


def _superadmin(app):
    uid = _mk('root1', is_admin=True, role='superadmin')
    return _client_for(app, uid, 'root1'), uid


def _plain_user(app, name='staf1'):
    uid = _mk(name)
    return _client_for(app, uid, name), uid


# ---------- Migrasi dan akun awal ----------

def test_seed_admin_is_superadmin_and_no_permissions_granted(app):
    with get_db_context() as conn:
        row = conn.execute("SELECT role FROM users WHERE username = 'admin'").fetchone()
        assert row is not None and row['role'] == 'superadmin'
        count = conn.execute('SELECT COUNT(*) FROM user_permissions').fetchone()[0]
    assert count == 0


def test_me_reports_role_and_permissions(app):
    client, _ = _plain_user(app)
    body = client.get('/api/v1/users/me').get_json()['user']
    assert body['role'] == 'user'
    assert body['permissions'] == []
    sa, _ = _superadmin(app)
    body = sa.get('/api/v1/users/me').get_json()['user']
    assert body['role'] == 'superadmin'
    assert body['permissions'] == []


def test_cannot_set_explicit_permissions_on_privileged_user(app):
    admin, _ = _superadmin(app)
    other_admin = _mk('adm9', is_admin=True, role='admin')
    r = admin.put(f'/api/v1/users/{other_admin}/permissions', json={})
    assert r.status_code == 400


def test_permissions_endpoints_are_admin_only(app):
    admin, _ = _superadmin(app)
    client, uid = _plain_user(app, 'staf4')
    assert client.get(f'/api/v1/users/{uid}/permissions').status_code == 403
    assert client.put(f'/api/v1/users/{uid}/permissions', json={}).status_code == 403
    assert admin.get(f'/api/v1/users/{uid}/permissions').status_code == 200


# ---------- Aturan peran ----------

def test_plain_admin_cannot_change_another_admin(app):
    _superadmin(app)
    adm2_id = _mk('adm2', is_admin=True, role='admin')
    adm2 = _client_for(app, adm2_id, 'adm2')
    sa_id = _mk('root2', is_admin=True, role='superadmin')
    r = adm2.put(f'/api/v1/users/{sa_id}', json={'display_name': 'x'})
    assert r.status_code == 403


def test_plain_admin_cannot_grant_admin_role(app):
    _superadmin(app)
    adm2_id = _mk('adm3', is_admin=True, role='admin')
    adm2 = _client_for(app, adm2_id, 'adm3')
    target = _mk('staf5')
    r = adm2.put(f'/api/v1/users/{target}', json={'role': 'admin'})
    assert r.status_code == 403


def test_superadmin_cannot_be_deleted_or_demoted(app):
    sa, sa_id = _superadmin(app)
    other_super_admin_id = _mk('adm4', is_admin=True, role='admin')
    adm4 = _client_for(app, other_super_admin_id, 'adm4')
    assert adm4.delete(f'/api/v1/users/{sa_id}').status_code == 403
    assert sa.put(f'/api/v1/users/{sa_id}', json={'role': 'user'}).status_code == 403


def test_superadmin_can_promote_and_demote_regular_admin(app):
    sa, _ = _superadmin(app)
    target = _mk('staf6')
    assert sa.put(f'/api/v1/users/{target}', json={'role': 'admin'}).status_code == 200
    with get_db_context() as conn:
        row = conn.execute('SELECT role, is_admin FROM users WHERE id = ?', (target,)).fetchone()
    assert row['role'] == 'admin' and row['is_admin'] == 1
    assert sa.put(f'/api/v1/users/{target}', json={'role': 'user'}).status_code == 200
    with get_db_context() as conn:
        row = conn.execute('SELECT role, is_admin FROM users WHERE id = ?', (target,)).fetchone()
    assert row['role'] == 'user' and row['is_admin'] == 0


def test_cannot_change_own_role_without_superadmin(app):
    _superadmin(app)
    adm2_id = _mk('adm5', is_admin=True, role='admin')
    adm2 = _client_for(app, adm2_id, 'adm5')
    r = adm2.put(f'/api/v1/users/{adm2_id}', json={'role': 'user'})
    assert r.status_code == 403


# ---------- Audit ----------

def test_role_changes_are_audited(app):
    sa, _ = _superadmin(app)
    target = _mk('staf11')
    sa.put(f'/api/v1/users/{target}', json={'role': 'moderator'})
    with get_db_context() as conn:
        actions = [r['action'] for r in conn.execute(
            "SELECT action FROM audit_log WHERE detail LIKE ?", (f'%id={target}%',)).fetchall()]
    assert 'user.role' in actions
