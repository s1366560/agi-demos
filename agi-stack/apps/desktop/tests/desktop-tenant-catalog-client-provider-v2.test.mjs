import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopTenantCatalogClientProviderV2,
  DesktopTenantCatalogClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/' +
    'desktopTenantCatalogClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop tenant catalog client provider fails closed before publication', () => {
  const provider = createDesktopTenantCatalogClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopTenantCatalogClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_tenant_catalog_client_unpublished');
      assert.equal(error.message, 'desktop_tenant_catalog_client_unpublished');
      return true;
    },
  );
});

test('publications pin one-method tenant catalog clients to exact operation configs', async () => {
  const provider = createDesktopTenantCatalogClientProviderV2();
  const publicationConfig = runtimeConfig(
    'http://127.0.0.1:43911',
    'local',
    'publication-session',
    'publication-launch',
  );
  const publication = provider.publish({ config: publicationConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:43912',
    'local',
    'operation-session',
    'operation-launch',
  );
  const operationClient = publication.bindOperation(operationConfig);
  publicationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.localApiToken = 'mutated-launch';

  const cloud = provider.publish({
    config: runtimeConfig('https://cloud.example.test', 'cloud', '', ''),
  });
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const fetchCalls = [];
  const cloudCommands = [];
  const controller = new AbortController();
  globalThis.fetch = async (input, init) => {
    fetchCalls.push({ input: String(input), init });
    return json({
      tenants: [{ id: 'tenant-local', name: 'Local tenant' }],
      total: 1,
      page: 1,
      page_size: 100,
    });
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          cloudCommands.push({ command, args });
          return {
            status: 200,
            body: {
              tenants: [{ id: 'tenant-cloud', name: 'Cloud tenant' }],
              total: 1,
              page: 1,
              page_size: 100,
            },
          };
        },
      },
    },
  };

  try {
    assert.deepEqual(await operationClient.listTenants(controller.signal), [
      { id: 'tenant-local', name: 'Local tenant' },
    ]);
    assert.deepEqual(await cloud.client.listTenants(), [
      { id: 'tenant-cloud', name: 'Cloud tenant' },
    ]);

    assert.equal(Object.isFrozen(provider), true);
    assert.equal(Object.isFrozen(publication), true);
    assert.equal(Object.isFrozen(publication.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(Object.isFrozen(cloud), true);
    assert.notEqual(publication, cloud);
    assert.notEqual(publication.client, cloud.client);
    assert.equal(provider.resolve(), cloud);
    assert.deepEqual(Object.keys(publication.client), ['listTenants']);
    assert.deepEqual(Object.keys(operationClient), ['listTenants']);

    assert.equal(fetchCalls.length, 1);
    const localUrl = new URL(fetchCalls[0].input);
    assert.equal(localUrl.origin, 'http://127.0.0.1:43912');
    assert.equal(localUrl.pathname, '/api/v1/tenants');
    assert.equal(localUrl.searchParams.get('page'), '1');
    assert.equal(localUrl.searchParams.get('page_size'), '100');
    assert.equal(fetchCalls[0].init.signal, controller.signal);
    const localHeaders = new Headers(fetchCalls[0].init.headers);
    assert.equal(localHeaders.get('Authorization'), 'Bearer operation-session');
    assert.equal(localHeaders.get('X-Agistack-Launch'), 'operation-launch');

    assert.equal(cloudCommands.length, 1);
    assert.equal(cloudCommands[0].command, 'cloud_request');
    assert.deepEqual(cloudCommands[0].args.request, {
      path: '/api/v1/tenants?page=1&page_size=100',
      method: 'GET',
    });
    assert.equal(JSON.stringify(cloudCommands).includes('Bearer'), false);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('failed tenant catalog publication keeps the last-good binding', () => {
  const provider = createDesktopTenantCatalogClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_tenant_catalog_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_tenant_catalog_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function runtimeConfig(apiBaseUrl, mode, apiKey, localApiToken) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl,
    mode,
    apiKey,
    localApiToken,
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
  };
}

function json(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}
