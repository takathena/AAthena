/* ==========================================
   AAguard IoT - Sidebar Toggle v4
   - Toggle via class .sidebar-toggle-btn (bisa multiple)
   - Logo = link ke #dashboard (bukan toggle)
   - DESKTOP (>992px): collapsed (icon-only 72px) ↔ expanded (240px)
   - MOBILE (≤992px): mini (72px) ↔ overlay expanded (240px)
   ========================================== */

(function() {
    'use strict';

    const STORAGE_KEY = 'aaguard-sidebar-collapsed';
    const MOBILE_BREAKPOINT = 992;
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT}px)`);

    function $(id) { return document.getElementById(id); }
    function isMobile() { return mql.matches; }
    function isCollapsedStored() {
        return localStorage.getItem(STORAGE_KEY) === 'true';
    }

    function invalidateMaps() {
        setTimeout(() => {
            if (window.__aaguardMaps) {
                window.__aaguardMaps.forEach(m => {
                    try { m.invalidateSize(); } catch (e) {}
                });
            }
        }, 300);
    }

    // ---------- DESKTOP ----------
    function setDesktopCollapsed(collapsed) {
        const sidebar = $('sidebar');
        const main = $('mainContent');
        if (!sidebar) return;

        sidebar.classList.toggle('collapsed', collapsed);
        if (main) main.classList.toggle('expanded', collapsed);

        try { localStorage.setItem(STORAGE_KEY, collapsed ? 'true' : 'false'); } catch (e) {}

        invalidateMaps();
        window.dispatchEvent(new CustomEvent('sidebar-toggle', {
            detail: { collapsed, mode: 'desktop' }
        }));
    }

    // ---------- MOBILE ----------
    function setMobileExpanded(expanded) {
        const sidebar = $('sidebar');
        const backdrop = $('sidebarBackdrop');
        const main = $('mainContent');
        if (!sidebar) return;

        if (expanded) {
            sidebar.classList.remove('collapsed');
            sidebar.classList.add('mobile-open');
            if (backdrop) backdrop.classList.add('active');
            if (main) main.classList.remove('expanded');
            document.body.style.overflow = 'hidden';
        } else {
            sidebar.classList.add('collapsed');
            sidebar.classList.remove('mobile-open');
            if (backdrop) backdrop.classList.remove('active');
            if (main) main.classList.add('expanded');
            document.body.style.overflow = '';
        }

        invalidateMaps();
        window.dispatchEvent(new CustomEvent('sidebar-toggle', {
            detail: { expanded, mode: 'mobile' }
        }));
    }

    function isMobileExpanded() {
        const sidebar = $('sidebar');
        return sidebar && sidebar.classList.contains('mobile-open');
    }

    // ---------- MODE SWITCH ----------
    function applyMode() {
        const sidebar = $('sidebar');
        const backdrop = $('sidebarBackdrop');
        const main = $('mainContent');
        if (!sidebar) return;

        if (isMobile()) {
            sidebar.classList.remove('mobile-open');
            sidebar.classList.add('collapsed');
            if (backdrop) backdrop.classList.remove('active');
            if (main) main.classList.add('expanded');
            document.body.style.overflow = '';
        } else {
            sidebar.classList.remove('mobile-open');
            if (backdrop) backdrop.classList.remove('active');
            document.body.style.overflow = '';

            const collapsed = isCollapsedStored();
            setDesktopCollapsed(collapsed);
        }

        invalidateMaps();
    }

    function toggleSidebar() {
        if (isMobile()) {
            setMobileExpanded(!isMobileExpanded());
        } else {
            const sidebar = $('sidebar');
            if (!sidebar) return;
            const willCollapse = !sidebar.classList.contains('collapsed');
            setDesktopCollapsed(willCollapse);
        }
    }

    function init() {
        applyMode();

        // Bind SEMUA toggle buttons (header sidebar + topbar)
        document.querySelectorAll('.sidebar-toggle-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                toggleSidebar();
            });
        });

        // Backdrop click (mobile)
        const backdrop = $('sidebarBackdrop');
        if (backdrop) {
            backdrop.addEventListener('click', () => {
                if (isMobile() && isMobileExpanded()) {
                    setMobileExpanded(false);
                }
            });
        }

        // Esc untuk tutup overlay (mobile)
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && isMobile() && isMobileExpanded()) {
                setMobileExpanded(false);
            }
        });

        // Auto-close overlay saat pilih menu (mobile)
        document.querySelectorAll('.sidebar-nav .nav-item, .sidebar-footer .nav-item')
            .forEach(item => {
                item.addEventListener('click', () => {
                    if (isMobile() && isMobileExpanded()) {
                        setTimeout(() => setMobileExpanded(false), 120);
                    }
                });
            });

        // AI belum aktif (LLM_API_KEY kosong): item non-klik, klik hanya
        // menampilkan hint lewat ui.js — pastikan tidak terjadi navigasi.
        const aiOff = $('chatDisabledBtn');
        if (aiOff) {
            aiOff.addEventListener('click', (e) => { e.preventDefault(); });
            aiOff.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') e.preventDefault();
            });
        }

        // Handle resize — switch mode
        const onChange = () => applyMode();
        if (mql.addEventListener) mql.addEventListener('change', onChange);
        else mql.addListener(onChange);

        console.log('[Sidebar] Initialized v4. Mobile:', isMobile());
    }

    // Expose public API
    window.toggleSidebar = toggleSidebar;
    window.AAGuardSidebar = {
        toggle: toggleSidebar,
        setDesktopCollapsed,
        setMobileExpanded,
        isMobile,
        isMobileExpanded,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();