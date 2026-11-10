/* ==========================================================
   AAguard — Metric Cards helper
   ========================================================== */
(function () {
    'use strict';

    function safeColor(color) {
        const c = String(color == null ? '' : color).trim();
        if (/^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(c)) return c;
        if (/^var\(--[a-zA-Z0-9-_]+\)$/.test(c)) return c;
        return '#22c55e';
    }

    function buildSparkline(values, color) {
        color = safeColor(color);
        if (!Array.isArray(values) || values.length < 2) {
            return '<svg viewBox="0 0 84 40" preserveAspectRatio="none">' +
                '<line x1="4" y1="30" x2="80" y2="30" stroke="' + color + '" stroke-width="1.5" stroke-linecap="round" opacity="0.35"/></svg>';
        }

        const W = 84, H = 40, PAD = 4;
        const min = Math.min.apply(null, values);
        const max = Math.max.apply(null, values);
        const range = (max - min) || 1;
        const stepX = (W - PAD * 2) / (values.length - 1);

        const pts = values.map(function (v, i) {
            const x = PAD + i * stepX;
            const y = H - PAD - ((v - min) / range) * (H - PAD * 2);
            return [x, y];
        });

        let line = '';
        for (let i = 0; i < pts.length; i++) {
            line += (i === 0 ? 'M' : 'L') + pts[i][0].toFixed(2) + ',' + pts[i][1].toFixed(2);
            if (i < pts.length - 1) line += ' ';
        }
        const area = line + ' L' + pts[pts.length - 1][0].toFixed(2) + ',' + (H - PAD) +
                     ' L' + pts[0][0].toFixed(2) + ',' + (H - PAD) + ' Z';

        const last = pts[pts.length - 1];

        return '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' +
            '<path d="' + area + '" fill="' + color + '" opacity="0.14"/>' +
            '<path d="' + line + '" fill="none" stroke="' + color + '" stroke-width="1.6" ' +
                  'stroke-linecap="round" stroke-linejoin="round"/>' +
            '<circle cx="' + last[0].toFixed(2) + '" cy="' + last[1].toFixed(2) + '" r="2.4" fill="' + color + '"/>' +
            '<circle cx="' + last[0].toFixed(2) + '" cy="' + last[1].toFixed(2) + '" r="1" fill="var(--surface)"/>' +
            '</svg>';
    }

    function renderSparkline(key, values, color) {
        const el = document.querySelector('[data-spark="' + key + '"]');
        if (!el) return;
        el.innerHTML = buildSparkline(values, safeColor(color));
    }

    function setValue(key, value) {
        const el = document.querySelector('[data-value="' + key + '"]');
        if (!el) return;
        if (typeof value === 'number') el.textContent = value.toLocaleString('id-ID');
        else el.textContent = value == null ? '0' : String(value);
    }

    function setTrend(key, value, opts) {
        opts = opts || {};
        const el = document.querySelector('[data-trend="' + key + '"]');
        if (!el) return;

        const v = Number(value) || 0;
        const abs = Math.abs(v);

        let cls = 'nx-metric-trend';
        let icon = 'fa-minus';

        if (v > 0) {
            cls += opts.invertColors ? ' down' : '';
            icon = 'fa-arrow-up';
        } else if (v < 0) {
            cls += opts.invertColors ? '' : ' down';
            icon = 'fa-arrow-down';
        } else {
            cls += ' neutral';
        }

        el.className = cls;
        el.innerHTML = '<i class="fa-solid ' + icon + '"></i> ' + abs + '%';

        const labelEl = document.querySelector('[data-trend-label="' + key + '"]');
        if (labelEl && opts.label) labelEl.textContent = opts.label;
    }

    function bindMenus(root) {
        const scope = root || document;

        scope.addEventListener('click', function (e) {
            const trigger = e.target.closest('.nx-metric-menu-btn');
            if (trigger) {
                e.stopPropagation();
                const menu = trigger.closest('.nx-metric-menu');
                const wasOpen = menu.classList.contains('nx-open');
                document.querySelectorAll('.nx-metric-menu.nx-open').forEach(function (m) {
                    m.classList.remove('nx-open');
                });
                if (!wasOpen) menu.classList.add('nx-open');
                return;
            }
            if (!e.target.closest('.nx-metric-menu')) {
                document.querySelectorAll('.nx-metric-menu.nx-open').forEach(function (m) {
                    m.classList.remove('nx-open');
                });
            }
        });

        scope.addEventListener('click', function (e) {
            const item = e.target.closest('.nx-metric-menu__item');
            if (!item) return;
            e.stopPropagation();

            const menu = item.closest('.nx-metric-menu');
            if (menu) menu.classList.remove('nx-open');

            const action = item.dataset.action;
            const key = item.dataset.key;
            const value = item.dataset.value || '';

            if (action === 'copy') {
                const valEl = document.querySelector('[data-value="' + key + '"]');
                const text = valEl ? valEl.textContent.trim() : '';
                if (navigator.clipboard) {
                    navigator.clipboard.writeText(text).then(function () {
                        if (window.showToast) window.showToast('Nilai disalin', 'success');
                    }).catch(function () {
                        if (window.showToast) window.showToast('Gagal menyalin', 'error');
                    });
                }
                return;
            }

            document.dispatchEvent(new CustomEvent('nx-metric-action', {
                detail: { action: action, key: key, value: value, item: item }
            }));
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                document.querySelectorAll('.nx-metric-menu.nx-open').forEach(function (m) {
                    m.classList.remove('nx-open');
                });
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { bindMenus(document); });
    } else {
        bindMenus(document);
    }

    window.AAGuardMetrics = {
        renderSparkline: renderSparkline,
        setValue: setValue,
        setTrend: setTrend,
        buildSparkline: buildSparkline,
    };

    console.log('[AAGuardMetrics] Ready');
})();