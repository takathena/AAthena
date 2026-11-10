"""
AAguard IoT - Alert System (FastAPI async murni)

State machine: healthy → warning → danger → warning → healthy

Fix v5.0:
  - Ack dengan severity-aware skip: alert baru di-skip hanya jika severity
    baru <= severity yang di-ack. Kalau severity memburuk (warning→danger),
    alert baru tetap di-trigger.
  - Setelah suhu pulih ke healthy, log 'cleared' → siap trigger lagi.
  - Message TIDAK lagi berisi nilai (value) karena sudah ditampilkan
    sebagai badge di frontend. Cegah duplikasi "32.1°C — 32.1°C di luar...".

DB lewat `get_db_async()` (aiosqlite) dengan PRAGMA yang sama seperti
`get_db_context` sync: WAL + busy_timeout=30000 (+ synchronous NORMAL,
foreign_keys ON, temp_store MEMORY, cache_size -64000).
Helper murni (band/hysteresis/format) tetap sync.
"""
import copy
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager

import aiosqlite

from app.config import get_config
from app.database import get_wib_time
from app.notifier import notify_alert_event
from app import workspace as ws

logger = logging.getLogger('aaguard')

SEVERITY_ORDER = ['healthy', 'info', 'warning', 'danger']
DEFAULT_HYSTERESIS = 0.5

# Rank untuk perbandingan severity (makin tinggi makin bahaya)
SEVERITY_RANK = {'healthy': 0, 'info': 1, 'warning': 2, 'danger': 3}

SENSOR_LABELS = {
    'temperature': ('Suhu', '°C'),
    'humidity': ('Kelembaban', '%'),
    'gas_level': ('Level Gas', 'ppm'),
    'smoke': ('Asap', 'ppm'),
    'moisture': ('Kelembaban Tanah', '%'),
    'lux': ('Cahaya', 'lux'),
    'co2': ('CO2', 'ppm'),
    'voc': ('VOC', 'ppb'),
    'air_quality': ('Kualitas Udara', 'AQI'),
    'motion': ('Gerakan', ''),
    'rfid': ('RFID', ''),
}


# ==========================================
# DB ASYNC (aiosqlite)
# ==========================================
def _db_path():
    from app.config import Config
    return Config.DB_PATH


async def _configure_async_conn(conn):
    conn.row_factory = aiosqlite.Row
    await conn.execute('PRAGMA journal_mode=WAL')
    await conn.execute('PRAGMA synchronous=NORMAL')
    await conn.execute('PRAGMA foreign_keys=ON')
    await conn.execute('PRAGMA busy_timeout=30000')
    await conn.execute('PRAGMA temp_store=MEMORY')
    await conn.execute('PRAGMA cache_size=-64000')
    return conn


@asynccontextmanager
async def get_db_async():
    """Pengganti `get_db_context` sync berbasis aiosqlite."""
    db_path = _db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = await aiosqlite.connect(
        db_path, timeout=30.0, isolation_level='DEFERRED')
    await _configure_async_conn(conn)
    try:
        yield conn
    finally:
        await conn.close()


async def _one(conn, sql, params=()):
    return await (await conn.execute(sql, params)).fetchone()


async def _all(conn, sql, params=()):
    return await (await conn.execute(sql, params)).fetchall()


async def _exec(conn, sql, params=()):
    return await conn.execute(sql, params)


def _get_sensor_label(key):
    return SENSOR_LABELS.get(key, (key.replace('_', ' ').title(), ''))


# Cache global rules (TTL pendek, thread-safe). Di-invalidate saat
# PUT/DELETE /system/alert-rules pada worker yang menangani request;
# worker lain menyusul paling lambat setelah TTL habis.
GLOBAL_RULES_TTL_SECONDS = 45
_global_rules_cache = {'rules': None, 'ts': 0.0}
_global_rules_lock = threading.Lock()


def invalidate_global_rules_cache():
    with _global_rules_lock:
        _global_rules_cache['rules'] = None
        _global_rules_cache['ts'] = 0.0


def _default_global_rules():
    config = get_config()
    return {
        k: copy.deepcopy(v)
        for k, v in config.ALERT_RULES.items() if isinstance(v, dict)
    }


async def _load_stored_global_rules(conn=None):
    """Baca rules tersimpan (user_settings.global_alert_rules).

    Return dict {sensor: rule} yang lolos _validate_rule, atau {} bila
    tidak ada / korup. Tidak pernah raise.
    """
    try:
        sql = "SELECT value FROM user_settings WHERE key = 'global_alert_rules'"
        if conn is not None:
            row = await _one(conn, sql)
        else:
            async with get_db_async() as c:
                row = await _one(c, sql)
    except Exception as e:
        logger.warning(f"Gagal membaca global alert rules dari DB: {e}")
        return {}

    if not row or not row['value']:
        return {}

    try:
        parsed = json.loads(row['value'])
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Global alert rules di user_settings korup, pakai default: {e}")
        return {}

    if not isinstance(parsed, dict):
        logger.warning("Global alert rules di user_settings bukan object, pakai default")
        return {}

    valid = {}
    for sensor, rule in parsed.items():
        if _validate_rule(rule):
            valid[sensor] = rule
        else:
            logger.warning(f"Global rule untuk '{sensor}' tidak valid, diabaikan")
    return valid


def _get_global_rules_sync(conn=None):
    """Sync version untuk tests/caller sync: baca user_settings via sync conn."""
    now = time.monotonic()
    with _global_rules_lock:
        cached = _global_rules_cache['rules']
        if cached is not None and (now - _global_rules_cache['ts']) < GLOBAL_RULES_TTL_SECONDS:
            return copy.deepcopy(cached)
    rules = _default_global_rules()
    try:
        if conn is not None:
            row = conn.execute("SELECT value FROM user_settings WHERE key = 'global_alert_rules'").fetchone()
        else:
            from app.database import get_db_context as _sync_ctx
            with _sync_ctx() as c:
                row = c.execute("SELECT value FROM user_settings WHERE key = 'global_alert_rules'").fetchone()
        stored = {}
        if row and row['value']:
            parsed = json.loads(row['value'])
            if isinstance(parsed, dict):
                for sensor, rule in parsed.items():
                    if _validate_rule(rule):
                        stored[sensor] = rule
    except Exception:
        stored = {}
    for sensor, rule in stored.items():
        merged = copy.deepcopy(rule)
        for k, v in rules.get(sensor, {}).items():
            if k.startswith('_'):
                merged.setdefault(k, v)
        rules[sensor] = merged
    with _global_rules_lock:
        _global_rules_cache['rules'] = copy.deepcopy(rules)
        _global_rules_cache['ts'] = now
    return rules


async def _get_global_rules(conn=None):
    """Rules default config, ditimpa per sensor oleh rules tersimpan di DB."""
    now = time.monotonic()
    with _global_rules_lock:
        cached = _global_rules_cache['rules']
        if cached is not None and (now - _global_rules_cache['ts']) < GLOBAL_RULES_TTL_SECONDS:
            return copy.deepcopy(cached)

    rules = _default_global_rules()
    for sensor, rule in (await _load_stored_global_rules(conn)).items():
        merged = copy.deepcopy(rule)
        # Kunci berawalan '_' (mis. _hysteresis) dari default tetap terbawa
        # kalau rule tersimpan tidak mengisinya.
        for k, v in rules.get(sensor, {}).items():
            if k.startswith('_'):
                merged.setdefault(k, v)
        rules[sensor] = merged

    with _global_rules_lock:
        _global_rules_cache['rules'] = copy.deepcopy(rules)
        _global_rules_cache['ts'] = now
    return rules


def _validate_rule(rule):
    # Satu sumber aturan validasi (termasuk min <= max) dengan API.
    from app.utils import validate_single_alert_rule
    ok, _ = validate_single_alert_rule(rule)
    return ok


def _band(rule, severity):
    """Return (min, max) float untuk satu band, atau None bila tidak ada/invalid."""
    r = rule.get(severity)
    if not isinstance(r, dict):
        return None
    try:
        return float(r['min']), float(r['max'])
    except (KeyError, TypeError, ValueError):
        return None


def _evaluate_severity(value, rule):
    """Tentukan severity dari band yang memuat `value`.

    Band di ALERT_RULES bersarang (healthy ⊂ info ⊂ warning ⊂ danger), jadi band
    PERTAMA (dari paling ringan) yang memuat value adalah severity-nya. Bila value
    tidak masuk band mana pun, itu berarti melampaui band terlebar → 'danger'.
    """
    if not _validate_rule(rule):
        return None, None

    for severity in SEVERITY_ORDER:
        bounds = _band(rule, severity)
        if bounds is None:
            continue
        if bounds[0] <= value <= bounds[1]:
            return severity, None

    return 'danger', None


def _severity_rank(sev):
    return SEVERITY_RANK.get(sev, 0)


def _apply_hysteresis(new_severity, old_severity, value, rule):
    if not old_severity or old_severity == new_severity:
        return new_severity

    old_rank = _severity_rank(old_severity)
    new_rank = _severity_rank(new_severity)

    if new_rank > old_rank:
        return new_severity

    offset = float(rule.get('_hysteresis', DEFAULT_HYSTERESIS))
    new_range = rule.get(new_severity)
    if not new_range:
        return new_severity

    try:
        n_min = float(new_range['min'])
        n_max = float(new_range['max'])
    except (TypeError, ValueError):
        return new_severity

    if (n_min + offset) <= value <= (n_max - offset):
        return new_severity
    return old_severity


def evaluate(value, rule, old_severity=None):
    """Evaluate murni: severity dari band + hysteresis per-sensor.

    Return severity final (atau None bila rule invalid).
    """
    new_severity, _ = _evaluate_severity(value, rule)
    if new_severity is None:
        return None
    return _apply_hysteresis(new_severity, old_severity, value, rule)


_BAND_LABELS = {'healthy': 'normal', 'info': 'info', 'warning': 'warning', 'danger': 'danger'}


def _reference_band(value, rule):
    """Band dengan severity TERTINGGI yang tidak memuat `value`.

    Band bersarang, jadi band ini adalah batas yang benar-benar dilanggar.
    Contoh suhu 36 °C: healthy (6–28) dan warning (0–32) tidak memuat 36 →
    acuannya warning, bukan healthy. Return (nama, min, max) atau None.
    """
    ref = None
    for severity in SEVERITY_ORDER:
        bounds = _band(rule, severity)
        if bounds is None:
            continue
        if bounds[0] <= value <= bounds[1]:
            continue
        ref = (severity, bounds[0], bounds[1])
    return ref


def _format_alert_message(key, value, severity, rule):
    """Format pesan alert TANPA nilai aktual.

    Nilai aktual (mis. "32.1°C") dan label sensor sudah ditampilkan frontend
    sebagai badge `.alert-val` + teks sensor, jadi pesan hanya menyebut batas
    yang benar-benar dilanggar agar tidak duplikat:
        (suhu, 36) → "Melewati batas warning (32°C)"
    """
    ref = _reference_band(value, rule) if isinstance(value, (int, float)) else None
    if ref is not None:
        ref_sev, r_min, r_max = ref
        _, unit = _get_sensor_label(key)
        name = _BAND_LABELS.get(ref_sev, ref_sev)
        if value > r_max:
            return f"Melewati batas {name} ({r_max:g}{unit})"
        if value < r_min:
            return f"Di bawah batas {name} ({r_min:g}{unit})"

    return "Di luar batas yang ditentukan"


def _format_recovery_message(key, value):
    """Format pesan recovery — ini tetap sertakan nilai karena
    tujuannya konfirmasi nilai sudah kembali normal."""
    label, unit = _get_sensor_label(key)
    value_str = f"{value:g}{unit}" if unit else f"{value:g}"
    return f"Kembali normal: {value_str}"


async def _log_history(conn, device_id, alert_type, severity, message, value, action):
    try:
        await _exec(conn, '''
            INSERT INTO alert_history
            (device_id, alert_type, severity, message, value, action, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (device_id, alert_type, severity, message, value, action, get_wib_time()))
    except Exception as e:
        logger.error(f"Failed to log alert history: {e}", exc_info=True)


async def _build_notify_event(conn, device_id, alert_type, severity, message, value,
                              event_type, old_severity=None):
    try:
        device = await _one(
            conn,
            'SELECT device_name, location, dashboard_id FROM devices WHERE device_id = ?',
            (device_id,))

        return {
            'event': event_type,
            'device_id': device_id,
            'dashboard_id': device['dashboard_id'] if device else None,
            'device_name': device['device_name'] if device else device_id,
            'location': device['location'] if device else '',
            'alert_type': alert_type,
            'severity': severity,
            'old_severity': old_severity,
            'message': message,
            'value': value,
            'timestamp': get_wib_time().strftime('%Y-%m-%d %H:%M:%S WIB'),
        }
    except Exception as e:
        logger.warning(f"Failed to build notify event: {e}")
        return None


async def _get_last_history_action(conn, device_id, alert_type):
    """Ambil action + severity dari entry terakhir di alert_history."""
    return await _one(conn, '''
        SELECT action, severity FROM alert_history
        WHERE device_id = ? AND alert_type = ?
        ORDER BY created_at DESC, id DESC LIMIT 1
    ''', (device_id, alert_type))


async def _should_skip_alert(conn, device_id, alert_type, new_severity):
    """Return True kalau alert baru harus di-skip.

    Aturan:
      1. Tidak ada history → trigger
      2. History terakhir 'cleared' → trigger (user sudah pulih, siap re-alert)
      3. History terakhir 'acknowledged':
         - new_severity <= severity_ack  → SKIP (kondisi sama/membaik)
         - new_severity >  severity_ack  → trigger (kondisi memburuk)
      4. Action lain → trigger
    """
    last = await _get_last_history_action(conn, device_id, alert_type)
    if not last:
        return False

    action = last['action']

    if action == 'cleared':
        return False

    if action == 'acknowledged':
        last_rank = SEVERITY_RANK.get(last['severity'], 0)
        new_rank = SEVERITY_RANK.get(new_severity, 0)
        if new_rank <= last_rank:
            logger.debug(
                f"[Alert] Skip {device_id}/{alert_type}: ack severity "
                f"{last['severity']} >= new {new_severity}"
            )
            return True
        logger.info(
            f"[Alert] Re-trigger {device_id}/{alert_type}: severity memburuk "
            f"dari {last['severity']} ke {new_severity}"
        )
        return False

    return False


async def _log_implicit_recovery_if_needed(conn, device_id, alert_type, value):
    """Kalau user pernah ack tapi belum log 'cleared' (device pulih), log sekarang.

    Dipanggil saat data masuk dengan severity healthy dan tidak ada alert aktif.
    """
    last = await _get_last_history_action(conn, device_id, alert_type)
    if last and last['action'] == 'acknowledged':
        await _log_history(conn, device_id, alert_type, 'healthy',
                           _format_recovery_message(alert_type, value),
                           value, 'cleared')
        logger.info(f"[Alert] Log implicit 'cleared' for {device_id}/{alert_type}")


async def get_device_alert_rules(conn, device_id):
    """Async version (untuk check_and_create_alerts). Sync callers pakai _sync."""
    row = await _one(
        conn,
        'SELECT alert_rules FROM devices WHERE device_id = ?',
        (device_id,))

    # Rules per-device menimpa global PER SENSOR (bukan mengganti total).
    rules = await _get_global_rules(conn)

    if row and row['alert_rules']:
        try:
            parsed = json.loads(row['alert_rules'])
            if isinstance(parsed, dict):
                for sensor, rule in parsed.items():
                    if _validate_rule(rule):
                        rules[sensor] = rule
                    else:
                        logger.warning(
                            f"Custom rule '{sensor}' untuk {device_id} tidak valid, diabaikan"
                        )
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Invalid alert_rules JSON for {device_id}: {e}")

    return rules


async def check_and_create_alerts(device_id, sensor_data):
    if not isinstance(sensor_data, dict):
        return []

    changes = []
    pending_notifications = []

    async with get_db_async() as conn:
        # Lock tulis sejak awal: tutup race read-modify-write dup alert aktif.
        await conn.execute('BEGIN IMMEDIATE')
        alert_rules = await get_device_alert_rules(conn, device_id)

        for key, value in sensor_data.items():
            if key in ('uid', 'card_id', 'tag', 'rfid'):
                continue
            if key not in alert_rules:
                continue
            if isinstance(value, bool):
                continue
            if not isinstance(value, (int, float)):
                continue

            rule = alert_rules[key]
            new_severity, _ = _evaluate_severity(value, rule)
            if new_severity is None:
                continue

            existing = await _one(conn, '''
                SELECT id, severity, message, value FROM alerts
                WHERE device_id = ? AND alert_type = ? AND is_active = 1
            ''', (device_id, key))

            old_severity = existing['severity'] if existing else None
            final_severity = _apply_hysteresis(new_severity, old_severity, value, rule)

            # ========= RECOVERY (healthy) =========
            if final_severity == 'healthy':
                if existing:
                    # Alert masih aktif → tutup + log 'cleared'
                    await _exec(conn, '''
                        UPDATE alerts SET is_active = 0, updated_at = ?, value = ?
                        WHERE id = ?
                    ''', (get_wib_time(), value, existing['id']))

                    recovery_msg = _format_recovery_message(key, value)
                    await _log_history(conn, device_id, key, 'healthy', recovery_msg,
                                       value, 'cleared')
                    changes.append({'type': key, 'action': 'cleared',
                                    'severity': 'healthy', 'value': value})

                    evt = await _build_notify_event(
                        conn, device_id, key, 'healthy', recovery_msg,
                        value, 'cleared', old_severity=existing['severity']
                    )
                    if evt:
                        pending_notifications.append(evt)
                else:
                    # Tidak ada alert aktif, tapi mungkin user pernah ack
                    # → log 'cleared' supaya siap re-trigger
                    await _log_implicit_recovery_if_needed(conn, device_id, key, value)
                continue

            # ========= ALERT (warning / danger) =========
            message = _format_alert_message(key, value, final_severity, rule)

            if existing:
                # Alert masih aktif — update severity/message
                if existing['severity'] != final_severity:
                    await _exec(conn, '''
                        UPDATE alerts
                        SET severity = ?, message = ?, value = ?, updated_at = ?
                        WHERE id = ?
                    ''', (final_severity, message, value, get_wib_time(), existing['id']))
                    await _log_history(conn, device_id, key, final_severity, message,
                                       value, 'severity_changed')
                    changes.append({'type': key, 'action': 'severity_changed',
                                    'severity': final_severity,
                                    'old_severity': existing['severity'],
                                    'value': value})

                    evt = await _build_notify_event(
                        conn, device_id, key, final_severity, message,
                        value, 'severity_changed', old_severity=existing['severity']
                    )
                    if evt:
                        pending_notifications.append(evt)
                else:
                    # Sama severity, update message saja
                    await _exec(conn, '''
                        UPDATE alerts SET message = ?, value = ?, updated_at = ?
                        WHERE id = ?
                    ''', (message, value, get_wib_time(), existing['id']))
            else:
                # Tidak ada alert aktif — cek apakah perlu trigger baru
                if await _should_skip_alert(conn, device_id, key, final_severity):
                    continue

                await _exec(conn, '''
                    INSERT INTO alerts
                    (device_id, alert_type, severity, message, value,
                     is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ''', (device_id, key, final_severity, message, value,
                      get_wib_time(), get_wib_time()))
                await _log_history(conn, device_id, key, final_severity, message,
                                   value, 'created')
                changes.append({'type': key, 'action': 'created',
                                'severity': final_severity, 'value': value})

                evt = await _build_notify_event(
                    conn, device_id, key, final_severity, message,
                    value, 'created', old_severity=None
                )
                if evt:
                    pending_notifications.append(evt)

        await conn.commit()

    for evt in pending_notifications:
        try:
            notify_alert_event(evt)
        except Exception as e:
            logger.warning(f"Failed to enqueue notification: {e}")

    return changes


async def create_offline_alert(device_id, severity='danger'):
    if severity not in ('info', 'warning', 'danger'):
        severity = 'danger'

    pending_notifications = []

    async with get_db_async() as conn:
        existing = await _one(conn, '''
            SELECT id, severity FROM alerts
            WHERE device_id = ? AND alert_type = 'offline' AND is_active = 1
        ''', (device_id,))

        if existing:
            if existing['severity'] != severity:
                await _exec(conn, '''
                    UPDATE alerts SET severity = ?, updated_at = ? WHERE id = ?
                ''', (severity, get_wib_time(), existing['id']))
                await _log_history(conn, device_id, 'offline', severity,
                                   f"Severity offline berubah ke {severity}", None,
                                   'severity_changed')

                evt = await _build_notify_event(
                    conn, device_id, 'offline', severity,
                    f"Perangkat offline dengan severity {severity}",
                    None, 'severity_changed', old_severity=existing['severity']
                )
                if evt:
                    pending_notifications.append(evt)

                await conn.commit()
                for e in pending_notifications:
                    try:
                        notify_alert_event(e)
                    except Exception as e2:
                        logger.warning(f"Failed to enqueue notification: {e2}")
                return True
            return False

        # Cek apakah perlu skip (user sudah ack, belum pulih)
        if await _should_skip_alert(conn, device_id, 'offline', severity):
            return False

        message = "Perangkat tidak mengirim data melebihi batas waktu"
        await _exec(conn, '''
            INSERT INTO alerts
            (device_id, alert_type, severity, message, is_active, created_at, updated_at)
            VALUES (?, 'offline', ?, ?, 1, ?, ?)
        ''', (device_id, severity, message, get_wib_time(), get_wib_time()))
        await _log_history(conn, device_id, 'offline', severity, message, None, 'created')

        evt = await _build_notify_event(
            conn, device_id, 'offline', severity, message, None, 'created'
        )
        if evt:
            pending_notifications.append(evt)

        await conn.commit()

        for e in pending_notifications:
            try:
                notify_alert_event(e)
            except Exception as e2:
                logger.warning(f"Failed to enqueue notification: {e2}")
        return True


async def clear_offline_alert(device_id):
    async with get_db_async() as conn:
        cur = await _exec(conn, '''
            UPDATE alerts SET is_active = 0, updated_at = ?
            WHERE device_id = ? AND alert_type = 'offline' AND is_active = 1
        ''', (get_wib_time(), device_id))

        if cur.rowcount > 0:
            await _log_history(conn, device_id, 'offline', 'healthy',
                               'Perangkat kembali online', None, 'cleared')

            evt = await _build_notify_event(
                conn, device_id, 'offline', 'healthy',
                'Perangkat kembali online', None, 'cleared', old_severity='danger'
            )

            await conn.commit()

            if evt:
                try:
                    notify_alert_event(evt)
                except Exception as e:
                    logger.warning(f"Failed to enqueue notification: {e}")
            return True
    return False


async def get_active_alerts(limit=100, severity=None, device_id=None, scope=None):
    query = '''
        SELECT a.*, d.device_name, d.location, d.offline_timeout, d.expected_interval
        FROM alerts a
        JOIN devices d ON a.device_id = d.device_id
        WHERE a.is_active = 1 AND a.alert_type != 'uid'
    '''
    params = []
    if severity:
        query += ' AND a.severity = ?'
        params.append(severity)
    if device_id:
        query += ' AND a.device_id = ?'
        params.append(device_id)
    if scope is not None:
        scope_sql, scope_params = ws.device_in_sql(scope, 'a.device_id')
        query += f' AND {scope_sql}'
        params.extend(scope_params)

    query += '''
        ORDER BY
            CASE a.severity
                WHEN 'danger' THEN 1 WHEN 'warning' THEN 2
                WHEN 'info' THEN 3 ELSE 4
            END,
            a.updated_at DESC, a.created_at DESC
        LIMIT ?
    '''
    params.append(limit)

    async with get_db_async() as conn:
        rows = await _all(conn, query, params)
    return [dict(r) for r in rows]


async def get_alert_history(device_id=None, limit=200, scope=None):
    where, params = [], []
    if device_id:
        where.append('h.device_id = ?')
        params.append(device_id)
    if scope is not None:
        scope_sql, scope_params = ws.device_in_sql(scope, 'h.device_id')
        where.append(scope_sql)
        params.extend(scope_params)
    clause = ('WHERE ' + ' AND '.join(where)) if where else ''

    async with get_db_async() as conn:
        rows = await _all(conn, f'''
            SELECT h.*, d.device_name
            FROM alert_history h
            LEFT JOIN devices d ON h.device_id = d.device_id
            {clause}
            ORDER BY h.created_at DESC LIMIT ?
        ''', params + [limit])
    return [dict(r) for r in rows]


async def acknowledge_alert(alert_id, scope=None):
    """Acknowledge alert.

    Menerima ID dari tabel `alerts` ATAU dari tabel `alert_history`
    (fallback, karena frontend lama mengirim history.id).
    """
    if alert_id is None:
        return False

    try:
        alert_id_int = int(alert_id)
    except (ValueError, TypeError):
        return False

    async with get_db_async() as conn:
        alert = await _one(
            conn, 'SELECT * FROM alerts WHERE id = ?', (alert_id_int,))

        # Fallback: mungkin ini history.id
        if not alert:
            hist = await _one(
                conn,
                'SELECT device_id, alert_type FROM alert_history WHERE id = ?',
                (alert_id_int,))
            if hist:
                alert = await _one(conn, '''
                    SELECT * FROM alerts
                    WHERE device_id = ? AND alert_type = ? AND is_active = 1
                    ORDER BY created_at DESC LIMIT 1
                ''', (hist['device_id'], hist['alert_type']))

        if not alert or not alert['is_active']:
            return False

        if scope is not None and not await ws.device_allowed(conn, scope, alert['device_id']):
            return False

        await _exec(conn,
                    'UPDATE alerts SET is_active = 0, updated_at = ? WHERE id = ?',
                    (get_wib_time(), alert['id']))
        await _log_history(conn, alert['device_id'], alert['alert_type'],
                           alert['severity'], alert['message'],
                           alert['value'], 'acknowledged')
        await conn.commit()
        return True


# Alias singkat untuk pemakai router lama.
acknowledge = acknowledge_alert


async def bulk_acknowledge_alerts(alert_ids, scope=None):
    if not alert_ids:
        return 0

    count = 0
    async with get_db_async() as conn:
        now = get_wib_time()
        for raw_id in alert_ids:
            try:
                alert_id = int(raw_id)
            except (ValueError, TypeError):
                continue

            alert = await _one(
                conn, 'SELECT * FROM alerts WHERE id = ? AND is_active = 1',
                (alert_id,))

            # Fallback via history
            if not alert:
                hist = await _one(
                    conn,
                    'SELECT device_id, alert_type FROM alert_history WHERE id = ?',
                    (alert_id,))
                if hist:
                    alert = await _one(conn, '''
                        SELECT * FROM alerts
                        WHERE device_id = ? AND alert_type = ? AND is_active = 1
                        ORDER BY created_at DESC LIMIT 1
                    ''', (hist['device_id'], hist['alert_type']))

            if not alert:
                continue

            if scope is not None and not await ws.device_allowed(conn, scope, alert['device_id']):
                continue

            await _exec(conn,
                        'UPDATE alerts SET is_active = 0, updated_at = ? WHERE id = ?',
                        (now, alert['id']))
            await _log_history(conn, alert['device_id'], alert['alert_type'],
                               alert['severity'], alert['message'],
                               alert['value'], 'acknowledged')
            count += 1
        await conn.commit()

    return count


# --- Compat sync wrappers untuk tests/routers lama (Flask-era sync calls) ---
def _run(coro):
    import asyncio as _aio
    try:
        loop = _aio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # sudah dalam loop: jalankan di thread terpisah
        import concurrent.futures as _cf
        with _cf.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(lambda: _aio.run(coro)).result()
    return _aio.run(coro)


def check_and_create_alerts_sync(device_id, sensor_data):
    return _run(check_and_create_alerts(device_id, sensor_data))


def get_active_alerts_sync(limit=100, severity=None, device_id=None, scope=None):
    return _run(get_active_alerts(limit, severity, device_id, scope))


def get_alert_history_sync(device_id=None, limit=200, scope=None):
    return _run(get_alert_history(device_id, limit, scope))


def acknowledge_alert_sync(alert_id, scope=None):
    return _run(acknowledge_alert(alert_id, scope))


def bulk_acknowledge_alerts_sync(alert_ids, scope=None):
    return _run(bulk_acknowledge_alerts(alert_ids, scope))


def get_device_alert_rules_sync(conn, device_id):
    # conn sync tidak dipakai; buka koneksi async baru
    async def _w():
        async with get_db_async() as c:
            return await get_device_alert_rules(c, device_id)
    return _run(_w())
