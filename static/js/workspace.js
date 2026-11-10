/* ============================================================
   AAguard — Workspace UI
   - Bagikan dashboard (anggota viewer/editor)
   - Telegram per dashboard
   - Kelola Data (hapus per rentang waktu, kecilkan file) — admin
   Backend adalah sumber kebenaran hak akses; file ini hanya antarmuka.
   ============================================================ */
(function () {
    'use strict';

    const $ = (id) => document.getElementById(id);
    const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const toast = (msg, type, ms) => (window.showToast ? window.showToast(msg, type || 'info', ms) : console.log(msg));
    const openModal = (id) => { const el = $(id); if (el) el.classList.add('active'); };
    const closeModal = (id) => { const el = $(id); if (el) el.classList.remove('active'); };
    const currentEditId = () => parseInt(($('dashboardEditId') || {}).value || '0', 10);

    // ------------------------------------------------------------
    // BAGIKAN DASHBOARD
    // ------------------------------------------------------------
    async function loadMembers(dashId) {
        const box = $('shareMemberList');
        if (!box) return;
        box.innerHTML = '<div style="font-size:12px;color:var(--text-3);">Memuat...</div>';
        const res = await API.call(`/api/v1/dashboards/${dashId}/members`);
        if (!res.success) {
            box.innerHTML = `<div style="font-size:12px;color:var(--accent-crit);">${esc(res.error || 'Gagal memuat anggota')}</div>`;
            return;
        }
        const owner = res.data.owner;
        const members = res.data.members || [];
        const row = (inner) => `<div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--hairline);font-size:13px;">${inner}</div>`;
        let html = owner ? row(`<i class="fa-solid fa-crown" style="color:var(--text-3);width:16px;"></i>
            <span style="flex:1;">${esc(owner.display_name || owner.username)} <span class="ws-badge">pemilik</span></span>`) : '';
        html += members.map((m) => row(`<i class="fa-solid fa-user" style="color:var(--text-3);width:16px;"></i>
            <span style="flex:1;">${esc(m.display_name || m.username)}
                <span style="color:var(--text-3);font-size:11px;">@${esc(m.username)}</span></span>
            <select data-member-role="${m.user_id}" style="width:100px;">
                <option value="viewer" ${m.role === 'viewer' ? 'selected' : ''}>Viewer</option>
                <option value="editor" ${m.role === 'editor' ? 'selected' : ''}>Editor</option>
            </select>
            <button type="button" class="btn btn-secondary" data-member-remove="${m.user_id}" title="Keluarkan"
                    style="width:36px;padding:0 !important;"><i class="fa-solid fa-xmark"></i></button>`)).join('');
        if (!members.length) {
            html += '<div style="font-size:12px;color:var(--text-3);padding:10px 0;">Belum dibagikan ke siapa pun.</div>';
        }
        box.innerHTML = html;

        box.querySelectorAll('[data-member-role]').forEach((sel) => {
            sel.addEventListener('change', async () => {
                const uid = parseInt(sel.dataset.memberRole, 10);
                const m = members.find((x) => x.user_id === uid);
                const r = await API.call(`/api/v1/dashboards/${dashId}/members`, {
                    method: 'PUT', body: JSON.stringify({ username: m.username, role: sel.value }),
                });
                toast(r.success ? 'Peran diperbarui' : (r.error || 'Gagal'), r.success ? 'success' : 'error');
                if (!r.success) loadMembers(dashId);
            });
        });
        box.querySelectorAll('[data-member-remove]').forEach((btn) => {
            btn.addEventListener('click', async () => {
                const uid = parseInt(btn.dataset.memberRemove, 10);
                const m = members.find((x) => x.user_id === uid);
                if (!confirm(`Keluarkan ${m ? m.username : 'anggota ini'} dari dashboard?`)) return;
                const r = await API.call(`/api/v1/dashboards/${dashId}/members/${uid}`, { method: 'DELETE' });
                toast(r.success ? 'Anggota dikeluarkan' : (r.error || 'Gagal'), r.success ? 'success' : 'error');
                loadMembers(dashId);
            });
        });
    }

    function openShare() {
        const id = currentEditId();
        if (!id) return;
        closeModal('dashboardModal');
        const u = $('shareUsername'); if (u) u.value = '';
        openModal('dashboardShareModal');
        loadMembers(id);
    }

    async function addMember() {
        const id = currentEditId();
        const username = (($('shareUsername') || {}).value || '').trim();
        const role = ($('shareRole') || {}).value || 'viewer';
        if (!username) { toast('Isi username', 'error'); return; }
        const r = await API.call(`/api/v1/dashboards/${id}/members`, {
            method: 'PUT', body: JSON.stringify({ username, role }),
        });
        if (r.success) {
            toast('Anggota ditambahkan', 'success');
            $('shareUsername').value = '';
            loadMembers(id);
        } else {
            toast(r.error || 'Gagal menambah anggota', 'error');
        }
    }

    // ------------------------------------------------------------
    // TELEGRAM PER DASHBOARD
    // ------------------------------------------------------------
    async function openTelegram() {
        const id = currentEditId();
        if (!id) return;
        closeModal('dashboardModal');
        const res = await API.call(`/api/v1/dashboards/${id}/telegram`);
        if (!res.success) { toast(res.error || 'Gagal memuat konfigurasi', 'error'); return; }
        const t = res.data.telegram;
        $('tgToken').value = '';
        $('tgToken').placeholder = t.configured ? `${t.token_masked} (tersimpan)` : '123456:ABC-DEF...';
        $('tgChatId').value = t.chat_id || '';
        $('tgEnabled').checked = t.configured ? t.enabled : true;
        $('tgDeleteBtn').style.display = t.configured ? 'inline-flex' : 'none';
        $('tgHelp').textContent = t.configured
            ? 'Alert perangkat di dashboard ini dikirim ke bot di bawah.'
            : (t.default_bot_available
                ? 'Belum ada bot khusus: alert dashboard ini sementara dikirim ke bot default server.'
                : 'Belum ada bot khusus dan bot default server tidak aktif: alert dashboard ini belum terkirim ke Telegram.');
        openModal('dashboardTelegramModal');
    }

    async function saveTelegram() {
        const id = currentEditId();
        const body = {
            bot_token: ($('tgToken').value || '').trim(),
            chat_id: ($('tgChatId').value || '').trim(),
            enabled: $('tgEnabled').checked,
        };
        const r = await API.call(`/api/v1/dashboards/${id}/telegram`, { method: 'PUT', body: JSON.stringify(body) });
        if (r.success) {
            toast('Telegram disimpan', 'success');
            closeModal('dashboardTelegramModal');
        } else {
            toast(r.error || 'Gagal menyimpan', 'error', 5000);
        }
    }

    async function testTelegram() {
        const id = currentEditId();
        // Simpan dulu bila ada perubahan, supaya tes memakai konfigurasi terbaru.
        const token = ($('tgToken').value || '').trim();
        const chat = ($('tgChatId').value || '').trim();
        if (token || chat) {
            const s = await API.call(`/api/v1/dashboards/${id}/telegram`, {
                method: 'PUT', body: JSON.stringify({ bot_token: token, chat_id: chat, enabled: $('tgEnabled').checked }),
            });
            if (!s.success) { toast(s.error || 'Gagal menyimpan', 'error', 5000); return; }
            $('tgToken').value = '';
        }
        toast('Mengirim pesan tes...', 'info');
        const r = await API.call(`/api/v1/dashboards/${id}/telegram/test`, { method: 'POST' });
        toast(r.success ? 'Pesan tes terkirim — cek Telegram Anda' : (r.error || 'Gagal mengirim tes'),
            r.success ? 'success' : 'error', 5000);
    }

    async function deleteTelegram() {
        const id = currentEditId();
        if (!confirm('Hapus konfigurasi Telegram dashboard ini?\nAlert akan kembali memakai bot default server (jika ada).')) return;
        const r = await API.call(`/api/v1/dashboards/${id}/telegram`, { method: 'DELETE' });
        if (r.success) { toast('Konfigurasi dihapus', 'success'); closeModal('dashboardTelegramModal'); }
        else toast(r.error || 'Gagal menghapus', 'error');
    }

    // ------------------------------------------------------------
    // KELOLA DATA (admin)
    // ------------------------------------------------------------
    let previewOk = false;

    const ymd = (d) => {
        const p = (n) => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
    };
    const fmtBytes = (b) => (b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1048576).toFixed(2)} MB`);

    function dmSpec() {
        const tables = Array.from(document.querySelectorAll('#dmTables input:checked')).map((c) => c.value);
        return {
            tables,
            date_from: ($('dmFrom').value || '') || null,
            date_to: ($('dmTo').value || '') || null,
            device_id: ($('dmDevice').value || '') || null,
        };
    }

    function dmInvalidate() {
        previewOk = false;
        const del = $('dmDeleteBtn'); if (del) del.disabled = true;
        const pv = $('dmPreview'); if (pv) pv.style.display = 'none';
    }

    async function loadAudit() {
        const box = $('dmAudit');
        if (!box) return;
        const r = await API.call('/api/v1/system/audit-log?limit=15');
        if (!r.success) { box.textContent = r.error || 'Gagal memuat'; return; }
        const rows = r.data.entries || [];
        box.innerHTML = rows.length
            ? rows.map((e) => `<div style="padding:3px 0;border-bottom:1px solid var(--hairline);">
                <b>${esc(e.action)}</b> · ${esc(e.username || '-')} · ${esc(String(e.created_at || '').replace('T', ' '))}
                <div style="opacity:.8;word-break:break-all;">${esc(String(e.detail || '').slice(0, 180))}</div></div>`).join('')
            : 'Belum ada aktivitas.';
    }

    async function openDataMgmt() {
        dmInvalidate();
        openModal('dataMgmtModal');
        const sel = $('dmDevice');
        if (sel && sel.options.length <= 1) {
            try {
                const resp = await fetch('/api/v1/devices?per_page=500', { headers: { 'X-Dashboard-Id': 'all' }, credentials: 'same-origin' });
                const j = await resp.json();
                (j.devices || []).forEach((d) => {
                    const o = document.createElement('option');
                    o.value = d.device_id;
                    o.textContent = `${d.device_name} (${d.device_id})${d.dashboard_name ? ' — ' + d.dashboard_name : ''}`;
                    sel.appendChild(o);
                });
            } catch (e) { /* daftar perangkat opsional */ }
        }
        loadAudit();
    }

    async function dmPreview() {
        const spec = dmSpec();
        const r = await API.call('/api/v1/system/data/preview', { method: 'POST', body: JSON.stringify(spec) });
        const box = $('dmPreview');
        box.style.display = 'block';
        if (!r.success) {
            box.innerHTML = `<span style="color:var(--accent-crit);">${esc(r.error || 'Gagal')}</span>`;
            previewOk = false; $('dmDeleteBtn').disabled = true;
            return;
        }
        const d = r.data;
        const names = { sensor_data: 'Data sensor', alert_history: 'Riwayat alert', device_status_log: 'Log status',
            alerts_inactive: 'Alert nonaktif' };
        box.innerHTML = Object.entries(d.tables).map(([k, v]) =>
            `<div style="display:flex;justify-content:space-between;"><span>${esc(names[k] || k)}</span>
             <span>${v.rows.toLocaleString('id-ID')} baris · ~${fmtBytes(v.estimated_bytes)}</span></div>`).join('')
            + `<div style="margin-top:6px;padding-top:6px;border-top:1px solid var(--hairline);font-weight:600;">
               Total ${d.total_rows.toLocaleString('id-ID')} baris · perkiraan ${d.estimated_mb} MB</div>
               <div style="margin-top:4px;color:var(--text-3);font-size:11px;">${esc(d.note)}</div>`;
        previewOk = d.total_rows > 0;
        $('dmDeleteBtn').disabled = !previewOk;
    }

    async function dmDelete() {
        if (!previewOk) return;
        const spec = dmSpec();
        const range = `${spec.date_from || '…'} s/d ${spec.date_to || '…'}`;
        if (!confirm(`Hapus data permanen?\n\nTabel: ${spec.tables.join(', ')}\nRentang: ${range}\nPerangkat: ${spec.device_id || 'semua'}\n\nTindakan ini tidak bisa dibatalkan.`)) return;
        const btn = $('dmDeleteBtn');
        btn.disabled = true;
        toast('Menghapus data...', 'info');
        const r = await API.call('/api/v1/system/data/delete', {
            method: 'POST',
            body: JSON.stringify({ ...spec, confirm: true, backup_first: $('dmBackupFirst').checked }),
        });
        if (r.success) {
            const extra = r.data.backup ? ` Backup: ${r.data.backup}` : '';
            toast(`${r.data.total_deleted.toLocaleString('id-ID')} baris dihapus.${extra}`, 'success', 6000);
            dmInvalidate();
            loadAudit();
        } else {
            toast(r.error || 'Gagal menghapus', 'error', 6000);
            btn.disabled = false;
        }
    }

    async function dmVacuum() {
        if (!confirm('Kecilkan file database sekarang?\n\nDatabase terkunci sebentar selama proses dan butuh ruang disk kosong kira-kira sebesar database.')) return;
        const btn = $('dmVacuumBtn');
        btn.disabled = true;
        toast('Memproses VACUUM...', 'info');
        const r = await API.call('/api/v1/system/vacuum', { method: 'POST' });
        btn.disabled = false;
        if (r.success) {
            toast(`Selesai: ${r.data.before_mb} MB → ${r.data.after_mb} MB (hemat ${r.data.freed_mb} MB)`, 'success', 7000);
            loadAudit();
        } else {
            toast(r.error || 'VACUUM gagal', 'error', 7000);
        }
    }

    function dmPreset(kind) {
        const today = new Date();
        const y = new Date(today); y.setDate(y.getDate() - 1);
        if (kind === 'yesterday') { $('dmFrom').value = ymd(y); $('dmTo').value = ymd(y); }
        if (kind === 'today') { $('dmFrom').value = ymd(today); $('dmTo').value = ymd(today); }
        if (kind === 'older30') {
            const o = new Date(today); o.setDate(o.getDate() - 30);
            $('dmFrom').value = ''; $('dmTo').value = ymd(o);
        }
        dmInvalidate();
    }

    // ------------------------------------------------------------
    function bind() {
        const on = (id, fn) => { const el = $(id); if (el) el.addEventListener('click', fn); };
        on('dashboardShareBtn', openShare);
        on('shareAddBtn', addMember);
        const su = $('shareUsername');
        if (su) su.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); addMember(); } });

        on('dashboardTelegramBtn', openTelegram);
        on('tgSaveBtn', saveTelegram);
        on('tgTestBtn', testTelegram);
        on('tgDeleteBtn', deleteTelegram);

        on('dataMgmtBtn', openDataMgmt);
        on('dmPreviewBtn', dmPreview);
        on('dmDeleteBtn', dmDelete);
        on('dmVacuumBtn', dmVacuum);
        document.querySelectorAll('[data-dm-preset]').forEach((b) =>
            b.addEventListener('click', () => dmPreset(b.dataset.dmPreset)));
        ['dmFrom', 'dmTo', 'dmDevice'].forEach((id) => { const el = $(id); if (el) el.addEventListener('change', dmInvalidate); });
        document.querySelectorAll('#dmTables input').forEach((c) => c.addEventListener('change', dmInvalidate));
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
    else bind();
})();
