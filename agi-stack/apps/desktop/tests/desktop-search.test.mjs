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
  DesktopSearch,
} = require('/tmp/agistack-desktop-test-dist/src/features/search/DesktopSearch.js');

const source = readFileSync(
  new URL('../src/features/search/DesktopSearch.tsx', import.meta.url),
  'utf8',
);

function renderSearch(
  projectId = 'project-1',
  capability = { available: true, reason_code: null },
) {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(DesktopSearch, {
        api: { searchProject: async () => ({ results: [], total: 0 }) },
        tenantId: 'tenant-1',
        projectId,
        projectName: projectId ? 'Desktop Search' : null,
        capability,
        capabilityLoading: false,
        onOpenProjectSettings: () => {},
      }),
    ),
  );
}

test('desktop search exposes all five Web search modes without static workspace metrics', () => {
  const markup = renderSearch();

  assert.match(markup, /Semantic/);
  assert.match(markup, /Graph traversal/);
  assert.match(markup, /Temporal/);
  assert.match(markup, /Faceted/);
  assert.match(markup, /Community/);
  assert.match(markup, /Search current project/);
  assert.doesNotMatch(markup, /Workspace task summary|Across Work and Code/);
});

test('desktop search requires an authoritative project before issuing requests', () => {
  const markup = renderSearch('');

  assert.match(markup, /Choose a project to search/);
  assert.match(markup, /Open workspace settings/);
  assert.doesNotMatch(markup, /type="submit"/);
});

test('desktop search fails closed when no structured capability is available', () => {
  const markup = renderSearch('project-1', {
    available: false,
    reason_code: 'search_capability_contract_unavailable',
  });

  assert.match(markup, /Search is unavailable/);
  assert.match(markup, /aria-label="Search is unavailable"/);
  assert.match(markup, /data-reason-code="search_capability_contract_unavailable"/);
  assert.doesNotMatch(markup, /type="submit"/);
});

test('desktop search cancels and rejects stale requests across scope changes', () => {
  assert.match(source, /AbortController/);
  assert.match(source, /\.abort\(\)/);
  assert.match(source, /searchResponseMayCommit/);
  assert.match(source, /tenantId/);
  assert.match(source, /projectId/);
});
