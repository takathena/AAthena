/* NEXUS IoT - Initial section from URL hash (externalized from dashboard.html inline <script>). Must load before dashboard.js. */
(function() {
    var hash = (window.location.hash || '').replace('#', '').trim();
    var valid = ['dashboard', 'map', 'graph', 'devices', 'alerts', 'settings'];
    var isSettingsHash = /^settings(\/[a-z-]+)?$/.test(hash);
    if (!valid.includes(hash) && !isSettingsHash) {
        try {
            var saved = sessionStorage.getItem('nexus-last-section');
            hash = (saved && valid.includes(saved)) ? saved : 'dashboard';
        } catch (e) { hash = 'dashboard'; }
    }
    if (!isSettingsHash && window.location.hash !== '#' + hash) {
        try { history.replaceState(null, '', '#' + hash); } catch (e) {}
    }
    window.__NEXUS_INITIAL_SECTION = isSettingsHash ? 'settings' : hash;
})();
