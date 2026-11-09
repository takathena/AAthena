/* ==========================================
   NEXUS IoT - Alert Center (v9)
   + Alert Trend Chart (stacked bar per jam)
   + Alert History Viewer (modal audit trail)
   + Date Range Picker
   + Test Notifikasi Telegram
   ========================================== */

(function() {
    'use strict';

    const state = {
        alerts: [],
        filtered: [],
        status: 'all',
        severity: '',
        search: '',
        dateStart: '',
        dateEnd: '',
        selectedIds: new Set(),
        newlyAdded: new Set(),
        refreshInterval: null,
        isInitialized: false,
        trendHours: 24,
        trendChart: null,
        historyOpen: false,
        alertDRP: null,
    };

    const STORAGE_KEYS = {
        BACK_URL: 'nexus_back_url',
    };

    const _seenAlertIds = new Set();

    function $(id) { return document.getElementById(id); }

    function escapeHtml(str) {
        return String(str ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function parseDate(iso) {
        if (!iso) return null;
        const s = String(iso).trim();
        if (/[+-]\d{2}:\d{2}$/.test(s) || s.endsWith('Z')) {
            const d = new Date(s);
            return isNaN(d.getTime()) ? null : d;
        }
        if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(s)) {
            const d = new Date(s.replace(' ', 'T') + '+07:00');
            return isNaN(d.getTime()) ? null : d;
        }
        if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(s)) {
            const d = new Date(s + '+07:00');
            return isNaN(d.getTime()) ? null : d;
        }
        if (/^\d{4}-\d{2}-\d{2}$/.test(s)) {
            const d = new Date(s + 'T00:00:00+07:00');
            return isNaN(d.getTime()) ? null : d;
        }
        const d = new Date(s);
        return isNaN(d.getTime()) ? null : d;
    }

    function formatTime(iso) {
        const d = parseDate(iso);
        if (!d) return '-';
        try {
            const diff = (Date.now() - d.getTime()) / 1000;
            if (diff < 0) return 'baru saja';
            if (diff < 60) return 'baru saja';
            if (diff < 3600) return `${Math.floor(diff / 60)}m lalu`;
            if (diff < 86400) return `${Math.floor(diff / 3600)}j lalu`;
            if (diff < 604800) return `${Math.floor(diff / 86400)}h lalu`;
            return d.toLocaleString('id-ID', {
                day: '2-digit', month: 'short',
                hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Jakarta',
            });
        } catch (e) { return '-'; }
    }

    function formatFullTime(iso) {
        const d = parseDate(iso);
        if (!d) return '-';
        try {
            return d.toLocaleString('id-ID', {
                day: '2-digit', month: 'short', year: 'numeric',
                hour: '2-digit', minute: '2-digit', second: '2-digit',
                timeZone: 'Asia/Jakarta',
            }) + ' WIB';
        } catch (e) { return '-'; }
    }

    function severityIcon(sev) {
        return {
            danger: 'fa-fire', warning: 'fa-triangle-exclamation',
            info: 'fa-circle-info', healthy: 'fa-circle-check',
        }[sev] || 'fa-bell';
    }

    function severityLabel(sev) {
        return {
            danger: 'Bahaya', warning: 'Peringatan',
            info: 'Info', healthy: 'Normal',
        }[sev] || String(sev).toUpperCase();
    }

    function actionLabel(action) {
        return {
            'created': 'Dibuat',
            'acknowledged': 'Ditandai',
            'cleared': 'Selesai',
            'severity_changed': 'Severity Berubah',
        }[action] || action;
    }

    function alertTypeLabel(type) {
        const map = {
            temperature: 'Suhu', humidity: 'Kelembaban', gas_level: 'Gas',
            offline: 'Offline', smoke: 'Asap', motion: 'Gerakan',
            co2: 'CO2', moisture: 'K. Tanah', lux: 'Cahaya',
            voc: 'VOC', air_quality: 'Kualitas Udara',
        };
        return map[type] || String(type).replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    }

    const SENSOR_UNITS = {
        temperature: '°C', humidity: '%', gas_level: 'ppm',
        smoke: 'ppm', moisture: '%', lux: 'lux',
        co2: 'ppm', voc: 'ppb', air_quality: 'AQI',
        motion: '', rfid: '',
    };

    function formatValue(alertType, value) {
        if (value === null || value === undefined) return null;
        const unit = SENSOR_UNITS[alertType] ?? '';
        const num = parseFloat(value);
        if (isNaN(num)) return String(value);
        const trimmed = parseFloat(num.toFixed(2));
        return `${trimmed}${unit}`;
    }

    function getAckId(a) {
        if (a && a.alert_id !== null && a.alert_id !== undefined) return a.alert_id;
        return a ? a.id : null;
    }

    function getCsrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : '';
    }

    // ==========================================
    // iOS CUSTOM DROPDOWN
    // ==========================================
    function bindIOSDropdown(id, onChange) {
        const dd = document.getElementById(id);
        if (!dd) return;
        const trigger = dd.querySelector('.ios-dropdown-trigger');
        const label = dd.querySelector('.ios-dropdown-label');
        const items = dd.querySelectorAll('.ios-dropdown-item');
        if (!trigger || !label) return;

        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            document.querySelectorAll('.ios-dropdown.open').forEach(el => {
                if (el !== dd) el.classList.remove('open');
            });
            dd.classList.toggle('open');
        });

        items.forEach(item => {
            item.addEventListener('click', (e) => {
                e.stopPropagation();
                const value = item.dataset.value || '';
                const textEl = item.querySelector('.ios-dropdown-item-label');
                const text = textEl ? textEl.textContent.trim() : '';

                dd.dataset.value = value;
                label.textContent = text;
                items.forEach(i => i.classList.toggle('active', i === item));
                dd.classList.remove('open');

                if (typeof onChange === 'function') onChange(value, text);
            });
        });
    }

    // ==========================================
    // LOAD STATS
    // ==========================================
    async function loadStats() {
        try {
            const res = await fetch('/api/v1/alerts/stats');
            const data = await res.json();
            if (!data.success) return;
            const setText = (id, val) => { const el = $(id); if (el) el.textContent = val ?? 0; };
            setText('statTotalActive', data.summary.total);
            setText('statDanger', data.summary.danger);
            setText('statWarning', data.summary.warning);
            setText('statInfo', data.summary.info);
            setText('alertBadge', data.summary.total);
        } catch (e) { console.error(e); }
    }

    // ==========================================
    // ALERT TREND CHART
    // ==========================================
    async function loadTrend(hours) {
        const h = hours || state.trendHours;
        try {
            const res = await fetch(`/api/v1/alerts/trend?hours=${h}`);
            const data = await res.json();
            if (!data.success) return;

            const buckets = {};
            (data.trend || []).forEach(r => {
                if (!buckets[r.hour_bucket]) {
                    buckets[r.hour_bucket] = { danger: 0, warning: 0, info: 0 };
                }
                if (buckets[r.hour_bucket][r.severity] !== undefined) {
                    buckets[r.hour_bucket][r.severity] = r.count;
                }
            });

            const labels = Object.keys(buckets).sort();
            const empty = $('alertTrendEmpty');
            const canvas = $('alertTrendCanvas');

            if (labels.length === 0) {
                if (empty) empty.style.display = 'flex';
                if (canvas) canvas.style.display = 'none';
                if (state.trendChart) { state.trendChart.destroy(); state.trendChart = null; }
                return;
            }
            if (empty) empty.style.display = 'none';
            if (canvas) canvas.style.display = '';

            const dangerData = labels.map(l => buckets[l].danger || 0);
            const warningData = labels.map(l => buckets[l].warning || 0);
            const infoData = labels.map(l => buckets[l].info || 0);

            const isLongRange = h > 48;
            const displayLabels = labels.map(l => {
                const parts = String(l).split(' ');
                const date = parts[0] || '';
                const time = parts[1] || '';
                if (isLongRange) {
                    const dateShort = date.slice(5);
                    return `${dateShort} ${time.slice(0, 2)}h`;
                }
                return time.slice(0, 5);
            });

            if (state.trendChart) {
                state.trendChart.destroy();
                state.trendChart = null;
            }

            const isLight = document.documentElement.getAttribute('data-theme') === 'light';
            const gridColor = isLight ? 'rgba(0,0,0,0.05)' : 'rgba(255,255,255,0.05)';
            const labelColor = isLight ? '#737373' : '#a3a3a3';
            const legendColor = isLight ? '#525252' : '#a3a3a3';
            const tooltipBg = isLight ? '#0a0a0a' : '#fafafa';
            const tooltipTitle = isLight ? '#fafafa' : '#0a0a0a';
            const tooltipBody = isLight ? '#a3a3a3' : '#525252';
            const font = "'Geist', -apple-system, sans-serif";

            if (typeof Chart === 'undefined') {
                console.warn('[Trend] Chart.js not loaded');
                return;
            }

            state.trendChart = new Chart(canvas.getContext('2d'), {
                type: 'bar',
                data: {
                    labels: displayLabels,
                    datasets: [
                        {
                            label: 'Bahaya',
                            data: dangerData,
                            backgroundColor: 'rgba(239, 68, 68, 0.75)',
                            borderColor: '#ef4444',
                            borderWidth: 0,
                            borderRadius: 4,
                            stack: 'stack1',
                        },
                        {
                            label: 'Peringatan',
                            data: warningData,
                            backgroundColor: 'rgba(249, 115, 22, 0.75)',
                            borderColor: '#f97316',
                            borderWidth: 0,
                            borderRadius: 4,
                            stack: 'stack1',
                        },
                        {
                            label: 'Info',
                            data: infoData,
                            backgroundColor: 'rgba(139, 92, 246, 0.75)',
                            borderColor: '#8b5cf6',
                            borderWidth: 0,
                            borderRadius: 4,
                            stack: 'stack1',
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    animation: { duration: 250, easing: 'easeOutQuart' },
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: {
                                color: legendColor,
                                font: { size: 11, family: font, weight: '500' },
                                usePointStyle: true,
                                pointStyle: 'circle',
                                boxWidth: 8,
                                boxHeight: 8,
                                padding: 14,
                            },
                        },
                        tooltip: {
                            backgroundColor: tooltipBg,
                            titleColor: tooltipTitle,
                            bodyColor: tooltipBody,
                            borderColor: isLight ? 'rgba(0,0,0,0.08)' : 'rgba(255,255,255,0.1)',
                            borderWidth: 1,
                            padding: 10,
                            cornerRadius: 8,
                            displayColors: true,
                            boxPadding: 4,
                            titleFont: { size: 11, family: font, weight: '600' },
                            bodyFont: { size: 11, family: font, weight: '500' },
                            callbacks: {
                                title: (items) => {
                                    if (!items.length) return '';
                                    const idx = items[0].dataIndex;
                                    return labels[idx] || '';
                                },
                            },
                        },
                    },
                    scales: {
                        x: {
                            stacked: true,
                            grid: { display: false },
                            border: { display: false },
                            ticks: {
                                color: labelColor,
                                font: { size: 10, family: font, weight: '500' },
                                maxRotation: 0,
                                autoSkip: true,
                                maxTicksLimit: 12,
                                padding: 4,
                            },
                        },
                        y: {
                            stacked: true,
                            beginAtZero: true,
                            grid: { color: gridColor, drawBorder: false, drawTicks: false },
                            border: { display: false },
                            ticks: {
                                color: labelColor,
                                font: { size: 10, family: font, weight: '500' },
                                padding: 6,
                                precision: 0,
                            },
                        },
                    },
                },
            });
        } catch (e) {
            console.error('[Trend] Load failed:', e);
        }
    }

    function bindTrendRange() {
        const rangeEl = $('alertTrendRange');
        if (!rangeEl) return;
        rangeEl.querySelectorAll('.trend-range-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                rangeEl.querySelectorAll('.trend-range-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                state.trendHours = parseInt(btn.dataset.hours, 10) || 24;
                loadTrend();
            });
        });
    }

    // ==========================================
    // LOAD ALERTS
    // ==========================================
    async function loadAlerts() {
        const params = new URLSearchParams();
        if (state.status !== 'all') params.set('status', state.status);
        if (state.severity) params.set('severity', state.severity);
        params.set('limit', '1000');

        try {
            const res = await fetch(`/api/v1/alerts/all?${params}`);
            const data = await res.json();
            if (!data.success) { showError('Gagal memuat alert'); return; }

            const freshAlerts = Array.isArray(data.alerts) ? data.alerts : [];
            const freshIds = new Set(freshAlerts.map(a => a.id));

            const newOnes = [];
            const wasFirstLoad = _seenAlertIds.size === 0;

            freshAlerts.forEach(a => {
                if (!_seenAlertIds.has(a.id)) {
                    if (!wasFirstLoad) newOnes.push(a);
                    _seenAlertIds.add(a.id);
                }
            });

            for (const id of Array.from(_seenAlertIds)) {
                if (!freshIds.has(id)) _seenAlertIds.delete(id);
            }

            state.alerts = freshAlerts;
            state.newlyAdded = new Set(newOnes.map(a => a.id));

            const validAckIds = new Set(
                freshAlerts
                    .filter(a => a.is_still_active === 1 && a.severity !== 'healthy')
                    .map(a => getAckId(a))
                    .filter(x => x !== null)
            );
            state.selectedIds.forEach(id => {
                if (!validAckIds.has(id)) state.selectedIds.delete(id);
            });

            applyFilter();
            loadStats();

            if (newOnes.length > 0) {
                setTimeout(() => {
                    state.newlyAdded = new Set();
                    document.querySelectorAll('.alert-row.is-new').forEach(el =>
                        el.classList.remove('is-new'));
                }, 5000);
            }
        } catch (e) { showError('Koneksi gagal'); }
    }

    function inDateRange(createdAt) {
        if (!state.dateStart && !state.dateEnd) return true;
        const d = parseDate(createdAt);
        if (!d) return true;
        const t = d.getTime();
        if (state.dateStart) {
            const st = new Date(state.dateStart + 'T00:00:00+07:00').getTime();
            if (t < st) return false;
        }
        if (state.dateEnd) {
            const en = new Date(state.dateEnd + 'T23:59:59+07:00').getTime();
            if (t > en) return false;
        }
        return true;
    }

    function applyFilter() {
        let list = state.alerts;
        list = list.filter(a => inDateRange(a.created_at));

        if (state.search) {
            const term = state.search.toLowerCase();
            list = list.filter(a =>
                (a.device_name || '').toLowerCase().includes(term) ||
                (a.device_id || '').toLowerCase().includes(term) ||
                (a.message || '').toLowerCase().includes(term) ||
                (a.alert_type || '').toLowerCase().includes(term) ||
                (a.label || '').toLowerCase().includes(term)
            );
        }

        state.filtered = list;
        renderAlerts();
        updateBulkBar();
    }

    function renderAlerts() {
        const container = $('alertsList');
        if (!container) return;

        if (state.filtered.length === 0) {
            const filterInfo = state.search || state.status !== 'all' ||
                              state.severity || state.dateStart || state.dateEnd;
            container.innerHTML = `
                <div class="empty-state" style="padding:60px 20px;">
                    <i class="fa-solid fa-bell-slash" style="font-size:36px;color:var(--text-3);"></i>
                    <h3 style="margin-top:12px;">Tidak ada alert</h3>
                    <p style="font-size:12.5px;color:var(--text-3);">
                        ${filterInfo ? 'Coba ubah filter atau kata kunci pencarian' : 'Semua perangkat dalam kondisi normal'}
                    </p>
                </div>`;
            return;
        }

        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const yesterday = new Date(today.getTime() - 86400000);
        const weekAgo = new Date(today.getTime() - 7 * 86400000);
        let html = '';
        let currentGroup = '', groupOpened = false;

        state.filtered.forEach(a => {
            const created = parseDate(a.created_at);
            let group;
            if (!created) group = 'Tidak Diketahui';
            else if (created >= today) group = 'Hari Ini';
            else if (created >= yesterday) group = 'Kemarin';
            else if (created >= weekAgo) group = '7 Hari Terakhir';
            else group = 'Lebih Lama';

            if (group !== currentGroup) {
                if (groupOpened) html += '</div>';
                html += `<div class="alert-group"><div class="alert-group-label">${group}</div>`;
                currentGroup = group;
                groupOpened = true;
            }
            html += renderAlertRow(a);
        });
        if (groupOpened) html += '</div>';

        container.innerHTML = html;
        bindItemEvents();
    }

    function renderAlertRow(a) {
        const isActive = a.is_still_active === 1;
        const severity = a.severity || 'info';
        const icon = severityIcon(severity);
        const sevLabel = severityLabel(severity);
        const typeLabel = alertTypeLabel(a.alert_type);
        const isHealthy = severity === 'healthy';
        const itemClass = isHealthy ? 'resolved' : (isActive ? severity : 'resolved');
        const ackId = getAckId(a);
        const isChecked = ackId !== null && state.selectedIds.has(ackId);
        const isNew = state.newlyAdded && state.newlyAdded.has(a.id);

        const valueDisplay = formatValue(a.alert_type, a.value);
        const timeStr = formatTime(a.created_at);
        const statusText = isActive && !isHealthy ? 'Aktif' : 'Selesai';

        const checkboxHtml = (isActive && !isHealthy && ackId !== null) ? `
            <label class="alert-row-check" onclick="event.stopPropagation();">
                <input type="checkbox" class="alert-checkbox" data-alert-id="${ackId}" ${isChecked ? 'checked' : ''}>
            </label>
        ` : '<div style="width:20px;flex-shrink:0;"></div>';

        const ackBtnHtml = (isActive && !isHealthy && ackId !== null) ? `
            <button class="alert-act-btn ack" data-action="acknowledge" data-alert-id="${ackId}" title="Tandai Selesai">
                <i class="fa-solid fa-check"></i>
            </button>
        ` : '';

        return `
            <div class="alert-row ${itemClass}${isNew ? ' is-new' : ''}" data-alert-id="${a.id}">
                ${checkboxHtml}

                <span class="alert-icon"><i class="fa-solid ${icon}"></i></span>

                <div class="alert-body">
                    <div class="alert-line-1">
                        <strong>${escapeHtml(typeLabel)}</strong>
                        ${valueDisplay ? `<span class="alert-val">${escapeHtml(valueDisplay)}</span>` : ''}
                        <span class="alert-msg">${escapeHtml(a.message || '-')}</span>
                    </div>
                    <div class="alert-line-2">
                        <span class="alert-sev ${severity}">${sevLabel}</span>
                        <span class="alert-st ${isActive && !isHealthy ? 'active' : 'done'}">${statusText}</span>
                        <span class="alert-dev"><i class="fa-solid fa-microchip"></i> ${escapeHtml(a.device_name || a.device_id)}</span>
                        <span class="alert-time" title="${formatFullTime(a.created_at)}">${timeStr}</span>
                    </div>
                </div>

                <div class="alert-acts">
                    <button class="alert-act-btn view" data-action="view-device" data-device-id="${escapeHtml(a.device_id)}" title="Lihat Device">
                        <i class="fa-solid fa-eye"></i>
                    </button>
                    ${ackBtnHtml}
                </div>
            </div>`;
    }

    function bindItemEvents() {
        document.querySelectorAll('[data-action="view-device"]').forEach(btn => {
            btn.addEventListener('click', e => {
                e.stopPropagation();
                try { sessionStorage.setItem(STORAGE_KEYS.BACK_URL, '/#alerts'); } catch (err) {}
                window.location.href = `/device/${encodeURIComponent(btn.dataset.deviceId)}`;
            });
        });
        document.querySelectorAll('[data-action="acknowledge"]').forEach(btn => {
            btn.addEventListener('click', async e => {
                e.stopPropagation();
                const alertId = parseInt(btn.dataset.alertId, 10);
                if (!Number.isFinite(alertId)) return;
                const ok = await acknowledgeAlert(alertId);
                if (ok) {
                    window.showToast('Alert ditandai selesai', 'success');
                    state.selectedIds.delete(alertId);
                    loadAlerts();
                } else window.showToast('Gagal menandai alert', 'error');
            });
        });
        document.querySelectorAll('.alert-checkbox').forEach(cb => {
            cb.addEventListener('change', e => {
                const id = parseInt(e.target.dataset.alertId, 10);
                if (!Number.isFinite(id)) return;
                if (e.target.checked) state.selectedIds.add(id);
                else state.selectedIds.delete(id);
                updateBulkBar();
            });
        });
        document.querySelectorAll('.alert-row').forEach(item => {
            item.addEventListener('click', (e) => {
                if (e.target.closest('button') || e.target.closest('label')) return;
                const viewBtn = item.querySelector('[data-action="view-device"]');
                if (viewBtn) {
                    try { sessionStorage.setItem(STORAGE_KEYS.BACK_URL, '/#alerts'); } catch (err) {}
                    window.location.href = `/device/${encodeURIComponent(viewBtn.dataset.deviceId)}`;
                }
            });
        });
    }

    function updateBulkBar() {
        const bar = $('bulkActionBar');
        if (!bar) return;
        const activeAlerts = state.filtered.filter(a => a.is_still_active === 1 && a.severity !== 'healthy' && getAckId(a) !== null);
        if (activeAlerts.length === 0) {
            bar.style.display = 'none';
            return;
        }
        bar.style.display = 'flex';

        const countEl = $('selectedCount');
        const counterEl = $('selectedCounter');
        const n = state.selectedIds.size;
        if (countEl) countEl.textContent = n;
        if (counterEl) counterEl.classList.toggle('has-selection', n > 0);

        const bulkBtn = $('bulkAckBtn');
        if (bulkBtn) bulkBtn.disabled = n === 0;

        const selectAll = $('selectAllCheckbox');
        if (selectAll) {
            const allIds = activeAlerts.map(a => getAckId(a));
            selectAll.checked = allIds.length > 0 && allIds.every(id => state.selectedIds.has(id));
        }
    }

    async function acknowledgeAlert(alertId) {
        try {
            const res = await fetch(`/api/v1/alerts/${alertId}/acknowledge`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            });
            const data = await res.json();
            return data.success === true;
        } catch (e) { return false; }
    }

    async function bulkAcknowledge() {
        if (state.selectedIds.size === 0) {
            window.showToast('Pilih minimal satu alert', 'warning');
            return;
        }
        const ids = Array.from(state.selectedIds);
        try {
            const res = await fetch('/api/v1/alerts/bulk-acknowledge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                body: JSON.stringify({ ids }),
            });
            const data = await res.json();
            if (data.success) {
                window.showToast(`${data.acknowledged} alert ditandai selesai`, 'success');
                state.selectedIds.clear();
                loadAlerts();
            } else window.showToast(data.error || 'Gagal', 'error');
        } catch (e) { window.showToast('Koneksi gagal', 'error'); }
    }

    async function markAllVisible() {
        const visibleActive = state.filtered.filter(a =>
            a.is_still_active === 1 && a.severity !== 'healthy' && getAckId(a) !== null);

        if (visibleActive.length === 0) {
            window.showToast('Tidak ada alert aktif di filter ini', 'info');
            return;
        }

        if (!confirm(`Tandai ${visibleActive.length} alert sebagai selesai?`)) return;

        const ids = visibleActive.map(a => getAckId(a));
        try {
            const res = await fetch('/api/v1/alerts/bulk-acknowledge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                body: JSON.stringify({ ids }),
            });
            const data = await res.json();
            if (data.success) {
                window.showToast(`${data.acknowledged} alert ditandai selesai`, 'success');
                loadAlerts();
            } else {
                window.showToast(data.error || 'Gagal', 'error');
            }
        } catch (e) {
            window.showToast('Koneksi gagal', 'error');
        }
    }

    function showError(msg) {
        const container = $('alertsList');
        if (!container) return;
        container.innerHTML = `
            <div class="empty-state" style="padding:60px 20px;">
                <i class="fa-solid fa-triangle-exclamation" style="font-size:36px;color:var(--accent-crit);"></i>
                <h3 style="margin-top:12px;">${escapeHtml(msg)}</h3>
            </div>`;
    }

    function applyDateFilter() {
        const startEl = $('alertStartDate');
        const endEl = $('alertEndDate');
        state.dateStart = startEl ? startEl.value : '';
        state.dateEnd = endEl ? endEl.value : '';
        applyFilter();
    }

    function clearDateFilter() {
        if (state.alertDRP) state.alertDRP.setValue(null, null);
        state.dateStart = '';
        state.dateEnd = '';
        applyFilter();
    }

    // ==========================================
    // TEST NOTIFIKASI
    // ==========================================
    function bindTestNotification() {
        const btn = $('testNotifBtn');
        if (!btn || btn.__bound) return;
        btn.__bound = true;

        btn.addEventListener('click', async () => {
            const originalHtml = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Mengirim...';

            try {
                const res = await fetch('/api/v1/notifications/test', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken(),
                    },
                });
                const data = await res.json();

                if (data.success) {
                    window.showToast('Notifikasi tes terkirim ke Telegram', 'success');
                } else {
                    let errMsg = data.error || 'Gagal mengirim';
                    if (data.results) {
                        const failures = Object.entries(data.results)
                            .filter(([k, v]) => !k.startsWith('_') && v && v.success === false)
                            .map(([k, v]) => `${k}: ${v.error || 'unknown'}`);
                        if (failures.length) errMsg = failures.join(' | ');
                    }
                    window.showToast(errMsg, 'error', 6000);
                }
            } catch (e) {
                window.showToast('Koneksi gagal: ' + e.message, 'error');
            } finally {
                btn.disabled = false;
                btn.innerHTML = originalHtml;
            }
        });
    }

    // ==========================================
    // ALERT HISTORY MODAL
    // ==========================================
    async function populateHistoryDeviceFilter() {
        const sel = $('historyDeviceFilter');
        if (!sel || sel.dataset.populated === '1') return;
        try {
            const res = await fetch('/api/v1/devices');
            const data = await res.json();
            if (!data.success) return;
            const devices = data.devices || [];
            devices.forEach(d => {
                const opt = document.createElement('option');
                opt.value = d.device_id;
                opt.textContent = `${d.device_name} (${d.device_id})`;
                sel.appendChild(opt);
            });
            sel.dataset.populated = '1';
        } catch (e) { console.warn('[History] device list failed', e); }
    }

    async function loadAlertHistory() {
        const body = $('alertHistoryBody');
        const countEl = $('alertHistoryCount');
        if (!body) return;

        body.innerHTML = `<div class="loading" style="padding:40px;text-align:center;">
            <div class="spinner"></div>
            <div style="margin-top:10px;font-size:12.5px;color:var(--text-3);">Memuat riwayat...</div>
        </div>`;

        const deviceId = ($('historyDeviceFilter') || {}).value || '';
        const severity = ($('historySeverityFilter') || {}).value || '';
        const params = new URLSearchParams();
        if (deviceId) params.set('device_id', deviceId);
        params.set('limit', '500');

        try {
            const res = await fetch(`/api/v1/alerts/history?${params}`);
            const data = await res.json();
            if (!data.success) {
                body.innerHTML = `<div class="empty-state" style="padding:32px;">
                    <i class="fa-solid fa-triangle-exclamation" style="color:var(--accent-crit);"></i>
                    <h3>Gagal memuat</h3>
                    <p>${escapeHtml(data.error || 'Koneksi gagal')}</p>
                </div>`;
                return;
            }

            let history = Array.isArray(data.history) ? data.history : [];
            if (severity) {
                history = history.filter(h => h.severity === severity);
            }

            if (countEl) {
                countEl.textContent = history.length > 0
                    ? `${history.length} entri`
                    : '';
            }

            if (history.length === 0) {
                body.innerHTML = `<div class="empty-state" style="padding:40px;">
                    <i class="fa-solid fa-inbox" style="opacity:0.4;"></i>
                    <h3>Belum ada riwayat</h3>
                    <p>Belum ada perubahan alert untuk filter ini</p>
                </div>`;
                return;
            }

            const rowsHtml = history.map(h => {
                const sev = h.severity || 'info';
                const action = h.action || '';
                const actionCls = action === 'cleared' ? 'ok'
                                 : action === 'acknowledged' ? 'ack'
                                 : action === 'severity_changed' ? 'warn'
                                 : '';
                const valueDisplay = h.value !== null && h.value !== undefined
                    ? `<span class="history-value">${escapeHtml(formatValue(h.alert_type, h.value) || h.value)}</span>`
                    : '';
                const deviceName = h.device_name || h.device_id || '—';

                return `<div class="history-row">
                    <div class="history-row-top">
                        <span class="alert-sev ${sev}">${escapeHtml(severityLabel(sev))}</span>
                        <span class="history-action history-action-${actionCls}">${escapeHtml(actionLabel(action))}</span>
                        <span class="history-device" title="${escapeHtml(h.device_id)}">
                            <i class="fa-solid fa-microchip"></i>
                            ${escapeHtml(deviceName)}
                        </span>
                        ${valueDisplay}
                        <span class="history-time" title="${escapeHtml(formatFullTime(h.created_at))}">${escapeHtml(formatTime(h.created_at))}</span>
                    </div>
                    <div class="history-row-bottom">
                        <span class="history-type">${escapeHtml(alertTypeLabel(h.alert_type))}</span>
                        <span class="history-sep">·</span>
                        <span class="history-msg">${escapeHtml(h.message || '-')}</span>
                    </div>
                </div>`;
            }).join('');

            body.innerHTML = `<div class="history-list">${rowsHtml}</div>`;

        } catch (e) {
            body.innerHTML = `<div class="empty-state" style="padding:32px;">
                <i class="fa-solid fa-triangle-exclamation" style="color:var(--accent-crit);"></i>
                <h3>Koneksi gagal</h3>
                <p>${escapeHtml(e.message || '')}</p>
            </div>`;
        }
    }

    function openHistoryModal() {
        const modal = $('alertHistoryModal');
        if (!modal) return;
        modal.classList.add('active');
        document.body.classList.add('modal-open');
        state.historyOpen = true;
        populateHistoryDeviceFilter();
        loadAlertHistory();
    }

    function closeHistoryModal() {
        const modal = $('alertHistoryModal');
        if (!modal) return;
        modal.classList.remove('active');
        state.historyOpen = false;
        const anyModal = document.querySelector('.modal.active');
        if (!anyModal) document.body.classList.remove('modal-open');
    }

    function bindHistoryModal() {
        const openBtn = $('historyAlertsBtn');
        if (openBtn && !openBtn.__bound) {
            openBtn.__bound = true;
            openBtn.addEventListener('click', openHistoryModal);
        }

        const modal = $('alertHistoryModal');
        if (modal && !modal.__bound) {
            modal.__bound = true;
            modal.querySelectorAll('.modal-close').forEach(btn => {
                btn.addEventListener('click', closeHistoryModal);
            });
            modal.addEventListener('click', e => {
                if (e.target === modal) closeHistoryModal();
            });
        }

        const devFilter = $('historyDeviceFilter');
        if (devFilter && !devFilter.__bound) {
            devFilter.__bound = true;
            devFilter.addEventListener('change', loadAlertHistory);
        }

        const sevFilter = $('historySeverityFilter');
        if (sevFilter && !sevFilter.__bound) {
            sevFilter.__bound = true;
            sevFilter.addEventListener('change', loadAlertHistory);
        }

        const refreshBtn = $('historyRefreshBtn');
        if (refreshBtn && !refreshBtn.__bound) {
            refreshBtn.__bound = true;
            refreshBtn.addEventListener('click', loadAlertHistory);
        }
    }

    // ==========================================
    // BIND EVENTS
    // ==========================================
    function bindEvents() {
        bindIOSDropdown('alertStatusDropdown', (value) => {
            state.status = value || 'all';
            loadAlerts();
        });

        bindIOSDropdown('alertSeverityDropdown', (value) => {
            state.severity = value || '';
            loadAlerts();
        });

        // Date range picker untuk alert (css/js lazy saat section dibuka)
        const drpEl = document.getElementById('alertDateRange');
        const makeAlertDRP = () => {
            if (!drpEl || !window.NexusDateRangePicker) return;
            state.alertDRP = new window.NexusDateRangePicker.DateRangePicker(drpEl, {
                placeholder: 'Filter tanggal...',
                onChange: (start, end) => {
                    state.dateStart = start || '';
                    state.dateEnd = end || '';
                    applyFilter();
                }
            });
        };
        if (window.NexusDateRangePicker) makeAlertDRP();
        else if (window.NexusLazy && typeof window.NexusLazy.loadDateRange === 'function') {
            window.NexusLazy.loadDateRange().then(makeAlertDRP).catch(() => {});
        }

        const refreshBtn = $('refreshAlertsBtn');
        if (refreshBtn) refreshBtn.addEventListener('click', loadAlerts);

        bindTestNotification();
        bindHistoryModal();
        bindTrendRange();

        const markAllBtn = $('markAllReadBtn');
        if (markAllBtn) markAllBtn.addEventListener('click', markAllVisible);

        const selectAll = $('selectAllCheckbox');
        if (selectAll) {
            selectAll.addEventListener('change', e => {
                const activeAlerts = state.filtered.filter(a => a.is_still_active === 1 && a.severity !== 'healthy' && getAckId(a) !== null);
                if (e.target.checked) activeAlerts.forEach(a => state.selectedIds.add(getAckId(a)));
                else state.selectedIds.clear();
                renderAlerts();
                updateBulkBar();
            });
        }

        const bulkAckBtn = $('bulkAckBtn');
        if (bulkAckBtn) bulkAckBtn.addEventListener('click', bulkAcknowledge);

        document.addEventListener('click', (e) => {
            if (!e.target.closest('.ios-dropdown')) {
                document.querySelectorAll('.ios-dropdown.open').forEach(el => {
                    el.classList.remove('open');
                });
            }
        });

        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') {
                document.querySelectorAll('.ios-dropdown.open').forEach(el => {
                    el.classList.remove('open');
                });
                if (state.historyOpen) closeHistoryModal();
            }
        });

        document.addEventListener('keydown', e => {
            if (e.key === 'r' && (e.ctrlKey || e.metaKey)) {
                const alertsSection = $('alertsSection');
                if (alertsSection && alertsSection.style.display !== 'none') {
                    e.preventDefault();
                    loadAlerts();
                }
            }
        });

        window.addEventListener('themechange', () => {
            if (state.trendChart) {
                loadTrend();
            }
        });
    }

    function init() {
        if (state.isInitialized) return;
        state.isInitialized = true;
        bindEvents();
        loadAlerts();
        loadTrend();

        state.refreshInterval = setInterval(() => {
            const alertsSection = $('alertsSection');
            if (alertsSection && alertsSection.style.display !== 'none') {
                loadAlerts();
                if (!state.historyOpen) loadTrend();
            }
        }, 20000);
    }

    window.addEventListener('beforeunload', () => {
        if (state.refreshInterval) {
            clearInterval(state.refreshInterval);
            state.refreshInterval = null;
        }
        if (state.trendChart) {
            try { state.trendChart.destroy(); } catch (e) {}
            state.trendChart = null;
        }
    });

    window.NexusAlerts = {
        init,
        load: loadAlerts,
        loadStats,
        loadTrend,
        setSearch(term) {
            state.search = (term || '').trim();
            applyFilter();
        },
        getSearch() { return state.search; },
        openHistory: openHistoryModal,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    console.log('[Alerts] Initialized v9 (trend + history + date range)');
})();