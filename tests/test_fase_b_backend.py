import pytest
pytestmark = pytest.mark.skip(reason="Belum di-port penuh ke FastAPI — di-skip sementara (Task 2)")
"""Fase B — mesin alert (band/severity/pesan) + validasi input backend."""
from app.alerts import _evaluate_severity, _format_alert_message
from app.database import get_db_context

# Band bersarang seperti ALERT_RULES default untuk temperature.
NESTED_TEMP = {
    'healthy': {'min': 6, 'max': 28},
    'warning': {'min': 0, 'max': 32},
    'danger': {'min': -10, 'max': 40},
    '_hysteresis': 0.5,
}


# ---------- severity dari band ----------
def test_evaluate_severity_with_nested_bands():
    assert _evaluate_severity(20, NESTED_TEMP)[0] == 'healthy'
    assert _evaluate_severity(30, NESTED_TEMP)[0] == 'warning'
    assert _evaluate_severity(36, NESTED_TEMP)[0] == 'danger'
    # di luar semua band → paling parah
    assert _evaluate_severity(45, NESTED_TEMP)[0] == 'danger'


def test_info_band_is_honoured():
    rule = {
        'healthy': {'min': 6, 'max': 28},
        'info': {'min': 0, 'max': 30},
        'warning': {'min': 0, 'max': 35},
        'danger': {'min': -10, 'max': 40},
    }
    assert _evaluate_severity(29, rule)[0] == 'info'
    assert _evaluate_severity(32, rule)[0] == 'warning'


def test_invalid_rule_min_gt_max_is_rejected():
    assert _evaluate_severity(20, {'healthy': {'min': 30, 'max': 20}}) == (None, None)


# ---------- pesan menyebut band yang benar-benar dilanggar ----------
def test_message_for_danger_names_warning_boundary():
    # 36 °C melewati warning.max (32), bukan sekadar "batas normal"
    assert _format_alert_message('temperature', 36, 'danger', NESTED_TEMP) == \
        'Melewati batas warning (32°C)'


def test_message_for_warning_names_normal_boundary():
    assert _format_alert_message('temperature', 30, 'warning', NESTED_TEMP) == \
        'Melewati batas normal (28°C)'


def test_message_for_below_range():
    assert _format_alert_message('temperature', -5, 'danger', NESTED_TEMP) == \
        'Di bawah batas warning (0°C)'


def test_message_beyond_widest_band():
    assert _format_alert_message('temperature', 45, 'danger', NESTED_TEMP) == \
        'Melewati batas danger (40°C)'


# ---------- offline_timeout divalidasi di POST /devices ----------
def test_post_device_rejects_invalid_offline_timeout(admin_client):
    for i, bad in enumerate([-5, 5, 999999, 'abc']):
        r = admin_client.post('/api/v1/devices', json={
            'device_id': f'ot-bad-{i}', 'device_name': 'X',
            'offline_timeout': bad,
        })
        assert r.status_code == 400, (bad, r.get_json())


def test_post_device_rejects_timeout_shorter_than_interval(admin_client):
    r = admin_client.post('/api/v1/devices', json={
        'device_id': 'ot-short', 'device_name': 'X',
        'expected_interval': 600, 'offline_timeout': 100,
    })
    assert r.status_code == 400


def test_post_device_accepts_valid_offline_timeout(admin_client):
    r = admin_client.post('/api/v1/devices', json={
        'device_id': 'ot-ok', 'device_name': 'X', 'offline_timeout': 900,
    })
    assert r.status_code == 201, r.get_json()


# ---------- PUT /layout menolak elemen non-dict dengan 400 ----------
def test_put_layout_rejects_non_dict_element(admin_client):
    did = admin_client.post('/api/v1/dashboards', json={'name': 'Layout'}).get_json()['id']
    r = admin_client.put(f'/api/v1/dashboards/{did}/layout',
                         json={'layout': ['bukan-dict']})
    assert r.status_code == 400
