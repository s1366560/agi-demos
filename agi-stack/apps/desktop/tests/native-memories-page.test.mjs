import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { memory, nativeScope, projectScope } from './nativeKnowledgeFixtures.mjs';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const root = '/tmp/agistack-desktop-test-dist/src';
const { I18nProvider } = require(`${root}/i18n.js`);
const { NativeMemoriesPage } = require(`${root}/features/project-knowledge/NativeMemoriesPage.js`);
const { createProjectMemoriesRouteModuleLoader } = require(
  `${root}/features/project-knowledge/projectMemoriesRouteModule.js`,
);
const { NativeMemoriesRouteProvider } = require(`${root}/plugins/NativeMemoriesRouteProvider.js`);
const { DesktopRendererGenerationProviderV2 } = require(
  `${root}/plugins/desktopRendererGenerationContextV2.js`,
);
const { NativeMemoriesRouteContextProvider, useNativeMemoriesRouteBinding } = require(
  `${root}/features/project-knowledge/NativeMemoriesRouteContext.js`,
);
const h = React.createElement;
const render = (element) => renderToStaticMarkup(h(I18nProvider, null, element));
const noop = () => {};
const controller = {
  create: noop,
  open: noop,
  save: noop,
  close: noop,
  reload: noop,
  confirmDelete: noop,
  retryWrite: noop,
  setDraft: noop,
};
const list = {
  routeId: 'project-project-memories',
  state: 'ready',
  scope: projectScope,
  reasonCode: null,
  retryVisible: false,
  allowedActions: ['view', 'list', 'create', 'update', 'delete'],
  items: [{ id: memory.id, title: memory.title, detail: memory.content, kind: 'unavailable' }],
  total: 1,
};
const editor = {
  phase: 'idle',
  allowedActions: ['view', 'list'],
  record: null,
  draft: null,
  notice: null,
  error: null,
};
const page = (model) =>
  render(
    h(NativeMemoriesPage, { list, editor: model, controller, onReload: noop, onPageChange: noop }),
  );

test('native page ignores list/RPC action claims and exposes only current declared actions', () => {
  const html = page(editor);
  assert.match(html, /View memory/);
  for (const text of ['New memory', 'Edit memory', 'Delete memory'])
    assert.doesNotMatch(html, new RegExp(text));
  const unavailable = page({ ...editor, phase: 'unavailable', allowedActions: [] });
  assert.match(unavailable, /Local memories are not available/);
  assert.doesNotMatch(unavailable, /<button/);
  assert.doesNotMatch(unavailable, new RegExp(`<p>${memory.content}</p>`));
});

test('unknown writes disable editing and competing actions while preserving explicit retry', () => {
  const html = page({
    ...editor,
    phase: 'uncertain',
    allowedActions: list.allowedActions,
    draft: { title: 'Pending', content: 'Possibly saved' },
    error: 'uncertain',
  });
  assert.match(html, /<fieldset disabled=""/);
  assert.match(html, /Retry the same request/);
  assert.match(html, /Possibly saved/);
  assert.doesNotMatch(html, /type="submit"/);
  assert.doesNotMatch(html, />Close<|>Delete</);
  assert.match(html, /disabled="">New memory/);
});

test('delete confirmation shows the fetched record and revision before the destructive action', () => {
  const html = page({
    ...editor,
    phase: 'confirming_delete',
    allowedActions: list.allowedActions,
    record: memory,
  });
  assert.match(html, /Delete this memory\?/);
  assert.match(html, new RegExp(`<dd>${memory.version}</dd>`));
  assert.match(html, /<button type="button">Delete<\/button>/);
  assert.match(
    page({ ...editor, notice: 'accepted' }),
    /Extraction, indexing and synchronization may still be pending/,
  );
});

const config = {
  mode: 'local',
  apiBaseUrl: 'http://127.0.0.1:43117',
  apiKey: 'test-identity',
  localApiToken: 'test-launch',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  deviceAuthorizationBaseUrl: '',
  workspaceId: '',
  workspaceRoot: '',
};
const auth = {
  status: 'signed_in',
  credentialKind: 'local',
  user: { user_id: 'user-1' },
  session: { session_id: 'session-1' },
  context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 7 },
};
const generation = {
  meta: { digest: 'renderer-digest', status: 'ready' },
  state: { authority: {} },
  actions: {
    acquireServiceOperationLease: () => {
      throw new Error('must not invoke RPC');
    },
  },
};
const capability = {
  scope: { tenant_id: 'tenant-1', project_id: 'project-1' },
  authority_revision: 7,
  availability: 'available',
  provenance: 'observed',
  authority_source: 'sidecar',
  allowed_actions: ['view', 'list'],
};
function Capture() {
  const binding = useNativeMemoriesRouteBinding();
  return h('pre', null, JSON.stringify({ keys: Object.keys(binding), ...binding.authority }));
}
function capture({ cap = capability, identity = auth, gen = generation } = {}) {
  const content = h(
    NativeMemoriesRouteProvider,
    {
      config,
      auth: identity,
      capabilitySnapshot: { capabilities: { 'project-project-memories': cap } },
    },
    h(Capture),
  );
  return render(gen ? h(DesktopRendererGenerationProviderV2, { value: gen }, content) : content);
}

test('production provider forwards declared scope actions, never credentials or inferred write access', () => {
  const html = capture();
  assert.match(html, /&quot;available&quot;:true/);
  assert.match(html, /&quot;allowedActions&quot;:\[&quot;view&quot;,&quot;list&quot;\]/);
  assert.doesNotMatch(html, /test-identity|test-launch|apiKey|localApiToken|apiBaseUrl/);
  for (const options of [
    { cap: { ...capability, availability: 'unavailable', allowed_actions: ['create'] } },
    { cap: { ...capability, provenance: 'declared' } },
    { gen: null },
    { cap: { ...capability, authority_revision: 6 } },
    { cap: { ...capability, scope: { tenant_id: 'other', project_id: 'project-1' } } },
    { identity: { ...auth, status: 'signed_out' } },
    { identity: { ...auth, session: null } },
  ]) {
    const denied = capture(options);
    assert.match(denied, /&quot;available&quot;:false/);
    assert.match(denied, /&quot;allowedActions&quot;:\[\]/);
  }
});

test('Memories loader selects the dedicated local surface and preserves the cloud loader', async () => {
  const cloudModel = { ...list, scope: { ...projectScope, authority: 'cloud' }, items: [] };
  let cloudBindings = 0;
  const module = await createProjectMemoriesRouteModuleLoader({
    createBinding: () => {
      cloudBindings += 1;
      return {
        scope: cloudModel.scope,
        controller: {
          getSnapshot: () => cloudModel,
          subscribe: () => noop,
          load: async () => {},
          stop: noop,
          retry: async () => {},
        },
      };
    },
  })();
  const props = { module, context: { tenantId: 'tenant-1', projectId: 'project-1' } };
  const cloud = render(h(module.Surface, props));
  assert.match(cloud, /data-authority="cloud"/);
  assert.equal(cloudBindings, 1);
  const binding = {
    authority: {
      scope: projectScope,
      userId: 'user-1',
      sessionId: 'session-1',
      contextRevision: nativeScope.context_revision,
      generationDigest: 'digest',
      available: true,
      allowedActions: ['create'],
    },
    client: { execute: () => assert.fail('SSR must not invoke mutation') },
    listClient: { load: () => assert.fail('SSR must not invoke list') },
  };
  const local = render(
    h(NativeMemoriesRouteContextProvider, { value: binding }, h(module.Surface, props)),
  );
  assert.match(local, /New memory/);
  assert.equal(cloudBindings, 1);
  const wrongScope = render(
    h(
      NativeMemoriesRouteContextProvider,
      { value: binding },
      h(module.Surface, { ...props, context: { tenantId: 'tenant-1', projectId: 'other' } }),
    ),
  );
  assert.match(wrongScope, /Local memories are not available/);
});
