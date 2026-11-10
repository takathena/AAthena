/* ============================================================
   AAguard AI CHAT — v4 (Composer + Shortcuts + Files)
   ============================================================ */
(function() {
    'use strict';

    const STORAGE_KEY = 'aaguard-chat-open';
    const AI_NAME = 'AAguard AI';

    const SHORTCUTS = [
        { icon: 'fa-microchip',           label: 'Status semua perangkat',            q: 'Bagaimana status semua perangkat?' },
        { icon: 'fa-bell',                label: 'Alert yang aktif saat ini',         q: 'Alert apa saja yang sedang aktif?' },
        { icon: 'fa-file-arrow-down',     label: 'Template bulk import',              q: 'Buatkan template bulk import perangkat' },
    ];

    const state = {
        history: [],
        isOpen: false,
        isSending: false,
        isOnline: false,
        lastDateKey: null,
        files: new Map(),         // id → { name, mime, content_b64 }
        fileCounter: 0,
    };

    const els = {};

    // ============================================================
    // MARKDOWN
    // ============================================================
    function renderMarkdown(text) {
        if (!text) return '';
        let s = String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');

        const codeBlocks = [];
        s = s.replace(/```(?:[a-z]*\n)?([\s\S]*?)```/g, (_, code) => {
            codeBlocks.push(code.replace(/\n$/, ''));
            return `\x00CB${codeBlocks.length - 1}\x00`;
        });

        const inlineCodes = [];
        s = s.replace(/`([^`\n]+)`/g, (_, code) => {
            inlineCodes.push(code);
            return `\x00IC${inlineCodes.length - 1}\x00`;
        });

        const lines = s.split('\n');
        const out = [];
        let inUl = false, inOl = false;
        for (const line of lines) {
            const ul = line.match(/^\s*[-*]\s+(.+)$/);
            const ol = line.match(/^\s*\d+\.\s+(.+)$/);
            if (ul) {
                if (inOl) { out.push('</ol>'); inOl = false; }
                if (!inUl) { out.push('<ul class="md-ul">'); inUl = true; }
                out.push(`<li>${ul[1]}</li>`);
            } else if (ol) {
                if (inUl) { out.push('</ul>'); inUl = false; }
                if (!inOl) { out.push('<ol class="md-ol">'); inOl = true; }
                out.push(`<li>${ol[1]}</li>`);
            } else {
                if (inUl) { out.push('</ul>'); inUl = false; }
                if (inOl) { out.push('</ol>'); inOl = false; }
                out.push(line);
            }
        }
        if (inUl) out.push('</ul>');
        if (inOl) out.push('</ol>');
        s = out.join('\n');

        s = s.replace(/^###\s+(.+)$/gm, '<h4 class="md-h">$1</h4>');
        s = s.replace(/^##\s+(.+)$/gm,  '<h3 class="md-h">$1</h3>');
        s = s.replace(/^#\s+(.+)$/gm,   '<h2 class="md-h">$1</h2>');

        s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
        s = s.replace(/__([^_\n]+)__/g,     '<strong>$1</strong>');
        s = s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
        s = s.replace(/(^|[^_])_([^_\n]+)_(?!_)/g,     '$1<em>$2</em>');

        s = s.replace(
            /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
            (m, label, url) => {
                let u;
                try { u = new URL(url.replace(/&amp;/g, '&')); } catch (e) { return label; }
                if (u.protocol !== 'http:' && u.protocol !== 'https:') return label;
                return '<a href="' + u.href.replace(/"/g, '&quot;') + '" target="_blank" rel="noopener noreferrer">' + label + '</a>';
            }
        );

        s = s.replace(/\x00CB(\d+)\x00/g, (_, i) =>
            `<pre class="md-pre"><code>${codeBlocks[+i]}</code></pre>`
        );
        s = s.replace(/\x00IC(\d+)\x00/g, (_, i) =>
            `<code class="md-code">${inlineCodes[+i]}</code>`
        );

        s = s.replace(/([^\n>])\n([^\n])/g, '$1<br>$2');
        return s;
    }

    // ============================================================
    // HELPERS
    // ============================================================
    function _now() { return new Date(); }

    function _timeShort(d) {
        try {
            return d.toLocaleTimeString('id-ID', {
                hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Jakarta',
            });
        } catch (e) { return ''; }
    }

    function _dateKey(d) {
        try { return d.toLocaleDateString('en-CA', { timeZone: 'Asia/Jakarta' }); }
        catch (e) { return ''; }
    }

    function _dateLabel(d) {
        const now = _now();
        const todayKey = _dateKey(now);
        const y = new Date(now.getTime() - 86400000);
        const key = _dateKey(d);
        if (key === todayKey) return 'Hari Ini';
        if (key === _dateKey(y)) return 'Kemarin';
        try {
            return d.toLocaleDateString('id-ID', {
                weekday: 'long', day: '2-digit', month: 'long', year: 'numeric',
                timeZone: 'Asia/Jakarta',
            });
        } catch (e) { return ''; }
    }

    function _maybeDayDivider(d) {
        const key = _dateKey(d);
        if (key === state.lastDateKey) return;
        state.lastDateKey = key;
        const divider = document.createElement('div');
        divider.className = 'chat-day-divider';
        divider.innerHTML = `<span>${_dateLabel(d)}</span>`;
        if (els.messages) els.messages.appendChild(divider);
    }

    function _esc(str) {
        return String(str ?? '')
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function _humanSize(bytes) {
        if (!bytes && bytes !== 0) return '';
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
    }

    function _b64ToBlob(b64, mime) {
        const bin = atob(b64);
        const len = bin.length;
        const bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) bytes[i] = bin.charCodeAt(i);
        return new Blob([bytes], { type: mime || 'application/octet-stream' });
    }

    function _downloadFile(fileId) {
        const f = state.files.get(fileId);
        if (!f) { console.warn('[Chat] File not found:', fileId); return; }
        try {
            const blob = _b64ToBlob(f.content_b64, f.mime);
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = f.name || 'download';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            setTimeout(() => URL.revokeObjectURL(url), 500);
            if (window.showToast) window.showToast('Mengunduh ' + f.name, 'success');
        } catch (e) {
            console.error('[Chat] Download failed', e);
            if (window.showToast) window.showToast('Gagal mengunduh file', 'error');
        }
    }

    window.__aaguardChatDownload = _downloadFile;

    // ============================================================
    // INIT
    // ============================================================
    function init() {
        els.panel = document.getElementById('chatPanel');
        els.messages = document.getElementById('chatMessages');
        els.input = document.getElementById('chatInput');
        els.send = document.getElementById('chatSend');
        els.status = document.getElementById('chatStatus');
        els.statusText = document.getElementById('chatStatusText');
        els.toggleBtn = document.getElementById('chatToggleBtn');
        els.onlineBadge = document.getElementById('chatOnlineBadge');
        els.shortcutsBtn = document.getElementById('chatShortcutsBtn');
        els.shortcutsMenu = document.getElementById('chatShortcutsMenu');
        els.shortcutsList = document.getElementById('chatShortcutsList');
        els.shortcutsClose = document.getElementById('chatShortcutsClose');
        els.attachBtn = document.getElementById('chatAttachBtn');
        els.micBtn = document.getElementById('chatMicBtn');
        els.userBtn = document.getElementById('chatComposerUser');

        if (!els.panel) return;

        // Nama user di composer
        try {
            const meta = document.querySelector('meta[name="username"]');
            const name = (meta && meta.content) || 'You';
            const btn = els.userBtn;
            if (btn) {
                const av = btn.querySelector('.chat-composer-user-avatar');
                const nm = btn.querySelector('.chat-composer-user-name');
                if (av) av.textContent = name.charAt(0).toUpperCase();
                if (nm) nm.textContent = name;
            }
        } catch (e) {}

        buildShortcutsMenu();

        const wasOpen = localStorage.getItem(STORAGE_KEY) === '1';
        if (wasOpen && window.innerWidth > 992) open(false);

        bindEvents();
        checkHealth();
        state.healthTimer = setInterval(checkHealth, 30000);

        console.log('[AAGuardChat] Initialized v4 (composer + shortcuts)');
    }

    function buildShortcutsMenu() {
        if (!els.shortcutsList) return;
        els.shortcutsList.innerHTML = SHORTCUTS.map((s, i) => `
            <button type="button" class="chat-shortcuts-item" data-shortcut-idx="${i}">
                <i class="fa-solid ${_esc(s.icon)}"></i>
                <span class="chat-shortcuts-item-text">${_esc(s.label)}</span>
            </button>
        `).join('');

        els.shortcutsList.querySelectorAll('.chat-shortcuts-item').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.shortcutIdx, 10);
                const sc = SHORTCUTS[idx];
                if (!sc) return;
                closeShortcutsMenu();
                if (els.input) {
                    els.input.value = sc.q;
                    autoGrow();
                    els.input.focus();
                }
                send();
            });
        });
    }

    function openShortcutsMenu() {
        if (!els.shortcutsMenu) return;
        els.shortcutsMenu.classList.add('open');
    }
    function closeShortcutsMenu() {
        if (!els.shortcutsMenu) return;
        els.shortcutsMenu.classList.remove('open');
    }
    function toggleShortcutsMenu() {
        if (!els.shortcutsMenu) return;
        els.shortcutsMenu.classList.toggle('open');
    }

    function bindEvents() {
        if (els.send) els.send.addEventListener('click', send);

        if (els.toggleBtn) {
            els.toggleBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                toggle();
            });
        }

        if (els.input) {
            els.input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    send();
                }
            });
            els.input.addEventListener('input', autoGrow);
        }

        document.querySelectorAll('.chat-suggestion').forEach(btn => {
            btn.addEventListener('click', () => {
                if (!els.input) return;
                els.input.value = btn.dataset.q || btn.textContent.trim();
                send();
            });
        });

        if (els.shortcutsBtn) {
            els.shortcutsBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                toggleShortcutsMenu();
            });
        }
        if (els.shortcutsClose) {
            els.shortcutsClose.addEventListener('click', (e) => {
                e.stopPropagation();
                closeShortcutsMenu();
            });
        }

        // Klik di luar shortcuts menu = tutup
        document.addEventListener('click', (e) => {
            if (!els.shortcutsMenu || !els.shortcutsMenu.classList.contains('open')) return;
            if (e.target.closest('.chat-shortcuts-wrap')) return;
            closeShortcutsMenu();
        });

        if (els.attachBtn) {
            els.attachBtn.addEventListener('click', () => {
                if (window.showToast) window.showToast('Fitur attach segera hadir', 'info');
            });
        }
        if (els.micBtn) {
            els.micBtn.addEventListener('click', () => {
                if (window.showToast) window.showToast('Fitur voice input segera hadir', 'info');
            });
        }

        const backdrop = document.getElementById('chatBackdrop');
        if (backdrop) backdrop.addEventListener('click', () => { if (state.isOpen) close(); });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                if (els.shortcutsMenu && els.shortcutsMenu.classList.contains('open')) {
                    closeShortcutsMenu();
                    return;
                }
                if (state.isOpen) toggle();
            }
        });
    }

    function autoGrow() {
        if (!els.input) return;
        els.input.style.height = 'auto';
        els.input.style.height = Math.min(els.input.scrollHeight, 160) + 'px';
    }

    function open(animate = true) {
        state.isOpen = true;
        if (!animate && els.panel) els.panel.style.transition = 'none';

        if (els.panel) els.panel.classList.add('open');
        if (els.toggleBtn) els.toggleBtn.classList.add('active');
        document.body.classList.add('chat-open');

        const backdrop = document.getElementById('chatBackdrop');
        if (backdrop) backdrop.classList.add('active');

        localStorage.setItem(STORAGE_KEY, '1');

        if (!animate && els.panel) {
            requestAnimationFrame(() => { els.panel.style.transition = ''; });
        }

        setTimeout(() => els.input && els.input.focus(), animate ? 300 : 0);
    }

    function close() {
        state.isOpen = false;
        closeShortcutsMenu();
        if (els.panel) els.panel.classList.remove('open');
        if (els.toggleBtn) els.toggleBtn.classList.remove('active');
        document.body.classList.remove('chat-open');

        const backdrop = document.getElementById('chatBackdrop');
        if (backdrop) backdrop.classList.remove('active');

        localStorage.setItem(STORAGE_KEY, '0');
    }

    function toggle() { state.isOpen ? close() : open(); }

    function scrollBottom() {
        if (els.messages) els.messages.scrollTop = els.messages.scrollHeight;
    }

    function hideWelcome() {
        const w = document.getElementById('chatWelcome');
        if (w) w.remove();
    }

    // ============================================================
    // MESSAGE RENDER
    // ============================================================
    function addMessage(role, text) {
        const now = _now();
        if (role !== 'thinking') _maybeDayDivider(now);

        const wrap = document.createElement('div');
        wrap.className = `chat-msg ${role}`;

        if (role === 'thinking') {
            wrap.innerHTML =
                '<div class="chat-msg-avatar"><i class="fa-solid fa-robot"></i></div>' +
                '<div class="chat-msg-body">' +
                    '<div class="chat-bubble">' +
                        '<span class="dot"></span><span class="dot"></span><span class="dot"></span>' +
                    '</div>' +
                '</div>';
            if (els.messages) els.messages.appendChild(wrap);
            scrollBottom();
            return wrap;
        }

        const isUser = role === 'user';
        const isAssistant = role === 'assistant';
        const isError = role === 'error';

        let avatarHtml = '';
        if (!isUser) {
            avatarHtml = '<div class="chat-msg-avatar"><i class="fa-solid fa-robot"></i></div>';
        }

        const nameLabel = isUser ? 'You' : (isError ? 'Sistem' : AI_NAME);
        const timeLabel = _timeShort(now);
        const receiptHtml = isUser
            ? '<span class="chat-msg-receipt" title="Terkirim"><i class="fa-solid fa-check"></i></span>'
            : '';

        const headHtml =
            '<div class="chat-msg-head">' +
                '<span class="chat-msg-name">' + _esc(nameLabel) + '</span>' +
                '<span class="chat-msg-time">' + _esc(timeLabel) + '</span>' +
                receiptHtml +
            '</div>';

        let bubbleInner;
        let bubbleClass = 'chat-bubble';
        if (isAssistant) {
            bubbleClass += ' chat-bubble-md';
            bubbleInner = renderMarkdown(text);
        } else {
            bubbleInner = _esc(text);
        }

        wrap.innerHTML =
            avatarHtml +
            '<div class="chat-msg-body">' +
                headHtml +
                '<div class="' + bubbleClass + '">' + bubbleInner + '</div>' +
            '</div>';

        if (els.messages) els.messages.appendChild(wrap);
        scrollBottom();
        return wrap;
    }

    function addFileAttachment(fileMeta) {
        // fileMeta = { name, mime, size, content_b64 }
        const id = 'f' + (++state.fileCounter);
        state.files.set(id, fileMeta);

        const ext = (fileMeta.name || '').split('.').pop().toLowerCase();
        const iconCls = ['csv', 'json', 'pdf'].includes(ext) ? ext : '';
        const iconText = ext.toUpperCase().slice(0, 4) || 'FILE';

        const wrap = document.createElement('div');
        wrap.className = 'chat-msg assistant';
        wrap.innerHTML =
            '<div class="chat-msg-avatar"><i class="fa-solid fa-robot"></i></div>' +
            '<div class="chat-msg-body">' +
                '<div class="chat-msg-head">' +
                    '<span class="chat-msg-name">' + _esc(AI_NAME) + '</span>' +
                    '<span class="chat-msg-time">' + _esc(_timeShort(_now())) + '</span>' +
                '</div>' +
                '<div class="chat-bubble chat-bubble-file">' +
                    '<div class="chat-attachment" data-file-id="' + id + '" role="button" tabindex="0">' +
                        '<div class="chat-attachment-icon ' + iconCls + '">' + _esc(iconText) + '</div>' +
                        '<div class="chat-attachment-body">' +
                            '<div class="chat-attachment-name">' + _esc(fileMeta.name) + '</div>' +
                            '<div class="chat-attachment-meta">' +
                                _esc(_humanSize(fileMeta.size) || '') +
                                ' · Klik untuk mengunduh' +
                            '</div>' +
                        '</div>' +
                        '<div class="chat-attachment-dl"><i class="fa-solid fa-download"></i></div>' +
                    '</div>' +
                '</div>' +
            '</div>';

        const card = wrap.querySelector('.chat-attachment');
        if (card) {
            card.addEventListener('click', () => _downloadFile(id));
            card.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    _downloadFile(id);
                }
            });
        }

        if (els.messages) els.messages.appendChild(wrap);
        scrollBottom();
    }

    function markUserMessagesRead() {
        document.querySelectorAll('.chat-msg.user .chat-msg-receipt').forEach(el => {
            el.classList.add('read');
            el.title = 'Dibaca';
            el.innerHTML =
                '<i class="fa-solid fa-check"></i><i class="fa-solid fa-check" style="margin-left:-6px;"></i>';
        });
    }

    function addToolsHint(tools) {
        if (!tools || !tools.length) return;
        const hint = document.createElement('div');
        hint.className = 'chat-tools-hint';
        hint.innerHTML = `<i class="fa-solid fa-wrench"></i> ${tools.map(t => _esc(t.tool)).join(' · ')}`;
        if (els.messages) els.messages.appendChild(hint);
        scrollBottom();
    }

    function getCsrf() {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.content : '';
    }

    function disableWidget() {
        if (state.healthTimer) { clearInterval(state.healthTimer); state.healthTimer = null; }
        if (state.isOpen) close();
        [els.panel, els.toggleBtn, document.getElementById('chatBackdrop'),
         document.querySelector('.chat-fab-mobile')].forEach(el => { if (el) el.style.display = 'none'; });
    }

    // ============================================================
    // HEALTH
    // ============================================================
    async function checkHealth() {
        try {
            const r = await fetch('/api/v1/chat/health', { credentials: 'same-origin' });
            const d = await r.json();
            if (d.configured === false) { disableWidget(); return; }

            if (d.success && d.upstream_ok) {
                state.isOnline = true;
                if (els.status) els.status.className = 'chat-status online';
                if (els.statusText) {
                    const m = (d.model || '').split('/').pop().replace(':free', '');
                    els.statusText.textContent = m.length > 22 ? m.slice(0, 20) + '…' : (m || 'Online');
                }
                if (els.onlineBadge) els.onlineBadge.style.display = 'inline-flex';
            } else {
                state.isOnline = false;
                if (els.status) els.status.className = 'chat-status offline';
                if (els.statusText) els.statusText.textContent = d.error || 'Offline';
                if (els.onlineBadge) els.onlineBadge.style.display = 'none';
            }
        } catch (e) {
            state.isOnline = false;
            if (els.status) els.status.className = 'chat-status offline';
            if (els.statusText) els.statusText.textContent = 'Tidak terhubung';
            if (els.onlineBadge) els.onlineBadge.style.display = 'none';
        }
    }

    // ============================================================
    // SEND
    // ============================================================
    async function send() {
        const text = els.input ? els.input.value.trim() : '';
        if (!text || state.isSending) return;

        state.isSending = true;
        els.input.value = '';
        els.input.style.height = 'auto';
        if (els.send) els.send.disabled = true;

        hideWelcome();
        addMessage('user', text);
        state.history.push({ role: 'user', content: text });

        const thinking = addMessage('thinking');

        try {
            const r = await fetch('/api/v1/chat', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrf(),
                },
                body: JSON.stringify({ messages: state.history }),
            });

            const d = await r.json();
            thinking.remove();

            if (!d.success) {
                addMessage('error', '⚠️ ' + (d.error || 'Gagal'));
                return;
            }

            markUserMessagesRead();

            // Render file attachments (jika ada)
            const files = Array.isArray(d.files) ? d.files : [];
            if (files.length > 0) {
                files.forEach(f => addFileAttachment(f));
                // Jangan tampilkan reply teks jika isinya kosong/pendek
                const replyText = (d.reply || '').trim();
                if (replyText && replyText.length > 3) {
                    addMessage('assistant', replyText);
                }
            } else {
                addMessage('assistant', d.reply);
            }

            if (d.tools_used && d.tools_used.length) addToolsHint(d.tools_used);

            state.history.push({ role: 'assistant', content: d.reply || '(file)' });

            if (state.history.length > 20) state.history = state.history.slice(-20);
        } catch (e) {
            thinking.remove();
            addMessage('error', '⚠️ Koneksi gagal: ' + e.message);
        } finally {
            state.isSending = false;
            if (els.send) els.send.disabled = false;
            if (els.input) els.input.focus();
        }
    }

    function clear() {
        if (!confirm('Bersihkan semua percakapan?')) return;
        state.history = [];
        state.lastDateKey = null;
        state.files.clear();
        state.fileCounter = 0;
        if (els.messages) els.messages.innerHTML = '';
        location.reload();
    }

    window.AAGuardChat = { toggle, open, close, send, clear };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();