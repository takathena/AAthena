/* ==========================================================
   NEXUS — Kelola Pengguna di Pengaturan › Pengguna
   - Daftar langsung tampil saat tab dibuka
   - Tambah/edit lewat laci kanan: X dan Simpan saja
   - Hapus lewat dialog Batal | Hapus (tanpa X)
   - Peran: User, Moderator, Admin (Superadmin hanya tampil, tidak bisa diubah)
   Aturan peran dan izin ditegakkan backend; UI hanya membatasi tampilan.
   Tanpa penyimpanan browser.
   ========================================================== */
(function (global) {
  'use strict';

  const API_BASE = '/api/v1/users';
  const ROLE_LABEL = { superadmin: 'Superadmin', admin: 'Admin', moderator: 'Moderator', user: 'User' };
  const PRIVILEGED = ['superadmin', 'admin'];

  const state = {
    users: [], me: null, editing: null, editUser: null,
    dirty: false, loaded: false,
  };

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
  const toast = (msg, type) => { if (global.showToast) global.showToast(msg, type); };
  const isPriv = (role) => PRIVILEGED.indexOf(role) !== -1;
  const callerIsSuper = () => !!state.me && state.me.role === 'superadmin';

  // ---------- Daftar ----------
  async function loadMe() {
    if (state.me) return;
    const res = await global.API.call('/api/v1/users/me');
    if (res.success && res.data && res.data.user) state.me = res.data.user;
  }

  async function load() {
    const list = $('usersList');
    if (!list) return;
    list.innerHTML = '<div class="nx-empty">Memuat pengguna…</div>';
    await loadMe();
    const res = await global.API.call(API_BASE);
    if (!res.success) {
      list.innerHTML = '<div class="nx-empty"><div class="nx-empty__title">Gagal memuat pengguna</div>'
        + '<div>' + esc(res.error || 'Koneksi gagal') + '</div></div>';
      return;
    }
    state.users = res.data.users || [];
    state.loaded = true;
    render();
  }

  function canEditRow(u) {
    if (!state.me) return false;
    if (u.id === state.me.id) return true;               // profil sendiri
    if (u.role === 'superadmin') return false;
    if (isPriv(u.role) && !callerIsSuper()) return false;
    return true;
  }

  function canDeleteRow(u) {
    if (!state.me || u.id === state.me.id) return false;
    if (u.role === 'superadmin') return false;
    if (isPriv(u.role) && !callerIsSuper()) return false;
    return true;
  }

  function render() {
    const list = $('usersList');
    if (!list) return;
    const q = (($('usersSearch') || {}).value || '').trim().toLowerCase();
    const rows = state.users.filter((u) =>
      !q || (u.username || '').toLowerCase().includes(q) || (u.display_name || '').toLowerCase().includes(q));

    if (state.users.length === 0) {
      list.innerHTML = '<div class="nx-empty"><div class="nx-empty__title">Belum ada pengguna</div>'
        + '<div>Tambah pengguna pertama dengan tombol di atas.</div></div>';
      return;
    }
    if (rows.length === 0) {
      list.innerHTML = '<div class="nx-empty">Tidak ada pengguna yang cocok.</div>';
      return;
    }

    list.innerHTML = rows.map((u) => {
      const isMe = !!state.me && u.id === state.me.id;
      const roleBadge = '<span class="nx-badge' + (isPriv(u.role) ? ' nx-badge--ok' : '') + '">'
        + esc(ROLE_LABEL[u.role] || u.role) + '</span>';
      const meBadge = isMe ? ' <span class="nx-badge">Anda</span>' : '';
      const items = [];
      if (canEditRow(u)) items.push('<button class="nx-menu__item" type="button" data-user-action="edit" data-user-id="' + u.id + '">Edit</button>');
      if (canDeleteRow(u)) items.push('<button class="nx-menu__item nx-menu__item--danger" type="button" data-user-action="delete" data-user-id="' + u.id + '">Hapus</button>');
      const menu = items.length ? (
        '<div class="nx-menu">'
        + '<button class="nx-btn nx-btn--icon nx-btn--ghost" type="button" data-menu-trigger title="Aksi" aria-label="Aksi untuk ' + esc(u.username) + '">'
        + '<i class="fa-solid fa-ellipsis"></i></button>'
        + '<div class="nx-menu__list">' + items.join('') + '</div></div>'
      ) : '';
      return '<div class="nx-user-row" data-user-id="' + u.id + '">'
        + '<div class="nx-user-row__main">'
        +   '<div class="nx-user-row__name">' + esc(u.display_name || u.username) + ' ' + roleBadge + meBadge + '</div>'
        +   '<div class="nx-user-row__meta">@' + esc(u.username) + '</div>'
        + '</div>' + menu + '</div>';
    }).join('');
  }

  // ---------- Laci (tambah/edit) ----------
  function setDirty(v) {
    state.dirty = v;
    const save = $('userFormSave');
    if (save && state.editing && state.editing !== 'new') save.hidden = !v;
  }

  function selectedRole() {
    const r = document.querySelector('input[name="userFormRole"]:checked');
    return r ? r.value : 'user';
  }

  function setRole(role) {
    document.querySelectorAll('input[name="userFormRole"]').forEach((r) => { r.checked = r.value === role; });
  }

  // Atur apa yang bisa diubah sesuai peran pemanggil dan target.
  function applyFormRules(target) {
    const superCaller = callerIsSuper();
    const targetRole = target ? target.role : 'user';
    const isSuperTarget = targetRole === 'superadmin';
    const adminRadio = $('userFormRoleAdminLabel').querySelector('input');
    const roleInputs = document.querySelectorAll('input[name="userFormRole"]');

    roleInputs.forEach((r) => { r.disabled = isSuperTarget; });
    if (adminRadio) adminRadio.disabled = isSuperTarget || !superCaller;
    $('userFormRoleSuperNote').hidden = !isSuperTarget;

    const allPerms = isPriv(targetRole) || isSuperTarget;
    $('userFormAllPerms').hidden = !allPerms;
  }

  function fillForm(u) {
    $('userFormId').value = u ? String(u.id) : '';
    $('userFormUsername').value = u ? (u.username || '') : '';
    $('userFormUsername').readOnly = !!u;
    $('userFormDisplayName').value = u ? (u.display_name || '') : '';
    $('userFormPassword').value = '';
    $('userFormPasswordLabel').textContent = u ? 'Password baru (kosongkan jika tidak diubah)' : 'Password';
    $('userFormPasswordHint').textContent = u ? 'Kosongkan jika tidak ingin mengubah password.' : 'Minimal 8 karakter.';
    setRole(u ? (u.role || 'user') : 'user');
    $('userFormError').hidden = true;
    $('userFormError').textContent = '';
    applyFormRules(u);
  }

  async function openForm(u) {
    state.editing = u || 'new';
    state.editUser = u || null;
    $('userDrawerTitle').textContent = u ? 'Edit pengguna' : 'Pengguna baru';
    fillForm(u || null);
    setDirty(false);
    $('userFormSave').hidden = !!u;
    global.NexusUI && NexusUI.openDrawer($('userDrawer'));

    setTimeout(() => { const f = u ? $('userFormDisplayName') : $('userFormUsername'); if (f) f.focus(); }, 120);
  }

  function closeForm(force) {
    if (!force && state.dirty) {
      global.NexusUI && NexusUI.openDialog($('userDiscardDialog'));
      return;
    }
    state.editing = null;
    state.editUser = null;
    setDirty(false);
    global.NexusUI && NexusUI.closeDrawer($('userDrawer'));
  }

  function showFormError(msg) {
    const el = $('userFormError');
    el.textContent = msg;
    el.hidden = false;
  }

  async function save() {
    const id = $('userFormId').value;
    const username = $('userFormUsername').value.trim();
    const displayName = $('userFormDisplayName').value.trim();
    const password = $('userFormPassword').value;
    const role = selectedRole();
    $('userFormError').hidden = true;

    if (!id) {
      if (username.length < 3) return showFormError('Username minimal 3 karakter');
      if (password.length < 8) return showFormError('Password minimal 8 karakter');
    } else if (password && password.length < 8) {
      return showFormError('Password baru minimal 8 karakter');
    }

    const btn = $('userFormSave');
    btn.disabled = true;
    try {
      let res;
      let userId = id;
      if (!id) {
        res = await global.API.call(API_BASE, {
          method: 'POST',
          body: JSON.stringify({ username, password, display_name: displayName || username, role }),
        });
        if (res.success && res.data && res.data.user) userId = res.data.user.id;
      } else {
        const payload = {};
        // Superadmin: peran tidak dikirim (backend menolak perubahannya).
        if (!(state.editUser && state.editUser.role === 'superadmin')) payload.role = role;
        if (displayName) payload.display_name = displayName;
        if (password) payload.password = password;
        res = await global.API.call(API_BASE + '/' + id, { method: 'PUT', body: JSON.stringify(payload) });
      }
      if (!res.success) return showFormError(res.error || 'Gagal menyimpan pengguna');

      toast(id ? 'Pengguna diperbarui' : 'Pengguna dibuat', 'success');
      closeForm(true);
      await load();
      // Perbarui profil sendiri bila yang diubah adalah akun pemanggil.
      if (state.me && String(state.me.id) === String(userId)) { state.me = null; await loadMe(); }
    } finally {
      btn.disabled = false;
    }
  }

  // ---------- Hapus ----------
  let pendingDelete = null;

  function askDelete(u) {
    pendingDelete = u;
    $('userDeleteText').textContent =
      'Pengguna "' + (u.display_name || u.username) + '" (@' + u.username + ') akan dihapus. '
      + 'Dashboard milik pengguna ini akan dipindahkan ke admin.';
    global.NexusUI && NexusUI.openDialog($('userDeleteDialog'));
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    const u = pendingDelete;
    const res = await global.API.call(API_BASE + '/' + u.id, { method: 'DELETE' });
    global.NexusUI && NexusUI.closeDialog($('userDeleteDialog'));
    pendingDelete = null;
    if (res.success) { toast('Pengguna dihapus', 'success'); await load(); }
    else toast(res.error || 'Gagal menghapus pengguna', 'error');
  }

  // ---------- Binding ----------
  function bind() {
    const add = $('usersAddBtn');
    if (add) add.addEventListener('click', () => openForm(null));

    const search = $('usersSearch');
    if (search) search.addEventListener('input', render);

    const list = $('usersList');
    if (list) list.addEventListener('click', (e) => {
      const item = e.target.closest('[data-user-action]');
      if (!item) return;
      const u = state.users.find((x) => x.id === parseInt(item.dataset.userId, 10));
      const menu = item.closest('.nx-menu');
      if (menu) menu.classList.remove('nx-open');
      if (!u) return;
      if (item.dataset.userAction === 'edit') openForm(u);
      if (item.dataset.userAction === 'delete') askDelete(u);
    });

    const form = $('userForm');
    if (form) {
      form.addEventListener('input', () => setDirty(true));
      form.addEventListener('change', () => { setDirty(true); });
      form.addEventListener('submit', (e) => { e.preventDefault(); save(); });
    }
    const saveBtn = $('userFormSave');
    if (saveBtn) saveBtn.addEventListener('click', save);

    const closeBtn = $('userDrawerClose');
    if (closeBtn) closeBtn.addEventListener('click', () => closeForm(false));

    // Escape di laci dengan perubahan belum disimpan: tanyakan dulu, jangan langsung tutup.
    window.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      const drawer = $('userDrawer');
      if (drawer && drawer.classList.contains('nx-open') && state.dirty) {
        e.stopImmediatePropagation();
        e.preventDefault();
        global.NexusUI && NexusUI.openDialog($('userDiscardDialog'));
      }
    }, true);

    const discardOk = $('userDiscardConfirm');
    if (discardOk) discardOk.addEventListener('click', () => {
      global.NexusUI && NexusUI.closeDialog($('userDiscardDialog'));
      closeForm(true);
    });
    const discardCancel = $('userDiscardCancel');
    if (discardCancel) discardCancel.addEventListener('click', () => {
      global.NexusUI && NexusUI.closeDialog($('userDiscardDialog'));
    });

    const delOk = $('userDeleteConfirm');
    if (delOk) delOk.addEventListener('click', confirmDelete);
    const delCancel = $('userDeleteCancel');
    if (delCancel) delCancel.addEventListener('click', () => {
      pendingDelete = null;
      global.NexusUI && NexusUI.closeDialog($('userDeleteDialog'));
    });

    // Muat daftar saat tab Pengguna dibuka.
    document.addEventListener('nexus:settings-tab', (e) => {
      if (e.detail && e.detail.tab === 'pengguna') load();
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();

  // Satu-satunya pintu masuk kelola pengguna (dipakai command palette & tombol
  // legacy). Membuka tab Pengaturan > Pengguna, lalu drawer form.
  function open(u) {
    if (location.hash !== '#settings/pengguna') location.hash = '#settings/pengguna';
    document.dispatchEvent(new CustomEvent('nexus:settings-tab', { detail: { tab: 'pengguna' } }));
    load();
    if (u !== undefined) openForm(u || null);
  }

  global.NexusUsers = { load: load, open: open, openForm: openForm };
})(window);
