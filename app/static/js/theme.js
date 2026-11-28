/*
 * Light / dark mode (issue #54).
 *
 * Loaded in <head> so the theme is set before the page is drawn (no flash of the wrong
 * theme). Uses Bootstrap 5.3's data-bs-theme. The choice is remembered in this browser;
 * until the user picks one, the operating system's setting is followed.
 */
(() => {
    const KEY = 'repomaster-theme';
    const root = document.documentElement;
    const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

    const saved = () => {
        try {
            const value = window.localStorage.getItem(KEY);
            return value === 'dark' || value === 'light' ? value : null;
        } catch (e) {
            return null;  // storage blocked (private mode, cookies disabled)
        }
    };
    const save = (theme) => {
        try {
            window.localStorage.setItem(KEY, theme);
        } catch (e) { /* the choice just won't be remembered */ }
    };
    const preferred = () => saved() || (media && media.matches ? 'dark' : 'light');

    let button = null;
    const apply = (theme) => {
        root.setAttribute('data-bs-theme', theme);
        if (button) {
            const next = theme === 'dark' ? 'light' : 'dark';
            button.textContent = theme === 'dark' ? '☀' : '☾';  // sun / moon
            button.setAttribute('aria-label', `Switch to ${next} mode`);
            button.title = `Switch to ${next} mode`;
        }
    };

    apply(preferred());

    if (media && media.addEventListener) {
        media.addEventListener('change', () => { if (!saved()) apply(preferred()); });
    }

    document.addEventListener('DOMContentLoaded', () => {
        button = document.createElement('button');
        button.type = 'button';
        button.className = 'theme-toggle';
        button.addEventListener('click', () => {
            const next = root.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
            save(next);
            apply(next);
        });
        document.body.appendChild(button);
        apply(root.getAttribute('data-bs-theme') || preferred());
    });
})();
