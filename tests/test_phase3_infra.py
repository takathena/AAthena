"""H5 + M9 — konfigurasi Nginx/Gunicorn/compose/dependensi/port (pemeriksaan statis)."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as fh:
        return fh.read()


def test_nginx_chat_location_has_long_read_timeout():
    conf = _read('nginx', 'conf.d', 'nexus.conf')
    m = re.search(r'location\s+/api/v1/chat\s*\{(.*?)\n    \}', conf, re.S)
    assert m, 'harus ada location /api/v1/chat'
    secs = int(re.search(r'proxy_read_timeout\s+(\d+)s', m.group(1)).group(1))
    assert secs >= 180                                    # >= LLM_TIMEOUT(120) x 1,5


def test_nginx_connection_header_uses_map_not_constant_upgrade():
    conf = _read('nginx', 'conf.d', 'nexus.conf')
    assert re.search(r'map\s+\$http_upgrade\s+\$connection_upgrade', conf)
    assert 'Connection "upgrade"' not in conf
    assert 'proxy_set_header Connection $connection_upgrade' in conf


def test_gunicorn_flags_and_version():
    docker = _read('Dockerfile')
    for flag in ('--timeout', '--graceful-timeout', '--max-requests', '--max-requests-jitter'):
        assert flag in docker
    m = re.search(r'^gunicorn==(\d+)\.', _read('requirements.txt'), re.M)
    assert m and int(m.group(1)) >= 22                    # CVE-2024-1135


def test_public_port_is_consistent_5008():
    env = _read('.env.example')
    assert re.search(r'^NGINX_PORT=4455$', env, re.M)
    assert re.search(r'NGINX_PORT:-[0-9]+', _read('docker-compose.yml'))
    cors = re.search(r'^CORS_ORIGINS=(.*)$', env, re.M).group(1)
    assert ':4455' in cors and ':8080' not in cors
    # Firmware takes the endpoint from secrets.py; main.py only imports it.
    # The example is what a new deployment copies.
    assert re.search(r':[0-9]+/api/v1/data', _read('esp32', 'secrets.example.py'))
    assert 'API_URL' in _read('esp32', 'main.py')


def test_prod_compose_does_not_mount_application_code():
    compose = _read('docker-compose.yml')
    app_block = compose.split('nginx:')[0]                 # layanan nexus-iot
    for mount in ('./app:', './templates:', './run.py:'):
        assert mount not in app_block
    assert './static:/app/static' not in app_block
    assert './static:/static:ro' in compose                # Nginx tetap menyajikan static
    override = _read('docker-compose.override.yml')
    assert './app:/app/app' in override
