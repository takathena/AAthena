"""M1 — validasi payload /data (ukuran, struktur, tipe)."""
import json

import pytest

from app.database import get_db_context
from tests.conftest import post_data


@pytest.fixture
def dev(make_device):
    return make_device('p-1'), 'p-1'


def _sensor_rows():
    with get_db_context() as conn:
        return conn.execute('SELECT COUNT(*) FROM sensor_data').fetchone()[0]


def test_firmware_payload_is_accepted(anon_client, dev):
    key, did = dev
    r = anon_client.post('/api/v1/data', json={
        'device_id': did, 'api_key': key, 'sensor_type': 'DHT22',
        'wifi_ssid': 'NamaWiFi', 'uptime_seconds': 3600,
        'data': {'temperature': 25.5, 'humidity': 60.0}})
    assert r.status_code == 200


def test_heartbeat_and_empty_data_accepted(anon_client, dev):
    key, did = dev
    assert post_data(anon_client, did, key, {}, sensor_type='heartbeat').status_code == 200


def test_bool_and_short_string_accepted(anon_client, dev):
    key, did = dev
    assert post_data(anon_client, did, key, {'motion': True, 'note': 'x' * 64}).status_code == 200


@pytest.mark.parametrize('data', [
    {'a': {'b': 1}},                    # bersarang
    {'a': [1, 2, 3]},                   # list
    {'a': None},                        # null
    {'tem p': 1},                       # key berspasi
    {'a.b': 1},                         # key bertitik
    {'k' * 33: 1},                      # key terlalu panjang
    {'a': 'x' * 65},                    # string terlalu panjang
    {f'k{i}': i for i in range(33)},    # > 32 key
])
def test_bad_data_shapes_rejected(anon_client, dev, data):
    key, did = dev
    assert post_data(anon_client, did, key, data).status_code == 400
    assert _sensor_rows() == 0


@pytest.mark.parametrize('literal', ['NaN', 'Infinity', '-Infinity', '1e999'])
def test_non_finite_numbers_rejected(anon_client, dev, literal):
    key, did = dev
    body = ('{"device_id": "%s", "api_key": "%s", "sensor_type": "s", '
            '"data": {"temperature": %s}}' % (did, key, literal))
    r = anon_client.post('/api/v1/data', data=body, content_type='application/json')
    assert r.status_code == 400
    assert _sensor_rows() == 0


@pytest.mark.parametrize('stype', ['DHT 22!', '', 'a' * 33, 'x/y'])
def test_bad_sensor_type_rejected(anon_client, dev, stype):
    key, did = dev
    assert post_data(anon_client, did, key, {'t': 1}, sensor_type=stype).status_code == 400


def test_huge_body_gets_413(anon_client, dev):
    key, did = dev
    r = anon_client.post('/api/v1/data', json={
        'device_id': did, 'api_key': key, 'sensor_type': 's',
        'data': {'note': 'x' * 200_000}})
    assert r.status_code == 413
    assert _sensor_rows() == 0


def test_data_max_bytes_is_configurable(app, dev):
    key, did = dev
    app.config['DATA_MAX_BYTES'] = 100
    client = app.test_client()
    r = client.post('/api/v1/data', json={
        'device_id': did, 'api_key': key, 'sensor_type': 's', 'data': {'t': 1}})
    assert r.status_code == 413
