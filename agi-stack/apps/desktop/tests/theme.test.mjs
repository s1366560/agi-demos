import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const theme = require('/tmp/agistack-desktop-test-dist/src/theme.js');
const { PreferenceSummaryPage } = require(
  '/tmp/agistack-desktop-test-dist/src/features/settings/SettingsCorePages.js'
);
const notificationPreferences = require(
  '/tmp/agistack-desktop-test-dist/src/features/settings/notificationPreferences.js'
);

const stylesCss = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const mainSource = readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8');
const settingsCoreSource = readFileSync(
  new URL('../src/features/settings/SettingsCorePages.tsx', import.meta.url),
  'utf8',
);
const indexHtml = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const themeInitSource = readFileSync(new URL('../public/theme-init.js', import.meta.url), 'utf8');
const themeSource = readFileSync(new URL('../src/theme.tsx', import.meta.url), 'utf8');

const {
  DEFAULT_THEME_PREFERENCE,
  THEME_STORAGE_KEY,
  ThemePreferenceProvider,
  parseThemePreference,
  resolveTheme,
} = theme;
const {
  DEFAULT_NOTIFICATION_PREFERENCES,
  NOTIFICATION_PREFERENCES_STORAGE_KEY,
  parseNotificationPreferences,
  readNotificationPreferences,
  writeNotificationPreferences,
} = notificationPreferences;

function blockTokens(blockSource) {
  const tokens = new Map();
  for (const match of blockSource.matchAll(/(--desktop-[\w-]+)\s*:\s*([^;]+);/g)) {
    tokens.set(match[1], match[2].trim());
  }
  return tokens;
}

const rootBlock = stylesCss.match(/:root\s*\{([\s\S]*?)\}/);
assert.ok(rootBlock, 'styles.css must define a plain :root block');
const lightBlock = stylesCss.match(/:root\[data-theme='light'\]\s*\{([\s\S]*?)\}/);
assert.ok(lightBlock, "styles.css must define a :root[data-theme='light'] block");
const darkTokens = blockTokens(rootBlock[1]);
const lightTokens = blockTokens(lightBlock[1]);

function hexToChannels(hex) {
  let value = hex.replace('#', '');
  if (value.length === 3) value = [...value].map((char) => char + char).join('');
  return [0, 2, 4].map((offset) => parseInt(value.slice(offset, offset + 2), 16)).join(', ');
}

function withStoredGlobals({ locale = 'en', theme: storedTheme = null } = {}, render) {
  const previousWindow = globalThis.window;
  const previousDocument = globalThis.document;
  globalThis.window = {
    localStorage: {
      getItem: (key) => {
        if (key === 'agistack.desktop.locale') return locale;
        if (key === THEME_STORAGE_KEY) return storedTheme;
        return null;
      },
      setItem: () => {},
    },
    addEventListener: () => {},
    removeEventListener: () => {},
  };
  try {
    return render();
  } finally {
    globalThis.window = previousWindow;
    globalThis.document = previousDocument;
  }
}

test('theme storage key and default preference are pinned', () => {
  assert.equal(THEME_STORAGE_KEY, 'agistack.desktop.theme');
  assert.equal(DEFAULT_THEME_PREFERENCE, 'dark');
});

test('parseThemePreference accepts valid values and falls back to dark', () => {
  assert.equal(parseThemePreference('dark'), 'dark');
  assert.equal(parseThemePreference('light'), 'light');
  assert.equal(parseThemePreference('system'), 'system');
  assert.equal(parseThemePreference(null), 'dark');
  assert.equal(parseThemePreference(''), 'dark');
  assert.equal(parseThemePreference('blue'), 'dark');
  assert.equal(parseThemePreference('DARK'), 'dark');
});

test('resolveTheme covers every preference x system combination', () => {
  assert.equal(resolveTheme('dark', true), 'dark');
  assert.equal(resolveTheme('dark', false), 'dark');
  assert.equal(resolveTheme('light', true), 'light');
  assert.equal(resolveTheme('light', false), 'light');
  assert.equal(resolveTheme('system', true), 'dark');
  assert.equal(resolveTheme('system', false), 'light');
});

test('light theme overrides exactly the token set defined in :root', () => {
  assert.ok(darkTokens.size > 80, 'dark :root should define the full token set');
  assert.deepEqual([...lightTokens.keys()].sort(), [...darkTokens.keys()].sort());
});

test('light theme sets a light color-scheme', () => {
  assert.match(lightBlock[1], /color-scheme:\s*light/);
});

test('light *-rgb channel tokens match their named light token channels', () => {
  const checked = [];
  for (const [name, value] of lightTokens) {
    if (!name.endsWith('-rgb')) continue;
    const named = lightTokens.get(name.slice(0, -4));
    if (!named || !named.startsWith('#')) continue;
    checked.push(name);
    assert.equal(value, hexToChannels(named), `${name} must match ${name.slice(0, -4)}`);
  }
  assert.ok(checked.length >= 4, 'expected several named/rgb token pairs to be checked');
});

test('light overlay channel tokens stay dark translucent like the dark theme', () => {
  for (const [name, value] of darkTokens) {
    if (!name.startsWith('--desktop-overlay-')) continue;
    assert.equal(lightTokens.get(name), value, `${name} must stay identical in the light theme`);
  }
});

test('App.tsx no longer hardcodes a dark Radix appearance', () => {
  assert.ok(!appSource.includes('appearance="dark"'));
  assert.match(appSource, /useThemePreference/);
});

test('main.tsx mounts ThemePreferenceProvider around the app', () => {
  assert.match(mainSource, /import \{ ThemePreferenceProvider \} from '\.\/theme';/);
  assert.match(mainSource, /<ThemePreferenceProvider>/);
});

test('settings appearance page uses the theme preference hook', () => {
  assert.match(settingsCoreSource, /useThemePreference/);
  assert.match(settingsCoreSource, /role="radiogroup"/);
});

test('theme i18n keys exist in both dictionaries', () => {
  const keys = [
    'settings.themeDescription',
    'settings.themeGroupLabel',
    'settings.themeDark',
    'settings.themeDarkDescription',
    'settings.themeLight',
    'settings.themeLightDescription',
    'settings.themeSystem',
    'settings.themeSystemDescription',
  ];
  for (const key of keys) {
    const occurrences = i18nSource.split(`'${key}':`).length - 1;
    assert.ok(occurrences >= 2, `${key} must exist in enUS and zhCN (found ${occurrences})`);
  }
});

test('no-flash bootstrap script is referenced from index.html and stays in sync', () => {
  assert.match(indexHtml, /<script src="\/theme-init\.js"><\/script>/);
  assert.ok(themeInitSource.includes(THEME_STORAGE_KEY));
  assert.ok(themeInitSource.includes('prefers-color-scheme: dark'));
});

test('meta theme-color follows the resolved theme background', () => {
  // index.html declares the dark default; the bootstrap script and the provider
  // effect both rewrite it to the resolved theme's --desktop-bg value.
  assert.match(indexHtml, /<meta name="theme-color" content="#0d0d0d" \/>/);
  for (const source of [themeInitSource, themeSource]) {
    assert.ok(source.includes('meta[name="theme-color"]'));
    assert.ok(source.includes('#f9f9f9'), 'light theme-color must match light --desktop-bg');
    assert.ok(source.includes('#0d0d0d'), 'dark theme-color must stay #0d0d0d');
  }
  assert.equal(lightTokens.get('--desktop-bg'), '#f9f9f9');
});

test('appearance settings page renders a localized radiogroup in English', () => {
  const markup = withStoredGlobals({ locale: 'en' }, () =>
    renderToStaticMarkup(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(
          ThemePreferenceProvider,
          null,
          React.createElement(PreferenceSummaryPage, { section: 'appearance' })
        )
      )
    )
  );
  assert.ok(markup.includes('role="radiogroup"'));
  assert.equal((markup.match(/role="radio"/g) || []).length, 3);
  assert.ok(markup.includes('Dark'));
  assert.ok(markup.includes('Light'));
  assert.ok(markup.includes('System'));
  assert.equal((markup.match(/aria-checked="true"/g) || []).length, 1);
});

test('appearance settings page renders a localized radiogroup in zh-CN', () => {
  const markup = withStoredGlobals({ locale: 'zh-CN' }, () =>
    renderToStaticMarkup(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(
          ThemePreferenceProvider,
          null,
          React.createElement(PreferenceSummaryPage, { section: 'appearance' })
        )
      )
    )
  );
  assert.ok(markup.includes('role="radiogroup"'));
  assert.ok(markup.includes('深色'));
  assert.ok(markup.includes('浅色'));
  assert.ok(markup.includes('跟随系统'));
});

test('stored light preference marks the light radio as checked', () => {
  const markup = withStoredGlobals({ locale: 'en', theme: 'light' }, () =>
    renderToStaticMarkup(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(
          ThemePreferenceProvider,
          null,
          React.createElement(PreferenceSummaryPage, { section: 'appearance' })
        )
      )
    )
  );
  const lightRadio = markup.match(/<button[^>]*aria-checked="true"[^>]*>[\s\S]*?<\/button>/);
  assert.ok(lightRadio, 'one radio must be checked');
  assert.ok(lightRadio[0].includes('Light'));
});

test('notification preferences use a versioned storage contract with safe defaults', () => {
  assert.equal(
    NOTIFICATION_PREFERENCES_STORAGE_KEY,
    'agistack.desktop.notification-preferences:v1'
  );
  assert.deepEqual(DEFAULT_NOTIFICATION_PREFERENCES, {
    reviewAlerts: true,
    delivery: 'desktop_and_in_app',
    completionMode: 'window_not_focused',
    quietHours: {
      enabled: false,
      start: '22:00',
      end: '08:00',
    },
  });
  assert.deepEqual(parseNotificationPreferences(null), DEFAULT_NOTIFICATION_PREFERENCES);
  assert.deepEqual(
    parseNotificationPreferences(
      JSON.stringify({
        version: 1,
        reviewAlerts: false,
        delivery: 'in_app',
        quietHours: { enabled: true, start: '21:30', end: '07:15' },
      })
    ),
    {
      reviewAlerts: false,
      delivery: 'in_app',
      completionMode: 'window_not_focused',
      quietHours: { enabled: true, start: '21:30', end: '07:15' },
    }
  );
  for (const invalid of [
    '{',
    JSON.stringify({ version: 2 }),
    JSON.stringify({
      version: 1,
      reviewAlerts: 'yes',
      delivery: 'email',
      quietHours: { enabled: true, start: 'night', end: 'morning' },
    }),
  ]) {
    assert.deepEqual(parseNotificationPreferences(invalid), DEFAULT_NOTIFICATION_PREFERENCES);
  }
});

test('notification preference persistence reads and writes the complete immutable snapshot', () => {
  const writes = [];
  const storage = {
    value: null,
    getItem(key) {
      assert.equal(key, NOTIFICATION_PREFERENCES_STORAGE_KEY);
      return this.value;
    },
    setItem(key, value) {
      assert.equal(key, NOTIFICATION_PREFERENCES_STORAGE_KEY);
      this.value = value;
      writes.push(value);
    },
  };
  const next = {
    reviewAlerts: false,
    delivery: 'desktop',
    completionMode: 'always',
    quietHours: { enabled: true, start: '23:00', end: '06:30' },
  };

  writeNotificationPreferences(next, storage);

  assert.equal(writes.length, 1);
  assert.deepEqual(JSON.parse(writes[0]), { version: 1, ...next });
  assert.deepEqual(readNotificationPreferences(storage), next);
  assert.notEqual(readNotificationPreferences(storage), next);
  assert.notEqual(readNotificationPreferences(storage).quietHours, next.quietHours);
});

test('notification settings render persisted switches, delivery choices, and quiet hours', () => {
  const stored = JSON.stringify({
    version: 1,
    reviewAlerts: false,
    delivery: 'in_app',
    quietHours: { enabled: true, start: '21:30', end: '07:15' },
  });
  const previousWindow = globalThis.window;
  globalThis.window = {
    localStorage: {
      getItem: (key) => {
        if (key === 'agistack.desktop.locale') return 'en';
        if (key === NOTIFICATION_PREFERENCES_STORAGE_KEY) return stored;
        return null;
      },
      setItem: () => {},
    },
    addEventListener: () => {},
    removeEventListener: () => {},
  };
  try {
    const markup = renderToStaticMarkup(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(
          ThemePreferenceProvider,
          null,
          React.createElement(PreferenceSummaryPage, { section: 'notifications' })
        )
      )
    );

    assert.equal((markup.match(/role="switch"/g) || []).length, 2);
    assert.ok(markup.includes('aria-checked="false"'));
    assert.ok(markup.includes('role="radiogroup"'));
    assert.equal((markup.match(/role="radio"/g) || []).length, 6);
    assert.ok(markup.includes('In-app only'));
    assert.ok(markup.includes('When the window is not focused'));
    assert.equal((markup.match(/aria-checked="true"/g) || []).length, 3);
    assert.match(markup, /type="time"[^>]*value="21:30"/);
    assert.match(markup, /type="time"[^>]*value="07:15"/);
  } finally {
    globalThis.window = previousWindow;
  }
});

test('notification preference i18n keys exist in both dictionaries', () => {
  const keys = [
    'settings.reviewAlertsDescription',
    'settings.preferenceOn',
    'settings.preferenceOff',
    'settings.deliveryGroupLabel',
    'settings.deliveryDesktopAndInApp',
    'settings.deliveryDesktopOnly',
    'settings.deliveryInAppOnly',
    'settings.quietHoursDescription',
    'settings.quietHoursStart',
    'settings.quietHoursEnd',
  ];
  for (const key of keys) {
    const occurrences = i18nSource.split(`'${key}':`).length - 1;
    assert.ok(occurrences >= 2, `${key} must exist in enUS and zhCN (found ${occurrences})`);
  }
});
