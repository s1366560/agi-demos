import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  KEYBOARD_SHORTCUTS,
  SHORTCUT_GROUPS,
  detectShortcutPlatform,
  shortcutById,
  shortcutChordFor,
  shortcutChordSegments,
  shortcutGroups,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/keyboardShortcutModel.js');
const { KeyboardShortcutsPanel } = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/KeyboardShortcutsDialog.js'
);
const { ShortcutSettingsPage } = require(
  '/tmp/agistack-desktop-test-dist/src/features/settings/ShortcutSettingsPage.js'
);

const readSource = (path) =>
  readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');

const modelSource = readSource('features/navigation/keyboardShortcutModel.ts');
const dialogSource = readSource('features/navigation/KeyboardShortcutsDialog.tsx');
const dialogCssSource = readSource('features/navigation/KeyboardShortcutsDialog.css');
const appSource = readSource('App.tsx');
const shellTypesSource = readSource('appShellTypes.ts');
const commandPaletteSource = readSource('features/navigation/CommandPalette.tsx');
const stylesSource = readSource('app-shell.css');
const i18nSource = readSource('i18n.tsx');

function withStoredLocale(locale, render) {
  const previousWindow = globalThis.window;
  globalThis.window = {
    localStorage: {
      getItem: (key) => (key === 'agistack.desktop.locale' ? locale : null),
      setItem: () => {},
    },
    addEventListener: () => {},
    removeEventListener: () => {},
  };
  try {
    return render();
  } finally {
    if (previousWindow === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = previousWindow;
    }
  }
}

function renderPanel(platform = 'other') {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(KeyboardShortcutsPanel, { platform, onClose: () => {} }),
    ),
  );
}

test('detectShortcutPlatform resolves mac from platform or user agent', () => {
  assert.equal(detectShortcutPlatform(undefined, 'MacIntel'), 'mac');
  assert.equal(
    detectShortcutPlatform('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'),
    'mac',
  );
  assert.equal(detectShortcutPlatform(undefined, 'Win32'), 'other');
  assert.equal(detectShortcutPlatform('Mozilla/5.0 (X11; Linux x86_64)'), 'other');
  assert.equal(detectShortcutPlatform(), 'other');
});

test('shortcutChordFor selects the platform-specific chord', () => {
  const palette = shortcutById('command-palette');
  assert.equal(shortcutChordFor(palette, 'mac'), '⌘ K');
  assert.equal(shortcutChordFor(palette, 'other'), 'Ctrl K');
  const newline = shortcutById('composer-newline');
  assert.equal(shortcutChordFor(newline, 'mac'), '⇧ Enter');
  assert.equal(shortcutChordFor(newline, 'other'), 'Shift Enter');
});

test('shortcutChordSegments splits a chord into key chips', () => {
  assert.deepEqual(shortcutChordSegments('⌘ K'), ['⌘', 'K']);
  assert.deepEqual(shortcutChordSegments('↑ ↓'), ['↑', '↓']);
  assert.deepEqual(shortcutChordSegments('/'), ['/']);
});

test('shortcut registry is grouped and free of duplicate ids', () => {
  const ids = KEYBOARD_SHORTCUTS.map((definition) => definition.id);
  assert.equal(new Set(ids).size, ids.length);
  const groups = shortcutGroups();
  assert.deepEqual(
    groups.map(({ group }) => group),
    [...SHORTCUT_GROUPS],
  );
  const grouped = groups.flatMap(({ shortcuts }) => shortcuts);
  assert.equal(grouped.length, KEYBOARD_SHORTCUTS.length);
  for (const definition of KEYBOARD_SHORTCUTS) {
    assert.ok(SHORTCUT_GROUPS.includes(definition.group), definition.id);
    assert.ok(definition.chords.mac.length > 0, definition.id);
    assert.ok(definition.chords.other.length > 0, definition.id);
  }
});

test('every registered shortcut label exists in both i18n dictionaries', () => {
  for (const definition of KEYBOARD_SHORTCUTS) {
    assert.equal(
      (i18nSource.match(new RegExp(`'${definition.labelKey.replaceAll('.', '\\.')}'`, 'g')) ?? [])
        .length,
      2,
      definition.labelKey,
    );
  }
  for (const key of [
    'shortcuts.title',
    'shortcuts.description',
    'shortcuts.group.navigation',
    'shortcuts.group.composer',
    'shortcuts.group.general',
    'commandPalette.showShortcuts',
  ]) {
    assert.equal(
      (i18nSource.match(new RegExp(`'${key.replaceAll('.', '\\.')}'`, 'g')) ?? []).length,
      2,
      key,
    );
  }
});

test('shortcuts dialog renders an accessible localized dialog in en', () => {
  const markup = withStoredLocale('en', () => renderPanel('other'));
  assert.match(markup, /role="dialog"/);
  assert.match(markup, /aria-modal="true"/);
  assert.match(markup, /aria-label="Keyboard shortcuts"/);
  assert.match(markup, /aria-label="Close"/);
  assert.match(markup, /Navigation/);
  assert.match(markup, /Composer/);
  assert.match(markup, /General/);
  assert.match(markup, /Open the command palette/);
  assert.match(markup, /Send the message/);
  assert.match(markup, /<kbd class="shortcuts-kbd">Ctrl<\/kbd><kbd class="shortcuts-kbd">K<\/kbd>/);
  assert.ok((markup.match(/<kbd /g) ?? []).length >= KEYBOARD_SHORTCUTS.length);
});

test('shortcuts dialog renders mac chords when the platform is mac', () => {
  const markup = withStoredLocale('en', () => renderPanel('mac'));
  assert.match(markup, /<kbd class="shortcuts-kbd">⌘<\/kbd><kbd class="shortcuts-kbd">K<\/kbd>/);
  assert.match(markup, /<kbd class="shortcuts-kbd">⇧<\/kbd>/);
});

test('shortcuts dialog renders localized zh-CN copy when the locale is stored', () => {
  const markup = withStoredLocale('zh-CN', () => renderPanel('other'));
  assert.match(markup, /aria-label="键盘快捷键"/);
  assert.match(markup, /导航/);
  assert.match(markup, /输入框/);
  assert.match(markup, /通用/);
  assert.match(markup, /打开命令面板/);
  assert.match(markup, /发送消息/);
});

test('command palette renders a kbd hint for items with a shortcut', () => {
  assert.match(shellTypesSource, /shortcut\?: string;/);
  assert.match(appSource, /id: 'keyboard-shortcuts'/);
  assert.match(appSource, /shortcut: showShortcutsChord/);
  assert.match(
    commandPaletteSource,
    /\{item\.shortcut \? <kbd className="command-shortcut">\{item\.shortcut\}<\/kbd> : null\}/,
  );
  assert.match(stylesSource, /\.command-shortcut \{/);
  assert.doesNotMatch(stylesSource.match(/\.command-shortcut \{[\s\S]*?\n\}/)?.[0] ?? '', /#[0-9a-fA-F]{3,8}\b/);
});

test('shortcuts dialog source keeps user-visible strings behind t()', () => {
  assert.match(dialogSource, /t\('shortcuts\.title'\)/);
  assert.match(dialogSource, /t\('common\.close'\)/);
  assert.match(dialogSource, /t\(`shortcuts\.group\.\$\{group\}`\)/);
  assert.match(dialogSource, /t\(definition\.labelKey\)/);
  assert.doesNotMatch(dialogSource, /aria-label="[A-Za-z]/);
  assert.doesNotMatch(dialogSource, /placeholder="[A-Za-z]/);
  assert.doesNotMatch(dialogSource, />[A-Z][a-z]+ [a-z]+</);
});

test('shortcuts dialog styles use desktop tokens and honor reduced motion', () => {
  for (const token of [
    '--desktop-panel',
    '--desktop-panel-2',
    '--desktop-border',
    '--desktop-border-soft',
    '--desktop-text',
    '--desktop-muted',
    '--desktop-faint',
  ]) {
    assert.match(dialogCssSource, new RegExp(`var\\(${token}\\)`), token);
  }
  assert.match(dialogCssSource, /@media \(prefers-reduced-motion: reduce\)/);
  assert.doesNotMatch(dialogCssSource, /#[0-9a-fA-F]{3,8}\b/);
});

test('model module stays free of React and hardcoded user copy', () => {
  assert.doesNotMatch(modelSource, /from 'react'/);
  assert.doesNotMatch(modelSource, /label: '/);
});

function renderShortcutSettingsPage(platform = 'other') {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(ShortcutSettingsPage, { platform }),
    ),
  );
}

test('shortcut settings page renders the searchable catalog from the shared model', () => {
  const markup = withStoredLocale('en', () => renderShortcutSettingsPage('other'));
  assert.match(markup, /Keyboard shortcuts/);
  assert.match(markup, /Search shortcuts or press a key combination/);
  assert.match(markup, /Open the command palette/);
  assert.match(markup, /<kbd class="shortcuts-kbd">Ctrl<\/kbd><kbd class="shortcuts-kbd">K<\/kbd>/);
  assert.match(markup, /per-user remapping is planned as a follow-up/);
  assert.ok((markup.match(/shortcuts-row__label/g) ?? []).length >= KEYBOARD_SHORTCUTS.length);
});

test('shortcut settings page renders localized zh-CN copy', () => {
  const markup = withStoredLocale('zh-CN', () => renderShortcutSettingsPage('other'));
  assert.match(markup, /搜索快捷键，或直接按下组合键/);
  assert.match(markup, /打开命令面板/);
  assert.match(markup, /快捷键目录/);
});
