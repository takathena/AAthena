/* ==========================================================
   NEXUS — Lazy loader (v2.0 frontend trim)
   Memuat CDN & aset section secara dinamis, bukan eager di <head>.
   Fitur tidak dihapus, hanya cara load yang berubah.
   ========================================================== */
(function () {
    'use strict';

    var _cache = {};       // key -> Promise
    var CDN = {
        leafletCss: 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
        leafletJs: 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
        clusterCss: 'https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css',
        clusterDefaultCss: 'https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css',
        clusterJs: 'https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js',
        chartJs: 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js',
        interactJs: 'https://cdn.jsdelivr.net/npm/interactjs@1.10.27/dist/interact.min.js',
    };

    function loadScript(url) {
        if (_cache[url]) return _cache[url];
        // Script yang sudah eager (metrics.js) tidak di-inject ulang; cukup resolve.
        if (document.querySelector('script[src="' + url + '"]')) {
            return (_cache[url] = Promise.resolve(url));
        }
        _cache[url] = new Promise(function (resolve, reject) {
            var s = document.createElement('script');
            s.src = url;
            s.async = true;
            s.onload = function () { resolve(url); };
            s.onerror = function () { delete _cache[url]; reject(new Error('Failed to load ' + url)); };
            document.head.appendChild(s);
        });
        return _cache[url];
    }

    function loadCSS(url) {
        if (_cache[url]) return _cache[url];
        // CSS yang sudah eager di <head> (metrics/components/date-range) tidak
        // di-inject ulang; cukup resolve agar pemanggil lain tetap jalan.
        if (document.querySelector('link[rel="stylesheet"][href="' + url + '"]')) {
            return (_cache[url] = Promise.resolve(url));
        }
        _cache[url] = new Promise(function (resolve, reject) {
            var l = document.createElement('link');
            l.rel = 'stylesheet';
            l.href = url;
            l.onload = function () { resolve(url); };
            l.onerror = function () { delete _cache[url]; try { l.remove(); } catch (e) {} reject(new Error('Failed to load ' + url)); };
            document.head.appendChild(l);
        });
        return _cache[url];
    }

    function loadSequential(urls) {
        var p = Promise.resolve();
        urls.forEach(function (u) { p = p.then(function () { return loadScript(u); }); });
        return p;
    }

    function fail(msg) {
        console.error('[LazyLoad] ' + msg);
        if (typeof window.showToast === 'function') window.showToast(msg, 'error');
        else if (typeof window.toast === 'function') window.toast(msg);
    }

    function loadMapLibs() {
        return Promise.all([loadCSS(CDN.leafletCss), loadCSS(CDN.clusterCss), loadCSS(CDN.clusterDefaultCss)])
            .then(function () { return loadSequential([CDN.leafletJs, CDN.clusterJs]); });
    }

    function loadChartLibs() {
        return loadSequential([CDN.chartJs, CDN.interactJs]);
    }

    function loadMetrics() { return loadCSS('/static/css/metrics.css').then(function () { return loadScript('/static/js/metrics.js'); }); }
    function loadComponents() { return loadCSS('/static/css/components.css'); }
    function loadDateRange() { return loadCSS('/static/css/date-range-picker.css').then(function () { return loadScript('/static/js/date-range-picker.js'); }); }
    function loadCommandPalette() { return loadCSS('/static/css/command-palette.css').then(function () { return loadScript('/static/js/command-palette.js'); }); }

    function loadSectionAssets(section) {
        if (section === 'map') return loadMapLibs();
        if (section === 'graph' || section === 'analytics') return loadChartLibs();
        if (section === 'alerts') return Promise.all([loadComponents(), loadMetrics(), loadDateRange()]);
        if (section === 'dashboard' || section === 'devices' || section === 'settings') return Promise.all([loadComponents(), loadMetrics()]);
        return Promise.resolve();
    }

    function sectionFromHash() {
        var h = (window.location.hash || '').replace('#', '').trim();
        if (h === 'analytics') return 'analytics';
        if (/^settings(\/[a-z-]+)?$/.test(h)) return 'settings';
        var valid = ['dashboard', 'map', 'graph', 'devices', 'alerts', 'settings'];
        return valid.includes(h) ? h : 'dashboard';
    }

    // Preload awal untuk section aktif (link langsung ke #map/#graph): async, tidak blokir paint.
    (function preloadInitial(){
        var h = sectionFromHash();
        if(h === 'map' || h === 'graph' || h === 'analytics') loadSectionAssets(h).catch(function(){ fail('Gagal memuat aset section. Cek koneksi internet/CDN.'); });
    })();

    // Preload assets untuk section aktif saat hash berubah / nav diklik (desktop & mobile).
    window.addEventListener('hashchange', function () {
        loadSectionAssets(sectionFromHash()).catch(function (e) { fail('Gagal memuat aset section. Cek koneksi internet/CDN.'); });
    }, true);

    // Section pertama langsung preload (direct #settings, restore session) supaya
    // Leaflet/Chart.js/picker sudah siap tanpa menunggu klik pertama.
    document.addEventListener('DOMContentLoaded', function () {
        // Hanya halaman desktop (ada nav [data-section]); mobile punya section sendiri.
        if (!document.querySelector('[data-section]')) return;
        loadSectionAssets(sectionFromHash()).catch(function () {});
    });

    document.addEventListener('click', function (e) {
        var nav = e.target.closest && e.target.closest('[data-section]');
        if (nav) loadSectionAssets(nav.getAttribute('data-section')).catch(function () { fail('Gagal memuat aset section. Cek koneksi internet/CDN.'); });
        var tab = e.target.closest && e.target.closest('[data-tab]');
        if (tab) loadSectionAssets(tab.getAttribute('data-tab')).catch(function () { fail('Gagal memuat aset section. Cek koneksi internet/CDN.'); });
    }, true);

    // Command palette: load on demand via Ctrl+K / klik search-box (desktop).
    document.addEventListener('keydown', function (e) {
        if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && (e.key === 'k' || e.key === 'K')) {
            if (window.NexusCommandPalette) return; // module sendiri yang menangani
            e.preventDefault();
            loadCommandPalette().then(function () {
                if (window.NexusCommandPalette && window.NexusCommandPalette.open) window.NexusCommandPalette.open();
            }).catch(function () { fail('Command palette gagal dimuat. Cek koneksi.'); });
        }
    }, true);

    document.addEventListener('click', function (e) {
        var sb = e.target.closest && e.target.closest('.search-box');
        if (!sb || sb.classList.contains('search-context')) return;
        if (window.NexusCommandPalette) return; // module sendiri yang menangani (capture)
        e.preventDefault();
        loadCommandPalette().then(function () {
            if (window.NexusCommandPalette && window.NexusCommandPalette.open) window.NexusCommandPalette.open();
        }).catch(function () { fail('Command palette gagal dimuat. Cek koneksi.'); });
    }, true);

    window.NexusLazy = {
        loadMapLibs: loadMapLibs,
        loadChartLibs: loadChartLibs,
        loadMetrics: loadMetrics,
        loadComponents: loadComponents,
        loadDateRange: loadDateRange,
        loadCommandPalette: loadCommandPalette,
        loadSectionAssets: loadSectionAssets,
    };
})();
