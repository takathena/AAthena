"""C3 + C4 — global rules dibaca mesin alert; rules per-device menimpa sebagian."""
import json

from app.alerts import get_device_alert_rules_sync as get_device_alert_rules, invalidate_global_rules_cache
from app.database import get_db_context, get_wib_time
from tests.conftest import active_alert_types, post_data

LOOSE_TEMP = {
    'temperature': {
        'healthy': {'min': 0, 'max': 40},
        'warning': {'min': -5, 'max': 45},
        'danger': {'min': -10, 'max': 60},
        '_hysteresis': 0.5,
    }
}


def test_global_rules_change_alert_behaviour(admin_client, make_device):
    key = make_device('g-1')

    resp = admin_client.put('/api/v1/system/alert-rules', json=LOOSE_TEMP)
    assert resp.status_code == 200

    assert post_data(admin_client, 'g-1', key, {'temperature': 35}).status_code == 200
    assert 'temperature' not in active_alert_types('g-1')   # (a) dilonggarkan -> tidak ada alert

    resp = admin_client.delete('/api/v1/system/alert-rules')
    assert resp.status_code == 200

    assert post_data(admin_client, 'g-1', key, {'temperature': 35}).status_code == 200
    assert 'temperature' in active_alert_types('g-1')       # (b) default config kembali berlaku


def test_global_rules_cache_invalidated_on_put(admin_client, make_device):
    key = make_device('g-2')
    # Panaskan cache dengan default
    post_data(admin_client, 'g-2', key, {'temperature': 20})
    admin_client.put('/api/v1/system/alert-rules', json=LOOSE_TEMP)
    post_data(admin_client, 'g-2', key, {'temperature': 35})
    assert 'temperature' not in active_alert_types('g-2')


def test_corrupt_global_rules_fall_back_to_default(admin_client, make_device):
    key = make_device('g-3')
    with get_db_context() as conn:
        conn.execute(
            "INSERT INTO user_settings (key, value, updated_at) "
            "VALUES ('global_alert_rules', ?, ?)", ('{bukan json', get_wib_time()))
        conn.commit()
    invalidate_global_rules_cache()

    resp = post_data(admin_client, 'g-3', key, {'temperature': 35})
    assert resp.status_code == 200
    assert 'temperature' in active_alert_types('g-3')


def test_invalid_stored_rule_for_one_sensor_is_ignored(app, make_device):
    stored = {'temperature': {'bogus': 1}, 'humidity': {
        'healthy': {'min': 0, 'max': 100}, 'warning': {'min': 0, 'max': 100},
        'danger': {'min': 0, 'max': 100}}}
    with get_db_context() as conn:
        conn.execute(
            "INSERT INTO user_settings (key, value, updated_at) "
            "VALUES ('global_alert_rules', ?, ?)", (json.dumps(stored), get_wib_time()))
        conn.commit()
    make_device('g-4')
    invalidate_global_rules_cache()
    with get_db_context() as conn:
        rules = get_device_alert_rules(conn, 'g-4')
    assert rules['temperature']['healthy']['max'] == 28          # default dipertahankan
    assert rules['humidity']['healthy']['max'] == 100            # stored dipakai


def test_hysteresis_key_is_carried_over(app, make_device):
    stored = {'temperature': {
        'healthy': {'min': 0, 'max': 40}, 'warning': {'min': 0, 'max': 45},
        'danger': {'min': -10, 'max': 60}}}                       # tanpa _hysteresis
    with get_db_context() as conn:
        conn.execute(
            "INSERT INTO user_settings (key, value, updated_at) "
            "VALUES ('global_alert_rules', ?, ?)", (json.dumps(stored), get_wib_time()))
        conn.commit()
    make_device('g-5')
    invalidate_global_rules_cache()
    with get_db_context() as conn:
        rules = get_device_alert_rules(conn, 'g-5')
    assert rules['temperature']['_hysteresis'] == 0.5
    assert rules['temperature']['healthy']['max'] == 40


def test_device_custom_rule_overrides_only_its_sensor(admin_client, make_device):
    custom = {'temperature': {
        'healthy': {'min': 0, 'max': 100}, 'warning': {'min': 0, 'max': 100},
        'danger': {'min': -10, 'max': 200}}}
    key = make_device('c-1', alert_rules_json=json.dumps(custom))

    resp = post_data(admin_client, 'c-1', key,
                     {'temperature': 35, 'humidity': 99, 'gas_level': 99})
    assert resp.status_code == 200

    active = active_alert_types('c-1')
    assert 'humidity' in active          # dari global
    assert 'gas_level' in active         # dari global
    assert 'temperature' not in active   # mengikuti custom rule


def test_device_custom_rule_still_triggers_for_its_sensor(admin_client, make_device):
    strict = {'temperature': {
        'healthy': {'min': 0, 'max': 10}, 'warning': {'min': 0, 'max': 20},
        'danger': {'min': -10, 'max': 30}}}
    key = make_device('c-2', alert_rules_json=json.dumps(strict))
    post_data(admin_client, 'c-2', key, {'temperature': 15})
    assert 'temperature' in active_alert_types('c-2')


def test_get_device_alert_rules_merges_and_skips_invalid(app, make_device):
    custom = {'temperature': {'bogus': 1},
              'lux': {'healthy': {'min': 1, 'max': 2}, 'warning': {'min': 0, 'max': 3},
                      'danger': {'min': 0, 'max': 4}}}
    make_device('c-3', alert_rules_json=json.dumps(custom))
    with get_db_context() as conn:
        rules = get_device_alert_rules(conn, 'c-3')
    assert rules['temperature']['healthy']['max'] == 28    # custom invalid diabaikan
    assert rules['lux']['healthy']['max'] == 2             # custom valid menimpa
    assert 'humidity' in rules and 'gas_level' in rules    # sensor global tetap ada


def test_device_rules_endpoint_shows_inherited_sensors(admin_client, make_device):
    custom = {'lux': {'healthy': {'min': 1, 'max': 2}, 'warning': {'min': 0, 'max': 3},
                      'danger': {'min': 0, 'max': 4}}}
    make_device('c-4', alert_rules_json=json.dumps(custom))
    body = admin_client.get('/api/v1/devices/c-4/alert-rules').get_json()
    assert body['is_custom'] is True
    assert 'temperature' in body['alert_rules']
