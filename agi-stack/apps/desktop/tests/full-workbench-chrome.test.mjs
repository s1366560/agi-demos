import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { presentHeaderGroups } = require(
  '/tmp/agistack-desktop-test-dist/src/fullHost/headerPresentation.js',
);

const css = readFileSync(new URL('../src/fullHost/style.css', import.meta.url), 'utf8');
const theme = readFileSync(new URL('../src/theme.tsx', import.meta.url), 'utf8');
const bootstrap = readFileSync(new URL('../public/theme-init.js', import.meta.url), 'utf8');
const shell = readFileSync(new URL('../src/fullHost/FullWorkbench.tsx', import.meta.url), 'utf8');

test('light and dark both publish the class signed pages already listen for', () => {
  for (const source of [theme, bootstrap]) {
    assert.match(source, /classList\.toggle\('dark',/);
    assert.match(source, /dataset\.theme/);
  }
});

test('the sidebar width is draggable and the narrow overlay sits flush under the titlebar', () => {
  assert.match(css, /--desktop-sidebar-preferred-width:\s*256px/);
  assert.match(css, /:not\(\.sidebar-collapsed\)/);
  assert.match(css, /@media \(max-width: 767px\)/);
  assert.match(css, /height: 100dvh/);
  assert.match(css, /--desktop-sidebar-width:\s*0px/);
  assert.match(css, /top:\s*0;/);
  assert.match(css, /\.app-shell:has\(\.desktop-workbench-header\) \.workbench \{\s*grid-column:\s*2;/);
  assert.doesNotMatch(css, /top:\s*36px/);
  assert.match(
    css,
    /width:\s*min\(var\(--desktop-sidebar-preferred-width, 256px\), calc\(100vw - 2rem\)\)/,
  );
  assert.doesNotMatch(
    css.slice(0, css.indexOf(':not(.sidebar-collapsed)')),
    /--desktop-sidebar-width:\s*256px/,
  );
  assert.match(shell, /useResizablePanelWidth/);
  assert.match(shell, /FULL_HOST_SIDEBAR_CONSTRAINTS/);
  assert.match(shell, /ResizeHandle/);
  assert.match(shell, /--desktop-sidebar-preferred-width/);
  assert.match(shell, /signedSidebarLoadPhase/);
  assert.match(shell, /scopeReady \? project : null/);
});

test('full workbench surfaces follow the web light and dark shell colors', () => {
  assert.match(css, /:root\[data-theme='light'\] \.app-shell:has\(\.desktop-workbench-header\)/);
  assert.match(css, /--desktop-bg:\s*#f7f7f7/);
  assert.match(css, /--desktop-sidebar-bg:\s*#ffffff/);
  assert.match(css, /--desktop-bg:\s*#0a0a0a/);
  assert.match(css, /--desktop-sidebar-bg:\s*#121212/);
});

test('a narrow window starts collapsed and a short header menu keeps every section', () => {
  assert.match(shell, /NARROW_SHELL_QUERY/);
  const groups = [
    {
      id: 'core',
      label: 'Core',
      current: false,
      items: [{ id: 'projects', label: 'Projects', path: '/projects', active: false }],
    },
    {
      id: 'knowledge',
      label: 'Knowledge',
      current: true,
      items: [{ id: 'memories', label: 'Memories', path: '/memories', active: true }],
    },
  ];
  assert.equal(presentHeaderGroups(groups, false).length, 2);
  const compact = presentHeaderGroups(groups, true);
  assert.deepEqual(
    compact.map((group) => group.id),
    ['compact-navigation'],
  );
  assert.equal(compact[0].label, 'Knowledge');
  assert.deepEqual(
    compact[0].items.map((item) => item.id),
    ['projects', 'memories'],
  );
});
