"""Fase 5 — rilis V6.5: versi tunggal, pemisahan dependensi dev, CI, Makefile."""
import os
import re

import app as app_pkg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXPECTED_VERSION = '2.0.0'


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as f:
        return f.read()


def _make_target_block(makefile, target):
    """Isi (resep) satu target Makefile, sampai target/baris kosong berikutnya."""
    m = re.search(r'^%s:[^\n]*\n((?:\t[^\n]*\n?)*)' % re.escape(target), makefile, re.M)
    assert m, 'target %s tidak ditemukan di Makefile' % target
    return m.group(1)


# ---------- Versi tunggal ----------

def test_version_constant_is_v2_0():
    assert app_pkg.__version__ == EXPECTED_VERSION


def test_health_and_system_info_report_same_version(admin_client):
    health = admin_client.get('/health').get_json()
    assert health['version'] == app_pkg.__version__

    r = admin_client.get('/api/v1/system/info')
    assert r.status_code == 200
    # Sebelumnya hardcode '4.3' sehingga UI "Versi Aplikasi" menampilkan angka usang.
    assert r.get_json()['info']['version'] == app_pkg.__version__


def test_readme_badge_matches_version():
    m = re.search(r'badge/version-([0-9][0-9.]*)-', _read('README.md'))
    assert m, 'badge versi tidak ada di README'
    assert m.group(1) == app_pkg.__version__


def test_changelog_has_heading_for_current_version():
    assert '## V%s' % app_pkg.__version__ in _read('CHANGELOG.md')


def test_readme_gunicorn_version_matches_requirements():
    pinned = re.search(r'^gunicorn==([0-9.]+)', _read('requirements.txt'), re.M | re.I)
    assert pinned
    ver = pinned.group(1)
    readme = _read('README.md')
    assert 'Gunicorn-%s-' % ver in readme   # badge
    assert re.search(r'\|\s*WSGI Server\s*\|\s*Gunicorn\s*\|\s*%s\s*\|' % re.escape(ver), readme)


# ---------- Dependensi dev terpisah ----------

def test_dev_requirements_are_separate_from_production():
    dev = _read('requirements-dev.txt')
    assert re.search(r'^-r\s+requirements\.txt', dev, re.M)
    assert re.search(r'^pytest', dev, re.M | re.I)
    assert re.search(r'^ruff', dev, re.M | re.I)

    prod = _read('requirements.txt').lower()
    assert 'pytest' not in prod
    assert 'ruff' not in prod


def test_docker_image_does_not_install_dev_requirements():
    assert 'requirements-dev' not in _read('Dockerfile')
    assert '.github/' in _read('.dockerignore')
    assert 'requirements-dev.txt' in _read('.dockerignore')


# ---------- CI ----------

def test_ci_workflow_runs_lint_and_tests_on_python_311():
    ci = _read('.github', 'workflows', 'ci.yml')
    assert re.search(r'python-version:\s*["\']?3\.11', ci)
    assert 'requirements-dev.txt' in ci
    assert 'ruff check' in ci
    assert 'pytest' in ci
    assert 'pull_request' in ci and 'push' in ci


# ---------- Makefile ----------

def test_make_test_runs_pytest_not_health_curl():
    block = _make_target_block(_read('Makefile'), 'test')
    assert 'pytest' in block
    assert 'curl' not in block


def test_make_lint_uses_ruff_and_does_not_swallow_failures():
    block = _make_target_block(_read('Makefile'), 'lint')
    assert 'ruff check' in block
    assert '2>/dev/null' not in block
    assert '||' not in block


def test_make_dev_installs_dev_requirements():
    mk = _read('Makefile')
    assert 'requirements-dev.txt' in mk
