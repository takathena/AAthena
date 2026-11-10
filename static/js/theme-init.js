/* AAguard IoT - Theme pre-paint (FOUC prevention, externalized from base.html inline <script>). Must load synchronously in <head>. */
(function() {
    try {
        var savedTheme = localStorage.getItem('aaguard-theme') || 'dark';
        document.documentElement.setAttribute('data-theme', savedTheme);
    } catch (e) {
        document.documentElement.setAttribute('data-theme', 'dark');
    }
})();
