"""AAguard IoT - FastAPI device/dashboard endpoints (dari app/api.py)."""
import csv
import io
import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from app.api_common import _clean_timestamp
from app.config import get_config
from app.deps import (get_current_user, load_device as _dl,
                      pick_write_dashboard as _pw, resolve_scope as _rs,
                      scope_error_response as _se, dashboard_in_sql,
                      device_in_sql)
from app.deps import limiter
from app.deps import safe_json

logger = logging.getLogger('aaguard')
router = APIRouter(prefix='/api/v1', tags=['devices'])


@router.get('/dashboard')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_dashboard_data(request: Request):
    from app.database import get_db_context
    user = get_current_user(request)

    async def _do():
        async with get_db_context() as conn:
            scope = await _rs(conn, request, user['user_id'])
            if scope['error']:
                return _se(scope)
            dev_sql, dev_params = dashboard_in_sql(scope, 'dashboard_id')
            d_sql, d_params = dashboard_in_sql(scope, 'd.dashboard_id')
            al_sql, al_params = device_in_sql(scope, 'device_id')
            counts = await (await conn.execute(f'''
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) AS online,
                    SUM(CASE WHEN status = 'offline' THEN 1 ELSE 0 END) AS offline
                FROM devices WHERE {dev_sql}
            ''', dev_params)).fetchone()
            total = counts['total'] or 0
            online = counts['online'] or 0
            offline = counts['offline'] or 0
            alert_rows = await (await conn.execute(f'''
                SELECT severity, COUNT(*) AS count
                FROM alerts
                WHERE is_active = 1 AND alert_type != 'uid' AND {al_sql}
                GROUP BY severity
            ''', al_params)).fetchall()
            alert_summary = {'danger': 0, 'warning': 0, 'info': 0, 'total': 0}
            for row in alert_rows:
                if row['severity'] in alert_summary:
                    alert_summary[row['severity']] = row['count']
                alert_summary['total'] += row['count']
            rows = await (await conn.execute(f'''
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
            ''', d_params)).fetchall()
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
        return None, {
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
        }

    err, data = await _do()
    if err is not None:
        return err
    return JSONResponse({'success': True, **data})


@router.get('/metrics/devices-history')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_devices_metrics_history(request: Request):
    from app.database import get_db_context, get_wib_time
    user = get_current_user(request)
    hours = min(max(int(request.query_params.get('hours', '24') or 24), 1), 168)

    async def _do():
        since = get_wib_time() - timedelta(hours=hours)
        async with get_db_context() as conn:
            scope = await _rs(conn, request, user['user_id'])
            if scope['error']:
                return _se(scope), None
            dev_sql, dev_params = dashboard_in_sql(scope, 'dv.dashboard_id')
            st_sql, st_params = device_in_sql(scope, 'sl.device_id')
            al_sql, al_params = device_in_sql(scope, 'a.device_id')
            all_devices = await (await conn.execute(f'''
                SELECT dv.device_id, dv.created_at, dv.status
                FROM devices dv WHERE {dev_sql}
            ''', dev_params)).fetchall()
            buckets = []
            cursor = since.replace(minute=0, second=0, microsecond=0)
            end = get_wib_time().replace(minute=0, second=0, microsecond=0)
            guard = 0
            while cursor <= end and guard < 200:
                buckets.append(cursor)
                cursor += timedelta(hours=1)
                guard += 1
            if not buckets:
                return None, {'hours': hours, 'buckets': [], 'total': [], 'online': [],
                              'offline': [], 'alerts': []}
            n = len(buckets)
            total_series = []
            for b in buckets:
                b_str = b.strftime('%Y-%m-%d %H:%M:%S')
                cnt = sum(1 for d in all_devices if d['created_at'] and str(d['created_at']) <= b_str)
                total_series.append(cnt)
            log_rows = await (await conn.execute(f'''
                SELECT
                    strftime('%Y-%m-%d %H:00', sl.created_at) AS bucket,
                    sl.device_id,
                    sl.status
                FROM device_status_log sl
                WHERE sl.created_at >= ?
                  AND sl.status IN ('online', 'offline')
                  AND {st_sql}
            ''', [since] + st_params)).fetchall()
            trans_map = {}
            for r in log_rows:
                trans_map.setdefault(r['bucket'], {})[r['device_id']] = r['status']
            online_series = [0] * n
            for d in all_devices:
                did = d['device_id']
                cur_status = d['status'] or 'offline'
                cr = d['created_at']
                if not cr:
                    continue
                first_idx = n
                for i, b in enumerate(buckets):
                    if str(cr) <= b.strftime('%Y-%m-%d %H:%M:%S'):
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
            alert_rows = await (await conn.execute(f'''
                SELECT
                    strftime('%Y-%m-%d %H:00', a.created_at) AS bucket,
                    COUNT(*) AS n
                FROM alerts a
                WHERE a.created_at >= ?
                  AND a.alert_type != 'uid'
                  AND {al_sql}
                GROUP BY bucket
            ''', [since] + al_params)).fetchall()
            alert_map = {r['bucket']: r['n'] for r in alert_rows}
            alerts_series = [alert_map.get(b.strftime('%Y-%m-%d %H:00'), 0) for b in buckets]
        return None, {
            'hours': hours,
            'buckets': [b.strftime('%Y-%m-%d %H:00') for b in buckets],
            'total': total_series,
            'online': online_series,
            'offline': offline_series,
            'alerts': alerts_series,
        }

    err, data = await _do()
    if err is not None:
        return err
    return JSONResponse({'success': True, **data})


@router.get('/devices')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_devices(request: Request):
    from app.database import get_db_context
    user = get_current_user(request)
    page = int(request.query_params.get('page', '1') or 1)
    per_page = min(int(request.query_params.get('per_page', '100') or 100), 500)
    offset = (page - 1) * per_page

    async def _do():
        async with get_db_context() as conn:
            scope = await _rs(conn, request, user['user_id'])
            if scope['error']:
                return _se(scope)
            scope_sql, scope_params = dashboard_in_sql(scope, 'dv.dashboard_id')
            total = (await (await conn.execute(
                f'SELECT COUNT(*) FROM devices dv WHERE {scope_sql}', scope_params
            )).fetchone())[0]
            rows = await (await conn.execute(f'''
                SELECT dv.*, db.name AS dashboard_name,
                       COALESCE(NULLIF(u.display_name, ''), u.username) AS owner_name
                FROM devices dv
                LEFT JOIN dashboards db ON db.id = dv.dashboard_id
                LEFT JOIN users u ON u.id = db.user_id
                WHERE {scope_sql}
                ORDER BY dv.created_at DESC LIMIT ? OFFSET ?
            ''', scope_params + [per_page, offset])).fetchall()
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
        return None, {'devices': devices, 'pagination': {
            'page': page, 'per_page': per_page, 'total': total,
            'total_pages': (total + per_page - 1) // per_page,
        }}

    err, data = await _do()
    if err is not None:
        return err
    return JSONResponse({'success': True, **data})


@router.post('/devices')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def add_device(request: Request):
    from app.database import get_db_context, get_wib_time
    from app.schemas import DeviceCreate
    from app.utils import generate_api_key, hash_api_key, validate_alert_rules
    user = get_current_user(request)
    payload = await safe_json(request)
    if not payload:
        return JSONResponse({'success': False, 'error': 'Invalid JSON'}, status_code=400)
    requested_dashboard = payload.pop('dashboard_id', None) if isinstance(payload, dict) else None
    try:
        data = DeviceCreate.model_validate(payload).model_dump()
    except ValidationError as err:
        return JSONResponse({'success': False, 'error': str(err)}, status_code=400)
    alert_rules = data.get('alert_rules')
    if alert_rules:
        is_valid, err_msg = validate_alert_rules(alert_rules)
        if not is_valid:
            return JSONResponse({'success': False, 'error': err_msg}, status_code=400)
    api_key = generate_api_key()
    api_key_hash = hash_api_key(api_key)
    explicit_interval = payload.get('expected_interval') is not None
    expected_interval = data.get('expected_interval') if explicit_interval else None
    interval_manual = 1 if explicit_interval else 0
    firmware_version = (data.get('firmware_version') or '').strip()
    offline_timeout = data.get('offline_timeout')
    device_type = (data.get('device_type') or '').strip()
    if offline_timeout is None and 'rfid' in device_type.lower():
        offline_timeout = 86400
    if (offline_timeout is not None and expected_interval is not None
            and offline_timeout < expected_interval):
        return JSONResponse({'success': False, 'error': (
            f'Offline Timeout minimal {expected_interval} detik '
            f'(= interval kirim device). Kosongkan untuk mode otomatis.')}, status_code=400)
    alert_rules_json = json.dumps(alert_rules) if alert_rules else None
    offline_severity = data.get('offline_alert_severity', 'danger')

    async def _do():
        async with get_db_context() as conn:
            scope = await _rs(conn, request, user['user_id'], 'editor')
            if scope['error']:
                return _se(scope), None, None
            dashboard_id, denied = await _pw(conn, scope, requested_id=requested_dashboard,
                                       minimum='editor')
            if denied:
                return denied, None, None
            existing = await (await conn.execute(
                'SELECT device_id FROM devices WHERE device_id = ?',
                (data['device_id'],))).fetchone()
            if existing:
                return JSONResponse({'success': False, 'error': 'Device ID already exists'},
                                    status_code=400), None, None
            await conn.execute('''
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
            await conn.commit()
        return None, dashboard_id, None

    err, dashboard_id, _ = await _do()
    if err is not None:
        return err
    logger.info(f"Device added: {data['device_id']}")
    return JSONResponse({'success': True, 'device': {
        'device_id': data['device_id'],
        'device_name': data['device_name'],
        'api_key': api_key,
        'offline_timeout': offline_timeout,
        'expected_interval': expected_interval,
        'firmware_version': firmware_version,
        'offline_alert_severity': offline_severity,
        'dashboard_id': dashboard_id,
        'warning': 'Simpan API key ini! Tidak akan ditampilkan lagi.'
    }}, status_code=201)


@router.get('/devices/{device_id}')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_device_detail(device_id: str, request: Request):
    from app.database import get_db_context
    from app.utils import safe_json_loads
    user = get_current_user(request)

    async def _do():
        async with get_db_context() as conn:
            device, denied = await _dl(conn, request, user['user_id'], device_id, 'viewer')
            if denied:
                return denied, None
            latest = await (await conn.execute('''
                SELECT * FROM sensor_data WHERE device_id = ?
                ORDER BY timestamp DESC LIMIT 1
            ''', (device_id,))).fetchone()
            active_alerts = await (await conn.execute('''
                SELECT * FROM alerts
                WHERE device_id = ? AND is_active = 1 AND alert_type != 'uid'
                ORDER BY
                    CASE severity
                        WHEN 'danger' THEN 1 WHEN 'warning' THEN 2
                        WHEN 'info' THEN 3 ELSE 4
                    END,
                    created_at DESC
            ''', (device_id,))).fetchall()
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
        return None, device_info

    err, data = await _do()
    if err is not None:
        return err
    return JSONResponse({'success': True, 'device': data})


@router.get('/devices/{device_id}/history')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_device_history(device_id: str, request: Request):
    from datetime import timedelta
    from app.database import get_db_context, get_wib_time
    from app.utils import safe_json_loads
    user = get_current_user(request)
    hours = min(int(request.query_params.get('hours', '3') or 3), 720)
    limit_q = min(int(request.query_params.get('limit', '500') or 500), 5000)
    since = get_wib_time() - timedelta(hours=hours)

    async def _do():
        async with get_db_context() as conn:
            _, denied = await _dl(conn, request, user['user_id'], device_id, 'viewer', 'device_id')
            if denied:
                return denied, None
            rows = await (await conn.execute('''
                SELECT * FROM sensor_data
                WHERE device_id = ? AND timestamp >= ?
                ORDER BY timestamp DESC LIMIT ?
            ''', (device_id, since, limit_q))).fetchall()
        rows = list(reversed(rows))
        history = [{
            'sensor_type': item['sensor_type'],
            'data': safe_json_loads(item['data']),
            'wifi_ssid': item['wifi_ssid'] or '',
            'uptime_seconds': item['uptime_seconds'] or 0,
            'timestamp': _clean_timestamp(item['timestamp']),
        } for item in rows]
        return None, history

    err, history = await _do()
    if err is not None:
        return err
    return JSONResponse({'success': True, 'history': history, 'data_count': len(history)})


@router.put('/devices/{device_id}')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def update_device(device_id: str, request: Request):
    from app.database import get_db_context
    from app.schemas import DeviceUpdate
    from app.utils import validate_alert_rules
    user = get_current_user(request)
    payload = await safe_json(request)
    if not payload:
        return JSONResponse({'success': False, 'error': 'Invalid JSON'}, status_code=400)
    try:
        data = DeviceUpdate.model_validate(payload).model_dump(exclude_unset=True,
                                                               exclude_none=False)
    except ValidationError as err:
        return JSONResponse({'success': False, 'error': str(err)}, status_code=400)
    alert_rules = data.get('alert_rules')
    if alert_rules is not None:
        is_valid, err_msg = validate_alert_rules(alert_rules)
        if not is_valid:
            return JSONResponse({'success': False, 'error': err_msg}, status_code=400)

    async def _do():
        async with get_db_context() as conn:
            device, denied = await _dl(conn, request, user['user_id'], device_id, 'editor')
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
                        return JSONResponse({'success': False, 'error':
                            'Offline Timeout harus berupa angka atau dikosongkan'}, status_code=400)
                    if new_timeout < 10:
                        return JSONResponse({'success': False, 'error':
                            'Offline Timeout minimal 10 detik. Kosongkan untuk mode otomatis.'},
                            status_code=400)
                    if new_timeout > 604800:
                        return JSONResponse({'success': False, 'error':
                            'Offline Timeout maksimal 604800 detik (7 hari).'}, status_code=400)
                    current_interval = device['expected_interval'] or 60
                    if new_timeout < current_interval:
                        return JSONResponse({'success': False, 'error': (
                            f'Offline Timeout minimal {current_interval} detik '
                            f'(= interval kirim device). '
                            f'Kalau perlu lebih kecil dari ini, '
                            f'kosongkan field untuk pakai mode otomatis.')}, status_code=400)
                    new_offline_timeout = new_timeout
            else:
                new_offline_timeout = device['offline_timeout']
            if alert_rules is not None:
                alert_rules_json = json.dumps(alert_rules) if alert_rules else None
            else:
                alert_rules_json = device['alert_rules']
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
                'offline_alert_severity': data.get('offline_alert_severity',
                                                   device['offline_alert_severity']),
                'alert_rules': alert_rules_json,
            }
            await conn.execute('''
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
            await conn.commit()
        return None

    err = await _do()
    if err is not None:
        return err
    return JSONResponse({'success': True})


@router.delete('/devices/{device_id}')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def delete_device(device_id: str, request: Request):
    from app.database import get_db_context
    from app.deps import audit
    user = get_current_user(request)

    async def _do():
        async with get_db_context() as conn:
            _, denied = await _dl(conn, request, user['user_id'], device_id, 'editor', 'device_id')
            if denied:
                return denied
            await audit(conn, request, user['user_id'], user['username'], 'device.delete',
                  f'device_id={device_id}')
            await conn.execute('DELETE FROM sensor_data WHERE device_id = ?', (device_id,))
            await conn.execute('DELETE FROM alerts WHERE device_id = ?', (device_id,))
            await conn.execute('DELETE FROM alert_history WHERE device_id = ?', (device_id,))
            await conn.execute('DELETE FROM device_status_log WHERE device_id = ?', (device_id,))
            await conn.execute('DELETE FROM devices WHERE device_id = ?', (device_id,))
            await conn.commit()
        return None

    err = await _do()
    if err is not None:
        return err
    logger.info(f"Device deleted: {device_id}")
    return JSONResponse({'success': True})


@router.post('/devices/{device_id}/regenerate-key')
@limiter.limit(get_config().RATE_LIMIT_REGENERATE)
async def regenerate_api_key(device_id: str, request: Request):
    from app.database import get_db_context
    from app.utils import generate_api_key, hash_api_key
    user = get_current_user(request)

    async def _do():
        async with get_db_context() as conn:
            _, denied = await _dl(conn, request, user['user_id'], device_id, 'editor', 'device_id')
            if denied:
                return denied, None
            new_key = generate_api_key()
            new_hash = hash_api_key(new_key)
            await conn.execute(
                'UPDATE devices SET api_key = NULL, api_key_hash = ? WHERE device_id = ?',
                (new_hash, device_id))
            await conn.commit()
        return None, new_key

    err, new_key = await _do()
    if err is not None:
        return err
    logger.warning(f"API key regenerated for {device_id}")
    return JSONResponse({'success': True, 'api_key': new_key,
                         'warning': 'Update firmware perangkat dengan API key baru!'})


@router.get('/devices/{device_id}/alert-rules')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_device_alert_rules_endpoint(device_id: str, request: Request):
    from app.database import get_db_context
    from app.alerts import get_device_alert_rules
    user = get_current_user(request)

    async def _do():
        async with get_db_context() as conn:
            device, denied = await _dl(conn, request, user['user_id'], device_id, 'viewer',
                                 'device_id, alert_rules')
            if denied:
                return denied, None, None
            rules = await get_device_alert_rules(conn, device_id)
            is_custom = device['alert_rules'] is not None
        return None, rules, is_custom

    err, rules, is_custom = await _do()
    if err is not None:
        return err
    return JSONResponse({'success': True, 'device_id': device_id,
                         'alert_rules': rules, 'is_custom': is_custom})


@router.put('/devices/{device_id}/alert-rules')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def update_device_alert_rules_endpoint(device_id: str, request: Request):
    from app.database import get_db_context
    from app.utils import validate_alert_rules
    user = get_current_user(request)
    payload = await safe_json(request)
    if payload is None:
        return JSONResponse({'success': False, 'error': 'Invalid JSON'}, status_code=400)
    is_valid, err_msg = validate_alert_rules(payload)
    if not is_valid:
        return JSONResponse({'success': False, 'error': err_msg}, status_code=400)

    async def _do():
        async with get_db_context() as conn:
            _, denied = await _dl(conn, request, user['user_id'], device_id, 'editor', 'device_id')
            if denied:
                return denied
            await conn.execute('UPDATE devices SET alert_rules = ? WHERE device_id = ?',
                         (json.dumps(payload), device_id))
            await conn.commit()
        return None

    err = await _do()
    if err is not None:
        return err
    return JSONResponse({'success': True, 'alert_rules': payload})


@router.delete('/devices/{device_id}/alert-rules')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def reset_device_alert_rules(device_id: str, request: Request):
    from app.database import get_db_context
    user = get_current_user(request)

    async def _do():
        async with get_db_context() as conn:
            _, denied = await _dl(conn, request, user['user_id'], device_id, 'editor', 'device_id')
            if denied:
                return denied
            await conn.execute('UPDATE devices SET alert_rules = NULL WHERE device_id = ?',
                         (device_id,))
            await conn.commit()
        return None

    err = await _do()
    if err is not None:
        return err
    return JSONResponse({'success': True})


@router.get('/devices/{device_id}/status-history')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_device_status_history(device_id: str, request: Request):
    from app.database import get_db_context
    user = get_current_user(request)
    limit_q = min(int(request.query_params.get('limit', '100') or 100), 500)

    async def _do():
        async with get_db_context() as conn:
            _, denied = await _dl(conn, request, user['user_id'], device_id, 'viewer', 'device_id')
            if denied:
                return denied, None
            rows = await (await conn.execute('''
                SELECT status, reason, created_at FROM device_status_log
                WHERE device_id = ? ORDER BY created_at DESC LIMIT ?
            ''', (device_id, limit_q))).fetchall()
        history = []
        for r in rows:
            d = dict(r)
            d['created_at'] = _clean_timestamp(d.get('created_at'))
            history.append(d)
        return None, history

    err, history = await _do()
    if err is not None:
        return err
    return JSONResponse({'success': True, 'history': history, 'count': len(history)})


@router.get('/devices/{device_id}/export')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def export_device_data(device_id: str, request: Request):
    from datetime import timedelta
    from app.database import get_db_context, get_wib_time
    from app.utils import csv_safe, safe_json_loads
    user = get_current_user(request)
    format_type = (request.query_params.get('format') or 'csv').lower()
    hours = min(int(request.query_params.get('hours', '24') or 24), 8760)
    limit_q = min(int(request.query_params.get('limit', '10000') or 10000), 50000)
    since = get_wib_time() - timedelta(hours=hours)

    async def _do():
        async with get_db_context() as conn:
            device, denied = await _dl(conn, request, user['user_id'], device_id, 'viewer',
                                 'device_name')
            if denied:
                return denied, None, None
            rows = await (await conn.execute('''
                SELECT sensor_type, data, wifi_ssid, uptime_seconds, timestamp
                FROM sensor_data
                WHERE device_id = ? AND timestamp >= ?
                ORDER BY timestamp ASC LIMIT ?
            ''', (device_id, since, limit_q))).fetchall()
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
        return None, device, (records, sorted(all_keys))

    err, device, pack = await _do()
    if err is not None:
        return err
    records, sorted_keys = pack
    if format_type == 'csv':
        output = io.StringIO()
        headers = ['timestamp', 'sensor_type', 'wifi_ssid', 'uptime_seconds'] + sorted_keys
        writer = csv.DictWriter(output, fieldnames=headers, extrasaction='ignore')
        writer.writeheader()
        for r in records:
            writer.writerow({k: csv_safe(v) for k, v in r.items()})
        filename = f"{device_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(output.getvalue(), media_type='text/csv',
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
        media_type='application/json',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@router.post('/devices/bulk-import')
@limiter.limit('10 per minute')
async def bulk_import_devices(request: Request):
    from app.database import get_db_context, get_wib_time
    from app.schemas import BulkImportItem
    from app.utils import generate_api_key, hash_api_key
    from app.deps import require_admin
    await require_admin(request)
    user = get_current_user(request)
    payload = await safe_json(request)
    if not payload or not isinstance(payload.get('devices'), list):
        return JSONResponse({'success': False,
                             'error': 'Kirim {"devices": [...]} dengan array'}, status_code=400)
    items = payload['devices']
    if len(items) == 0:
        return JSONResponse({'success': False, 'error': 'Array kosong'}, status_code=400)
    if len(items) > 200:
        return JSONResponse({'success': False, 'error':
                             f'Maksimal 200 device per import. Dikirim: {len(items)}'},
                            status_code=400)

    async def _do():
        created, skipped, errors = [], [], []
        async with get_db_context() as conn:
            scope = await _rs(conn, request, user['user_id'], 'editor')
            if scope['error']:
                return _se(scope), None, None, None
            dashboard_id, denied = await _pw(conn, scope, requested_id=payload.get('dashboard_id'),
                                       minimum='editor')
            if denied:
                return denied, None, None, None
            for idx, raw in enumerate(items):
                if not isinstance(raw, dict):
                    errors.append({'row': idx + 1, 'error': 'Bukan object'})
                    continue
                try:
                    data = BulkImportItem.model_validate(raw).model_dump()
                except ValidationError as err:
                    errors.append({'row': idx + 1,
                                   'device_id': raw.get('device_id', '?'),
                                   'error': str(err)})
                    continue
                device_id = data['device_id']
                existing = await (await conn.execute(
                    'SELECT device_id FROM devices WHERE device_id = ?', (device_id,)
                )).fetchone()
                if existing:
                    skipped.append({'row': idx + 1, 'device_id': device_id,
                                    'reason': 'Sudah ada'})
                    continue
                try:
                    api_key = generate_api_key()
                    api_key_hash = hash_api_key(api_key)
                    offline_timeout = data.get('offline_timeout')
                    device_type = (data.get('device_type') or '').strip()
                    if offline_timeout is None and 'rfid' in device_type.lower():
                        offline_timeout = 86400
                    await conn.execute('''
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
                    created.append({'row': idx + 1, 'device_id': device_id,
                                    'device_name': data['device_name'], 'api_key': api_key})
                except Exception as e:
                    errors.append({'row': idx + 1, 'device_id': device_id, 'error': str(e)})
            await conn.commit()
        return None, created, skipped, errors

    err, created, skipped, errors = await _do()
    if err is not None:
        return err
    logger.info(f"Bulk import by user {user['user_id']}: "
                f"{len(created)} created, {len(skipped)} skipped, {len(errors)} errors")
    return JSONResponse({
        'success': True,
        'created': created,
        'skipped': skipped,
        'errors': errors,
        'summary': {'total': len(items), 'created': len(created),
                    'skipped': len(skipped), 'errors': len(errors)},
        'warning': 'Simpan semua API key! Tidak akan ditampilkan lagi.',
    })
