import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const {
  DESKTOP_BACKEND_STORES_AUTHORITY_SERVICE_V2,
  DESKTOP_BACKEND_STORES_AUTHORITY_VERSION_V2,
  createDesktopBackendStoresOperationsV2,
  withDesktopBackendStoresAuthorityOperationV2,
} = require(`${ROOT}/src/plugins/desktopBackendStoresAuthorityModuleV2.js`);
const { createDesktopBackendStoresHttpAuthorityV2 } = require(
  `${ROOT}/src/plugins/desktopBackendStoresHttpProjectionV2.js`,
);
const { DEFAULT_CONFIG } = require(`${ROOT}/src/types.js`);

const config = (overrides = {}) => ({
  ...DEFAULT_CONFIG,
  apiBaseUrl: 'https://cloud.test',
  deviceAuthorizationBaseUrl: 'https://cloud.test',
  apiKey: 'session',
  localApiToken: 'launch',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  workspaceRoot: '',
  mode: 'cloud',
  ...overrides,
});
const scope = (authority = 'cloud') => ({ authority, tenantId: 'tenant-1' });
const store = (id = 'store-1') => ({
  id,
  tenantId: 'tenant-1',
  name: 'Store',
  engineType: 'neo4j',
  status: 'ready',
  healthStatus: null,
  detectedVersion: null,
  connectionConfig: {},
  indexConfig: {},
  createdAt: null,
  updatedAt: null,
  source: 'user',
  readonly: false,
});
const snapshot = () => ({
  scope: scope(),
  scopeRevision: 1,
  authority: 'cloud',
  availability: 'available',
  reasonCode: null,
  contractVersion: '4.0.0',
  allowedActions: ['view'],
  data: {
    scopeRevision: 1,
    membershipRole: 'admin',
    graph: { stores: [], types: [] },
    retrieval: { stores: [], types: [] },
  },
  membershipRole: 'admin',
  graph: { stores: [], types: [] },
  retrieval: { stores: [], types: [] },
});

function service(events, overrides = {}) {
  return Object.freeze({
    bindOperation(operationConfig, operationScope) {
      events.push(['bind', operationConfig, operationScope]);
      return Object.freeze({
        async load(options) {
          events.push(['load', options]);
          return overrides.load?.() ?? snapshot();
        },
        async create(plane, input, options) {
          events.push(['create', plane, input, options]);
          return store('created');
        },
        async update(plane, id, input, options) {
          events.push(['update', plane, id, input, options]);
          return store(id);
        },
        async remove(plane, id, options) {
          events.push(['remove', plane, id, options]);
        },
        async testDraft(plane, input, options) {
          events.push(['testDraft', plane, input, options]);
          return { success: true, version: '1', error: null };
        },
        async testExisting(plane, id, options) {
          events.push(['testExisting', plane, id, options]);
          return { success: true, version: '1', error: null };
        },
        async probe(options) {
          events.push(['probe', options]);
          return {
            availability: 'available',
            reasonCode: null,
            allowedActions: ['view'],
            authorityRevision: 1,
          };
        },
      });
    },
  });
}
function actions(authorityService, lifecycle = [], releaseError = null) {
  return {
    async acquireServiceOperationLease(request) {
      lifecycle.push(['acquire', request]);
      return {
        status: 'accepted',
        digest: 'digest',
        useService: (operation) => operation(authorityService),
        async release() {
          lifecycle.push(['release']);
          if (releaseError) throw releaseError;
        },
      };
    },
  };
}

test('all seven operations acquire exact tenant leases and freeze mutable inputs', async () => {
  const events = [];
  const lifecycle = [];
  const operations = createDesktopBackendStoresOperationsV2(() =>
    actions(service(events), lifecycle),
  );
  const runtime = config();
  const operationScope = scope();
  const createInput = {
    name: 'main',
    engineType: 'neo4j',
    connectionConfig: { password: 'secret' },
  };
  const pending = operations.createBackendStore({
    config: runtime,
    scope: operationScope,
    plane: 'graph',
    input: createInput,
  });
  runtime.tenantId = 'mutated';
  operationScope.tenantId = 'mutated';
  createInput.connectionConfig.password = 'mutated';
  await pending;
  await operations.loadBackendStores({ config: config(), scope: scope() });
  await operations.updateBackendStore({
    config: config(),
    scope: scope(),
    plane: 'graph',
    storeId: 'store-1',
    input: { name: 'next' },
  });
  await operations.removeBackendStore({
    config: config(),
    scope: scope(),
    plane: 'graph',
    storeId: 'store-1',
  });
  await operations.testBackendStoreDraft({
    config: config(),
    scope: scope(),
    plane: 'retrieval',
    input: { engineType: 'pg', connectionConfig: {} },
  });
  await operations.testBackendStoreExisting({
    config: config(),
    scope: scope(),
    plane: 'retrieval',
    storeId: 'store-1',
  });
  await operations.probeBackendStores({ config: config(), scope: scope() });
  assert.equal(events[0][1].tenantId, 'tenant-1');
  assert.equal(events[1][2].connectionConfig.password, 'secret');
  assert.equal(lifecycle.length, 14);
  for (const [kind, request] of lifecycle.filter(([kind]) => kind === 'acquire'))
    assert.deepEqual(
      [kind, request],
      [
        'acquire',
        {
          service: DESKTOP_BACKEND_STORES_AUTHORITY_SERVICE_V2,
          version: DESKTOP_BACKEND_STORES_AUTHORITY_VERSION_V2,
          scope: { kind: 'tenant', tenant_id: 'tenant-1' },
        },
      ],
    );
});

test('masked secrets and malformed inputs reject before lease acquisition', async () => {
  let acquisitions = 0;
  const operations = createDesktopBackendStoresOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      throw new Error('must_not_acquire');
    },
  }));
  assert.throws(
    () =>
      operations.createBackendStore({
        config: config(),
        scope: scope(),
        plane: 'graph',
        input: {
          name: 'main',
          engineType: 'neo4j',
          connectionConfig: { nested: { password: '***' } },
        },
      }),
    (error) => error.code === 'backend_stores_masked_secret_rejected',
  );
  assert.throws(
    () =>
      operations.updateBackendStore({
        config: config(),
        scope: scope(),
        plane: 'graph',
        storeId: 'bad/id',
        input: { name: 'next' },
      }),
    (error) => error.code === 'desktop_backend_stores_operation_input_invalid',
  );
  assert.equal(acquisitions, 0);
});

test('HMR pins in-flight work and revokes escaped authority after release', async () => {
  let resolveLoad;
  const oldEvents = [];
  const newEvents = [];
  let current = actions(
    service(oldEvents, {
      load: () =>
        new Promise((resolve) => {
          resolveLoad = resolve;
        }),
    }),
  );
  const operations = createDesktopBackendStoresOperationsV2(() => current);
  const first = operations.loadBackendStores({
    config: config(),
    scope: scope(),
  });
  await waitFor(() => resolveLoad);
  current = actions(service(newEvents));
  resolveLoad(snapshot());
  await first;
  await operations.loadBackendStores({ config: config(), scope: scope() });
  assert.equal(
    oldEvents.some(([kind]) => kind === 'load'),
    true,
  );
  assert.equal(
    newEvents.some(([kind]) => kind === 'load'),
    true,
  );
  let escaped;
  await withDesktopBackendStoresAuthorityOperationV2(
    actions(service([])),
    { kind: 'load', config: config(), scope: scope() },
    async (authority) => {
      escaped = authority;
      return authority.load();
    },
  );
  await assert.rejects(
    escaped.load(),
    (error) => error.code === 'desktop_backend_stores_operation_released',
  );
});

test('operation error outranks release error and successful release error propagates', async () => {
  const primary = new Error('load_failed');
  await assert.rejects(
    createDesktopBackendStoresOperationsV2(() =>
      actions(
        service([], {
          load: () => {
            throw primary;
          },
        }),
        [],
        new Error('release_failed'),
      ),
    ).loadBackendStores({ config: config(), scope: scope() }),
    (error) => error === primary,
  );
  await assert.rejects(
    createDesktopBackendStoresOperationsV2(() =>
      actions(service([]), [], new Error('release_failed')),
    ).loadBackendStores({ config: config(), scope: scope() }),
    /release_failed/u,
  );
});

test('Local projection is structured cloud-only and performs zero broker or network work', async () => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      core: {
        invoke: async () => {
          calls += 1;
        },
      },
    },
  };
  globalThis.fetch = async () => {
    calls += 1;
    throw new Error('must_not_fetch');
  };
  try {
    const authority = createDesktopBackendStoresHttpAuthorityV2(
      config({ mode: 'local' }),
      scope('local'),
    );
    await assert.rejects(
      authority.load(),
      (error) =>
        error.status === 503 &&
        error.payload.reason_code === 'local_backend_stores_cloud_authority_unavailable',
    );
    assert.deepEqual(await authority.probe(), {
      availability: 'not_applicable',
      reasonCode: 'local_backend_stores_cloud_authority_unavailable',
      allowedActions: [],
      authorityRevision: null,
    });
    assert.equal(calls, 0);
  } finally {
    globalThis.window = originalWindow;
    globalThis.fetch = originalFetch;
  }
});

test('invalid service and response shapes fail closed', async () => {
  await assert.rejects(
    createDesktopBackendStoresOperationsV2(() =>
      actions({ bindOperation: () => ({ load: async () => ({}) }) }),
    ).loadBackendStores({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_backend_stores_service_invalid',
  );
  await assert.rejects(
    createDesktopBackendStoresOperationsV2(() =>
      actions(service([], { load: () => ({ authority: 'cloud' }) })),
    ).loadBackendStores({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_backend_stores_response_invalid',
  );
});

async function waitFor(predicate, attempts = 100) {
  for (let index = 0; index < attempts; index += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  assert.fail('condition_not_observed');
}
