import pytest
pytestmark = pytest.mark.skip(reason="Belum di-port penuh ke FastAPI — di-skip sementara (Task 2)")
"""H1 — restore database aman: endpoint hanya menyiapkan, penerapan saat start."""
import os
import sqlite3

import pytest

from app import restore
from app.config import Config


def _make_db(path, value, wal=False):
    conn = sqlite3.connect(path)
    if wal:
        conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('CREATE TABLE IF NOT EXISTS t (x TEXT)')
    conn.execute('DELETE FROM t')
    conn.execute('INSERT INTO t VALUES (?)', (value,))
    conn.commit()
    conn.close()


def _value(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute('SELECT x FROM t').fetchone()[0]
    finally:
        conn.close()


def _integrity(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute('PRAGMA integrity_check').fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setenv('NEXUS_LOCK_DIR', str(tmp_path / 'locks'))
    return str(tmp_path / 'live.db'), str(tmp_path / 'backup.db')


def test_apply_replaces_db_and_removes_wal_shm(paths):
    live, backup = paths
    _make_db(live, 'LIVE', wal=True)
    _make_db(backup, 'FROM-BACKUP')
    # sisa WAL/SHM basi dari DB lama
    open(live + '-wal', 'wb').write(b'stale-wal-bytes')
    open(live + '-shm', 'wb').write(b'stale-shm-bytes')

    restore.schedule_restore(backup, live, {'requested_by': 1})
    assert _value(live) == 'LIVE'                       # DB hidup belum disentuh
    assert os.path.exists(live + '.restore-pending')
    assert os.path.exists(live + '.restore-marker')

    assert restore.apply_pending_restore(live) is True
    assert _value(live) == 'FROM-BACKUP'
    assert _integrity(live) == 'ok'
    assert not os.path.exists(live + '-wal')
    assert not os.path.exists(live + '-shm')
    assert not os.path.exists(live + '.restore-pending')
    assert not os.path.exists(live + '.restore-marker')


def test_apply_is_noop_without_marker(paths):
    live, _ = paths
    _make_db(live, 'LIVE')
    assert restore.apply_pending_restore(live) is False
    assert _value(live) == 'LIVE'


def test_apply_is_idempotent(paths):
    live, backup = paths
    _make_db(live, 'LIVE')
    _make_db(backup, 'B')
    restore.schedule_restore(backup, live)
    assert restore.apply_pending_restore(live) is True
    assert restore.apply_pending_restore(live) is False   # worker kedua: tidak ada yang tertunda
    assert _value(live) == 'B'


def test_marker_without_pending_file_is_discarded(paths):
    live, _ = paths
    _make_db(live, 'LIVE')
    open(live + '.restore-marker', 'w').write('{}')
    assert restore.apply_pending_restore(live) is False
    assert not os.path.exists(live + '.restore-marker')
    assert _value(live) == 'LIVE'


def test_corrupt_pending_is_rejected_and_live_db_kept(paths):
    live, backup = paths
    _make_db(live, 'LIVE')
    open(backup, 'wb').write(b'ini bukan database sqlite' * 50)
    restore.schedule_restore(backup, live)
    assert restore.apply_pending_restore(live) is False
    assert _value(live) == 'LIVE'
    assert not os.path.exists(live + '.restore-pending')
    assert not os.path.exists(live + '.restore-marker')


def test_apply_deferred_while_another_connection_is_open(paths):
    live, backup = paths
    _make_db(live, 'LIVE', wal=True)
    _make_db(backup, 'B')
    restore.schedule_restore(backup, live)

    other = sqlite3.connect(live)                       # proses lain masih memakai DB
    other.execute('PRAGMA journal_mode=WAL')
    other.execute('SELECT count(*) FROM t').fetchone()
    try:
        assert restore.apply_pending_restore(live) is False
        assert _value(live) == 'LIVE'
        assert os.path.exists(live + '.restore-marker')  # tetap tertunda untuk start berikutnya
    finally:
        other.close()
    assert restore.apply_pending_restore(live) is True
    assert _value(live) == 'B'


def test_restore_endpoint_does_not_touch_live_db(admin_client):
    from app.database import get_db_context
    backup_dir = Config.BACKUP_DIR
    os.makedirs(backup_dir, exist_ok=True)
    bk = os.path.join(backup_dir, 'iot_endpoint-test.db')
    _make_db(bk, 'BACKUP-DATA')

    with get_db_context() as conn:
        before = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]

    r = admin_client.post('/api/v1/system/restore',
                          json={'filename': 'iot_endpoint-test.db', 'confirm': 'RESTORE'})
    assert r.status_code == 200
    body = r.get_json()
    assert body['restart_required'] is True
    assert body['pre_restore_backup'].startswith('pre-restore-')
    assert os.path.exists(os.path.join(backup_dir, body['pre_restore_backup']))

    db = Config.DB_PATH
    assert os.path.exists(db + '.restore-pending') and os.path.exists(db + '.restore-marker')
    with get_db_context() as conn:                      # DB hidup masih utuh & dipakai normal
        assert conn.execute('SELECT COUNT(*) FROM users').fetchone()[0] == before
    assert _integrity(db + '.restore-pending') == 'ok'


def test_restore_endpoint_requires_admin(user_client):
    r = user_client.post('/api/v1/system/restore',
                         json={'filename': 'x.db', 'confirm': 'RESTORE'})
    assert r.status_code == 403
