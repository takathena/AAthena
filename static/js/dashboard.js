/* ==========================================
   AAguard IoT - Dashboard Logic (v8.0)
   Batch 1-7 + Metric cards integrated
   ========================================== */

(function() {
    'use strict';

    const state = {
        devices: [],
        currentSection: 'dashboard',
        charts: [],
        chartIdCounter: 0,
        globalTimeMinutes: 1440,
        deviceFilter: 'all',
        deviceFilterFull: 'all',
        mapFull: null,
        mapBento: null,
        bentoChart: null,
        marker: null,
        selectedLat: null,
        selectedLng: null,
        selectedMapDeviceId: null,
        refreshTimeout: null,
        autoRefreshInterval: null,
        dashboardInterval: null,
        deviceSearchTerm: '',
        alertSearchTerm: '',
        graphSearchTerm: '',
        analyticsTabs: [],
        currentTabId: null,
        isInitialized: false,
        dashboardSlug: null,
        dashboardsList: [],
        currentDashboardId: null,
        currentDashboardName: '',
        currentDashboardIcon: 'fa-chart-pie',
        mapFilter: 'all',
        mapSearchTerm: '',
        mapHasUnsavedChange: false,
        activityRefreshInterval: null,
        markerMap: new Map(),
        deleteTarget: null,
        canvasHeight: 720,
    };

    const CHART_FONT = "'Geist', -apple-system, sans-serif";

    const CHART_COLORS = [
        '#f97316', '#22c55e', '#ef4444', '#8b5cf6',
        '#3b82f6', '#14b8a6', '#f59e0b', '#ec4899',
    ];

    const GAP = 12;
    const PADDING = 16;
    const DEFAULT_W = 440;
    const DEFAULT_H = 320;
    const MIN_W = 240;
    const MIN_H = 160;

    const DATA_KEYS = {
        temperature: { label: 'Suhu',       unit: '°C',  color: '#f97316' },
        humidity:    { label: 'Kelembaban', unit: '%',   color: '#3b82f6' },
        gas_level:   { label: 'Gas',        unit: 'ppm', color: '#ef4444' },
        smoke:       { label: 'Asap',       unit: 'ppm', color: '#8b5cf6' },
    };

    const STORAGE_KEYS = {
        THEME: 'aaguard-theme',
        GLOBAL_TIME: 'aaguard-global-time',
        LAST_SECTION: 'aaguard-last-section',
        BACK_URL: 'aaguard_back_url',
        CURRENT_TAB: 'aaguard-current-tab',
        CHART_LAYOUT_PREFIX: 'aaguard-chart-layout-',
        CANVAS_HEIGHT: 'aaguard-chart-canvas-height',
    };

    const DASHBOARD_SECTIONS = ['dashboard', 'map', 'graph', 'devices', 'alerts', 'settings'];

    function refreshPermissionGates() {
        if (!window.AAGuardUI) return;
        const curDash = (state.dashboardsList || []).find(d => d.id === state.currentDashboardId);
        AAGuardUI.applyNeeds({
            isAdmin: userState.currentIsAdmin === true,
            dashboardRole: curDash ? curDash.role : null,
            permissions: userState.permissions || [],
        });

        // Sinkronkan context ke command palette (agar 'needs' difilter sesuai peran)
        if (window.AAGuardCommandPalette && typeof window.AAGuardCommandPalette.updateContext === 'function') {
            window.AAGuardCommandPalette.updateContext({
                isAdmin: userState.currentIsAdmin === true,
                dashboardRole: curDash ? curDash.role : null,
                permissions: userState.permissions || [],
            });
        }
    }

    const $ = (id) => document.getElementById(id);
    const $$ = (sel) => document.querySelectorAll(sel);

    // ==========================================
    // HELPERS
    // ==========================================
    function escapeHtml(str) {
        return String(str ?? '')
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function parseDate(iso) {
        if (!iso) return null;
        const s = String(iso).trim();
        if (/[+-]\d{2}:\d{2}$/.test(s) || s.endsWith('Z')) { const d = new Date(s); return isNaN(d.getTime()) ? null : d; }
        if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(s)) { const d = new Date(s.replace(' ', 'T') + '+07:00'); return isNaN(d.getTime()) ? null : d; }
        if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(s)) { const d = new Date(s + '+07:00'); return isNaN(d.getTime()) ? null : d; }
        if (/^\d{4}-\d{2}-\d{2}$/.test(s)) { const d = new Date(s + 'T00:00:00+07:00'); return isNaN(d.getTime()) ? null : d; }
        const d = new Date(s); return isNaN(d.getTime()) ? null : d;
    }

    function formatUptime(s) {
        if (!s && s !== 0) return '-';
        s = parseInt(s) || 0;
        if (s < 60) return `${s}s`;
        const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
        if (d > 0) return `${d}h ${h}j`;
        if (h > 0) return `${h}j ${m}m`;
        return `${m}m`;
    }

    function formatTime(iso) {
        const d = parseDate(iso); if (!d) return '-';
        try { return d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Jakarta' }); } catch (e) { return '-'; }
    }

    function formatRelativeTime(date) {
        if (!(date instanceof Date)) return '-';
        const diff = (Date.now() - date.getTime()) / 1000;
        if (diff < 0) return 'baru saja';
        if (diff < 60) return 'baru saja';
        if (diff < 3600) return `${Math.floor(diff / 60)} mnt lalu`;
        if (diff < 86400) return `${Math.floor(diff / 3600)} jam lalu`;
        if (diff < 604800) return `${Math.floor(diff / 86400)} hari lalu`;
        return date.toLocaleDateString('id-ID', { day: '2-digit', month: 'short' });
    }

    function formatTimeRange(minutes) {
        if (minutes <= 0) return '0 menit';
        if (minutes < 60) return `${minutes} menit`;
        if (minutes < 1440) return `${Math.round(minutes / 60)} jam`;
        if (minutes < 10080) return `${Math.round(minutes / 1440)} hari`;
        if (minutes < 43200) return `${Math.round(minutes / 10080)} minggu`;
        return `${Math.round(minutes / 43200)} bulan`;
    }

    function getChartColors() {
        const isLight = document.documentElement.getAttribute('data-theme') === 'light';
        return {
            gridColor: isLight ? 'rgba(0,0,0,0.05)' : 'rgba(255,255,255,0.05)',
            labelColor: isLight ? '#737373' : '#a3a3a3',
            legendColor: isLight ? '#525252' : '#a3a3a3',
            tooltipBg: isLight ? '#0a0a0a' : '#fafafa',
            tooltipBorder: isLight ? 'rgba(0,0,0,0.08)' : 'rgba(255,255,255,0.1)',
            tooltipTitleColor: isLight ? '#fafafa' : '#0a0a0a',
            tooltipBodyColor: isLight ? '#a3a3a3' : '#525252',
            pointBorderColor: isLight ? '#fafafa' : '#0a0a0a',
        };
    }

    function downsampleHistory(arr, max) {
        if (!Array.isArray(arr) || arr.length <= max) return arr;
        const step = arr.length / max;
        const out = [];
        for (let i = 0; i < max; i++) out.push(arr[Math.floor(i * step)]);
        if (out[out.length - 1] !== arr[arr.length - 1]) out.push(arr[arr.length - 1]);
        return out;
    }

    function showToast(msg, type) { if (window.showToast) window.showToast(msg, type); }
    function lockBodyScroll() { document.body.classList.add('modal-open'); }
    function unlockBodyScrollIfNoModal() {
        if (!document.querySelector('.modal.active')) document.body.classList.remove('modal-open');
    }
    function openModal(id) { const el = $(id); if (el) { el.classList.add('active'); lockBodyScroll(); } }
    function closeModal(id) { const el = $(id); if (el) el.classList.remove('active'); unlockBodyScrollIfNoModal(); }

    function registerMapInstance(map) {
        if (!window.__aaguardMaps) window.__aaguardMaps = [];
        if (!window.__aaguardMaps.includes(map)) window.__aaguardMaps.push(map);
    }

    // Leaflet must re-measure after display/layout settles (banner toggle, resize, sidebar)
    function invalidateMap(map) {
        if (!map) return;
        requestAnimationFrame(() => requestAnimationFrame(() => {
            try { map.invalidateSize(); } catch (e) {}
        }));
        setTimeout(() => { try { map.invalidateSize(); } catch (e) {} }, 200);
    }

    const MAP_VIEW_KEY = 'aaguard:map-view';
    function loadMapViews() {
        try { return JSON.parse(localStorage.getItem(MAP_VIEW_KEY) || '{}') || {}; } catch (e) { return {}; }
    }
    function saveMapView(key, map) {
        if (!key || !map) return;
        try {
            const c = map.getCenter();
            const z = map.getZoom();
            if (!c || typeof z !== 'number') return;
            const views = loadMapViews();
            views[key] = { lat: +c.lat.toFixed(6), lng: +c.lng.toFixed(6), zoom: z };
            localStorage.setItem(MAP_VIEW_KEY, JSON.stringify(views));
        } catch (e) {}
    }
    function restoreMapView(key, map, fallbackCenter, fallbackZoom) {
        if (!map) return;
        const view = loadMapViews()[key];
        if (view && Number.isFinite(view.lat) && Number.isFinite(view.lng) && Number.isFinite(view.zoom)) {
            map.setView([view.lat, view.lng], view.zoom);
            return;
        }
        if (fallbackCenter) map.setView(fallbackCenter, fallbackZoom);
    }
    function bindMapViewPersistence(key, map) {
        if (!key || !map || map.__viewPersistBound) return;
        map.__viewPersistBound = true;
        let t = null;
        const save = () => {
            clearTimeout(t);
            t = setTimeout(() => saveMapView(key, map), 150);
        };
        map.on('moveend', save);
        map.on('zoomend', save);
        window.addEventListener('resize', () => invalidateMap(map));
    }

    function getSectionFromHash() {
        const hash = (window.location.hash || '').replace('#', '').trim();
        const base = hash.split('/')[0];
        return DASHBOARD_SECTIONS.includes(base) ? base : 'dashboard';
    }

    function getSettingsTabFromHash() {
        const m = (window.location.hash || '').match(/^#settings\/([a-z-]+)/);
        return m ? m[1] : 'umum';
    }

    function updateHash(section, replace = false) {
        if (!DASHBOARD_SECTIONS.includes(section)) return;
        const newHash = `#${section}`;
        if (window.location.hash === newHash) return;
        if (replace) history.replaceState(null, '', newHash);
        else history.pushState(null, '', newHash);
    }

    // ==========================================
    // SECTION NAV
    // ==========================================
    function showSection(section, skipHistory = false) {
        if (!DASHBOARD_SECTIONS.includes(section)) section = 'dashboard';
        state.currentSection = section;

        DASHBOARD_SECTIONS.forEach(s => {
            const el = $(s + 'Section');
            if (!el) return;
            if (s === section) { el.style.display = 'block'; el.removeAttribute('hidden'); }
            else { el.style.display = 'none'; el.setAttribute('hidden', ''); }
        });


        $$('.sidebar .nav-item[data-section]').forEach(item => {
            item.classList.toggle('active', item.getAttribute('data-section') === section);
        });

        const searchBox = document.querySelector('.search-box');
        const searchInput = $('searchInput');
        const noSearch = ['settings'];
        const isSearchContext = section === 'map' || section === 'graph';
        if (searchBox) {
            searchBox.style.display = noSearch.includes(section) ? 'none' : '';
            searchBox.classList.toggle('search-context', isSearchContext);
        }
        if (searchInput) {
            searchInput.readOnly = !isSearchContext;
            if (section === 'map') {
                searchInput.value = state.mapSearchTerm || '';
                searchInput.placeholder = 'Cari device di peta...';
            } else if (section === 'graph') {
                searchInput.value = state.graphSearchTerm || '';
                searchInput.placeholder = 'Cari diagram / perangkat...';
            } else if (section === 'alerts') {
                searchInput.value = state.alertSearchTerm || '';
                searchInput.placeholder = 'Cari alert...';
            } else {
                searchInput.value = state.deviceSearchTerm || '';
                searchInput.placeholder = 'Cari perangkat...';
            }
        }

        if (section === 'settings' && window.AAGuardSettings) { AAGuardSettings.show(getSettingsTabFromHash()); }
        if (section === 'map') {
            setTimeout(() => {
                if (!state.mapFull) initFullMap();
                // Leaflet lazy: markers/invalidate ditangani initFullMap setelah map siap (atau fallback offline)
                if (state.mapFull) {
                    loadMarkers(state.mapFull, 'main');
                    renderMapDeviceList();
                    invalidateMap(state.mapFull);
                    updateMapSelectedBanner();
                } else {
                    renderMapDeviceList();
                    updateMapSelectedBanner();
                }
            }, 100);
        }
        if (section === 'dashboard') {
            setTimeout(() => { loadActivityFeed(); refreshBento(); }, 100);
        }
        if (section === 'graph') {
            setTimeout(() => {
                const runGraph = () => {
                    loadAnalyticsTabs();
                    refreshAllCharts();
                    setTimeout(() => {
                        state.charts.forEach(c => { if (c.chartInstance) try { const i=echarts.getInstanceByDom(c.chartInstance); if(i) i.resize(); } catch (e) {} });
                    }, 200);
                };
                // ECharts/interact.js lazy-load saat graph dibuka; fallback pesan bila offline
                if (window.AAGuardLazy && typeof window.AAGuardLazy.loadChartLibs === 'function') {
                    window.AAGuardLazy.loadChartLibs().then(runGraph).catch(() => {
                        const grid = $('chartsGrid');
                        if (grid) grid.innerHTML = '<div class="chart-empty" style="padding:30px;text-align:center;">Gagal memuat ECharts (offline?). Cek koneksi lalu buka lagi section Analitik.</div>';
                    });
                } else {
                    runGraph();
                }
            }, 100);
        }
        if (section === 'alerts' && window.AAGuardAlerts && typeof window.AAGuardAlerts.load === 'function') {
            if (window.AAGuardAlerts.setSearch) {
                window.AAGuardAlerts.setSearch(state.alertSearchTerm || '');
            }
            window.AAGuardAlerts.load();
        }

        try { sessionStorage.setItem(STORAGE_KEYS.LAST_SECTION, section); } catch (e) {}
        if (!skipHistory) updateHash(section);
    }

    function updateDateTime() {
        const now = new Date();
        const dateEl = $('currentDate'), timeEl = $('currentTime');
        if (dateEl) dateEl.textContent = now.toLocaleDateString('id-ID', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', timeZone: 'Asia/Jakarta' });
        if (timeEl) timeEl.textContent = now.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Asia/Jakarta' }) + ' WIB';
    }

    // ==========================================
    // DASHBOARD LOAD
    // ==========================================
    async function loadDashboard() {
        const result = await API.getDashboard();
        if (!result.success) {
            if (result.status === 401) { showToast('Session expired', 'warning'); setTimeout(() => window.location.href = '/login', 1500); return; }
            const tbody = $('deviceTableBody');
            if (tbody) tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--accent-crit);">Gagal memuat</td></tr>`;
            const tbodyFull = $('deviceTableBodyFull');
            if (tbodyFull) tbodyFull.innerHTML = `<tr><td colspan="9" style="text-align:center;padding:40px;color:var(--accent-crit);">Gagal memuat</td></tr>`;
            return;
        }
        const { summary, devices } = result.data;
        state.devices = Array.isArray(devices) ? devices : [];

        const total = summary.total_devices || 0;
        const online = summary.online_devices || 0;
        const offline = summary.offline_devices || 0;
        const alerts = summary.active_alerts || 0;
        const applyMetrics = () => {
            const M = window.AAGuardMetrics;
            if (!M) return;
            M.setValue('totalDevices', total);
            M.setValue('onlineDevices', online);
            M.setValue('offlineDevices', offline);
            M.setValue('activeAlerts', alerts);
            // Sparkline real dari /api/v1/metrics/devices-history
            loadDashboardMetricsHistory();
        };
        if (window.AAGuardMetrics) applyMetrics();
        // metrics.css/js lazy saat section dibuka
        else if (window.AAGuardLazy && typeof window.AAGuardLazy.loadMetrics === 'function') {
            window.AAGuardLazy.loadMetrics().then(applyMetrics).catch(() => {});
        }

        const setText = (id, val) => { const el = $(id); if (el) el.textContent = val; };
        setText('deviceBadge', total);
        setText('alertBadge', alerts);
        const onboarding = $('onboardingCard');
        if (onboarding) onboarding.hidden = (summary.total_devices || 0) > 0;
        if (state.mapFull) loadMarkers(state.mapFull, 'main');
        refreshBento();
        updateFilterCounts();
        renderFilteredDevices();
        renderFilteredDevicesFull();
        renderMapDeviceList();
        loadActivityFeed();
    }

    async function loadDashboardMetricsHistory() {
        const M = window.AAGuardMetrics;
        if (!M) return;

        const res = await API.call('/api/v1/metrics/devices-history?hours=24');
        if (!res.success) return;

        const { total, online, offline, alerts } = res.data || {};
        if (!Array.isArray(total) || total.length === 0) return;

        M.renderSparkline('totalDevices', total, '#a3a3a3');
        M.renderSparkline('onlineDevices', online, '#22c55e');
        M.renderSparkline('offlineDevices', offline, '#ef4444');
        M.renderSparkline('activeAlerts', alerts, '#f97316');

        const calcTrend = (arr) => {
            if (!Array.isArray(arr) || arr.length < 4) return 0;
            const half = Math.floor(arr.length / 2);
            const first = arr.slice(0, half).reduce((a, b) => a + b, 0);
            const second = arr.slice(half).reduce((a, b) => a + b, 0);
            if (first === 0) return second > 0 ? 100 : 0;
            return Math.round(((second - first) / first) * 100);
        };

        M.setTrend('totalDevices', calcTrend(total), { label: 'vs 24 jam lalu' });
        M.setTrend('onlineDevices', calcTrend(online), { label: 'vs 24 jam lalu' });
        M.setTrend('offlineDevices', calcTrend(offline), { label: 'vs 24 jam lalu', invertColors: true });
        M.setTrend('activeAlerts', calcTrend(alerts), { label: 'vs 24 jam lalu', invertColors: true });
    }

    // ==========================================
    // ACTIVITY FEED
    // ==========================================
    async function loadActivityFeed() {
        const container = $('activityList');
        if (!container) return;
        try {
            const alertsRes = await API.getAlertsAll({ limit: 20 });
            const events = [];
            if (alertsRes.success && Array.isArray(alertsRes.data.alerts)) {
                alertsRes.data.alerts.slice(0, 15).forEach(a => {
                    events.push({
                        type: 'alert', severity: a.severity || 'info',
                        title: a.device_name || a.device_id,
                        message: a.message || a.alert_type,
                        timestamp: a.created_at, deviceId: a.device_id,
                    });
                });
            }
            state.devices.forEach(d => {
                if (!d.last_seen) return;
                events.push({
                    type: d.status === 'online' ? 'online' : 'offline',
                    severity: d.status === 'online' ? 'online' : 'offline',
                    title: d.device_name,
                    message: d.status === 'online' ? 'Baru saja online' : 'Terakhir terlihat',
                    timestamp: d.last_seen, deviceId: d.device_id,
                });
            });
            events.sort((a, b) => {
                const da = parseDate(a.timestamp), db = parseDate(b.timestamp);
                if (!da || !db) return 0;
                return db - da;
            });
            const top = events.slice(0, 12);
            if (top.length === 0) { container.innerHTML = `<div class="activity-empty">Belum ada aktivitas</div>`; return; }
            const iconMap = {
                danger: 'fa-fire',
                warning: 'fa-triangle-exclamation',
                info: 'fa-circle-info',
                online: 'fa-circle-check',
                offline: 'fa-power-off',
                healthy: 'fa-circle-check'
            };
            container.innerHTML = top.map(ev => {
                const sev = ev.severity || 'info';
                const icon = iconMap[sev] || 'fa-bell';
                const dt = parseDate(ev.timestamp);
                const timeStr = dt ? formatRelativeTime(dt) : '-';
                const shortMsg = ev.type === 'alert' ? escapeHtml(String(ev.message).slice(0, 80)) : escapeHtml(ev.message);
                return `<div class="activity-item" data-device-id="${escapeHtml(ev.deviceId)}"><div class="activity-icon ${sev}"><i class="fa-solid ${icon}"></i></div><div class="activity-body"><div class="activity-text"><strong>${escapeHtml(ev.title)}</strong> — ${shortMsg}</div><div class="activity-time">${timeStr}</div></div></div>`;
            }).join('');
            container.querySelectorAll('.activity-item').forEach(item => {
                item.addEventListener('click', () => { const id = item.dataset.deviceId; if (id) viewDevice(id); });
            });
        } catch (e) { console.error(e); container.innerHTML = `<div class="activity-empty">Gagal memuat aktivitas</div>`; }
    }

    // ==========================================
    // MAP
    // ==========================================
    async function initFullMap() {
        if (state.mapFull) return;
        const el = $('mapFull'); if (!el) return;
        // Leaflet lazy-load saat section peta dibuka; fallback bila offline
        if (typeof L === 'undefined') {
            el.innerHTML = '<div class="map-fallback" style="padding:30px;text-align:center;">Memuat peta...</div>';
            try {
                if (window.AAGuardLazy) await window.AAGuardLazy.loadMapLibs();
            } catch (e) { /* ditangani di bawah */ }
            if (typeof L === 'undefined') {
                el.innerHTML = '<div class="map-fallback" style="padding:30px;text-align:center;">Gagal memuat peta (offline?). Cek koneksi lalu buka lagi section Peta.</div>';
                return;
            }
            el.innerHTML = '';
        }
        state.mapFull = L.map('mapFull').setView([-2.5489, 118.0149], 5);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(state.mapFull);
        state.mapFull.on('click', (e) => {
            if (!state.selectedMapDeviceId) { showToast('Pilih device di list dulu', 'warning'); return; }
            placeMarkerAt(e.latlng.lat, e.latlng.lng);
        });
        registerMapInstance(state.mapFull);
        restoreMapView('full', state.mapFull, [-2.5489, 118.0149], 5);
        bindMapViewPersistence('full', state.mapFull);
        loadMarkers(state.mapFull, 'main');
        renderMapDeviceList();
        invalidateMap(state.mapFull);
        updateMapSelectedBanner();
    }

    // ==========================================
    // BENTO TILES (dashboard): peta Leaflet ke-2 + chart sensor gabungan
    // ==========================================
    async function initBentoMap() {
        if (state.mapBento) return;
        const el = $('mapBento'); if (!el) return;
        if (typeof L === 'undefined') {
            try { if (window.AAGuardLazy) await window.AAGuardLazy.loadMapLibs(); } catch (e) {}
            if (typeof L === 'undefined') {
                el.innerHTML = '<div class="bento-map-empty">Peta gagal dimuat (offline?). Buka section Peta.</div>';
                return;
            }
        }
        // Instans kedua interaktif (klik tile luar map tetap -> section map via data-goto)
        state.mapBento = L.map('mapBento', {
            zoomControl: true, scrollWheelZoom: true, dragging: true,
            doubleClickZoom: true, boxZoom: true, keyboard: true, tap: false,
            attributionControl: true,
        }).setView([-7.0, 109.5], 7);
        el.closest('.bento-map-wrap')?.addEventListener('click', e => e.stopPropagation());
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(state.mapBento);
        registerMapInstance(state.mapBento);
        restoreMapView('bento', state.mapBento, [-7.0, 109.5], 7);
        bindMapViewPersistence('bento', state.mapBento);
        loadMarkers(state.mapBento, 'bento');
        invalidateMap(state.mapBento);
    }

    function fitBentoMap() {
        if (!state.mapBento) return;
        const saved = loadMapViews().bento;
        if (saved && Number.isFinite(saved.lat) && Number.isFinite(saved.lng) && Number.isFinite(saved.zoom)) {
            state.mapBento.setView([saved.lat, saved.lng], saved.zoom);
            return;
        }
        state.mapBento.setView([-7.0, 109.5], 7);
    }

    function refreshBento() {
        initBentoMap().then(() => {}).catch(() => {});
        if (state.mapBento) { loadMarkers(state.mapBento, 'bento'); invalidateMap(state.mapBento); }
        const withLoc = state.devices.filter(d => d.latitude != null && d.longitude != null && !(d.latitude === 0 && d.longitude === 0));
        const sub = $('bentoMapSub');
        if (sub) sub.textContent = withLoc.length ? `${withLoc.length} dari ${state.devices.length} perangkat berkoordinat — klik untuk buka peta` : (state.devices.length ? 'Belum ada perangkat berkoordinat' : 'Belum ada perangkat');
        loadBentoChart();
    }

    function stopRace(el){ if(el && el._race){ clearInterval(el._race); el._race=null; } }
    function ensureEChart(el){
        if(!el || typeof echarts === 'undefined') return null;
        let inst = echarts.getInstanceByDom(el);
        if(!inst) inst = echarts.init(el, null, {renderer:'canvas'});
        if(!el._ro && typeof ResizeObserver !== 'undefined'){
            el._ro = new ResizeObserver(() => { try{ inst && !inst.isDisposed() && inst.resize(); }catch(e){} });
            el._ro.observe(el);
        }
        return inst;
    }

    async function loadBentoChart() {
        const plotEl = $('bentoChart');
        const sub = $('bentoChartSub');
        const badgeCount = $('bentoBadgeCount');
        if (badgeCount) badgeCount.textContent = `${state.devices.length} perangkat`;
        if (!plotEl) return;
        if (state.devices.length === 0) { if (sub) sub.textContent = 'Belum ada perangkat'; return; }
        if (typeof echarts === 'undefined') {
            try { if (window.AAGuardLazy) await window.AAGuardLazy.loadChartLibs(); } catch (e) {}
            if (typeof echarts === 'undefined') { if (sub) sub.textContent = 'ECharts gagal dimuat (offline?)'; return; }
        }
        const hours = 24, limit = 500;
        const ids = state.devices.slice(0, 15).map(d => d.device_id);
        try {
            const results = await Promise.all(ids.map(did =>
                API.getDeviceHistory(did, { hours, limit }).then(r => r.success ? (r.data.history || []) : []).catch(() => [])
            ));
            const byTs = {};
            results.forEach(hist => hist.forEach(item => {
                const d = item.data || {};
                Object.keys(d).forEach(k => {
                    const v = Number(d[k]);
                    if (!Number.isFinite(v)) return;
                    byTs[item.timestamp] = byTs[item.timestamp] || {};
                    const cell = byTs[item.timestamp][k] = byTs[item.timestamp][k] || { sum: 0, n: 0 };
                    cell.sum += v; cell.n += 1;
                });
            }));
            const tsList = Object.keys(byTs).sort();
            if (tsList.length === 0) { if (sub) sub.textContent = 'Menunggu data sensor…'; return; }
            const usedTs = downsampleHistory(tsList, 120);
            const keyCounts = {};
            usedTs.forEach(ts => Object.keys(byTs[ts]).forEach(k => { keyCounts[k] = (keyCounts[k] || 0) + 1; }));
            const PRIORITY = ['temperature', 'humidity', 'gas_level', 'smoke'];
            const keys = PRIORITY.concat(Object.keys(keyCounts).sort((a, b) => (keyCounts[b] || 0) - (keyCounts[a] || 0)))
                .filter((k, i, arr) => arr.indexOf(k) === i && (keyCounts[k] || 0) >= Math.max(2, usedTs.length * 0.3))
                .slice(0, 3);
            if (keys.length === 0) { if (sub) sub.textContent = 'Tidak ada data sensor yang cocok'; return; }
            const colors = getChartColors();
            const series = keys.map((key, i) => {
                const info = DATA_KEYS[key] || { label: key, unit: '', color: CHART_COLORS[i % CHART_COLORS.length] };
                const color = info.color || CHART_COLORS[i % CHART_COLORS.length];
                const data = usedTs.map(ts => {
                    const t = String(ts).replace(' ','T'); const dt = new Date(/[+-]\d\d:\d\d$|Z$/.test(t)?t:t+'+07:00'); const ms = dt.getTime();
                    const c = byTs[ts][key];
                    return [isNaN(ms)?null:ms, c ? +(c.sum/c.n).toFixed(2) : null];
                }).filter(p => p[0]!=null);
                return { name: info.label, type:'bar', stack:'bento', data, barMaxWidth:18, itemStyle:{color}, emphasis:{focus:'series'} };
            });
            const chart = ensureEChart(plotEl);
            if(!chart) return;
            chart.setOption({
                animation:false,
                grid:{left:8,right:8,top:26,bottom:4,containLabel:true},
                tooltip:{trigger:'axis',confine:true,appendToBody:true,axisPointer:{type:'shadow'}},
                legend:{top:0,left:0,textStyle:{color:colors.legendColor,fontSize:10,fontFamily:CHART_FONT},itemWidth:10,itemHeight:10},
                xAxis:{type:'time',axisLabel:{color:colors.labelColor,fontSize:9,fontFamily:CHART_FONT},splitLine:{show:false},axisLine:{show:false},axisTick:{show:false}},
                yAxis:{type:'value',axisLabel:{color:colors.labelColor,fontSize:9,fontFamily:CHART_FONT},splitLine:{lineStyle:{color:colors.gridColor}}},
                series,
            }, {notMerge:true,lazyUpdate:true});
            state.bentoChart = plotEl;
            plotEl.onclick = e => e.stopPropagation();
            plotEl.onpointerdown = e => e.stopPropagation();
            const last = usedTs[usedTs.length - 1];
            const parts = keys.map(k => {
                const info = DATA_KEYS[k]; const c = byTs[last] && byTs[last][k];
                if (!c) return null;
                const avg = c.sum / c.n;
                return `${info ? info.label : k} ${avg.toFixed(1)}${info && info.unit ? ' ' + info.unit : ''}`;
            }).filter(Boolean);
            if (sub) sub.textContent = parts.length ? parts.join(' · ') + ` · ${ids.length} perangkat` : 'Grafik sensor real-time';
        } catch (e) { console.error('[BentoChart]', e); if (sub) sub.textContent = 'Gagal memuat grafik sensor'; }
    }

    function placeMarkerAt(lat, lng) {
        if (!state.mapFull) return;
        state.selectedLat = lat; state.selectedLng = lng;
        if (state.marker) { state.marker.setLatLng([lat, lng]); }
        else {
            state.marker = L.marker([lat, lng], { draggable: true }).addTo(state.mapFull);
            state.marker.on('dragstart', () => { state.mapHasUnsavedChange = true; });
            state.marker.on('dragend', (e) => {
                const pos = e.target.getLatLng();
                state.selectedLat = pos.lat; state.selectedLng = pos.lng;
                state.mapHasUnsavedChange = true;
                updateMapSelectedBanner();
            });
        }
        state.mapHasUnsavedChange = true;
        updateMapSelectedBanner();
    }

    function safeColor(c) {
        return /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(String(c || '')) ? c : '#737373';
    }

    function getDeviceMapStyle(d) {
        let color = '#737373'; let label = 'OFFLINE';
        if (d.status === 'offline') { color = '#ef4444'; label = 'OFFLINE'; }
        else if (d.has_alert && d.top_alert_severity) {
            const sev = String(d.top_alert_severity).toLowerCase();
            if (sev === 'danger') { color = '#ef4444'; label = 'DANGER'; }
            else if (sev === 'warning') { color = '#f97316'; label = 'WARNING'; }
            else if (sev === 'info') { color = '#8b5cf6'; label = 'INFO'; }
            else { color = '#8b5cf6'; label = 'INFO'; }
        } else if (d.status === 'online') { color = '#22c55e'; label = 'ONLINE'; }
        return { color: safeColor(color), label };
    }

    function loadMarkers(map, key = 'main') {
        if (!map || typeof L === 'undefined') return;
        if (state.marker && !state.mapHasUnsavedChange) { map.removeLayer(state.marker); state.marker = null; }
        const mapKey = key || 'main';
        const validIds = new Set();
        state.devices.forEach(d => {
            if (d.latitude == null || d.longitude == null) return;
            if (d.latitude === 0 && d.longitude === 0) return;
            validIds.add(d.device_id);
        });
        for (const [deviceId, entry] of state.markerMap.entries()) {
            if (entry.mapKey !== mapKey) continue;
            if (!validIds.has(deviceId)) {
                try { map.removeLayer(entry.marker); } catch (e) {}
                state.markerMap.delete(deviceId);
            }
        }
        state.devices.forEach(d => {
            if (!validIds.has(d.device_id)) return;
            const style = getDeviceMapStyle(d);
            const existing = state.markerMap.get(d.device_id);
            if (existing && existing.mapKey === mapKey) {
                try {
                    existing.marker.setLatLng([d.latitude, d.longitude]);
                    existing.marker.setStyle({ color: style.color, fillColor: style.color, radius: 7, fillOpacity: 0.9, weight: 2 });
                } catch (e) {}
                return;
            }
            const popup = mapKey === 'bento'
                ? `<div style="font-family:Geist,sans-serif;min-width:140px;"><div style="font-weight:600;margin-bottom:4px;">${escapeHtml(d.device_name)}</div><div style="font-size:11px;">Status: <b style="color:${escapeHtml(style.color)};">${escapeHtml(style.label)}</b></div><div style="font-size:10px;color:#888;margin-top:4px;">Klik tile untuk buka peta</div></div>`
                : `<div style="font-family:Geist,sans-serif;min-width:200px;"><div style="font-weight:600;margin-bottom:4px;">${escapeHtml(d.device_name)}</div><div style="font-size:11px;color:#888;margin-bottom:6px;font-family:'Geist Mono',monospace;">${escapeHtml(d.device_id)}</div><div style="font-size:11px;margin-bottom:8px;">Status: <b style="color:${escapeHtml(style.color)};">${escapeHtml(style.label)}</b></div><div style="display:flex;gap:6px;"><button data-action="map-select" data-device-id="${escapeHtml(d.device_id)}" style="flex:1;padding:6px 10px;background:#f5f5f5;color:#0a0a0a;border:none;border-radius:6px;font-size:11px;cursor:pointer;">Pilih</button><button data-action="map-view" data-device-id="${escapeHtml(d.device_id)}" style="flex:1;padding:6px 10px;background:#f97316;color:#fff;border:none;border-radius:6px;font-size:11px;cursor:pointer;">Detail</button></div></div>`;
            const marker = L.circleMarker([d.latitude, d.longitude], { radius: 7, color: style.color, fillColor: style.color, fillOpacity: 0.9, weight: 2 }).bindPopup(popup);
            marker.on('popupopen', (e) => {
                const el = e.popup.getElement();
                if (!el || el.__bound) return;
                el.__bound = true;
                el.querySelectorAll('[data-action="map-select"],[data-action="map-view"]').forEach(btn => {
                    btn.addEventListener('click', () => {
                        const id = btn.dataset.deviceId;
                        if (btn.dataset.action === 'map-select') window.__aaguardMapSelect(id);
                        else window.__aaguardMapView(id);
                    });
                });
            });
            marker.on('click', () => selectMapDevice(d.device_id, { zoom: false, placeMarker: false }));
            marker.addTo(map);
            state.markerMap.set(d.device_id, { marker, mapKey });
        });
    }

    function selectMapDevice(deviceId, opts = {}) {
        const device = state.devices.find(d => d.device_id === deviceId);
        if (!device) return;
        if (state.selectedMapDeviceId && state.selectedMapDeviceId !== deviceId && state.mapHasUnsavedChange) {
            if (!confirm('Ada perubahan lokasi belum disimpan. Lanjutkan?')) return;
        }
        state.selectedMapDeviceId = deviceId;
        state.mapHasUnsavedChange = false;
        state.selectedLat = null; state.selectedLng = null;
        const list = $('mapDeviceList');
        if (list) list.querySelectorAll('.map-device-item').forEach(el => el.classList.toggle('selected', el.dataset.deviceId === deviceId));
        const hasLoc = device.latitude && device.longitude && !(device.latitude === 0 && device.longitude === 0);
        if (hasLoc) {
            state.selectedLat = device.latitude; state.selectedLng = device.longitude;
            if (state.mapFull) {
                const targetZoom = opts.zoom ? 15 : Math.max(state.mapFull.getZoom(), 13);
                state.mapFull.flyTo([device.latitude, device.longitude], targetZoom, { duration: 1 });
            }
        } else if (opts.placeMarker && state.mapFull) {
            const c = state.mapFull.getCenter();
            placeMarkerAt(c.lat, c.lng);
        }
        updateMapSelectedBanner();
    }

    function updateMapSelectedBanner() {
        const banner = $('mapSelectedBanner'); const nameEl = $('mapSelectedName');
        const coordEl = $('mapSelectedCoord'); const dotEl = $('mapSelectedDot');
        const saveBtn = $('saveLocationBtn');
        if (!state.selectedMapDeviceId) { if (banner) banner.style.display = 'none'; return; }
        const device = state.devices.find(d => d.device_id === state.selectedMapDeviceId);
        if (!device) { if (banner) banner.style.display = 'none'; return; }
        const style = getDeviceMapStyle(device);
        if (banner) banner.style.display = 'flex';
        if (nameEl) nameEl.textContent = device.device_name;
        if (dotEl) dotEl.style.background = style.color;
        if (coordEl) {
            if (state.selectedLat != null && state.selectedLng != null) {
                coordEl.innerHTML = `${state.selectedLat.toFixed(5)}, ${state.selectedLng.toFixed(5)}` + (state.mapHasUnsavedChange ? ' <span style="color:var(--accent-warn);font-weight:600;">• belum disimpan</span>' : '');
            } else coordEl.textContent = 'Belum ada koordinat';
        }
        if (saveBtn) saveBtn.disabled = !(state.selectedLat != null && state.selectedLng != null && state.mapHasUnsavedChange);
        if (state.mapFull) invalidateMap(state.mapFull);
    }

    function renderMapDeviceList() {
        const container = $('mapDeviceList'); if (!container) return;
        const filter = state.mapFilter || 'all';
        const term = (state.mapSearchTerm || '').toLowerCase().trim();
        let list = state.devices.slice();
        if (filter === 'online') list = list.filter(d => d.status === 'online');
        else if (filter === 'offline') list = list.filter(d => d.status === 'offline');
        else if (filter === 'alert') list = list.filter(d => d.has_alert === true);
        if (term) list = list.filter(d => (d.device_name || '').toLowerCase().includes(term) || (d.device_id || '').toLowerCase().includes(term) || (d.location || '').toLowerCase().includes(term));
        if (list.length === 0) { container.innerHTML = `<div class="map-empty-list">${term ? 'Tidak ada device yang cocok' : 'Tidak ada device di filter ini'}</div>`; return; }
        container.innerHTML = list.map(d => {
            const style = getDeviceMapStyle(d);
            const hasLoc = d.latitude && d.longitude && !(d.latitude === 0 && d.longitude === 0);
            const isSelected = state.selectedMapDeviceId === d.device_id;
            return `<button class="map-device-item ${isSelected ? 'selected' : ''}" data-device-id="${escapeHtml(d.device_id)}"><span class="device-dot" style="background:${style.color};"></span><div class="device-info"><div class="device-name">${escapeHtml(d.device_name)}</div><div class="device-id">${escapeHtml(d.device_id)}${!hasLoc ? '<span style="color:var(--accent-warn);margin-left:4px;font-size:9px;">• belum ada lokasi</span>' : ''}</div></div><span class="device-status" style="background:${style.color}20;color:${style.color};">${escapeHtml(style.label)}</span></button>`;
        }).join('');
        container.querySelectorAll('.map-device-item').forEach(item => {
            item.addEventListener('click', () => selectMapDevice(item.dataset.deviceId, { zoom: true, placeMarker: true }));
        });
    }

    async function saveLocation() {
        const deviceId = state.selectedMapDeviceId;
        if (!deviceId) { showToast('Pilih perangkat dulu', 'error'); return; }
        if (!Number.isFinite(state.selectedLat) || !Number.isFinite(state.selectedLng)) { showToast('Atur lokasi dulu', 'error'); return; }
        const result = await API.updateDevice(deviceId, { latitude: state.selectedLat, longitude: state.selectedLng });
        if (result.success) {
            showToast(`Lokasi ${deviceId} tersimpan`, 'success');
            const device = state.devices.find(d => d.device_id === deviceId);
            if (device) { device.latitude = state.selectedLat; device.longitude = state.selectedLng; }
            state.mapHasUnsavedChange = false;
            updateMapSelectedBanner();
            loadDashboard();
        } else showToast(result.error || 'Gagal menyimpan', 'error');
    }

    function clearMapSelection() {
        if (state.mapHasUnsavedChange && !confirm('Ada perubahan belum disimpan. Yakin batal?')) return;
        state.selectedMapDeviceId = null;
        state.selectedLat = null; state.selectedLng = null;
        state.mapHasUnsavedChange = false;
        if (state.marker && state.mapFull) { state.mapFull.removeLayer(state.marker); state.marker = null; }
        const list = $('mapDeviceList');
        if (list) list.querySelectorAll('.map-device-item').forEach(el => el.classList.remove('selected'));
        updateMapSelectedBanner();
    }

    window.__aaguardMapSelect = function(id) { if (state.mapFull) state.mapFull.closePopup(); selectMapDevice(id, { zoom: false, placeMarker: true }); };
    window.__aaguardMapView = function(id) { viewDevice(id); };

    // ==========================================
    // DEVICE FILTERS
    // ==========================================
    function setDeviceFilter(filter) {
        state.deviceFilter = filter;
        $$('#deviceFilterBar .filter-btn').forEach(btn => btn.classList.toggle('active', btn.dataset.filter === filter));
        renderFilteredDevices();
    }

    function setDeviceFilterFull(filter) {
        state.deviceFilterFull = filter;
        $$('#deviceFilterBarFull .filter-btn').forEach(btn => btn.classList.toggle('active', btn.dataset.filter === filter));
        renderFilteredDevicesFull();
    }

    function filterDevicesByStatus(devices, filter) {
        switch (filter) {
            case 'online': return devices.filter(d => d.status === 'online');
            case 'offline': return devices.filter(d => d.status === 'offline');
            case 'alert': return devices.filter(d => d.has_alert === true);
            default: return devices;
        }
    }

    function renderFilteredDevices() { renderTable(filterDevicesByStatus(state.devices, state.deviceFilter), 'deviceTableBody', false); }
    function renderFilteredDevicesFull() { renderTable(filterDevicesByStatus(state.devices, state.deviceFilterFull), 'deviceTableBodyFull', true); }

    function updateFilterCounts() {
        const setText = (id, v) => { const el = $(id); if (el) el.textContent = v; };
        setText('filterCountAll', state.devices.length);
        setText('filterCountOnline', state.devices.filter(d => d.status === 'online').length);
        setText('filterCountOffline', state.devices.filter(d => d.status === 'offline').length);
        setText('filterCountAlert', state.devices.filter(d => d.has_alert === true).length);
    }

    function renderTable(devices, tbodyId, full) {
        const tbody = $(tbodyId); if (!tbody) return;
        if (devices.length === 0) { tbody.innerHTML = `<tr><td colspan="${full ? 9 : 7}" style="text-align:center;padding:40px;color:var(--text-3);">Tidak ada perangkat</td></tr>`; return; }
        tbody.innerHTML = devices.map(d => {
            const lastSeen = formatTime(d.last_seen);
            const uptime = formatUptime(d.latest_uptime_seconds || 0);
            const wifi = escapeHtml(d.latest_wifi_ssid || '-');
            let statusClass, statusLabel;
            if (d.status === 'offline') { statusClass = 'offline'; statusLabel = 'OFFLINE'; }
            else if (d.has_alert && d.top_alert_severity) {
                statusClass = d.top_alert_severity;
                statusLabel = d.top_alert_severity === 'danger' ? 'BAHAYA' : d.top_alert_severity === 'warning' ? 'PERINGATAN' : d.top_alert_severity.toUpperCase();
            } else { statusClass = d.status || 'online'; statusLabel = (d.status || 'online').toUpperCase(); }
            return `<tr data-device-id="${escapeHtml(d.device_id)}"><td><span class="status-badge ${statusClass}"><span class="status-dot-inline"></span>${escapeHtml(statusLabel)}</span></td><td><span class="device-id">${escapeHtml(d.device_id)}</span></td><td><span class="device-name">${escapeHtml(d.device_name)}</span>${isViewAllMode() && d.dashboard_name ? `<span class="ws-badge" title="Dashboard · pemilik">${escapeHtml(d.dashboard_name)} · ${escapeHtml(d.owner_name || "-")}</span>` : ''}</td>${full ? `<td>${escapeHtml(d.device_type || '-')}</td>` : ''}<td>${wifi}</td><td>${uptime}</td>${full ? `<td>${escapeHtml(d.location || '-')}</td>` : ''}<td>${lastSeen}</td><td><div class="device-actions"><button class="action-btn more" data-action="more" data-device-id="${escapeHtml(d.device_id)}" title="Aksi lainnya" aria-label="Aksi lainnya"><i class="fa-solid fa-ellipsis-vertical"></i></button></div></td></tr>`;
        }).join('');

        tbody.querySelectorAll('[data-action="more"]').forEach(b => {
            b.addEventListener('click', (e) => {
                e.stopPropagation();
                openDeviceActionMenu(b, b.dataset.deviceId);
            });
        });
    }

    // ==========================================
    // DEVICE ACTION MENU (⋯ popup)
    // ==========================================
    function openDeviceActionMenu(anchorEl, deviceId) {
        closeDeviceActionMenu();

        const menu = document.createElement('div');
        menu.className = 'device-action-menu';
        menu.id = 'deviceActionMenu';
        menu.setAttribute('role', 'menu');
        menu.innerHTML = `
            <button type="button" class="device-action-menu__item" data-menu-action="view" role="menuitem">
                <i class="fa-solid fa-eye"></i> Detail
            </button>
            <button type="button" class="device-action-menu__item" data-menu-action="config" role="menuitem">
                <i class="fa-solid fa-sliders"></i> Konfigurasi
            </button>
            <button type="button" class="device-action-menu__item" data-menu-action="regenerate" role="menuitem">
                <i class="fa-solid fa-key"></i> Regenerate API Key
            </button>
            <div class="device-action-menu__divider"></div>
            <button type="button" class="device-action-menu__item device-action-menu__item--danger" data-menu-action="delete" role="menuitem">
                <i class="fa-solid fa-trash"></i> Hapus Perangkat
            </button>
        `;
        document.body.appendChild(menu);

        const rect = anchorEl.getBoundingClientRect();
        const menuRect = menu.getBoundingClientRect();

        let top = rect.bottom + 6;
        let left = rect.right - menuRect.width;

        if (top + menuRect.height > window.innerHeight - 10) {
            top = rect.top - menuRect.height - 6;
        }
        if (left < 10) left = 10;
        if (left + menuRect.width > window.innerWidth - 10) {
            left = window.innerWidth - menuRect.width - 10;
        }

        menu.style.top = top + 'px';
        menu.style.left = left + 'px';

        menu.querySelectorAll('[data-menu-action]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const action = btn.dataset.menuAction;
                closeDeviceActionMenu();
                if (action === 'view') viewDevice(deviceId);
                else if (action === 'config') openEditDeviceConfig(deviceId);
                else if (action === 'regenerate') regenerateApiKey(deviceId);
                else if (action === 'delete') openDeleteModal(deviceId);
            });
        });

        anchorEl.classList.add('menu-open');

        setTimeout(() => {
            document.addEventListener('mousedown', _handleDeviceMenuOutside, true);
            document.addEventListener('keydown', _handleDeviceMenuKey, true);
        }, 0);
    }

    function _handleDeviceMenuOutside(e) {
        const menu = document.getElementById('deviceActionMenu');
        if (!menu) return;
        if (menu.contains(e.target)) return;
        closeDeviceActionMenu();
    }

    function _handleDeviceMenuKey(e) {
        if (e.key === 'Escape') closeDeviceActionMenu();
    }

    function closeDeviceActionMenu() {
        const menu = document.getElementById('deviceActionMenu');
        if (menu) menu.remove();
        document.querySelectorAll('.action-btn.menu-open').forEach(b => b.classList.remove('menu-open'));
        document.removeEventListener('mousedown', _handleDeviceMenuOutside, true);
        document.removeEventListener('keydown', _handleDeviceMenuKey, true);
    }

    function filterDevices() {
        const term = (state.deviceSearchTerm || '').toLowerCase().trim();
        const searched = term ? state.devices.filter(d => d.device_id.toLowerCase().includes(term) || d.device_name.toLowerCase().includes(term) || (d.location && d.location.toLowerCase().includes(term))) : state.devices;
        renderTable(filterDevicesByStatus(searched, state.deviceFilter), 'deviceTableBody', false);
        renderTable(filterDevicesByStatus(searched, state.deviceFilterFull), 'deviceTableBodyFull', true);
    }

    // ==========================================
    // DEVICE CRUD
    // ==========================================
    function viewDevice(id) {
        const backUrl = `/${window.location.hash || '#dashboard'}`;
        try { sessionStorage.setItem(STORAGE_KEYS.BACK_URL, backUrl); } catch (e) {}
        window.location.href = `/device/${encodeURIComponent(id)}`;
    }

    async function regenerateApiKey(deviceId) {
        if (!confirm(`Regenerate API key ${deviceId}?`)) return;
        const result = await API.regenerateKey(deviceId);
        if (result.success) {
            const display = $('apiKeyDisplay'); if (display) display.textContent = result.data.api_key;
            openModal('apiKeyModal'); loadDashboard();
        } else showToast(result.error || 'Gagal', 'error');
    }

    function openAddDeviceModal() {
        if (window.populateAlertRules) window.populateAlertRules('add', null);
        const setVal = (id, val) => { const el = $(id); if (el) el.value = val; };
        setVal('addDeviceId', '');
        setVal('addDeviceName', '');
        setVal('addDeviceLocation', '');
        setVal('addDeviceDescription', '');
        setVal('addDeviceFirmware', '');
        setVal('addDeviceOfflineTimeout', '');
        setVal('addDeviceInterval', '');
        const sevEl = $('addDeviceOfflineSeverity');
        if (sevEl) sevEl.value = 'danger';
        const typeEl = $('addDeviceType');
        if (typeEl) typeEl.value = 'ESP32';
        openModal('addDeviceModal');
    }

    async function addDevice() {
        const idEl = $('addDeviceId'); const nameEl = $('addDeviceName');
        const deviceId = idEl ? idEl.value.trim() : '';
        const deviceName = nameEl ? nameEl.value.trim() : '';
        if (!deviceId || !deviceName) { showToast('ID dan Nama wajib', 'error'); return; }
        const alertRules = window.collectAlertRules ? window.collectAlertRules('add') : null;

        const payload = {
            device_id: deviceId,
            device_name: deviceName,
            device_type: ($('addDeviceType') || {}).value,
            location: (($('addDeviceLocation') || {}).value || '').trim(),
            description: (($('addDeviceDescription') || {}).value || '').trim(),
            firmware_version: (($('addDeviceFirmware') || {}).value || '').trim(),
            offline_alert_severity: ($('addDeviceOfflineSeverity') || {}).value || 'danger',
        };

        const offlineTimeout = ($('addDeviceOfflineTimeout') || {}).value;
        if (offlineTimeout) payload.offline_timeout = parseInt(offlineTimeout);

        const intervalVal = ($('addDeviceInterval') || {}).value;
        if (intervalVal && parseInt(intervalVal) >= 10) {
            payload.expected_interval = parseInt(intervalVal);
        }

        if (alertRules) payload.alert_rules = alertRules;

        const result = await API.addDevice(payload);
        if (result.success) {
            closeModal('addDeviceModal');
            const display = $('apiKeyDisplay'); if (display) display.textContent = result.data.device.api_key;
            openModal('apiKeyModal');
            if (idEl) idEl.value = '';
            if (nameEl) nameEl.value = '';
            const locEl = $('addDeviceLocation'); if (locEl) locEl.value = '';
            const descEl = $('addDeviceDescription'); if (descEl) descEl.value = '';
            const fwEl = $('addDeviceFirmware'); if (fwEl) fwEl.value = '';
            const toEl = $('addDeviceOfflineTimeout'); if (toEl) toEl.value = '';
            const ivEl = $('addDeviceInterval'); if (ivEl) ivEl.value = '';
            if (window.populateAlertRules) window.populateAlertRules('add', null);
            loadDashboard();
        } else {
            showToast(result.error || 'Gagal', 'error');
        }
    }

    function copyApiKey() {
        const display = $('apiKeyDisplay'); if (!display) return;
        navigator.clipboard.writeText(display.textContent).then(() => showToast('Tersalin!', 'success')).catch(() => showToast('Gagal', 'error'));
    }

    async function openEditDeviceConfig(deviceId) {
        const result = await API.getDevice(deviceId);
        if (!result.success) { showToast('Gagal memuat', 'error'); return; }
        const device = result.data.device;
        const setVal = (id, val) => { const el = $(id); if (el) el.value = val; };
        setVal('editConfigDeviceId', deviceId);

        setVal('editDeviceName', device.device_name || '');
        setVal('editDeviceLocation', device.location || '');
        setVal('editDeviceDescription', device.description || '');
        setVal('editDeviceFirmware', device.firmware_version || '');

        const typeEl = $('editDeviceType');
        if (typeEl) {
            const types = ['ESP32', 'ESP8266', 'Arduino', 'Raspberry Pi', 'Other'];
            const current = device.device_type || 'ESP32';
            typeEl.value = types.includes(current) ? current : 'Other';
        }

        const sevEl = $('editDeviceOfflineSeverity');
        if (sevEl) sevEl.value = device.offline_alert_severity || 'danger';

        const intervalDisplay = $('editDeviceIntervalDisplay');
        if (intervalDisplay) {
            const interval = device.expected_interval;
            intervalDisplay.textContent = interval ? `${interval} detik` : 'Menunggu data...';
        }
        setVal('editDeviceInterval', device.expected_interval || '');

        setVal('editDeviceOfflineTimeout', device.offline_timeout || '');

        if (window.populateAlertRules) window.populateAlertRules('edit', device.alert_rules);
        openModal('editDeviceConfigModal');
    }

    async function saveDeviceConfig() {
        const deviceId = ($('editConfigDeviceId') || {}).value;
        if (!deviceId) return;

        const deviceName = (($('editDeviceName') || {}).value || '').trim();
        if (!deviceName) { showToast('Nama perangkat wajib diisi', 'error'); return; }

        const alertRules = window.collectAlertRules ? window.collectAlertRules('edit') : null;

        const payload = {
            device_name: deviceName,
            device_type: ($('editDeviceType') || {}).value || 'ESP32',
            location: (($('editDeviceLocation') || {}).value || '').trim(),
            description: (($('editDeviceDescription') || {}).value || '').trim(),
            firmware_version: (($('editDeviceFirmware') || {}).value || '').trim(),
            offline_alert_severity: ($('editDeviceOfflineSeverity') || {}).value || 'danger',
            alert_rules: alertRules,
        };

        const intervalVal = ($('editDeviceInterval') || {}).value;
        if (intervalVal && parseInt(intervalVal) >= 10) {
            payload.expected_interval = parseInt(intervalVal);
        } else if ($('editDeviceInterval') && intervalVal === '') {
            payload.expected_interval = null;
        }

        const offlineTimeout = ($('editDeviceOfflineTimeout') || {}).value;
        if (offlineTimeout) {
            payload.offline_timeout = parseInt(offlineTimeout);
        } else {
            payload.offline_timeout = null;
        }

        const result = await API.updateDevice(deviceId, payload);
        if (result.success) {
            closeModal('editDeviceConfigModal');
            showToast('Konfigurasi tersimpan', 'success');
            loadDashboard();
        } else {
            showToast(result.error || 'Gagal', 'error');
        }
    }

    function updateDeleteButtonState() {
        const btn = $('confirmDeleteBtn'); const input = $('deleteConfirmInput');
        if (!btn || !input) return;
        const target = state.deleteTarget;
        if (!target) { btn.disabled = true; return; }
        btn.disabled = input.value.trim() !== target.confirmKey;
    }

    function openDeleteModal(id) {
        const device = state.devices.find(d => d.device_id === id);
        const deviceName = device ? device.device_name : id;
        state.deleteTarget = { type: 'device', id, confirmKey: id };
        const setVal = (elId, val) => { const el = $(elId); if (el) el.value = val; };
        setVal('deleteType', 'device'); setVal('deleteDeviceId', id);
        const titleEl = $('deleteModalTitle'); const textEl = $('deleteModalText');
        const labelEl = $('deleteConfirmLabel'); const inputEl = $('deleteConfirmInput');
        if (titleEl) titleEl.textContent = 'Hapus Perangkat';
        if (textEl) textEl.textContent = `Perangkat "${deviceName}" (${id}) akan dihapus permanen.`;
        if (labelEl) labelEl.innerHTML = `Ketik <code style="background:var(--surface-2);padding:2px 6px;border-radius:4px;font-family:var(--mono);font-size:12px;">${escapeHtml(id)}</code> untuk konfirmasi`;
        if (inputEl) { inputEl.value = ''; inputEl.placeholder = `Ketik ${id}...`; }
        updateDeleteButtonState();
        openModal('deleteModal');
    }

    async function confirmDelete() {
        const target = state.deleteTarget; if (!target) return;
        const input = $('deleteConfirmInput'); const value = input ? input.value.trim() : '';
        if (value !== target.confirmKey) { showToast(`Ketik "${target.confirmKey}" dengan benar`, 'error'); return; }
        const result = await API.deleteDevice(target.id);
        if (result.success) {
            closeModal('deleteModal');
            state.deleteTarget = null;
            showToast('Perangkat dihapus', 'success'); loadDashboard();
        } else showToast(result.error || 'Gagal', 'error');
    }

    // ==========================================
    // ANALYTICS TABS
    // ==========================================
    async function loadAnalyticsTabs() {
        const store = window.DashboardStore;
        if (!store) return;
        let targetDashboard = null;
        if (state.dashboardSlug) {
            const res = await API.call(`/api/v1/dashboards/slug/${encodeURIComponent(state.dashboardSlug)}`);
            if (res.success) targetDashboard = res.data.dashboard;
        }
        if (!targetDashboard) {
            await store.loadDashboards();
            if (state.currentDashboardId) {
                targetDashboard = store.state.dashboards.find(d => d.id === state.currentDashboardId);
            }
            if (!targetDashboard) {
                targetDashboard = store.state.dashboards.find(d => d.is_default) || store.state.dashboards[0];
            }
        }
        if (!targetDashboard) return;
        state.currentDashboardId = targetDashboard.id;
        state.currentDashboardName = targetDashboard.name;
        state.currentDashboardIcon = targetDashboard.icon || 'fa-chart-pie';
        await store.loadDashboard(targetDashboard.id);
        const res = await API.call(`/api/v1/dashboards/${targetDashboard.id}/analytics-tabs`);
        state.analyticsTabs = res.success ? (res.data.tabs || []) : [];
        let savedTabId = null;
        try { const raw = sessionStorage.getItem(STORAGE_KEYS.CURRENT_TAB); if (raw) savedTabId = parseInt(raw); } catch (e) {}
        const validIds = new Set(state.analyticsTabs.map(t => t.id));
        if (savedTabId && validIds.has(savedTabId)) state.currentTabId = savedTabId;
        else if (state.currentTabId !== null && validIds.has(state.currentTabId)) {}
        else state.currentTabId = state.analyticsTabs.length > 0 ? state.analyticsTabs[0].id : null;
        renderAnalyticsTabs();
        if (state.currentTabId) await loadTabCharts(state.currentTabId);
    }

    function renderAnalyticsTabs() {
        const trigger = $('tabDropdownTrigger'); const label = $('tabDropdownLabel'); const menu = $('tabDropdownMenu');
        if (!trigger || !label || !menu) return;
        const currentTab = state.analyticsTabs.find(t => t.id === state.currentTabId);
        label.textContent = currentTab ? currentTab.name : 'Pilih Tab';
        let html = '';
        state.analyticsTabs.forEach(tab => {
            html += `<div class="tab-dropdown-item ${state.currentTabId === tab.id ? 'active' : ''}" data-tab-id="${tab.id}"><i class="fa-solid ${escapeHtml(tab.icon || 'fa-chart-line')}"></i><span>${escapeHtml(tab.name)}</span><div class="tab-actions"><button class="tab-action-btn" data-action="rename-tab" data-tab-id="${tab.id}" title="Rename"><i class="fa-solid fa-pen"></i></button><button class="tab-action-btn" data-action="delete-tab" data-tab-id="${tab.id}" title="Hapus"><i class="fa-solid fa-trash"></i></button></div></div>`;
        });
        html += `<div class="tab-dropdown-divider"></div><div class="tab-dropdown-add" data-action="new-tab"><i class="fa-solid fa-plus"></i><span>Tambah Tab Analitik</span></div>`;
        menu.innerHTML = html;
        menu.querySelectorAll('[data-tab-id]').forEach(item => {
            const tabId = parseInt(item.dataset.tabId);
            item.addEventListener('click', (e) => {
                if (e.target.closest('[data-action]')) return;
                switchAnalyticsTab(tabId);
                menu.classList.remove('active');
            });
        });
        menu.querySelectorAll('[data-action="rename-tab"], [data-action="delete-tab"]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const tabId = parseInt(btn.dataset.tabId);
                const tab = state.analyticsTabs.find(t => t.id === tabId);
                if (tab) openAnalyticsTabModal('edit', tab.id, tab.name);
                menu.classList.remove('active');
            });
        });
        const addBtn = menu.querySelector('[data-action="new-tab"]');
        if (addBtn) addBtn.addEventListener('click', () => { openAnalyticsTabModal('new'); menu.classList.remove('active'); });
    }

    async function switchAnalyticsTab(tabId) {
        state.currentTabId = tabId;
        try { sessionStorage.setItem(STORAGE_KEYS.CURRENT_TAB, String(tabId)); } catch (e) {}
        renderAnalyticsTabs();
        await loadTabCharts(tabId);
    }

    function openAnalyticsTabModal(mode, tabId, currentName) {
        const titleEl = $('analyticsTabModalTitle'); const modeEl = $('analyticsTabMode');
        const idEl = $('analyticsTabId'); const nameEl = $('analyticsTabName');
        const delBtn = $('analyticsTabDeleteBtn');
        if (titleEl) titleEl.textContent = mode === 'edit' ? 'Edit Tab Analitik' : 'Tambah Tab Analitik';
        if (modeEl) modeEl.value = mode;
        if (idEl) idEl.value = tabId || '';
        if (nameEl) nameEl.value = currentName || '';
        if (delBtn) delBtn.style.display = mode === 'edit' ? 'inline-flex' : 'none';
        openModal('analyticsTabModal');
    }

    async function saveAnalyticsTab() {
        const mode = ($('analyticsTabMode') || {}).value;
        const tabId = ($('analyticsTabId') || {}).value;
        const name = ($('analyticsTabName') || {}).value?.trim() || '';
        if (!name) { showToast('Nama tab wajib', 'error'); return; }
        const store = window.DashboardStore;
        const dashboardId = store.state.currentDashboardId;
        if (mode === 'edit' && tabId) {
            const res = await API.call(`/api/v1/analytics-tabs/${tabId}`, { method: 'PUT', body: JSON.stringify({ name }) });
            if (res.success) { closeModal('analyticsTabModal'); showToast('Tab diupdate', 'success'); await loadAnalyticsTabs(); }
            else showToast(res.error || 'Gagal', 'error');
        } else {
            const res = await API.call(`/api/v1/dashboards/${dashboardId}/analytics-tabs`, { method: 'POST', body: JSON.stringify({ name, icon: 'fa-chart-line' }) });
            if (res.success) { closeModal('analyticsTabModal'); showToast('Tab dibuat', 'success'); await loadAnalyticsTabs(); switchAnalyticsTab(res.data.id); }
            else showToast(res.error || 'Gagal', 'error');
        }
    }

    async function deleteAnalyticsTab() {
        const tabId = ($('analyticsTabId') || {}).value;
        if (!tabId || !confirm('Hapus tab ini beserta diagramnya?')) return;
        const res = await API.call(`/api/v1/analytics-tabs/${tabId}`, { method: 'DELETE' });
        if (res.success) {
            closeModal('analyticsTabModal');
            showToast('Tab dihapus', 'success');
            if (state.currentTabId === parseInt(tabId)) {
                state.currentTabId = null;
                try { sessionStorage.removeItem(STORAGE_KEYS.CURRENT_TAB); } catch (e) {}
            }
            await loadAnalyticsTabs();
            if (state.analyticsTabs.length > 0) switchAnalyticsTab(state.analyticsTabs[0].id);
            else {
                state.charts.forEach(c => { if (c.chartInstance) { stopRace(c.chartInstance); try { const i=echarts.getInstanceByDom(c.chartInstance); if(i) i.dispose(); } catch(e){} try{ if(c.chartInstance._ro){c.chartInstance._ro.disconnect(); c.chartInstance._ro=null;} }catch(e){} } });
                state.charts = [];
                const grid = $('chartsGrid');
                if (grid) grid.innerHTML = `<div class="empty-charts" style="text-align:center;padding:40px;color:var(--text-3);"><i class="fa-solid fa-chart-column" style="font-size:40px;margin-bottom:12px;display:block;opacity:.4;"></i><p style="font-size:14px;font-weight:600;">Belum ada diagram di tab ini</p></div>`;
            }
        } else showToast(res.error || 'Gagal', 'error');
    }

    // ==========================================
    // CHART ENGINE
    // ==========================================
    function layoutKey() { return STORAGE_KEYS.CHART_LAYOUT_PREFIX + (state.currentTabId || 'default'); }

    function saveChartLayout() {
        const layout = state.charts.map(c => ({
            id: c.id, widgetId: c.widgetId, title: c.title, deviceId: c.deviceId,
            chartType: c.chartType, showData: c.showData,
            x: c.x, y: c.y, w: c.w, h: c.h,
        }));
        try { localStorage.setItem(layoutKey(), JSON.stringify(layout)); } catch (e) {}
        try { localStorage.setItem(STORAGE_KEYS.CANVAS_HEIGHT, String(state.canvasHeight)); } catch (e) {}
    }

    function loadChartLayout() {
        try { return JSON.parse(localStorage.getItem(layoutKey()) || 'null'); } catch (e) { return null; }
    }

    function loadCanvasHeight() {
        try {
            const h = parseInt(localStorage.getItem(STORAGE_KEYS.CANVAS_HEIGHT));
            if (h && h >= 300 && h <= 3000) state.canvasHeight = h;
        } catch (e) {}
    }

    function applyChartGeom(c) {
        const el = document.getElementById(c.id);
        if (!el) return;
        el.style.left = c.x + 'px';
        el.style.top = c.y + 'px';
        el.style.width = c.w + 'px';
        el.style.height = c.h + 'px';
    }

    function applyAllGeom() { state.charts.forEach(applyChartGeom); }

    function getRect(c) {
        return { left: c.x, top: c.y, right: c.x + c.w, bottom: c.y + c.h };
    }

    function rectsOverlap(a, b) {
        return !(a.right <= b.left || a.left >= b.right || a.bottom <= b.top || a.top >= b.bottom);
    }

    function resolveCollisions() {
        if (state.charts.length < 2) return;
        const sorted = [...state.charts].sort((a, b) => a.y - b.y);
        let changed = true;
        let iter = 0;
        while (changed && iter < 30) {
            changed = false;
            iter++;
            for (let i = 0; i < sorted.length; i++) {
                const a = sorted[i];
                const aRect = getRect(a);
                for (let j = i + 1; j < sorted.length; j++) {
                    const b = sorted[j];
                    const bRect = getRect(b);
                    if (rectsOverlap(aRect, bRect)) {
                        b.y = aRect.bottom + GAP;
                        bRect.top = b.y;
                        bRect.bottom = b.y + bRect.height;
                        changed = true;
                    }
                }
            }
        }
    }

    function clampChartsToCanvas() {
        const grid = $('chartsGrid');
        if (!grid) return;
        const canvasW = grid.clientWidth;
        const maxW = Math.max(MIN_W, canvasW - PADDING * 2);
        const limit = canvasW - PADDING;

        state.charts.forEach(c => {
            if (c.w > maxW) c.w = maxW;
            if (c.x < PADDING) c.x = PADDING;
            if (c.x + c.w > limit) c.x = Math.max(PADDING, limit - c.w);
            if (c.y < PADDING) c.y = PADDING;
        });
    }

    function autoGrowCanvas() {
        const grid = $('chartsGrid');
        if (!grid) return;
        let maxBottom = 0;
        state.charts.forEach(c => { maxBottom = Math.max(maxBottom, c.y + c.h); });
        const needed = maxBottom + PADDING * 2;
        if (needed > state.canvasHeight) {
            state.canvasHeight = needed;
            grid.style.height = needed + 'px';
        }
    }

    async function loadTabCharts(tabId) {
        if (!tabId) return;
        const store = window.DashboardStore;
        const dashboardId = store.state.currentDashboardId;
        if (!dashboardId) return;
        const res = await API.call(`/api/v1/dashboards/${dashboardId}/analytics-tabs/${tabId}/widgets`);
        const widgets = res.success ? (res.data.widgets || []) : [];
        console.log('[Charts] Loaded widgets:', widgets.length);

        state.charts.forEach(c => {
            if (c.chartInstance) { stopRace(c.chartInstance); try { const i=echarts.getInstanceByDom(c.chartInstance); if(i) i.dispose(); } catch(e){} try{ if(c.chartInstance._ro){c.chartInstance._ro.disconnect(); c.chartInstance._ro=null;} }catch(e){} }
            const el = document.getElementById(c.id);
            if (el) { try { interact(el).unset(); } catch (e) {} el.remove(); }
        });
        state.charts = [];

        const grid = $('chartsGrid');
        if (grid) {
            grid.innerHTML = '';
            grid.style.height = state.canvasHeight + 'px';
        }

        if (widgets.length === 0) {
            if (grid) grid.innerHTML = `<div class="empty-charts" style="text-align:center;padding:40px;color:var(--text-3);"><i class="fa-solid fa-chart-column" style="font-size:40px;margin-bottom:12px;display:block;opacity:.4;"></i><p style="font-size:14px;font-weight:600;">Belum ada diagram di tab ini</p></div>`;
            return;
        }

        const savedLayout = loadChartLayout() || {};
        const savedMap = {};
        if (Array.isArray(savedLayout)) savedLayout.forEach(s => { savedMap[s.id] = s; });

        widgets.forEach((w, idx) => {
            const saved = savedMap[`chart_${w.id}`];
            let x, y, cw, ch;
            if (saved && typeof saved.x === 'number') {
                x = saved.x; y = saved.y;
                cw = saved.w || DEFAULT_W;
                ch = saved.h || DEFAULT_H;
            } else {
                const col = idx % 2;
                const row = Math.floor(idx / 2);
                x = PADDING + col * (DEFAULT_W + GAP);
                y = PADDING + row * (DEFAULT_H + GAP);
                cw = DEFAULT_W;
                ch = DEFAULT_H;
            }
            const wConfig = w.config || {};
            const deviceIds = Array.isArray(wConfig.devices) && wConfig.devices.length > 0
                ? wConfig.devices
                : (w.device_id ? [w.device_id] : []);

            const config = {
                id: `chart_${w.id}`,
                widgetId: w.id,
                title: w.title,
                deviceIds,
                chartType: store.mapWidgetTypeToChartType(w.widget_type),
                showData: wConfig.show_data || {},
                x, y, w: cw, h: ch,
                chartInstance: null,
            };
            state.charts.push(config);
            state.chartIdCounter = Math.max(state.chartIdCounter, w.id);
        });

        state.charts.forEach(c => renderChartCard(c));
        applyGraphSearch();
        clampChartsToCanvas();
        resolveCollisions();
        applyAllGeom();
        autoGrowCanvas();
        await loadAllChartDataBatched();
    }

    function applyGraphSearch() {
        const term = (state.graphSearchTerm || '').toLowerCase().trim();
        const grid = $('chartsGrid');
        let visible = 0;
        state.charts.forEach(c => {
            const el = document.getElementById(c.id);
            if (!el) return;
            if (!term) { el.style.display = ''; visible++; return; }
            const hay = [c.title, ...(c.deviceIds || []).flatMap(did => {
                const d = state.devices.find(x => x.device_id === did);
                return [did, d ? d.device_name : ''];
            }), ...Object.keys(c.showData || {}).filter(k => c.showData[k]).flatMap(k => [k, DATA_KEYS[k] ? DATA_KEYS[k].label : ''])]
                .join(' ').toLowerCase();
            const match = hay.includes(term);
            el.style.display = match ? '' : 'none';
            if (match) visible++;
        });
        if (grid) {
            let note = grid.querySelector('.graph-no-result');
            if (term && state.charts.length > 0 && visible === 0) {
                if (!note) { note = document.createElement('div'); note.className = 'graph-no-result empty-charts'; note.style.cssText = 'text-align:center;padding:40px;color:var(--text-3);'; grid.appendChild(note); }
                note.textContent = 'Tidak ada diagram yang cocok';
            } else if (note) note.remove();
        }
    }

    function renderChartCard(config) {
        const grid = $('chartsGrid');
        if (!grid) return;
        const emptyEl = grid.querySelector('.empty-charts');
        if (emptyEl) emptyEl.remove();

        const card = document.createElement('div');
        card.className = 'chart-card';
        card.id = config.id;
        card.style.left = config.x + 'px';
        card.style.top = config.y + 'px';
        card.style.width = config.w + 'px';
        card.style.height = config.h + 'px';

        const dataLabels = Object.entries(config.showData).filter(([_, v]) => v).map(([k]) => DATA_KEYS[k]?.label || k).join(', ');
        const deviceNamesStr = (config.deviceIds || []).map(did => state.devices.find(d => d.device_id === did)?.device_name || did).join(', ');

        card.innerHTML = `
            <div class="chart-card-header">
                <div class="chart-card-title">
                    <i class="fa-solid fa-chart-line"></i>
                    <span>${escapeHtml(config.title)}</span>
                    <span class="chart-meta">(${escapeHtml(deviceNamesStr)} - ${escapeHtml(dataLabels)})</span>
                </div>
                <div class="chart-actions">
                    <button class="chart-action-btn" data-action="edit" title="Edit"><i class="fa-solid fa-pen"></i></button>
                    <button class="chart-action-btn remove" data-action="remove" title="Hapus"><i class="fa-solid fa-trash"></i></button>
                </div>
            </div>
            <div class="chart-card-body">
                <div class="chart-canvas-container">
                    <div id="${config.id}_canvas" class="echart" style="width:100%;height:100%;"></div>
                </div>
            </div>
            <div class="chart-card-resize"></div>
        `;

        grid.appendChild(card);

        card.querySelector('[data-action="edit"]').addEventListener('click', e => { e.stopPropagation(); e.preventDefault(); openEditChartModal(config.id); });
        card.querySelector('[data-action="remove"]').addEventListener('click', e => { e.stopPropagation(); e.preventDefault(); removeChart(config.id); });

        initializeDragResize(config.id);
    }

    function initializeDragResize(chartId) {
        const el = document.getElementById(chartId);
        if (!el) return;
        if (typeof interact === 'undefined') {
            console.warn('[Chart] interact.js tidak dimuat, drag/resize dimatikan');
            return;
        }

        let dragState = null;
        let autoScrollRAF = null;

        function stopAutoScroll() {
            if (autoScrollRAF) {
                cancelAnimationFrame(autoScrollRAF);
                autoScrollRAF = null;
            }
        }

        function startAutoScroll() {
            stopAutoScroll();

            function loop() {
                autoScrollRAF = null;
                if (!dragState) return;

                const grid = $('chartsGrid');
                const c = state.charts.find(x => x.id === chartId);
                if (!grid || !c) {
                    autoScrollRAF = requestAnimationFrame(loop);
                    return;
                }

                const gridRect = grid.getBoundingClientRect();
                const y = dragState.lastY;
                const margin = 70;
                const maxSpeed = 16;

                let scrollDelta = 0;

                if (y > gridRect.bottom - margin) {
                    const t = Math.min(1, (y - (gridRect.bottom - margin)) / margin);
                    scrollDelta = maxSpeed * t;
                } else if (y < gridRect.top + margin) {
                    const t = Math.min(1, ((gridRect.top + margin) - y) / margin);
                    scrollDelta = -maxSpeed * t;
                }

                if (scrollDelta !== 0) {
                    const before = grid.scrollTop;
                    grid.scrollTop += scrollDelta;
                    const actual = grid.scrollTop - before;

                    if (actual !== 0) {
                        c.y = Math.max(PADDING, c.y + actual);
                        el.style.top = c.y + 'px';

                        if (c.y + c.h + PADDING > state.canvasHeight) {
                            state.canvasHeight = c.y + c.h + PADDING;
                            grid.style.height = state.canvasHeight + 'px';
                        }
                    }
                }

                autoScrollRAF = requestAnimationFrame(loop);
            }

            autoScrollRAF = requestAnimationFrame(loop);
        }

        interact(el)
            .draggable({
                allowFrom: '.chart-card-header',
                ignoreFrom: '.chart-actions',
                inertia: false,
                listeners: {
                    start(event) {
                        el.classList.add('dragging');
                        const elRect = el.getBoundingClientRect();
                        dragState = {
                            offsetX: event.clientX - elRect.left,
                            offsetY: event.clientY - elRect.top,
                            lastY: event.clientY,
                        };
                        startAutoScroll();
                    },
                    move(event) {
                        const c = state.charts.find(x => x.id === chartId);
                        if (!c || !dragState) return;
                        const grid = $('chartsGrid');
                        const gridRect = grid.getBoundingClientRect();
                        const newLeft = event.clientX - dragState.offsetX - gridRect.left + grid.scrollLeft;
                        const newTop = event.clientY - dragState.offsetY - gridRect.top + grid.scrollTop;
                        c.x = Math.max(PADDING, newLeft);
                        c.y = Math.max(PADDING, newTop);
                        el.style.left = c.x + 'px';
                        el.style.top = c.y + 'px';
                        dragState.lastY = event.clientY;
                    },
                    end() {
                        el.classList.remove('dragging');
                        stopAutoScroll();
                        dragState = null;
                        clampChartsToCanvas();
                        resolveCollisions();
                        applyAllGeom();
                        autoGrowCanvas();
                        saveChartLayout();
                    }
                }
            })
            .resizable({
                edges: { right: true, bottom: true, left: false, top: false },
                inertia: false,
                modifiers: [interact.modifiers.restrictSize({ min: { width: MIN_W, height: MIN_H } })],
                listeners: {
                    start() { el.classList.add('resizing'); },
                    move(event) {
                        const c = state.charts.find(x => x.id === chartId);
                        if (!c) return;
                        const grid = $('chartsGrid');
                        const canvasW = grid ? grid.clientWidth : 1000;
                        const maxW = Math.max(MIN_W, canvasW - c.x - PADDING);
                        c.w = Math.min(event.rect.width, maxW);
                        c.h = event.rect.height;
                        el.style.width = c.w + 'px';
                        el.style.height = c.h + 'px';
                        if (c.chartInstance) try { const i=echarts.getInstanceByDom(c.chartInstance); if(i) i.resize(); } catch (e) {}
                    },
                    end() {
                        el.classList.remove('resizing');
                        clampChartsToCanvas();
                        resolveCollisions();
                        applyAllGeom();
                        autoGrowCanvas();
                        saveChartLayout();
                    }
                }
            });
    }

    function bindGridResize() {
        const handle = document.querySelector('.charts-grid-resize-handle');
        const grid = $('chartsGrid');
        if (!handle || !grid) return;

        grid.style.height = state.canvasHeight + 'px';

        let startY = 0, startH = 0;

        function start(clientY) {
            startY = clientY;
            startH = grid.clientHeight;
            handle.classList.add('dragging');
            document.body.style.cursor = 'ns-resize';
            document.body.style.userSelect = 'none';
        }
        function move(clientY) {
            const delta = clientY - startY;
            const newH = Math.min(Math.max(startH + delta, 300), 3000);
            grid.style.height = newH + 'px';
            state.canvasHeight = newH;
        }
        function end() {
            handle.classList.remove('dragging');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            saveChartLayout();
        }

        handle.addEventListener('mousedown', e => {
            e.preventDefault();
            start(e.clientY);
            const onMove = ev => move(ev.clientY);
            const onUp = () => { end(); document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
        handle.addEventListener('touchstart', e => {
            start(e.touches[0].clientY);
            const onMove = ev => move(ev.touches[0].clientY);
            const onEnd = () => { end(); document.removeEventListener('touchmove', onMove); document.removeEventListener('touchend', onEnd); };
            document.addEventListener('touchmove', onMove, { passive: true });
            document.addEventListener('touchend', onEnd);
        }, { passive: true });
    }

    function generateDeviceCheckboxes(selectedDeviceIds = []) {
        const container = $('chartDeviceCheckboxes');
        if (!container) return;
        if (state.devices.length === 0) {
            container.innerHTML = '<div style="padding:12px;color:var(--text-3);font-size:12px;grid-column:1/-1;">Belum ada perangkat. Tambah dulu di menu Perangkat.</div>';
            return;
        }
        const selectedSet = new Set(selectedDeviceIds);
        container.innerHTML = state.devices.map(d => `
            <label class="checkbox-item">
                <input type="checkbox" class="chart-device-checkbox"
                       data-device-id="${escapeHtml(d.device_id)}"
                       ${selectedSet.has(d.device_id) ? 'checked' : ''}>
                <span>${escapeHtml(d.device_name)}
                    <span style="color:var(--text-3);font-family:var(--mono);font-size:10px;">(${escapeHtml(d.device_id)})</span>
                </span>
            </label>
        `).join('');
    }

    function generateDataCheckboxes(selected = {}) {
        const container = $('chartDataCheckboxes'); if (!container) return;
        container.innerHTML = Object.entries(DATA_KEYS).map(([key, info]) => `<label class="checkbox-item"><input type="checkbox" class="chart-data-checkbox" data-key="${key}" ${selected[key] ? 'checked' : ''}><span class="data-color" style="background:${info.color};"></span><span>${escapeHtml(info.label)} (${escapeHtml(info.unit)})</span></label>`).join('');
    }

    function openAddChartModal() {
        if (!state.currentTabId) { showToast('Buat tab analitik dulu', 'warning'); return; }
        const titleEl = $('chartModalTitle');
        const editEl = $('editChartId');
        const chartTitleEl = $('chartTitle');
        if (titleEl) titleEl.textContent = 'Tambah Diagram';
        if (editEl) editEl.value = '';
        if (chartTitleEl) chartTitleEl.value = '';
        generateDeviceCheckboxes([]);
        const typeEl = $('chartTypeSelect'); if (typeEl) typeEl.value = 'line';
        generateDataCheckboxes({ temperature: true });
        openModal('chartModal');
    }

    function openEditChartModal(chartId) {
        const chart = state.charts.find(c => c.id === chartId);
        if (!chart) return;
        const titleEl = $('chartModalTitle');
        const editEl = $('editChartId');
        const chartTitleEl = $('chartTitle');
        if (titleEl) titleEl.textContent = 'Edit Diagram';
        if (editEl) editEl.value = chartId;
        if (chartTitleEl) chartTitleEl.value = chart.title;
        generateDeviceCheckboxes(chart.deviceIds || []);
        const typeEl = $('chartTypeSelect'); if (typeEl) typeEl.value = chart.chartType;
        generateDataCheckboxes(chart.showData);
        openModal('chartModal');
    }

    async function saveChart() {
        const editId = ($('editChartId') || {}).value;
        const title = (($('chartTitle') || {}).value || '').trim() || 'Diagram';
        const chartType = ($('chartTypeSelect') || {}).value;

        const deviceIds = [];
        document.querySelectorAll('#chartDeviceCheckboxes .chart-device-checkbox').forEach(cb => {
            if (cb.checked) deviceIds.push(cb.dataset.deviceId);
        });

        const showData = {};
        document.querySelectorAll('#chartDataCheckboxes .chart-data-checkbox').forEach(cb => {
            showData[cb.dataset.key] = cb.checked;
        });

        if (deviceIds.length === 0) { showToast('Pilih minimal 1 perangkat', 'error'); return; }
        if (!Object.values(showData).some(v => v)) { showToast('Pilih minimal 1 jenis data', 'error'); return; }

        const store = window.DashboardStore;
        const dashboardId = store.state.currentDashboardId;
        const widgetType = store.mapChartTypeToWidgetType(chartType);

        const widgetConfig = {
            show_data: showData,
            devices: deviceIds,
        };

        if (editId) {
            const chart = state.charts.find(c => c.id === editId);
            if (!chart) return;

            const res = await API.call(`/api/v1/widgets/${chart.widgetId}`, {
                method: 'PUT',
                body: JSON.stringify({
                    title,
                    device_id: deviceIds[0],
                    widget_type: widgetType,
                    config: widgetConfig,
                }),
            });
            if (!res.success) { showToast(res.error || 'Gagal', 'error'); return; }

            chart.title = title;
            chart.deviceIds = deviceIds;
            chart.chartType = chartType;
            chart.showData = showData;

            if (chart.chartInstance) { try { const i=echarts.getInstanceByDom(chart.chartInstance); if(i) i.dispose(); } catch(e){} try{ if(chart.chartInstance._ro){chart.chartInstance._ro.disconnect(); chart.chartInstance._ro=null;} }catch(e){} chart.chartInstance = null; }

            const card = document.getElementById(editId);
            if (card) {
                const dataLabels = Object.entries(showData).filter(([_, v]) => v).map(([k]) => DATA_KEYS[k]?.label || k).join(', ');
                const deviceNamesStr = deviceIds.map(did => state.devices.find(d => d.device_id === did)?.device_name || did).join(', ');
                card.querySelector('.chart-card-title').innerHTML =
                    `<i class="fa-solid fa-chart-line"></i><span>${escapeHtml(title)}</span><span class="chart-meta">(${escapeHtml(deviceNamesStr)} - ${escapeHtml(dataLabels)})</span>`;
            }
            await loadDynamicChartData(chart);
            showToast('Diagram diupdate', 'success');
        } else {
            const res = await API.call(`/api/v1/dashboards/${dashboardId}/widgets`, {
                method: 'POST',
                body: JSON.stringify({
                    widget_type: widgetType,
                    title,
                    device_id: deviceIds[0],
                    config: widgetConfig,
                    grid_x: 0, grid_y: 0, grid_w: 6, grid_h: 2,
                    analytics_tab_id: state.currentTabId,
                }),
            });
            if (!res.success) { showToast(res.error || 'Gagal', 'error'); return; }
            await loadTabCharts(state.currentTabId);
            showToast('Diagram ditambahkan', 'success');
        }
        closeModal('chartModal');
    }

    async function loadDynamicChartData(config) {
        const deviceIds = config.deviceIds || [];
        if (deviceIds.length === 0) { showChartEmpty(config.id, 'Belum ada device dipilih'); return; }
        const hours = Math.max(1, Math.ceil(state.globalTimeMinutes / 60));
        const limit = Math.min(Math.max(hours * 60, 500), 5000);
        try {
            const results = await Promise.all(deviceIds.map(did =>
                API.getDeviceHistory(did, { hours, limit }).then(r => ({ did, result: r }))
            ));
            const historyByDevice = {};
            results.forEach(({ did, result }) => {
                historyByDevice[did] = result.success ? (result.data.history || []) : [];
            });
            renderChartDataSync(config, historyByDevice);
        } catch (e) { console.error('[Chart]', e); }
    }

    async function loadAllChartDataBatched() {
        if (state.charts.length === 0) return;

        const uniqueDevices = new Set();
        state.charts.forEach(c => {
            (c.deviceIds || []).forEach(did => uniqueDevices.add(did));
        });
        if (uniqueDevices.size === 0) return;

        const hours = Math.max(1, Math.ceil(state.globalTimeMinutes / 60));
        const limit = Math.min(Math.max(hours * 60, 500), 5000);

        const fetchResults = await Promise.all(
            Array.from(uniqueDevices).map(did =>
                API.getDeviceHistory(did, { hours, limit }).then(r => ({ did, result: r }))
            )
        );
        const historyByDevice = {};
        fetchResults.forEach(({ did, result }) => {
            historyByDevice[did] = result.success ? (result.data.history || []) : [];
        });

        state.charts.forEach(c => {
            const chartHistory = {};
            (c.deviceIds || []).forEach(did => { chartHistory[did] = historyByDevice[did] || []; });
            try { renderChartDataSync(c, chartHistory); } catch (e) { console.error(e); }
        });
    }

    function renderChartDataSync(config, historyByDevice) {
        let plotEl = document.getElementById(`${config.id}_canvas`);
        const card = document.getElementById(config.id);
        const container = card && card.querySelector('.chart-canvas-container');
        if (!container) return;
        if (!plotEl || plotEl.tagName === 'CANVAS') {
            container.innerHTML = `<div id="${config.id}_canvas" class="echart" style="width:100%;height:100%;"></div>`;
            plotEl = document.getElementById(`${config.id}_canvas`);
        }
        if (typeof echarts === 'undefined') { showChartEmpty(config.id, 'ECharts gagal dimuat. Cek koneksi internet/CDN.'); return; }

        stopRace(plotEl);
        if (config.chartInstance) { try { const i=echarts.getInstanceByDom(config.chartInstance); if(i) i.dispose(); } catch(e){} try{ if(config.chartInstance._ro){config.chartInstance._ro.disconnect(); config.chartInstance._ro=null;} }catch(e){} }
        config.chartInstance = null;

        const colors = getChartColors();
        const deviceIds = config.deviceIds || [];
        const activeKeys = Object.entries(config.showData || {}).filter(([_, v]) => v).map(([k]) => k);
        const isGauge = ['doughnut', 'pie', 'polarArea', 'radar', 'halfDoughnut'].includes(config.chartType);
        const font = CHART_FONT;
        const chart = ensureEChart(plotEl);
        if(!chart) return;
        const bg = getComputedStyle(document.documentElement).getPropertyValue('--bg-card').trim() || (document.documentElement.getAttribute('data-theme')==='light'?'#fff':'#141414');

        if (isGauge) {
            const gaugeLabels = [], gaugeValues = [];
            deviceIds.forEach(did => {
                const hist = historyByDevice[did] || [];
                if (hist.length === 0) return;
                const latest = hist[hist.length - 1];
                const dname = state.devices.find(d => d.device_id === did)?.device_name || did;
                activeKeys.forEach(key => {
                    const info = DATA_KEYS[key];
                    if (!info) return;
                    const val = latest.data?.[key];
                    if (val !== null && val !== undefined) {
                        gaugeLabels.push(deviceIds.length > 1 ? `${dname} — ${info.label}` : info.label);
                        gaugeValues.push(val);
                    }
                });
            });
            if (gaugeValues.length === 0) { showChartEmpty(config.id, 'Tidak ada data terbaru'); return; }
            const pal = gaugeValues.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]);
            const data = gaugeLabels.map((n,i)=>({name:n,value:gaugeValues[i],itemStyle:{color:pal[i]}}));
            let opt;
            if (config.chartType === 'doughnut' || config.chartType === 'halfDoughnut') {
                const isHalf = config.chartType === 'halfDoughnut';
                opt = {
                    animation:false, textStyle:{fontFamily:font},
                    tooltip:{trigger:'item',appendToBody:true,confine:true},
                    legend:{type:'scroll', bottom:0, textStyle:{color:colors.legendColor,fontSize:10}},
                    series:[{
                        type:'pie',
                        radius: isHalf ? ['42%','78%'] : ['38%','68%'],
                        center: isHalf ? ['50%','72%'] : ['50%','45%'],
                        startAngle: isHalf ? 180 : 90,
                        endAngle: isHalf ? 360 : -270,
                        padAngle: 2, itemStyle:{borderRadius:8, borderColor:bg, borderWidth:2},
                        data, label:{show:false}, emphasis:{itemStyle:{shadowBlur:8}}
                    }]
                };
            } else if (config.chartType === 'pie') {
                opt = { animation:false, textStyle:{fontFamily:font}, tooltip:{trigger:'item',appendToBody:true,confine:true}, legend:{ type:'scroll', orient:'vertical', right:0, top:'center', textStyle:{color:colors.legendColor,fontSize:10} }, series:[{type:'pie',radius:'58%',center:['32%','50%'],data,label:{show:false},emphasis:{itemStyle:{shadowBlur:8}}, itemStyle:{borderRadius:4, borderColor:bg, borderWidth:1}}] };
            } else if (config.chartType === 'polarArea') {
                opt = { animation:false, textStyle:{fontFamily:font}, polar:{radius:'65%'}, angleAxis:{type:'category',data:gaugeLabels,axisLabel:{color:colors.labelColor,fontSize:9}}, radiusAxis:{axisLabel:{color:colors.labelColor},splitLine:{lineStyle:{color:colors.gridColor}}}, series:[{type:'bar',data:gaugeValues.map((v,i)=>({value:v,itemStyle:{color:pal[i]}})),coordinateSystem:'polar'}], tooltip:{} };
            } else { // radar (unchanged)
                const max = Math.max(...gaugeValues, 1);
                opt = { animation:false, textStyle:{fontFamily:font}, radar:{indicator:gaugeLabels.map(n=>({name:n,max:max*1.2})),axisName:{color:colors.labelColor,fontSize:9},splitLine:{lineStyle:{color:colors.gridColor}},splitArea:{show:false}}, series:[{type:'radar',data:[{value:gaugeValues,areaStyle:{color:pal[0]+'33'},lineStyle:{color:pal[0]},itemStyle:{color:pal[0]}}]}], tooltip:{} };
            }
            chart.setOption(opt,{notMerge:true,lazyUpdate:true});
            config.chartInstance = plotEl;
            return;
        }

        const timestampSet = new Set();
        deviceIds.forEach(did => { (historyByDevice[did] || []).forEach(item => timestampSet.add(item.timestamp)); });
        if (timestampSet.size === 0) { showChartEmpty(config.id, 'Menunggu data sensor...'); return; }
        const now = Date.now();
        const cutoff = now - state.globalTimeMinutes * 60 * 1000;
        const allTs = Array.from(timestampSet).sort();
        const inRange = allTs.filter(ts => { const d = parseDate(ts); return d && d.getTime() >= cutoff; });
        const usedTs = downsampleHistory(inRange.length > 0 ? inRange : allTs, 360);
        if (usedTs.length === 0) { showChartEmpty(config.id, 'Menunggu data sensor...'); return; }

        // Bar Race (bar vertikal / horizontalBar horizontal) — snapshot real data, animasi saat update
        if (config.chartType === 'bar' || config.chartType === 'horizontalBar') {
            const catInfo = [];
            deviceIds.forEach(did => {
                const hist = historyByDevice[did] || [];
                const dname = state.devices.find(d => d.device_id === did)?.device_name || did;
                const tsMap = {}; hist.forEach(it => { tsMap[it.timestamp] = it.data || {}; });
                activeKeys.forEach(key => {
                    const info = DATA_KEYS[key]; if(!info) return;
                    let val = null;
                    for (let i = usedTs.length - 1; i >= 0; i--) {
                        const o = tsMap[usedTs[i]];
                        const v = o ? (o[key] ?? o[key.toLowerCase()] ?? o[key.toUpperCase()]) : null;
                        if (v !== null && v !== undefined && typeof v === 'number' && isFinite(v)) { val = v; break; }
                    }
                    if (val === null) return;
                    const label = deviceIds.length > 1 ? `${dname} — ${info.label}` : info.label;
                    catInfo.push({ name: label, value: val, color: CHART_COLORS[catInfo.length % CHART_COLORS.length] });
                });
            });
            if (catInfo.length === 0) { showChartEmpty(config.id, 'Tidak ada data sensor yang cocok'); return; }
            const isH = config.chartType === 'horizontalBar';
            const pairs = catInfo.sort((a,b)=>b.value-a.value).slice(0,10);
            const names = pairs.map(p=>p.name), values = pairs.map(p=>p.value), cols = pairs.map(p=>p.color);
            const data = values.map((v,i)=>({value:v,itemStyle:{color:cols[i],borderRadius:isH?[0,6,6,0]:[6,6,0,0]}}));
            chart.setOption({
                animation: true, animationDuration: 400, animationDurationUpdate: 700, animationEasingUpdate: 'cubicOut',
                grid:{left:isH?8:8,right:isH?56:12,top:isH?12:28,bottom:isH?8:8,containLabel:true},
                xAxis: isH ? {type:'value',axisLabel:{color:colors.labelColor},splitLine:{lineStyle:{color:colors.gridColor}}} : {type:'category',data:names,axisLabel:{color:colors.labelColor,fontSize:10,interval:0,rotate:names.length>4?20:0},axisLine:{show:false},axisTick:{show:false}},
                yAxis: isH ? {type:'category',data:names,inverse:true,axisLabel:{color:colors.labelColor,fontSize:10},axisLine:{show:false},axisTick:{show:false}} : {type:'value',axisLabel:{color:colors.labelColor},splitLine:{lineStyle:{color:colors.gridColor}}},
                series:[{type:'bar',data,barMaxWidth:28,label:{show:true,position:isH?'right':'top',color:colors.labelColor,fontSize:10,formatter:'{c}'},labelLayout:{hideOverlap:true}}],
                tooltip:{trigger:'item',appendToBody:true,confine:true}
            }, {notMerge:true,lazyUpdate:false});
            config.chartInstance = plotEl;
            return;
        }


        // Time-series: line (smoothed), area (gradient stacked), stackedArea (gradient stacked), stackedBar (unchanged)
        const series = [];
        let colorIdx = 0;
        deviceIds.forEach(did => {
            const hist = historyByDevice[did] || [];
            if (hist.length === 0) return;
            const dname = state.devices.find(d => d.device_id === did)?.device_name || did;
            const tsMap = {};
            hist.forEach(item => { tsMap[item.timestamp] = item.data || {}; });
            activeKeys.forEach(key => {
                const info = DATA_KEYS[key];
                if (!info) return;
                const data = usedTs.map(ts => {
                    const obj = tsMap[ts];
                    const v = obj ? (obj[key] ?? obj[key.toLowerCase()] ?? obj[key.toUpperCase()]) : null;
                    const t = String(ts).replace(' ','T'); const dt = new Date(/[+-]\d\d:\d\d$|Z$/.test(t)?t:t+'+07:00'); const ms = dt.getTime();
                    return (ms && !isNaN(ms)) ? [ms, (v===null||v===undefined)?null:v] : null;
                }).filter(Boolean);
                if (!data.some(p => p[1] !== null && p[1] !== undefined)) return;
                const color = CHART_COLORS[colorIdx % CHART_COLORS.length]; colorIdx++;
                const isAreaType = config.chartType === 'area' || config.chartType === 'stackedArea';
                const isStacked = config.chartType === 'stackedBar' || config.chartType === 'stackedArea';
                const isBarType = config.chartType === 'stackedBar';
                const label = deviceIds.length > 1 ? `${dname} — ${info.label}` : `${info.label} (${info.unit})`;
                if (isBarType) {
                    series.push({ name: label, type:'bar', data, stack: isStacked?'s':undefined, itemStyle:{color}, barMaxWidth:28, emphasis:{focus:'series'} });
                } else {
                    const grad = { type:'linear', x:0,y:0,x2:0,y2:1, colorStops:[{offset:0,color:color+'55'},{offset:1,color:color+'05'}] };
                    series.push({
                        name: label, type:'line', data,
                        showSymbol:false, smooth:true, sampling:'lttb', connectNulls:true,
                        lineStyle:{width:2,color}, itemStyle:{color},
                        areaStyle: isAreaType ? { color: grad } : undefined,
                        stack: (isAreaType && isStacked) ? 'a' : undefined,
                        emphasis:{focus:'series'}
                    });
                }
            });
        });
        if (series.length === 0) { showChartEmpty(config.id, 'Tidak ada data sensor yang cocok'); return; }
        const isBarType = config.chartType === 'stackedBar';
        chart.setOption({
            animation:false, textStyle:{fontFamily:font},
            grid:{left:8,right:12,top:28,bottom:8,containLabel:true},
            tooltip:{trigger:'axis',confine:true,appendToBody:true},
            legend:{type:'scroll', top:0, textStyle:{color:colors.legendColor,fontSize:10}, pageIconSize:10, pageTextStyle:{color:colors.legendColor}},
            xAxis:{type:'time', splitLine:{show:false}, axisLabel:{color:colors.labelColor,fontSize:10,fontFamily:font, hideOverlap:true}},
            yAxis:{type:'value', splitLine:{lineStyle:{color:colors.gridColor}}, axisLabel:{color:colors.labelColor,fontSize:10,fontFamily:font}},
            series,
        }, {notMerge:true,lazyUpdate:true});
        config.chartInstance = plotEl;
    }

    function showChartEmpty(chartId, message) {
        const card = document.getElementById(chartId); if (!card) return;
        const container = card.querySelector('.chart-canvas-container'); if (!container) return;
        const plot = document.getElementById(`${chartId}_canvas`);
        if (plot) { stopRace(plot); try { const i=echarts.getInstanceByDom(plot); if(i) i.dispose(); } catch(e){} try{ if(plot._ro){plot._ro.disconnect(); plot._ro=null;} }catch(e){} }
        container.innerHTML = `<div style="text-align:center;padding:20px;color:var(--text-3);font-size:12px;display:flex;flex-direction:column;align-items:center;gap:8px;height:100%;justify-content:center;"><i class="fa-solid fa-satellite-dish" style="font-size:20px;opacity:0.5;"></i><span>${escapeHtml(message)}</span></div>`;
    }

    function refreshAllCharts() {
        if (state.refreshTimeout) clearTimeout(state.refreshTimeout);
        state.refreshTimeout = setTimeout(() => { loadAllChartDataBatched(); }, 300);
    }

    function startAutoRefresh() {
        if (state.autoRefreshInterval) clearInterval(state.autoRefreshInterval);
        state.autoRefreshInterval = setInterval(() => {
            const graph = $('graphSection');
            if (graph && graph.style.display !== 'none') refreshAllCharts();
        }, 15000);
    }

    function setGlobalTimeRange(minutes) {
        state.globalTimeMinutes = minutes;
        localStorage.setItem(STORAGE_KEYS.GLOBAL_TIME, minutes);
        $$('.time-range-item').forEach(item => item.classList.toggle('active', parseInt(item.dataset.minutes) === minutes));
        const labelEl = $('timeRangeLabel'); if (labelEl) labelEl.textContent = formatTimeRange(minutes);
        refreshAllCharts();
    }

    function loadGlobalTimeRange() {
        const saved = localStorage.getItem(STORAGE_KEYS.GLOBAL_TIME);
        if (saved) state.globalTimeMinutes = parseInt(saved);
        $$('.time-range-item').forEach(item => item.classList.toggle('active', parseInt(item.dataset.minutes) === state.globalTimeMinutes));
        const labelEl = $('timeRangeLabel'); if (labelEl) labelEl.textContent = formatTimeRange(state.globalTimeMinutes);
    }

    async function removeChart(chartId) {
        const idx = state.charts.findIndex(c => c.id === chartId); if (idx === -1) return;
        const chart = state.charts[idx];
        if (!confirm(`Hapus diagram "${chart.title}"?`)) return;
        await API.call(`/api/v1/widgets/${chart.widgetId}`, { method: 'DELETE' });
        if (chart.chartInstance) { stopRace(chart.chartInstance); try { const i=echarts.getInstanceByDom(chart.chartInstance); if(i) i.dispose(); } catch(e){} try{ if(chart.chartInstance._ro){chart.chartInstance._ro.disconnect(); chart.chartInstance._ro=null;} }catch(e){} }
        state.charts.splice(idx, 1);
        const card = document.getElementById(chartId);
        if (card) { try { interact(card).unset(); } catch (e) {} card.remove(); }
        if (state.charts.length === 0) {
            const grid = $('chartsGrid');
            if (grid) grid.innerHTML = `<div class="empty-charts" style="text-align:center;padding:40px;color:var(--text-3);"><i class="fa-solid fa-chart-column" style="font-size:40px;margin-bottom:12px;display:block;opacity:.4;"></i><p style="font-size:14px;font-weight:600;">Belum ada diagram di tab ini</p></div>`;
        }
        resolveCollisions();
        applyAllGeom();
        saveChartLayout();
        showToast('Diagram dihapus', 'success');
    }

    function resetChartLayout() {
        state.charts.forEach((c, i) => {
            const col = i % 2;
            const row = Math.floor(i / 2);
            c.x = PADDING + col * (DEFAULT_W + GAP);
            c.y = PADDING + row * (DEFAULT_H + GAP);
            c.w = DEFAULT_W;
            c.h = DEFAULT_H;
        });
        state.canvasHeight = 720;
        const grid = $('chartsGrid');
        if (grid) grid.style.height = '720px';
        clampChartsToCanvas();
        resolveCollisions();
        applyAllGeom();
        state.charts.forEach(c => { if (c.chartInstance) try { const i=echarts.getInstanceByDom(c.chartInstance); if(i) i.resize(); } catch (e) {} });
        try { localStorage.removeItem(layoutKey()); localStorage.removeItem(STORAGE_KEYS.CANVAS_HEIGHT); } catch (e) {}
        showToast('Layout direset', 'success');
    }

    // ==========================================
    // RESET ALERT RULES + SYSTEM INFO
    // ==========================================
    window.resetDeviceAlertRules = async function() {
        const deviceIdEl = $('editConfigDeviceId');
        const deviceId = deviceIdEl ? deviceIdEl.value : '';
        if (!deviceId) return;
        if (!confirm('Reset semua custom alert rules ke default global?\n\nSemua threshold custom untuk device ini akan dihapus.')) return;

        const result = await API.resetDeviceAlertRules(deviceId);
        if (result.success) {
            if (window.populateAlertRules) window.populateAlertRules('edit', null);
            showToast('Custom rules direset ke global', 'success');
            loadDashboard();
        } else {
            showToast(result.error || 'Gagal reset', 'error');
        }
    };

    async function openSystemInfo() {
        openModal('systemInfoModal');
        const body = $('systemInfoBody');
        if (!body) return;
        body.innerHTML = `<div class="loading" style="padding:32px;text-align:center;">
            <div class="spinner"></div>
            <div style="margin-top:10px;font-size:12.5px;color:var(--text-3);">Memuat...</div>
        </div>`;

        const result = await API.getSystemInfo();
        if (!result.success) {
            body.innerHTML = `<div class="empty-state" style="padding:32px;">
                <i class="fa-solid fa-triangle-exclamation" style="color:var(--accent-crit);"></i>
                <h3>Gagal memuat</h3>
                <p>${escapeHtml(result.error || 'Koneksi gagal')}</p>
            </div>`;
            return;
        }

        const info = result.data.info || {};
        const rows = [
            { label: 'Versi Aplikasi', value: info.version || '—', icon: 'fa-tag' },
            { label: 'Total Perangkat', value: info.device_count ?? 0, icon: 'fa-microchip' },
            { label: 'Total Data Sensor', value: (info.sensor_data_count ?? 0).toLocaleString('id-ID'), icon: 'fa-database' },
            { label: 'Alert Aktif', value: info.active_alerts ?? 0, icon: 'fa-bell', color: 'var(--accent-warn)' },
            { label: 'Riwayat Alert', value: (info.alert_history_count ?? 0).toLocaleString('id-ID'), icon: 'fa-clock-rotate-left' },
            { label: 'Ukuran Database', value: `${info.database_size_mb ?? 0} MB`, icon: 'fa-hard-drive' },
            { label: 'Retensi Data Sensor', value: `${info.data_retention_days ?? 30} hari`, icon: 'fa-calendar' },
        ];

        body.innerHTML = `
            <div class="info-list">
                ${rows.map(r => `
                    <div class="info-row">
                        <span class="info-label">
                            <i class="fa-solid ${r.icon}" style="width:14px;margin-right:6px;opacity:0.6;"></i>
                            ${escapeHtml(r.label)}
                        </span>
                        <span class="info-value mono" style="${r.color ? 'color:' + r.color + ';' : ''}">${escapeHtml(String(r.value))}</span>
                    </div>
                `).join('')}
            </div>
        `;
    }
    window.openSystemInfo = openSystemInfo;

    // ==========================================
    // DASHBOARD SWITCHER
    // ==========================================
    function isAdminMeta() {
        const m = document.querySelector('meta[name="is-admin"]');
        return !!m && m.content === '1';
    }
    function isViewAllMode() {
        return !!document.querySelector('meta[name="view-all"]');
    }

    function renderDashboardSwitcher() {
        const menu = $('dashboardSwitcherMenu');
        const listEl = $('dashboardSwitcherList');
        const labelEl = $('dashboardSwitcherLabel');
        const iconEl = $('dashboardSwitcherIcon');
        if (!menu || !listEl) return;

        const current = state.currentDashboardId;
        const items = state.dashboardsList || [];

        if (labelEl) {
            labelEl.textContent = isViewAllMode() ? 'Semua perangkat' : (state.currentDashboardName || 'Dashboard');
        }

        const curDash = items.find(d => d.id === current);
        state.currentDashboardRole = curDash ? curDash.role : null;
        document.body.classList.toggle('is-viewer',
            !isAdminMeta() && !!curDash && curDash.role === 'viewer');
        if (window.AAGuardUI) {
            AAGuardUI.applyNeeds({ isAdmin: isAdminMeta(), dashboardRole: curDash ? curDash.role : null,
                                 permissions: userState.permissions || [] });
        }
        if (window.AAGuardCommandPalette && typeof window.AAGuardCommandPalette.updateContext === 'function') {
            window.AAGuardCommandPalette.updateContext({
                isAdmin: isAdminMeta(),
                dashboardRole: curDash ? curDash.role : null,
                permissions: userState.permissions || [],
            });
        }
        if (iconEl) {
            const cls = 'fa-solid ' + (state.currentDashboardIcon || 'fa-layer-group');
            iconEl.className = cls;
            iconEl.style.color = 'var(--text-3)';
            iconEl.style.fontSize = '12px';
        }

        if (items.length === 0) {
            listEl.innerHTML = `<div class="dashboard-switcher-loading">
                <i class="fa-solid fa-spinner fa-spin"></i>
                <span>Memuat...</span>
            </div>`;
            return;
        }

        listEl.innerHTML = items.map(d => {
            const isActive = d.id === current && !isViewAllMode();
            const isDefault = d.is_default === 1;
            const icon = d.icon || 'fa-chart-line';
            const isOwn = d.role === 'owner' || isAdminMeta() && d.role === 'owner';
            const subtitle = isOwn
                ? escapeHtml(d.slug)
                : `dibagikan oleh ${escapeHtml(d.owner_name || '-')} · ${escapeHtml(d.role || 'viewer')}`;
            return `<div class="dashboard-switcher-item ${isActive ? 'active' : ''}"
                        data-dashboard-id="${d.id}"
                        data-dashboard-slug="${escapeHtml(d.slug)}">
                <i class="fa-solid ${escapeHtml(icon)} dashboard-switcher-item-icon"></i>
                <div class="dashboard-switcher-item-info">
                    <div class="dashboard-switcher-item-name">
                        ${escapeHtml(d.name)}
                        ${isDefault ? '<span class="dashboard-switcher-default-badge" title="Default">★</span>' : ''}
                    </div>
                    <div class="dashboard-switcher-item-slug">${subtitle}</div>
                </div>
                <div class="dashboard-switcher-item-actions">
                    ${isOwn ? `<button class="ds-action-btn" data-action="set-default"
                            title="Jadikan Default" data-dashboard-id="${d.id}">
                        <i class="fa-solid fa-star"></i>
                    </button>
                    <button class="ds-action-btn" data-action="edit"
                            title="Edit" data-dashboard-id="${d.id}">
                        <i class="fa-solid fa-pen"></i>
                    </button>` : ''}
                </div>
            </div>`;
        }).join('') + (isAdminMeta() ? `<div class="dashboard-switcher-item ${isViewAllMode() ? 'active' : ''}"
                        data-all-devices="1">
                <i class="fa-solid fa-globe dashboard-switcher-item-icon"></i>
                <div class="dashboard-switcher-item-info">
                    <div class="dashboard-switcher-item-name">Semua perangkat</div>
                    <div class="dashboard-switcher-item-slug">admin · semua dashboard &amp; pemilik</div>
                </div>
            </div>` : '');

        listEl.querySelectorAll('.dashboard-switcher-item').forEach(item => {
            item.addEventListener('click', (e) => {
                if (e.target.closest('[data-action]')) return;
                if (item.dataset.allDevices) { window.location.href = '/all'; return; }
                const id = parseInt(item.dataset.dashboardId, 10);
                const slug = item.dataset.dashboardSlug;
                switchDashboard(id, slug);
            });
        });

        listEl.querySelectorAll('[data-action="edit"]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const id = parseInt(btn.dataset.dashboardId, 10);
                openEditDashboardModal(id);
            });
        });
        listEl.querySelectorAll('[data-action="set-default"]').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const id = parseInt(btn.dataset.dashboardId, 10);
                if (id === current && state.dashboardsList.find(d => d.id === id)?.is_default === 1) {
                    showToast('Sudah menjadi default', 'info');
                    return;
                }
                const res = await API.call(`/api/v1/dashboards/${id}/set-default`, { method: 'POST' });
                if (res.success) {
                    showToast('Dashboard default diperbarui', 'success');
                    await refreshDashboardsList();
                } else {
                    showToast(res.error || 'Gagal', 'error');
                }
            });
        });
    }

    async function refreshDashboardsList() {
        const store = window.DashboardStore;
        if (!store) return;
        try {
            const list = await store.loadDashboards();
            state.dashboardsList = list || [];
            renderDashboardSwitcher();
        } catch (e) {
            console.error('[Dashboard] refresh list failed', e);
        }
    }

    function switchDashboard(id, slug) {
        const menu = $('dashboardSwitcherMenu');
        if (menu) menu.classList.remove('active');
        if (!isViewAllMode() && id === state.currentDashboardId) return;

        const targetIsDefault = (state.dashboardsList || []).find(d => d.id === id)?.is_default === 1;
        const targetUrl = targetIsDefault ? '/' : `/d/${encodeURIComponent(slug)}`;

        try { sessionStorage.setItem(STORAGE_KEYS.LAST_SECTION, state.currentSection); } catch (e) {}
        try { sessionStorage.removeItem(STORAGE_KEYS.CURRENT_TAB); } catch (e) {}

        window.location.href = targetUrl + (window.location.hash || '#dashboard');
    }

    function openCreateDashboardModal() {
        const modal = $('dashboardModal');
        if (!modal) return;
        const titleEl = $('dashboardModalTitle');
        const editEl = $('dashboardEditId');
        const delBtn = $('dashboardDeleteBtn');
        const defaultGroup = $('dashboardDefaultGroup');

        if (titleEl) titleEl.textContent = 'Dashboard Baru';
        if (editEl) editEl.value = '';
        if (delBtn) delBtn.style.display = 'none';
        if (defaultGroup) defaultGroup.style.display = 'none';
        const wsGroupNew = $('dashboardWorkspaceGroup');
        if (wsGroupNew) wsGroupNew.style.display = 'none';

        const setVal = (elId, v) => { const el = $(elId); if (el) el.value = v; };
        setVal('dashboardName', '');
        setVal('dashboardSlug', '');
        setVal('dashboardDescription', '');
        setVal('dashboardIcon', 'fa-chart-line');
        const chk = $('dashboardIsDefault');
        if (chk) chk.checked = false;

        const slugInput = $('dashboardSlug');
        if (slugInput) { slugInput.removeAttribute('readonly'); slugInput.style.opacity = ''; }

        openModal('dashboardModal');
    }

    function openEditDashboardModal(id) {
        const menu = $('dashboardSwitcherMenu');
        if (menu) menu.classList.remove('active');

        const dash = (state.dashboardsList || []).find(d => d.id === id);
        if (!dash) { showToast('Dashboard tidak ditemukan', 'error'); return; }

        const modal = $('dashboardModal');
        if (!modal) return;
        const titleEl = $('dashboardModalTitle');
        const editEl = $('dashboardEditId');
        const delBtn = $('dashboardDeleteBtn');
        const defaultGroup = $('dashboardDefaultGroup');

        if (titleEl) titleEl.textContent = 'Edit Dashboard';
        if (editEl) editEl.value = String(id);
        if (delBtn) {
            delBtn.style.display = dash.is_default === 1 ? 'none' : 'inline-flex';
        }
        if (defaultGroup) defaultGroup.style.display = 'block';
        const wsGroupEdit = $('dashboardWorkspaceGroup');
        if (wsGroupEdit) wsGroupEdit.style.display = (dash.role === 'owner' || isAdminMeta()) ? 'block' : 'none';

        const setVal = (elId, v) => { const el = $(elId); if (el) el.value = v; };
        setVal('dashboardName', dash.name || '');
        setVal('dashboardSlug', dash.slug || '');
        setVal('dashboardDescription', dash.description || '');
        setVal('dashboardIcon', dash.icon || 'fa-chart-line');
        const chk = $('dashboardIsDefault');
        if (chk) chk.checked = dash.is_default === 1;

        const slugInput = $('dashboardSlug');
        if (slugInput) { slugInput.setAttribute('readonly', 'readonly'); slugInput.style.opacity = '0.6'; }

        openModal('dashboardModal');
    }

    async function saveDashboardModal() {
        const editId = ($('dashboardEditId') || {}).value;
        const name = (($('dashboardName') || {}).value || '').trim();
        const slugInput = (($('dashboardSlug') || {}).value || '').trim().toLowerCase();
        const description = (($('dashboardDescription') || {}).value || '').trim();
        const icon = ($('dashboardIcon') || {}).value || 'fa-chart-line';
        const isDefault = !!($('dashboardIsDefault') || {}).checked;

        if (!name) { showToast('Nama dashboard wajib diisi', 'error'); return; }

        const store = window.DashboardStore;

        if (editId) {
            const payload = { name, description, icon };
            const res = await API.call(`/api/v1/dashboards/${editId}`, {
                method: 'PUT',
                body: JSON.stringify(payload),
            });
            if (!res.success) { showToast(res.error || 'Gagal menyimpan', 'error'); return; }

            if (isDefault) {
                await API.call(`/api/v1/dashboards/${editId}/set-default`, { method: 'POST' });
            }

            if (parseInt(editId, 10) === state.currentDashboardId) {
                state.currentDashboardName = name;
                state.currentDashboardIcon = icon;
            }
            closeModal('dashboardModal');
            showToast('Dashboard diperbarui', 'success');
            await refreshDashboardsList();
        } else {
            const payload = { name, description, icon };
            if (slugInput) payload.slug = slugInput;
            const res = await store.createDashboard(payload);
            if (!res.success) { showToast(res.error || 'Gagal membuat dashboard', 'error'); return; }

            const newId = res.data.id;

            if (isDefault) {
                await API.call(`/api/v1/dashboards/${newId}/set-default`, { method: 'POST' });
            }

            closeModal('dashboardModal');
            showToast('Dashboard dibuat', 'success');
            await refreshDashboardsList();

            if (confirm('Dashboard berhasil dibuat. Pindah ke dashboard baru sekarang?')) {
                const newSlug = res.data.slug;
                switchDashboard(newId, newSlug);
            }
        }

        const slugEl = $('dashboardSlug');
        if (slugEl) { slugEl.removeAttribute('readonly'); slugEl.style.opacity = ''; }
    }

    async function deleteDashboardModal() {
        const editId = ($('dashboardEditId') || {}).value;
        if (!editId) return;
        const dash = (state.dashboardsList || []).find(d => d.id === parseInt(editId, 10));
        if (!dash) return;

        if (!confirm(`Hapus dashboard "${dash.name}"?\n\nSemua widget dan tab analitik di dalamnya akan ikut terhapus.`)) return;

        const res = await API.call(`/api/v1/dashboards/${editId}`, { method: 'DELETE' });
        if (res.success) {
            closeModal('dashboardModal');
            showToast('Dashboard dihapus', 'success');
            await refreshDashboardsList();

            if (parseInt(editId, 10) === state.currentDashboardId) {
                window.location.href = '/#dashboard';
            }
        } else {
            showToast(res.error || 'Gagal menghapus', 'error');
        }
    }

    function bindDashboardSwitcher() {
        const trigger = $('dashboardSwitcherTrigger');
        const menu = $('dashboardSwitcherMenu');
        const addBtn = $('dashboardSwitcherAdd');
        const saveBtn = $('dashboardSaveBtn');
        const delBtn = $('dashboardDeleteBtn');

        if (trigger && menu && !trigger.__bound) {
            trigger.__bound = true;
            trigger.addEventListener('click', (e) => {
                e.stopPropagation();
                menu.classList.toggle('active');
            });
        }

        if (addBtn && !addBtn.__bound) {
            addBtn.__bound = true;
            addBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                if (menu) menu.classList.remove('active');
                openCreateDashboardModal();
            });
        }

        if (saveBtn && !saveBtn.__bound) {
            saveBtn.__bound = true;
            saveBtn.addEventListener('click', saveDashboardModal);
        }

        if (delBtn && !delBtn.__bound) {
            delBtn.__bound = true;
            delBtn.addEventListener('click', deleteDashboardModal);
        }

        if (!document.__dsBound) {
            document.__dsBound = true;
            document.addEventListener('click', (e) => {
                if (!e.target.closest('#dashboardSwitcher')) {
                    const m = $('dashboardSwitcherMenu');
                    if (m) m.classList.remove('active');
                }
            });
        }
    }

    async function loadCurrentDashboardInfo() {
        await refreshDashboardsList();

        if (state.dashboardSlug) {
            const found = (state.dashboardsList || []).find(d => d.slug === state.dashboardSlug);
            if (found) {
                state.currentDashboardId = found.id;
                state.currentDashboardName = found.name;
                state.currentDashboardIcon = found.icon || 'fa-chart-pie';
            }
        } else {
            const def = (state.dashboardsList || []).find(d => d.is_default === 1)
                     || (state.dashboardsList || [])[0];
            if (def) {
                state.currentDashboardId = def.id;
                state.currentDashboardName = def.name;
                state.currentDashboardIcon = def.icon || 'fa-chart-pie';
            }
        }
        renderDashboardSwitcher();
    }

    // ==========================================
    // USER MANAGEMENT
    // ==========================================
    const userState = {
        users: [],
        currentUserId: null,
        currentIsAdmin: false,
        view: 'list',
        editId: null,
    };

    async function loadCurrentUser() {
        try {
            const res = await API.call('/api/v1/users/me');
            if (res.success && res.data.user) {
                userState.currentUserId = res.data.user.id;
                userState.currentIsAdmin = res.data.user.is_admin === true;
                userState.currentRole = res.data.user.role || (userState.currentIsAdmin ? 'admin' : 'user');
                userState.permissions = res.data.user.permissions || [];
                userState.permissionsLoaded = true;
                refreshPermissionGates();
                document.body.classList.toggle('is-non-admin', !userState.currentIsAdmin);

                const usersBtn = $('manageUsersBtn');
                if (usersBtn) usersBtn.style.display = userState.currentIsAdmin ? '' : 'none';
                // Tombol legacy ini tak terlihat (ada di #legacyActions). Satu-satunya
                // jalan ke kelola pengguna: command palette -> AAGuardUsers.open().
                if (usersBtn) usersBtn.addEventListener('click', () => {
                    if (window.AAGuardUsers) window.AAGuardUsers.open();
                    else window.showToast('Modul pengguna belum siap', 'error');
                });

                const backupBtn = $('backupBtn');
                if (backupBtn) backupBtn.style.display = userState.currentIsAdmin ? '' : 'none';

                const cleanupBtn = $('cleanupBtn');
                if (cleanupBtn) cleanupBtn.style.display = userState.currentIsAdmin ? '' : 'none';

                const dataMgmtBtn = $('dataMgmtBtn');
                if (dataMgmtBtn) dataMgmtBtn.style.display = userState.currentIsAdmin ? '' : 'none';

                const globalRulesBtn = $('globalRulesBtn');
                if (globalRulesBtn) globalRulesBtn.style.display = userState.currentIsAdmin ? '' : 'none';

                const bulkImportBtn = $('bulkImportBtn');
                if (bulkImportBtn) bulkImportBtn.style.display = userState.currentIsAdmin ? '' : 'none';
            }
        } catch (e) {
            console.warn('[Users] load me failed', e);
        }
    }


    // ==========================================
    // BACKUP MANAGEMENT
    // ==========================================
    function formatBytes(bytes) {
        if (!bytes && bytes !== 0) return '-';
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
    }

    function formatBackupDate(iso) {
        if (!iso) return '-';
        try {
            const d = new Date(String(iso).replace(' ', 'T') + '+07:00');
            return d.toLocaleString('id-ID', {
                day: '2-digit', month: 'short', year: 'numeric',
                hour: '2-digit', minute: '2-digit',
                timeZone: 'Asia/Jakarta',
            }) + ' WIB';
        } catch (e) { return iso; }
    }

    async function loadBackupList() {
        const listEl = $('backupList');
        const countEl = $('backupListCount');
        const autoEl = $('backupAutoStatus');
        const intEl = $('backupInterval');
        const retEl = $('backupRetention');

        if (!listEl) return;

        listEl.innerHTML = `<div class="loading" style="padding:32px;text-align:center;">
            <div class="spinner"></div>
            <div style="margin-top:10px;font-size:12.5px;color:var(--text-3);">Memuat...</div>
        </div>`;

        const res = await API.call('/api/v1/system/backups');
        if (!res.success) {
            listEl.innerHTML = `<div class="empty-state" style="padding:32px;">
                <i class="fa-solid fa-triangle-exclamation" style="color:var(--accent-crit);"></i>
                <h3>Gagal memuat</h3>
                <p>${escapeHtml(res.error || 'Koneksi gagal')}</p>
            </div>`;
            if (countEl) countEl.textContent = '';
            return;
        }

        const data = res.data;
        if (autoEl) {
            autoEl.textContent = data.auto_backup_enabled ? 'Aktif' : 'Nonaktif';
            autoEl.style.color = data.auto_backup_enabled ? 'var(--accent-ok)' : 'var(--text-3)';
        }
        if (intEl) intEl.textContent = data.auto_backup_enabled ? `${data.backup_interval_hours} jam` : '—';
        if (retEl) retEl.textContent = `${data.retention_days} hari`;

        const backups = data.backups || [];
        if (countEl) countEl.textContent = backups.length > 0 ? `${backups.length} file` : '';

        if (backups.length === 0) {
            listEl.innerHTML = `<div class="empty-state" style="padding:40px 20px;">
                <i class="fa-solid fa-box-archive" style="opacity:0.4;"></i>
                <h3>Belum ada backup</h3>
                <p>Klik "Backup Sekarang" untuk membuat backup pertama</p>
            </div>`;
            return;
        }

        const newestTs = backups.reduce((m, b) => (b.created_at > m ? b.created_at : m), '');
        listEl.innerHTML = backups.map(b => `
            <div class="backup-item">
                <div class="backup-item-icon">
                    <i class="fa-solid fa-database"></i>
                </div>
                <div class="backup-item-info">
                    <div class="backup-item-name">${escapeHtml(b.filename)}</div>
                    <div class="backup-item-meta">
                        <span>${formatBytes(b.size_bytes)}</span>
                        <span class="backup-item-sep">·</span>
                        <span>${escapeHtml(formatBackupDate(b.created_at))}</span>
                        ${b.created_at === newestTs ? '<span class="backup-item-sep">·</span><span title="Backup terbaru dilindungi dari penghapusan">terbaru (dilindungi)</span>' : ''}
                    </div>
                </div>
                <button class="backup-download-btn" data-filename="${escapeHtml(b.filename)}" title="Download">
                    <i class="fa-solid fa-download"></i>
                </button>
                ${b.created_at === newestTs ? '' : `<button class="backup-download-btn backup-delete-btn" data-filename="${escapeHtml(b.filename)}" title="Hapus backup ini" style="color:var(--accent-crit);">
                    <i class="fa-solid fa-trash"></i>
                </button>`}
            </div>
        `).join('');

        listEl.querySelectorAll('.backup-delete-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const filename = btn.dataset.filename;
                if (!confirm(`Hapus file backup ini secara permanen?\n\n${filename}`)) return;
                const r = await API.call(`/api/v1/system/backups/${encodeURIComponent(filename)}`, { method: 'DELETE' });
                if (r.success) {
                    window.showToast('Backup dihapus', 'success');
                    loadBackupList();
                } else {
                    window.showToast(r.error || 'Gagal menghapus backup', 'error', 5000);
                }
            });
        });

        listEl.querySelectorAll('.backup-download-btn:not(.backup-delete-btn)').forEach(btn => {
            btn.addEventListener('click', () => {
                const filename = btn.dataset.filename;
                window.location.href = `/api/v1/system/backups/${encodeURIComponent(filename)}`;
                window.showToast('Mengunduh backup...', 'info');
            });
        });
    }

    async function triggerManualBackup() {
        const btn = $('backupNowBtn');
        if (!btn) return;
        const originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> <span>Memproses...</span>';

        try {
            const res = await API.call('/api/v1/system/backup', { method: 'POST' });
            if (res.success) {
                window.showToast(res.data.message || 'Backup berhasil dibuat', 'success');
                await loadBackupList();
            } else {
                window.showToast(res.error || 'Gagal backup', 'error', 5000);
            }
        } catch (e) {
            window.showToast('Koneksi gagal: ' + e.message, 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    }

    function openBackupModal() {
        const modal = $('backupModal');
        if (!modal) return;
        const actionsEl = modal.querySelector('.modal-actions');
        if (actionsEl && !actionsEl.querySelector('[data-action="open-restore"]')) {
            const restoreBtn = document.createElement('button');
            restoreBtn.className = 'btn btn-danger';
            restoreBtn.setAttribute('data-action', 'open-restore');
            restoreBtn.style.cssText = 'margin-right:auto;';
            restoreBtn.innerHTML = '<i class="fa-solid fa-rotate-left"></i> Restore';
            actionsEl.insertBefore(restoreBtn, actionsEl.firstChild);
            restoreBtn.addEventListener('click', () => {
                closeModal('backupModal');
                openRestoreModal();
            });
        }
        openModal('backupModal');
        loadBackupList();
    }

    function bindBackup() {
        const btn = $('backupBtn');
        if (btn && !btn.__bound) {
            btn.__bound = true;
            btn.addEventListener('click', openBackupModal);
        }

        const triggerBtn = $('backupNowBtn');
        if (triggerBtn && !triggerBtn.__bound) {
            triggerBtn.__bound = true;
            triggerBtn.addEventListener('click', triggerManualBackup);
        }
    }

    // ==========================================
    // CHANGE PASSWORD
    // ==========================================
    function showCpError(msg) {
        const el = $('cpError');
        if (!el) return;
        el.textContent = msg;
        el.style.display = 'block';
    }

    function hideCpError() {
        const el = $('cpError');
        if (el) { el.style.display = 'none'; el.textContent = ''; }
    }

    function openChangePasswordModal() {
        const modal = $('changePasswordModal');
        if (!modal) return;
        const setVal = (id, v) => { const el = $(id); if (el) el.value = v; };
        setVal('cpOldPassword', '');
        setVal('cpNewPassword', '');
        setVal('cpConfirmPassword', '');
        hideCpError();
        openModal('changePasswordModal');
        setTimeout(() => {
            const el = $('cpOldPassword');
            if (el) el.focus();
        }, 100);
    }

    async function submitChangePassword() {
        hideCpError();

        const oldPw = ($('cpOldPassword') || {}).value || '';
        const newPw = ($('cpNewPassword') || {}).value || '';
        const confirmPw = ($('cpConfirmPassword') || {}).value || '';

        if (!oldPw) { showCpError('Password lama wajib diisi'); return; }
        if (!newPw || newPw.length < 8) { showCpError('Password baru minimal 8 karakter'); return; }
        if (newPw !== confirmPw) { showCpError('Konfirmasi password tidak cocok'); return; }
        if (oldPw === newPw) { showCpError('Password baru harus berbeda dari yang lama'); return; }

        const btn = $('cpSaveBtn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Menyimpan...';
        }

        try {
            const res = await API.call('/api/v1/users/me/password', {
                method: 'POST',
                body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
            });

            if (res.success) {
                closeModal('changePasswordModal');
                window.showToast('Password berhasil diubah', 'success');
            } else {
                showCpError(res.error || 'Gagal mengubah password');
            }
        } catch (e) {
            showCpError('Koneksi gagal: ' + e.message);
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-check"></i> Simpan';
            }
        }
    }

    function bindChangePassword() {
        const btn = $('changePasswordBtn');
        if (btn && !btn.__bound) {
            btn.__bound = true;
            btn.addEventListener('click', openChangePasswordModal);
        }

        const saveBtn = $('cpSaveBtn');
        if (saveBtn && !saveBtn.__bound) {
            saveBtn.__bound = true;
            saveBtn.addEventListener('click', submitChangePassword);
        }

        ['cpOldPassword', 'cpNewPassword', 'cpConfirmPassword'].forEach(id => {
            const el = $(id);
            if (el && !el.__bound) {
                el.__bound = true;
                el.addEventListener('keydown', e => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        submitChangePassword();
                    }
                });
            }
        });
    }

    // ==========================================
    // MANUAL CLEANUP
    // ==========================================
    async function triggerManualCleanup() {
        if (!confirm('Jalankan cleanup data lama sekarang?\n\nData yang lebih tua dari batas retensi akan dihapus permanen.')) return;

        window.showToast('Menjalankan cleanup...', 'info');
        try {
            const res = await API.call('/api/v1/system/cleanup', { method: 'POST' });
            if (res.success) {
                const total = res.data.total_deleted || 0;
                const details = res.data.details || {};
                const detailStr = Object.entries(details).map(([k, v]) => `${k}: ${v}`).join(', ');
                window.showToast(
                    total > 0 ? `Cleanup selesai: ${total} baris (${detailStr})` : 'Tidak ada data yang perlu dihapus',
                    total > 0 ? 'success' : 'info',
                    5000
                );
                loadDashboard();
            } else {
                window.showToast(res.error || 'Cleanup gagal', 'error', 5000);
            }
        } catch (e) {
            window.showToast('Koneksi gagal: ' + e.message, 'error');
        }
    }

    function bindCleanupButton() {
        const btn = $('cleanupBtn');
        if (btn && !btn.__bound) {
            btn.__bound = true;
            btn.addEventListener('click', triggerManualCleanup);
        }
    }

    // ==========================================
    // DROPDOWNS & BINDINGS
    // ==========================================
    function bindTimeRangeDropdown() {
        const trigger = $('timeRangeTrigger'); const menu = $('timeRangeMenu');
        if (!trigger || !menu) return;
        trigger.addEventListener('click', e => { e.stopPropagation(); menu.classList.toggle('active'); });
        menu.querySelectorAll('.time-range-item').forEach(item => {
            item.addEventListener('click', () => { setGlobalTimeRange(parseInt(item.dataset.minutes)); menu.classList.remove('active'); });
        });
        document.addEventListener('click', e => {
            if (!menu.classList.contains('active')) return;
            if (!menu.contains(e.target) && !trigger.contains(e.target)) menu.classList.remove('active');
        });
    }

    function bindTabDropdown() {
        const trigger = $('tabDropdownTrigger'); const menu = $('tabDropdownMenu');
        if (!trigger || !menu) return;
        trigger.addEventListener('click', e => { e.stopPropagation(); menu.classList.toggle('active'); });
        document.addEventListener('click', e => {
            if (!menu.classList.contains('active')) return;
            if (!menu.contains(e.target) && !trigger.contains(e.target)) menu.classList.remove('active');
        });
    }

    // ==========================================
    // GLOBAL ALERT RULES
    // ==========================================
    let globalRulesCache = null;

    const SENSOR_LABELS = {
        temperature: 'Suhu', humidity: 'Kelembaban', gas_level: 'Level Gas', smoke: 'Asap',
    };
    const SENSOR_UNITS = {
        temperature: '°C', humidity: '%', gas_level: 'ppm', smoke: 'ppm',
    };

    async function openGlobalRulesModal() {
        if (!userState.currentIsAdmin) {
            window.showToast('Hanya admin yang bisa edit global rules', 'error');
            return;
        }
        openModal('globalRulesModal');
        await loadGlobalRules();
    }

    async function loadGlobalRules() {
        const listEl = $('globalRulesList');
        const statusEl = $('globalRulesStatus');
        const resetBtn = $('globalRulesResetBtn');
        if (!listEl) return;

        listEl.innerHTML = `<div class="loading" style="padding:32px;text-align:center;">
            <div class="spinner"></div>
            <div style="margin-top:10px;font-size:12.5px;color:var(--text-3);">Memuat rules...</div>
        </div>`;

        const res = await API.call('/api/v1/system/alert-rules');
        if (!res.success) {
            listEl.innerHTML = `<div class="empty-state" style="padding:32px;">
                <i class="fa-solid fa-triangle-exclamation" style="color:var(--accent-crit);"></i>
                <h3>Gagal memuat</h3>
                <p>${escapeHtml(res.error || 'Koneksi gagal')}</p>
            </div>`;
            return;
        }

        globalRulesCache = res.data;
        const rules = res.data.alert_rules || {};
        const isCustom = res.data.is_custom === true;

        if (statusEl) {
            if (isCustom) {
                statusEl.style.display = 'block';
                statusEl.style.background = 'var(--accent-info-bg)';
                statusEl.style.color = 'var(--accent-info)';
                statusEl.style.border = '1px solid var(--accent-info)';
                statusEl.innerHTML = '<i class="fa-solid fa-pen"></i> Menggunakan rules custom (tidak default)';
            } else {
                statusEl.style.display = 'block';
                statusEl.style.background = 'var(--surface-2)';
                statusEl.style.color = 'var(--text-3)';
                statusEl.style.border = '1px solid var(--hairline)';
                statusEl.innerHTML = '<i class="fa-solid fa-circle-check"></i> Menggunakan default dari config.py';
            }
        }
        if (resetBtn) resetBtn.style.display = isCustom ? 'inline-flex' : 'none';

        const keys = Object.keys(rules);
        if (keys.length === 0) {
            listEl.innerHTML = `<div class="empty-state" style="padding:32px;">
                <i class="fa-solid fa-sliders" style="opacity:0.4;"></i>
                <h3>Tidak ada rules</h3>
            </div>`;
            return;
        }

        listEl.innerHTML = keys.map(key => {
            const rule = rules[key] || {};
            const label = SENSOR_LABELS[key] || key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            const unit = SENSOR_UNITS[key] ?? '';
            const severities = ['healthy', 'warning', 'danger'];
            const sevLabels = { healthy: 'Normal', warning: 'Warning', danger: 'Bahaya' };

            const rows = severities.map(sev => {
                const r = rule[sev];
                if (!r) return '';
                return `<div class="global-rule-sev-grid ${sev}">
                    <div class="global-rule-sev-label"><span class="dot"></span>${sevLabels[sev]}</div>
                    <input type="number" step="0.1" class="global-rule-input" data-sensor="${escapeHtml(key)}" data-severity="${sev}" data-field="min" value="${r.min ?? 0}">
                    <input type="number" step="0.1" class="global-rule-input" data-sensor="${escapeHtml(key)}" data-severity="${sev}" data-field="max" value="${r.max ?? 0}">
                </div>`;
            }).join('');

            return `<div class="global-rule-card">
                <div class="global-rule-head">
                    <div class="global-rule-name">
                        <i class="fa-solid fa-wave-square"></i>
                        ${escapeHtml(label)}
                    </div>
                    ${unit ? `<span class="global-rule-unit">${escapeHtml(unit)}</span>` : ''}
                </div>
                <div class="global-rule-severities">${rows}</div>
            </div>`;
        }).join('');
    }

    async function saveGlobalRules() {
        const listEl = $('globalRulesList');
        if (!listEl) return;

        const rules = {};
        listEl.querySelectorAll('.global-rule-card').forEach(card => {
            const inputs = card.querySelectorAll('.global-rule-input');
            const sensorKey = inputs[0]?.dataset.sensor;
            if (!sensorKey) return;

            const rule = {};
            const sevMap = {};

            inputs.forEach(inp => {
                const sev = inp.dataset.severity;
                const field = inp.dataset.field;
                const val = parseFloat(inp.value);
                if (isNaN(val)) return;
                if (!sevMap[sev]) sevMap[sev] = {};
                sevMap[sev][field] = val;
            });

            ['healthy', 'warning', 'danger'].forEach(sev => {
                if (sevMap[sev] && sevMap[sev].min !== undefined && sevMap[sev].max !== undefined) {
                    rule[sev] = { min: sevMap[sev].min, max: sevMap[sev].max };
                }
            });

            if (Object.keys(rule).length > 0) rules[sensorKey] = rule;
        });

        if (globalRulesCache?.alert_rules) {
            Object.keys(rules).forEach(key => {
                const orig = globalRulesCache.alert_rules[key];
                if (orig && orig._hysteresis !== undefined) {
                    rules[key]._hysteresis = orig._hysteresis;
                }
            });
        }

        if (Object.keys(rules).length === 0) {
            window.showToast('Minimal 1 rule harus diisi', 'error');
            return;
        }

        const btn = $('globalRulesSaveBtn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Menyimpan...';
        }

        try {
            const res = await API.call('/api/v1/system/alert-rules', {
                method: 'PUT',
                body: JSON.stringify(rules),
            });

            if (res.success) {
                window.showToast('Global rules tersimpan', 'success');
                closeModal('globalRulesModal');
            } else {
                window.showToast(res.error || 'Gagal menyimpan', 'error', 5000);
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-check"></i> Simpan';
            }
        }
    }

    async function resetGlobalRules() {
        if (!confirm('Reset global rules ke default dari config.py?\n\nSemua custom rules akan dihapus.')) return;

        const btn = $('globalRulesResetBtn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Reset...';
        }

        try {
            const res = await API.call('/api/v1/system/alert-rules', { method: 'DELETE' });
            if (res.success) {
                window.showToast('Global rules direset ke default', 'success');
                await loadGlobalRules();
            } else {
                window.showToast(res.error || 'Gagal reset', 'error');
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-rotate-left"></i> Reset ke Default';
            }
        }
    }

    function bindGlobalRules() {
        const btn = $('globalRulesBtn');
        if (btn && !btn.__bound) {
            btn.__bound = true;
            btn.addEventListener('click', openGlobalRulesModal);
        }
        const saveBtn = $('globalRulesSaveBtn');
        if (saveBtn && !saveBtn.__bound) {
            saveBtn.__bound = true;
            saveBtn.addEventListener('click', saveGlobalRules);
        }
        const resetBtn = $('globalRulesResetBtn');
        if (resetBtn && !resetBtn.__bound) {
            resetBtn.__bound = true;
            resetBtn.addEventListener('click', resetGlobalRules);
        }
    }

    // ==========================================
    // RESTORE DATABASE
    // ==========================================
    async function openRestoreModal() {
        if (!userState.currentIsAdmin) {
            window.showToast('Hanya admin yang bisa restore', 'error');
            return;
        }
        const sel = $('restoreFileSelect');
        const inp = $('restoreConfirmInput');
        const btn = $('restoreConfirmBtn');
        const errEl = $('restoreError');
        if (sel) sel.innerHTML = '<option value="">— Memuat file backup —</option>';
        if (inp) inp.value = '';
        if (btn) btn.disabled = true;
        if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
        openModal('restoreModal');
        await loadRestoreFileList();
    }

    async function loadRestoreFileList() {
        const sel = $('restoreFileSelect');
        if (!sel) return;

        const res = await API.call('/api/v1/system/backups');
        if (!res.success) {
            sel.innerHTML = '<option value="">Gagal memuat file</option>';
            return;
        }

        const backups = res.data.backups || [];
        if (backups.length === 0) {
            sel.innerHTML = '<option value="">Tidak ada file backup</option>';
            return;
        }

        sel.innerHTML = '<option value="">— Pilih file backup —</option>' + backups.map(b =>
            `<option value="${escapeHtml(b.filename)}">${escapeHtml(b.filename)} (${b.size_mb} MB)</option>`
        ).join('');
    }

    function updateRestoreBtnState() {
        const sel = $('restoreFileSelect');
        const inp = $('restoreConfirmInput');
        const btn = $('restoreConfirmBtn');
        if (!btn) return;
        const hasFile = sel && sel.value;
        const confirmed = inp && inp.value.trim().toUpperCase() === 'RESTORE';
        btn.disabled = !(hasFile && confirmed);
    }

    async function submitRestore() {
        const sel = $('restoreFileSelect');
        const inp = $('restoreConfirmInput');
        const errEl = $('restoreError');
        const btn = $('restoreConfirmBtn');

        if (!sel || !sel.value) { window.showToast('Pilih file backup dulu', 'error'); return; }
        if (!inp || inp.value.trim().toUpperCase() !== 'RESTORE') {
            window.showToast('Ketik RESTORE untuk konfirmasi', 'error'); return;
        }

        const filename = sel.value;

        if (!confirm(`YAKIN restore dari "${filename}"?\n\nSemua data saat ini akan DIGANTIKAN.\nPre-restore backup akan dibuat otomatis.`)) return;

        if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Merestore...';
        }

        try {
            const res = await API.call('/api/v1/system/restore', {
                method: 'POST',
                body: JSON.stringify({ filename, confirm: 'RESTORE' }),
            });

            if (res.success) {
                closeModal('restoreModal');
                window.showToast(res.data.message || 'Restore berhasil! Restart aplikasi sekarang.', 'success', 8000);
                setTimeout(() => {
                    if (confirm('Restart aplikasi sekarang?\n\nKlik OK untuk reload halaman.')) {
                        window.location.reload();
                    }
                }, 2000);
            } else {
                if (errEl) {
                    errEl.textContent = res.error || 'Gagal restore';
                    errEl.style.display = 'block';
                }
                window.showToast(res.error || 'Gagal restore', 'error', 6000);
            }
        } catch (e) {
            if (errEl) {
                errEl.textContent = 'Koneksi gagal: ' + e.message;
                errEl.style.display = 'block';
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> Restore Sekarang';
                updateRestoreBtnState();
            }
        }
    }

    function bindRestore() {
        const sel = $('restoreFileSelect');
        if (sel && !sel.__bound) {
            sel.__bound = true;
            sel.addEventListener('change', updateRestoreBtnState);
        }
        const inp = $('restoreConfirmInput');
        if (inp && !inp.__bound) {
            inp.__bound = true;
            inp.addEventListener('input', updateRestoreBtnState);
        }
        const btn = $('restoreConfirmBtn');
        if (btn && !btn.__bound) {
            btn.__bound = true;
            btn.addEventListener('click', submitRestore);
        }
        const restoreTrigger = document.querySelector('[data-action="open-restore"]');
        if (restoreTrigger && !restoreTrigger.__bound) {
            restoreTrigger.__bound = true;
            restoreTrigger.addEventListener('click', () => {
                closeModal('backupModal');
                openRestoreModal();
            });
        }
    }

    // ==========================================
    // BULK IMPORT
    // ==========================================
    let bulkImportParsed = [];

    function openBulkImportModal() {
        if (!userState.currentIsAdmin) {
            window.showToast('Hanya admin yang bisa bulk import', 'error');
            return;
        }
        switchBulkImportView('paste');
        const txt = $('bulkImportJson');
        if (txt) txt.value = '';
        const nameEl = $('bulkImportFileName');
        if (nameEl) { nameEl.style.display = 'none'; nameEl.textContent = ''; }
        const prev = $('bulkImportPreview');
        if (prev) prev.style.display = 'none';
        const err = $('bulkImportError');
        if (err) { err.style.display = 'none'; err.textContent = ''; }
        bulkImportParsed = [];
        openModal('bulkImportModal');
    }

    function switchBulkImportView(mode) {
        document.querySelectorAll('.bulk-import-tab').forEach(t => {
            t.classList.toggle('active', t.dataset.mode === mode);
        });
        const pasteV = $('bulkImportPasteView');
        const csvV = $('bulkImportCsvView');
        if (pasteV) pasteV.style.display = mode === 'paste' ? '' : 'none';
        if (csvV) csvV.style.display = mode === 'csv' ? '' : 'none';
    }

    function parseBulkJson() {
        const txt = $('bulkImportJson');
        const errEl = $('bulkImportError');
        if (!txt) return;
        if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }

        const raw = txt.value.trim();
        if (!raw) { bulkImportParsed = []; renderBulkPreview(); return; }

        try {
            const parsed = JSON.parse(raw);
            if (!Array.isArray(parsed)) {
                throw new Error('Harus berupa array JSON');
            }
            bulkImportParsed = parsed;
            renderBulkPreview();
        } catch (e) {
            bulkImportParsed = [];
            if (errEl) {
                errEl.textContent = 'JSON tidak valid: ' + e.message;
                errEl.style.display = 'block';
            }
            renderBulkPreview();
        }
    }

    function parseBulkCsv(text) {
        const lines = text.split(/\r?\n/).filter(l => l.trim());
        if (lines.length < 2) { bulkImportParsed = []; renderBulkPreview(); return; }

        const headers = lines[0].split(',').map(h => h.trim().toLowerCase().replace(/\s+/g, '_'));
        const rows = [];

        for (let i = 1; i < lines.length; i++) {
            const cells = lines[i].split(',').map(c => c.trim().replace(/^"|"$/g, ''));
            const obj = {};
            headers.forEach((h, idx) => {
                if (cells[idx] !== undefined && cells[idx] !== '') {
                    obj[h] = cells[idx];
                }
            });
            rows.push(obj);
        }

        bulkImportParsed = rows;
        renderBulkPreview();
    }

    function renderBulkPreview() {
        const wrap = $('bulkImportPreview');
        const listEl = $('bulkImportPreviewList');
        const countEl = $('bulkImportPreviewCount');
        if (!wrap || !listEl) return;

        if (bulkImportParsed.length === 0) {
            wrap.style.display = 'none';
            return;
        }

        wrap.style.display = 'block';
        if (countEl) countEl.textContent = `${bulkImportParsed.length} device`;

        listEl.innerHTML = bulkImportParsed.slice(0, 50).map((item, idx) => {
            const hasError = !item.device_id || !item.device_name;
            const errMsg = hasError ? 'device_id & device_name wajib' : '';
            return `<div class="bulk-import-preview-item ${hasError ? 'error' : ''}">
                <span class="bulk-import-preview-row">${idx + 1}</span>
                <span class="bulk-import-preview-id">${escapeHtml(item.device_id || '?')}</span>
                <span class="bulk-import-preview-name">${escapeHtml(item.device_name || '—')}</span>
                ${errMsg ? `<span class="bulk-import-preview-error">${escapeHtml(errMsg)}</span>` : ''}
            </div>`;
        }).join('') + (bulkImportParsed.length > 50
            ? `<div style="text-align:center;padding:8px;font-size:11px;color:var(--text-3);">... +${bulkImportParsed.length - 50} baris lainnya</div>`
            : '');
    }

    function fillBulkImportSample() {
        const txt = $('bulkImportJson');
        if (!txt) return;
        txt.value = JSON.stringify([
            { device_id: "ESP32-001", device_name: "Sensor Suhu Server", device_type: "ESP32", location: "Ruang Server", description: "Monitoring suhu ruang server" },
            { device_id: "ESP32-002", device_name: "Sensor Gudang", device_type: "ESP32", location: "Gudang A", description: "" },
        ], null, 2);
        parseBulkJson();
    }

    function downloadBulkTemplate() {
        const csv = 'device_id,device_name,device_type,location,description,firmware_version\n' +
                    'ESP32-001,Sensor Suhu Server,ESP32,Ruang Server,Monitoring suhu,\n' +
                    'ESP32-002,Sensor Gudang,ESP32,Gudang A,,\n';
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'aaguard-bulk-import-template.csv';
        a.click();
        URL.revokeObjectURL(url);
    }

    async function submitBulkImport() {
        const errEl = $('bulkImportError');
        if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }

        const pasteV = $('bulkImportPasteView');
        if (pasteV && pasteV.style.display !== 'none') {
            parseBulkJson();
        }

        if (bulkImportParsed.length === 0) {
            if (errEl) {
                errEl.textContent = 'Tidak ada device untuk diimport';
                errEl.style.display = 'block';
            }
            return;
        }

        if (bulkImportParsed.length > 200) {
            if (errEl) {
                errEl.textContent = `Maksimal 200 device per import (dikirim: ${bulkImportParsed.length})`;
                errEl.style.display = 'block';
            }
            return;
        }

        const btn = $('bulkImportSubmitBtn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Mengimport...';
        }

        try {
            const res = await API.call('/api/v1/devices/bulk-import', {
                method: 'POST',
                body: JSON.stringify({ devices: bulkImportParsed }),
            });

            if (res.success) {
                closeModal('bulkImportModal');
                showBulkImportResult(res.data);
                loadDashboard();
            } else {
                if (errEl) {
                    errEl.textContent = res.error || 'Import gagal';
                    errEl.style.display = 'block';
                }
            }
        } catch (e) {
            if (errEl) {
                errEl.textContent = 'Koneksi gagal: ' + e.message;
                errEl.style.display = 'block';
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-upload"></i> Import Sekarang';
            }
        }
    }

    function showBulkImportResult(data) {
        const modal = $('bulkImportResultModal');
        if (!modal) return;

        const summary = data.summary || {};
        const summaryEl = $('bulkResultSummary');
        if (summaryEl) {
            summaryEl.innerHTML = `
                <div class="bulk-result-stat ok">
                    <div class="bulk-result-stat-value">${summary.created || 0}</div>
                    <div class="bulk-result-stat-label">Dibuat</div>
                </div>
                <div class="bulk-result-stat warn">
                    <div class="bulk-result-stat-value">${summary.skipped || 0}</div>
                    <div class="bulk-result-stat-label">Skip</div>
                </div>
                <div class="bulk-result-stat crit">
                    <div class="bulk-result-stat-value">${summary.errors || 0}</div>
                    <div class="bulk-result-stat-label">Error</div>
                </div>
            `;
        }

        const created = data.created || [];
        const createdSec = $('bulkResultCreatedSection');
        const createdBody = $('bulkResultCreatedBody');
        const createdCount = $('bulkResultCreatedCount');
        if (created.length > 0 && createdSec && createdBody) {
            createdSec.style.display = 'block';
            if (createdCount) createdCount.textContent = created.length;
            createdBody.innerHTML = created.map(c => `
                <tr>
                    <td>${escapeHtml(c.device_id)}</td>
                    <td>${escapeHtml(c.device_name)}</td>
                    <td class="api-key-cell">${escapeHtml(c.api_key || '')}</td>
                </tr>
            `).join('');
        } else if (createdSec) {
            createdSec.style.display = 'none';
        }

        const skipped = data.skipped || [];
        const skippedSec = $('bulkResultSkippedSection');
        const skippedBody = $('bulkResultSkippedBody');
        const skippedCount = $('bulkResultSkippedCount');
        if (skipped.length > 0 && skippedSec && skippedBody) {
            skippedSec.style.display = 'block';
            if (skippedCount) skippedCount.textContent = skipped.length;
            skippedBody.innerHTML = skipped.map(s => `
                <tr>
                    <td>${s.row}</td>
                    <td>${escapeHtml(s.device_id)}</td>
                    <td>${escapeHtml(s.reason || '')}</td>
                </tr>
            `).join('');
        } else if (skippedSec) {
            skippedSec.style.display = 'none';
        }

        const errors = data.errors || [];
        const errSec = $('bulkResultErrorSection');
        const errBody = $('bulkResultErrorBody');
        const errCount = $('bulkResultErrorCount');
        if (errors.length > 0 && errSec && errBody) {
            errSec.style.display = 'block';
            if (errCount) errCount.textContent = errors.length;
            errBody.innerHTML = errors.map(e => `
                <tr>
                    <td>${e.row || '?'}</td>
                    <td>${escapeHtml(e.device_id || '?')}</td>
                    <td>${escapeHtml(e.error || '')}</td>
                </tr>
            `).join('');
        } else if (errSec) {
            errSec.style.display = 'none';
        }

        openModal('bulkImportResultModal');
    }

    function copyAllBulkKeys() {
        const created = document.querySelectorAll('#bulkResultCreatedBody tr');
        const lines = [];
        created.forEach(tr => {
            const cells = tr.querySelectorAll('td');
            if (cells.length >= 3) {
                lines.push(`Device ID: ${cells[0].textContent}  |  API Key: ${cells[2].textContent}`);
            }
        });
        const text = lines.join('\n');

        if (navigator.clipboard) {
            navigator.clipboard.writeText(text)
                .then(() => window.showToast(`${lines.length} API key disalin`, 'success'))
                .catch(() => window.showToast('Gagal copy', 'error'));
        } else {
            alert('Copy manual:\n\n' + text);
        }
    }

    function downloadBulkResultCsv() {
        const created = document.querySelectorAll('#bulkResultCreatedBody tr');
        if (created.length === 0) { window.showToast('Tidak ada data', 'info'); return; }

        const rows = [['device_id', 'device_name', 'api_key']];
        created.forEach(tr => {
            const cells = tr.querySelectorAll('td');
            if (cells.length >= 3) {
                rows.push([cells[0].textContent, cells[1].textContent, cells[2].textContent]);
            }
        });

        const csv = rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n');
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `bulk-import-keys-${Date.now()}.csv`;
        a.click();
        URL.revokeObjectURL(url);
    }

    function bindBulkImport() {
        const btn = $('bulkImportBtn');
        if (btn && !btn.__bound) {
            btn.__bound = true;
            btn.addEventListener('click', openBulkImportModal);
        }

        document.querySelectorAll('.bulk-import-tab').forEach(tab => {
            if (tab.__bound) return;
            tab.__bound = true;
            tab.addEventListener('click', () => {
                switchBulkImportView(tab.dataset.mode);
                if (tab.dataset.mode === 'paste') {
                    parseBulkJson();
                }
            });
        });

        const json = $('bulkImportJson');
        if (json && !json.__bound) {
            json.__bound = true;
            let tid = null;
            json.addEventListener('input', () => {
                clearTimeout(tid);
                tid = setTimeout(parseBulkJson, 400);
            });
        }

        const sampleBtn = $('bulkImportSampleBtn');
        if (sampleBtn && !sampleBtn.__bound) {
            sampleBtn.__bound = true;
            sampleBtn.addEventListener('click', fillBulkImportSample);
        }

        const dropzone = $('bulkImportDropzone');
        const fileInput = $('bulkImportFileInput');
        if (dropzone && fileInput && !dropzone.__bound) {
            dropzone.__bound = true;

            dropzone.addEventListener('click', () => fileInput.click());

            fileInput.addEventListener('change', e => {
                const file = e.target.files[0];
                if (file) handleCsvFile(file);
            });

            ['dragenter', 'dragover'].forEach(ev => {
                dropzone.addEventListener(ev, e => {
                    e.preventDefault();
                    dropzone.classList.add('dragover');
                });
            });
            ['dragleave', 'drop'].forEach(ev => {
                dropzone.addEventListener(ev, e => {
                    e.preventDefault();
                    dropzone.classList.remove('dragover');
                });
            });
            dropzone.addEventListener('drop', e => {
                const file = e.dataTransfer.files[0];
                if (file) handleCsvFile(file);
            });
        }

        function handleCsvFile(file) {
            const nameEl = $('bulkImportFileName');
            if (nameEl) {
                nameEl.textContent = file.name + ' (' + (file.size / 1024).toFixed(1) + ' KB)';
                nameEl.style.display = 'block';
            }
            const reader = new FileReader();
            reader.onload = (e) => {
                parseBulkCsv(e.target.result);
            };
            reader.readAsText(file);
        }

        const tmplBtn = $('bulkImportDownloadTemplate');
        if (tmplBtn && !tmplBtn.__bound) {
            tmplBtn.__bound = true;
            tmplBtn.addEventListener('click', e => {
                e.preventDefault();
                downloadBulkTemplate();
            });
        }

        const submitBtn = $('bulkImportSubmitBtn');
        if (submitBtn && !submitBtn.__bound) {
            submitBtn.__bound = true;
            submitBtn.addEventListener('click', submitBulkImport);
        }

        const copyAllBtn = $('bulkResultCopyAllBtn');
        if (copyAllBtn && !copyAllBtn.__bound) {
            copyAllBtn.__bound = true;
            copyAllBtn.addEventListener('click', copyAllBulkKeys);
        }

        const dlCsvBtn = $('bulkResultDownloadCsvBtn');
        if (dlCsvBtn && !dlCsvBtn.__bound) {
            dlCsvBtn.__bound = true;
            dlCsvBtn.addEventListener('click', downloadBulkResultCsv);
        }
    }

    // ==========================================
    // NOTIFICATION CONFIG
    // ==========================================
    async function openNotificationConfigModal() {
        openModal('notificationConfigModal');
        await loadNotificationConfig();
    }

    async function loadNotificationConfig() {
        const body = $('notificationConfigBody');
        if (!body) return;

        body.innerHTML = `<div class="loading" style="padding:32px;text-align:center;">
            <div class="spinner"></div>
            <div style="margin-top:10px;font-size:12.5px;color:var(--text-3);">Memuat...</div>
        </div>`;

        const res = await API.call('/api/v1/notifications/config');
        if (!res.success) {
            body.innerHTML = `<div class="empty-state" style="padding:32px;">
                <i class="fa-solid fa-triangle-exclamation" style="color:var(--accent-crit);"></i>
                <h3>Gagal memuat</h3>
                <p>${escapeHtml(res.error || 'Koneksi gagal')}</p>
            </div>`;
            return;
        }

        const cfg = res.data.config || {};
        const tg = cfg.telegram || {};

        const valClass = (v) => v ? 'ok' : 'crit';
        const boolStr = (v) => v ? 'Ya' : 'Tidak';

        body.innerHTML = `
            <div class="notif-config-section">
                <div class="notif-config-section-title">
                    <i class="fa-solid fa-bell"></i> Notifikasi Umum
                </div>
                <div class="notif-config-row">
                    <span class="notif-config-label">Status Notifikasi</span>
                    <span class="notif-config-value ${valClass(cfg.notify_enabled)}">${boolStr(cfg.notify_enabled)}</span>
                </div>
                <div class="notif-config-row">
                    <span class="notif-config-label">Severity Minimum</span>
                    <span class="notif-config-value">${escapeHtml(cfg.min_severity || 'warning').toUpperCase()}</span>
                </div>
                <div class="notif-config-row">
                    <span class="notif-config-label">Notif saat pulih</span>
                    <span class="notif-config-value ${valClass(cfg.notify_on_cleared)}">${boolStr(cfg.notify_on_cleared)}</span>
                </div>
            </div>

            <div class="notif-config-section">
                <div class="notif-config-section-title">
                    <i class="fa-brands fa-telegram"></i> Telegram
                </div>
                <div class="notif-config-row">
                    <span class="notif-config-label">Aktif</span>
                    <span class="notif-config-value ${valClass(tg.enabled)}">${boolStr(tg.enabled)}</span>
                </div>
                <div class="notif-config-row">
                    <span class="notif-config-label">Bot Token</span>
                    <span class="notif-config-value ${valClass(tg.has_token)}">${tg.has_token ? '✓ Terkonfigurasi' : '✗ Kosong'}</span>
                </div>
                <div class="notif-config-row">
                    <span class="notif-config-label">Chat ID</span>
                    <span class="notif-config-value ${valClass(tg.has_chat_id)}">${tg.has_chat_id ? '✓ Terkonfigurasi' : '✗ Kosong'}</span>
                </div>
            </div>

            <div class="notif-config-actions">
                <button class="btn btn-secondary" id="notifTestTelegramBtn" style="flex:1;" ${!tg.enabled ? 'disabled' : ''}>
                    <i class="fa-solid fa-paper-plane"></i> Test Telegram
                </button>
            </div>

            ${!cfg.notify_enabled ? `
                <div style="margin-top:14px;padding:10px 12px;background:var(--accent-warn-bg);border:1px solid var(--accent-warn);border-radius:var(--radius-md);font-size:12px;color:var(--accent-warn);font-weight:500;line-height:1.5;">
                    <i class="fa-solid fa-circle-info"></i>
                    Notifikasi nonaktif. Set <code style="font-family:var(--mono);background:var(--surface);padding:1px 5px;border-radius:4px;">NOTIFY_ENABLED=True</code> di <code style="font-family:var(--mono);background:var(--surface);padding:1px 5px;border-radius:4px;">.env</code> dan restart aplikasi untuk mengaktifkan.
                </div>
            ` : ''}
        `;

        const testBtn = $('notifTestTelegramBtn');
        if (testBtn && !testBtn.__bound) {
            testBtn.__bound = true;
            testBtn.addEventListener('click', async () => {
                const orig = testBtn.innerHTML;
                testBtn.disabled = true;
                testBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Mengirim...';

                try {
                    const r = await API.call('/api/v1/notifications/test-channel', {
                        method: 'POST',
                        body: JSON.stringify({ channel: 'telegram' }),
                    });
                    if (r.success) {
                        window.showToast('Notifikasi test terkirim', 'success');
                    } else {
                        const errMsg = r.data?.result?.error || r.error || 'Gagal';
                        window.showToast('Telegram: ' + errMsg, 'error', 6000);
                    }
                } finally {
                    testBtn.disabled = false;
                    testBtn.innerHTML = orig;
                }
            });
        }
    }

    function bindNotificationConfig() {
        const btn = $('notificationConfigBtn');
        if (btn && !btn.__bound) {
            btn.__bound = true;
            btn.addEventListener('click', openNotificationConfigModal);
        }
    }

    function bindSidebarNav() {
        document.querySelectorAll('.sidebar .nav-item').forEach(item => {
            item.addEventListener('click', e => {
                const href = (item.getAttribute('href') || '').trim();
                if (href.startsWith('#')) {
                    e.preventDefault();
                    const targetSection = href.replace('#', '');
                    if (DASHBOARD_SECTIONS.includes(targetSection)) showSection(targetSection);
                }
            });
        });
    }

    async function doLogout() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        try {
            await fetch('/logout', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'X-CSRFToken': meta ? meta.content : '' },
            });
            window.location.href = '/login';
        } catch (e) {
            showToast('Gagal logout. Periksa koneksi lalu coba lagi.', 'error');
        }
    }

    function bindLogout() {
        const logoutBtn = $('logoutBtn');
        if (logoutBtn) logoutBtn.addEventListener('click', e => { e.preventDefault(); doLogout(); });
    }

    function bindModals() {
        document.querySelectorAll('.modal-close').forEach(btn => {
            btn.addEventListener('click', () => {
                const modal = btn.closest('.modal'); if (modal) modal.classList.remove('active');
                unlockBodyScrollIfNoModal();
            });
        });
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', e => {
                if (e.target === modal) { modal.classList.remove('active'); unlockBodyScrollIfNoModal(); }
            });
        });
        const deleteInput = $('deleteConfirmInput');
        if (deleteInput) {
            deleteInput.addEventListener('input', updateDeleteButtonState);
            deleteInput.addEventListener('keydown', e => { if (e.key === 'Enter') { const btn = $('confirmDeleteBtn'); if (btn && !btn.disabled) btn.click(); } });
        }
    }

    function bindActionButtons() {
        const map = {
            'add-device': openAddDeviceModal,
            'add-chart': openAddChartModal,
            'refresh-charts': refreshAllCharts,
            'reset-layout': resetChartLayout,
            'submit-add-device': addDevice,
            'save-device-config': saveDeviceConfig,
            'copy-api-key': copyApiKey,
            'confirm-delete': confirmDelete,
            'save-chart': saveChart,
            'save-analytics-tab': saveAnalyticsTab,
            'delete-analytics-tab': deleteAnalyticsTab,
        };
        Object.entries(map).forEach(([action, handler]) => {
            document.querySelectorAll(`[data-action="${action}"]`).forEach(btn => btn.addEventListener('click', handler));
        });
        const delTabBtn = $('analyticsTabDeleteBtn');
        if (delTabBtn) delTabBtn.addEventListener('click', deleteAnalyticsTab);
        document.querySelectorAll('[data-goto]').forEach(card => {
            card.addEventListener('click', () => {
                const target = card.dataset.goto; const filter = card.dataset.filter;
                if (filter && target === 'devices') { state.deviceFilter = filter; setDeviceFilter(filter); }
                showSection(target);
            });
            if (card.getAttribute('role') === 'button') {
                card.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); card.click(); }
                });
            }
        });
        const activityRefresh = $('activityRefreshBtn');
        if (activityRefresh) activityRefresh.addEventListener('click', loadActivityFeed);
    }

    function bindFilters() {
        const searchInput = $('searchInput');
        if (searchInput) {
            searchInput.addEventListener('input', () => {
                const value = searchInput.value;
                if (state.currentSection === 'map') {
                    state.mapSearchTerm = value.trim();
                    const local = $('mapSearchInput'); if (local && local.value !== value) local.value = value;
                    renderMapDeviceList();
                } else if (state.currentSection === 'graph') {
                    state.graphSearchTerm = value;
                    applyGraphSearch();
                } else if (state.currentSection === 'alerts') {
                    state.alertSearchTerm = value;
                    if (window.AAGuardAlerts && window.AAGuardAlerts.setSearch) {
                        window.AAGuardAlerts.setSearch(value);
                    }
                } else {
                    state.deviceSearchTerm = value;
                    filterDevices();
                }
            });
        }
        document.querySelectorAll('#deviceFilterBar .filter-btn').forEach(btn => btn.addEventListener('click', () => setDeviceFilter(btn.dataset.filter)));
        document.querySelectorAll('#deviceFilterBarFull .filter-btn').forEach(btn => btn.addEventListener('click', () => setDeviceFilterFull(btn.dataset.filter)));
    }

    function bindMapControls() {
        const saveBtn = $('saveLocationBtn'); if (saveBtn) saveBtn.addEventListener('click', saveLocation);
        const clearBtn = $('clearMapSelectionBtn'); if (clearBtn) clearBtn.addEventListener('click', clearMapSelection);
        const resetBtn = $('resetMapViewBtn'); if (resetBtn) resetBtn.addEventListener('click', () => { if (state.mapFull) state.mapFull.flyTo([-2.5489, 118.0149], 5, { duration: 1 }); });
        const searchInput = $('mapSearchInput');
        if (searchInput) {
            let t;
            searchInput.addEventListener('input', e => {
                clearTimeout(t);
                t = setTimeout(() => {
                    state.mapSearchTerm = e.target.value.trim();
                    const nav = $('searchInput'); if (nav && nav.value !== e.target.value) nav.value = e.target.value;
                    renderMapDeviceList();
                }, 150);
            });
        }
        const chips = $('mapFilterChips');
        if (chips) chips.querySelectorAll('.map-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                chips.querySelectorAll('.map-chip').forEach(c => c.classList.remove('active'));
                chip.classList.add('active');
                state.mapFilter = chip.dataset.filter;
                renderMapDeviceList();
            });
        });
    }

    function bindKeyboard() {
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') {
                document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'));
                unlockBodyScrollIfNoModal();
                const trMenu = $('timeRangeMenu'); if (trMenu) trMenu.classList.remove('active');
                const tabMenu = $('tabDropdownMenu'); if (tabMenu) tabMenu.classList.remove('active');
            }
        });
    }

    function bindNavigation() {
        window.addEventListener('popstate', () => { const s = getSectionFromHash(); showSection(s, true); });
        window.addEventListener('hashchange', () => {
            const s = getSectionFromHash();
            if (state.currentSection !== s) showSection(s, true);
            else if (s === 'settings' && window.AAGuardSettings) AAGuardSettings.show(getSettingsTabFromHash());
        });
    }

    function bindEvents() {
        bindSidebarNav();
        bindLogout();
        bindModals();
        bindActionButtons();
        bindDashboardSwitcher();
        bindBackup();
        bindChangePassword();
        bindCleanupButton();
        bindGlobalRules();
        bindRestore();
        bindBulkImport();
        bindNotificationConfig();

        const sysBtn = $('systemInfoBtn');
        if (sysBtn) sysBtn.addEventListener('click', openSystemInfo);

        const resetBtn = $('resetAlertRulesBtn');
        if (resetBtn) resetBtn.addEventListener('click', window.resetDeviceAlertRules);

        bindFilters();
        bindMapControls();
        bindTimeRangeDropdown();
        bindTabDropdown();
        bindGridResize();
        bindKeyboard();
        bindNavigation();

        const themeBtn = $('themeToggleBtn');
        if (themeBtn) themeBtn.addEventListener('click', () => {
            const t = window.ThemeManager.toggle();
            updateThemeUI(t);
            setTimeout(refreshAllCharts, 100);
        });

        window.addEventListener('sidebar-toggle', () => {
            setTimeout(() => {
                if (window.__aaguardMaps) window.__aaguardMaps.forEach(m => { try { m.invalidateSize(); } catch (e) {} });
            }, 400);
        });

        window.addEventListener('resize', () => {
            clearTimeout(window.__aaguardResizeTO);
            window.__aaguardResizeTO = setTimeout(() => {
                if (window.__aaguardMaps) window.__aaguardMaps.forEach(m => { try { m.invalidateSize(); } catch (e) {} });
                clampChartsToCanvas();
                resolveCollisions();
                applyAllGeom();
                state.charts.forEach(c => {
                    if (c.chartInstance) try { c.chartInstance.resize(); } catch (e) {}
                });
            }, 150);
        });

        window.ThemeManager.onChange(() => setTimeout(refreshAllCharts, 100));

        // Handler menu ⋮ di metric cards
        document.addEventListener('nx-metric-action', (e) => {
            const { action, key } = e.detail;
            if (action === 'view') {
                if (key === 'totalDevices' || key === 'onlineDevices' || key === 'offlineDevices') {
                    showSection('devices');
                } else if (key === 'activeAlerts') {
                    showSection('alerts');
                }
            }
        });
    }

    function updateThemeUI(theme) {
        const icon = $('themeIcon'); const label = $('themeLabel');
        if (icon) icon.className = theme === 'light' ? 'fa-solid fa-sun' : 'fa-solid fa-moon';
        if (label) label.textContent = theme === 'light' ? 'Tema Terang' : 'Tema Gelap';
    }

    function bindCleanup() {
        window.addEventListener('beforeunload', () => {
            if (state.dashboardInterval) clearInterval(state.dashboardInterval);
            if (state.autoRefreshInterval) clearInterval(state.autoRefreshInterval);
            if (state.activityRefreshInterval) clearInterval(state.activityRefreshInterval);
            state.charts.forEach(c => { if (c.chartInstance) { stopRace(c.chartInstance); try { const i=echarts.getInstanceByDom(c.chartInstance); if(i) i.dispose(); } catch(e){} try{ if(c.chartInstance._ro){c.chartInstance._ro.disconnect(); c.chartInstance._ro=null;} }catch(e){} } });
        });
    }

    function readDashboardSlug() {
        const meta = document.querySelector('meta[name="dashboard-slug"]');
        if (meta && meta.content) return meta.content.trim() || null;
        const body = document.body;
        if (body && body.dataset && body.dataset.dashboardSlug) return body.dataset.dashboardSlug.trim() || null;
        const m = window.location.pathname.match(/^\/d\/([a-z0-9\-]+)/i);
        return m ? m[1] : null;
    }

    // ==========================================
    // INIT
    // ==========================================
    async function init() {
        if (state.isInitialized) return;
        state.isInitialized = true;
        state.dashboardSlug = readDashboardSlug();
        loadCanvasHeight();
        bindEvents();
        bindCleanup();
        updateThemeUI(window.ThemeManager.get());
        loadGlobalTimeRange();
        updateDateTime();
        setInterval(updateDateTime, 1000);
        let initialSection = getSectionFromHash();
        if (!window.location.hash) {
            try {
                const saved = sessionStorage.getItem(STORAGE_KEYS.LAST_SECTION);
                if (saved && DASHBOARD_SECTIONS.includes(saved)) { initialSection = saved; history.replaceState(null, '', `#${saved}`); }
            } catch (e) {}
        }
        state.currentSection = initialSection;
        await loadCurrentUser();
        await loadCurrentDashboardInfo();
        await loadDashboard();
        await loadAnalyticsTabs();
        showSection(initialSection, true);
        state.dashboardInterval = setInterval(loadDashboard, 30000);
        startAutoRefresh();
        state.activityRefreshInterval = setInterval(() => { if (state.currentSection === 'dashboard') loadActivityFeed(); }, 60000);
        console.log('[Dashboard] Ready v8.0 (metric cards integrated)');
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();