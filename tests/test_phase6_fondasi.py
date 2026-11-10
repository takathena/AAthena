"""Fase 0 redesain — fondasi komponen, atribut izin, dan helper UI.

Tes ini memeriksa struktur statis (CSS/JS/template) dan logika applyNeeds
lewat Node.js bila tersedia. Tidak menguji tampilan piksel.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as f:
        return f.read()


# ---------- Komponen CSS ----------

REQUIRED_CLASSES = [
    'nx-btn', 'nx-btn--primary', 'nx-btn--ghost', 'nx-btn--danger',
    'nx-btn--danger-solid', 'nx-btn--icon', 'nx-badge', 'nx-chip', 'nx-tabs',
    'nx-tab', 'nx-menu', 'nx-menu__list', 'nx-overlay', 'nx-dialog',
    'nx-drawer', 'nx-empty', 'nx-hidden',
]


def test_components_css_defines_required_classes():
    css = _read('static', 'css', 'components.css')
    for cls in REQUIRED_CLASSES:
        assert re.search(r'\.%s\b' % re.escape(cls), css), 'kelas %s tidak ada' % cls


def test_components_css_adds_no_important():
    css = _read('static', 'css', 'components.css')
    assert '!important' not in css.replace('.nx-hidden { display: none !important; }', '')


def test_components_css_uses_existing_tokens_only():
    css = _read('static', 'css', 'components.css')
    used = set(re.findall(r'var\((--[a-z0-9-]+)\)', css))
    defined = set()
    css_dir = os.path.join(ROOT, 'static', 'css')
    for fn in os.listdir(css_dir):
        if fn.endswith('.css'):
            defined |= set(re.findall(r'(--[a-z0-9-]+)\s*:', _read('static', 'css', fn)))
    assert used <= defined, 'token tidak dikenal: %s' % (used - defined)


# ---------- Helper JS ----------

def test_ui_js_does_not_use_browser_storage():
    js = _read('static', 'js', 'ui.js')
    for name in ('localStorage', 'sessionStorage'):
        assert name not in js


def test_ui_js_exposes_api():
    js = _read('static', 'js', 'ui.js')
    for name in ('applyNeeds', 'openDialog', 'closeDialog', 'openDrawer', 'closeDrawer'):
        assert name + ':' in js or name + ',' in js


# ---------- Integrasi template dan dashboard.js ----------

def test_dashboard_template_loads_components_and_ui():
    html = _read('templates', 'dashboard.html')
    assert "css/components.css" in html
    assert "js/ui.js" in html
    # ui.js harus dimuat sebelum dashboard.js
    assert html.index("js/ui.js") < html.index("js/dashboard.js")


def test_dashboard_js_calls_apply_needs_after_role_known():
    js = _read('static', 'js', 'dashboard.js')
    assert 'AAGuardUI.applyNeeds' in js


# ---------- Logika data-needs (Node.js) ----------

NODE = shutil.which('node')

NODE_SCRIPT = r"""
const fs = require('fs');
global.window = {};
global.document = { addEventListener() {}, querySelectorAll() { return []; } };
eval(fs.readFileSync(process.argv[1], 'utf8'));
const cases = JSON.parse(process.argv[2]);
const out = cases.map(c => window.AAGuardUI._allowed(c.spec, c.ctx));
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason='node tidak tersedia')
def test_apply_needs_logic():
    cases = [
        # admin global lolos semua
        {'spec': 'admin', 'ctx': {'isAdmin': True, 'dashboardRole': None}},
        {'spec': 'owner', 'ctx': {'isAdmin': True, 'dashboardRole': None}},
        # owner
        {'spec': 'owner', 'ctx': {'isAdmin': False, 'dashboardRole': 'owner'}},
        {'spec': 'editor', 'ctx': {'isAdmin': False, 'dashboardRole': 'owner'}},
        # editor
        {'spec': 'editor', 'ctx': {'isAdmin': False, 'dashboardRole': 'editor'}},
        {'spec': 'owner', 'ctx': {'isAdmin': False, 'dashboardRole': 'editor'}},
        # viewer tidak boleh editor
        {'spec': 'editor', 'ctx': {'isAdmin': False, 'dashboardRole': 'viewer'}},
        {'spec': 'viewer', 'ctx': {'isAdmin': False, 'dashboardRole': 'viewer'}},
        # tanpa dashboard aktif
        {'spec': 'viewer', 'ctx': {'isAdmin': False, 'dashboardRole': None}},
        # daftar: salah satu cocok
        {'spec': 'admin owner', 'ctx': {'isAdmin': False, 'dashboardRole': 'owner'}},
        {'spec': 'admin owner', 'ctx': {'isAdmin': False, 'dashboardRole': 'viewer'}},
        # admin murni bukan admin
        {'spec': 'admin', 'ctx': {'isAdmin': False, 'dashboardRole': 'owner'}},
    ]
    expected = [True, True, True, True, True, False, False, True, False, True, False, False]
    res = subprocess.run(
        [NODE, '-e', NODE_SCRIPT, os.path.join(ROOT, 'static', 'js', 'ui.js'), json.dumps(cases)],
        capture_output=True, text=True, timeout=20,
    )
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout) == expected
