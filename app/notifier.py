"""
NEXUS IoT - Telegram Notification Dispatcher (native async FastAPI)
"""
import asyncio
import hashlib
import html
import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_config
from app.database import get_db_context
from app.workspace import get_dashboard_telegram

logger = logging.getLogger('nexus')
WIB = timezone(timedelta(hours=7))

_notify_queue = None  # asyncio.Queue, dibuat lazily di event loop aktif
_worker_task = None
_recent_notifications = {}
DEDUP_WINDOW_SECONDS = 60

SEVERITY_EMOJI = {'info': 'ℹ️', 'warning': '⚠️', 'danger': '🔥', 'healthy': '✅'}
SEVERITY_LABEL = {'info': 'INFO', 'warning': 'PERINGATAN', 'danger': 'BAHAYA', 'healthy': 'NORMAL'}
ACTION_LABEL = {'created': 'ALERT BARU', 'severity_changed': 'PERUBAHAN SEVERITY', 'cleared': 'ALERT SELESAI'}


def _esc(value):
    """Escape nilai dinamis untuk parse_mode HTML Telegram (&, <, >)."""
    return html.escape(str(value), quote=False)


def _format_message(event, html_mode=True):
    """Susun teks notifikasi.

    html_mode=True  -> HTML Telegram: semua nilai dinamis di-escape, <b>/<code> dipakai.
    html_mode=False -> teks polos tanpa tag (fallback bila Telegram menolak entitas).
    """
    severity = event.get('severity', 'info')
    action = event.get('event', 'created')
    emoji = SEVERITY_EMOJI.get(severity, '🔔')
    sev_label = SEVERITY_LABEL.get(severity, str(severity).upper())
    action_label = ACTION_LABEL.get(action, str(action).upper())

    if html_mode:
        def bold(v):
            return f"<b>{_esc(v)}</b>"

        def code(v):
            return f"<code>{_esc(v)}</code>"

        def text(v):
            return _esc(v)
    else:
        def bold(v):
            return str(v)

        def code(v):
            return str(v)

        def text(v):
            return str(v)

    if action == 'cleared':
        title = f"{emoji} {bold(action_label)}"
    elif action == 'severity_changed':
        old_raw = event.get('old_severity', '')
        old_sev = SEVERITY_LABEL.get(old_raw, old_raw or '?')
        title = f"{emoji} {bold(action_label)} — {text(sev_label)} (dari {text(old_sev)})"
    else:
        title = f"{emoji} {bold(action_label)} — {text(sev_label)}"

    lines = [
        title, "",
        f"📟 {bold('Device:')} {code(event.get('device_id', '-'))}",
        f"🏷️ {bold('Nama:')} {text(event.get('device_name', '-'))}",
    ]
    if event.get('location'):
        lines.append(f"📍 {bold('Lokasi:')} {text(event['location'])}")
    lines.append(f"🔧 {bold('Sensor:')} {code(event.get('alert_type', '-'))}")
    lines.append(f"💬 {bold('Pesan:')} {text(event.get('message', '-'))}")
    if event.get('value') is not None:
        lines.append(f"📊 {bold('Nilai:')} {code(event['value'])}")
    lines.append(f"🕐 {bold('Waktu:')} {text(event.get('timestamp', '-'))}")
    return "\n".join(lines)


def _is_parse_error(resp):
    """True bila Telegram menolak teks karena entitas/markup tidak bisa di-parse."""
    if resp.status_code != 400:
        return False
    try:
        desc = (resp.json() or {}).get('description', '')
    except ValueError:
        return False
    return "can't parse entities" in str(desc).lower()


async def _resolve_target(event):
    """Tentukan bot tujuan sebuah event.

    Return (kind, token, chat_id):
      'dashboard' : dashboard pemilik perangkat punya bot sendiri yang aktif
      'muted'     : dashboard punya konfigurasi tapi dimatikan -> jangan kirim ke mana pun
      'default'   : pakai bot dari .env (perilaku lama)
    """
    dash_id = event.get('dashboard_id')
    try:
        async with get_db_context() as conn:
            if dash_id is None and event.get('device_id'):
                cur = await conn.execute(
                    'SELECT dashboard_id FROM devices WHERE device_id = ?',
                    (event['device_id'],)
                )
                row = await cur.fetchone()
                dash_id = row['dashboard_id'] if row else None
            if dash_id is None:
                return 'default', None, None
            cfg = await get_dashboard_telegram(conn, dash_id)
    except Exception as e:
        logger.warning(f"Gagal membaca Telegram dashboard, pakai bot default: {type(e).__name__}")
        return 'default', None, None

    if not cfg:
        return 'default', None, None
    if not cfg['enabled']:
        return 'muted', None, None
    if cfg['token'] and cfg['chat_id']:
        return 'dashboard', cfg['token'], cfg['chat_id']
    return 'default', None, None


async def _send_telegram(event, token=None, chat_id=None):
    """Kirim satu event. token/chat_id kosong = pakai bot default dari .env.

    Retry 3x: 429 -> tunggu retry_after, 5xx/network -> backoff 2**attempt.
    Fallback teks polos sekali bila Telegram menolak entitas HTML.
    """
    config = get_config()
    if token is None and chat_id is None:
        if not config.TELEGRAM_ENABLED:
            return False, 'telegram_disabled'
        token = config.TELEGRAM_BOT_TOKEN
        chat_id = config.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return False, 'telegram_not_configured'

    # URL berisi token: jangan pernah di-log, dan jangan log teks exception
    # (str(e) dari httpx sering memuat URL lengkap).
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': _format_message(event),
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    }
    fell_back = False

    attempt = 0
    async with httpx.AsyncClient(timeout=10) as client:
        while attempt < 3:
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get('ok'):
                        return True, None
                    return False, f"telegram_api_error: {data.get('description')}"
                if not fell_back and _is_parse_error(resp):
                    # Fallback: kirim ulang sebagai teks polos (tanpa parse_mode).
                    logger.warning("Telegram menolak format HTML, kirim ulang sebagai teks polos")
                    payload = {
                        'chat_id': chat_id,
                        'text': _format_message(event, html_mode=False),
                        'disable_web_page_preview': True,
                    }
                    fell_back = True
                    continue  # tidak menghabiskan jatah retry
                if resp.status_code == 429:
                    retry_after = resp.json().get('parameters', {}).get('retry_after', 5)
                    await asyncio.sleep(retry_after)
                    attempt += 1
                    continue
                if 500 <= resp.status_code < 600:
                    await asyncio.sleep(2 ** attempt)
                    attempt += 1
                    continue
                return False, f"telegram_http_{resp.status_code}"
            except httpx.RequestError:
                logger.warning("Telegram request error")
                await asyncio.sleep(2 ** attempt)
                attempt += 1

    return False, 'telegram_max_retries_exceeded'


def _event_hash(event):
    key = f"{event.get('device_id')}:{event.get('alert_type')}:{event.get('severity')}:{event.get('message')}"
    return hashlib.md5(key.encode('utf-8')).hexdigest()


def _is_duplicate(event):
    import time
    h = _event_hash(event)
    now = time.time()
    expired = [k for k, t in _recent_notifications.items() if now - t > DEDUP_WINDOW_SECONDS]
    for k in expired:
        del _recent_notifications[k]
    if h in _recent_notifications:
        return True
    _recent_notifications[h] = now
    return False


def _should_notify(event):
    config = get_config()
    levels = {'info': 0, 'warning': 1, 'danger': 2}
    if event.get('event') == 'cleared':
        return config.NOTIFY_ON_CLEARED
    severity = event.get('severity', 'info')
    return levels.get(severity, 0) >= levels.get(config.NOTIFY_MIN_SEVERITY, 1)


async def _dispatch_worker():
    logger.info("Notification worker started")
    while True:
        try:
            item = await asyncio.wait_for(_notify_queue.get(), timeout=5)
        except asyncio.TimeoutError:
            continue
        if item is None:
            break
        try:
            event, target = item
            await _dispatch_one(event, target)
        except Exception as e:
            logger.error(f"Notification dispatch error: {e}", exc_info=True)
        finally:
            _notify_queue.task_done()


async def _dispatch_one(event, target=None):
    config = get_config()
    kind, token, chat_id = target or await _resolve_target(event)
    if kind == 'muted':
        return
    if kind == 'default' and not (config.NOTIFY_ENABLED and config.TELEGRAM_ENABLED):
        return
    if not _should_notify(event):
        return
    if _is_duplicate(event):
        return

    if kind == 'dashboard':
        ok, err = await _send_telegram(event, token=token, chat_id=chat_id)
    else:
        ok, err = await _send_telegram(event)
    if ok:
        logger.info(f"📨 Telegram sent ({kind}): {event.get('device_id')}/{event.get('alert_type')}")
    else:
        logger.warning(f"Telegram failed ({kind}): {err}")


def _start_worker_if_needed():
    global _notify_queue, _worker_task
    if _notify_queue is None:
        _notify_queue = asyncio.Queue(maxsize=1000)
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.get_running_loop().create_task(_dispatch_worker())


async def _enqueue(event, target):
    _start_worker_if_needed()
    try:
        _notify_queue.put_nowait((event, target))
    except asyncio.QueueFull as e:
        logger.warning(f"Notification queue full: {e}")


def notify_alert_event(event):
    """Enqueue notifikasi alert. Fire-and-forget, kompatibel sync & async caller.

    - Di dalam event loop: dijadwalkan sebagai task (worker asyncio.Queue).
    - Di luar event loop (thread sync): kirim langsung via dispatcher yang sama.
    """
    if not event:
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_dispatch_one(event))
        return

    async def _prepare_and_enqueue():
        config = get_config()
        target = await _resolve_target(event)
        kind = target[0]
        if kind == 'muted':
            return
        if kind == 'default' and not (config.NOTIFY_ENABLED and config.TELEGRAM_ENABLED):
            return
        await _enqueue(event, target)

    asyncio.get_running_loop().create_task(_prepare_and_enqueue())


async def send_test_notification(token=None, chat_id=None):
    """Kirim pesan tes. Dengan token+chat_id = tes bot sebuah dashboard; tanpa = bot default."""
    event = {
        'event': 'created',
        'device_id': 'TEST-DEVICE',
        'device_name': 'Test Notification',
        'location': 'Test Location',
        'alert_type': 'temperature',
        'severity': 'info',
        'old_severity': None,
        'message': 'Ini pesan test dari NEXUS IoT.',
        'value': 25.5,
        'timestamp': datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S WIB'),
    }
    if token and chat_id:
        ok, err = await _send_telegram(event, token=token, chat_id=chat_id)
        return {'telegram': {'success': ok, 'error': err}}

    config = get_config()
    results = {}
    if config.TELEGRAM_ENABLED:
        ok, err = await _send_telegram(event)
        results['telegram'] = {'success': ok, 'error': err}
    if not results:
        results['_info'] = {
            'success': False,
            'error': 'Telegram not enabled. Set TELEGRAM_ENABLED=True di .env'
        }
    return results


def get_notification_status():
    config = get_config()
    return {
        'notify_enabled': config.NOTIFY_ENABLED,
        'min_severity': config.NOTIFY_MIN_SEVERITY,
        'notify_on_cleared': config.NOTIFY_ON_CLEARED,
        'telegram': {
            'enabled': config.TELEGRAM_ENABLED,
            'has_token': bool(config.TELEGRAM_BOT_TOKEN),
            'has_chat_id': bool(config.TELEGRAM_CHAT_ID),
        },
    }
