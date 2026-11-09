"""
NEXUS IoT - API Common Helpers
Dipisahkan dari app/api.py agar helper yang dipakai banyak route (timestamp,
auth device, status, label alert, auto-interval, user, purge) punya rumah sendiri.
Khususnya test yang mengimpor helper lewat app.api tetap jalan karena app/api.py
mengimpor ulang semua nama di sini.
"""
import logging
from datetime import timedelta, datetime

from app.database import get_db_context, get_wib_time
from app.utils import verify_api_key
from app.alerts import clear_offline_alert

logger = logging.getLogger('nexus')

# ============================================================
# Helper
# ============================================================
def _clean_timestamp(ts):
    if not ts:
        return None
    s = str(ts).strip().replace('T', ' ')
    return s.split('.')[0]


def validate_device_api_key(device_id, api_key):
    if not device_id or not api_key:
        return False

    with get_db_context() as conn:
        device = conn.execute(
            'SELECT device_id, api_key, api_key_hash FROM devices WHERE device_id = ?',
            (device_id,)
        ).fetchone()

    if not device:
        return False

    if device['api_key_hash']:
        return verify_api_key(api_key, device['api_key_hash'])

    if device['api_key']:
        import hmac
        return hmac.compare_digest(device['api_key'], api_key)
    return False


def update_device_status(device_id, status, ip=None):
    with get_db_context() as conn:
        prev = conn.execute(
            'SELECT status FROM devices WHERE device_id = ?', (device_id,)
        ).fetchone()
        prev_status = prev['status'] if prev else None

        if ip:
            conn.execute(
                'UPDATE devices SET status = ?, last_seen = ?, last_ip = ? WHERE device_id = ?',
                (status, get_wib_time(), ip, device_id)
            )
        else:
            conn.execute(
                'UPDATE devices SET status = ?, last_seen = ? WHERE device_id = ?',
                (status, get_wib_time(), device_id)
            )

        if prev_status is not None and prev_status != status:
            conn.execute(
                'INSERT INTO device_status_log (device_id, status, reason, created_at) '
                'VALUES (?, ?, ?, ?)',
                (device_id, status, 'data_received', get_wib_time())
            )
        conn.commit()

    if status == 'online':
        try:
            # clear_offline_alert kini async (FastAPI native). Jalankan via asyncio.run
            # bila belum ada loop berjalan (konteks sync/routers sweep).
            import asyncio as _aio
            _r = clear_offline_alert(device_id)
            try:
                loop = _aio.get_running_loop()  # type: ignore[attr-defined]
            except RuntimeError:
                _aio.run(_r)
            else:
                # ada loop berjalan -> scheduler ke thread
                import concurrent.futures as _cf
                with _cf.ThreadPoolExecutor(max_workers=1) as ex:
                    ex.submit(lambda: _aio.run(clear_offline_alert(device_id))).result(timeout=5)
        except Exception as e:
            logger.error(f"Failed to clear offline alert: {e}", exc_info=True)


def _alert_label(alert_type, severity):
    type_labels = {
        'temperature': 'Suhu', 'humidity': 'Kelembaban', 'gas_level': 'Level Gas',
        'offline': 'Perangkat Offline', 'smoke': 'Asap', 'motion': 'Gerakan',
        'co2': 'CO2', 'moisture': 'Kelembaban Tanah', 'lux': 'Cahaya',
    }
    base = type_labels.get(alert_type, alert_type.replace('_', ' ').title())
    sev_labels = {'danger': 'Bahaya', 'warning': 'Peringatan', 'info': 'Info', 'healthy': 'Normal'}
    return f"{base} — {sev_labels.get(severity, severity)}"


AUTO_INTERVAL_MIN_SAMPLES = 5      # minimal jumlah data terakhir
AUTO_INTERVAL_MIN_DELTAS = 3       # minimal selisih valid
AUTO_INTERVAL_IGNORE_BELOW = 2     # detik: selisih lebih kecil diabaikan
AUTO_INTERVAL_FLOOR = 10           # detik: interval otomatis tidak di bawah ini


def _detect_interval(conn, device_id):
    """Perkirakan interval kirim (detik) dari median selisih data terakhir.

    Return None bila sampel belum cukup. Tidak menulis apa pun ke DB.
    """
    from app.utils import parse_datetime
    rows = conn.execute(
        'SELECT timestamp FROM sensor_data WHERE device_id = ? '
        'ORDER BY timestamp DESC LIMIT 10', (device_id,)
    ).fetchall()
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
    median = deltas[len(deltas) // 2]
    return max(AUTO_INTERVAL_FLOOR, min(86400, int(round(median))))


def _validate_username(username):
    if not username or len(username) < 3:
        return 'Username minimal 3 karakter'
    if len(username) > 64:
        return 'Username maksimal 64 karakter'
    if not all(c.isalnum() or c in '._-' for c in username):
        return 'Username hanya huruf, angka, titik, dash, underscore'
    return None


# ==========================================
# MANAJEMEN DATABASE (admin): hapus per rentang, hapus backup, kecilkan file
# ==========================================
# nama tabel di API -> (tabel, kolom waktu, ekspresi ukuran-baris rata-rata, filter tambahan)
PURGE_TABLES = {
    'sensor_data': ('sensor_data', 'timestamp', 'LENGTH(data) + LENGTH(sensor_type) + 60', ''),
    'alert_history': ('alert_history', 'created_at', 'LENGTH(message) + 70', ''),
    'device_status_log': ('device_status_log', 'created_at', 'LENGTH(reason) + 50', ''),
    'alerts_inactive': ('alerts', 'COALESCE(updated_at, created_at)', 'LENGTH(message) + 80',
                        'is_active = 0'),
}
PURGE_BATCH = 5000


def _parse_purge_request(payload):
    """Validasi body hapus/pratinjau. Return (spec, error_message)."""
    if not isinstance(payload, dict):
        return None, 'Body harus JSON object'

    tables = payload.get('tables')
    if not isinstance(tables, list) or not tables:
        return None, 'Pilih minimal satu tabel'
    unknown = [t for t in tables if t not in PURGE_TABLES]
    if unknown:
        return None, f"Tabel tidak dikenal: {', '.join(map(str, unknown))}"

    def _day(key):
        raw = payload.get(key)
        if raw in (None, ''):
            return None
        try:
            return datetime.strptime(str(raw), '%Y-%m-%d')
        except ValueError:
            raise ValueError(f'{key} harus berformat YYYY-MM-DD')

    try:
        date_from = _day('date_from')
        date_to = _day('date_to')
    except ValueError as e:
        return None, str(e)

    if date_from is None and date_to is None:
        return None, ('Isi minimal salah satu batas tanggal (dari / sampai). '
                      'Hapus tanpa batas tanggal tidak diizinkan.')
    if date_from and date_to and date_from > date_to:
        return None, 'Tanggal "dari" tidak boleh setelah tanggal "sampai"'

    device_id = (payload.get('device_id') or '').strip() or None
    dashboard_id = payload.get('dashboard_id')
    if dashboard_id in ('', None, 0, '0'):
        dashboard_id = None
    else:
        try:
            dashboard_id = int(dashboard_id)
        except (ValueError, TypeError):
            return None, 'dashboard_id tidak valid'

    return {
        'tables': list(dict.fromkeys(tables)),
        'start': date_from.strftime('%Y-%m-%d 00:00:00') if date_from else None,
        'end_exclusive': ((date_to + timedelta(days=1)).strftime('%Y-%m-%d 00:00:00')
                          if date_to else None),
        'device_id': device_id,
        'dashboard_id': dashboard_id,
    }, None


def _purge_where(table_key, spec):
    """WHERE + params untuk satu tabel sesuai spec."""
    _, ts_col, _, extra = PURGE_TABLES[table_key]
    where, params = [], []
    if extra:
        where.append(extra)
    if spec['start']:
        where.append(f'{ts_col} >= ?')
        params.append(spec['start'])
    if spec['end_exclusive']:
        where.append(f'{ts_col} < ?')
        params.append(spec['end_exclusive'])
    if spec['device_id']:
        where.append('device_id = ?')
        params.append(spec['device_id'])
    if spec['dashboard_id'] is not None:
        where.append('device_id IN (SELECT device_id FROM devices WHERE dashboard_id = ?)')
        params.append(spec['dashboard_id'])
    return ' AND '.join(where) if where else '1=1', params


def _purge_preview(conn, spec):
    result, total_rows, total_bytes = {}, 0, 0
    for key in spec['tables']:
        table, _, size_expr, _ = PURGE_TABLES[key]
        where, params = _purge_where(key, spec)
        row = conn.execute(
            f'SELECT COUNT(*) AS n, COALESCE(SUM({size_expr}), COUNT(*) * 80) AS b '
            f'FROM {table} WHERE {where}', params
        ).fetchone()
        n, b = row['n'] or 0, int(row['b'] or 0)
        result[key] = {'rows': n, 'estimated_bytes': b}
        total_rows += n
        total_bytes += b
    return result, total_rows, total_bytes
