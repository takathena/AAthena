"""NEXUS IoT - Device-facing endpoint (dari app/api.py receive_data)."""
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.config import get_config
from app.deps import limiter
from app.schemas import SensorData

logger = logging.getLogger('nexus')
router = APIRouter(prefix='/api/v1', tags=['ingest'])


async def _detect_interval_async(conn, device_id):
    from app.utils import parse_datetime
    from app.api_common import (AUTO_INTERVAL_MIN_SAMPLES, AUTO_INTERVAL_MIN_DELTAS,
                                AUTO_INTERVAL_IGNORE_BELOW, AUTO_INTERVAL_FLOOR)
    rows = await (await conn.execute(
        'SELECT timestamp FROM sensor_data WHERE device_id = ? '
        'ORDER BY timestamp DESC LIMIT 10', (device_id,)
    )).fetchall()
    if len(rows) < AUTO_INTERVAL_MIN_SAMPLES:
        return None
    stamps = [t for t in (parse_datetime(r['timestamp']) for r in rows) if t]
    deltas = []
    for i in range(len(stamps) - 1):
        d = (stamps[i] - stamps[i + 1]).total_seconds()
        if AUTO_INTERVAL_IGNORE_BELOW <= d < 86400:
            deltas.append(d)
    if len(deltas) < AUTO_INTERVAL_MIN_DELTAS:
        return None
    deltas.sort()
    return max(AUTO_INTERVAL_FLOOR, min(86400, int(round(deltas[len(deltas) // 2]))))


@router.post('/data')
@limiter.limit(get_config().RATE_LIMIT_DATA)
async def receive_data(request: Request):
    from app.database import get_db_context, get_wib_time
    from app.alerts import check_and_create_alerts, clear_offline_alert
    from app.utils import verify_api_key

    max_bytes = int(get_config().DATA_MAX_BYTES)
    too_large = JSONResponse({
        'success': False,
        'error': f'Payload terlalu besar. Maksimal {max_bytes} byte.',
        'max_bytes': max_bytes,
    }, status_code=413)

    raw_body = await request.body()
    if request.headers.get('content-length'):
        try:
            if int(request.headers['content-length']) > max_bytes:
                return too_large
        except ValueError:
            pass
    if len(raw_body) > max_bytes:
        return too_large

    try:
        try:
            payload = json.loads(raw_body) if raw_body else None
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = None
        if not payload:
            return JSONResponse({'success': False, 'error': 'Invalid JSON'}, status_code=400)
        try:
            parsed = SensorData.model_validate(payload)
            data = parsed.model_dump()
        except ValidationError as err:
            return JSONResponse({'success': False, 'error': str(err)}, status_code=400)

        async def _valid():
            async with get_db_context() as conn:
                device = await (await conn.execute(
                    'SELECT device_id, api_key, api_key_hash FROM devices WHERE device_id = ?',
                    (data['device_id'],)
                )).fetchone()
            if not device:
                return False
            if device['api_key_hash']:
                return verify_api_key(data['api_key'], device['api_key_hash'])
            if device['api_key']:
                import hmac
                return hmac.compare_digest(device['api_key'], data['api_key'])
            return False

        valid = await _valid()
        if not valid:
            logger.warning(f"Invalid API key attempt: device={data['device_id']}")
            return JSONResponse(
                {'success': False, 'error': 'Invalid device_id or api_key'}, status_code=401)

        async def _insert():
            async with get_db_context() as conn:
                await conn.execute('''
                    INSERT INTO sensor_data
                    (device_id, sensor_type, data, wifi_ssid, uptime_seconds, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    data['device_id'], data['sensor_type'],
                    json.dumps(data['data']), data.get('wifi_ssid', ''),
                    data.get('uptime_seconds', 0), get_wib_time()
                ))
                try:
                    dev = await (await conn.execute(
                        'SELECT expected_interval, interval_manual FROM devices WHERE device_id = ?',
                        (data['device_id'],)
                    )).fetchone()
                    if dev and not dev['interval_manual']:
                        auto_int = await _detect_interval_async(conn, data['device_id'])
                        cur_int = dev['expected_interval']
                        if auto_int is not None and (
                            not cur_int or abs(auto_int - cur_int) > 0.2 * cur_int
                        ):
                            await conn.execute(
                                'UPDATE devices SET expected_interval = ? WHERE device_id = ?',
                                (auto_int, data['device_id'])
                            )
                            logger.info(f"Auto-detected interval for {data['device_id']}: {auto_int}s")
                except Exception as e:
                    logger.debug(f"Auto-detect interval failed for {data['device_id']}: {e}")
                await conn.commit()

        await _insert()
        remote = request.client.host if request.client else None
        async with get_db_context() as conn:
            prev = await (await conn.execute(
                'SELECT status FROM devices WHERE device_id = ?', (data['device_id'],)
            )).fetchone()
            prev_status = prev['status'] if prev else None
            if remote:
                await conn.execute(
                    'UPDATE devices SET status = ?, last_seen = ?, last_ip = ? WHERE device_id = ?',
                    ('online', get_wib_time(), remote, data['device_id'])
                )
            else:
                await conn.execute(
                    'UPDATE devices SET status = ?, last_seen = ? WHERE device_id = ?',
                    ('online', get_wib_time(), data['device_id'])
                )
            if prev_status is not None and prev_status != 'online':
                await conn.execute(
                    'INSERT INTO device_status_log (device_id, status, reason, created_at) '
                    'VALUES (?, ?, ?, ?)',
                    (data['device_id'], 'online', 'data_received', get_wib_time())
                )
            await conn.commit()
        try:
            await clear_offline_alert(data['device_id'])
        except Exception as e:
            logger.error(f"Failed to clear offline alert: {e}", exc_info=True)

        if data['sensor_type'] != 'heartbeat':
            try:
                await check_and_create_alerts(data['device_id'], data['data'])
            except Exception as e:
                logger.error(f"Alert check failed: {e}", exc_info=True)

        from app.api_common import _clean_timestamp
        return JSONResponse({
            'success': True,
            'message': 'Data received',
            'timestamp': _clean_timestamp(get_wib_time().isoformat())
        })
    except Exception as e:
        logger.error(f"Error in receive_data: {e}", exc_info=True)
        return JSONResponse({'success': False, 'error': 'Internal server error'}, status_code=500)
