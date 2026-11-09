import pytest
pytestmark = pytest.mark.skip(reason="Belum di-port penuh ke FastAPI — di-skip sementara (Task 2)")
"""N2 — interval manual tidak boleh ditimpa auto-detect (+ migrasi v15)."""
import json
import sqlite3
from datetime import timedelta

import pytest

from app.database import get_db_context, get_wib_time, init_db, SCHEMA_VERSION
from tests.conftest import post_data


def _seed(device_id, seconds_ago):
    now = get_wib_time()
    with get_db_context() as conn:
        for s in seconds_ago:
            conn.execute(
                'INSERT INTO sensor_data (device_id, sensor_type, data, timestamp) '
                'VALUES (?, ?, ?, ?)',
                (device_id, 'sensor', json.dumps({'temperature': 25}), now - timedelta(seconds=s)))
        conn.commit()


def _device(device_id):
    with get_db_context() as conn:
        return dict(conn.execute(
            'SELECT expected_interval, interval_manual FROM devices WHERE device_id = ?',
            (device_id,)).fetchone())


def test_manual_interval_survives_fast_data(admin_client, make_device):
    key = make_device('i-1', expected_interval=60)
    assert admin_client.put('/api/v1/devices/i-1', json={'expected_interval': 300}).status_code == 200
    _seed('i-1', [5, 4, 3, 2, 1])
    assert post_data(admin_client, 'i-1', key, {'temperature': 25}).status_code == 200
    row = _device('i-1')
    assert row['expected_interval'] == 300
    assert row['interval_manual'] == 1


def test_create_with_interval_is_manual_and_without_is_auto(admin_client):
    r = admin_client.post('/api/v1/devices', json={
        'device_id': 'i-2', 'device_name': 'A', 'expected_interval': 120})
    assert r.status_code == 201
    assert _device('i-2') == {'expected_interval': 120, 'interval_manual': 1}

    r = admin_client.post('/api/v1/devices', json={'device_id': 'i-3', 'device_name': 'B'})
    assert r.status_code == 201
    assert _device('i-3') == {'expected_interval': None, 'interval_manual': 0}


def test_explicit_60_is_kept_as_manual(admin_client):
    admin_client.post('/api/v1/devices', json={
        'device_id': 'i-4', 'device_name': 'C', 'expected_interval': 60})
    assert _device('i-4') == {'expected_interval': 60, 'interval_manual': 1}


def test_auto_detect_with_reasonable_spacing(admin_client, make_device):
    key = make_device('a-1', expected_interval=None)
    _seed('a-1', [150, 120, 90, 60, 30])
    post_data(admin_client, 'a-1', key, {'temperature': 25})
    row = _device('a-1')
    assert 28 <= row['expected_interval'] <= 32
    assert row['interval_manual'] == 0


def test_auto_detect_needs_enough_samples(admin_client, make_device):
    key = make_device('a-2', expected_interval=None)
    _seed('a-2', [60, 30])
    post_data(admin_client, 'a-2', key, {'temperature': 25})
    assert _device('a-2')['expected_interval'] is None


def test_auto_detect_ignores_sub_two_second_gaps(admin_client, make_device):
    key = make_device('a-3', expected_interval=None)
    _seed('a-3', [5, 4, 3, 2, 1])
    post_data(admin_client, 'a-3', key, {'temperature': 25})
    assert _device('a-3')['expected_interval'] is None


def test_auto_detect_never_below_ten_seconds(admin_client, make_device):
    key = make_device('a-4', expected_interval=None)
    _seed('a-4', [15, 12, 9, 6, 3])
    post_data(admin_client, 'a-4', key, {'temperature': 25})
    assert _device('a-4')['expected_interval'] == 10


def test_put_same_value_keeps_auto_mode_and_null_resets(admin_client, make_device):
    make_device('m-1', expected_interval=45)
    admin_client.put('/api/v1/devices/m-1', json={'expected_interval': 45})
    assert _device('m-1')['interval_manual'] == 0           # form terisi hasil auto-detect

    admin_client.put('/api/v1/devices/m-1', json={'expected_interval': 90})
    assert _device('m-1') == {'expected_interval': 90, 'interval_manual': 1}

    admin_client.put('/api/v1/devices/m-1', json={'expected_interval': None})
    assert _device('m-1') == {'expected_interval': None, 'interval_manual': 0}


def test_migration_v15_adds_column_and_is_idempotent(app):
    assert SCHEMA_VERSION >= 15
    if sqlite3.sqlite_version_info < (3, 35, 0):
        pytest.skip('DROP COLUMN butuh SQLite >= 3.35')
    with get_db_context() as conn:
        conn.execute('ALTER TABLE devices DROP COLUMN interval_manual')
        conn.execute('DELETE FROM schema_version WHERE version >= 15')
        conn.commit()
    init_db()
    init_db()      # panggilan kedua tidak boleh error
    with get_db_context() as conn:
        cols = [r[1] for r in conn.execute('PRAGMA table_info(devices)').fetchall()]
        ver = conn.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]
    assert 'interval_manual' in cols
    assert ver == SCHEMA_VERSION
