/* ==========================================
   AAguard IoT - Toast Notification (v2)
   Fitur:
     - Stacking: pesan & tipe sama → di-merge jadi 1 toast
     - Badge counter: ×2, ×3, dst
     - Timer reset setiap increment
     - Pulse animation saat increment
   ========================================== */

(function() {
    'use strict';

    let container = null;
    const DEFAULT_DURATION = 3000;

    // Map key -> { element, count, timeoutId, message, type }
    const activeToasts = new Map();

    function ensureContainer() {
        if (container && document.body.contains(container)) return container;

        container = document.createElement('div');
        container.id = 'toast-container';
        container.style.cssText = `
            position: fixed;
            bottom: 22px;
            right: 22px;
            z-index: 99999;
            display: flex;
            flex-direction: column;
            gap: 10px;
            pointer-events: none;
            max-width: 400px;
        `;
        document.body.appendChild(container);
        return container;
    }

    const ICONS = {
        success: 'fa-circle-check',
        error: 'fa-circle-exclamation',
        warning: 'fa-triangle-exclamation',
        info: 'fa-circle-info'
    };

    const COLORS = {
        success: '#30d158',
        error: '#ff453a',
        warning: '#ff9f0a',
        info: '#0a84ff'
    };

    function makeKey(message, type) {
        return `${type}::${String(message).trim()}`;
    }

    function updateBadge(toastEl, count) {
        let badge = toastEl.querySelector('.toast-badge');
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'toast-badge';
            toastEl.appendChild(badge);
        }
        if (count > 1) {
            badge.textContent = `×${count}`;
            badge.style.display = '';
        } else {
            badge.textContent = '';
            badge.style.display = 'none';
        }
    }

    function pulseToast(toastEl) {
        toastEl.classList.remove('toast-pulse');
        // Force reflow biar animasi bisa restart
        void toastEl.offsetWidth;
        toastEl.classList.add('toast-pulse');
    }

    function showToast(message, type = 'success', duration = DEFAULT_DURATION) {
        const c = ensureContainer();
        const key = makeKey(message, type);

        // ==========================================
        // Cek apakah sudah ada toast dengan key sama
        // ==========================================
        const existing = activeToasts.get(key);

        if (existing && document.body.contains(existing.element)) {
            // Increment counter
            existing.count++;

            // Update badge
            updateBadge(existing.element, existing.count);

            // Pulse animation
            pulseToast(existing.element);

            // Reset timer (durasi diperpanjang lagi)
            if (existing.timeoutId) {
                clearTimeout(existing.timeoutId);
            }
            if (duration > 0) {
                existing.timeoutId = setTimeout(
                    () => removeToast(existing.element),
                    duration
                );
            }

            return existing.element;
        }

        // ==========================================
        // Buat toast baru
        // ==========================================
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.style.cssText = `
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 13px 18px;
            background: var(--surface-solid, #1c1c1e);
            border: 1px solid var(--hairline, rgba(255,255,255,.1));
            border-left: 3px solid ${COLORS[type] || COLORS.info};
            border-radius: 12px;
            font-size: 13px;
            font-weight: 600;
            color: var(--text, #f5f5f7);
            box-shadow: 0 12px 30px rgba(0,0,0,.3);
            pointer-events: auto;
            animation: toastSlideIn .35s cubic-bezier(.16,1,.3,1);
            max-width: 400px;
            word-wrap: break-word;
            position: relative;
        `;

        toast.innerHTML = `
            <i class="fa-solid ${ICONS[type] || ICONS.info}" style="color:${COLORS[type] || COLORS.info};flex-shrink:0;"></i>
            <span style="flex:1;min-width:0;">${escapeHtml(message)}</span>
        `;

        toast.style.cursor = 'pointer';
        toast.onclick = () => removeToast(toast);

        c.appendChild(toast);

        // Set timer
        const timeoutId = duration > 0
            ? setTimeout(() => removeToast(toast), duration)
            : null;

        // Daftarkan ke map
        activeToasts.set(key, {
            element: toast,
            count: 1,
            timeoutId,
            message,
            type
        });

        return toast;
    }

    function removeToast(toast) {
        if (!toast || !toast.parentNode) return;

        // Hapus dari map
        for (const [key, entry] of activeToasts.entries()) {
            if (entry.element === toast) {
                if (entry.timeoutId) clearTimeout(entry.timeoutId);
                activeToasts.delete(key);
                break;
            }
        }

        toast.style.animation = 'toastSlideOut .3s cubic-bezier(.16,1,.3,1) forwards';
        setTimeout(() => {
            if (toast.parentNode) toast.parentNode.removeChild(toast);
        }, 300);
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }

    // ==========================================
    // KEYFRAMES (inject sekali)
    // ==========================================
    if (!document.getElementById('toast-keyframes')) {
        const style = document.createElement('style');
        style.id = 'toast-keyframes';
        style.textContent = `
            @keyframes toastSlideIn {
                from { transform: translateX(120%); opacity: 0; }
                to   { transform: translateX(0);    opacity: 1; }
            }
            @keyframes toastSlideOut {
                from { transform: translateX(0);    opacity: 1; }
                to   { transform: translateX(120%); opacity: 0; }
            }
            @keyframes toastBadgePop {
                0%   { transform: scale(0.5);  opacity: 0; }
                60%  { transform: scale(1.15); opacity: 1; }
                100% { transform: scale(1);    opacity: 1; }
            }
            @keyframes toastPulse {
                0%, 100% { transform: translateX(0); }
                50%      { transform: translateX(-4px); }
            }
        `;
        document.head.appendChild(style);
    }

    // ==========================================
    // EXPORTS
    // ==========================================
    window.showToast = showToast;
    window.toast = {
        success: (msg, dur) => showToast(msg, 'success', dur),
        error: (msg, dur) => showToast(msg, 'error', dur),
        warning: (msg, dur) => showToast(msg, 'warning', dur),
        info: (msg, dur) => showToast(msg, 'info', dur)
    };

    console.log('[Toast] Initialized v2 (stacking enabled)');
})();