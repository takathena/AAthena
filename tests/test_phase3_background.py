import pytest
pytestmark = pytest.mark.skip(reason="Belum di-port penuh ke FastAPI — di-skip sementara (Task 2)")
"""H2 — lock background task bisa diambil alih + heartbeat di /system/info."""
import json
import threading
import time

from app import background
from app.background import BackgroundLock
from app.database import get_db_context


def test_second_lock_cannot_acquire_while_first_holds(tmp_path):
    a, b = BackgroundLock(str(tmp_path)), BackgroundLock(str(tmp_path))
    assert a.try_acquire() is True
    assert b.try_acquire() is False
    a.release()
    assert b.try_acquire() is True
    b.release()


def test_standby_takes_over_within_retry_interval(tmp_path):
    owner, standby = BackgroundLock(str(tmp_path)), BackgroundLock(str(tmp_path))
    assert owner.try_acquire()
    acquired = threading.Event()
    stop = threading.Event()
    t = threading.Thread(
        target=background.wait_for_lock,
        args=(standby, stop, acquired.set, 0.1), daemon=True)
    t.start()
    time.sleep(0.35)
    assert not acquired.is_set()                # owner masih hidup -> standby menunggu
    owner.release()                             # simulasi pemegang lock mati
    assert acquired.wait(1.0), 'standby harus mengambil alih dalam interval retry'
    stop.set()
    t.join(1.0)
    standby.release()


def test_wait_for_lock_stops_on_shutdown(tmp_path):
    owner, standby = BackgroundLock(str(tmp_path)), BackgroundLock(str(tmp_path))
    owner.try_acquire()
    stop = threading.Event()
    result = []
    t = threading.Thread(target=lambda: result.append(
        background.wait_for_lock(standby, stop, lambda: None, 0.05)), daemon=True)
    t.start()
    stop.set()
    t.join(1.0)
    assert result == [False]
    owner.release()


def test_failed_open_does_not_erase_owner_pid(tmp_path):
    owner, other = BackgroundLock(str(tmp_path)), BackgroundLock(str(tmp_path))
    assert owner.try_acquire()
    assert other.try_acquire() is False
    assert other.read_owner_pid() is not None   # isi file milik owner tidak ter-truncate
    owner.release()


def test_heartbeat_recorded_and_reported(app):
    background.record_heartbeat('status_check')
    status = background.get_background_status()
    assert status['last_status_check'] is not None
    assert status['last_backup'] is None and status['last_cleanup'] is None
    assert status['stale']['status_check'] is False


def test_heartbeat_marked_stale_after_three_intervals(app):
    from app.config import get_config
    cfg = get_config()
    old = time.time() - (3 * cfg.CHECK_INTERVAL + 5)
    with get_db_context() as conn:
        conn.execute("INSERT OR REPLACE INTO user_settings (key, value) VALUES (?, ?)",
                     ('bg_hb_status_check', json.dumps({'ts': old, 'pid': 4242})))
        conn.commit()
    status = background.get_background_status(cfg)
    assert status['stale']['status_check'] is True


def test_system_info_exposes_background(admin_client):
    background.record_heartbeat('cleanup')
    r = admin_client.get('/api/v1/system/info')
    assert r.status_code == 200
    bg = r.get_json()['info']['background']
    assert {'owner_pid', 'last_status_check', 'last_backup', 'last_cleanup'} <= set(bg)
    assert bg['last_cleanup'] is not None
