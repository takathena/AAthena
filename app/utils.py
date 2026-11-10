"""
AAguard IoT - Utilities
"""
import json
import os
import fcntl
import secrets
import logging
import hmac
import hashlib
from datetime import datetime, timedelta, timezone

logger = logging.getLogger('aaguard')

WIB = timezone(timedelta(hours=7))


def generate_api_key():
    return secrets.token_hex(32)


def hash_api_key(api_key):
    """SHA-256 hash API key (deterministic untuk lookup)."""
    return hashlib.sha256(api_key.encode('utf-8')).hexdigest()


def verify_api_key(api_key_plain, api_key_hash):
    """Timing-safe comparison."""
    if not api_key_plain or not api_key_hash:
        return False
    computed = hash_api_key(api_key_plain)
    return hmac.compare_digest(computed, api_key_hash)


_CSV_FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def csv_safe(value):
    """Cegah CSV/formula injection: sel string berawalan = + - @ TAB CR diberi awalan '.

    Hanya string yang diubah; angka/None dikembalikan apa adanya.
    """
    if isinstance(value, str) and value and value[0] in _CSV_FORMULA_PREFIXES:
        return "'" + value
    return value


def safe_json_loads(data, default=None):
    if default is None:
        default = {}
    if not data:
        return default
    if isinstance(data, (dict, list)):
        return data
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return default


def parse_datetime(value):
    """Parse datetime → naive WIB."""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None

    if dt.tzinfo is None:
        return dt
    return dt.astimezone(WIB).replace(tzinfo=None)


# ✅ FIX #10: process_lock tidak swallow exception
# Kalau lock gagal karena error sistem (bukan karena lock dipegang proses lain),
# kita raise supaya caller tahu.
class process_lock:
    """Cross-process file lock (dual sync/async context manager).

    Yield True jika lock didapat, False jika lock dipegang proses lain.
    Raise OSError jika ada error sistem (permission, disk, dll).
    Dipakai sebagai:
        with process_lock('name'): ...
        async with process_lock('name'): ...
    """

    def __init__(self, name, blocking=True):
        self.name = name
        self.blocking = blocking
        self._lock_file = None
        self._acquired = False

    def _open(self):
        lock_dir = os.environ.get('AAGUARD_LOCK_DIR', '/tmp')
        try:
            os.makedirs(lock_dir, exist_ok=True)
        except Exception:
            lock_dir = '/tmp'

        lock_path = os.path.join(lock_dir, f'aaguard-{self.name}.lock')
        try:
            self._lock_file = open(lock_path, 'w')
        except OSError as e:
            # Tidak bisa buka file lock → error sistem, raise
            logger.error(f"process_lock({self.name}): cannot open lock file: {e}")
            raise

        flags = fcntl.LOCK_EX
        if not self.blocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(self._lock_file, flags)
            self._acquired = True
        except (IOError, OSError):
            # Lock dipegang proses lain → yield False, bukan raise
            self._acquired = False
        return self._acquired

    def _close(self):
        if self._lock_file is not None:
            try:
                if self._acquired:
                    fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self._lock_file.close()
            except Exception:
                pass
            self._lock_file = None

    def __enter__(self):
        return self._open()

    def __exit__(self, exc_type, exc, tb):
        self._close()
        return False

    async def __aenter__(self):
        return self._open()

    async def __aexit__(self, exc_type, exc, tb):
        self._close()
        return False


VALID_ALERT_SEVERITIES = ['healthy', 'info', 'warning', 'danger']


def validate_single_alert_rule(rule):
    """Validasi satu rule sensor. Return (bool, pesan_error|None).

    Satu-satunya sumber aturan validitas rule, dipakai oleh API (lewat
    validate_alert_rules) dan oleh mesin alert (alerts._validate_rule).
    """
    if not isinstance(rule, dict):
        return False, 'harus berupa object'
    for severity, range_dict in rule.items():
        if severity.startswith('_'):
            continue
        if severity not in VALID_ALERT_SEVERITIES:
            return False, f"severity '{severity}' tidak valid"
        if not isinstance(range_dict, dict):
            return False, f"'{severity}' harus berupa object"
        if 'min' not in range_dict or 'max' not in range_dict:
            return False, f"'{severity}' wajib punya 'min' dan 'max'"
        try:
            lo = float(range_dict['min'])
            hi = float(range_dict['max'])
        except (TypeError, ValueError):
            return False, f"'{severity}' min/max harus angka"
        if lo > hi:
            return False, f"'{severity}' min tidak boleh > max"
    return True, None


def validate_alert_rules(rules):
    if not isinstance(rules, dict):
        return False, "alert_rules harus berupa object"

    for sensor_key, rule in rules.items():
        ok, reason = validate_single_alert_rule(rule)
        if not ok:
            return False, f"Rule '{sensor_key}' {reason}"

    return True, None
