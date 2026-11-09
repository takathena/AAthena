"""Paket A — penerapan izin di UI (desktop, mobile, Kelola Pengguna).

Tes ini memeriksa sumber, bukan tampilan. Penegakan sebenarnya ada di backend.
"""
import os
import re
import shutil
import subprocess
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as f:
        return f.read()


def test_ui_js_supports_permission_tokens():
    js = _read('static', 'js', 'ui.js')
    assert "'perm:'" in js


def test_users_drawer_has_roles():
    part = _read('templates', 'partials', 'settings_section.html')
    for value in ('value="user"', 'value="moderator"', 'value="admin"'):
        assert value in part
    assert 'id="userPermView"' not in part and 'id="userPermManage"' not in part
    js = _read('static', 'js', 'users.js')
    assert '/permissions' not in js
    assert "'role'" in js or 'payload.role' in js


def test_users_drawer_still_has_no_cancel_button():
    part = _read('templates', 'partials', 'settings_section.html')
    drawer = part[part.index('<aside class="nx-drawer"'):part.index('</aside>')]
    assert 'Batal' not in drawer
    footer = drawer[drawer.index('<footer'):]
    assert len(re.findall(r'<button', footer)) == 1


NODE = shutil.which('node')


def test_ui_js_permission_logic_node():
    if NODE is None:
        import pytest
        pytest.skip('node tidak tersedia')
    script = r"""
const fs = require('fs');
global.window = {};
global.document = { addEventListener() {}, querySelectorAll() { return []; } };
eval(fs.readFileSync(process.argv[1], 'utf8'));
const A = window.NexusUI._allowed;
const cases = [
  ['perm:foo.view', {isAdmin:false, permissions:['foo.view']}],
  ['perm:foo.view', {isAdmin:false, permissions:[]}],
  ['perm:foo.manage', {isAdmin:false, permissions:['foo.view']}],
  ['perm:foo.view', {isAdmin:true, permissions:[]}],
  ['perm:foo.view admin', {isAdmin:false, permissions:[]}],
];
console.log(JSON.stringify(cases.map(c => A(c[0], c[1]))));
"""
    res = subprocess.run([NODE, '-e', script, os.path.join(ROOT, 'static', 'js', 'ui.js')],
                         capture_output=True, text=True, timeout=20)
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout) == [True, False, False, True, False]
