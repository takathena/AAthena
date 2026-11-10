"""
AAguard IoT - Throttle percobaan login gagal.

Disimpan di tabel `login_failures` (SQLite) supaya konsisten antar worker Gunicorn.
Dua kunci dihitung terpisah:
  - 'u:<username>|<ip>' : tebakan password untuk satu akun dari satu IP
  - 'ip:<ip>'           : password spraying (banyak username) dari satu IP
Sengaja TIDAK ada kunci per-akun-saja: penyerang dari IP lain tidak boleh bisa
mengunci admin yang sah.
"""
import time

from app.database import get_db_context


def _keys(username, ip):
    uname = (username or '').strip().lower()[:64]
    ip = (ip or 'unknown')[:64]
    return f"u:{uname}|{ip}", f"ip:{ip}"


def check_locked(username, ip, now=None):
    """Return sisa detik lockout (>0) bila diblokir, selain itu 0."""
    now = time.time() if now is None else now
    remaining = 0
    with get_db_context() as conn:
        for key in _keys(username, ip):
            row = conn.execute(
                'SELECT locked_until FROM login_failures WHERE key = ?', (key,)
            ).fetchone()
            if row and row['locked_until'] and row['locked_until'] > now:
                remaining = max(remaining, int(row['locked_until'] - now) + 1)
    return remaining


def record_failure(username, ip, config, now=None):
    """Catat satu kegagalan; kunci bila melewati ambang. Atomik antar worker."""
    now = time.time() if now is None else now
    window = config.LOGIN_FAIL_WINDOW_SECONDS
    lockout = config.LOGIN_LOCKOUT_SECONDS
    limits = (config.LOGIN_MAX_FAILURES, config.LOGIN_IP_MAX_FAILURES)

    with get_db_context() as conn:
        for key, limit in zip(_keys(username, ip), limits):
            conn.execute('''
                INSERT INTO login_failures (key, fail_count, window_start, locked_until)
                VALUES (?, 1, ?, 0)
                ON CONFLICT(key) DO UPDATE SET
                    fail_count = CASE WHEN ? - window_start > ? THEN 1 ELSE fail_count + 1 END,
                    window_start = CASE WHEN ? - window_start > ? THEN ? ELSE window_start END
            ''', (key, now, now, window, now, window, now))
            row = conn.execute(
                'SELECT fail_count FROM login_failures WHERE key = ?', (key,)
            ).fetchone()
            if row and row['fail_count'] >= limit:
                conn.execute(
                    'UPDATE login_failures SET locked_until = ?, fail_count = 0, window_start = ? '
                    'WHERE key = ?', (now + lockout, now, key))
        # Bersihkan baris basi secara oportunistik
        conn.execute(
            'DELETE FROM login_failures WHERE locked_until < ? AND window_start < ?',
            (now, now - max(window, lockout) * 2))
        conn.commit()


def clear_failures(username, ip):
    """Login berhasil: reset hitungan akun+IP (hitungan IP-saja tetap, agar spraying tetap terlihat)."""
    user_key, _ = _keys(username, ip)
    with get_db_context() as conn:
        conn.execute('DELETE FROM login_failures WHERE key = ?', (user_key,))
        conn.commit()
