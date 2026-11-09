"""
NEXUS IoT - Background Tasks
Hanya satu worker yang menjalankan background tasks (file lock). Worker lain terus
mencoba mengambil alih secara berkala bila pemegang lock mati. Setiap task mencatat
heartbeat di tabel user_settings supaya status terlihat dari /system/info.
"""
import fnmatch
import json
import os
import re
import sqlite3
import threading
import time
import logging
from datetime import datetime, timedelta

from app.config import get_config
from app.database import get_db_context, get_wib_time
from app.utils import parse_datetime
from app.alerts import create_offline_alert, clear_offline_alert

logger = logging.getLogger('nexus')

shutdown_event = threading.Event()
_bg_lock = threading.Lock()

LOCK_RETRY_SECONDS = 30
BACKUP_STARTUP_DELAY = 30          # jeda kecil saat boot sebelum backup pertama
# Backup otomatis yang boleh di-prune. File manual / file lain TIDAK disentuh.
# pre-delete_* dan pre-restore-* dibuat otomatis oleh aplikasi, jadi ikut
# dibersihkan setelah lewat retensi supaya disk tidak penuh.
AUTO_BACKUP_PATTERNS = ('iot_*.db', 'pre-delete_*.db', 'pre-restore-*.db')
# Backup terjadwal — dipakai untuk menghitung kapan backup berikutnya jatuh tempo.
SCHEDULED_BACKUP_PATTERNS = ('iot_*.db',)


def _matches_backup_pattern(name, patterns):
    return any(fnmatch.fnmatch(name, p) for p in patterns)
HEARTBEAT_PREFIX = 'bg_hb_'
STALE_FACTOR = 3                   # stale bila heartbeat lebih tua dari 3x interval
CLEANUP_INTERVAL = 86400


# ==========================================
# FILE LOCK (satu pemilik background tasks)
# ==========================================
class BackgroundLock:
    """Exclusive file lock non-blocking. Dua instance pada path yang sama saling eksklusif."""

    def __init__(self, lock_dir=None, name='nexus-background.lock'):
        self.lock_dir = lock_dir or os.environ.get('NEXUS_LOCK_DIR', '/tmp')
        self.name = name
        self._file = None
        self._guard = threading.Lock()

    @property
    def path(self):
        return os.path.join(self.lock_dir, self.name)

    @property
    def held(self):
        return self._file is not None

    def try_acquire(self):
        import fcntl
        with self._guard:
            if self._file is not None:
                return False
            try:
                os.makedirs(self.lock_dir, exist_ok=True)
            except Exception:
                self.lock_dir = '/tmp'
            f = None
            try:
                # 'a+' agar membuka file TIDAK menghapus isi (pid pemilik) milik proses lain
                f = open(self.path, 'a+')
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                f.seek(0)
                f.truncate()
                f.write(f"pid={os.getpid()}\n")
                f.flush()
                self._file = f
                return True
            except (IOError, OSError):
                if f is not None:
                    try:
                        f.close()
                    except Exception:
                        pass
                return False

    def release(self):
        import fcntl
        with self._guard:
            if self._file is None:
                return
            try:
                fcntl.flock(self._file, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None

    def read_owner_pid(self):
        """pid yang tertulis di file lock (None bila tidak ada/tidak terbaca)."""
        try:
            with open(self.path) as fh:
                m = re.search(r'pid=(\d+)', fh.read())
            return int(m.group(1)) if m else None
        except OSError:
            return None


_lock = BackgroundLock()


def wait_for_lock(lock, stop_event, on_acquire, retry_seconds=LOCK_RETRY_SECONDS, log=None):
    """Coba ambil lock berkala sampai berhasil atau stop_event di-set.

    Return True bila lock didapat (on_acquire sudah dipanggil), False bila dihentikan.
    """
    log = log or logger
    while not stop_event.wait(retry_seconds):
        if lock.try_acquire():
            log.info(f"Background lock diambil alih (pid={os.getpid()})")
            on_acquire()
            return True
    return False


# ==========================================
# HEARTBEAT
# ==========================================
def record_heartbeat(task):
    """Catat waktu terakhir `task` berjalan. Tidak boleh membuat task gagal."""
    try:
        value = json.dumps({'ts': time.time(), 'pid': os.getpid()})
        with get_db_context() as conn:
            conn.execute('''
                INSERT INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                               updated_at = excluded.updated_at
            ''', (HEARTBEAT_PREFIX + task, value, get_wib_time()))
            conn.commit()
    except Exception as e:
        logger.warning(f"Heartbeat '{task}' gagal dicatat: {e}")


def _read_heartbeats():
    out = {}
    try:
        with get_db_context() as conn:
            rows = conn.execute(
                "SELECT key, value FROM user_settings WHERE key LIKE ?",
                (HEARTBEAT_PREFIX + '%',)
            ).fetchall()
        for row in rows:
            try:
                out[row['key'][len(HEARTBEAT_PREFIX):]] = json.loads(row['value'])
            except (ValueError, TypeError):
                continue
    except Exception as e:
        logger.warning(f"Gagal membaca heartbeat: {e}")
    return out


def _iso_wib(ts):
    return (datetime.utcfromtimestamp(ts) + timedelta(hours=7)).strftime('%Y-%m-%d %H:%M:%S')


def get_background_status(config=None, now=None):
    """Ringkasan status background tasks untuk /system/info."""
    config = config or get_config()
    now = time.time() if now is None else now
    beats = _read_heartbeats()

    intervals = {
        'status_check': max(1, config.CHECK_INTERVAL),
        'backup': max(1, config.BACKUP_INTERVAL_HOURS * 3600),
        'cleanup': CLEANUP_INTERVAL,
    }
    enabled = {
        'status_check': config.BACKGROUND_TASKS_ENABLED,
        'backup': config.BACKGROUND_TASKS_ENABLED and config.BACKUP_ENABLED,
        'cleanup': config.BACKGROUND_TASKS_ENABLED,
    }

    last, stale = {}, {}
    for task, interval in intervals.items():
        beat = beats.get(task)
        ts = beat.get('ts') if isinstance(beat, dict) else None
        last[task] = _iso_wib(ts) if ts else None
        # Stale: sudah pernah jalan tapi lebih tua dari 3x interval.
        # (Belum pernah jalan = None; tidak ditandai stale supaya tidak palsu saat boot.)
        stale[task] = bool(enabled[task] and ts and (now - ts) > STALE_FACTOR * interval)

    owner_pid = _lock.read_owner_pid()
    if owner_pid is None:
        pids = [b.get('pid') for b in beats.values() if isinstance(b, dict) and b.get('pid')]
        owner_pid = pids[0] if pids else None

    return {
        'enabled': config.BACKGROUND_TASKS_ENABLED,
        'owner_pid': owner_pid,
        'last_status_check': last['status_check'],
        'last_backup': last['backup'],
        'last_cleanup': last['cleanup'],
        'stale': stale,
    }


def _log_status_change(conn, device_id, status, reason=''):
    try:
        conn.execute('''
            INSERT INTO device_status_log (device_id, status, reason, created_at)
            VALUES (?, ?, ?, ?)
        ''', (device_id, status, reason, get_wib_time()))
    except Exception as e:
        logger.error(f"Failed to log status change: {e}")


def _compute_offline_timeout(device, config):
    """Hitung offline timeout efektif.

    Prioritas:
      1. offline_timeout manual (jika di-set user)
      2. auto = 2x expected_interval (auto-detected)
      3. fallback: config.OFFLINE_TIMEOUT
    """
    manual = device['offline_timeout']
    if manual is not None and manual > 0:
        return manual

    interval = device['expected_interval']
    if interval is not None and interval > 0:
        return max(10, interval * 2)

    return config.OFFLINE_TIMEOUT


def check_device_status():
    config = get_config()
    logger.info(f"Status checker started (interval={config.CHECK_INTERVAL}s, "
                f"fallback_timeout={config.OFFLINE_TIMEOUT}s)")

    while not shutdown_event.is_set():
        try:
            current_time = get_wib_time()
            to_offline = []   # (device_id, severity)
            to_online = []    # device_id

            with get_db_context() as conn:
                devices = conn.execute('''
                    SELECT device_id, last_seen, status,
                           offline_timeout, expected_interval,
                           offline_alert_severity
                    FROM devices
                ''').fetchall()

                for device in devices:
                    device_id = device['device_id']
                    last_seen = device['last_seen']
                    current_status = device['status']

                    timeout = _compute_offline_timeout(device, config)
                    severity = device['offline_alert_severity'] or config.DEFAULT_OFFLINE_SEVERITY

                    if not last_seen:
                        if current_status != 'offline':
                            conn.execute('UPDATE devices SET status = ? WHERE device_id = ?',
                                         ('offline', device_id))
                            _log_status_change(conn, device_id, 'offline', 'never_seen')
                        continue

                    last_seen_dt = parse_datetime(last_seen)
                    if not last_seen_dt:
                        continue

                    time_diff = (current_time - last_seen_dt).total_seconds()

                    if time_diff > timeout and current_status != 'offline':
                        conn.execute('UPDATE devices SET status = ? WHERE device_id = ?',
                                     ('offline', device_id))
                        _log_status_change(conn, device_id, 'offline',
                                           f'timeout_{int(time_diff)}s')
                        logger.info(f"Device {device_id} OFFLINE (timeout={timeout}s)")
                        to_offline.append((device_id, severity))

                    elif time_diff <= timeout and current_status == 'offline':
                        conn.execute('UPDATE devices SET status = ? WHERE device_id = ?',
                                     ('online', device_id))
                        _log_status_change(conn, device_id, 'online', 'recovered')
                        logger.info(f"Device {device_id} back online")
                        to_online.append(device_id)

                    elif current_status == 'offline' and time_diff > timeout:
                        raised = conn.execute('''
                            SELECT 1 FROM alert_history
                            WHERE device_id = ? AND alert_type = 'offline'
                              AND action IN ('created', 'acknowledged')
                              AND created_at >= ?
                            LIMIT 1
                        ''', (device_id, last_seen)).fetchone()
                        if not raised:
                            to_offline.append((device_id, severity))

                conn.commit()

            for device_id, severity in to_offline:
                try:
                    create_offline_alert(device_id, severity)
                except Exception as e:
                    logger.error(f"Failed to create offline alert: {e}", exc_info=True)

            for device_id in to_online:
                try:
                    clear_offline_alert(device_id)
                except Exception as e:
                    logger.error(f"Failed to clear offline alert: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Status checker error: {e}", exc_info=True)

        record_heartbeat('status_check')
        shutdown_event.wait(config.CHECK_INTERVAL)

    logger.info("Status checker stopped")


def cleanup_old_data():
    """Cleanup data lama di 4 tabel dengan retention berbeda."""
    config = get_config()
    retention_sensor = config.DATA_RETENTION_DAYS
    retention_history = config.ALERT_HISTORY_RETENTION_DAYS
    retention_log = config.STATUS_LOG_RETENTION_DAYS

    logger.info(
        f"Data cleanup started "
        f"(sensor={retention_sensor}d, history={retention_history}d, "
        f"status_log={retention_log}d)"
    )

    if shutdown_event.wait(300):
        logger.info("Data cleanup stopped (early shutdown)")
        return

    while not shutdown_event.is_set():
        try:
            now = get_wib_time()
            cutoff_sensor = now - timedelta(days=retention_sensor)
            cutoff_history = now - timedelta(days=retention_history)
            cutoff_log = now - timedelta(days=retention_log)

            with get_db_context() as conn:
                total_deleted = 0
                results = {}

                r = conn.execute(
                    'DELETE FROM sensor_data WHERE timestamp < ?',
                    (cutoff_sensor,)
                )
                results['sensor_data'] = r.rowcount
                total_deleted += r.rowcount

                r = conn.execute(
                    'DELETE FROM alert_history WHERE created_at < ?',
                    (cutoff_history,)
                )
                results['alert_history'] = r.rowcount
                total_deleted += r.rowcount

                r = conn.execute(
                    'DELETE FROM device_status_log WHERE created_at < ?',
                    (cutoff_log,)
                )
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

                if total_deleted > 0:
                    details = ', '.join(
                        f"{k}={v}" for k, v in results.items() if v > 0
                    )
                    logger.info(f"Cleaned up {total_deleted} records: {details}")

                if total_deleted > 1000:
                    logger.info("Running VACUUM to reclaim space...")
                    conn.execute('VACUUM')
                    logger.info("VACUUM complete")

        except Exception as e:
            logger.error(f"Cleanup error: {e}", exc_info=True)

        record_heartbeat('cleanup')
        shutdown_event.wait(CLEANUP_INTERVAL)

    logger.info("Data cleanup stopped")


def create_backup_file(backup_dir, db_path, prefix='iot'):
    """Buat backup konsisten (sqlite backup API). Nama file memakai waktu WIB.

    Return path file backup.
    """
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = get_wib_time().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(backup_dir, f'{prefix}_{timestamp}.db')

    source = sqlite3.connect(db_path, timeout=30.0)
    dest = sqlite3.connect(backup_path)
    try:
        with dest:
            source.backup(dest)
    finally:
        dest.close()
        source.close()
    return backup_path


def prune_backups(backup_dir, retention_days, min_keep, now=None):
    """Hapus backup otomatis yang kedaluwarsa.

    Aturan keselamatan:
      - hanya file yang cocok AUTO_BACKUP_PATTERNS (iot_*, pre-delete_*, pre-restore-*)
        yang boleh dihapus; file manual dan file lain tidak pernah disentuh;
      - `min_keep` backup terbaru selalu dipertahankan walau sudah lewat retensi.
    Return daftar nama file yang dihapus.
    """
    now = time.time() if now is None else now
    cutoff = now - retention_days * 86400
    min_keep = max(0, int(min_keep))

    candidates = []
    for name in os.listdir(backup_dir):
        path = os.path.join(backup_dir, name)
        if _matches_backup_pattern(name, AUTO_BACKUP_PATTERNS) and os.path.isfile(path):
            candidates.append((os.path.getmtime(path), name, path))
    candidates.sort(reverse=True)          # terbaru dulu

    removed = []
    for mtime, name, path in candidates[min_keep:]:
        if mtime < cutoff:
            os.remove(path)
            removed.append(name)
            logger.info(f"Old backup removed: {name}")
    return removed


def seconds_until_next_backup(backup_dir, interval_hours, now=None):
    """0 bila backup sudah jatuh tempo (atau belum ada), selain itu sisa detik.

    Jatuh tempo = backup terjadwal (`iot_*.db`) terbaru lebih tua dari min(interval, 24 jam), jadi
    setelah restart tidak ada backup ganda, dan tidak menunggu tanpa syarat.
    """
    now = time.time() if now is None else now
    interval = min(max(1, interval_hours) * 3600, 86400)
    newest = None
    try:
        for name in os.listdir(backup_dir):
            path = os.path.join(backup_dir, name)
            if _matches_backup_pattern(name, SCHEDULED_BACKUP_PATTERNS) and os.path.isfile(path):
                mt = os.path.getmtime(path)
                newest = mt if newest is None else max(newest, mt)
    except OSError:
        return 0
    if newest is None:
        return 0
    return max(0, int(newest + interval - now))


def backup_database():
    config = get_config()
    if not config.BACKUP_ENABLED:
        logger.info("Backup disabled")
        return

    logger.info(f"Backup started (interval={config.BACKUP_INTERVAL_HOURS}h, "
                f"retention={config.BACKUP_RETENTION_DAYS}d, min_keep={config.BACKUP_MIN_KEEP})")

    # Jeda kecil agar boot tidak terbebani; setelah itu backup langsung bila jatuh tempo.
    if shutdown_event.wait(BACKUP_STARTUP_DELAY):
        logger.info("Backup task stopped (early shutdown)")
        return

    first = True
    while not shutdown_event.is_set():
        wait_s = config.BACKUP_INTERVAL_HOURS * 3600
        try:
            due_in = seconds_until_next_backup(
                config.BACKUP_DIR, config.BACKUP_INTERVAL_HOURS) if first else 0
            first = False
            if due_in > 0:
                logger.info(f"Backup terakhir masih baru, backup berikutnya {due_in}s lagi")
                wait_s = due_in
            else:
                backup_path = create_backup_file(config.BACKUP_DIR, config.DB_PATH)
                size_mb = os.path.getsize(backup_path) / (1024 * 1024)
                logger.info(f"Backup created: {backup_path} ({size_mb:.2f} MB)")
                prune_backups(config.BACKUP_DIR, config.BACKUP_RETENTION_DAYS,
                              config.BACKUP_MIN_KEEP)
        except Exception as e:
            logger.error(f"Backup failed: {e}", exc_info=True)
        record_heartbeat('backup')
        shutdown_event.wait(wait_s)

    logger.info("Backup task stopped")


def _acquire_background_lock():
    """Coba ambil lock proses ini. Return True jika berhasil (kompatibel dengan versi lama)."""
    config = get_config()
    if not config.BACKGROUND_TASKS_ENABLED:
        logger.info("Background tasks disabled via BACKGROUND_TASKS_ENABLED=False")
        return False
    if _lock.held:
        logger.info("Background lock already held by this process")
        return False
    if _lock.try_acquire():
        logger.info(f"Background lock acquired (pid={os.getpid()})")
        return True
    logger.info(f"Background lock dipegang worker lain; akan dicoba lagi tiap "
                f"{LOCK_RETRY_SECONDS} detik")
    return False


def _start_task_threads():
    threads = []
    for target, name in [
        (check_device_status, 'status-checker'),
        (cleanup_old_data, 'data-cleanup'),
        (backup_database, 'db-backup'),
    ]:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        threads.append(t)
    logger.info(f"Started {len(threads)} background tasks (this worker owns the lock)")
    return threads


def start_background_tasks():
    global shutdown_event

    with _bg_lock:
        shutdown_event = threading.Event()

    config = get_config()
    if not config.BACKGROUND_TASKS_ENABLED:
        logger.info("Background tasks disabled via BACKGROUND_TASKS_ENABLED=False")
        return []

    if _acquire_background_lock():
        return _start_task_threads()

    # Lock dipegang worker lain: pantau, ambil alih bila pemegangnya mati.
    stop_event = shutdown_event
    watcher = threading.Thread(
        target=wait_for_lock,
        args=(_lock, stop_event, _start_task_threads),
        name='bg-lock-watcher', daemon=True,
    )
    watcher.start()
    return [watcher]


def stop_background_tasks():
    logger.info("Stopping background tasks...")
    shutdown_event.set()
    _lock.release()
