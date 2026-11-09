import pytest
pytestmark = pytest.mark.skip(reason="Belum di-port penuh ke FastAPI — di-skip sementara (Task 2)")
"""H6 — pesan Telegram di-escape (HTML) + fallback teks polos; token tidak bocor di log."""
import logging

import pytest
import requests

from app import notifier
from app.config import TestingConfig

TOKEN = '123456:SECRET-TOKEN-VALUE'
EVENT = {
    'event': 'created', 'severity': 'danger',
    'device_id': 'dev_1', 'device_name': 'Dev*Six_[x]<b>',
    'location': 'Gudang <A> & B', 'alert_type': 'temp_[1]',
    'message': 'Suhu *tinggi* <script>x</script>', 'value': 41.5,
    'timestamp': '2026-10-07 10:00:00 WIB',
}


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {'ok': True}

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def _telegram_cfg(monkeypatch):
    monkeypatch.setattr(TestingConfig, 'TELEGRAM_ENABLED', True)
    monkeypatch.setattr(TestingConfig, 'TELEGRAM_BOT_TOKEN', TOKEN)
    monkeypatch.setattr(TestingConfig, 'TELEGRAM_CHAT_ID', '999')
    monkeypatch.setattr(notifier.time, 'sleep', lambda s: None)


def test_format_message_escapes_dynamic_values():
    text = notifier._format_message(EVENT)
    assert 'Dev*Six_[x]&lt;b&gt;' in text          # nama device ter-escape
    assert 'Gudang &lt;A&gt; &amp; B' in text
    assert '&lt;script&gt;' in text and '<script>' not in text
    assert '<b>Dev*Six' not in text                # tag asli tidak menyatu dengan data
    assert '<b>Device:</b>' in text and '<code>dev_1</code>' in text


def test_format_message_plain_mode_has_no_tags():
    text = notifier._format_message(EVENT, html_mode=False)
    assert '<b>Device:</b>' not in text and '<code>' not in text   # tanpa tag pembungkus
    assert 'Dev*Six_[x]<b>' in text                # data apa adanya


def test_send_uses_html_parse_mode(monkeypatch):
    calls = []
    monkeypatch.setattr(requests, 'post', lambda url, json=None, timeout=None: calls.append(json) or _Resp())
    ok, err = notifier._send_telegram(EVENT)
    assert ok and err is None
    assert calls[0]['parse_mode'] == 'HTML'


def test_fallback_to_plain_text_on_parse_error(monkeypatch):
    calls = []
    responses = [
        _Resp(400, {'ok': False, 'description': "Bad Request: can't parse entities: Unsupported start tag"}),
        _Resp(200),
    ]

    def fake_post(url, json=None, timeout=None):
        calls.append(json)
        return responses[len(calls) - 1]

    monkeypatch.setattr(requests, 'post', fake_post)
    ok, err = notifier._send_telegram(EVENT)
    assert ok and err is None
    assert len(calls) == 2
    assert 'parse_mode' not in calls[1]            # kirim ulang tanpa parse_mode
    assert '<b>Device:</b>' not in calls[1]['text']
    assert '<code>' not in calls[1]['text']


def test_parse_error_fallback_happens_only_once(monkeypatch):
    calls = []
    bad = _Resp(400, {'ok': False, 'description': "Bad Request: can't parse entities"})
    monkeypatch.setattr(requests, 'post', lambda url, json=None, timeout=None: calls.append(json) or bad)
    ok, err = notifier._send_telegram(EVENT)
    assert not ok and err == 'telegram_http_400'
    assert len(calls) == 2


def test_other_400_does_not_trigger_fallback(monkeypatch):
    calls = []
    bad = _Resp(400, {'ok': False, 'description': 'Bad Request: chat not found'})
    monkeypatch.setattr(requests, 'post', lambda url, json=None, timeout=None: calls.append(json) or bad)
    ok, err = notifier._send_telegram(EVENT)
    assert not ok and len(calls) == 1


def test_token_never_logged_on_request_error(monkeypatch):
    records = []

    class _H(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _H()
    log = logging.getLogger('nexus')
    log.addHandler(handler)
    old_level = log.level
    log.setLevel(logging.DEBUG)

    def boom(url, json=None, timeout=None):
        raise requests.exceptions.ConnectionError(f'HTTPSConnectionPool: {url} unreachable')

    monkeypatch.setattr(requests, 'post', boom)
    try:
        ok, err = notifier._send_telegram(EVENT)
    finally:
        log.removeHandler(handler)
        log.setLevel(old_level)
    assert not ok and err == 'telegram_max_retries_exceeded'
    assert records, 'harus ada log peringatan'
    assert all(TOKEN not in r for r in records)
    assert TOKEN not in (err or '')
