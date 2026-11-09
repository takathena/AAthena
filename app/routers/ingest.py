"""NEXUS IoT - Device-facing endpoint (dari app/api.py receive_data)."""
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.config import get_config
from app.deps import limiter, run_sync
from app.schemas import SensorData

logger = logging.getLogger('nexus')
router = APIRouter(prefix='/api/v1', tags=['ingest'])


@router.post('/data')
@limiter.limit(get_config().RATE_LIMIT_DATA)
async def receive_data(request: Request):
    from app.api_common import validate_device_api_key, update_device_status
    from app.database import get_db_context, get_wib_time
    from app.alerts import check_and_create_alerts

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

        valid = await run_sync(validate_device_api_key,
                               data['device_id'], data['api_key'])
        if not valid:
            logger.warning(f"Invalid API key attempt: device={data['device_id']}")
            return JSONResponse(
                {'success': False, 'error': 'Invalid device_id or api_key'}, status_code=401)

        def _insert():
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
                from app.api_common import _detect_interval
                try:
                    dev = conn.execute(
                        'SELECT expected_interval, interval_manual FROM devices WHERE device_id = ?',
                        (data['device_id'],)
                    ).fetchone()
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

        await run_sync(_insert)
        remote = request.client.host if request.client else None
        await run_sync(update_device_status, data['device_id'], 'online', remote)

        if data['sensor_type'] != 'heartbeat':
            try:
                # check_and_create_alerts kini native async
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
