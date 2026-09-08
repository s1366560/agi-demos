import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const root = process.env.CLOUD_MEMORY_AUTHORITY_DIST ?? '/tmp/agistack-desktop-test-dist';
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { NativeMemoriesRouteProvider } = require(
  `${root}/src/plugins/NativeMemoriesRouteProvider.js`,
);
const { DesktopRendererGenerationProviderV2 } = require(
  `${root}/src/plugins/desktopRendererGenerationContextV2.js`,
);
const { useNativeMemoriesRouteBinding } = require(
  `${root}/src/features/project-knowledge/NativeMemoriesRouteContext.js`,
);
const { useCloudMemoryRouteBinding } = require(
  `${root}/src/features/project-knowledge/CloudMemoryRouteContext.js`,
);
const h = React.createElement;
const config = {
  apiBaseUrl: 'https://cloud.invalid',
  deviceAuthorizationBaseUrl: '',
  apiKey: 'fixture-secret',
  localApiToken: 'fixture-launch',
  tenantId: 'tenant',
  projectId: 'project',
  workspaceId: '',
  mode: 'cloud',
  workspaceRoot: '',
};
const auth = {
  status: 'signed_in',
  credentialKind: 'cloud',
  user: { user_id: 'actor' },
  session: { session_id: 'session' },
  context: { tenant_id: 'tenant', project_id: 'project', revision: 7 },
};
const cap = {
  scope: { tenant_id: 'tenant', project_id: 'project' },
  authority_revision: 7,
  availability: 'degraded',
  provenance: 'observed',
  authority_source: 'cloud_service',
  allowed_actions: ['view', 'list'],
};
const generation = {
  meta: { digest: 'digest', status: 'ready' },
  state: { authority: {} },
  actions: {
    acquireServiceOperationLease() {
      throw Error('no RPC in render');
    },
  },
};
function Capture() {
  const local = useNativeMemoriesRouteBinding();
  const cloud = useCloudMemoryRouteBinding();
  return h(
    'pre',
    null,
    JSON.stringify({
      local: local?.authority,
      cloud: cloud?.authority,
      processing: !!local?.processingClient,
      processingWrite: !!local?.processingCommandClient,
      cloudClient: !!cloud?.client,
    }),
  );
}
function render({
  mode = 'cloud',
  capability = cap,
  identity = auth,
  gen = generation,
  runtime = config,
} = {}) {
  const node = h(
    NativeMemoriesRouteProvider,
    {
      config: { ...runtime, mode },
      auth: identity,
      capabilitySnapshot: { capabilities: { 'project-project-memories': capability } },
    },
    h(Capture),
  );
  const html = renderToStaticMarkup(
    gen ? h(DesktopRendererGenerationProviderV2, { value: gen }, node) : node,
  );
  assert.doesNotMatch(html, /fixture-secret|fixture-launch|apiBaseUrl|localApiToken/);
  return JSON.parse(html.slice(5, -6).replaceAll('&quot;', '"'));
}
test('cloud Provider supplies scoped command client with read-only navigation actions', () => {
  const value = render();
  assert.equal(value.local.available, false);
  assert.equal(value.cloud.available, true);
  assert.equal(value.cloud.actorId, 'actor');
  assert.deepEqual(value.cloud.allowedActions, ['view', 'list']);
  assert.equal(value.cloudClient, true);
});
test('local Provider supplies query and command clients only under sidecar authority', () => {
  const value = render({ mode: 'local', capability: { ...cap, authority_source: 'sidecar' } });
  assert.equal(value.local.available, true);
  assert.equal(value.cloud.available, false);
  assert.equal(value.processing, true);
  assert.equal(value.processingWrite, true);
});
test('wrong source or identity and generation drift close both surfaces', () => {
  for (const input of [
    { capability: { ...cap, authority_source: 'renderer' } },
    { capability: { ...cap, provenance: 'declared' } },
    { capability: { ...cap, authority_revision: 6 } },
    { capability: { ...cap, scope: { tenant_id: 'tenant', project_id: 'other' } } },
    { identity: { ...auth, status: 'signed_out' } },
    { gen: null },
  ]) {
    const value = render(input);
    assert.equal(value.cloud.available, false);
    assert.equal(value.local.available, false);
  }
});

test('signed-out initial render needs no catalog configuration', () => {
  const value = render({
    runtime: { ...config, tenantId: '', projectId: '' },
    identity: { ...auth, status: 'signed_out' },
    gen: null,
  });
  assert.equal(value.local.available, false);
  assert.equal(value.cloud.available, false);
});
