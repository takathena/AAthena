"""Navbar search aktif untuk peta + analitik (bukan palette trigger)."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as f:
        return f.read()


def test_showsection_unhides_search_for_map_and_graph_only():
    js = _read('static', 'js', 'dashboard.js')
    assert "const noSearch = ['settings'];" in js
    assert "section === 'map' || section === 'graph'" in js
    assert "'Cari device di peta...'" in js
    assert "'Cari diagram / perangkat...'" in js


def test_navbar_input_routes_to_map_and_graph_terms():
    js = _read('static', 'js', 'dashboard.js')
    assert 'graphSearchTerm' in js
    assert 'state.mapSearchTerm = value.trim();' in js
    assert 'applyGraphSearch();' in js


def test_palette_trigger_skips_search_context():
    assert "sb.classList.contains('search-context')" in _read('static', 'js', 'lazy-load.js')
    assert "sb.classList.contains('search-context')" in _read('static', 'js', 'command-palette.js')
    assert '.search-box.search-context input' in _read('static', 'css', 'app.css')
