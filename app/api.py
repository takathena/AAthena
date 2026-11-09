"""
NEXUS IoT - API Routes (v1)
Batch 1-7 integrated
Refactor: helper bersama (timestamp/device/status/interval/purge/user)
dipindah ke app/api_common.py; file ini hanya route + orkestrasi.
"""
from app.auth import login_required, admin_required
import json
import logging
import csv
import io
import os
import sqlite3
from datetime import timedelta, datetime
from flask import Blueprint, request, jsonify, Response, current_app
from marshmallow import ValidationError

from app.database import get_db_context, get_wib_time
from app.validators import (
    device_create_schema, device_update_schema, sensor_data_schema,
    bulk_import_item_schema,
)
from app.utils import (
    generate_api_key, safe_json_loads, validate_alert_rules,
    hash_api_key, csv_safe,
)
from app.alerts import (
    check_and_create_alerts, get_active_alerts, get_alert_history,
    acknowledge_alert, bulk_acknowledge_alerts,
    get_device_alert_rules,
    invalidate_global_rules_cache,
)
from app.extensions import limiter, csrf
from app.ratelimit import data_rate_limit_key
from app.config import get_config
from app.notifier import send_test_notification, get_notification_status
from app.background import get_background_status
from app import workspace as ws
from app import permissions as perm
from app.api_common import (
    _clean_timestamp, validate_device_api_key, update_device_status,
    _alert_label, _detect_interval, _current_user_id, _validate_username,
    PURGE_TABLES, PURGE_BATCH, _parse_purge_request, _purge_where,
    _purge_preview,
    AUTO_INTERVAL_MIN_SAMPLES, AUTO_INTERVAL_MIN_DELTAS,
    AUTO_INTERVAL_IGNORE_BELOW, AUTO_INTERVAL_FLOOR,
)

logger = logging.getLogger('nexus')
api_bp = Blueprint('api', __name__, url_prefix='/api/v1')


# ==========================================
# DEVICE-FACING ENDPOINT
# ==========================================
@api_bp.route('/data', methods=['POST'])
@csrf.exempt
@limiter.limit(lambda: get_config().RATE_LIMIT_DATA, key_func=data_rate_limit_key)
@limiter.limit(lambda: get_config().RATE_LIMIT_DATA_IP)
def receive_data():
    from werkzeug.exceptions import RequestEntityTooLarge

    # Batas ukuran khusus endpoint device (default 8 KB, DATA_MAX_BYTES).
    max_bytes = int(current_app.config.get('DATA_MAX_BYTES') or get_config().DATA_MAX_BYTES)
    too_large = (jsonify({
        'success': False,
        'error': f'Payload terlalu besar. Maksimal {max_bytes} byte.',
        'max_bytes': max_bytes,
    }), 413)

    if request.content_length is not None and request.content_length > max_bytes:
        return too_large

    try:
        raw_body = request.get_data(cache=True)
        if len(raw_body) > max_bytes:
            return too_large
        payload = request.get_json(silent=True)
    except RequestEntityTooLarge:
        return too_large

    try:
        if not payload:
            return jsonify({'success': False, 'error': 'Invalid JSON'}), 400

        try:
            data = sensor_data_schema.load(payload)
        except ValidationError as err:
            return jsonify({'success': False, 'error': err.messages}), 400

        if not validate_device_api_key(data['device_id'], data['api_key']):
            logger.warning(f"Invalid API key attempt: device={data['device_id']}")
            return jsonify({'success': False, 'error': 'Invalid device_id or api_key'}), 401

        with get_db_context() as conn:
            conn.execute('''
                INSERT INTO sensor_data
                (device_id, sensor_type, data, wifi_ssid, uptime_seconds, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                data['device_id'], data['sensor_type'],
                json.dumps(data['data']), data.get('wifi_ssid', ''),
                data.get('uptime_seconds', 0), get_wib_time()
            ))

            try:
                dev = conn.execute(
                    'SELECT expected_interval, interval_manual FROM devices WHERE device_id = ?',
                    (data['device_id'],)
                ).fetchone()
                # Auto-detect hanya untuk device yang intervalnya TIDAK diisi manual.
                if dev and not dev['interval_manual']:
                    auto_int = _detect_interval(conn, data['device_id'])
                    cur_int = dev['expected_interval']
                    if auto_int is not None and (
                        not cur_int or abs(auto_int - cur_int) > 0.2 * cur_int
                    ):
                        conn.execute(
                            'UPDATE devices SET expected_interval = ? WHERE device_id = ?',
                            (auto_int, data['device_id'])
                        )
                        logger.info(f"Auto-detected interval for {data['device_id']}: {auto_int}s")
            except Exception as e:
                logger.debug(f"Auto-detect interval failed for {data['device_id']}: {e}")

            conn.commit()

        update_device_status(data['device_id'], 'online', request.remote_addr)

        if data['sensor_type'] != 'heartbeat':
            try:
                check_and_create_alerts(data['device_id'], data['data'])
            except Exception as e:
                logger.error(f"Alert check failed: {e}", exc_info=True)

        return jsonify({
            'success': True,
            'message': 'Data received',
            'timestamp': _clean_timestamp(get_wib_time().isoformat())
        }), 200

    except Exception as e:
        logger.error(f"Error in receive_data: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Internal server error'}), 500


# ==========================================
# ALERT TREND
# ==========================================
@api_bp.route('/alerts/trend', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_alert_trend():
    hours = min(request.args.get('hours', 24, type=int), 168)
    since = get_wib_time() - timedelta(hours=hours)

    with get_db_context() as conn:
        scope = ws.resolve_scope(conn)
        if scope['error']:
            return ws.scope_error_response(scope)
        scope_sql, scope_params = ws.device_in_sql(scope, 'device_id')
        rows = conn.execute(f'''
            SELECT strftime('%Y-%m-%d %H:00', created_at) AS hour_bucket,
                   severity, COUNT(*) AS count
            FROM alert_history
            WHERE created_at >= ? AND action = 'created' AND {scope_sql}
            GROUP BY hour_bucket, severity
            ORDER BY hour_bucket ASC
        ''', [since] + scope_params).fetchall()

    return jsonify({'success': True, 'trend': [dict(r) for r in rows], 'range_hours': hours}), 200


# ==========================================
# DEVICES
# ==========================================
@api_bp.route('/devices', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_devices():
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 100, type=int), 500)
    offset = (page - 1) * per_page

    with get_db_context() as conn:
        scope = ws.resolve_scope(conn)
        if scope['error']:
            return ws.scope_error_response(scope)
        scope_sql, scope_params = ws.dashboard_in_sql(scope, 'dv.dashboard_id')
        total = conn.execute(
            f'SELECT COUNT(*) FROM devices dv WHERE {scope_sql}', scope_params
        ).fetchone()[0]
        rows = conn.execute(f'''
            SELECT dv.*, db.name AS dashboard_name,
                   COALESCE(NULLIF(u.display_name, ''), u.username) AS owner_name
            FROM devices dv
            LEFT JOIN dashboards db ON db.id = dv.dashboard_id
            LEFT JOIN users u ON u.id = db.user_id
            WHERE {scope_sql}
            ORDER BY dv.created_at DESC LIMIT ? OFFSET ?
        ''', scope_params + [per_page, offset]).fetchall()

    devices = []
    for device in rows:
        d = dict(device)
        d.pop('api_key', None)
        d.pop('api_key_hash', None)
        if d.get('alert_rules'):
            try:
                d['alert_rules'] = json.loads(d['alert_rules'])
            except (json.JSONDecodeError, TypeError):
                d['alert_rules'] = None
        devices.append(d)

    return jsonify({
        'success': True,
        'devices': devices,
        'pagination': {
            'page': page, 'per_page': per_page, 'total': total,
            'total_pages': (total + per_page - 1) // per_page,
        }
    }), 200

# ==========================================
# METRICS HISTORY (sparkline Dashboard & Absensi)
# ==========================================
@api_bp.route('/metrics/devices-history', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_devices_metrics_history():
    """Kumulatif device per bucket jam + alerts baru per jam."""
    hours = min(max(request.args.get('hours', 24, type=int), 1), 168)
    since = get_wib_time() - timedelta(hours=hours)

    with get_db_context() as conn:
        scope = ws.resolve_scope(conn)
        if scope['error']:
            return ws.scope_error_response(scope)

        dev_sql, dev_params = ws.dashboard_in_sql(scope, 'dv.dashboard_id')
        st_sql, st_params = ws.device_in_sql(scope, 'sl.device_id')
        al_sql, al_params = ws.device_in_sql(scope, 'a.device_id')

        all_devices = conn.execute(f'''
            SELECT dv.device_id, dv.created_at, dv.status
            FROM devices dv WHERE {dev_sql}
        ''', dev_params).fetchall()

        buckets = []
        cursor = since.replace(minute=0, second=0, microsecond=0)
        end = get_wib_time().replace(minute=0, second=0, microsecond=0)
        guard = 0
        while cursor <= end and guard < 200:
            buckets.append(cursor)
            cursor += timedelta(hours=1)
            guard += 1

        if not buckets:
            return jsonify({
                'success': True, 'hours': hours, 'buckets': [],
                'total': [], 'online': [], 'offline': [], 'alerts': [],
            }), 200

        n = len(buckets)

        total_series = []
        for b in buckets:
            b_str = b.strftime('%Y-%m-%d %H:%M:%S')
            cnt = 0
            for d in all_devices:
                cr = d['created_at']
                if cr and str(cr) <= b_str:
                    cnt += 1
            total_series.append(cnt)

        log_rows = conn.execute(f'''
            SELECT
                strftime('%Y-%m-%d %H:00', sl.created_at) AS bucket,
                sl.device_id,
                sl.status
            FROM device_status_log sl
            WHERE sl.created_at >= ?
              AND sl.status IN ('online', 'offline')
              AND {st_sql}
        ''', [since] + st_params).fetchall()

        trans_map = {}
        for r in log_rows:
            bkey = r['bucket']
            trans_map.setdefault(bkey, {})
            trans_map[bkey][r['device_id']] = r['status']

        online_series = [0] * n
        for d in all_devices:
            did = d['device_id']
            cur_status = d['status'] or 'offline'
            cr = d['created_at']
            if not cr:
                continue

            first_idx = n
            for i, b in enumerate(buckets):
                b_str = b.strftime('%Y-%m-%d %H:%M:%S')
                if str(cr) <= b_str:
                    first_idx = i
                    break
            if first_idx >= n:
                continue

            states = [0] * n
            states[n - 1] = 1 if cur_status == 'online' else 0

            for i in range(n - 2, -1, -1):
                next_bkey = buckets[i + 1].strftime('%Y-%m-%d %H:00')
                trans = trans_map.get(next_bkey, {}).get(did)
                if trans == 'online':
                    states[i] = max(0, states[i + 1] - 1)
                elif trans == 'offline':
                    states[i] = min(1, states[i + 1] + 1)
                else:
                    states[i] = states[i + 1]

            for i in range(first_idx, n):
                online_series[i] += states[i]

        for i in range(n):
            online_series[i] = min(online_series[i], total_series[i])

        offline_series = [max(0, total_series[i] - online_series[i]) for i in range(n)]

        alert_rows = conn.execute(f'''
            SELECT
                strftime('%Y-%m-%d %H:00', a.created_at) AS bucket,
                COUNT(*) AS n
            FROM alerts a
            WHERE a.created_at >= ?
              AND a.alert_type != 'uid'
              AND {al_sql}
            GROUP BY bucket
        ''', [since] + al_params).fetchall()
        alert_map = {r['bucket']: r['n'] for r in alert_rows}
        alerts_series = [alert_map.get(b.strftime('%Y-%m-%d %H:00'), 0) for b in buckets]

    return jsonify({
        'success': True,
        'hours': hours,
        'buckets': [b.strftime('%Y-%m-%d %H:00') for b in buckets],
        'total': total_series,
        'online': online_series,
        'offline': offline_series,
        'alerts': alerts_series,
    }), 200


@api_bp.route('/devices', methods=['POST'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def add_device():
    """Tambah perangkat ke sebuah dashboard (peran editor/owner, atau admin)."""
    try:
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({'success': False, 'error': 'Invalid JSON'}), 400

        # dashboard_id bukan bagian schema perangkat; diambil dulu agar tidak ditolak sebagai field asing.
        requested_dashboard = payload.pop('dashboard_id', None) if isinstance(payload, dict) else None

        try:
            data = device_create_schema.load(payload)
        except ValidationError as err:
            return jsonify({'success': False, 'error': err.messages}), 400

        alert_rules = data.get('alert_rules')
        if alert_rules:
            is_valid, err_msg = validate_alert_rules(alert_rules)
            if not is_valid:
                return jsonify({'success': False, 'error': err_msg}), 400

        api_key = generate_api_key()
        api_key_hash = hash_api_key(api_key)

        # expected_interval: diisi eksplisit oleh user => manual (auto-detect mati).
        # Tidak diisi => None dan auto-detect aktif.
        explicit_interval = payload.get('expected_interval') is not None
        expected_interval = data.get('expected_interval') if explicit_interval else None
        interval_manual = 1 if explicit_interval else 0

        firmware_version = (data.get('firmware_version') or '').strip()
        offline_timeout = data.get('offline_timeout')
        device_type = (data.get('device_type') or '').strip()

        if offline_timeout is None and 'rfid' in device_type.lower():
            offline_timeout = 86400

        # offline_timeout tidak boleh lebih pendek dari interval kirim device,
        # kalau tidak device akan tampak offline padahal baru saja mengirim data.
        if (offline_timeout is not None and expected_interval is not None
                and offline_timeout < expected_interval):
            return jsonify({
                'success': False,
                'error': (f'Offline Timeout minimal {expected_interval} detik '
                          f'(= interval kirim device). Kosongkan untuk mode otomatis.')
            }), 400

        alert_rules_json = json.dumps(alert_rules) if alert_rules else None
        offline_severity = data.get('offline_alert_severity', 'danger')

        with get_db_context() as conn:
            scope = ws.resolve_scope(conn, 'editor')
            if scope['error']:
                return ws.scope_error_response(scope)
            dashboard_id, denied = ws.pick_write_dashboard(
                conn, scope, requested_id=requested_dashboard, minimum='editor'
            )
            if denied:
                return denied

            existing = conn.execute(
                'SELECT device_id FROM devices WHERE device_id = ?',
                (data['device_id'],)
            ).fetchone()

            if existing:
                return jsonify({'success': False, 'error': 'Device ID already exists'}), 400

            conn.execute('''
                INSERT INTO devices
                (device_id, device_name, device_type, location, description,
                 firmware_version,
                 api_key, api_key_hash, offline_timeout, expected_interval,
                 alert_rules, offline_alert_severity, created_at, interval_manual,
                 dashboard_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['device_id'], data['device_name'], data['device_type'],
                data['location'], data['description'],
                firmware_version,
                None, api_key_hash,
                offline_timeout, expected_interval,
                alert_rules_json, offline_severity, get_wib_time(), interval_manual,
                dashboard_id
            ))
            conn.commit()

        logger.info(f"Device added: {data['device_id']}")

        return jsonify({
            'success': True,
            'device': {
                'device_id': data['device_id'],
                'device_name': data['device_name'],
                'api_key': api_key,
                'offline_timeout': offline_timeout,
                'expected_interval': expected_interval,
                'firmware_version': firmware_version,
                'offline_alert_severity': offline_severity,
                'dashboard_id': dashboard_id,
                'warning': 'Simpan API key ini! Tidak akan ditampilkan lagi.'
            }
        }), 201

    except Exception as e:
        logger.error(f"Error adding device: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Internal server error'}), 500


@api_bp.route('/devices/<device_id>', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_device_detail(device_id):
    with get_db_context() as conn:
        device, denied = ws.load_device(conn, device_id, 'viewer')
        if denied:
            return denied

        latest = conn.execute('''
            SELECT * FROM sensor_data WHERE device_id = ?
            ORDER BY timestamp DESC LIMIT 1
        ''', (device_id,)).fetchone()

        active_alerts = conn.execute('''
            SELECT * FROM alerts
            WHERE device_id = ? AND is_active = 1 AND alert_type != 'uid'
            ORDER BY
                CASE severity
                    WHEN 'danger' THEN 1 WHEN 'warning' THEN 2
                    WHEN 'info' THEN 3 ELSE 4
                END,
                created_at DESC
        ''', (device_id,)).fetchall()

    device_info = dict(device)
    device_info.pop('api_key', None)
    device_info.pop('api_key_hash', None)

    if device_info.get('alert_rules'):
        try:
            device_info['alert_rules'] = json.loads(device_info['alert_rules'])
        except (json.JSONDecodeError, TypeError):
            device_info['alert_rules'] = None

    device_info['latest_data'] = None
    if latest:
        device_info['latest_data'] = {
            'sensor_type': latest['sensor_type'],
            'data': safe_json_loads(latest['data']),
            'wifi_ssid': latest['wifi_ssid'] or '',
            'uptime_seconds': latest['uptime_seconds'] or 0,
            'timestamp': _clean_timestamp(latest['timestamp']),
        }

    device_info['active_alerts'] = [dict(a) for a in active_alerts]

    return jsonify({'success': True, 'device': device_info}), 200


@api_bp.route('/devices/<device_id>/history', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_device_history(device_id):
    hours = min(request.args.get('hours', 3, type=int), 720)
    limit = min(request.args.get('limit', 500, type=int), 5000)
    since = get_wib_time() - timedelta(hours=hours)

    with get_db_context() as conn:
        _, denied = ws.load_device(conn, device_id, 'viewer', 'device_id')
        if denied:
            return denied
        rows = conn.execute('''
            SELECT * FROM sensor_data
            WHERE device_id = ? AND timestamp >= ?
            ORDER BY timestamp DESC LIMIT ?
        ''', (device_id, since, limit)).fetchall()

    rows = list(reversed(rows))

    history = [{
        'sensor_type': item['sensor_type'],
        'data': safe_json_loads(item['data']),
        'wifi_ssid': item['wifi_ssid'] or '',
        'uptime_seconds': item['uptime_seconds'] or 0,
        'timestamp': _clean_timestamp(item['timestamp']),
    } for item in rows]

    return jsonify({'success': True, 'history': history, 'data_count': len(history)}), 200


@api_bp.route('/devices/<device_id>', methods=['PUT'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def update_device(device_id):
    try:
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({'success': False, 'error': 'Invalid JSON'}), 400

        try:
            data = device_update_schema.load(payload)
        except ValidationError as err:
            err_msgs = err.messages
            if isinstance(err_msgs, dict):
                parts = []
                for field, msgs in err_msgs.items():
                    arr = msgs if isinstance(msgs, list) else [msgs]
                    for m in arr:
                        parts.append(f"{field}: {m}")
                error_str = ' | '.join(parts) if parts else 'Validation error'
            else:
                error_str = str(err_msgs)
            return jsonify({'success': False, 'error': error_str}), 400

        alert_rules = data.get('alert_rules')
        if alert_rules is not None:
            is_valid, err_msg = validate_alert_rules(alert_rules)
            if not is_valid:
                return jsonify({'success': False, 'error': err_msg}), 400

        with get_db_context() as conn:
            device, denied = ws.load_device(conn, device_id, 'editor')
            if denied:
                return denied

            if 'offline_timeout' in data:
                raw_timeout = data['offline_timeout']

                if raw_timeout is None or raw_timeout == '':
                    new_offline_timeout = None
                else:
                    try:
                        new_timeout = int(raw_timeout)
                    except (ValueError, TypeError):
                        return jsonify({
                            'success': False,
                            'error': 'Offline Timeout harus berupa angka atau dikosongkan'
                        }), 400

                    if new_timeout < 10:
                        return jsonify({
                            'success': False,
                            'error': 'Offline Timeout minimal 10 detik. Kosongkan untuk mode otomatis.'
                        }), 400

                    if new_timeout > 604800:
                        return jsonify({
                            'success': False,
                            'error': 'Offline Timeout maksimal 604800 detik (7 hari).'
                        }), 400

                    current_interval = device['expected_interval'] or 60
                    min_allowed = current_interval

                    if new_timeout < min_allowed:
                        return jsonify({
                            'success': False,
                            'error': (
                                f'Offline Timeout minimal {min_allowed} detik '
                                f'(= interval kirim device). '
                                f'Kalau perlu lebih kecil dari ini, '
                                f'kosongkan field untuk pakai mode otomatis.'
                            )
                        }), 400

                    new_offline_timeout = new_timeout
            else:
                new_offline_timeout = device['offline_timeout']

            if alert_rules is not None:
                alert_rules_json = json.dumps(alert_rules) if alert_rules else None
            else:
                alert_rules_json = device['alert_rules']

            # Interval: nilai baru yang BERBEDA dari yang tersimpan = pilihan manual.
            # Nilai sama (mis. form edit yang terisi hasil auto-detect) tidak mengubah mode.
            # None = kembali ke mode otomatis.
            new_interval = device['expected_interval']
            new_manual = device['interval_manual'] or 0
            if 'expected_interval' in data:
                requested = data['expected_interval']
                if requested is None:
                    new_interval, new_manual = None, 0
                elif requested != device['expected_interval']:
                    new_interval, new_manual = requested, 1

            updates = {
                'device_name': data.get('device_name', device['device_name']),
                'device_type': data.get('device_type', device['device_type']),
                'location': data.get('location', device['location']),
                'description': data.get('description', device['description']),
                'firmware_version': data.get('firmware_version', device['firmware_version'] or ''),
                'latitude': data.get('latitude', device['latitude']),
                'longitude': data.get('longitude', device['longitude']),
                'offline_timeout': new_offline_timeout,
                'expected_interval': new_interval,
                'interval_manual': new_manual,
                'offline_alert_severity': data.get('offline_alert_severity', device['offline_alert_severity']),
                'alert_rules': alert_rules_json,
            }

            conn.execute('''
                UPDATE devices SET
                    device_name = ?, device_type = ?, location = ?,
                    description = ?, firmware_version = ?,
                    latitude = ?, longitude = ?,
                    offline_timeout = ?, expected_interval = ?,
                    interval_manual = ?,
                    offline_alert_severity = ?, alert_rules = ?
                WHERE device_id = ?
            ''', (
                updates['device_name'], updates['device_type'], updates['location'],
                updates['description'], updates['firmware_version'],
                updates['latitude'], updates['longitude'],
                updates['offline_timeout'], updates['expected_interval'],
                updates['interval_manual'],
                updates['offline_alert_severity'], updates['alert_rules'], device_id
            ))
            conn.commit()

        return jsonify({'success': True}), 200

    except Exception as e:
        logger.error(f"Error updating device {device_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Internal server error'}), 500


@api_bp.route('/devices/<device_id>', methods=['DELETE'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def delete_device(device_id):
    with get_db_context() as conn:
        device, denied = ws.load_device(conn, device_id, 'editor', 'device_id')
        if denied:
            return denied

        ws.audit(conn, 'device.delete', f'device_id={device_id}')
        conn.execute('DELETE FROM sensor_data WHERE device_id = ?', (device_id,))
        conn.execute('DELETE FROM alerts WHERE device_id = ?', (device_id,))
        conn.execute('DELETE FROM alert_history WHERE device_id = ?', (device_id,))
        conn.execute('DELETE FROM device_status_log WHERE device_id = ?', (device_id,))
        conn.execute('DELETE FROM devices WHERE device_id = ?', (device_id,))
        conn.commit()

    logger.info(f"Device deleted: {device_id}")
    return jsonify({'success': True}), 200


@api_bp.route('/devices/<device_id>/regenerate-key', methods=['POST'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_REGENERATE)
def regenerate_api_key(device_id):
    with get_db_context() as conn:
        device, denied = ws.load_device(conn, device_id, 'editor', 'device_id')
        if denied:
            return denied

        new_key = generate_api_key()
        new_hash = hash_api_key(new_key)
        conn.execute(
            'UPDATE devices SET api_key = NULL, api_key_hash = ? WHERE device_id = ?',
            (new_hash, device_id)
        )
        conn.commit()

    logger.warning(f"API key regenerated for {device_id}")
    return jsonify({
        'success': True, 'api_key': new_key,
        'warning': 'Update firmware perangkat dengan API key baru!'
    }), 200


@api_bp.route('/devices/<device_id>/alert-rules', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_device_alert_rules_endpoint(device_id):
    with get_db_context() as conn:
        device, denied = ws.load_device(conn, device_id, 'viewer', 'device_id, alert_rules')
        if denied:
            return denied

        rules = get_device_alert_rules(conn, device_id)
        is_custom = device['alert_rules'] is not None

    return jsonify({
        'success': True, 'device_id': device_id,
        'alert_rules': rules, 'is_custom': is_custom,
    }), 200


@api_bp.route('/devices/<device_id>/alert-rules', methods=['PUT'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def update_device_alert_rules_endpoint(device_id):
    try:
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({'success': False, 'error': 'Invalid JSON'}), 400

        is_valid, err_msg = validate_alert_rules(payload)
        if not is_valid:
            return jsonify({'success': False, 'error': err_msg}), 400

        with get_db_context() as conn:
            device, denied = ws.load_device(conn, device_id, 'editor', 'device_id')
            if denied:
                return denied

            conn.execute('UPDATE devices SET alert_rules = ? WHERE device_id = ?',
                         (json.dumps(payload), device_id))
            conn.commit()

        return jsonify({'success': True, 'alert_rules': payload}), 200

    except Exception as e:
        logger.error(f"Error updating alert rules: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Internal server error'}), 500


@api_bp.route('/devices/<device_id>/alert-rules', methods=['DELETE'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def reset_device_alert_rules(device_id):
    with get_db_context() as conn:
        device, denied = ws.load_device(conn, device_id, 'editor', 'device_id')
        if denied:
            return denied

        conn.execute('UPDATE devices SET alert_rules = NULL WHERE device_id = ?', (device_id,))
        conn.commit()

    return jsonify({'success': True}), 200


# ==========================================
# DASHBOARD
# ==========================================
@api_bp.route('/dashboard', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_dashboard_data():
    with get_db_context() as conn:
        scope = ws.resolve_scope(conn)
        if scope['error']:
            return ws.scope_error_response(scope)
        dev_sql, dev_params = ws.dashboard_in_sql(scope, 'dashboard_id')
        d_sql, d_params = ws.dashboard_in_sql(scope, 'd.dashboard_id')
        al_sql, al_params = ws.device_in_sql(scope, 'device_id')

        counts = conn.execute(f'''
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) AS online,
                SUM(CASE WHEN status = 'offline' THEN 1 ELSE 0 END) AS offline
            FROM devices WHERE {dev_sql}
        ''', dev_params).fetchone()

        total = counts['total'] or 0
        online = counts['online'] or 0
        offline = counts['offline'] or 0

        alert_rows = conn.execute(f'''
            SELECT severity, COUNT(*) AS count
            FROM alerts
            WHERE is_active = 1 AND alert_type != 'uid' AND {al_sql}
            GROUP BY severity
        ''', al_params).fetchall()

        alert_summary = {'danger': 0, 'warning': 0, 'info': 0, 'total': 0}
        for row in alert_rows:
            if row['severity'] in alert_summary:
                alert_summary[row['severity']] = row['count']
            alert_summary['total'] += row['count']

        rows = conn.execute(f'''
            SELECT
                d.dashboard_id, db.name AS dashboard_name,
                COALESCE(NULLIF(u.display_name, ''), u.username) AS owner_name,
                d.device_id, d.device_name, d.device_type, d.location,
                d.latitude, d.longitude, d.status, d.last_seen,
                d.offline_timeout, d.expected_interval, d.offline_alert_severity,
                d.firmware_version, d.last_ip,
                sd.wifi_ssid AS latest_wifi_ssid,
                sd.uptime_seconds AS latest_uptime_seconds,
                sd.timestamp AS latest_data_at,
                a.severity AS top_alert_severity,
                a.alert_type AS top_alert_type,
                a.message AS top_alert_message,
                a.created_at AS top_alert_created_at,
                ac.alert_count AS total_active_alerts
            FROM devices d
            LEFT JOIN dashboards db ON db.id = d.dashboard_id
            LEFT JOIN users u ON u.id = db.user_id
            LEFT JOIN (
                SELECT device_id, wifi_ssid, uptime_seconds, timestamp,
                       ROW_NUMBER() OVER (PARTITION BY device_id ORDER BY timestamp DESC) AS rn
                FROM sensor_data
            ) sd ON d.device_id = sd.device_id AND sd.rn = 1
            LEFT JOIN (
                SELECT device_id, severity, alert_type, message, created_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY device_id
                           ORDER BY CASE severity
                               WHEN 'danger' THEN 1 WHEN 'warning' THEN 2
                               WHEN 'info' THEN 3 ELSE 4
                           END, created_at DESC
                       ) AS rn
                FROM alerts
                WHERE is_active = 1 AND alert_type != 'uid'
            ) a ON d.device_id = a.device_id AND a.rn = 1
            LEFT JOIN (
                SELECT device_id, COUNT(*) AS alert_count
                FROM alerts
                WHERE is_active = 1 AND alert_type != 'uid'
                GROUP BY device_id
            ) ac ON d.device_id = ac.device_id
            WHERE {d_sql}
            ORDER BY
                CASE WHEN a.severity = 'danger' THEN 1
                     WHEN a.severity = 'warning' THEN 2
                     WHEN a.severity = 'info' THEN 3
                     ELSE 4 END,
                d.created_at DESC
        ''', d_params).fetchall()

        device_list = []
        healthy_count = 0
        for row in rows:
            has_alert = row['top_alert_severity'] is not None
            is_online = row['status'] == 'online'
            if is_online and not has_alert:
                healthy_count += 1

            device_list.append({
                'dashboard_id': row['dashboard_id'],
                'dashboard_name': row['dashboard_name'] or '',
                'owner_name': row['owner_name'] or '',
                'device_id': row['device_id'],
                'device_name': row['device_name'],
                'device_type': row['device_type'],
                'location': row['location'],
                'latitude': row['latitude'] or 0,
                'longitude': row['longitude'] or 0,
                'status': row['status'],
                'last_seen': _clean_timestamp(row['last_seen']),
                'last_ip': row['last_ip'] or '',
                'firmware_version': row['firmware_version'] or '',
                'offline_timeout': row['offline_timeout'] or 900,
                'expected_interval': row['expected_interval'] or 60,
                'offline_alert_severity': row['offline_alert_severity'] or 'danger',
                'latest_wifi_ssid': row['latest_wifi_ssid'] or '',
                'latest_uptime_seconds': row['latest_uptime_seconds'] or 0,
                'latest_data_at': _clean_timestamp(row['latest_data_at']),
                'has_alert': has_alert,
                'top_alert_severity': row['top_alert_severity'],
                'top_alert_type': row['top_alert_type'],
                'top_alert_message': row['top_alert_message'],
                'top_alert_created_at': _clean_timestamp(row['top_alert_created_at']),
                'total_active_alerts': row['total_active_alerts'] or 0,
            })

    return jsonify({
        'success': True,
        'summary': {
            'total_devices': total,
            'online_devices': online,
            'offline_devices': offline,
            'healthy_devices': healthy_count,
            'active_alerts': alert_summary['total'],
            'danger_alerts': alert_summary['danger'],
            'warning_alerts': alert_summary['warning'],
            'info_alerts': alert_summary['info'],
        },
        'devices': device_list,
    }), 200


# ==========================================
# ALERTS
# ==========================================
@api_bp.route('/alerts', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_alerts():
    severity = request.args.get('severity')
    device_id = request.args.get('device_id')
    limit = min(request.args.get('limit', 100, type=int), 500)
    with get_db_context() as conn:
        scope = ws.resolve_scope(conn)
    if scope['error']:
        return ws.scope_error_response(scope)
    alerts = get_active_alerts(limit=limit, severity=severity, device_id=device_id, scope=scope)
    for a in alerts:
        a['created_at'] = _clean_timestamp(a.get('created_at'))
        a['updated_at'] = _clean_timestamp(a.get('updated_at'))
    return jsonify({'success': True, 'alerts': alerts, 'count': len(alerts)}), 200


@api_bp.route('/alerts/history', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_alerts_history():
    device_id = request.args.get('device_id')
    limit = min(request.args.get('limit', 200, type=int), 1000)
    with get_db_context() as conn:
        scope = ws.resolve_scope(conn)
    if scope['error']:
        return ws.scope_error_response(scope)
    history = get_alert_history(device_id, limit, scope=scope)
    for h in history:
        h['created_at'] = _clean_timestamp(h.get('created_at'))
    return jsonify({'success': True, 'history': history}), 200


@api_bp.route('/alerts/stats', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_alert_stats():
    with get_db_context() as conn:
        scope = ws.resolve_scope(conn)
        if scope['error']:
            return ws.scope_error_response(scope)
        sc_sql, sc_params = ws.device_in_sql(scope, 'device_id')
        sa_sql, sa_params = ws.device_in_sql(scope, 'a.device_id')

        summary = {'danger': 0, 'warning': 0, 'info': 0, 'total': 0}
        rows = conn.execute(f'''
            SELECT severity, COUNT(*) as count
            FROM alerts WHERE is_active = 1 AND alert_type != 'uid' AND {sc_sql}
            GROUP BY severity
        ''', sc_params).fetchall()
        for r in rows:
            if r['severity'] in summary:
                summary[r['severity']] = r['count']
            summary['total'] += r['count']

        top_devices = conn.execute(f'''
            SELECT a.device_id, d.device_name, COUNT(*) as alert_count,
                   SUM(CASE WHEN a.severity = 'danger' THEN 1 ELSE 0 END) as danger_count,
                   SUM(CASE WHEN a.severity = 'warning' THEN 1 ELSE 0 END) as warning_count
            FROM alerts a
            JOIN devices d ON a.device_id = d.device_id
            WHERE a.is_active = 1 AND a.alert_type != 'uid' AND {sa_sql}
            GROUP BY a.device_id
            ORDER BY alert_count DESC LIMIT 5
        ''', sa_params).fetchall()

        total_history = conn.execute(
            f'SELECT COUNT(*) FROM alert_history WHERE {sc_sql}', sc_params
        ).fetchone()[0]
        active_count = conn.execute(
            f"SELECT COUNT(*) FROM alerts WHERE is_active = 1 AND alert_type != 'uid' AND {sc_sql}",
            sc_params
        ).fetchone()[0]

    return jsonify({
        'success': True,
        'summary': summary,
        'top_devices': [dict(r) for r in top_devices],
        'total_history': total_history,
        'active_count': active_count,
    }), 200


@api_bp.route('/alerts/all', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_all_alerts():
    status = request.args.get('status', 'all')
    severity = request.args.get('severity')
    device_id = request.args.get('device_id')
    limit = min(request.args.get('limit', 200, type=int), 1000)

    with get_db_context() as conn:
        scope = ws.resolve_scope(conn)
        if scope['error']:
            return ws.scope_error_response(scope)
        sh_sql, sh_params = ws.device_in_sql(scope, 'h.device_id')

        base_query = '''
            SELECT * FROM (
                SELECT h.id, h.device_id, h.alert_type, h.severity, h.message,
                       h.value, h.action, h.created_at,
                       d.device_name, d.location,
                       active_alerts.id AS alert_id,
                       CASE
                           WHEN h.action IN ('cleared', 'acknowledged') THEN 0
                           WHEN active_alerts.device_id IS NOT NULL THEN 1
                           ELSE 0
                       END as is_still_active,
                       ROW_NUMBER() OVER (
                           PARTITION BY h.device_id, h.alert_type
                           ORDER BY h.created_at DESC, h.id DESC
                       ) AS rn
                FROM alert_history h
                LEFT JOIN devices d ON h.device_id = d.device_id
                LEFT JOIN (
                    SELECT id, device_id, alert_type
                    FROM alerts
                    WHERE is_active = 1
                ) active_alerts
                    ON active_alerts.device_id = h.device_id
                   AND active_alerts.alert_type = h.alert_type
                WHERE h.alert_type != 'uid'
        '''
        params = []
        base_query += f' AND {sh_sql}'
        params.extend(sh_params)

        if severity:
            base_query += ' AND h.severity = ?'
            params.append(severity)

        if device_id:
            base_query += ' AND h.device_id = ?'
            params.append(device_id)

        base_query += '''
            ) sub
            WHERE rn = 1
        '''

        if status == 'active':
            base_query += ' AND is_still_active = 1'
        elif status == 'resolved':
            base_query += ' AND is_still_active = 0'

        base_query += ' ORDER BY created_at DESC LIMIT ?'
        params.append(limit)

        rows = conn.execute(base_query, params).fetchall()

    alerts = []
    for r in rows:
        d = dict(r)
        d.pop('rn', None)
        d['created_at'] = _clean_timestamp(d.get('created_at'))
        d['label'] = _alert_label(d['alert_type'], d['severity'])
        alerts.append(d)

    return jsonify({'success': True, 'alerts': alerts, 'count': len(alerts)}), 200


@api_bp.route('/alerts/<int:alert_id>/acknowledge', methods=['POST'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def acknowledge_alert_endpoint(alert_id):
    with get_db_context() as conn:
        scope = ws.resolve_scope(conn, 'editor')
    if scope['error']:
        return ws.scope_error_response(scope)
    success = acknowledge_alert(alert_id, scope=scope)
    if not success:
        return jsonify({'success': False, 'error': 'Alert not found or already acknowledged'}), 404
    return jsonify({'success': True}), 200


@api_bp.route('/alerts/bulk-acknowledge', methods=['POST'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def bulk_acknowledge():
    payload = request.get_json(silent=True)
    if not payload or not isinstance(payload.get('ids'), list):
        return jsonify({'success': False, 'error': 'Kirim {"ids": [1, 2, 3]}'}), 400

    ids = []
    for i in payload['ids']:
        try:
            ids.append(int(i))
        except (ValueError, TypeError):
            continue

    if not ids:
        return jsonify({'success': False, 'error': 'Tidak ada ID valid'}), 400

    with get_db_context() as conn:
        scope = ws.resolve_scope(conn, 'editor')
    if scope['error']:
        return ws.scope_error_response(scope)
    count = bulk_acknowledge_alerts(ids, scope=scope)
    return jsonify({'success': True, 'acknowledged': count}), 200


@api_bp.route('/devices/<device_id>/status-history', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_device_status_history(device_id):
    limit = min(request.args.get('limit', 100, type=int), 500)
    with get_db_context() as conn:
        _, denied = ws.load_device(conn, device_id, 'viewer', 'device_id')
        if denied:
            return denied
        rows = conn.execute('''
            SELECT status, reason, created_at FROM device_status_log
            WHERE device_id = ? ORDER BY created_at DESC LIMIT ?
        ''', (device_id, limit)).fetchall()

    history = []
    for r in rows:
        d = dict(r)
        d['created_at'] = _clean_timestamp(d.get('created_at'))
        history.append(d)

    return jsonify({
        'success': True,
        'history': history,
        'count': len(history)
    }), 200


@api_bp.route('/devices/<device_id>/export', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def export_device_data(device_id):
    format_type = request.args.get('format', 'csv').lower()
    hours = min(request.args.get('hours', 24, type=int), 8760)
    limit = min(request.args.get('limit', 10000, type=int), 50000)
    since = get_wib_time() - timedelta(hours=hours)

    with get_db_context() as conn:
        device, denied = ws.load_device(conn, device_id, 'viewer', 'device_name')
        if denied:
            return denied

        rows = conn.execute('''
            SELECT sensor_type, data, wifi_ssid, uptime_seconds, timestamp
            FROM sensor_data
            WHERE device_id = ? AND timestamp >= ?
            ORDER BY timestamp ASC LIMIT ?
        ''', (device_id, since, limit)).fetchall()

    records = []
    all_keys = set()
    for item in rows:
        parsed = safe_json_loads(item['data'])
        record = {
            'timestamp': _clean_timestamp(item['timestamp']),
            'sensor_type': item['sensor_type'],
            'wifi_ssid': item['wifi_ssid'] or '',
            'uptime_seconds': item['uptime_seconds'] or 0,
        }
        for k, v in parsed.items():
            record[k] = v
            all_keys.add(k)
        records.append(record)

    sorted_keys = sorted(all_keys)

    if format_type == 'csv':
        output = io.StringIO()
        headers = ['timestamp', 'sensor_type', 'wifi_ssid', 'uptime_seconds'] + sorted_keys
        writer = csv.DictWriter(output, fieldnames=headers, extrasaction='ignore')
        writer.writeheader()
        for r in records:
            writer.writerow({k: csv_safe(v) for k, v in r.items()})

        filename = f"{device_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(output.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename="{filename}"'})

    filename = f"{device_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return Response(
        json.dumps({
            'device_id': device_id,
            'device_name': device['device_name'],
            'exported_at': _clean_timestamp(get_wib_time().isoformat()),
            'range_hours': hours,
            'count': len(records),
            'data': records,
        }, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@api_bp.route('/system/info', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_system_info():
    from app import __version__
    config = get_config()

    with get_db_context() as conn:
        scope = ws.resolve_scope(conn)
        if scope['error']:
            return ws.scope_error_response(scope)
        sd_sql, sd_params = ws.dashboard_in_sql(scope, 'dashboard_id')
        sv_sql, sv_params = ws.device_in_sql(scope, 'device_id')
        device_count = conn.execute(
            f'SELECT COUNT(*) FROM devices WHERE {sd_sql}', sd_params).fetchone()[0]
        sensor_count = conn.execute(
            f'SELECT COUNT(*) FROM sensor_data WHERE {sv_sql}', sv_params).fetchone()[0]
        alert_count = conn.execute(
            f"SELECT COUNT(*) FROM alerts WHERE is_active = 1 AND alert_type != 'uid' AND {sv_sql}",
            sv_params).fetchone()[0]
        history_count = conn.execute(
            f'SELECT COUNT(*) FROM alert_history WHERE {sv_sql}', sv_params).fetchone()[0]
    db_size = 0
    db_path = config.DB_PATH
    if os.path.exists(db_path):
        db_size = os.path.getsize(db_path)
    wal_path = db_path + '-wal'
    if os.path.exists(wal_path):
        db_size += os.path.getsize(wal_path)

    return jsonify({
        'success': True,
        'info': {
            'version': __version__,
            'device_count': device_count,
            'sensor_data_count': sensor_count,
            'active_alerts': alert_count,
            'alert_history_count': history_count,
            'database_size_bytes': db_size,
            'database_size_mb': round(db_size / (1024 * 1024), 2),
            'data_retention_days': config.DATA_RETENTION_DAYS,
            'background': get_background_status(config),
        }
    }), 200


# ==========================================
# NOTIFICATIONS
# ==========================================
@api_bp.route('/notifications/test', methods=['POST'])
@login_required
@admin_required
@limiter.limit("10 per minute")
def test_notification():
    try:
        results = send_test_notification()
        # Kunci berawalan '_' adalah info diagnostik (mis. "Telegram not enabled"),
        # bukan hasil pengiriman. Kalau semua channel kosong, TIDAK boleh dianggap sukses.
        channels = {k: r for k, r in results.items() if not k.startswith('_')}
        all_success = bool(channels) and all(
            r.get('success', False) for r in channels.values()
        )
        status = 200 if all_success else 503
        return jsonify({'success': all_success, 'results': results}), status
    except Exception as e:
        logger.error(f"Test notification failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Terjadi kesalahan internal. Detail ada di log server.'}), 500


@api_bp.route('/notifications/config', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def notification_config():
    return jsonify({'success': True, 'config': get_notification_status()}), 200


# ==========================================
# USER MANAGEMENT
# ==========================================
from werkzeug.security import generate_password_hash, check_password_hash




@api_bp.route('/users/me', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_current_user():
    uid = _current_user_id()
    if not uid:
        return jsonify({'success': False, 'error': 'Session invalid'}), 401
    with get_db_context() as conn:
        row = conn.execute(
            'SELECT id, username, display_name FROM users WHERE id = ?',
            (uid,)
        ).fetchone()
        info = perm.get_user_info(conn, uid)
        effective = sorted(perm.effective_permissions(conn, uid)) if info else []
    if not row or not info:
        return jsonify({'success': False, 'error': 'User tidak ditemukan'}), 404
    return jsonify({
        'success': True,
        'user': {
            'id': row['id'],
            'username': row['username'],
            'display_name': row['display_name'] or row['username'],
            'is_admin': info['is_admin'],
            'role': info['role'],
            'permissions': effective,
        }
    }), 200


@api_bp.route('/users', methods=['GET'])
@login_required
@admin_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def list_users():
    with get_db_context() as conn:
        rows = conn.execute('''
            SELECT id, username, display_name, is_admin, role, created_at
            FROM users
            ORDER BY is_admin DESC, username ASC
        ''').fetchall()

    users = []
    for r in rows:
        d = dict(r)
        d['is_admin'] = bool(d['is_admin'])
        d['role'] = perm.resolve_role(d['is_admin'], d.pop('role', None))
        d['created_at'] = _clean_timestamp(d.get('created_at'))
        users.append(d)

    return jsonify({'success': True, 'users': users}), 200


@api_bp.route('/users', methods=['POST'])
@login_required
@admin_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def create_user():
    payload = request.get_json(silent=True) or {}
    username = (payload.get('username') or '').strip()
    password = payload.get('password') or ''
    display_name = (payload.get('display_name') or '').strip() or username

    requested = payload.get('role')
    if requested is None:
        requested = perm.ROLE_ADMIN if payload.get('is_admin') else perm.ROLE_USER
    if requested not in (perm.ROLE_ADMIN, perm.ROLE_MODERATOR, perm.ROLE_USER):
        return jsonify({'success': False, 'error': 'Peran tidak valid'}), 400
    is_admin = requested == perm.ROLE_ADMIN

    uerr = _validate_username(username)
    if uerr:
        return jsonify({'success': False, 'error': uerr}), 400
    if not password or len(password) < 8:
        return jsonify({'success': False, 'error': 'Password minimal 8 karakter'}), 400
    if len(display_name) > 128:
        return jsonify({'success': False, 'error': 'Display name maksimal 128 karakter'}), 400

    with get_db_context() as conn:
        caller = perm.get_user_info(conn, _current_user_id())
        if is_admin and not (caller and caller['role'] == perm.ROLE_SUPERADMIN):
            return jsonify({
                'success': False,
                'error': 'Hanya superadmin yang bisa memberi peran admin'
            }), 403

        existing = conn.execute(
            'SELECT id FROM users WHERE username = ?', (username,)
        ).fetchone()
        if existing:
            return jsonify({'success': False, 'error': 'Username sudah dipakai'}), 400

        pw_hash = generate_password_hash(password)
        cur = conn.execute('''
            INSERT INTO users (username, password_hash, display_name, is_admin, role, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (username, pw_hash, display_name, 1 if is_admin else 0, requested, get_wib_time()))
        new_id = cur.lastrowid
        ws.audit(conn, 'user.create', f'user={username} id={new_id} role={requested}')
        conn.commit()

    logger.info(f"User created: {username} (id={new_id}, admin={is_admin})")
    return jsonify({
        'success': True,
        'user': {
            'id': new_id,
            'username': username,
            'display_name': display_name,
            'is_admin': is_admin,
            'role': requested,
        }
    }), 201


@api_bp.route('/users/<int:user_id>', methods=['PUT'])
@login_required
@admin_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def update_user(user_id):
    payload = request.get_json(silent=True) or {}
    caller_id = _current_user_id()

    with get_db_context() as conn:
        user = conn.execute(
            'SELECT id, username, is_admin, role FROM users WHERE id = ?', (user_id,)
        ).fetchone()
        if not user:
            return jsonify({'success': False, 'error': 'User tidak ditemukan'}), 404

        target = perm.get_user_info(conn, user_id)
        caller = perm.get_user_info(conn, caller_id)
        caller_super = bool(caller and caller['role'] == perm.ROLE_SUPERADMIN)
        self_edit = user_id == caller_id

        # Admin biasa tidak boleh mengubah admin/superadmin lain.
        if perm.is_privileged(target['role']) and not caller_super and not self_edit:
            return jsonify({
                'success': False,
                'error': 'Hanya superadmin yang bisa mengubah admin lain'
            }), 403

        # Peran yang diminta (role lebih diutamakan daripada is_admin lama).
        requested_role = None
        if 'role' in payload:
            requested_role = payload.get('role')
        elif 'is_admin' in payload:
            requested_role = perm.ROLE_ADMIN if payload.get('is_admin') else perm.ROLE_USER

        fields = []
        params = []

        if 'display_name' in payload:
            dn = (payload.get('display_name') or '').strip()
            if not dn:
                return jsonify({'success': False, 'error': 'Display name tidak boleh kosong'}), 400
            if len(dn) > 128:
                return jsonify({'success': False, 'error': 'Display name maksimal 128 karakter'}), 400
            fields.append('display_name = ?')
            params.append(dn)

        if 'password' in payload:
            pw = payload.get('password') or ''
            if pw:
                if len(pw) < 8:
                    return jsonify({'success': False, 'error': 'Password minimal 8 karakter'}), 400
                fields.append('password_hash = ?')
                params.append(generate_password_hash(pw))

        role_changed = None
        if requested_role is not None and requested_role != target['role']:
            if target['role'] == perm.ROLE_SUPERADMIN:
                return jsonify({'success': False, 'error': 'Peran superadmin tidak bisa diubah'}), 403
            if requested_role not in (perm.ROLE_ADMIN, perm.ROLE_MODERATOR, perm.ROLE_USER):
                return jsonify({'success': False, 'error': 'Peran tidak valid'}), 400
            if self_edit and not caller_super:
                return jsonify({'success': False, 'error': 'Anda tidak bisa mengubah peran akun sendiri'}), 403
            if requested_role == perm.ROLE_ADMIN and not caller_super:
                return jsonify({'success': False, 'error': 'Hanya superadmin yang bisa memberi peran admin'}), 403
            if perm.is_privileged(target['role']) and not perm.is_privileged(requested_role):
                admin_count = conn.execute(
                    'SELECT COUNT(*) FROM users WHERE is_admin = 1'
                ).fetchone()[0]
                if admin_count <= 1:
                    return jsonify({
                        'success': False,
                        'error': 'Tidak bisa demote admin terakhir'
                    }), 400
            fields.append('role = ?')
            params.append(requested_role)
            fields.append('is_admin = ?')
            params.append(1 if perm.is_privileged(requested_role) else 0)
            role_changed = (target['role'], requested_role)

        if not fields:
            return jsonify({'success': False, 'error': 'Tidak ada field yang diupdate'}), 400

        params.append(user_id)
        conn.execute(
            f'UPDATE users SET {", ".join(fields)} WHERE id = ?', params
        )
        if role_changed:
            ws.audit(conn, 'user.role',
                     f"user={user['username']} id={user_id} {role_changed[0]}->{role_changed[1]}")
        conn.commit()

    logger.info(f"User updated: id={user_id}")
    return jsonify({'success': True}), 200


@api_bp.route('/users/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def delete_user(user_id):
    if user_id == _current_user_id():
        return jsonify({'success': False, 'error': 'Tidak bisa hapus akun sendiri'}), 400

    with get_db_context() as conn:
        user = conn.execute(
            'SELECT id, username, is_admin, role FROM users WHERE id = ?', (user_id,)
        ).fetchone()
        if not user:
            return jsonify({'success': False, 'error': 'User tidak ditemukan'}), 404

        target_role = perm.resolve_role(user['is_admin'], user['role'])
        caller = perm.get_user_info(conn, _current_user_id())
        if target_role == perm.ROLE_SUPERADMIN:
            return jsonify({'success': False, 'error': 'Superadmin tidak bisa dihapus'}), 403
        if perm.is_privileged(target_role) and not (caller and caller['role'] == perm.ROLE_SUPERADMIN):
            return jsonify({'success': False, 'error': 'Hanya superadmin yang bisa menghapus admin'}), 403

        if user['is_admin']:
            admin_count = conn.execute(
                'SELECT COUNT(*) FROM users WHERE is_admin = 1'
            ).fetchone()[0]
            if admin_count <= 1:
                return jsonify({
                    'success': False,
                    'error': 'Tidak bisa hapus admin terakhir'
                }), 400

        dash_ids = [
            r[0] for r in conn.execute(
                'SELECT id FROM dashboards WHERE user_id = ?', (user_id,)
            ).fetchall()
        ]

        # Perangkat milik user yang dihapus TIDAK ikut hilang: dipindah ke
        # dashboard default admin yang melakukan penghapusan.
        acting = conn.execute(
            'SELECT id FROM dashboards WHERE user_id = ? ORDER BY is_default DESC, id ASC LIMIT 1',
            (_current_user_id(),)
        ).fetchone()
        target_dash = acting['id'] if acting else None

        # Kalau admin pelaku tidak punya dashboard tujuan, perangkat milik
        # user yang dihapus akan jadi yatim (dashboard_id=NULL) → lenyap dari
        # semua halaman. Tolak dulu supaya datanya tidak hilang diam-diam.
        if target_dash is None and dash_ids:
            orphan = 0
            for did in dash_ids:
                orphan += conn.execute(
                    'SELECT COUNT(*) FROM devices WHERE dashboard_id = ?', (did,)
                ).fetchone()[0]
            if orphan:
                return jsonify({
                    'success': False,
                    'error': (f'Anda belum punya dashboard tujuan untuk menampung '
                              f'{orphan} perangkat milik user ini. Buat '
                              f'dashboard dulu, lalu hapus ulang user.'),
                }), 409

        moved_devices = 0
        from app.dashboards import purge_dashboard
        for did in dash_ids:
            moved_devices += conn.execute(
                'UPDATE devices SET dashboard_id = ? WHERE dashboard_id = ?', (target_dash, did)
            ).rowcount
            purge_dashboard(conn, did)

        conn.execute('DELETE FROM dashboard_members WHERE user_id = ?', (user_id,))
        conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
        ws.audit(conn, 'user.delete',
                 f"user={user['username']} id={user_id} devices_moved={moved_devices}")
        conn.commit()

    logger.warning(f"User deleted: {user['username']} (id={user_id})")
    return jsonify({'success': True}), 200


@api_bp.route('/users/<int:user_id>/permissions', methods=['GET'])
@login_required
@admin_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_user_permissions(user_id):
    with get_db_context() as conn:
        target = perm.get_user_info(conn, user_id)
        if not target:
            return jsonify({'success': False, 'error': 'User tidak ditemukan'}), 404
        explicit = sorted(perm.explicit_permissions(conn, user_id))
        effective = sorted(perm.effective_permissions(conn, user_id))
    return jsonify({
        'success': True,
        'role': target['role'],
        'implicit_all': perm.is_privileged(target['role']),
        'explicit': explicit,
        'permissions': effective,
    }), 200


@api_bp.route('/users/<int:user_id>/permissions', methods=['PUT'])
@login_required
@admin_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def update_user_permissions(user_id):
    payload = request.get_json(silent=True) or {}

    with get_db_context() as conn:
        target = perm.get_user_info(conn, user_id)
        if not target:
            return jsonify({'success': False, 'error': 'User tidak ditemukan'}), 404
        if perm.is_privileged(target['role']):
            return jsonify({
                'success': False,
                'error': 'Admin dan superadmin sudah punya semua izin'
            }), 400

        before = sorted(perm.explicit_permissions(conn, user_id))
        after = sorted(perm.set_user_permissions(
            conn, user_id, _current_user_id()))
        username = conn.execute(
            'SELECT username FROM users WHERE id = ?', (user_id,)
        ).fetchone()['username']
        if before != after:
            ws.audit(conn, 'user.permissions',
                     f"user={username} id={user_id} {','.join(before) or '-'}->{','.join(after) or '-'}")
        effective = sorted(perm.effective_permissions(conn, user_id))
        conn.commit()

    return jsonify({'success': True, 'permissions': effective}), 200


# ==========================================
# MANUAL BACKUP
# ==========================================
@api_bp.route('/system/backup', methods=['POST'])
@login_required
@admin_required
@limiter.limit("5 per minute")
def trigger_backup():
    config = get_config()
    try:
        from app.background import create_backup_file
        backup_path = create_backup_file(config.BACKUP_DIR, config.DB_PATH)

        size_mb = os.path.getsize(backup_path) / (1024 * 1024)
        filename = os.path.basename(backup_path)

        logger.info(f"Manual backup created: {backup_path} ({size_mb:.2f} MB)")
        return jsonify({
            'success': True,
            'filename': filename,
            'size_mb': round(size_mb, 2),
            'message': f'Backup berhasil dibuat ({size_mb:.2f} MB)',
        }), 200
    except Exception as e:
        logger.error(f"Manual backup failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Terjadi kesalahan internal. Detail ada di log server.'}), 500


@api_bp.route('/system/backups', methods=['GET'])
@login_required
@admin_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def list_backups():
    config = get_config()
    backups = []
    try:
        os.makedirs(config.BACKUP_DIR, exist_ok=True)
        for filename in os.listdir(config.BACKUP_DIR):
            if not filename.endswith('.db'):
                continue
            filepath = os.path.join(config.BACKUP_DIR, filename)
            if not os.path.isfile(filepath):
                continue
            stat = os.stat(filepath)
            backups.append({
                'filename': filename,
                'size_bytes': stat.st_size,
                'size_mb': round(stat.st_size / (1024 * 1024), 2),
                'created_at': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                '_mtime': stat.st_mtime,
            })
        backups.sort(key=lambda x: x['_mtime'], reverse=True)
    except Exception as e:
        logger.error(f"List backups failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Terjadi kesalahan internal. Detail ada di log server.'}), 500

    for b in backups:
        b.pop('_mtime', None)

    return jsonify({
        'success': True,
        'backups': backups,
        'count': len(backups),
        'retention_days': config.BACKUP_RETENTION_DAYS,
        'backup_interval_hours': config.BACKUP_INTERVAL_HOURS,
        'auto_backup_enabled': config.BACKUP_ENABLED,
    }), 200


@api_bp.route('/system/backups/<path:filename>', methods=['GET'])
@login_required
@admin_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def download_backup(filename):
    from werkzeug.utils import secure_filename
    from flask import send_file

    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename or not safe_name.endswith('.db'):
        return jsonify({'success': False, 'error': 'Nama file tidak valid'}), 400

    config = get_config()
    filepath = os.path.join(config.BACKUP_DIR, safe_name)

    real_dir = os.path.realpath(config.BACKUP_DIR)
    real_path = os.path.realpath(filepath)
    if not real_path.startswith(real_dir + os.sep):
        logger.warning(f"Path traversal attempt: {filename} from {request.remote_addr}")
        return jsonify({'success': False, 'error': 'Akses ditolak'}), 403

    if not os.path.isfile(real_path):
        return jsonify({'success': False, 'error': 'File tidak ditemukan'}), 404

    logger.info(f"Backup downloaded: {safe_name} by user {_current_user_id()}")
    return send_file(real_path, as_attachment=True, download_name=safe_name)


# ==========================================
# MANUAL CLEANUP
# ==========================================
@api_bp.route('/system/cleanup', methods=['POST'])
@login_required
@admin_required
@limiter.limit("5 per hour")
def trigger_cleanup():
    config = get_config()
    try:
        now = get_wib_time()
        cutoff_sensor = now - timedelta(days=config.DATA_RETENTION_DAYS)
        cutoff_history = now - timedelta(days=config.ALERT_HISTORY_RETENTION_DAYS)
        cutoff_log = now - timedelta(days=config.STATUS_LOG_RETENTION_DAYS)

        with get_db_context() as conn:
            total_deleted = 0
            results = {}

            r = conn.execute('DELETE FROM sensor_data WHERE timestamp < ?', (cutoff_sensor,))
            results['sensor_data'] = r.rowcount
            total_deleted += r.rowcount

            r = conn.execute('DELETE FROM alert_history WHERE created_at < ?', (cutoff_history,))
            results['alert_history'] = r.rowcount
            total_deleted += r.rowcount

            r = conn.execute('DELETE FROM device_status_log WHERE created_at < ?', (cutoff_log,))
            results['device_status_log'] = r.rowcount
            total_deleted += r.rowcount

            r = conn.execute(
                '''DELETE FROM alerts
                   WHERE is_active = 0
                   AND updated_at IS NOT NULL
                   AND updated_at < ?''',
                (cutoff_history,)
            )
            results['alerts_inactive'] = r.rowcount
            total_deleted += r.rowcount

            conn.commit()

            if total_deleted > 1000:
                try:
                    conn.execute('VACUUM')
                    logger.info("VACUUM completed after manual cleanup")
                except Exception as ve:
                    logger.warning(f"VACUUM failed: {ve}")

        with get_db_context() as audit_conn:
            ws.audit(audit_conn, 'data.cleanup_retention', f'rows={total_deleted}')
            audit_conn.commit()
        logger.info(f"Manual cleanup by user {_current_user_id()}: {total_deleted} rows deleted")
        return jsonify({
            'success': True,
            'total_deleted': total_deleted,
            'details': {k: v for k, v in results.items() if v > 0},
            'message': f'{total_deleted} baris dihapus',
        }), 200
    except Exception as e:
        logger.error(f"Manual cleanup failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Terjadi kesalahan internal. Detail ada di log server.'}), 500




@api_bp.route('/system/data/preview', methods=['POST'])
@login_required
@admin_required
@limiter.limit("60 per hour")
def preview_data_purge():
    spec, err = _parse_purge_request(request.get_json(silent=True))
    if err:
        return jsonify({'success': False, 'error': err}), 400

    with get_db_context() as conn:
        tables, total_rows, total_bytes = _purge_preview(conn, spec)

    return jsonify({
        'success': True,
        'tables': tables,
        'total_rows': total_rows,
        'estimated_bytes': total_bytes,
        'estimated_mb': round(total_bytes / (1024 * 1024), 2),
        'note': 'Ukuran adalah perkiraan kasar. File database baru mengecil setelah "Kecilkan file".',
    }), 200


@api_bp.route('/system/data/delete', methods=['POST'])
@login_required
@admin_required
@limiter.limit("10 per hour")
def delete_data_range():
    """Hapus data per rentang waktu (opsional per perangkat/dashboard/tabel).

    Body: {tables, date_from?, date_to?, device_id?, dashboard_id?,
           confirm: true, backup_first?: bool}
    """
    payload = request.get_json(silent=True)
    spec, err = _parse_purge_request(payload)
    if err:
        return jsonify({'success': False, 'error': err}), 400
    if payload.get('confirm') is not True:
        return jsonify({
            'success': False,
            'error': 'Konfirmasi diperlukan. Lihat pratinjau dulu lalu kirim confirm=true.',
        }), 400

    config = get_config()
    backup_name = None
    try:
        if payload.get('backup_first'):
            from app.background import create_backup_file
            backup_path = create_backup_file(config.BACKUP_DIR, config.DB_PATH, prefix='pre-delete')
            backup_name = os.path.basename(backup_path)

        deleted = {}
        with get_db_context() as conn:
            for key in spec['tables']:
                table, _, _, _ = PURGE_TABLES[key]
                where, params = _purge_where(key, spec)
                total = 0
                while True:
                    r = conn.execute(
                        f'DELETE FROM {table} WHERE rowid IN '
                        f'(SELECT rowid FROM {table} WHERE {where} LIMIT {PURGE_BATCH})', params
                    )
                    conn.commit()
                    total += r.rowcount
                    if r.rowcount < PURGE_BATCH:
                        break
                deleted[key] = total

            total_deleted = sum(deleted.values())
            ws.audit(conn, 'data.delete', json.dumps({
                'tables': spec['tables'], 'from': spec['start'],
                'to_exclusive': spec['end_exclusive'], 'device_id': spec['device_id'],
                'dashboard_id': spec['dashboard_id'], 'deleted': deleted,
                'backup': backup_name,
            }, ensure_ascii=False))
            conn.commit()

        return jsonify({
            'success': True,
            'deleted': deleted,
            'total_deleted': total_deleted,
            'backup': backup_name,
            'message': f'{total_deleted} baris dihapus',
        }), 200
    except Exception as e:
        logger.error(f"Hapus data per rentang gagal: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Terjadi kesalahan internal. Detail ada di log server.',
            'backup': backup_name,
        }), 500


@api_bp.route('/system/vacuum', methods=['POST'])
@login_required
@admin_required
@limiter.limit("3 per hour")
def vacuum_database():
    """Kecilkan file database (VACUUM). Mengunci database sebentar."""
    import shutil
    config = get_config()
    db_path = config.DB_PATH

    def _size():
        total = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        wal = db_path + '-wal'
        return total + (os.path.getsize(wal) if os.path.exists(wal) else 0)

    before = _size()
    free = shutil.disk_usage(os.path.dirname(os.path.abspath(db_path))).free
    needed = int(before * 1.2)
    if free < needed:
        return jsonify({
            'success': False,
            'error': (f'Ruang disk kosong tidak cukup untuk VACUUM '
                      f'(butuh sekitar {needed // (1024 * 1024)} MB, tersedia {free // (1024 * 1024)} MB).'),
        }), 409

    try:
        conn = sqlite3.connect(db_path, timeout=60.0)
        conn.isolation_level = None
        try:
            conn.execute('PRAGMA busy_timeout=60000')
            conn.execute('VACUUM')
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"VACUUM gagal: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'VACUUM gagal. Database sedang sibuk? Coba lagi nanti.'}), 500

    after = _size()
    with get_db_context() as conn:
        ws.audit(conn, 'db.vacuum', f'before={before} after={after}')
        conn.commit()
    return jsonify({
        'success': True,
        'before_mb': round(before / (1024 * 1024), 2),
        'after_mb': round(after / (1024 * 1024), 2),
        'freed_mb': round(max(0, before - after) / (1024 * 1024), 2),
    }), 200


@api_bp.route('/system/backups/<path:filename>', methods=['DELETE'])
@login_required
@admin_required
@limiter.limit("20 per hour")
def delete_backup(filename):
    """Hapus satu file backup. Backup terbaru selalu dilindungi."""
    from werkzeug.utils import secure_filename

    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename or not safe_name.endswith('.db'):
        return jsonify({'success': False, 'error': 'Nama file tidak valid'}), 400

    config = get_config()
    real_dir = os.path.realpath(config.BACKUP_DIR)
    real_path = os.path.realpath(os.path.join(config.BACKUP_DIR, safe_name))
    if not real_path.startswith(real_dir + os.sep):
        logger.warning(f"Path traversal attempt (delete backup): {filename} from {request.remote_addr}")
        return jsonify({'success': False, 'error': 'Akses ditolak'}), 403
    if not os.path.isfile(real_path):
        return jsonify({'success': False, 'error': 'File tidak ditemukan'}), 404

    candidates = [
        os.path.join(real_dir, n) for n in os.listdir(real_dir)
        if n.endswith('.db') and os.path.isfile(os.path.join(real_dir, n))
    ]
    newest = max(candidates, key=os.path.getmtime) if candidates else None
    if newest and os.path.realpath(newest) == real_path:
        return jsonify({
            'success': False,
            'error': 'Backup terbaru dilindungi dan tidak bisa dihapus. Buat backup baru dulu bila perlu.',
        }), 409

    size = os.path.getsize(real_path)
    os.remove(real_path)
    with get_db_context() as conn:
        ws.audit(conn, 'backup.delete', f'file={safe_name} size={size}')
        conn.commit()
    return jsonify({'success': True, 'filename': safe_name, 'freed_bytes': size}), 200


@api_bp.route('/system/audit-log', methods=['GET'])
@login_required
@admin_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_audit_log():
    limit = min(request.args.get('limit', 50, type=int), 500)
    with get_db_context() as conn:
        rows = conn.execute(
            'SELECT id, username, action, detail, ip, created_at FROM audit_log '
            'ORDER BY id DESC LIMIT ?', (limit,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d['created_at'] = _clean_timestamp(d.get('created_at'))
        out.append(d)
    return jsonify({'success': True, 'entries': out}), 200


# ==========================================
# CHANGE OWN PASSWORD
# ==========================================
@api_bp.route('/users/me/password', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def change_own_password():
    uid = _current_user_id()
    if not uid:
        return jsonify({'success': False, 'error': 'Session invalid'}), 401

    payload = request.get_json(silent=True) or {}
    old_password = payload.get('old_password') or ''
    new_password = payload.get('new_password') or ''

    if not old_password or not new_password:
        return jsonify({'success': False, 'error': 'Password lama dan baru wajib diisi'}), 400
    if len(new_password) < 8:
        return jsonify({'success': False, 'error': 'Password baru minimal 8 karakter'}), 400
    if old_password == new_password:
        return jsonify({'success': False, 'error': 'Password baru harus berbeda dari yang lama'}), 400

    with get_db_context() as conn:
        user = conn.execute(
            'SELECT id, username, password_hash FROM users WHERE id = ?', (uid,)
        ).fetchone()
        if not user:
            return jsonify({'success': False, 'error': 'User tidak ditemukan'}), 404

        try:
            valid = check_password_hash(user['password_hash'], old_password)
        except Exception:
            valid = False

        if not valid:
            logger.warning(f"Change password failed (wrong old) for {user['username']}")
            return jsonify({'success': False, 'error': 'Password lama salah'}), 400

        new_hash = generate_password_hash(new_password)
        conn.execute('UPDATE users SET password_hash = ? WHERE id = ?', (new_hash, uid))
        conn.commit()

    logger.info(f"Password changed for user: {user['username']}")
    return jsonify({'success': True, 'message': 'Password berhasil diubah'}), 200

    # ==========================================
# BATCH 8: GLOBAL ALERT RULES EDITOR
# ==========================================


@api_bp.route('/system/alert-rules', methods=['GET'])
@login_required
@limiter.limit(lambda: get_config().RATE_LIMIT_DEFAULT)
def get_global_alert_rules():
    """Ambil global alert rules. Custom dari user_settings menang, fallback ke config."""
    from app.config import get_config as _gc
    config = _gc()

    with get_db_context() as conn:
        row = conn.execute(
            "SELECT value FROM user_settings WHERE key = 'global_alert_rules'"
        ).fetchone()

    custom_rules = None
    if row and row['value']:
        try:
            custom_rules = json.loads(row['value'])
        except (json.JSONDecodeError, TypeError):
            custom_rules = None

    default_rules = {k: v for k, v in config.ALERT_RULES.items() if isinstance(v, dict)}

    return jsonify({
        'success': True,
        'alert_rules': custom_rules or default_rules,
        'is_custom': custom_rules is not None,
        'default_rules': default_rules,
    }), 200


@api_bp.route('/system/alert-rules', methods=['PUT'])
@login_required
@admin_required
@limiter.limit("20 per minute")
def update_global_alert_rules():
    payload = request.get_json(silent=True)
    if payload is None or not isinstance(payload, dict):
        return jsonify({'success': False, 'error': 'Format rules harus object'}), 400

    is_valid, err_msg = validate_alert_rules(payload)
    if not is_valid:
        return jsonify({'success': False, 'error': err_msg}), 400

    if not payload:
        return jsonify({'success': False, 'error': 'Minimal 1 sensor rule'}), 400

    try:
        with get_db_context() as conn:
            conn.execute('''
                INSERT INTO user_settings (key, value, updated_at)
                VALUES ('global_alert_rules', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
            ''', (json.dumps(payload), get_wib_time()))
            conn.commit()

        invalidate_global_rules_cache()
        logger.info(f"Global alert rules updated by user {_current_user_id()}")
        return jsonify({
            'success': True,
            'alert_rules': payload,
            'message': 'Global alert rules tersimpan',
        }), 200
    except Exception as e:
        logger.error(f"Update global rules failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Terjadi kesalahan internal. Detail ada di log server.'}), 500


@api_bp.route('/system/alert-rules', methods=['DELETE'])
@login_required
@admin_required
@limiter.limit("20 per minute")
def reset_global_alert_rules():
    try:
        with get_db_context() as conn:
            conn.execute(
                "DELETE FROM user_settings WHERE key = 'global_alert_rules'"
            )
            conn.commit()

        invalidate_global_rules_cache()
        logger.info(f"Global alert rules reset by user {_current_user_id()}")
        return jsonify({
            'success': True,
            'message': 'Global alert rules direset ke default config',
        }), 200
    except Exception as e:
        logger.error(f"Reset global rules failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Terjadi kesalahan internal. Detail ada di log server.'}), 500


# ==========================================
# BATCH 8: RESTORE DATABASE FROM BACKUP
# ==========================================
@api_bp.route('/system/restore', methods=['POST'])
@login_required
@admin_required
@limiter.limit("2 per hour")
def restore_database():
    """Restore database dari file backup.
    
    PENTING:
    - Backup current DB dulu ke 'pre-restore-*.db'
    - Validate filename ketat (harus file .db di BACKUP_DIR)
    - Wajib konfirmasi string 'RESTORE'
    - Return instruksi restart manual (tidak auto-restart)
    """
    payload = request.get_json(silent=True) or {}
    filename = (payload.get('filename') or '').strip()
    confirm = (payload.get('confirm') or '').strip()

    if confirm != 'RESTORE':
        return jsonify({
            'success': False,
            'error': 'Konfirmasi salah. Kirim field "confirm" dengan nilai "RESTORE".'
        }), 400

    if not filename:
        return jsonify({'success': False, 'error': 'Filename wajib'}), 400

    from werkzeug.utils import secure_filename
    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename or not safe_name.endswith('.db'):
        return jsonify({'success': False, 'error': 'Nama file tidak valid'}), 400

    config = get_config()
    backup_file = os.path.join(config.BACKUP_DIR, safe_name)

    real_dir = os.path.realpath(config.BACKUP_DIR)
    real_path = os.path.realpath(backup_file)
    if not real_path.startswith(real_dir + os.sep):
        logger.warning(f"Restore path traversal attempt: {filename}")
        return jsonify({'success': False, 'error': 'Akses ditolak'}), 403

    if not os.path.isfile(real_path):
        return jsonify({'success': False, 'error': 'File backup tidak ditemukan'}), 404

    # Verify SQLite integrity
    try:
        test_conn = sqlite3.connect(real_path, timeout=5.0)
        result = test_conn.execute('PRAGMA integrity_check').fetchone()
        test_conn.close()
        if not result or result[0] != 'ok':
            return jsonify({
                'success': False,
                'error': f'File backup corrupt (integrity check: {result[0] if result else "unknown"})'
            }), 400
    except Exception as e:
        logger.error(f"Restore: verifikasi file backup gagal: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Gagal verifikasi file backup'
        }), 400

    # Backup current DB sebelum restore
    pre_restore_name = f"pre-restore-{get_wib_time().strftime('%Y%m%d_%H%M%S')}.db"
    pre_restore_path = os.path.join(config.BACKUP_DIR, pre_restore_name)

    try:
        os.makedirs(config.BACKUP_DIR, exist_ok=True)
        src = sqlite3.connect(config.DB_PATH, timeout=30.0)
        dst = sqlite3.connect(pre_restore_path)
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        logger.info(f"Pre-restore backup saved: {pre_restore_path}")
    except Exception as e:
        logger.error(f"Restore: backup DB current gagal: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Gagal membuat backup DB saat ini'
        }), 500

    # Jangan menimpa DB hidup: siapkan file pending + penanda, diterapkan saat start.
    try:
        from app.restore import schedule_restore
        schedule_restore(real_path, config.DB_PATH, {
            'pre_restore_backup': pre_restore_name,
            'requested_by': _current_user_id(),
        })
        logger.warning(
            f"DATABASE RESTORE DIJADWALKAN by user {_current_user_id()}: "
            f"from {safe_name} (pre-restore backup: {pre_restore_name}); "
            f"diterapkan saat restart"
        )
    except Exception as e:
        logger.error(f"Restore failed: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Gagal menyiapkan restore. Pre-restore backup di: {pre_restore_name}'
        }), 500

    return jsonify({
        'success': True,
        'message': (
            'Restore disiapkan dan akan diterapkan saat aplikasi di-restart. '
            'PENTING: Restart container/aplikasi sekarang (hentikan semua worker, lalu start). '
            f'Pre-restore backup: {pre_restore_name}'
        ),
        'pre_restore_backup': pre_restore_name,
        'restored_from': safe_name,
        'restart_required': True,
    }), 200


# ==========================================
# BATCH 8: DEVICE BULK IMPORT
# ==========================================
@api_bp.route('/devices/bulk-import', methods=['POST'])
@login_required
@admin_required
@limiter.limit("10 per minute")
def bulk_import_devices():
    """Bulk import devices.
    
    Body: { devices: [ {device_id, device_name, ...}, ... ] }
    Max 200 devices per call.
    Return: { created: [...], skipped: [...], errors: [...] }
    """
    try:
        payload = request.get_json(silent=True)
        if not payload or not isinstance(payload.get('devices'), list):
            return jsonify({
                'success': False,
                'error': 'Kirim {"devices": [...]} dengan array'
            }), 400

        items = payload['devices']
        if len(items) == 0:
            return jsonify({'success': False, 'error': 'Array kosong'}), 400
        if len(items) > 200:
            return jsonify({
                'success': False,
                'error': f'Maksimal 200 device per import. Dikirim: {len(items)}'
            }), 400

        created = []
        skipped = []
        errors = []

        with get_db_context() as conn:
            scope = ws.resolve_scope(conn, 'editor')
            if scope['error']:
                return ws.scope_error_response(scope)
            dashboard_id, denied = ws.pick_write_dashboard(
                conn, scope, requested_id=payload.get('dashboard_id'), minimum='editor'
            )
            if denied:
                return denied

            for idx, raw in enumerate(items):
                if not isinstance(raw, dict):
                    errors.append({'row': idx + 1, 'error': 'Bukan object'})
                    continue

                try:
                    data = bulk_import_item_schema.load(raw)
                except ValidationError as err:
                    err_msgs = err.messages
                    err_str = '; '.join(
                        f"{k}: {', '.join(v) if isinstance(v, list) else v}"
                        for k, v in err_msgs.items()
                    )
                    errors.append({
                        'row': idx + 1,
                        'device_id': raw.get('device_id', '?'),
                        'error': err_str,
                    })
                    continue

                device_id = data['device_id']

                existing = conn.execute(
                    'SELECT device_id FROM devices WHERE device_id = ?', (device_id,)
                ).fetchone()
                if existing:
                    skipped.append({
                        'row': idx + 1,
                        'device_id': device_id,
                        'reason': 'Sudah ada',
                    })
                    continue

                try:
                    api_key = generate_api_key()
                    api_key_hash = hash_api_key(api_key)

                    offline_timeout = data.get('offline_timeout')
                    device_type = (data.get('device_type') or '').strip()
                    if offline_timeout is None and 'rfid' in device_type.lower():
                        offline_timeout = 86400

                    conn.execute('''
                        INSERT INTO devices
                        (device_id, device_name, device_type, location, description,
                         firmware_version,
                         api_key, api_key_hash, offline_timeout, expected_interval,
                         alert_rules, offline_alert_severity, created_at, dashboard_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        device_id,
                        data['device_name'],
                        data['device_type'],
                        data.get('location', ''),
                        data.get('description', ''),
                        data.get('firmware_version', ''),
                        None, api_key_hash,
                        offline_timeout,
                        None,
                        None,
                        data.get('offline_alert_severity', 'danger'),
                        get_wib_time(),
                        dashboard_id,
                    ))

                    created.append({
                        'row': idx + 1,
                        'device_id': device_id,
                        'device_name': data['device_name'],
                        'api_key': api_key,
                    })
                except Exception as e:
                    errors.append({
                        'row': idx + 1,
                        'device_id': device_id,
                        'error': str(e),
                    })

            conn.commit()

        logger.info(
            f"Bulk import by user {_current_user_id()}: "
            f"{len(created)} created, {len(skipped)} skipped, {len(errors)} errors"
        )

        return jsonify({
            'success': True,
            'created': created,
            'skipped': skipped,
            'errors': errors,
            'summary': {
                'total': len(items),
                'created': len(created),
                'skipped': len(skipped),
                'errors': len(errors),
            },
            'warning': 'Simpan semua API key! Tidak akan ditampilkan lagi.',
        }), 200

    except Exception as e:
        logger.error(f"Bulk import failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Internal server error'}), 500


# ==========================================
# BATCH 8: NOTIFICATION CONFIG (extended)
# ==========================================
@api_bp.route('/notifications/test-channel', methods=['POST'])
@login_required
@admin_required
@limiter.limit("10 per minute")
def test_notification_channel():
    """Test 1 channel spesifik. Body: {channel: 'telegram'}"""
    payload = request.get_json(silent=True) or {}
    channel = (payload.get('channel') or '').strip().lower()

    if channel not in ('telegram',):
        return jsonify({'success': False, 'error': f'Channel "{channel}" tidak dikenal'}), 400

    try:
        results = send_test_notification()
        ch_result = results.get(channel)
        if not ch_result:
            return jsonify({
                'success': False,
                'error': f'Channel {channel} tidak terkonfigurasi',
                'all_results': results,
            }), 400

        return jsonify({
            'success': ch_result.get('success', False),
            'channel': channel,
            'result': ch_result,
        }), 200 if ch_result.get('success') else 500
    except Exception as e:
        logger.error(f"Test channel failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Terjadi kesalahan internal. Detail ada di log server.'}), 500