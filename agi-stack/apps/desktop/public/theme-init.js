// Pre-paint theme bootstrap. Loaded as a classic script from <head> so
// documentElement carries data-theme before the first paint; must stay
// dependency-free and in sync with src/theme.tsx.
(function () {
  var theme = 'dark';
  try {
    var raw = window.localStorage.getItem('agistack.desktop.theme');
    var preference = raw === 'dark' || raw === 'light' || raw === 'system' ? raw : 'dark';
    theme = preference;
    if (preference === 'system') {
      theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
  } catch (error) {
    theme = 'dark';
  }
  document.documentElement.dataset.theme = theme;
  // Keep the browser chrome color in sync with the resolved theme background
  // (#0a0a0a dark / #ffffff light, matching --desktop-bg).
  var themeColorMeta = document.querySelector('meta[name="theme-color"]');
  if (themeColorMeta) {
    themeColorMeta.setAttribute('content', theme === 'light' ? '#ffffff' : '#0a0a0a');
  }
})();
