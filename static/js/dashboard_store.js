/* ==========================================
   AAguard IoT - Dashboard Store v3 (Multi-Dashboard)
   + list, create, update, delete, set-default
   ========================================== */

(function() {
    'use strict';

    const state = {
        dashboards: [],
        currentDashboardId: null,
        currentDashboard: null,
        widgets: [],
        saveTimer: null,
        isSaving: false,
        pendingSave: false,
    };

    async function loadDashboards() {
        const res = await window.API.call('/api/v1/dashboards');
        if (res.success) {
            state.dashboards = res.data.dashboards || [];
        }
        return state.dashboards;
    }

    async function loadDashboard(id) {
        const res = await window.API.call(`/api/v1/dashboards/${id}`);
        if (res.success) {
            state.currentDashboardId = id;
            state.currentDashboard = res.data.dashboard;
            state.widgets = res.data.widgets || [];
        }
        return res;
    }

    async function loadDashboardBySlug(slug) {
        const res = await window.API.call(`/api/v1/dashboards/slug/${encodeURIComponent(slug)}`);
        if (res.success) {
            state.currentDashboardId = res.data.dashboard.id;
            state.currentDashboard = res.data.dashboard;
            state.widgets = res.data.widgets || [];
        }
        return res;
    }

    async function createDashboard(payload) {
        const res = await window.API.call('/api/v1/dashboards', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        if (res.success) {
            await loadDashboards();
        }
        return res;
    }

    async function updateDashboard(id, payload) {
        return window.API.call(`/api/v1/dashboards/${id}`, {
            method: 'PUT',
            body: JSON.stringify(payload),
        });
    }

    async function deleteDashboard(id) {
        return window.API.call(`/api/v1/dashboards/${id}`, { method: 'DELETE' });
    }

    async function setDefaultDashboard(id) {
        return window.API.call(`/api/v1/dashboards/${id}/set-default`, { method: 'POST' });
    }

    async function createWidget(dashboardId, payload) {
        const res = await window.API.call(`/api/v1/dashboards/${dashboardId}/widgets`, {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        if (res.success) {
            await loadDashboard(dashboardId);
        }
        return res;
    }

    async function updateWidget(widgetId, payload) {
        return window.API.call(`/api/v1/widgets/${widgetId}`, {
            method: 'PUT',
            body: JSON.stringify(payload),
        });
    }

    async function deleteWidget(widgetId) {
        return window.API.call(`/api/v1/widgets/${widgetId}`, { method: 'DELETE' });
    }

    function updateWidgetPositionLocal(widgetId, x, y, w, h) {
        const wgt = state.widgets.find(x => x.id === widgetId);
        if (wgt) {
            wgt.grid_x = x;
            wgt.grid_y = y;
            wgt.grid_w = w;
            wgt.grid_h = h;
        }
    }

    function scheduleLayoutSave() {
        clearTimeout(state.saveTimer);
        state.saveTimer = setTimeout(saveLayoutNow, 600);
    }

    async function saveLayoutNow() {
        if (!state.currentDashboardId || state.widgets.length === 0) return;

        if (state.isSaving) {
            state.pendingSave = true;
            return;
        }

        state.isSaving = true;
        state.pendingSave = false;

        const layout = state.widgets.map(w => ({
            id: w.id,
            x: w.grid_x || 0,
            y: w.grid_y || 0,
            w: w.grid_w || 2,
            h: w.grid_h || 2,
        }));

        const dashboardId = state.currentDashboardId;

        try {
            await window.API.call(
                `/api/v1/dashboards/${dashboardId}/layout`,
                { method: 'PUT', body: JSON.stringify({ layout }) }
            );
        } catch (e) {
            console.error('[DashboardStore] saveLayoutNow failed:', e);
        } finally {
            state.isSaving = false;

            if (state.pendingSave) {
                state.pendingSave = false;
                scheduleLayoutSave();
            }
        }
    }

    function mapChartTypeToWidgetType(chartType) {
        const map = {
            'line': 'line_chart', 'bar': 'bar_chart', 'area': 'area_chart',
            'doughnut': 'doughnut_chart', 'pie': 'pie_chart',
            'polarArea': 'polar_area', 'radar': 'radar_chart',
            'horizontalBar': 'horizontal_bar', 'stackedBar': 'stacked_bar',
            'stackedArea': 'stacked_area', 'scatter': 'scatter_chart',
            'halfDoughnut': 'half_doughnut', 'pieDataset': 'pie_dataset',
        };
        return map[chartType] || 'line_chart';
    }

    function mapWidgetTypeToChartType(widgetType) {
        const map = {
            'line_chart': 'line', 'bar_chart': 'bar', 'area_chart': 'area',
            'doughnut_chart': 'doughnut', 'pie_chart': 'pie',
            'polar_area': 'polarArea', 'radar_chart': 'radar',
            'horizontal_bar': 'horizontalBar', 'stacked_bar': 'stackedBar',
            'stacked_area': 'stackedArea', 'scatter_chart': 'scatter',
            'half_doughnut': 'halfDoughnut', 'pie_dataset': 'pieDataset',
        };
        return map[widgetType] || 'line';
    }

    window.DashboardStore = {
        state,
        loadDashboards,
        loadDashboard,
        loadDashboardBySlug,
        createDashboard,
        updateDashboard,
        deleteDashboard,
        setDefaultDashboard,
        createWidget,
        updateWidget,
        deleteWidget,
        updateWidgetPositionLocal,
        scheduleLayoutSave,
        saveLayoutNow,
        mapChartTypeToWidgetType,
        mapWidgetTypeToChartType,
    };

    console.log('[DashboardStore] Initialized v3 (multi-dashboard)');
})();