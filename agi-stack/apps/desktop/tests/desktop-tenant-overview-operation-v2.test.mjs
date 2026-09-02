import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopTenantOverviewAuthorityUnavailableErrorV2,
  createDesktopTenantOverviewOperationsV2,
  withDesktopTenantOverviewAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopTenantOverviewAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46941',
    apiKey: 'tenant-overview-secret',
    localApiToken: 'tenant-overview-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: '',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

function scope(overrides = {}) {
  return { authority: 'local', tenantId: 'tenant-1', ...overrides };
}

function snapshot(overrides = {}) {
  return {
    scope: scope(),
    authority: 'local',
    availability: 'degraded',
    reasonCode: 'local_tenant_overview_memory_projection_unavailable',
    serviceVersion: '0.1.0',
    contractVersion: '3.0.0',
    allowedActions: ['view'],
    authorityRevision: 7,
    tenantInfo: {
      organizationId: '#TEN-1',
      plan: 'Local',
      region: { availability: 'not_applicable', reasonCode: 'region_na', value: null },
      nextBillingDate: {
        availability: 'not_applicable',
        reasonCode: 'billing_na',
        value: null,
      },
    },
    storage: { availability: 'unavailable', reasonCode: 'storage_na', value: null },
    projects: {
      availability: 'available',
      reasonCode: null,
      active: 0,
      newThisWeek: 0,
      value: [],
    },
    members: {
      availability: 'available',
      reasonCode: null,
      value: { total: 1, newAdded: 0 },
    },
    memoryHistory: { availability: 'unavailable', reasonCode: 'history_na', value: [] },
    ...overrides,
  };
}

function serviceFixture(received, result = snapshot()) {
  return Object.freeze({
    bindOperation(config, operationScope) {
      received.push({ type: 'bind', config, scope: operationScope });
      return Object.freeze({
        async load(signal) {
          received.push({ type: 'load', signal });
          return result;
        },
      });
    },
  });
}

function acceptedActions(service, digest, lifecycle = []) {
  return {
    acquireServiceOperationLease: async (request) => {
      lifecycle.push({ type: 'acquire', digest, request });
      let released = false;
      return {
        status: 'accepted',
        digest,
        useService(operation) {
          if (released) throw new Error('lease_released');
          return operation(service);
        },
        async release() {
          if (released) return;
          released = true;
          lifecycle.push({ type: 'release', digest });
        },
      };
    },
  };
}

test('operation freezes tenant identity before acquiring one tenant lease', async () => {
  const lifecycle = [];
  const received = [];
  const controller = new AbortController();
  const config = runtimeConfig();
  const operationScope = scope();
  const operations = createDesktopTenantOverviewOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-a', lifecycle),
  );

  const pending = operations.loadTenantOverview({
    config,
    scope: operationScope,
    signal: controller.signal,
  });
  config.tenantId = 'tenant-mutated';
  operationScope.tenantId = 'tenant-mutated';
  const result = await pending;

  assert.deepEqual(lifecycle, [
    {
      type: 'acquire',
      digest: 'digest-a',
      request: {
        service: 'service:desktop-renderer.tenant-overview-authority',
        version: '1.0.0',
        scope: { kind: 'tenant', tenant_id: 'tenant-1' },
      },
    },
    { type: 'release', digest: 'digest-a' },
  ]);
  assert.equal(received[0].config.tenantId, 'tenant-1');
  assert.deepEqual(received[0].scope, { authority: 'local', tenantId: 'tenant-1' });
  assert.equal(received[1].signal, controller.signal);
  assert.equal(Object.isFrozen(result), true);
  assert.equal(Object.isFrozen(result.tenantInfo), true);
  assert.equal(Object.isFrozen(result.allowedActions), true);
});

test('invalid scope fails before acquisition and missing generation actions fail closed', async () => {
  let acquisitions = 0;
  const operations = createDesktopTenantOverviewOperationsV2(() => ({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      assert.fail('invalid input must not acquire a lease');
    },
  }));

  assert.throws(
    () =>
      operations.loadTenantOverview({
        config: runtimeConfig(),
        scope: scope({ tenantId: 'tenant-other' }),
      }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_tenant_overview_operation_input_invalid',
  );
  assert.equal(acquisitions, 0);
  assert.throws(
    () =>
      createDesktopTenantOverviewOperationsV2(() => null).loadTenantOverview({
        config: runtimeConfig(),
        scope: scope(),
      }),
    (error) =>
      error instanceof DesktopTenantOverviewAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
});

test('escaped authority is revoked and the primary error wins over release failure', async () => {
  let escaped;
  const actions = acceptedActions(serviceFixture([]), 'digest-a');
  await withDesktopTenantOverviewAuthorityOperationV2(
    actions,
    { config: runtimeConfig(), scope: scope() },
    (authority) => {
      escaped = authority;
      return authority.load();
    },
  );
  await assert.rejects(
    escaped.load(),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_tenant_overview_operation_released',
  );

  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  const failingActions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'digest-failure',
      useService: (operation) => operation(serviceFixture([], snapshot())),
      release: async () => {
        throw release;
      },
    }),
  };
  await assert.rejects(
    withDesktopTenantOverviewAuthorityOperationV2(
      failingActions,
      { config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      },
    ),
    (error) => error === primary,
  );
});

test('old request stays pinned while a new request uses the replacement generation', async () => {
  let actions = acceptedActions(serviceFixture([], snapshot({ serviceVersion: 'old' })), 'old');
  let releaseOld;
  const gate = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const oldService = Object.freeze({
    bindOperation() {
      return Object.freeze({
        async load() {
          await gate;
          return snapshot({ serviceVersion: 'old' });
        },
      });
    },
  });
  actions = acceptedActions(oldService, 'old');
  const operations = createDesktopTenantOverviewOperationsV2(() => actions);
  const oldRequest = operations.loadTenantOverview({ config: runtimeConfig(), scope: scope() });
  actions = acceptedActions(
    serviceFixture([], snapshot({ serviceVersion: 'new' })),
    'new',
  );
  const newRequest = operations.loadTenantOverview({ config: runtimeConfig(), scope: scope() });
  releaseOld();

  assert.equal((await oldRequest).serviceVersion, 'old');
  assert.equal((await newRequest).serviceVersion, 'new');
});
