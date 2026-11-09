"""
NEXUS IoT - Restore database yang aman.

Endpoint restore TIDAK menimpa DB yang sedang hidup. Ia hanya menyiapkan:
    <DB_PATH>.restore-pending   salinan backup yang sudah diverifikasi
    <DB_PATH>.restore-marker    penanda (JSON) bahwa restore harus diterapkan

Penerapan dilakukan saat proses start (apply_pending_restore), sebelum koneksi
database mana pun dibuka: hapus -wal/-shm, ganti DB, hapus penanda.
"""
import json
import logging
import os
import shutil
import sqlite3
import time

from app.utils import process_lock

logger = logging.getLogger('nexus')

PENDING_SUFFIX = '.restore-pending'
MARKER_SUFFIX = '.restore-marker'


def pending_paths(db_path):
    return db_path + PENDING_SUFFIX, db_path + MARKER_SUFFIX


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def schedule_restore(backup_path, db_path, meta=None):
    """Salin backup ke file pending (atomik) lalu tulis penanda. Tidak menyentuh DB hidup."""
    pending, marker = pending_paths(db_path)
    os.makedirs(os.path.dirname(db_path) or '.', exist_ok=True)

    tmp = pending + '.tmp'
    try:
        shutil.copy2(backup_path, tmp)
        os.replace(tmp, pending)          # atomik di filesystem yang sama
    finally:
        _remove(tmp)

    info = {'source': os.path.basename(backup_path), 'requested_at': time.time()}
    info.update(meta or {})
    tmp_marker = marker + '.tmp'
    with open(tmp_marker, 'w') as fh:
        json.dump(info, fh)
    os.replace(tmp_marker, marker)
    return pending, marker


def _integrity_ok(path):
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=5.0)
        row = conn.execute('PRAGMA integrity_check').fetchone()
        return bool(row) and row[0] == 'ok'
    except sqlite3.Error:
        return False
    finally:
        if conn is not None:
            conn.close()


def _db_in_use(db_path):
    """True bila proses lain masih membuka DB (mengganti DB saat itu berbahaya).

    Probe: minta locking_mode=EXCLUSIVE lalu baca. Bila ada koneksi lain pada DB WAL,
    pembacaan gagal dengan 'database is locked'.
    """
    if not os.path.exists(db_path):
        return False
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=0.5)
        conn.execute('PRAGMA locking_mode=EXCLUSIVE')
        conn.execute('SELECT count(*) FROM sqlite_master').fetchone()
        conn.execute('BEGIN EXCLUSIVE')
        conn.execute('ROLLBACK')
        return False
    except sqlite3.OperationalError as e:
        # 'database is locked' → proses lain masih membuka DB, ganti DB berbahaya.
        # Error lain (mis. 'database disk image is malformed') berarti DB rusak,
        # BUKAN sedang dipakai — restore justru harus tetap boleh dijalankan.
        if 'locked' in str(e).lower():
            return True
        logger.warning(f"_db_in_use: OperationalError non-lock pada {db_path}: {e}")
        return False
    finally:
        if conn is not None:
            conn.close()


def apply_pending_restore(db_path, log=None):
    """Terapkan restore yang tertunda. Panggil SEBELUM koneksi DB mana pun dibuka.

    Return True bila DB diganti. False bila tidak ada yang tertunda / ditunda / dibatalkan.
    Aman dipanggil bersamaan oleh banyak worker (process_lock + cek ulang di dalam lock).
    """
    log = log or logger
    pending, marker = pending_paths(db_path)
    if not os.path.exists(marker):
        return False

    with process_lock('db-restore', blocking=True) as got:
        if not got:
            return False
        if not os.path.exists(marker):          # worker lain sudah menerapkan
            return False

        if not os.path.exists(pending):
            log.warning("Penanda restore ada tapi file pending tidak ada; penanda dibuang")
            _remove(marker)
            return False

        if not _integrity_ok(pending):
            log.error("File restore pending gagal integrity_check; restore dibatalkan "
                      "(DB lama tidak diubah)")
            _remove(pending)
            _remove(marker)
            return False

        if _db_in_use(db_path):
            log.warning("Restore ditunda: database masih dipakai proses lain. "
                        "Hentikan SEMUA proses lalu start ulang agar restore diterapkan.")
            return False

        _remove(db_path + '-wal')
        _remove(db_path + '-shm')
        os.replace(pending, db_path)
        _remove(marker)
        log.warning(f"RESTORE DITERAPKAN saat start: {db_path} diganti dari backup")
        return True
