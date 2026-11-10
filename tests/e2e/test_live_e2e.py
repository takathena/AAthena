"""E2E live browser tests for AAguard.

Gated by E2E=1 because they mutate the live database (create/delete a device).
Run:
    E2E=1 pytest -q tests/e2e/test_live_e2e.py
Optional:
    E2E_BASE_URL=http://localhost:4455
    E2E_USERNAME=... E2E_PASSWORD=...
Credentials fall back to IOT_USERNAME/IOT_PASSWORD from the local .env.
"""
import json
import os
import re
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
ENV = dotenv_values(ROOT / '.env')
BASE = os.getenv('E2E_BASE_URL', 'http://localhost:4455').rstrip('/')
USER = os.getenv('E2E_USERNAME') or ENV.get('IOT_USERNAME') or ''
PASSWORD = os.getenv('E2E_PASSWORD') or ENV.get('IOT_PASSWORD') or ''

pytestmark = pytest.mark.skipif(
    not os.getenv('E2E') or not USER or not PASSWORD,
    reason='set E2E=1 and IOT_USERNAME/IOT_PASSWORD (or E2E_USERNAME/E2E_PASSWORD)',
)


@pytest.fixture(scope='session')
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={'width': 1440, 'height': 900})
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda exc: errors.append(str(exc)))
    yield page
    context.close()
    assert not errors, f'uncaught JS errors: {errors}'


def login(page):
    page.goto(f'{BASE}/login', wait_until='domcontentloaded')
    page.fill('#username', USER)
    page.fill('#password', PASSWORD)
    page.click('button.login-submit')
    page.wait_for_url(f'{BASE}/', timeout=15000)
    # Admin can read the seeded dashboard even when it is not their own.
    if page.request.get(f'{BASE}/d/default').status == 200:
        page.goto(f'{BASE}/d/default', wait_until='domcontentloaded')
    expect(page.locator('#dashboardSection')).to_be_visible()


def dashboard_payload(page):
    return page.evaluate("""async () => {
        const meta = document.querySelector('meta[name="dashboard-id"]');
        const id = meta ? meta.content : 'all';
        const r = await fetch('/api/v1/dashboard', {headers: {'X-Dashboard-Id': id}});
        return r.json();
    }""")


def dashboard_scope(page):
    meta = page.locator('meta[name="dashboard-id"]')
    value = meta.get_attribute('content') if meta.count() else ''
    if value:
        return value
    rows = page.evaluate("""async () => {
        const r = await fetch('/api/v1/dashboards');
        return (await r.json()).dashboards || [];
    }""")
    return str(rows[0]['id']) if rows else 'all'


def api(page, method, path, payload=None):
    csrf = next(c['value'] for c in page.context.cookies() if c['name'] == 'csrf_token')
    headers = {
        'X-CSRFToken': csrf,
        'X-Dashboard-Id': dashboard_scope(page),
    }
    request = getattr(page.context.request, method)
    if payload is None:
        return request(f'{BASE}{path}', headers=headers)
    return request(f'{BASE}{path}', headers=headers, data=json.dumps(payload))


def has_coords(devices):
    return any(
        d.get('latitude') not in (None, 0) and d.get('longitude') not in (None, 0)
        for d in devices
    )


def test_login_and_dashboard_smoke(page):
    login(page)
    payload = dashboard_payload(page)
    summary = payload['summary']
    expect(page.locator('#totalDevices')).to_have_text(str(summary['total_devices']))
    expect(page.locator('#onlineDevices')).to_have_text(str(summary['online_devices']))
    expect(page.locator('#offlineDevices')).to_have_text(str(summary['offline_devices']))
    expect(page.locator('#activeAlerts')).to_have_text(str(summary['active_alerts']))
    expect(page.locator('#bentoChart')).to_be_visible()
    expect(page.locator('#mapBento')).to_be_visible()
    expect(page.locator('#activityList')).to_be_visible()
    if has_coords(payload['devices']):
        page.wait_for_selector('#mapBento .leaflet-interactive', timeout=15000)


def test_sidebar_sections(page):
    login(page)
    devices = dashboard_payload(page)['devices']
    for section in ('map', 'graph', 'devices', 'alerts', 'settings', 'dashboard'):
        nav = page.locator(f'.sidebar .nav-item[data-section="{section}"]')
        nav.click()
        expect(page.locator(f'#{section}Section')).to_be_visible()
        expect(nav).to_have_class(re.compile(r'\bactive\b'))
    page.locator('.sidebar .nav-item[data-section="map"]').click()
    expect(page.locator('#mapFull')).to_be_visible()
    if has_coords(devices):
        page.wait_for_selector('#mapFull .leaflet-interactive', timeout=15000)


def test_command_palette_search_opens_device(page):
    login(page)
    devices = dashboard_payload(page)['devices']
    if not devices:
        pytest.skip('no devices to search')
    device_id = devices[0]['device_id']
    page.keyboard.press('Control+k')
    expect(page.locator('.nx-cmdk-overlay.nx-cmdk-open')).to_be_visible()
    page.fill('.nx-cmdk-input', device_id)
    result = page.locator(f'[data-cmd-id="device-{device_id}"]')
    expect(result).to_be_visible(timeout=10000)
    result.click()
    page.wait_for_url(re.compile(rf'/device/{re.escape(device_id)}$'), timeout=15000)
    expect(page.locator('#deviceName')).to_be_visible()


def test_settings_tabs_and_logout(page):
    login(page)
    page.locator('.sidebar .nav-item[data-section="settings"]').click()
    expect(page.locator('#settingsSection')).to_be_visible()
    tabs = page.locator('[data-settings-tab]')
    assert tabs.count() > 0, 'settings tabs not rendered'
    clicked = 0
    for i in range(tabs.count()):
        tab = tabs.nth(i)
        name = tab.get_attribute('data-settings-tab')
        if not tab.is_visible():
            continue
        tab.click()
        expect(tab).to_have_attribute('aria-selected', 'true')
        expect(page.locator(f'[data-settings-panel="{name}"]')).to_be_visible()
        clicked += 1
    assert clicked > 0, 'no visible settings tab could be opened'
    page.locator('#logoutBtn').click()
    page.wait_for_url(re.compile(r'/login$'), timeout=15000)
    expect(page.locator('#username')).to_be_visible()


def test_device_create_and_delete_roundtrip(page):
    login(page)
    device_id = f'E2E-{uuid.uuid4().hex[:8]}'
    try:
        resp = api(page, 'post', '/api/v1/devices', {
            'device_id': device_id,
            'device_name': 'E2E Device',
            'device_type': 'ESP32',
            'location': 'E2E Lab',
            'dashboard_id': dashboard_scope(page),
        })
        assert resp.status == 201, resp.text()
        page.reload(wait_until='domcontentloaded')
        page.locator('.sidebar .nav-item[data-section="devices"]').click()
        row = page.locator(f'#deviceTableBodyFull tr[data-device-id="{device_id}"]')
        expect(row).to_be_visible(timeout=15000)
        expect(row).to_contain_text('E2E Device')
    finally:
        api(page, 'delete', f'/api/v1/devices/{device_id}')
        check = api(page, 'get', f'/api/v1/devices/{device_id}')
        assert check.status == 404, check.text()
