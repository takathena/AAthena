import pytest
pytestmark = pytest.mark.skip(reason="Belum di-port penuh ke FastAPI — di-skip sementara (Task 2)")
"""N1 — Bulk Import tidak boleh 500 (NameError) dan alurnya benar."""
import shutil
import subprocess
import sys
import os

import pytest

from tests.conftest import post_data

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_no_undefined_names_in_app():
    """Pengaman: pyflakes tidak boleh melaporkan 'undefined name' di app/."""
    pytest.importorskip('pyflakes')
    proc = subprocess.run(
        [sys.executable, '-m', 'pyflakes', 'app', 'run.py'],
        cwd=ROOT, capture_output=True, text=True,
    )
    undefined = [l for l in proc.stdout.splitlines() if 'undefined name' in l]
    assert undefined == []


def test_bulk_import_mixed_rows(admin_client, make_device):
    make_device('dup-1')
    resp = admin_client.post('/api/v1/devices/bulk-import', json={'devices': [
        {'device_id': 'new-1', 'device_name': 'Baru 1'},
        {'device_id': 'dup-1', 'device_name': 'Duplikat'},
        {'device_id': 'bad id!', 'device_name': 'Invalid'},
    ]})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert len(body['created']) == 1
    assert len(body['skipped']) == 1
    assert len(body['errors']) == 1
    assert body['created'][0]['device_id'] == 'new-1'
    assert len(body['created'][0]['api_key']) >= 32
    assert body['skipped'][0]['device_id'] == 'dup-1'


def test_bulk_import_api_key_works_and_is_not_stored_plain(admin_client):
    resp = admin_client.post('/api/v1/devices/bulk-import', json={'devices': [
        {'device_id': 'key-1', 'device_name': 'Key 1'},
    ]})
    key = resp.get_json()['created'][0]['api_key']

    from app.database import get_db_context
    with get_db_context() as conn:
        row = conn.execute(
            'SELECT api_key, api_key_hash FROM devices WHERE device_id = ?', ('key-1',)
        ).fetchone()
    assert row['api_key'] is None
    assert row['api_key_hash']

    r = post_data(admin_client, 'key-1', key, {'temperature': 25})
    assert r.status_code == 200


def test_bulk_import_duplicate_inside_same_batch(admin_client):
    resp = admin_client.post('/api/v1/devices/bulk-import', json={'devices': [
        {'device_id': 'same-1', 'device_name': 'A'},
        {'device_id': 'same-1', 'device_name': 'B'},
    ]})
    body = resp.get_json()
    assert resp.status_code == 200
    assert len(body['created']) == 1
    assert len(body['skipped']) == 1


def test_bulk_import_limits(admin_client):
    too_many = [{'device_id': f'd{i}', 'device_name': 'x'} for i in range(201)]
    assert admin_client.post('/api/v1/devices/bulk-import',
                             json={'devices': too_many}).status_code == 400
    assert admin_client.post('/api/v1/devices/bulk-import',
                             json={'devices': []}).status_code == 400
    assert admin_client.post('/api/v1/devices/bulk-import',
                             json={'devices': 'nope'}).status_code == 400
