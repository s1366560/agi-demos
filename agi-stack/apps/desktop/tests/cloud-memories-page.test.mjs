import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  CloudMemoriesPage,
} = require('/tmp/agistack-desktop-test-dist/src/features/project-knowledge/CloudMemoriesPage.js');
const {
  CloudMemoryRouteSurface,
} = require('/tmp/agistack-desktop-test-dist/src/features/project-knowledge/CloudMemoryRouteSurface.js');
const {
  CloudMemoryRouteContextProvider,
} = require('/tmp/agistack-desktop-test-dist/src/features/project-knowledge/CloudMemoryRouteContext.js');
const h = React.createElement;
const noop = () => {};
const scope = { authority: 'cloud', tenantId: 'tenant-1', projectId: 'project-1' };
const memory = {
  id: 'memory-1',
  projectId: 'project-1',
  title: 'Original title',
  content: 'Original body',
  contentType: 'text',
  version: 1,
  status: 'ENABLED',
  processingStatus: 'pending',
  createdAt: '2026-09-08T00:00:00Z',
  updatedAt: null,
};
const list = {
  scope,
  scopeRevision: 7,
  authority: 'cloud',
  availability: 'degraded',
  reasonCode: 'partial',
  allowedActions: ['list', 'view', 'create', 'update', 'delete'],
  memories: [memory],
  page: 1,
  pageSize: 50,
  total: null,
  hasMore: true,
};
const model = {
  phase: 'idle',
  listState: 'ready',
  list,
  record: null,
  latest: null,
  draft: null,
  intent: null,
  error: null,
  notice: null,
  canCreate: false,
  readable: true,
};
const controller = {
  create: noop,
  loadPage: noop,
  goToPage: noop,
  open: noop,
  save: noop,
  setDraft: noop,
  confirmDelete: noop,
  retryWrite: noop,
  reloadConflict: noop,
  adoptLatest: noop,
  close: noop,
  canView: () => true,
  canUpdate: () => false,
  canDelete: () => false,
};
const render = (element) => renderToStaticMarkup(h(I18nProvider, null, element));
const page = (m = model, c = controller) =>
  render(h(CloudMemoriesPage, { model: m, controller: c }));

test('legacy list allowedActions do not create write affordances and no-total pagination stays honest', () => {
  const html = page();
  assert.match(html, />View</);
  assert.doesNotMatch(html, />Edit<|>Delete<|New memory/);
  assert.match(html, /Page 1/);
  assert.doesNotMatch(html, /Page 1 \/|NaN|Infinity/);
  assert.match(html, />Next page</);
});

test('unknown write locks list and editor while preserving the draft and exact-retry affordance', () => {
  const html = page(
    {
      ...model,
      phase: 'uncertain',
      canCreate: true,
      intent: 'edit',
      record: memory,
      draft: { title: 'Preserved draft', content: 'Preserved body' },
    },
    { ...controller, canUpdate: () => true, canDelete: () => true },
  );
  assert.match(html, /readOnly=""[^>]*value="Preserved draft"/);
  assert.match(html, /Preserved body/);
  assert.match(html, /outcome is unknown/);
  assert.match(html, />Retry the same request</);
  assert.match(html, /<button[^>]*disabled=""[^>]*>New memory/);
  assert.match(html, /<button[^>]*disabled=""[^>]*>Refresh/);
  assert.doesNotMatch(html, />Save memory<|Read latest version and permissions/);
});

test('conflict review shows old and latest versions without overwriting the draft or auto-submitting', () => {
  const html = page({
    ...model,
    phase: 'reviewing',
    intent: 'edit',
    record: memory,
    latest: { ...memory, version: 2, content: 'Latest remote body' },
    draft: { title: 'My draft', content: 'My body' },
  });
  assert.match(html, /Original body/);
  assert.match(html, /Latest remote body/);
  assert.match(html, /My body/);
  assert.match(html, /draft has not been replaced/);
  assert.match(html, />Review using the latest revision</);
  assert.doesNotMatch(html, />Save memory</);
});

test('deletion explicitly confirms the displayed version and unavailable object never becomes acceptance', () => {
  const html = page({ ...model, phase: 'deleting', intent: 'delete', record: memory });
  assert.match(html, /Confirm after reviewing its current content/);
  assert.match(html, />Confirm deletion</);
  assert.match(html, /Revision<\/dt><dd>1/);
  const absent = page({
    ...model,
    phase: 'error',
    intent: 'delete',
    record: memory,
    error: 'notFound',
  });
  assert.match(absent, /absence does not confirm a previous command succeeded/);
  assert.doesNotMatch(absent, /server confirmed/);
});

test('cloud route requires matching binding and fails closed without exposing native surfaces', () => {
  const props = { context: { tenantId: 'tenant-1', projectId: 'project-1' } };
  const absent = render(h(CloudMemoryRouteSurface, props));
  assert.match(absent, /not available for the current trusted context/);
  const binding = {
    authority: {
      scope: { ...scope, projectId: 'other' },
      actorId: 'actor-1',
      sessionId: 'session-1',
      contextRevision: 7,
      generationDigest: 'generation-1',
      available: true,
      allowedActions: ['list', 'view'],
    },
    listClient: {
      load: () => {
        throw Error('must not read');
      },
    },
    client: {
      execute: () => {
        throw Error('must not write');
      },
    },
  };
  const wrong = render(
    h(CloudMemoryRouteContextProvider, { value: binding }, h(CloudMemoryRouteSurface, props)),
  );
  assert.match(wrong, /not available for the current trusted context/);
  assert.doesNotMatch(wrong, /Local memories|Synchronization|indexing/);
});
