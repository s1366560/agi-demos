import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopTenantAnalyticsAuthorityUnavailableErrorV2,
  createDesktopTenantAnalyticsOperationsV2,
  withDesktopTenantAnalyticsAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopTenantAnalyticsAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46941',
    apiKey: 'tenant-analytics-secret',
    localApiToken: 'tenant-analytics-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: '',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

function scope(overrides = {}) {
  return { authority: 'local', tenantId: 'tenant-1', period: '30d', ...overrides };
}

function field(value, overrides = {}) {
  return { availability: 'available', reasonCode: null, value, ...overrides };
}

function snapshot(overrides = {}) {
  return {
    scope: scope(),
    authority: 'local',
    availability: 'degraded',
    reasonCode: 'local_tenant_analytics_memory_projection_unavailable',
    serviceVersion: '0.1.0',
    contractVersion: '3.0.0',
    allowedActions: ['view', 'retry'],
    authorityRevision: 9,
    memoryGrowth: field([]),
    projectStorage: field([]),
    summary: {
      totalMemories: field(null, {
        availability: 'unavailable',
        reasonCode: 'memory_unavailable',
      }),
      totalStorageBytes: field(null, {
        availability: 'unavailable',
        reasonCode: 'storage_unavailable',
      }),
      totalProjects: field(1),
      periodDays: 30,
    },
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

test('operation freezes tenant and period before acquiring one tenant lease', async () => {
  const lifecycle = [];
  const received = [];
  const controller = new AbortController();
  const config = runtimeConfig();
  const operationScope = scope();
  const operations = createDesktopTenantAnalyticsOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-a', lifecycle),
  );

  const pending = operations.loadTenantAnalytics({
    config,
    scope: operationScope,
    signal: controller.signal,
  });
  config.tenantId = 'tenant-mutated';
  operationScope.period = '7d';
  const result = await pending;

  assert.deepEqual(lifecycle, [
    {
      type: 'acquire',
      digest: 'digest-a',
      request: {
        service: 'service:desktop-renderer.tenant-analytics-authority',
        version: '1.0.0',
        scope: { kind: 'tenant', tenant_id: 'tenant-1' },
      },
    },
    { type: 'release', digest: 'digest-a' },
  ]);
  assert.equal(received[0].config.tenantId, 'tenant-1');
  assert.deepEqual(received[0].scope, {
    authority: 'local',
    tenantId: 'tenant-1',
    period: '30d',
  });
  assert.equal(received[1].signal, controller.signal);
  assert.equal(Object.isFrozen(result), true);
  assert.equal(Object.isFrozen(result.summary), true);
  assert.equal(Object.isFrozen(result.allowedActions), true);
});

test('invalid scope fails before acquisition and missing generation actions fail closed', () => {
  let acquisitions = 0;
  const operations = createDesktopTenantAnalyticsOperationsV2(() => ({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      assert.fail('invalid input must not acquire a lease');
    },
  }));

  for (const invalidScope of [
    scope({ tenantId: 'tenant-other' }),
    scope({ authority: 'cloud' }),
    scope({ period: '14d' }),
    { ...scope(), extra: true },
  ]) {
    assert.throws(
      () =>
        operations.loadTenantAnalytics({
          config: runtimeConfig(),
          scope: invalidScope,
        }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_tenant_analytics_operation_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
  assert.throws(
    () =>
      createDesktopTenantAnalyticsOperationsV2(() => null).loadTenantAnalytics({
        config: runtimeConfig(),
        scope: scope(),
      }),
    (error) =>
      error instanceof DesktopTenantAnalyticsAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
});

test('escaped authority is revoked and primary failure wins over release failure', async () => {
  let escaped;
  await withDesktopTenantAnalyticsAuthorityOperationV2(
    acceptedActions(serviceFixture([]), 'digest-a'),
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
      error.code === 'desktop_tenant_analytics_operation_released',
  );

  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  const actions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'digest-failure',
      useService: (operation) => operation(serviceFixture([])),
      release: async () => {
        throw release;
      },
    }),
  };
  await assert.rejects(
    withDesktopTenantAnalyticsAuthorityOperationV2(
      actions,
      { config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      },
    ),
    (error) => error === primary,
  );
});

test('malformed nested service values retain the V2 service-contract error', async () => {
  const malformed = snapshot({
    summary: {
      ...snapshot().summary,
      totalProjects: field(-1),
    },
  });
  const operations = createDesktopTenantAnalyticsOperationsV2(() =>
    acceptedActions(serviceFixture([], malformed), 'digest-malformed'),
  );

  await assert.rejects(
    operations.loadTenantAnalytics({
      config: runtimeConfig(),
      scope: scope(),
    }),
    /desktop_tenant_analytics_service_contract_invalid/u,
  );
});

test('old request stays pinned while a new request uses the replacement generation', async () => {
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
  let actions = acceptedActions(oldService, 'old');
  const operations = createDesktopTenantAnalyticsOperationsV2(() => actions);
  const oldRequest = operations.loadTenantAnalytics({
    config: runtimeConfig(),
    scope: scope(),
  });
  actions = acceptedActions(
    serviceFixture([], snapshot({ serviceVersion: 'new' })),
    'new',
  );
  const newRequest = operations.loadTenantAnalytics({
    config: runtimeConfig(),
    scope: scope(),
  });
  releaseOld();

  assert.equal((await oldRequest).serviceVersion, 'old');
  assert.equal((await newRequest).serviceVersion, 'new');
});
