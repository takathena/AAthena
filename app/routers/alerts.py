"""NEXUS IoT - FastAPI alert endpoints (dari app/api.py)."""
import logging
from datetime import timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api_common import _alert_label, _clean_timestamp
from app.config import get_config
from app.deps import (get_current_user, resolve_scope as _rs,
                      scope_error_response as _se, device_in_sql)
from app.deps import limiter, safe_json

logger = logging.getLogger('nexus')
router = APIRouter(prefix='/api/v1', tags=['alerts'])


@router.get('/alerts/trend')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_alert_trend(request: Request):
    from app.database import get_db_context, get_wib_time
    user = get_current_user(request)
    hours = min(int(request.query_params.get('hours', '24') or 24), 168)
    since = get_wib_time() - timedelta(hours=hours)

    async def _do():
        async with get_db_context() as conn:
            scope = await _rs(conn, request, user['user_id'])
            if scope['error']:
                return _se(scope), None
            scope_sql, scope_params = device_in_sql(scope, 'device_id')
            rows = await (await conn.execute(f'''
                SELECT strftime('%Y-%m-%d %H:00', created_at) AS hour_bucket,
                       severity, COUNT(*) AS count
                FROM alert_history
                WHERE created_at >= ? AND action = 'created' AND {scope_sql}
                GROUP BY hour_bucket, severity
                ORDER BY hour_bucket ASC
            ''', [since] + scope_params)).fetchall()
        return None, [dict(r) for r in rows]

    err, trend = await _do()
    if err is not None:
        return err
    return JSONResponse({'success': True, 'trend': trend, 'range_hours': hours})


@router.get('/alerts')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_alerts(request: Request):
    from app.alerts import get_active_alerts
    from app.database import get_db_context
    user = get_current_user(request)
    severity = request.query_params.get('severity')
    device_id = request.query_params.get('device_id')
    limit = min(int(request.query_params.get('limit', '100') or 100), 500)

    async def _do():
        async with get_db_context() as conn:
            scope = await _rs(conn, request, user['user_id'])
        if scope['error']:
            return _se(scope), None
        alerts = await get_active_alerts(limit=limit, severity=severity,
                                   device_id=device_id, scope=scope)
        return None, alerts

    err, alerts = await _do()
    if err is not None:
        return err
    for a in alerts:
        a['created_at'] = _clean_timestamp(a.get('created_at'))
        a['updated_at'] = _clean_timestamp(a.get('updated_at'))
    return JSONResponse({'success': True, 'alerts': alerts, 'count': len(alerts)})


@router.get('/alerts/history')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_alerts_history(request: Request):
    from app.alerts import get_alert_history
    from app.database import get_db_context
    user = get_current_user(request)
    device_id = request.query_params.get('device_id')
    limit = min(int(request.query_params.get('limit', '200') or 200), 1000)

    async def _do():
        async with get_db_context() as conn:
            scope = await _rs(conn, request, user['user_id'])
        if scope['error']:
            return _se(scope), None
        return None, await get_alert_history(device_id, limit, scope=scope)

    err, history = await _do()
    if err is not None:
        return err
    for h in history:
        h['created_at'] = _clean_timestamp(h.get('created_at'))
    return JSONResponse({'success': True, 'history': history})


@router.get('/alerts/stats')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_alert_stats(request: Request):
    from app.database import get_db_context
    user = get_current_user(request)

    async def _do():
        async with get_db_context() as conn:
            scope = await _rs(conn, request, user['user_id'])
            if scope['error']:
                return _se(scope), None
            sc_sql, sc_params = device_in_sql(scope, 'device_id')
            sa_sql, sa_params = device_in_sql(scope, 'a.device_id')
            summary = {'danger': 0, 'warning': 0, 'info': 0, 'total': 0}
            rows = await (await conn.execute(f'''
                SELECT severity, COUNT(*) as count
                FROM alerts WHERE is_active = 1 AND alert_type != 'uid' AND {sc_sql}
                GROUP BY severity
            ''', sc_params)).fetchall()
            for r in rows:
                if r['severity'] in summary:
                    summary[r['severity']] = r['count']
                summary['total'] += r['count']
            top_devices = await (await conn.execute(f'''
                SELECT a.device_id, d.device_name, COUNT(*) as alert_count,
                       SUM(CASE WHEN a.severity = 'danger' THEN 1 ELSE 0 END) as danger_count,
                       SUM(CASE WHEN a.severity = 'warning' THEN 1 ELSE 0 END) as warning_count
                FROM alerts a
                JOIN devices d ON a.device_id = d.device_id
                WHERE a.is_active = 1 AND a.alert_type != 'uid' AND {sa_sql}
                GROUP BY a.device_id
                ORDER BY alert_count DESC LIMIT 5
            ''', sa_params)).fetchall()
            total_history = (await (await conn.execute(
                f'SELECT COUNT(*) FROM alert_history WHERE {sc_sql}', sc_params
            )).fetchone())[0]
            active_count = (await (await conn.execute(
                f"SELECT COUNT(*) FROM alerts WHERE is_active = 1 AND alert_type != 'uid' AND {sc_sql}",
                sc_params
            )).fetchone())[0]
        return None, {'summary': summary, 'top_devices': [dict(r) for r in top_devices],
                      'total_history': total_history, 'active_count': active_count}

    err, data = await _do()
    if err is not None:
        return err
    return JSONResponse({'success': True, **data})


@router.get('/alerts/all')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_all_alerts(request: Request):
    from app.database import get_db_context
    user = get_current_user(request)
    status = request.query_params.get('status', 'all')
    severity = request.query_params.get('severity')
    device_id = request.query_params.get('device_id')
    limit = min(int(request.query_params.get('limit', '200') or 200), 1000)

    async def _do():
        async with get_db_context() as conn:
            scope = await _rs(conn, request, user['user_id'])
            if scope['error']:
                return _se(scope), None
            sh_sql, sh_params = device_in_sql(scope, 'h.device_id')
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
            rows = await (await conn.execute(base_query, params)).fetchall()
        alerts = []
        for r in rows:
            d = dict(r)
            d.pop('rn', None)
            d['created_at'] = _clean_timestamp(d.get('created_at'))
            d['label'] = _alert_label(d['alert_type'], d['severity'])
            alerts.append(d)
        return None, alerts

    err, alerts = await _do()
    if err is not None:
        return err
    return JSONResponse({'success': True, 'alerts': alerts, 'count': len(alerts)})


@router.post('/alerts/{alert_id:int}/acknowledge')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def acknowledge_alert_endpoint(alert_id: int, request: Request):
    from app.alerts import acknowledge_alert
    from app.database import get_db_context
    user = get_current_user(request)

    async def _do():
        async with get_db_context() as conn:
            scope = await _rs(conn, request, user['user_id'], 'editor')
        if scope['error']:
            return _se(scope), None
        return None, await acknowledge_alert(alert_id, scope=scope)

    err, success = await _do()
    if err is not None:
        return err
    if not success:
        return JSONResponse(
            {'success': False, 'error': 'Alert not found or already acknowledged'},
            status_code=404)
    return JSONResponse({'success': True})


@router.post('/alerts/bulk-acknowledge')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def bulk_acknowledge(request: Request):
    from app.alerts import bulk_acknowledge_alerts
    from app.database import get_db_context
    user = get_current_user(request)
    payload = await safe_json(request)
    if not payload or not isinstance(payload.get('ids'), list):
        return JSONResponse({'success': False, 'error': 'Kirim {"ids": [1, 2, 3]}'},
                            status_code=400)
    ids = []
    for i in payload['ids']:
        try:
            ids.append(int(i))
        except (ValueError, TypeError):
            continue
    if not ids:
        return JSONResponse({'success': False, 'error': 'Tidak ada ID valid'}, status_code=400)

    async def _do():
        async with get_db_context() as conn:
            scope = await _rs(conn, request, user['user_id'], 'editor')
        if scope['error']:
            return _se(scope), None
        return None, await bulk_acknowledge_alerts(ids, scope=scope)

    err, count = await _do()
    if err is not None:
        return err
    return JSONResponse({'success': True, 'acknowledged': count})
