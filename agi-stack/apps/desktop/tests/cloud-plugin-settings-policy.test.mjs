import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const root = '/tmp/agistack-desktop-test-dist';
const { executeVaultBoundCloudRequest } = require(
  `${root}/apps/desktop/electron/main/cloudRequestPolicy.js`,
);
const { createMarketplaceClient } = require(`${root}/packages/plugin-marketplace-ui/src/client.js`);
const { createPluginInstanceClientV2 } = require(`${root}/src/api/pluginInstanceClientV2.js`);
const scope = { tenant_id: 'tenant-1', project_id: 'project-1' };
const prefix = '/api/v1/plugin-marketplace/v3';
function harness(status = 200) {
  const requests = [];
  return {
    requests,
    dependencies: {
      async loadTrustedSession() {
        return {
          version: 1,
          api_base_url: 'https://cloud.memstack.test',
          runtime_mode: 'cloud',
          credential_kind: 'cloud_bearer',
          credential: 'test-only-vault-token',
          expires_at: null,
        };
      },
      async fetch(url, init) {
        const path = new URL(url).pathname;
        requests.push({
          path,
          method: init.method,
          body: init.body && JSON.parse(init.body),
        });
        const context = path === '/api/v1/workspace-context';
        return new Response(
          JSON.stringify(
            context
              ? { context: { ...scope, revision: 1 } }
              : { scope, revision: 1, instances: [], items: [] },
          ),
          {
            status: context ? 200 : status,
            headers: { 'Content-Type': 'application/json' },
          },
        );
      },
    },
  };
}
test('all declared cloud marketplace and instance client operations reach the scoped API', async () => {
  const h = harness();
  const transport = async (path, options) =>
    (
      await executeVaultBoundCloudRequest(
        {
          path,
          method: options.method ?? 'GET',
          ...(options.body ? { body: options.body } : {}),
        },
        h.dependencies,
      )
    ).body;
  const client = createMarketplaceClient(transport, scope, true);
  const plugin = { id: 'plugin-1', source_id: 'source-1', version: '1.0.0' };
  const preflight = { id: 'preflight-1', permissions: ['tools.execute'] };
  const installation = { id: 'installation-1' };
  await client.catalog();
  await client.sources();
  await client.installations();
  await client.cache();
  await client.cleanupCache('key-cleanup');
  await client.addSource({
    name: 'Registry',
    kind: 'https',
    location: 'https://registry.example/manifest.json',
    trusted: false,
  });
  await client.removeSource('source-1');
  await client.preflight(plugin);
  await client.install(preflight, 'key-install');
  for (const action of ['enable', 'disable', 'uninstall', 'verify'])
    await client.action(installation, action, {}, `key-${action}`);
  await client.action(
    installation,
    'update',
    { preflight_id: preflight.id, approved_permissions: [] },
    'key-update',
  );
  await client.action(
    installation,
    'configure',
    { credentials: { EXAMPLE_TOKEN: 'test-only-credential' } },
    'key-configure',
  );
  await client.oauthStatus(installation.id, 'server-1');
  await client.oauthAction(
    installation.id,
    'server-1',
    'start',
    {
      client_id: 'client',
      client_metadata_url: 'https://example.com/client.json',
    },
    'key-oauth',
  );
  await client.oauthAction(installation.id, 'server-1', 'cancel', {}, 'key-cancel');
  await client.oauthAction(installation.id, 'server-1', 'disconnect', {}, 'key-disconnect');
  const instances = createPluginInstanceClientV2(
    { mode: 'cloud', tenantId: scope.tenant_id, projectId: scope.project_id },
    transport,
  );
  await instances.list();
  await instances.apply(1, [
    { entry_id: 'entry-1', enabled: false },
    {
      entry_id: 'entry-2',
      config: {},
      replacement: {
        plugin_id: 'plugin-2',
        module_ref: 'builtin://replacement',
      },
    },
  ]);
  assert.equal(h.requests.filter(({ path }) => path !== '/api/v1/workspace-context').length, 21);
  assert.equal(h.requests.filter(({ path }) => path === '/api/v1/workspace-context').length, 21);
  assert.equal(
    h.requests.some(({ path }) => path === `${prefix}/catalog/scoped`),
    true,
  );
});
test('the production desktop Cloud client selects the scoped catalog through the native vault broker', async () => {
  const { DesktopApiClient } = require(`${root}/src/api/client.js`);
  const previousWindow = globalThis.window;
  const h = harness();
  try {
    globalThis.window = {
      __MEMSTACK_DESKTOP__: {
        runtime: 'electron',
        core: {
          invoke: async (command, args) => {
            assert.equal(command, 'cloud_request');
            return executeVaultBoundCloudRequest(args.request, h.dependencies);
          },
        },
      },
    };
    const client = new DesktopApiClient({
      mode: 'cloud',
      apiKey: '',
      apiBaseUrl: 'https://cloud.memstack.test',
      tenantId: scope.tenant_id,
      projectId: scope.project_id,
    });
    await client.pluginMarketplaceV3().catalog();
    await client.pluginInstancesV2().list();
    assert.deepEqual(
      h.requests.filter(({ path }) => path !== '/api/v1/workspace-context').map(({ path }) => path),
      [`${prefix}/catalog/scoped`, '/api/v1/platform-plugins/v2/instances'],
    );
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
});
test('cloud plugin settings reject malformed, extra, unscoped, and undeclared requests before network', async () => {
  const query = '?tenant_id=tenant-1&project_id=project-1';
  const post = { ...scope, idempotency_key: 'key' };
  const requests = [
    { path: `${prefix}/catalog${query}` },
    { path: `${prefix}/catalog/scoped` },
    { path: `${prefix}/sources${query}&tenant_id=tenant-1` },
    { path: `${prefix}/installations${query}&extra=true` },
    { path: `${prefix}/jobs/job${query}` },
    {
      path: `${prefix}/sources`,
      method: 'POST',
      body: {
        ...scope,
        name: 'Local',
        kind: 'local',
        location: '/tmp/private',
        trusted: false,
      },
    },
    {
      path: `${prefix}/installations/id/disable?tenant_id=tenant-1`,
      method: 'POST',
      body: post,
    },
    { path: `${prefix}/installations/id/delete`, method: 'POST', body: post },
    { path: `${prefix}/installations/id/disable`, method: 'PUT', body: post },
    {
      path: `${prefix}/installations/id/disable`,
      method: 'POST',
      body: { ...post, arbitrary: true },
    },
    { path: `${prefix}/installations/id/update`, method: 'POST', body: post },
    {
      path: `${prefix}/installations`,
      method: 'POST',
      body: {
        ...post,
        preflight_id: 'preflight',
        approved_permissions: 'tools.execute',
      },
    },
    {
      path: `${prefix}/installations/id/configure`,
      method: 'POST',
      body: { ...post, credentials: { token: 42 } },
    },
    {
      path: `${prefix}/installations/id/oauth/server/cancel`,
      method: 'POST',
      body: { ...post, client_id: 'unexpected' },
    },
    {
      path: `${prefix}/installations/%2Fadmin/oauth/server/start`,
      method: 'POST',
      body: post,
    },
    {
      path: '/api/v1/platform-plugins/v2/instances/apply',
      method: 'POST',
      body: {
        ...scope,
        expected_revision: 0,
        changes: [{ entry_id: 'a', enabled: false }],
      },
    },
    {
      path: '/api/v1/platform-plugins/v2/instances/apply',
      method: 'POST',
      body: {
        ...scope,
        expected_revision: 1,
        changes: [{ entry_id: 'a', enabled: 'false' }],
      },
    },
    {
      path: '/api/v1/platform-plugins/v2/instances/apply',
      method: 'POST',
      body: {
        ...scope,
        expected_revision: 1,
        changes: [
          {
            entry_id: 'a',
            replacement: { plugin_id: 'p', module_ref: 'm', arbitrary: true },
          },
        ],
      },
    },
  ];
  for (const request of requests) {
    const h = harness();
    await assert.rejects(
      executeVaultBoundCloudRequest({ method: 'GET', ...request }, h.dependencies),
      /endpoint is not allowed/,
      request.path,
    );
    assert.equal(h.requests.length, 0, request.path);
  }
});
test('cloud plugin scope drift fails before mutations and server denial remains authoritative', async () => {
  for (const body of [
    { tenant_id: 'other', project_id: 'project-1' },
    { tenant_id: 'tenant-1', project_id: 'other' },
  ]) {
    const h = harness();
    await assert.rejects(
      executeVaultBoundCloudRequest(
        {
          path: `${prefix}/installations/id/disable`,
          method: 'POST',
          body: { ...body, idempotency_key: 'key' },
        },
        h.dependencies,
      ),
      /scope mismatch/,
    );
    assert.deepEqual(
      h.requests.map(({ path }) => path),
      ['/api/v1/workspace-context'],
    );
  }
  const denied = harness(403);
  assert.equal(
    (
      await executeVaultBoundCloudRequest(
        {
          path: `${prefix}/installations/id/disable`,
          method: 'POST',
          body: { ...scope, idempotency_key: 'key' },
        },
        denied.dependencies,
      )
    ).status,
    403,
  );
});
