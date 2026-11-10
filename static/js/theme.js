/* ==========================================
   AAguard IoT - Theme Manager
   ========================================== */

(function() {
    'use strict';

    const THEME_KEY = 'aaguard-theme';
    const THEMES = { DARK: 'dark', LIGHT: 'light' };

    const ThemeManager = {
        get() {
            return localStorage.getItem(THEME_KEY) || THEMES.DARK;
        },

        set(theme) {
            if (!Object.values(THEMES).includes(theme)) {
                console.warn('[Theme] Invalid theme:', theme);
                return;
            }

            document.documentElement.setAttribute('data-theme', theme);
            localStorage.setItem(THEME_KEY, theme);

            const meta = document.querySelector('meta[name="theme-color"]');
            if (meta) {
                meta.content = theme === THEMES.LIGHT ? '#f5f5f7' : '#000000';
            }

            window.dispatchEvent(new CustomEvent('themechange', { detail: { theme } }));
        },

        toggle() {
            const newTheme = this.get() === THEMES.LIGHT ? THEMES.DARK : THEMES.LIGHT;
            this.set(newTheme);
            return newTheme;
        },

        init() {
            const theme = this.get();
            document.documentElement.setAttribute('data-theme', theme);
            return theme;
        },

        isDark() {
            return this.get() === THEMES.DARK;
        },

        onChange(callback) {
            window.addEventListener('themechange', (e) => callback(e.detail.theme));
        }
    };

    ThemeManager.init();

    window.ThemeManager = ThemeManager;
    window.toggleTheme = () => ThemeManager.toggle();

    console.log('[Theme] Initialized:', ThemeManager.get());
})();