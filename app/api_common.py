"""
AAguard IoT - API Common Helpers
Helper yang dipakai banyak route (timestamp, label alert, validasi username,
purge) punya rumah sendiri.
"""
from datetime import timedelta, datetime

# ============================================================
# Helper
# ============================================================
def _clean_timestamp(ts):
    if not ts:
        return None
    s = str(ts).strip().replace('T', ' ')
    return s.split('.')[0]


def _alert_label(alert_type, severity):
    type_labels = {
        'temperature': 'Suhu', 'humidity': 'Kelembaban', 'gas_level': 'Level Gas',
        'offline': 'Perangkat Offline', 'smoke': 'Asap',
    }
    base = type_labels.get(alert_type, alert_type.replace('_', ' ').title())
    sev_labels = {'danger': 'Bahaya', 'warning': 'Peringatan', 'info': 'Info', 'healthy': 'Normal'}
    return f"{base} — {sev_labels.get(severity, severity)}"


AUTO_INTERVAL_MIN_SAMPLES = 5      # minimal jumlah data terakhir
AUTO_INTERVAL_MIN_DELTAS = 3       # minimal selisih valid
AUTO_INTERVAL_IGNORE_BELOW = 2     # detik: selisih lebih kecil diabaikan
AUTO_INTERVAL_FLOOR = 10           # detik: interval otomatis tidak di bawah ini


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
