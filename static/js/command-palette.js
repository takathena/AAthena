/* ==========================================================
   AAguard — Command Palette (Ctrl+K / Cmd+K)
   Akses cepat ke fitur AAGuard via keyboard.
   ========================================================== */
(function () {
    'use strict';

    // ============================================================
    // Daftar command — dapat diperluas dengan AAGuardCommandPalette.register()
    // ============================================================
    const COMMANDS = [
        // ---------- HALAMAN ----------
        { id: 'nav-dashboard', group: 'Halaman', label: 'Buka Beranda',
          icon: 'fa-house', keywords: ['home', 'dashboard', 'beranda', 'utama'],
          action: () => _go('#dashboard') },
        { id: 'nav-map', group: 'Halaman', label: 'Buka Peta Lokasi',
          icon: 'fa-map', keywords: ['map', 'peta', 'lokasi'],
          action: () => _go('#map') },
        { id: 'nav-graph', group: 'Halaman', label: 'Buka Analitik',
          icon: 'fa-chart-line', keywords: ['analitik', 'chart', 'grafik', 'graph'],
          action: () => _go('#graph') },
        { id: 'nav-devices', group: 'Halaman', label: 'Buka Perangkat',
          icon: 'fa-microchip', keywords: ['perangkat', 'device', 'devices'],
          action: () => _go('#devices') },
        { id: 'nav-alerts', group: 'Halaman', label: 'Buka Alert Center',
          icon: 'fa-bell', keywords: ['alert', 'notifikasi', 'peringatan'],
          action: () => _go('#alerts') },
        { id: 'nav-settings', group: 'Halaman', label: 'Buka Pengaturan',
          icon: 'fa-gear', keywords: ['pengaturan', 'setting', 'preferensi'],
          action: () => _go('#settings') },

        // ---------- AKSI ----------
        { id: 'theme-toggle', group: 'Aksi', label: 'Ganti tema (gelap / terang)',
          icon: 'fa-circle-half-stroke', keywords: ['tema', 'theme', 'gelap', 'terang', 'dark', 'light'],
          action: () => _toggleTheme() },
        { id: 'change-password', group: 'Aksi', label: 'Ganti password',
          icon: 'fa-key', keywords: ['password', 'sandi', 'ganti', 'ubah'],
          action: () => _click('changePasswordBtn') },
        { id: 'notif-config', group: 'Aksi', label: 'Konfigurasi notifikasi',
          icon: 'fa-bell', keywords: ['notifikasi', 'notification', 'telegram'],
          action: () => _click('notificationConfigBtn') },
        { id: 'add-device', group: 'Aksi', label: 'Tambah perangkat baru',
          icon: 'fa-plus', keywords: ['tambah', 'add', 'new', 'device', 'perangkat'],
          action: () => _click('[data-action="add-device"]'),
          needs: 'editor' },
        { id: 'refresh-dashboard', group: 'Aksi', label: 'Refresh dashboard',
          icon: 'fa-rotate', keywords: ['refresh', 'reload', 'muat ulang'],
          action: () => _refresh() },

        // ---------- ADMIN ----------
        { id: 'manage-users', group: 'Admin', label: 'Kelola user',
          icon: 'fa-users', keywords: ['user', 'pengguna', 'kelola', 'manage', 'admin'],
          action: () => (window.AAGuardUsers ? window.AAGuardUsers.open()
                                           : _click('manageUsersBtn')),
          needs: 'admin' },
        { id: 'global-rules', group: 'Admin', label: 'Global alert rules',
          icon: 'fa-sliders', keywords: ['global', 'rules', 'alert', 'aturan'],
          action: () => _click('globalRulesBtn'),
          needs: 'admin' },
        { id: 'bulk-import', group: 'Admin', label: 'Bulk import perangkat',
          icon: 'fa-file-import', keywords: ['bulk', 'import', 'impor', 'massal'],
          action: () => _click('bulkImportBtn'),
          needs: 'admin' },
        { id: 'backup', group: 'Admin', label: 'Backup database',
          icon: 'fa-database', keywords: ['backup', 'database', 'db'],
          action: () => _click('backupBtn'),
          needs: 'admin' },
        { id: 'cleanup', group: 'Admin', label: 'Cleanup data lama',
          icon: 'fa-broom', keywords: ['cleanup', 'bersih', 'hapus', 'lama'],
          action: () => _click('cleanupBtn'),
          needs: 'admin' },
        { id: 'data-mgmt', group: 'Admin', label: 'Kelola data',
          icon: 'fa-eraser', keywords: ['kelola', 'data', 'hapus', 'purge'],
          action: () => _click('dataMgmtBtn'),
          needs: 'admin' },
        { id: 'system-info', group: 'Admin', label: 'Info sistem',
          icon: 'fa-circle-info', keywords: ['info', 'sistem', 'versi', 'system'],
          action: () => _click('systemInfoBtn') },
    ];

        // ============================================================
    // DEVICE SEARCH — data dinamis dari /api/v1/devices
    // ============================================================
    const DEVICES = {
        list: [],
        loaded: false,
        loading: false,
    };

    async function loadDevices() {
        if (DEVICES.loaded || DEVICES.loading) return;
        DEVICES.loading = true;
        try {
            const res = await fetch('/api/v1/devices?per_page=500', {
                credentials: 'same-origin',
            });
            const data = await res.json();
            if (data.success && Array.isArray(data.devices)) {
                DEVICES.list = data.devices.map(d => ({
                    id: 'device-' + d.device_id,
                    group: 'Perangkat',
                    label: d.device_name || d.device_id,
                    icon: 'fa-microchip',
                    keywords: [
                        d.device_id,
                        d.location || '',
                        d.device_type || '',
                        d.status || '',
                    ].filter(Boolean),
                    hint: d.status === 'online' ? '● online' : (d.status === 'offline' ? '○ offline' : ''),
                    action: () => _openDevice(d.device_id),
                }));
            }
        } catch (e) {
            console.warn('[CmdK] device fetch failed', e);
        } finally {
            DEVICES.loading = false;
            DEVICES.loaded = true;
        }
    }

    function _openDevice(deviceId) {
        close();
        setTimeout(() => {
            try { sessionStorage.setItem('aaguard_back_url', '/#' + (window.location.hash || '#dashboard').replace('#','')); } catch (e) {}
            window.location.href = '/device/' + encodeURIComponent(deviceId);
        }, 80);
    }

    // ============================================================
    // State
    // ============================================================
    const state = {
        isOpen: false,
        query: '',
        filtered: [],
        activeIndex: 0,
        lastFocusedEl: null,
    };

    let overlay = null;
    let inputEl = null;
    let listEl = null;
    let currentCtx = { isAdmin: false, dashboardRole: null, permissions: [] };

    // ============================================================
    // Helpers — dipakai oleh action
    // ============================================================
    function _go(hash) {
        close();
        // Tunggu overlay menutup dulu, baru navigasi
        setTimeout(() => {
            const section = hash.replace('#', '').split('/')[0];
            if (window.location.hash === hash) {
                if (typeof window.__aaguardShowSection === 'function') {
                    window.__aaguardShowSection(section);
                }
                return;
            }
            window.location.hash = hash;
            if (typeof window.__aaguardShowSection === 'function') {
                window.__aaguardShowSection(section);
            }
        }, 80);
    }

    function _toggleTheme() {
        close();
        setTimeout(() => {
            if (window.ThemeManager && typeof window.ThemeManager.toggle === 'function') {
                window.ThemeManager.toggle();
            }
        }, 80);
    }

    function _click(selector) {
        close();
        setTimeout(() => {
            const el = typeof selector === 'string'
                ? document.querySelector(selector)
                : selector;
            if (el) el.click();
        }, 80);
    }

    function _refresh() {
        close();
        setTimeout(() => {
            if (typeof window.__aaguardRefreshDashboard === 'function') {
                window.__aaguardRefreshDashboard();
            } else {
                window.location.reload();
            }
        }, 80);
    }

    // ============================================================
    // Context (permission gating)
    // ============================================================
    function updateContext(ctx) {
        if (ctx && typeof ctx === 'object') {
            currentCtx = {
                isAdmin: !!ctx.isAdmin,
                dashboardRole: ctx.dashboardRole || null,
                permissions: Array.isArray(ctx.permissions) ? ctx.permissions : [],
            };
        }
        if (state.isOpen) applyFilter();
    }

    function _allowed(cmd) {
        if (!cmd.needs) return true;
        const tokens = String(cmd.needs).split(/[\s,]+/).filter(Boolean);
        for (const t of tokens) {
            if (t === 'admin') {
                if (currentCtx.isAdmin) return true;
                continue;
            }
            if (t === 'owner') {
                if (currentCtx.isAdmin) return true;
                if (currentCtx.dashboardRole === 'owner') return true;
                continue;
            }
            if (t === 'editor') {
                if (currentCtx.isAdmin) return true;
                if (currentCtx.dashboardRole === 'owner' || currentCtx.dashboardRole === 'editor') return true;
                continue;
            }
            if (t.startsWith('perm:')) {
                const perm = t.slice(5);
                if (currentCtx.isAdmin) return true;
                if (currentCtx.permissions.indexOf(perm) !== -1) return true;
                continue;
            }
        }
        return false;
    }

    // ============================================================
    // Filter & render
    // ============================================================
    function _normalize(s) {
        return String(s || '').toLowerCase().trim();
    }

    function _match(cmd, q) {
        if (!q) return { score: 0, matchIdx: -1 };
        const label = _normalize(cmd.label);
        if (label.startsWith(q)) return { score: 100, matchIdx: 0 };
        const idx = label.indexOf(q);
        if (idx >= 0) return { score: 80 - idx, matchIdx: idx };
        if (Array.isArray(cmd.keywords)) {
            for (const kw of cmd.keywords) {
                const k = _normalize(kw);
                if (k.startsWith(q)) return { score: 60, matchIdx: -1 };
                if (k.indexOf(q) >= 0) return { score: 40, matchIdx: -1 };
            }
        }
        // Fuzzy: karakter query harus muncul berurutan di label
        let qi = 0;
        for (let i = 0; i < label.length && qi < q.length; i++) {
            if (label[i] === q[qi]) qi++;
        }
        if (qi === q.length) return { score: 10, matchIdx: -1 };
        return null;
    }

    function _highlight(label, q) {
        if (!q) return _esc(label);
        const idx = _normalize(label).indexOf(q);
        if (idx < 0) return _esc(label);
        return _esc(label.slice(0, idx)) +
               '<mark>' + _esc(label.slice(idx, idx + q.length)) + '</mark>' +
               _esc(label.slice(idx + q.length));
    }

    function _esc(s) {
        return String(s || '')
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function applyFilter() {
        const q = _normalize(state.query);
        const scored = [];

        // 1. Command statis (halaman + aksi)
        for (const cmd of COMMANDS) {
            if (!_allowed(cmd)) continue;
            const m = _match(cmd, q);
            if (!m) continue;
            scored.push({ cmd, score: m.score, isDevice: false });
        }

        // 2. Devices (hanya kalau query minimal 1 karakter)
        if (q.length >= 1) {
            // Load device pertama kali user buka palette
            if (!DEVICES.loaded) loadDevices();

            for (const dev of DEVICES.list) {
                const m = _match(dev, q);
                if (!m) continue;
                // Device selalu di bawah command jika score sama
                scored.push({ cmd: dev, score: m.score - 5, isDevice: true });
            }
        }

        scored.sort((a, b) => {
            if (b.score !== a.score) return b.score - a.score;
            // Kalau score sama, command menang atas device
            if (a.isDevice !== b.isDevice) return a.isDevice ? 1 : -1;
            return 0;
        });

        state.filtered = scored.map(x => x.cmd);
        if (state.activeIndex >= state.filtered.length) {
            state.activeIndex = Math.max(0, state.filtered.length - 1);
        }
        render();
    }

    function render() {
        if (!listEl) return;

        if (state.filtered.length === 0) {
            listEl.innerHTML =
                '<div class="nx-cmdk-empty">' +
                    '<i class="fa-solid fa-magnifying-glass"></i>' +
                    'Tidak ada hasil untuk <b>' + _esc(state.query) + '</b>' +
                '</div>';
            return;
        }

        // Group by `group`, pertahankan urutan group
        const groups = {};
        const order = [];
        for (const cmd of state.filtered) {
            const g = cmd.group || 'Lainnya';
            if (!groups[g]) { groups[g] = []; order.push(g); }
            groups[g].push(cmd);
        }

        let html = '';
        let globalIdx = 0;
        const q = _normalize(state.query);

        for (const g of order) {
            html += '<div class="nx-cmdk-group">';
            html += '<div class="nx-cmdk-group-label">' + _esc(g) + '</div>';
            for (const cmd of groups[g]) {
                const isActive = globalIdx === state.activeIndex;
                html += '<button type="button" class="nx-cmdk-item ' +
                        (isActive ? 'nx-cmdk-active' : '') +
                        '" data-cmd-id="' + _esc(cmd.id) + '" data-idx="' + globalIdx + '">' +
                    '<span class="nx-cmdk-item-icon"><i class="fa-solid ' + _esc(cmd.icon || 'fa-circle') + '"></i></span>' +
                    '<span class="nx-cmdk-item-label">' + _highlight(cmd.label, q) + '</span>' +
                    (cmd.hint ? '<span class="nx-cmdk-item-hint">' + _esc(cmd.hint) + '</span>' : '') +
                '</button>';
                globalIdx++;
            }
            html += '</div>';
        }

        listEl.innerHTML = html;

        // Bind click
        listEl.querySelectorAll('.nx-cmdk-item').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const idx = parseInt(btn.dataset.idx, 10);
                runCommand(idx);
            });
            btn.addEventListener('mouseenter', () => {
                const idx = parseInt(btn.dataset.idx, 10);
                if (!Number.isNaN(idx)) {
                    state.activeIndex = idx;
                    _syncActive();
                }
            });
        });

        _scrollActiveIntoView();
    }

    function _syncActive() {
        if (!listEl) return;
        listEl.querySelectorAll('.nx-cmdk-item').forEach(btn => {
            const idx = parseInt(btn.dataset.idx, 10);
            btn.classList.toggle('nx-cmdk-active', idx === state.activeIndex);
        });
        _scrollActiveIntoView();
    }

    function _scrollActiveIntoView() {
        if (!listEl) return;
        const el = listEl.querySelector('.nx-cmdk-item.nx-cmdk-active');
        if (!el) return;
        const listRect = listEl.getBoundingClientRect();
        const elRect = el.getBoundingClientRect();
        if (elRect.top < listRect.top) {
            listEl.scrollTop -= (listRect.top - elRect.top) + 8;
        } else if (elRect.bottom > listRect.bottom) {
            listEl.scrollTop += (elRect.bottom - listRect.bottom) + 8;
        }
    }

    function runCommand(idx) {
        const cmd = state.filtered[idx];
        if (!cmd) return;
        close();
        // Beri jeda kecil agar overlay tertutup sebelum aksi berat
        setTimeout(() => {
            try {
                cmd.action();
            } catch (e) {
                console.error('[CmdK] Action failed:', e);
            }
        }, 60);
    }

    // ============================================================
    // Open / close
    // ============================================================
    function open() {
        if (state.isOpen) return;
        if (!overlay) return;

        state.isOpen = true;
        state.query = '';
        state.activeIndex = 0;
        state.lastFocusedEl = document.activeElement;

        overlay.classList.add('nx-cmdk-open');
        document.body.classList.add('modal-open');

        if (inputEl) {
            inputEl.value = '';
            requestAnimationFrame(() => inputEl.focus());
        }

        // Pre-load device biar kalau user langsung ketik, sudah tersedia
        loadDevices();

        applyFilter();
    }

    function close() {
        if (!state.isOpen) return;
        state.isOpen = false;
        if (overlay) overlay.classList.remove('nx-cmdk-open');
        // Hanya hapus modal-open kalau tidak ada modal lain yang aktif
        if (!document.querySelector('.modal.active')) {
            document.body.classList.remove('modal-open');
        }
        // Kembalikan fokus
        try {
            if (state.lastFocusedEl && document.contains(state.lastFocusedEl)) {
                state.lastFocusedEl.focus();
            } else if (inputEl) {
                inputEl.blur();
            }
        } catch (e) {}
    }

    function toggle() { state.isOpen ? close() : open(); }

    // ============================================================
    // Keyboard
    // ============================================================
    function _onGlobalKeydown(e) {
        // Ctrl+K atau Cmd+K
        if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && (e.key === 'k' || e.key === 'K')) {
            e.preventDefault();
            e.stopPropagation();
            toggle();
            return;
        }
        // '/' juga umum: buka kalau tidak sedang mengetik di input
        if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
            const tag = (e.target && e.target.tagName || '').toLowerCase();
            const isEditable = tag === 'input' || tag === 'textarea' || (e.target && e.target.isContentEditable);
            if (!isEditable) {
                e.preventDefault();
                open();
            }
        }
    }

    function _onPanelKeydown(e) {
        if (!state.isOpen) return;

        if (e.key === 'Escape') {
            e.preventDefault();
            close();
            return;
        }
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (state.filtered.length === 0) return;
            state.activeIndex = (state.activeIndex + 1) % state.filtered.length;
            _syncActive();
            return;
        }
        if (e.key === 'ArrowUp') {
            e.preventDefault();
            if (state.filtered.length === 0) return;
            state.activeIndex = (state.activeIndex - 1 + state.filtered.length) % state.filtered.length;
            _syncActive();
            return;
        }
        if (e.key === 'Home' && e.ctrlKey) {
            e.preventDefault();
            state.activeIndex = 0;
            _syncActive();
            return;
        }
        if (e.key === 'End' && e.ctrlKey) {
            e.preventDefault();
            state.activeIndex = Math.max(0, state.filtered.length - 1);
            _syncActive();
            return;
        }
        if (e.key === 'Enter') {
            e.preventDefault();
            runCommand(state.activeIndex);
            return;
        }
        if (e.key === 'Tab') {
            // Tab = pindah antar item juga (aksesibel)
            e.preventDefault();
            if (state.filtered.length === 0) return;
            if (e.shiftKey) {
                state.activeIndex = (state.activeIndex - 1 + state.filtered.length) % state.filtered.length;
            } else {
                state.activeIndex = (state.activeIndex + 1) % state.filtered.length;
            }
            _syncActive();
            return;
        }
    }

    // ============================================================
    // Build DOM
    // ============================================================
    function build() {
        overlay = document.createElement('div');
        overlay.className = 'nx-cmdk-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-label', 'Command palette');

        overlay.innerHTML =
            '<div class="nx-cmdk" role="document">' +
                '<div class="nx-cmdk-search">' +
                    '<i class="fa-solid fa-magnifying-glass nx-cmdk-search-icon"></i>' +
                    '<input type="text" class="nx-cmdk-input" placeholder="Cari halaman, aksi, atau perangkat…" ' +
                        'autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" ' +
                        'aria-label="Cari perintah">' +
                    '<span class="nx-cmdk-kbd">ctrl K</span>' +
                '</div>' +
                '<div class="nx-cmdk-list" role="listbox"></div>' +
                '<div class="nx-cmdk-footer">' +
                    '<span class="nx-cmdk-footer-group">' +
                        '<span class="nx-cmdk-footer-kbd">↑</span>' +
                        '<span class="nx-cmdk-footer-kbd">↓</span>' +
                        '<span>pilih</span>' +
                    '</span>' +
                    '<span class="nx-cmdk-footer-group">' +
                        '<span class="nx-cmdk-footer-kbd">Enter</span>' +
                        '<span>buka</span>' +
                    '</span>' +
                    '<span class="nx-cmdk-footer-group">' +
                        '<span class="nx-cmdk-footer-kbd">Esc</span>' +
                        '<span>tutup</span>' +
                    '</span>' +
                    '<span class="nx-cmdk-footer-group" style="margin-left:auto;">' +
                        '<span class="nx-cmdk-footer-kbd">/</span>' +
                        '<span>fokus cari</span>' +
                    '</span>' +
                '</div>' +
            '</div>';

        document.body.appendChild(overlay);

        inputEl = overlay.querySelector('.nx-cmdk-input');
        listEl = overlay.querySelector('.nx-cmdk-list');

        // Input event
        inputEl.addEventListener('input', () => {
            state.query = inputEl.value;
            state.activeIndex = 0;
            applyFilter();
        });

        // Klik di luar panel = tutup
        overlay.addEventListener('mousedown', (e) => {
            if (e.target === overlay) {
                e.preventDefault();
                close();
            }
        });

        // Keyboard di dalam panel
        overlay.addEventListener('keydown', _onPanelKeydown);

        // Global keyboard
        document.addEventListener('keydown', _onGlobalKeydown, true);

        // Cegah input blur saat klik item (mousedown pada list)
        listEl.addEventListener('mousedown', (e) => {
            if (e.target.closest('.nx-cmdk-item')) {
                e.preventDefault();
            }
        });
    }

    // ============================================================
    // Public API
    // ============================================================
    function register(cmd) {
        if (!cmd || !cmd.id || !cmd.label || typeof cmd.action !== 'function') {
            console.warn('[CmdK] register: butuh { id, label, action }');
            return;
        }
        // Cegah duplikat ID
        const idx = COMMANDS.findIndex(c => c.id === cmd.id);
        if (idx >= 0) COMMANDS[idx] = Object.assign({}, COMMANDS[idx], cmd);
        else COMMANDS.push(cmd);
    }

        // ============================================================
    // Search box trigger — klik kotak search lama = buka palette
    // (search box lama untuk filter per halaman digantikan palette)
    // ============================================================
    function bindSearchBoxTrigger() {
        // Cegah input lama menerima fokus saat diklik
        document.addEventListener('mousedown', function (e) {
            const sb = e.target.closest('.search-box');
            if (!sb || sb.classList.contains('search-context')) return;
            e.preventDefault();  // cegah focus ke input
        }, true);

        // Klik → buka palette
        document.addEventListener('click', function (e) {
            const sb = e.target.closest('.search-box');
            if (!sb || sb.classList.contains('search-context')) return;
            e.preventDefault();
            e.stopPropagation();
            open();
        }, true);

        // Ubah visual jadi klik-able (cursor pointer + opacity input)
        const style = document.createElement('style');
        style.textContent =
            '.search-box { cursor: pointer; }' +
            '.search-box input { pointer-events: none; cursor: pointer; }';
        document.head.appendChild(style);
    }

    function init() {
        const stale = document.querySelector('.nx-cmdk-overlay');
        if (stale) stale.remove();
        build();
        bindSearchBoxTrigger();
        console.log('[CmdK] Ready — Ctrl+K atau / untuk membuka');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.AAGuardCommandPalette = {
        open,
        close,
        toggle,
        register,
        updateContext,
        isOpen: () => state.isOpen,
    };
})();