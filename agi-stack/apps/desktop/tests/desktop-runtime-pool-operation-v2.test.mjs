import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopRuntimePoolAuthorityUnavailableErrorV2,
  createDesktopRuntimePoolOperationsV2,
  withDesktopRuntimePoolAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopRuntimePoolAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

const CLOUD_ACTIONS = Object.freeze([
  'view',
  'refresh',
  'toggle-auto-refresh',
  'list-instances',
  'search-current-page',
  'filter-by-tier',
  'paginate-instances',
  'pause-instance',
  'resume-instance',
  'terminate-instance',
  'retry-list-instances',
  'inspect-pool-status',
]);

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://memstack.test',
    deviceAuthorizationBaseUrl: 'https://memstack.test',
    apiKey: 'pool-secret',
    localApiToken: 'pool-launch',
    mode: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

function scope(authority = 'cloud', overrides = {}) {
  return { authority, tenantId: 'tenant-1', ...overrides };
}

function status(overrides = {}) {
  return {
    enabled: true,
    status: 'running',
    totalInstances: 1,
    hotInstances: 1,
    warmInstances: 0,
    coldInstances: 0,
    readyInstances: 1,
    executingInstances: 0,
    unhealthyInstances: 0,
    prewarmPool: null,
    resourceUsage: null,
    reasonCode: 'global_pool_capacity_not_available_in_tenant_scope',
    ...overrides,
  };
}

function instancePage(operationScope = scope(), overrides = {}) {
  return {
    instances: [
      {
        instanceKey: 'tenant-1:project-1:chat',
        tenantId: operationScope.tenantId,
        projectId: 'project-1',
        agentMode: 'chat',
        tier: 'hot',
        status: 'ready',
        createdAt: '2026-09-03T00:00:00Z',
        lastRequestAt: null,
        activeRequests: 0,
        totalRequests: 1,
        memoryUsedMb: 64,
        healthStatus: 'healthy',
      },
    ],
    total: 1,
    page: 1,
    pageSize: 20,
    ...overrides,
  };
}

function metrics(overrides = {}) {
  return {
    instances: {
      total: 1,
      byTier: { hot: 1, warm: 0, cold: 0 },
      byStatus: { ready: 1, executing: 0, unhealthy: 0 },
    },
    unhealthyCount: 0,
    prewarm: null,
    reasonCode: 'global_pool_capacity_not_available_in_tenant_scope',
    ...overrides,
  };
}

function capability(operationScope = scope(), authority = operationScope.authority) {
  return authority === 'local'
    ? {
        availability: 'not_applicable',
        reason_code: 'cloud_runtime_pool_not_applicable',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: {
          tenant_id: operationScope.tenantId,
          project_id: null,
          workspace_id: null,
          instance_id: null,
        },
        authority_revision: null,
      }
    : {
        availability: 'degraded',
        reason_code: 'global_pool_capacity_not_available_in_tenant_scope',
        service_version: '0.1.0',
        contract_version: '3.0.0',
        allowed_actions: [...CLOUD_ACTIONS],
        scope: {
          tenant_id: operationScope.tenantId,
          project_id: null,
          workspace_id: null,
          instance_id: null,
        },
        authority_revision: null,
      };
}

function serviceFixture(received, overrides = {}) {
  return Object.freeze({
    bindOperation(config, operationScope) {
      received.push({ type: 'bind', config, scope: operationScope });
      return Object.freeze({
        async getStatus(signal) {
          received.push({ type: 'getStatus', signal });
          return overrides.status ?? status();
        },
        async listInstances(query, signal) {
          received.push({ type: 'listInstances', query, signal });
          return (
            overrides.instances ??
            instancePage(operationScope, {
              page: query.page,
              pageSize: query.pageSize,
            })
          );
        },
        async getMetrics(signal) {
          received.push({ type: 'getMetrics', signal });
          return overrides.metrics ?? metrics();
        },
        async pauseInstance(instanceKey, signal) {
          received.push({ type: 'pauseInstance', instanceKey, signal });
          return overrides.pauseResult;
        },
        async resumeInstance(instanceKey, signal) {
          received.push({ type: 'resumeInstance', instanceKey, signal });
          return overrides.resumeResult;
        },
        async terminateInstance(instanceKey, graceful, signal) {
          received.push({
            type: 'terminateInstance',
            instanceKey,
            graceful,
            signal,
          });
          return overrides.terminateResult;
        },
        async probe(signal) {
          received.push({ type: 'probe', signal });
          return overrides.capability ?? capability(operationScope);
        },
      });
    },
  });
}

function acceptedActions(service, digest, lifecycle = [], releaseError = null) {
  return {
    async acquireServiceOperationLease(request) {
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
          if (releaseError) throw releaseError;
        },
      };
    },
  };
}

test('Runtime Pool operations freeze inputs before one exact tenant lease per call', async () => {
  const lifecycle = [];
  const received = [];
  const controller = new AbortController();
  const config = runtimeConfig();
  const operationScope = scope();
  const query = { tier: 'hot', status: 'ready', page: 2, pageSize: 25 };
  const operations = createDesktopRuntimePoolOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-cloud', lifecycle),
  );

  const pending = operations.listRuntimePoolInstances({
    config,
    scope: operationScope,
    query,
    signal: controller.signal,
  });
  config.tenantId = 'mutated';
  operationScope.tenantId = 'mutated';
  query.page = 9;
  const page = await pending;
  await operations.getRuntimePoolStatus({
    config: runtimeConfig(),
    scope: scope(),
  });
  await operations.getRuntimePoolMetrics({
    config: runtimeConfig(),
    scope: scope(),
  });
  await operations.pauseRuntimePoolInstance({
    config: runtimeConfig(),
    scope: scope(),
    instanceKey: 'tenant-1:project-1:chat',
  });
  await operations.resumeRuntimePoolInstance({
    config: runtimeConfig(),
    scope: scope(),
    instanceKey: 'tenant-1:project-1:chat',
  });
  await operations.terminateRuntimePoolInstance({
    config: runtimeConfig(),
    scope: scope(),
    instanceKey: 'tenant-1:project-1:chat',
    graceful: false,
  });
  await operations.probeRuntimePool({
    config: runtimeConfig(),
    scope: scope(),
  });

  assert.equal(page.page, 2);
  assert.deepEqual(received[1].query, {
    tier: 'hot',
    status: 'ready',
    page: 2,
    pageSize: 25,
  });
  assert.equal(received[1].signal, controller.signal);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(Object.isFrozen(received[0].scope), true);
  assert.equal(Object.isFrozen(received[1].query), true);
  assert.equal(received.find(({ type }) => type === 'terminateInstance').graceful, false);
  assert.equal(lifecycle.filter(({ type }) => type === 'acquire').length, 7);
  assert.equal(lifecycle.filter(({ type }) => type === 'release').length, 7);
  for (const event of lifecycle.filter(({ type }) => type === 'acquire')) {
    assert.deepEqual(event.request, {
      service: 'service:desktop-renderer.runtime-pool-authority',
      version: '1.0.0',
      scope: { kind: 'tenant', tenant_id: 'tenant-1' },
    });
  }
});

test('invalid scope, query, key, flag and signal fail before lease acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopRuntimePoolOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      assert.fail('invalid input must not acquire a lease');
    },
  }));
  const calls = [
    () =>
      operations.getRuntimePoolStatus({
        config: runtimeConfig(),
        scope: scope('local'),
      }),
    () =>
      operations.getRuntimePoolStatus({
        config: runtimeConfig(),
        scope: scope('cloud', { tenantId: ' tenant-1' }),
      }),
    () =>
      operations.listRuntimePoolInstances({
        config: runtimeConfig(),
        scope: scope(),
        query: { tier: 'semantic' },
      }),
    () =>
      operations.pauseRuntimePoolInstance({
        config: runtimeConfig(),
        scope: scope(),
        instanceKey: ' bad',
      }),
    () =>
      operations.terminateRuntimePoolInstance({
        config: runtimeConfig(),
        scope: scope(),
        instanceKey: 'key',
        graceful: 'yes',
      }),
    () =>
      operations.probeRuntimePool({
        config: runtimeConfig(),
        scope: scope(),
        signal: {},
      }),
  ];
  for (const call of calls) {
    assert.throws(
      call,
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_runtime_pool_operation_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
  assert.throws(
    () =>
      createDesktopRuntimePoolOperationsV2(() => null).getRuntimePoolStatus({
        config: runtimeConfig(),
        scope: scope(),
      }),
    (error) =>
      error instanceof DesktopRuntimePoolAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
});

test('lease rejection and malformed service, authority, read and mutation results fail closed', async () => {
  const rejected = createDesktopRuntimePoolOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return {
        status: 'rejected',
        reasonCode: 'missing_service',
        runtimeCode: 'missing_service',
      };
    },
  }));
  await assert.rejects(
    rejected.getRuntimePoolStatus({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof DesktopRuntimePoolAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'missing_service',
  );

  for (const service of [
    Object.freeze({ bindOperation: null }),
    Object.freeze({
      bindOperation: () => Object.freeze({ getStatus: async () => status() }),
    }),
  ]) {
    await assert.rejects(
      createDesktopRuntimePoolOperationsV2(() =>
        acceptedActions(service, 'invalid'),
      ).getRuntimePoolStatus({
        config: runtimeConfig(),
        scope: scope(),
      }),
      (error) =>
        error instanceof RuntimeV2Error && error.code === 'desktop_runtime_pool_service_invalid',
    );
  }

  const malformed = createDesktopRuntimePoolOperationsV2(() =>
    acceptedActions(
      serviceFixture([], {
        status: status({ totalInstances: -1 }),
        instances: instancePage(scope(), {
          instances: [{ tenantId: 'tenant-other' }],
        }),
        metrics: metrics({ unhealthyCount: -1 }),
        pauseResult: { success: true },
        capability: { ...capability(), authority_revision: 1 },
      }),
      'malformed',
    ),
  );
  for (const call of [
    () =>
      malformed.getRuntimePoolStatus({
        config: runtimeConfig(),
        scope: scope(),
      }),
    () =>
      malformed.listRuntimePoolInstances({
        config: runtimeConfig(),
        scope: scope(),
      }),
    () =>
      malformed.getRuntimePoolMetrics({
        config: runtimeConfig(),
        scope: scope(),
      }),
    () =>
      malformed.pauseRuntimePoolInstance({
        config: runtimeConfig(),
        scope: scope(),
        instanceKey: 'key',
      }),
    () => malformed.probeRuntimePool({ config: runtimeConfig(), scope: scope() }),
  ]) {
    await assert.rejects(
      call,
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_runtime_pool_service_contract_invalid',
    );
  }
});

test('escaped authority is revoked and primary operation failure wins over release failure', async () => {
  let escaped;
  await withDesktopRuntimePoolAuthorityOperationV2(
    acceptedActions(serviceFixture([]), 'digest-a'),
    { config: runtimeConfig(), scope: scope() },
    (authority) => {
      escaped = authority;
      return authority.getStatus();
    },
  );
  await assert.rejects(
    escaped.getStatus(),
    (error) =>
      error instanceof RuntimeV2Error && error.code === 'desktop_runtime_pool_operation_released',
  );

  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopRuntimePoolAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-failure', [], release),
      { config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  await assert.rejects(
    withDesktopRuntimePoolAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { config: runtimeConfig(), scope: scope() },
      (authority) => authority.getStatus(),
    ),
    (error) => error === release,
  );
});

test('old Runtime Pool request stays pinned while a later request uses the replacement generation', async () => {
  let releaseOld;
  const gate = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const oldService = serviceFixture([]);
  const gatedService = Object.freeze({
    bindOperation(...args) {
      const authority = oldService.bindOperation(...args);
      return Object.freeze({
        ...authority,
        async getStatus(signal) {
          await gate;
          await authority.getStatus(signal);
          return status({ status: 'old-generation' });
        },
      });
    },
  });
  let actions = acceptedActions(gatedService, 'old');
  const operations = createDesktopRuntimePoolOperationsV2(() => actions);
  const oldRequest = operations.getRuntimePoolStatus({
    config: runtimeConfig(),
    scope: scope(),
  });
  actions = acceptedActions(
    serviceFixture([], { status: status({ status: 'new-generation' }) }),
    'new',
  );
  const newRequest = operations.getRuntimePoolStatus({
    config: runtimeConfig(),
    scope: scope(),
  });
  releaseOld();

  assert.equal((await oldRequest).status, 'old-generation');
  assert.equal((await newRequest).status, 'new-generation');
});
