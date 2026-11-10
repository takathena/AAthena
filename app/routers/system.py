"""AAguard IoT - FastAPI system endpoints (dari app/api.py)."""
import json
import logging
import os
import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from app.api_common import (_clean_timestamp, _parse_purge_request,
                            _purge_where, PURGE_BATCH, PURGE_TABLES)
from app.config import get_config
from app.deps import (audit, get_current_user, limiter, require_admin,
                      resolve_scope as _rs, safe_json,
                      scope_error_response as _se, device_in_sql,
                      dashboard_in_sql as _dash_in_sql)

logger = logging.getLogger('aaguard')
router = APIRouter(prefix='/api/v1', tags=['system'])


@router.get('/system/info')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_system_info(request: Request):
    from app.database import get_db_context
    from app.background import get_background_status
    user = get_current_user(request)

    async def _do():
        async with get_db_context() as conn:
            scope = await _rs(conn, request, user['user_id'])
            if scope['error']:
                return _se(scope), None
            sd_sql, sd_params = _dash_in_sql(scope, 'dashboard_id')
            sv_sql, sv_params = device_in_sql(scope, 'device_id')
            device_count = (await (await conn.execute(
                f'SELECT COUNT(*) FROM devices WHERE {sd_sql}', sd_params)).fetchone())[0]
            sensor_count = (await (await conn.execute(
                f'SELECT COUNT(*) FROM sensor_data WHERE {sv_sql}', sv_params)).fetchone())[0]
            alert_count = (await (await conn.execute(
                f"SELECT COUNT(*) FROM alerts WHERE is_active = 1 "
                f"AND alert_type != 'uid' AND {sv_sql}", sv_params)).fetchone())[0]
            history_count = (await (await conn.execute(
                f'SELECT COUNT(*) FROM alert_history WHERE {sv_sql}', sv_params)).fetchone())[0]
        return None, (device_count, sensor_count, alert_count, history_count)

    err, counts = await _do()
    if err is not None:
        return err
    device_count, sensor_count, alert_count, history_count = counts
    config = get_config()
    db_size = 0
    db_path = config.DB_PATH
    if os.path.exists(db_path):
        db_size = os.path.getsize(db_path)
    wal_path = db_path + '-wal'
    if os.path.exists(wal_path):
        db_size += os.path.getsize(wal_path)
    # get_background_status bisa sync atau async (dual) — await bila coroutine
    import inspect as _insp
    _bg = get_background_status(config)
    if _insp.iscoroutine(_bg):
        _bg = await _bg
    return JSONResponse({'success': True, 'info': {
        'version': '2.0.0',
        'device_count': device_count,
        'sensor_data_count': sensor_count,
        'active_alerts': alert_count,
        'alert_history_count': history_count,
        'database_size_bytes': db_size,
        'database_size_mb': round(db_size / (1024 * 1024), 2),
        'data_retention_days': config.DATA_RETENTION_DAYS,
        'background': _bg,
    }})


@router.post('/notifications/test')
@limiter.limit('10 per minute')
async def test_notification(request: Request):
    await require_admin(request)
    try:
        from app.notifier import send_test_notification
        results = await send_test_notification()
        channels = {k: r for k, r in results.items() if not k.startswith('_')}
        all_success = bool(channels) and all(r.get('success', False)
                                             for r in channels.values())
        status = 200 if all_success else 503
        return JSONResponse({'success': all_success, 'results': results},
                            status_code=status)
    except Exception as e:
        logger.error(f"Test notification failed: {e}", exc_info=True)
        return JSONResponse(
            {'success': False,
             'error': 'Terjadi kesalahan internal. Detail ada di log server.'},
            status_code=500)


@router.post('/notifications/test-channel')
@limiter.limit('10 per minute')
async def test_notification_channel(request: Request):
    await require_admin(request)
    payload = await safe_json(request) or {}
    channel = (payload.get('channel') or '').strip().lower()
    if channel not in ('telegram',):
        return JSONResponse(
            {'success': False, 'error': f'Channel "{channel}" tidak dikenal'}, status_code=400)
    try:
        from app.notifier import send_test_notification
        results = await send_test_notification()
        ch_result = results.get(channel)
        if not ch_result:
            return JSONResponse({'success': False,
                                 'error': f'Channel {channel} tidak terkonfigurasi',
                                 'all_results': results}, status_code=400)
        return JSONResponse({'success': ch_result.get('success', False),
                             'channel': channel, 'result': ch_result},
                            status_code=200 if ch_result.get('success') else 500)
    except Exception as e:
        logger.error(f"Test channel failed: {e}", exc_info=True)
        return JSONResponse(
            {'success': False,
             'error': 'Terjadi kesalahan internal. Detail ada di log server.'},
            status_code=500)


@router.get('/notifications/config')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def notification_config(request: Request):
    get_current_user(request)
    from app.notifier import get_notification_status
    return JSONResponse({'success': True, 'config': get_notification_status()})


@router.post('/system/backup')
@limiter.limit('5 per minute')
async def trigger_backup(request: Request):
    await require_admin(request)
    config = get_config()
    try:
        from app.background import create_backup_file
        backup_path = await create_backup_file(config.BACKUP_DIR, config.DB_PATH)
        size_mb = os.path.getsize(backup_path) / (1024 * 1024)
        filename = os.path.basename(backup_path)
        logger.info(f"Manual backup created: {backup_path} ({size_mb:.2f} MB)")
        return JSONResponse({'success': True, 'filename': filename,
                             'size_mb': round(size_mb, 2),
                             'message': f'Backup berhasil dibuat ({size_mb:.2f} MB)'})
    except Exception as e:
        logger.error(f"Manual backup failed: {e}", exc_info=True)
        return JSONResponse(
            {'success': False,
             'error': 'Terjadi kesalahan internal. Detail ada di log server.'},
            status_code=500)


@router.get('/system/backups')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def list_backups(request: Request):
    await require_admin(request)
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
                'created_at': __import__('datetime').datetime.fromtimestamp(
                    stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                '_mtime': stat.st_mtime,
            })
        backups.sort(key=lambda x: x['_mtime'], reverse=True)
    except Exception as e:
        logger.error(f"List backups failed: {e}", exc_info=True)
        return JSONResponse(
            {'success': False,
             'error': 'Terjadi kesalahan internal. Detail ada di log server.'},
            status_code=500)
    for b in backups:
        b.pop('_mtime', None)
    return JSONResponse({'success': True, 'backups': backups, 'count': len(backups),
                         'retention_days': config.BACKUP_RETENTION_DAYS,
                         'backup_interval_hours': config.BACKUP_INTERVAL_HOURS,
                         'auto_backup_enabled': config.BACKUP_ENABLED})


@router.get('/system/backups/{filename:path}')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def download_backup(filename: str, request: Request):
    await require_admin(request)
    from werkzeug.utils import secure_filename
    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename or not safe_name.endswith('.db'):
        return JSONResponse({'success': False, 'error': 'Nama file tidak valid'}, status_code=400)
    config = get_config()
    filepath = os.path.join(config.BACKUP_DIR, safe_name)
    real_dir = os.path.realpath(config.BACKUP_DIR)
    real_path = os.path.realpath(filepath)
    if not real_path.startswith(real_dir + os.sep):
        logger.warning(f"Path traversal attempt: {filename}")
        return JSONResponse({'success': False, 'error': 'Akses ditolak'}, status_code=403)
    if not os.path.isfile(real_path):
        return JSONResponse({'success': False, 'error': 'File tidak ditemukan'}, status_code=404)
    logger.info(f"Backup downloaded: {safe_name}")
    return FileResponse(real_path, filename=safe_name, media_type='application/octet-stream')


@router.delete('/system/backups/{filename:path}')
@limiter.limit('20 per hour')
async def delete_backup(filename: str, request: Request):
    await require_admin(request)
    from werkzeug.utils import secure_filename
    from app.database import get_db_context
    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename or not safe_name.endswith('.db'):
        return JSONResponse({'success': False, 'error': 'Nama file tidak valid'}, status_code=400)
    config = get_config()
    real_dir = os.path.realpath(config.BACKUP_DIR)
    real_path = os.path.realpath(os.path.join(config.BACKUP_DIR, safe_name))
    if not real_path.startswith(real_dir + os.sep):
        logger.warning(f"Path traversal attempt (delete backup): {filename}")
        return JSONResponse({'success': False, 'error': 'Akses ditolak'}, status_code=403)
    if not os.path.isfile(real_path):
        return JSONResponse({'success': False, 'error': 'File tidak ditemukan'}, status_code=404)
    candidates = [os.path.join(real_dir, n) for n in os.listdir(real_dir)
                  if n.endswith('.db') and os.path.isfile(os.path.join(real_dir, n))]
    newest = max(candidates, key=os.path.getmtime) if candidates else None
    if newest and os.path.realpath(newest) == real_path:
        return JSONResponse({'success': False, 'error':
            'Backup terbaru dilindungi dan tidak bisa dihapus. '
            'Buat backup baru dulu bila perlu.'}, status_code=409)
    size = os.path.getsize(real_path)
    os.remove(real_path)

    async def _audit():
        async with get_db_context() as conn:
            await audit(conn, request, get_current_user(request)['user_id'],
                  get_current_user(request)['username'], 'backup.delete',
                  f'file={safe_name} size={size}')
            await conn.commit()

    await _audit()
    return JSONResponse({'success': True, 'filename': safe_name, 'freed_bytes': size})


@router.post('/system/cleanup')
@limiter.limit('5 per hour')
async def trigger_cleanup(request: Request):
    await require_admin(request)
    from datetime import timedelta
    from app.database import get_db_context, get_wib_time
    user = get_current_user(request)
    config = get_config()

    async def _do():
        now = get_wib_time()
        cutoff_sensor = now - timedelta(days=config.DATA_RETENTION_DAYS)
        cutoff_history = now - timedelta(days=config.ALERT_HISTORY_RETENTION_DAYS)
        cutoff_log = now - timedelta(days=config.STATUS_LOG_RETENTION_DAYS)
        async with get_db_context() as conn:
            total_deleted = 0
            results = {}
            r = await conn.execute('DELETE FROM sensor_data WHERE timestamp < ?',
                             (cutoff_sensor,))
            results['sensor_data'] = r.rowcount
            total_deleted += r.rowcount
            r = await conn.execute('DELETE FROM alert_history WHERE created_at < ?',
                             (cutoff_history,))
            results['alert_history'] = r.rowcount
            total_deleted += r.rowcount
            r = await conn.execute('DELETE FROM device_status_log WHERE created_at < ?',
                             (cutoff_log,))
            results['device_status_log'] = r.rowcount
            total_deleted += r.rowcount
            r = await conn.execute(
                '''DELETE FROM alerts
                   WHERE is_active = 0
                   AND updated_at IS NOT NULL
                   AND updated_at < ?''', (cutoff_history,))
            results['alerts_inactive'] = r.rowcount
            total_deleted += r.rowcount
            await conn.commit()
            if total_deleted > 1000:
                try:
                    await conn.execute('VACUUM')
                    logger.info("VACUUM completed after manual cleanup")
                except Exception as ve:
                    logger.warning(f"VACUUM failed: {ve}")
        async with get_db_context() as audit_conn:
            await audit(audit_conn, request, user['user_id'], user['username'],
                  'data.cleanup_retention', f'rows={total_deleted}')
            await audit_conn.commit()
        return total_deleted, results

    try:
        total_deleted, results = await _do()
        logger.info(f"Manual cleanup by user {user['user_id']}: {total_deleted} rows deleted")
        return JSONResponse({'success': True, 'total_deleted': total_deleted,
                             'details': {k: v for k, v in results.items() if v > 0},
                             'message': f'{total_deleted} baris dihapus'})
    except Exception as e:
        logger.error(f"Manual cleanup failed: {e}", exc_info=True)
        return JSONResponse(
            {'success': False,
             'error': 'Terjadi kesalahan internal. Detail ada di log server.'},
            status_code=500)


@router.post('/system/data/preview')
@limiter.limit('60 per hour')
async def preview_data_purge(request: Request):
    await require_admin(request)
    from app.database import get_db_context
    spec, err = _parse_purge_request(await safe_json(request))
    if err:
        return JSONResponse({'success': False, 'error': err}, status_code=400)

    async def _do():
        async with get_db_context() as conn:
            result, total_rows, total_bytes = {}, 0, 0
            for key in spec['tables']:
                table, _, size_expr, _ = PURGE_TABLES[key]
                where, params = _purge_where(key, spec)
                row = await (await conn.execute(
                    f'SELECT COUNT(*) AS n, COALESCE(SUM({size_expr}), COUNT(*) * 80) AS b '
                    f'FROM {table} WHERE {where}', params
                )).fetchone()
                n, b = row['n'] or 0, int(row['b'] or 0)
                result[key] = {'rows': n, 'estimated_bytes': b}
                total_rows += n
                total_bytes += b
            return result, total_rows, total_bytes

    tables, total_rows, total_bytes = await _do()
    return JSONResponse({
        'success': True, 'tables': tables, 'total_rows': total_rows,
        'estimated_bytes': total_bytes,
        'estimated_mb': round(total_bytes / (1024 * 1024), 2),
        'note': 'Ukuran adalah perkiraan kasar. File database baru mengecil setelah "Kecilkan file".',
    })


@router.post('/system/data/delete')
@limiter.limit('10 per hour')
async def delete_data_range(request: Request):
    await require_admin(request)
    from app.database import get_db_context
    user = get_current_user(request)
    payload = await safe_json(request)
    spec, err = _parse_purge_request(payload)
    if err:
        return JSONResponse({'success': False, 'error': err}, status_code=400)
    if payload.get('confirm') is not True:
        return JSONResponse({'success': False, 'error':
            'Konfirmasi diperlukan. Lihat pratinjau dulu lalu kirim confirm=true.'},
            status_code=400)
    config = get_config()
    backup_name = None
    try:
        if payload.get('backup_first'):
            from app.background import create_backup_file
            backup_path = await create_backup_file(config.BACKUP_DIR, config.DB_PATH,
                                             prefix='pre-delete')
            backup_name = os.path.basename(backup_path)

        async def _do():
            deleted = {}
            async with get_db_context() as conn:
                for key in spec['tables']:
                    table, _, _, _ = PURGE_TABLES[key]
                    where, params = _purge_where(key, spec)
                    total = 0
                    while True:
                        r = await conn.execute(
                            f'DELETE FROM {table} WHERE rowid IN '
                            f'(SELECT rowid FROM {table} WHERE {where} LIMIT {PURGE_BATCH})',
                            params)
                        await conn.commit()
                        total += r.rowcount
                        if r.rowcount < PURGE_BATCH:
                            break
                    deleted[key] = total
                total_deleted = sum(deleted.values())
                await audit(conn, request, user['user_id'], user['username'], 'data.delete',
                      json.dumps({'tables': spec['tables'], 'from': spec['start'],
                                  'to_exclusive': spec['end_exclusive'],
                                  'device_id': spec['device_id'],
                                  'dashboard_id': spec['dashboard_id'],
                                  'deleted': deleted, 'backup': backup_name},
                                 ensure_ascii=False))
                await conn.commit()
            return deleted, total_deleted

        deleted, total_deleted = await _do()
        return JSONResponse({'success': True, 'deleted': deleted,
                             'total_deleted': total_deleted, 'backup': backup_name,
                             'message': f'{total_deleted} baris dihapus'})
    except Exception as e:
        logger.error(f"Hapus data per rentang gagal: {e}", exc_info=True)
        return JSONResponse({'success': False,
                             'error': 'Terjadi kesalahan internal. Detail ada di log server.',
                             'backup': backup_name}, status_code=500)


@router.post('/system/vacuum')
@limiter.limit('3 per hour')
async def vacuum_database(request: Request):
    await require_admin(request)
    import shutil
    from app.database import get_db_context
    user = get_current_user(request)
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
        return JSONResponse({'success': False, 'error': (
            f'Ruang disk kosong tidak cukup untuk VACUUM '
            f'(butuh sekitar {needed // (1024 * 1024)} MB, tersedia '
            f'{free // (1024 * 1024)} MB).')}, status_code=409)

    async def _vacuum():
        conn = sqlite3.connect(db_path, timeout=60.0)
        conn.isolation_level = None
        try:
            conn.execute('PRAGMA busy_timeout=60000')
            conn.execute('VACUUM')
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:
            conn.close()

    try:
        await _vacuum()
    except Exception as e:
        logger.error(f"VACUUM gagal: {e}", exc_info=True)
        return JSONResponse(
            {'success': False,
             'error': 'VACUUM gagal. Database sedang sibuk? Coba lagi nanti.'},
            status_code=500)
    after = _size()

    async def _audit():
        async with get_db_context() as conn:
            await audit(conn, request, user['user_id'], user['username'], 'db.vacuum',
                  f'before={before} after={after}')
            await conn.commit()

    await _audit()
    return JSONResponse({'success': True,
                         'before_mb': round(before / (1024 * 1024), 2),
                         'after_mb': round(after / (1024 * 1024), 2),
                         'freed_mb': round(max(0, before - after) / (1024 * 1024), 2)})


@router.get('/system/audit-log')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_audit_log(request: Request):
    await require_admin(request)
    from app.database import get_db_context
    limit = min(int(request.query_params.get('limit', '50') or 50), 500)

    async def _do():
        async with get_db_context() as conn:
            rows = await (await conn.execute(
                'SELECT id, username, action, detail, ip, created_at FROM audit_log '
                'ORDER BY id DESC LIMIT ?', (limit,))).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d['created_at'] = _clean_timestamp(d.get('created_at'))
            out.append(d)
        return out

    out = await _do()
    return JSONResponse({'success': True, 'entries': out})


@router.get('/system/alert-rules')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_global_alert_rules(request: Request):
    get_current_user(request)
    from app.database import get_db_context
    config = get_config()

    async def _do():
        async with get_db_context() as conn:
            return await (await conn.execute(
                "SELECT value FROM user_settings WHERE key = 'global_alert_rules'"
            )).fetchone()

    row = await _do()
    custom_rules = None
    if row and row['value']:
        try:
            custom_rules = json.loads(row['value'])
        except (json.JSONDecodeError, TypeError):
            custom_rules = None
    default_rules = {k: v for k, v in config.ALERT_RULES.items() if isinstance(v, dict)}
    return JSONResponse({'success': True,
                         'alert_rules': custom_rules or default_rules,
                         'is_custom': custom_rules is not None,
                         'default_rules': default_rules})


@router.put('/system/alert-rules')
@limiter.limit('20 per minute')
async def update_global_alert_rules(request: Request):
    await require_admin(request)
    from app.database import get_db_context, get_wib_time
    from app.utils import validate_alert_rules
    from app.alerts import invalidate_global_rules_cache
    payload = await safe_json(request)
    if payload is None or not isinstance(payload, dict):
        return JSONResponse(
            {'success': False, 'error': 'Format rules harus object'}, status_code=400)
    is_valid, err_msg = validate_alert_rules(payload)
    if not is_valid:
        return JSONResponse({'success': False, 'error': err_msg}, status_code=400)
    if not payload:
        return JSONResponse(
            {'success': False, 'error': 'Minimal 1 sensor rule'}, status_code=400)
    try:
        async def _do():
            async with get_db_context() as conn:
                await conn.execute('''
                    INSERT INTO user_settings (key, value, updated_at)
                    VALUES ('global_alert_rules', ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                ''', (json.dumps(payload), get_wib_time()))
                await conn.commit()

        await _do()
        invalidate_global_rules_cache()
        logger.info("Global alert rules updated")
        return JSONResponse({'success': True, 'alert_rules': payload,
                             'message': 'Global alert rules tersimpan'})
    except Exception as e:
        logger.error(f"Update global rules failed: {e}", exc_info=True)
        return JSONResponse(
            {'success': False,
             'error': 'Terjadi kesalahan internal. Detail ada di log server.'},
            status_code=500)


@router.delete('/system/alert-rules')
@limiter.limit('20 per minute')
async def reset_global_alert_rules(request: Request):
    await require_admin(request)
    from app.database import get_db_context
    from app.alerts import invalidate_global_rules_cache
    try:
        async def _do():
            async with get_db_context() as conn:
                await conn.execute(
                    "DELETE FROM user_settings WHERE key = 'global_alert_rules'")
                await conn.commit()

        await _do()
        invalidate_global_rules_cache()
        logger.info("Global alert rules reset")
        return JSONResponse({'success': True,
                             'message': 'Global alert rules direset ke default config'})
    except Exception as e:
        logger.error(f"Reset global rules failed: {e}", exc_info=True)
        return JSONResponse(
            {'success': False,
             'error': 'Terjadi kesalahan internal. Detail ada di log server.'},
            status_code=500)


@router.post('/system/restore')
@limiter.limit('2 per hour')
async def restore_database(request: Request):
    await require_admin(request)
    from app.database import get_wib_time
    user = get_current_user(request)
    payload = await safe_json(request) or {}
    filename = (payload.get('filename') or '').strip()
    confirm = (payload.get('confirm') or '').strip()
    if confirm != 'RESTORE':
        return JSONResponse({'success': False, 'error':
            'Konfirmasi salah. Kirim field "confirm" dengan nilai "RESTORE".'},
            status_code=400)
    if not filename:
        return JSONResponse({'success': False, 'error': 'Filename wajib'}, status_code=400)
    from werkzeug.utils import secure_filename
    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename or not safe_name.endswith('.db'):
        return JSONResponse({'success': False, 'error': 'Nama file tidak valid'}, status_code=400)
    config = get_config()
    backup_file = os.path.join(config.BACKUP_DIR, safe_name)
    real_dir = os.path.realpath(config.BACKUP_DIR)
    real_path = os.path.realpath(backup_file)
    if not real_path.startswith(real_dir + os.sep):
        logger.warning(f"Restore path traversal attempt: {filename}")
        return JSONResponse({'success': False, 'error': 'Akses ditolak'}, status_code=403)
    if not os.path.isfile(real_path):
        return JSONResponse(
            {'success': False, 'error': 'File backup tidak ditemukan'}, status_code=404)
    try:
        async def _verify():
            test_conn = sqlite3.connect(real_path, timeout=5.0)
            result = test_conn.execute('PRAGMA integrity_check').fetchone()
            test_conn.close()
            return result

        result = await _verify()
        if not result or result[0] != 'ok':
            return JSONResponse({'success': False, 'error':
                f"File backup corrupt (integrity check: "
                f"{result[0] if result else 'unknown'})"}, status_code=400)
    except Exception as e:
        logger.error(f"Restore: verifikasi file backup gagal: {e}", exc_info=True)
        return JSONResponse(
            {'success': False, 'error': 'Gagal verifikasi file backup'}, status_code=400)
    pre_restore_name = f"pre-restore-{get_wib_time().strftime('%Y%m%d_%H%M%S')}.db"
    pre_restore_path = os.path.join(config.BACKUP_DIR, pre_restore_name)
    try:
        async def _backup():
            os.makedirs(config.BACKUP_DIR, exist_ok=True)
            src = sqlite3.connect(config.DB_PATH, timeout=30.0)
            dst = sqlite3.connect(pre_restore_path)
            with dst:
                src.backup(dst)
            dst.close()
            src.close()

        await _backup()
        logger.info(f"Pre-restore backup saved: {pre_restore_path}")
    except Exception as e:
        logger.error(f"Restore: backup DB current gagal: {e}", exc_info=True)
        return JSONResponse(
            {'success': False, 'error': 'Gagal membuat backup DB saat ini'}, status_code=500)
    try:
        from app.restore import schedule_restore
        schedule_restore(real_path, config.DB_PATH, {
            'pre_restore_backup': pre_restore_name,
            'requested_by': user['user_id'],
        })
        logger.warning(f"DATABASE RESTORE DIJADWALKAN by user {user['user_id']} "
                       f"from {safe_name}")
    except Exception as e:
        logger.error(f"Restore failed: {e}", exc_info=True)
        return JSONResponse({'success': False,
            'error': f'Gagal menyiapkan restore. Pre-restore backup di: {pre_restore_name}'},
            status_code=500)
    return JSONResponse({'success': True,
        'message': ('Restore disiapkan dan akan diterapkan saat aplikasi di-restart. '
                    'PENTING: Restart container/aplikasi sekarang '
                    '(hentikan semua worker, lalu start). '
                    f'Pre-restore backup: {pre_restore_name}'),
        'pre_restore_backup': pre_restore_name,
        'restored_from': safe_name,
        'restart_required': True})
