/* ==========================================================
   NEXUS — Helper UI bersama (Fase 0 redesain)
   - applyNeeds(): sembunyikan kontrol sesuai peran/izin (data-needs)
   - Dialog, Drawer, Menu: buka/tutup dengan satu cara
   Tanpa penyimpanan browser. Backend tetap sumber kebenaran (403).
   ========================================================== */
(function (global) {
  'use strict';

  // Peran dashboard aktif: 'owner' | 'editor' | 'viewer' | null
  // Admin global (is_admin) selalu lolos semua syarat.
  function satisfies(token, ctx) {
    const role = ctx.dashboardRole || null;
    if (ctx.isAdmin) return true;
    if (token.indexOf('perm:') === 0) {
      // Izin dari /users/me (sudah termasuk izin turunan, mis. manage → view).
      return (ctx.permissions || []).indexOf(token.slice(5)) !== -1;
    }
    switch (token) {
      case 'admin':  return false;
      case 'owner':  return role === 'owner';
      case 'editor': return role === 'owner' || role === 'editor';
      case 'viewer': return role !== null;
      default:       return false;
    }
  }

  // data-needs="editor" atau "owner admin" atau "perm:foo.view" (salah satu cocok = tampil)
  function allowed(spec, ctx) {
    return String(spec).split(/[\s,]+/).filter(Boolean)
      .some(function (t) { return satisfies(t, ctx); });
  }

  function applyNeeds(ctx, root) {
    ctx = ctx || {};
    const scope = root || document;
    scope.querySelectorAll('[data-needs]').forEach(function (el) {
      el.classList.toggle('nx-hidden', !allowed(el.getAttribute('data-needs'), ctx));
    });
  }

  // ---------- Dialog: konfirmasi, tanpa X ----------
  function openDialog(overlay) {
    overlay.classList.add('nx-open');
    const first = overlay.querySelector('[data-autofocus]') || overlay.querySelector('button');
    if (first) first.focus();
  }
  function closeDialog(overlay) {
    overlay.classList.remove('nx-open');
  }
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    document.querySelectorAll('.nx-overlay.nx-open').forEach(closeDialog);
    document.querySelectorAll('.nx-drawer.nx-open').forEach(function (d) {
      d.classList.remove('nx-open');
    });
  });

  // ---------- Drawer ----------
  function openDrawer(drawer) { drawer.classList.add('nx-open'); }
  function closeDrawer(drawer) { drawer.classList.remove('nx-open'); }

  // ---------- Menu ⋯ ----------
  document.addEventListener('click', function (e) {
    const trigger = e.target.closest('.nx-menu > [data-menu-trigger]');
    document.querySelectorAll('.nx-menu.nx-open').forEach(function (m) {
      if (!trigger || m !== trigger.parentElement) m.classList.remove('nx-open');
    });
    if (trigger) trigger.parentElement.classList.toggle('nx-open');
  });

  // ---------- Kontrol yang belum siap dipakai ----------
  // Elemen dengan aria-disabled="true" tetap terlihat (fitur ada, tapi belum
  // dikonfigurasi) dan memberi penjelasan saat diklik, bukan diam saja.
  document.addEventListener('click', function (e) {
    const el = e.target.closest('[aria-disabled="true"][data-hint]');
    if (!el) return;
    e.preventDefault();
    const msg = el.getAttribute('data-hint');
    if (typeof global.showToast === 'function') global.showToast(msg, 'warning');
  });

  // Delegasi data-click="fnName" (ganti onclick inline): panggil fungsi global
  // dengan nama sama. data-arg opsional (string/angka/true/false/null),
  // data-self=1 tambah elemen sebagai argumen, data-filter untuk go(),
  // data-then fungsi kedua tanpa argumen, data-prevent cegah default.
  document.addEventListener('click', function (e) {
    const el = e.target.closest('[data-click]');
    if (!el) return;
    if (el.hasAttribute('data-prevent')) e.preventDefault();
    const name = el.getAttribute('data-click');
    const raw = el.getAttribute('data-arg');
    if (name === 'click' && raw) {
      const target = document.getElementById(raw);
      if (target) target.click();
      return;
    }
    let obj = global, fn;
    if (name.indexOf('.') !== -1) {
      const parts = name.split('.');
      obj = global[parts[0]];
      fn = obj && obj[parts[1]];
    } else {
      fn = global[name];
    }
    if (typeof fn !== 'function') return;
    const args = [];
    if (raw !== null) {
      if (raw === 'true') args.push(true);
      else if (raw === 'false') args.push(false);
      else if (raw === 'null') args.push(null);
      else if (/^\d+$/.test(raw)) args.push(Number(raw));
      else args.push(raw);
    }
    if (el.hasAttribute('data-self')) args.push(el);
    if (name === 'go' && el.hasAttribute('data-filter')) {
      args.push({ filter: el.getAttribute('data-filter') });
    }
    fn.apply(obj, args);
    const then = el.getAttribute('data-then');
    if (then && typeof global[then] === 'function') global[then]();
  });

  global.NexusUI = {
    applyNeeds: applyNeeds,
    _allowed: allowed,
    openDialog: openDialog,
    closeDialog: closeDialog,
    openDrawer: openDrawer,
    closeDrawer: closeDrawer,
  };
})(window);
