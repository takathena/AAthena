/* ==========================================================
   AAguard — Halaman Pengaturan (Fase 1)
   - Tab di #settings/<tab>; tab yang tidak diizinkan disembunyikan
   - Tombol di halaman ini memicu tombol lama (data-proxy) agar
     handler yang sudah ada tetap dipakai.
   Tanpa penyimpanan browser.
   ========================================================== */
(function (global) {
  'use strict';

  const TABS = ['umum', 'notifikasi', 'alert-rules', 'pengguna', 'data', 'impor', 'sistem'];

  function root() { return document.getElementById('settingsSection'); }

  function isTabVisible(tab) {
    const btn = root() && root().querySelector('[data-settings-tab="' + tab + '"]');
    return !!btn && !btn.classList.contains('nx-hidden');
  }

  function show(tab) {
    const el = root();
    if (!el) return;
    if (!TABS.includes(tab) || !isTabVisible(tab)) tab = 'umum';

    el.querySelectorAll('[data-settings-tab]').forEach(function (b) {
      const active = b.getAttribute('data-settings-tab') === tab;
      b.setAttribute('aria-selected', active ? 'true' : 'false');
      b.classList.toggle('is-active', active);
    });
    el.querySelectorAll('[data-settings-panel]').forEach(function (p) {
      const active = p.getAttribute('data-settings-panel') === tab;
      p.hidden = !active;
    });

    document.dispatchEvent(new CustomEvent('aaguard:settings-tab', { detail: { tab: tab } }));
  }

  function setHashTab(tab) {
    const newHash = '#settings/' + tab;
    if (window.location.hash !== newHash) {
      try { history.replaceState(null, '', newHash); } catch (e) {}
    }
  }

  function init() {
    // Tombol [data-proxy] di mana pun (mis. menu ⋯ Perangkat) memicu tombol lama.
    document.addEventListener('click', function (e) {
      if (root() && e.target.closest('#settingsSection')) return; // ditangani di bawah
      const p = e.target.closest('[data-proxy]');
      if (!p) return;
      const target = document.getElementById(p.getAttribute('data-proxy'));
      if (target) target.click();
    });

    const el = root();
    if (!el) return;

    // Sembunyikan tab dan panel admin sejak awal (sebelum daftar dashboard dimuat).
    const meta = document.querySelector('meta[name="is-admin"]');
    if (window.AAGuardUI) {
      AAGuardUI.applyNeeds({ isAdmin: !!meta && meta.content === '1', dashboardRole: null }, el);
    }

    el.addEventListener('click', function (e) {
      const tabBtn = e.target.closest('[data-settings-tab]');
      if (tabBtn) {
        const tab = tabBtn.getAttribute('data-settings-tab');
        setHashTab(tab);
        show(tab);
        return;
      }
      const proxy = e.target.closest('[data-proxy]');
      if (proxy) {
        const target = document.getElementById(proxy.getAttribute('data-proxy'));
        if (target) target.click();
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  global.AAGuardSettings = { show: show, TABS: TABS };
})(window);
