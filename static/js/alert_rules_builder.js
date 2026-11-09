/* ==========================================
   NEXUS IoT - Alert Rules Builder
   ========================================== */

(function() {
    'use strict';

    window.SENSOR_PRESETS = {
        temperature: {
            label: 'Suhu', unit: '°C',
            defaults: {
                healthy: { min: 20, max: 26 },
                warning: { min: 15, max: 30 },
                danger:  { min: 10, max: 35 },
            }
        },
        humidity: {
            label: 'Kelembaban', unit: '%',
            defaults: {
                healthy: { min: 40, max: 70 },
                warning: { min: 30, max: 80 },
                danger:  { min: 20, max: 90 },
            }
        },
        gas_level: {
            label: 'Level Gas', unit: 'ppm',
            defaults: {
                healthy: { min: 0, max: 70 },
                warning: { min: 0, max: 85 },
                danger:  { min: 0, max: 100 },
            }
        },
        co2: {
            label: 'CO2', unit: 'ppm',
            defaults: {
                healthy: { min: 300, max: 1000 },
                warning: { min: 300, max: 1500 },
                danger:  { min: 300, max: 5000 },
            }
        },
        moisture: {
            label: 'Kelembaban Tanah', unit: '%',
            defaults: {
                healthy: { min: 40, max: 70 },
                warning: { min: 30, max: 80 },
                danger:  { min: 20, max: 90 },
            }
        },
        lux: {
            label: 'Cahaya', unit: 'lux',
            defaults: {
                healthy: { min: 100, max: 800 },
                warning: { min: 50, max: 1000 },
                danger:  { min: 0, max: 2000 },
            }
        },
    };

    const SEVERITY_LABELS = { healthy: 'Normal', warning: 'Peringatan', danger: 'Bahaya' };

    function renderSeverityRow(severity, values) {
        return `
            <div class="severity-row ${severity}">
                <div class="severity-row-label"><span class="dot"></span>${SEVERITY_LABELS[severity]}</div>
                <input type="number" step="0.1" class="severity-input" data-severity="${severity}" data-field="min" placeholder="Min" value="${values.min}">
                <input type="number" step="0.1" class="severity-input" data-severity="${severity}" data-field="max" placeholder="Max" value="${values.max}">
            </div>
        `;
    }

    function renderRuleItem(sensorKey, rule) {
        const options = Object.entries(window.SENSOR_PRESETS).map(([key, val]) =>
            `<option value="${key}" ${key === sensorKey ? 'selected' : ''}>${val.label}</option>`
        ).join('');

        const item = document.createElement('div');
        item.className = 'alert-rule-item';

        let rows = '';
        if (rule.healthy) rows += renderSeverityRow('healthy', rule.healthy);
        if (rule.warning) rows += renderSeverityRow('warning', rule.warning);
        if (rule.danger) rows += renderSeverityRow('danger', rule.danger);

        item.innerHTML = `
            <div class="alert-rule-header">
                <select class="alert-rule-sensor-select">${options}</select>
                <button type="button" class="alert-rule-remove" title="Hapus"><i class="fa-solid fa-trash"></i></button>
            </div>
            <div class="alert-rule-severities">${rows}</div>
        `;

        item.querySelector('.alert-rule-sensor-select').addEventListener('change', function() { onSensorChange(this); });
        item.querySelector('.alert-rule-remove').addEventListener('click', function() { onRemove(this); });
        return item;
    }

    function onSensorChange(selectEl) {
        const item = selectEl.closest('.alert-rule-item');
        const preset = window.SENSOR_PRESETS[selectEl.value];
        item.querySelectorAll('.severity-row').forEach(row => {
            const severity = Array.from(row.classList).find(c => ['healthy','warning','danger'].includes(c));
            if (!severity || !preset.defaults[severity]) return;
            row.querySelector('[data-field="min"]').value = preset.defaults[severity].min;
            row.querySelector('[data-field="max"]').value = preset.defaults[severity].max;
        });
    }

    function onRemove(btn) {
        const item = btn.closest('.alert-rule-item');
        const container = item.parentElement;
        item.remove();
        if (container.querySelectorAll('.alert-rule-item').length === 0) {
            container.innerHTML = '<div class="alert-rule-empty">Belum ada custom rule. Pakai global default.</div>';
        }
    }

    window.addAlertRule = function(mode = 'add') {
        const container = document.getElementById(mode === 'add' ? 'addAlertRulesBuilder' : 'editAlertRulesBuilder');
        if (!container) return;
        const empty = container.querySelector('.alert-rule-empty');
        if (empty) empty.remove();
        const usedSensors = Array.from(container.querySelectorAll('.alert-rule-sensor-select')).map(sel => sel.value);
        const availableSensor = Object.keys(window.SENSOR_PRESETS).find(s => !usedSensors.includes(s)) || Object.keys(window.SENSOR_PRESETS)[0];
        const preset = window.SENSOR_PRESETS[availableSensor];
        const rule = {
            healthy: preset.defaults.healthy,
            warning: preset.defaults.warning,
            danger: preset.defaults.danger,
        };
        const item = renderRuleItem(availableSensor, rule);
        container.appendChild(item);
    };

    window.collectAlertRules = function(mode = 'add') {
        const container = document.getElementById(mode === 'add' ? 'addAlertRulesBuilder' : 'editAlertRulesBuilder');
        if (!container) return null;
        const rules = {};
        container.querySelectorAll('.alert-rule-item').forEach(item => {
            const sensorKey = item.querySelector('.alert-rule-sensor-select').value;
            const rule = {};
            item.querySelectorAll('.severity-row').forEach(row => {
                const severity = Array.from(row.classList).find(c => ['healthy','warning','danger'].includes(c));
                if (!severity) return;
                const minEl = row.querySelector('[data-field="min"]');
                const maxEl = row.querySelector('[data-field="max"]');
                const min = parseFloat(minEl.value);
                const max = parseFloat(maxEl.value);
                if (!isNaN(min) && !isNaN(max)) rule[severity] = { min, max };
            });
            if (Object.keys(rule).length > 0) rules[sensorKey] = rule;
        });
        return Object.keys(rules).length > 0 ? rules : null;
    };

    window.populateAlertRules = function(mode, rules) {
        const container = document.getElementById(mode === 'add' ? 'addAlertRulesBuilder' : 'editAlertRulesBuilder');
        if (!container) return;
        container.innerHTML = '';
        if (!rules || Object.keys(rules).length === 0) {
            container.innerHTML = '<div class="alert-rule-empty">Belum ada custom rule. Pakai global default.</div>';
            return;
        }
        Object.entries(rules).forEach(([sensorKey, rule]) => {
            const item = renderRuleItem(sensorKey, rule);
            container.appendChild(item);
        });
    };

})();