/* ==========================================
   AAguard IoT — Global Error Boundary v2
   Filter: cross-origin "Script error." noise
   ========================================== */

(function() {
    'use strict';

    const MAX_TOASTS = 3;
    let errorCount = 0;
    let lastErrorTime = 0;

    // Pattern noise yang harus di-skip (tidak informatif)
    const NOISE_PATTERNS = [
        /^Script error\.?$/i,               // cross-origin generic
        /ResizeObserver loop/i,             // Chart/Plotly resize noise
        /Non-Error promise rejection/i,     // Promise reject non-error
        /Loading chunk/i,                   // code-split fail
        /^null$/i,                          // null message
    ];

    function isNoise(msg) {
        if (!msg) return true;
        const s = String(msg).trim();
        if (!s) return true;
        return NOISE_PATTERNS.some(p => p.test(s));
    }

    function showErrorToast(message) {
        const now = Date.now();
        if (now - lastErrorTime < 5000) {
            errorCount++;
            if (errorCount > MAX_TOASTS) return;
        } else {
            errorCount = 1;
            lastErrorTime = now;
        }

        if (window.showToast) {
            window.showToast(message, 'error', 5000);
        } else {
            console.error('[ErrorHandler]', message);
        }
    }

    window.addEventListener('error', (event) => {
        // Abaikan error dari resource load (img, script, link)
        if (event.target && event.target !== window) {
            const tag = event.target.tagName;
            if (tag === 'SCRIPT' || tag === 'LINK' || tag === 'IMG') {
                console.warn('[ResourceError]', tag, event.target.src || event.target.href);
                return;
            }
            return;
        }

        const msg = event.message || 'Unknown error';

        // Filter noise (cross-origin Script error., dll)
        if (isNoise(msg)) {
            console.warn('[GlobalError] Filtered noise:', msg,
                         '| src:', event.filename || 'unknown',
                         '| line:', event.lineno || '?');
            return;
        }

        console.error('[GlobalError]', msg, event.error);
        showErrorToast('Terjadi kesalahan: ' + msg);
    });

    window.addEventListener('unhandledrejection', (event) => {
        const reason = event.reason;
        const msg = reason?.message || String(reason) || 'Unknown promise rejection';

        // Filter noise
        if (isNoise(msg)) {
            console.warn('[UnhandledRejection] Filtered noise:', msg);
            return;
        }

        // Abaikan network error yang tidak penting
        if (/NetworkError|Failed to fetch|HTTP|AbortError|timeout/i.test(msg)) {
            console.warn('[UnhandledRejection] Network:', msg);
            return;
        }

        console.error('[UnhandledRejection]', msg, reason);
        showErrorToast('Error: ' + msg);
    });

    // Wrap fetch — log hanya error 5xx (server error), bukan 4xx
    const originalFetch = window.fetch;
    window.fetch = async function(...args) {
        try {
            const response = await originalFetch.apply(this, args);
            if (response.status >= 500 && response.status < 600) {
                console.warn('[Fetch] Server error:', response.status, args[0]);
            }
            return response;
        } catch (err) {
            // Network error — jangan toast, biar caller yang handle
            console.warn('[Fetch] Network error:', args[0], err.message);
            throw err;
        }
    };

    console.log('[ErrorHandler] Initialized v2 (noise filtered)');
})();