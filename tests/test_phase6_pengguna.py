"""Fase 2 redesain — Kelola Pengguna di Pengaturan › Pengguna.

Memeriksa struktur template dan perilaku yang bisa dibaca dari sumber.
Peran Moderator belum ada di backend, jadi tidak diuji di sini.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as f:
        return f.read()


def _drawer_block():
    part = _read('templates', 'partials', 'settings_section.html')
    start = part.index('<aside class="nx-drawer" id="userDrawer"')
    end = part.index('</aside>', start) + len('</aside>')
    return part[start:end]


def _dialogs_block():
    part = _read('templates', 'partials', 'settings_section.html')
    return part[part.index('id="userDiscardDialog"') - 40:]


def test_users_panel_lists_directly_and_has_add_button():
    part = _read('templates', 'partials', 'settings_section.html')
    panel = part[part.index('data-settings-panel="pengguna"'):]
    panel = panel[:panel.index('</section>')]
    assert 'id="usersAddBtn"' in panel
    assert 'id="usersList"' in panel
    assert 'data-proxy="manageUsersBtn"' not in panel


def test_drawer_has_close_and_single_save_only():
    drawer = _drawer_block()
    assert 'id="userDrawerClose"' in drawer
    assert 'id="userFormSave"' in drawer
    assert 'Batal' not in drawer
    assert 'modal-close' not in drawer
    footer = drawer[drawer.index('<footer'):]
    assert len(re.findall(r'<button', footer)) == 1


def test_delete_and_discard_dialogs_have_no_close_x():
    dialogs = _dialogs_block()
    assert 'modal-close' not in dialogs
    assert 'nx-btn--icon' not in dialogs
    assert 'id="userDeleteCancel"' in dialogs and 'id="userDeleteConfirm"' in dialogs
    assert 'id="userDiscardCancel"' in dialogs and 'id="userDiscardConfirm"' in dialogs


def test_dialog_actions_are_cancel_then_danger():
    dialogs = _dialogs_block()
    assert dialogs.index('id="userDeleteCancel"') < dialogs.index('id="userDeleteConfirm"')
    assert 'nx-btn--danger-solid' in dialogs


def test_users_js_uses_existing_api_and_no_browser_storage():
    js = _read('static', 'js', 'users.js')
    assert "'/api/v1/users'" in js or '"/api/v1/users"' in js or "API_BASE = '/api/v1/users'" in js
    assert 'window.API' not in js or 'global.API.call' in js
    assert 'localStorage' not in js and 'sessionStorage' not in js


def test_users_js_listens_to_settings_tab_event():
    js = _read('static', 'js', 'users.js')
    settings = _read('static', 'js', 'settings.js')
    assert "'nexus:settings-tab'" in js
    assert "'nexus:settings-tab'" in settings


def test_dashboard_loads_users_js_after_settings_js():
    html = _read('templates', 'dashboard.html')
    assert 'js/users.js' in html
    assert html.index('js/settings.js') < html.index('js/users.js')


def test_escape_in_dirty_drawer_asks_before_closing():
    js = _read('static', 'js', 'users.js')
    assert "addEventListener('keydown'" in js
    assert 'stopImmediatePropagation' in js
