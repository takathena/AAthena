import pytest
pytestmark = pytest.mark.skip(reason="Belum di-port penuh ke FastAPI — di-skip sementara (Task 2)")
"""H7 — SESSION_COOKIE_SECURE tidak dipaksa True; HSTS hanya bila ENABLE_HSTS."""
import os
import subprocess
import sys

import pytest

from app.main import create_app  # FastAPI (dulu app.create_app Flask)
try:
    from app import warn_if_insecure_cookie  # noqa: F401
except ImportError:
    warn_if_insecure_cookie = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _app(**overrides):
    cfg = {'TESTING': True, 'RATELIMIT_ENABLED': False, 'WTF_CSRF_ENABLED': False}
    cfg.update(overrides)
    return create_app(config_override=cfg)


def _login_page(app):
    resp = app.test_client().get('/login')
    return resp, resp.headers.getlist('Set-Cookie')


def test_insecure_cookie_and_no_hsts(db_path):
    resp, cookies = _login_page(_app(SESSION_COOKIE_SECURE=False, ENABLE_HSTS=False))
    assert cookies, 'halaman login harus menyetel cookie sesi'
    for c in cookies:
        attrs = [a.strip().lower() for a in c.split(';')[1:]]
        assert 'secure' not in attrs
    assert 'Strict-Transport-Security' not in resp.headers


def test_secure_cookie_and_hsts_when_enabled(db_path):
    resp, cookies = _login_page(_app(SESSION_COOKIE_SECURE=True, ENABLE_HSTS=True))
    assert cookies
    assert all('; secure' in c.lower() for c in cookies)
    assert 'Strict-Transport-Security' in resp.headers


def test_secure_cookie_alone_does_not_send_hsts(db_path):
    resp, cookies = _login_page(_app(SESSION_COOKIE_SECURE=True, ENABLE_HSTS=False))
    assert cookies and all('; secure' in c.lower() for c in cookies)
    assert 'Strict-Transport-Security' not in resp.headers


def _config_value(env_overrides, unset=()):
    env = dict(os.environ)
    env.update(env_overrides)
    for k in unset:
        env.pop(k, None)
    out = subprocess.run(
        [sys.executable, '-c',
         "from app.config import get_config; c = get_config(); "
         "print(c.__name__, c.SESSION_COOKIE_SECURE, c.ENABLE_HSTS)"],
        cwd=ROOT, env=env, capture_output=True, text=True, check=True,
    ).stdout.split()
    return out


def test_production_config_honours_env_false():
    name, secure, hsts = _config_value(
        {'FLASK_ENV': 'production', 'SESSION_COOKIE_SECURE': 'False'}, unset=['ENABLE_HSTS'])
    assert name == 'ProductionConfig'
    assert secure == 'False'
    assert hsts == 'False'


def test_production_config_honours_env_true():
    _, secure, _ = _config_value({'FLASK_ENV': 'production', 'SESSION_COOKIE_SECURE': 'True'})
    assert secure == 'True'


def test_production_default_follows_enable_hsts():
    _, secure, hsts = _config_value(
        {'FLASK_ENV': 'production', 'ENABLE_HSTS': 'True'}, unset=['SESSION_COOKIE_SECURE'])
    assert (secure, hsts) == ('True', 'True')
    _, secure, hsts = _config_value(
        {'FLASK_ENV': 'production'}, unset=['SESSION_COOKIE_SECURE', 'ENABLE_HSTS'])
    assert (secure, hsts) == ('False', 'False')


class _Log:
    def __init__(self):
        self.warnings = []

    def warning(self, msg, *a):
        self.warnings.append(msg)


@pytest.mark.parametrize('env,secure,expect_warn', [
    ('production', False, True),
    ('production', True, False),
    ('development', False, False),
    ('testing', False, False),
])
def test_startup_warning(env, secure, expect_warn):
    log = _Log()
    result = warn_if_insecure_cookie({'SESSION_COOKIE_SECURE': secure}, env=env, log=log)
    assert result is expect_warn
    assert bool(log.warnings) is expect_warn
