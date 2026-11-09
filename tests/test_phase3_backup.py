import pytest
pytestmark = pytest.mark.skip(reason="Belum di-port penuh ke FastAPI — di-skip sementara (Task 2)")
"""M3 — retensi backup aman."""
import os
import re
import sqlite3
import time

from app import background

DAY = 86400


def _touch(path, age_days, now):
    path.write_bytes(b'x')
    ts = now - age_days * DAY
    os.utime(path, (ts, ts))


def test_prune_removes_old_auto_backups_but_keeps_manual(tmp_path):
    now = time.time()
    for name, age in [('iot_old.db', 10), ('iot_new1.db', 0), ('iot_new2.db', 1),
                      ('iot_new3.db', 2), ('pre-restore-x.db', 10),
                      ('pre-delete_old.db', 10), ('manual.txt', 10)]:
        _touch(tmp_path / name, age, now)
    removed = background.prune_backups(str(tmp_path), retention_days=7, min_keep=3, now=now)
    # Backup otomatis (iot_*, pre-delete_*, pre-restore-*) ikut dibersihkan,
    # file manual tidak pernah disentuh.
    assert set(removed) == {'iot_old.db', 'pre-restore-x.db', 'pre-delete_old.db'}
    left = sorted(os.listdir(tmp_path))
    assert 'manual.txt' in left
    assert {'iot_new1.db', 'iot_new2.db', 'iot_new3.db'} <= set(left)  # 3 terbaru


def test_prune_never_goes_below_min_keep(tmp_path):
    now = time.time()
    for i, age in enumerate([20, 15, 12, 30]):
        _touch(tmp_path / f'iot_{i}.db', age, now)
    removed = background.prune_backups(str(tmp_path), retention_days=7, min_keep=3, now=now)
    assert len(removed) == 1 and removed == ['iot_3.db']      # hanya yang terlama
    assert len([n for n in os.listdir(tmp_path) if n.startswith('iot_')]) == 3


def test_prune_removes_very_old_pre_restore_when_no_min_keep(tmp_path):
    # Perubahan kebijakan: pre-restore_* dibuat otomatis, jadi ikut di-prune
    # (sebelumnya dibiarkan selamanya sehingga disk bisa penuh).
    now = time.time()
    _touch(tmp_path / 'pre-restore-20200101_000000.db', 2000, now)
    assert background.prune_backups(str(tmp_path), 7, 0, now=now) == [
        'pre-restore-20200101_000000.db']
    assert not (tmp_path / 'pre-restore-20200101_000000.db').exists()


def test_first_backup_is_immediate_when_none_exists(tmp_path):
    assert background.seconds_until_next_backup(str(tmp_path), 24) == 0


def test_no_duplicate_backup_when_recent_exists(tmp_path):
    now = time.time()
    _touch(tmp_path / 'iot_recent.db', 0.1, now)           # ~2,4 jam lalu
    wait = background.seconds_until_next_backup(str(tmp_path), 24, now=now)
    assert 0 < wait <= DAY


def test_backup_due_when_latest_is_older_than_interval(tmp_path):
    now = time.time()
    _touch(tmp_path / 'iot_stale.db', 2, now)
    assert background.seconds_until_next_backup(str(tmp_path), 24, now=now) == 0


def test_create_backup_file_uses_wib_name_and_valid_db(tmp_path):
    src = tmp_path / 'src.db'
    conn = sqlite3.connect(src)
    conn.execute('CREATE TABLE t (x INTEGER)')
    conn.execute('INSERT INTO t VALUES (7)')
    conn.commit()
    conn.close()
    path = background.create_backup_file(str(tmp_path / 'bk'), str(src))
    assert re.match(r'^iot_\d{8}_\d{6}\.db$', os.path.basename(path))
    c = sqlite3.connect(path)
    assert c.execute('SELECT x FROM t').fetchone()[0] == 7
    assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    c.close()
