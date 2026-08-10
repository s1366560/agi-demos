import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  CommandPalette,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/CommandPalette.js');

const source = readFileSync(
  new URL('../src/features/navigation/CommandPalette.tsx', import.meta.url),
  'utf8',
);

function renderPalette(items) {
  const previousWindow = globalThis.window;
  globalThis.window = {
    localStorage: {
      getItem: () => 'en',
      setItem: () => {},
    },
    addEventListener: () => {},
    removeEventListener: () => {},
  };
  try {
    return renderToStaticMarkup(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(CommandPalette, {
          inputRef: { current: null },
          query: '',
          items,
          onQueryChange: () => {},
          onClose: () => {},
        }),
      ),
    );
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
}

const baseItem = {
  kind: 'route',
  groupId: 'tenant-core-operations',
  groupLabel: 'Core operations',
  label: 'Overview',
  description: 'Open Overview',
  icon: React.createElement('span', null, 'icon'),
  searchText: 'Overview Core operations tenant-tenant-overview',
  onSelect: () => {},
};

test('command palette renders grouped listbox semantics and disabled reasons', () => {
  const markup = renderPalette([
    { ...baseItem, id: 'overview', routeId: 'tenant-tenant-overview' },
    {
      ...baseItem,
      id: 'billing',
      routeId: 'tenant-tenant-billing',
      groupId: 'tenant-governance-management',
      groupLabel: 'Governance',
      label: 'Billing',
      disabled: true,
      disabledReason: 'Select a tenant first.',
    },
  ]);

  assert.match(markup, /role="combobox"/);
  assert.match(markup, /aria-controls="command-palette-results"/);
  assert.match(markup, /aria-expanded="true"/);
  assert.match(markup, /aria-autocomplete="list"/);
  assert.match(markup, /id="command-palette-results"[^>]*role="listbox"/);
  assert.equal((markup.match(/role="group"/g) ?? []).length, 2);
  assert.equal((markup.match(/role="option"/g) ?? []).length, 2);
  assert.match(markup, /Core operations/);
  assert.match(markup, /Governance/);
  assert.match(markup, /Select a tenant first\./);
});

test('command palette keyboard traversal remains flat across visual groups', () => {
  assert.match(source, /const enabledItems = useMemo/);
  assert.match(source, /items\.filter\(\(item\) => !item\.disabled\)/);
  assert.match(source, /moveActiveItem\(1\)/);
  assert.match(source, /moveActiveItem\(-1\)/);
  assert.match(source, /setActiveItemId\(enabledItems\[0\]\.id\)/);
  assert.match(source, /setActiveItemId\(enabledItems\[enabledItems\.length - 1\]\.id\)/);
});

test('command palette omits empty groups because groups are derived from visible items', () => {
  const markup = renderPalette([
    { ...baseItem, id: 'overview', routeId: 'tenant-tenant-overview' },
  ]);

  assert.equal((markup.match(/role="group"/g) ?? []).length, 1);
  assert.doesNotMatch(markup, /Governance/);
});
