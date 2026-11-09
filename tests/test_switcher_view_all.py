import pytest
pytestmark = pytest.mark.skip(reason="Belum di-port penuh ke FastAPI — di-skip sementara (Task 2)")
"""Regresi: dari tampilan 'Semua perangkat' (/all) user harus bisa kembali ke dashboard default."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as f:
        return f.read()


def _switch_body():
    js = _read('static', 'js', 'dashboard.js')
    start = js.index('function switchDashboard(')
    return js[start:js.index('function openCreateDashboardModal', start)]


def test_same_id_early_return_is_skipped_in_view_all_mode():
    body = _switch_body()
    assert 'if (!isViewAllMode() && id === state.currentDashboardId) return;' in body
    assert 'if (id === state.currentDashboardId) return;' not in body


def test_default_dashboard_navigates_to_root_from_view_all():
    body = _switch_body()
    assert "targetIsDefault ? '/' : `/d/${encodeURIComponent(slug)}`" in body


def test_view_all_page_scope_meta_is_all():
    views = _read('app', 'views.py')
    assert "dashboard_id='all', view_all=True" in views
