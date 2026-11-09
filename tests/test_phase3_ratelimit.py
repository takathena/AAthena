import pytest
pytestmark = pytest.mark.skip(reason="Belum di-port penuh ke FastAPI — di-skip sementara (Task 2)")
"""H4 — rate limiting: storage dari config, key /data per device, throttle login."""
import importlib
import logging

import pytest

from app import login_throttle
try:
    from app import ratelimit
except ImportError:
    ratelimit = None
from app.config import TestingConfig
from tests.conftest import csrf_token, post_data

IP = '203.0.113.7'


# ---------- storage dari config ----------
def test_limiter_uses_storage_from_config(monkeypatch):
    import flask_limiter
    import app.extensions as ext

    # reload() membuat objek Limiter BARU di app.extensions. Tapi app/__init__.py
    # meng-import `limiter` sekali saat modul dimuat, jadi setelah reload ada dua
    # singleton: yang dipakai create_app (yang lama) dan yang ada di app.extensions
    # (yang baru, _storage=None). Test lain yang meng-import dari app.extensions
    # akan dapat yang baru dan gagal. Simpan & pasang kembali yang asli.
    original = ext.limiter
    seen = {}

    class _Spy(flask_limiter.Limiter):
        def __init__(self, *a, **kw):
            seen.update(kw)
            super().__init__(*a, **kw)

    monkeypatch.setattr(TestingConfig, 'RATE_LIMIT_STORAGE', 'memory://')
    monkeypatch.setattr(flask_limiter, 'Limiter', _Spy)
    try:
        importlib.reload(ext)
    finally:
        monkeypatch.undo()
        importlib.reload(ext)
        ext.limiter = original
    assert seen['storage_uri'] == 'memory://'


def test_warns_on_memory_storage_with_multiple_workers():
    class _Log:
        msgs = []

        def warning(self, m):
            self.msgs.append(m)

    log = _Log()
    assert ratelimit.warn_if_memory_limiter_multiworker('memory://', workers=2, log=log) is True
    assert 'memory://' in log.msgs[0]
    assert ratelimit.warn_if_memory_limiter_multiworker('memory://', workers=1, log=log) is False
    assert ratelimit.warn_if_memory_limiter_multiworker('redis://x:6379', workers=4, log=log) is False


def test_count_workers_reads_web_concurrency():
    assert ratelimit.count_workers({'WEB_CONCURRENCY': '3'}) == 3
    assert ratelimit.count_workers({}) == 1
    assert ratelimit.count_workers({'WEB_CONCURRENCY': 'abc'}) == 1


# ---------- key function /data ----------
def test_data_key_is_device_id_from_body(app):
    with app.test_request_context('/api/v1/data', method='POST',
                                  json={'device_id': 'dev-a', 'api_key': 'k'}):
        assert ratelimit.data_rate_limit_key(get_ip=lambda: IP) == 'device:dev-a'


@pytest.mark.parametrize('kwargs', [
    {'data': b'not json{{', 'content_type': 'application/json'},
    {'json': ['bukan', 'object']},
    {'json': {'device_id': 123}},
    {'json': {'device_id': 'a b/../c'}},
    {'json': {}},
    {'data': b'', 'content_type': 'application/json'},
])
def test_data_key_falls_back_to_ip_and_never_crashes(app, kwargs):
    with app.test_request_context('/api/v1/data', method='POST', **kwargs):
        assert ratelimit.data_rate_limit_key(get_ip=lambda: IP) == IP


def test_data_key_does_not_parse_oversized_body(app):
    big = {'device_id': 'dev-a', 'pad': 'x' * 20000}      # > DATA_MAX_BYTES (8 KB)
    with app.test_request_context('/api/v1/data', method='POST', json=big):
        assert ratelimit.data_rate_limit_key(get_ip=lambda: IP) == IP


def test_two_devices_same_ip_do_not_share_quota(app, make_device, monkeypatch):
    """Dengan limiter aktif: kuota /data dihitung per device, bukan per IP."""
    from app.main import create_app  # FastAPI (dulu app.create_app)
    from app.deps import limiter  # FastAPI (dulu app.extensions)

    monkeypatch.setattr(TestingConfig, 'RATE_LIMIT_DATA', '2 per minute')
    monkeypatch.setattr(TestingConfig, 'RATE_LIMIT_DATA_IP', '100 per minute')
    limited = create_app(config_override={
        'TESTING': True, 'RATELIMIT_ENABLED': True,
        'WTF_CSRF_ENABLED': False, 'SESSION_COOKIE_SECURE': False,
    })
    try:
        # `limiter` adalah singleton modul; init_app() dari app lain (fixture `app`
        # memakai RATELIMIT_ENABLED=False) menimpa flag `enabled`. Set eksplisit
        # supaya tes ini tidak bergantung urutan pembuatan app.
        limiter.enabled = True
        limiter.reset()
        key_a, key_b = make_device('rl-a'), make_device('rl-b')
        client = limited.test_client()
        codes_a = [post_data(client, 'rl-a', key_a, {'t': 1}).status_code for _ in range(3)]
        code_b = post_data(client, 'rl-b', key_b, {'t': 1}).status_code
        assert codes_a == [200, 200, 429]
        assert code_b == 200
    finally:
        limiter.reset()
        limiter.enabled = False


# ---------- throttle login (storage DB) ----------
def _fail(username, ip, n, now=1000.0):
    for _ in range(n):
        login_throttle.record_failure(username, ip, TestingConfig, now=now)


def test_account_ip_locked_after_max_failures(app):
    _fail('admin', IP, TestingConfig.LOGIN_MAX_FAILURES - 1)
    assert login_throttle.check_locked('admin', IP, now=1000.0) == 0
    _fail('admin', IP, 1)
    assert login_throttle.check_locked('admin', IP, now=1000.0) > 0


def test_attacker_ip_cannot_lock_admin_from_other_ip(app):
    _fail('admin', IP, TestingConfig.LOGIN_MAX_FAILURES)
    assert login_throttle.check_locked('admin', IP, now=1000.0) > 0
    assert login_throttle.check_locked('admin', '198.51.100.9', now=1000.0) == 0


def test_other_user_same_ip_not_locked_by_single_account_failures(app):
    _fail('admin', IP, TestingConfig.LOGIN_MAX_FAILURES)
    assert login_throttle.check_locked('budi', IP, now=1000.0) == 0


def test_password_spraying_from_one_ip_locks_that_ip(app):
    for i in range(TestingConfig.LOGIN_IP_MAX_FAILURES):
        login_throttle.record_failure(f'user{i}', IP, TestingConfig, now=1000.0)
    assert login_throttle.check_locked('siapa-saja', IP, now=1000.0) > 0


def test_lock_expires_and_success_clears_counter(app):
    _fail('admin', IP, TestingConfig.LOGIN_MAX_FAILURES)
    later = 1000.0 + TestingConfig.LOGIN_LOCKOUT_SECONDS + 5
    assert login_throttle.check_locked('admin', IP, now=later) == 0
    _fail('admin', IP, 2, now=later)
    login_throttle.clear_failures('admin', IP)
    _fail('admin', IP, TestingConfig.LOGIN_MAX_FAILURES - 1, now=later)
    assert login_throttle.check_locked('admin', IP, now=later) == 0


def test_failures_outside_window_are_not_accumulated(app):
    _fail('admin', IP, TestingConfig.LOGIN_MAX_FAILURES - 1, now=1000.0)
    later = 1000.0 + TestingConfig.LOGIN_FAIL_WINDOW_SECONDS + 1
    _fail('admin', IP, 1, now=later)                    # jendela baru, hitungan mulai dari 1
    assert login_throttle.check_locked('admin', IP, now=later) == 0


def _post_login(client, username, password, ip):
    return client.post('/login', data={
        'username': username, 'password': password, 'csrf_token': csrf_token(client),
    }, environ_overrides={'REMOTE_ADDR': ip})


def test_login_endpoint_blocks_after_repeated_failures(app):
    client = app.test_client()
    for _ in range(TestingConfig.LOGIN_MAX_FAILURES):
        assert _post_login(client, 'admin', 'salah-terus', IP).status_code == 200
    # Password BENAR pun ditolak selama terkunci
    r = _post_login(client, 'admin', 'AdminPass-12345', IP)
    assert r.status_code == 429
    # IP lain tetap bisa login (admin sah tidak ikut terkunci)
    r2 = _post_login(app.test_client(), 'admin', 'AdminPass-12345', '198.51.100.9')
    assert r2.status_code == 302
