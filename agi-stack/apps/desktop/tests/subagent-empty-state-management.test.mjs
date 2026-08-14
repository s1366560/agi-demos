import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  ManagedResourceWorkspace,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings/ManagedResourceViews.js');

const managedResourceViewsSource = readFileSync(
  new URL('../src/features/settings/ManagedResourceViews.tsx', import.meta.url),
  'utf8',
);

test('an authorized empty SubAgent catalog still exposes its management actions', () => {
  assert.match(
    managedResourceViewsSource,
    /section === 'subagents' && canCreate/u,
  );
  assert.doesNotMatch(
    managedResourceViewsSource,
    /section === 'subagents' && canManage/u,
  );
});

test('an empty SubAgent catalog distinguishes resources from project availability', () => {
  const withProject = renderEmptySubAgentCatalog(true);
  assert.match(
    withProject,
    /managed-resource-catalog-state[^>]*>[\s\S]*?<strong>0 SubAgents<\/strong>/u,
  );
  assert.doesNotMatch(withProject, /No projects are available in this tenant\./u);

  const withoutProjects = renderEmptySubAgentCatalog(false);
  assert.match(withoutProjects, /No projects are available in this tenant\./u);
  assert.doesNotMatch(
    withoutProjects,
    /managed-resource-catalog-state[^>]*>[\s\S]*?<strong>0 SubAgents<\/strong>/u,
  );
});

function renderEmptySubAgentCatalog(hasAvailableProjects) {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(ManagedResourceWorkspace, {
        section: 'subagents',
        items: [],
        selected: null,
        query: '',
        filter: 'all',
        loading: false,
        error: null,
        actionError: null,
        busy: false,
        canManage: false,
        canCreate: true,
        mode: 'local',
        hasAvailableProjects,
        onQueryChange() {},
        onFilterChange() {},
        onSelect() {},
        onRetry() {},
        onAction() {},
        onCreate() {},
        onImport() {},
        onEdit() {},
        onVersions() {},
        onExport() {},
        onEvolution() {},
        onSubAgentLibrary() {},
        onImportSubAgent() {},
        onChannels() {},
        onPluginActivity() {},
        onReload() {},
        onRemove() {},
      }),
    ),
  );
}
