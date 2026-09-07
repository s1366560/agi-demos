import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopTenantTasksAuthorityUnavailableErrorV2,
  createDesktopTenantTasksOperationsV2,
  withDesktopTenantTasksAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopTenantTasksAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46942',
    apiKey: 'tasks-secret',
    localApiToken: 'tasks-launch',
    mode: 'cloud',
    tenantId: 'tenant-1',
    projectId: '',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

function cloudScope(overrides = {}) {
  return { authority: 'cloud', tenantId: 'tenant-1', projectId: null, ...overrides };
}

function localScope(overrides = {}) {
  return { authority: 'local', tenantId: 'tenant-1', projectId: 'project-1', ...overrides };
}

function task(overrides = {}) {
  return {
    id: 'task-1',
    projectId: null,
    workspaceId: null,
    conversationId: null,
    taskType: 'add_episode',
    name: 'Process episode',
    status: 'failed',
    createdAt: '2026-09-03T00:00:00Z',
    completedAt: null,
    error: null,
    duration: null,
    entityId: null,
    entityType: null,
    revision: null,
    canRetry: true,
    canStop: false,
    ...overrides,
  };
}

function snapshot(scope = cloudScope(), overrides = {}) {
  return {
    scope,
    authority: scope.authority,
    availability: scope.authority === 'cloud' ? 'available' : 'degraded',
    reasonCode: scope.authority === 'cloud' ? null : 'local_task_dashboard_partial',
    serviceVersion: scope.authority === 'cloud' ? 'cloud' : '0.1.0',
    contractVersion: '3.0.0',
    allowedActions:
      scope.authority === 'cloud'
        ? ['view', 'list', 'search', 'filter', 'paginate', 'refresh', 'retry-task', 'stop-task', 'retry-pending', 'navigate-dead-letter-queue']
        : ['view', 'list', 'search', 'filter', 'paginate', 'refresh', 'open-workspace'],
    authorityRevision: null,
    stats: {
      total: 1,
      pending: 0,
      processing: 0,
      completed: 0,
      failed: 1,
      throughputPerMinute: 0,
      errorRate: 0,
    },
    queue: { current: 0, history: [] },
    tasks: [task({ projectId: scope.projectId })],
    total: 1,
    limit: 50,
    offset: 0,
    hasMore: false,
    ...overrides,
  };
}

function serviceFixture(received, overrides = {}) {
  return Object.freeze({
    bindOperation(config, operationScope) {
      received.push({ type: 'bind', config, scope: operationScope });
      return Object.freeze({
        async load(query, signal) {
          received.push({ type: 'load', query, signal });
          return overrides.load ?? snapshot(operationScope);
        },
        async retryTask(record, signal) {
          received.push({ type: 'retry', task: record, signal });
          return overrides.retryTask;
        },
        async stopTask(record, signal) {
          received.push({ type: 'stop', task: record, signal });
          return overrides.stopTask;
        },
        async retryPending(limit, signal) {
          received.push({ type: 'retry-pending', limit, signal });
          return overrides.retryPending ?? { submitted: 1, skipped: 0, limit, taskIds: ['task-1'] };
        },
      });
    },
  });
}

function acceptedActions(service, digest, lifecycle = [], releaseError = null) {
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
          if (releaseError) throw releaseError;
        },
      };
    },
  };
}

test('Cloud Tasks operations freeze inputs before one exact tenant lease', async () => {
  const lifecycle = [];
  const received = [];
  const controller = new AbortController();
  const config = runtimeConfig();
  const scope = cloudScope();
  const query = { search: ' episode ', status: 'FAILED', limit: 25, offset: 0 };
  const record = task();
  const operations = createDesktopTenantTasksOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-cloud', lifecycle),
  );

  const pendingLoad = operations.loadTenantTasks({
    config,
    scope,
    query,
    signal: controller.signal,
  });
  config.tenantId = 'mutated';
  scope.tenantId = 'mutated';
  query.search = 'mutated';
  await pendingLoad;
  await operations.retryTenantTask({ config: runtimeConfig(), scope: cloudScope(), task: record });
  await operations.stopTenantTask({ config: runtimeConfig(), scope: cloudScope(), task: record });
  await operations.retryPendingTenantTasks({
    config: runtimeConfig(),
    scope: cloudScope(),
    limit: 5,
  });

  assert.equal(lifecycle.length, 8);
  for (const event of lifecycle.filter(({ type }) => type === 'acquire')) {
    assert.deepEqual(event.request, {
      service: 'service:desktop-renderer.tenant-tasks-authority',
      version: '1.0.0',
      scope: { kind: 'tenant', tenant_id: 'tenant-1' },
    });
  }
  assert.deepEqual(received[0].scope, {
    authority: 'cloud',
    tenantId: 'tenant-1',
    projectId: null,
  });
  assert.deepEqual(received[1].query, {
    search: 'episode',
    status: 'failed',
    limit: 25,
    offset: 0,
  });
  assert.equal(Object.isFrozen(received[1].query), true);
  assert.equal(received[1].signal, controller.signal);
  assert.equal(received[3].task.id, 'task-1');
  assert.equal(Object.isFrozen(received[3].task), true);
  assert.equal(received[7].limit, 5);
});

test('Local load uses a project lease and local mutations fail before acquisition', async () => {
  const lifecycle = [];
  let acquisitions = 0;
  const operations = createDesktopTenantTasksOperationsV2(() => ({
    async acquireServiceOperationLease(request) {
      acquisitions += 1;
      return acceptedActions(
        serviceFixture([], { load: snapshot(localScope()) }),
        'digest-local',
        lifecycle,
      ).acquireServiceOperationLease(request);
    },
  }));
  const config = runtimeConfig({ mode: 'local', projectId: 'project-1' });
  await operations.loadTenantTasks({ config, scope: localScope() });

  assert.equal(acquisitions, 1);
  assert.deepEqual(lifecycle[0].request, {
    service: 'service:desktop-renderer.tenant-tasks-authority',
    version: '1.0.0',
    scope: { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' },
  });
  for (const call of [
    () => operations.retryTenantTask({ config, scope: localScope(), task: task({ projectId: 'project-1' }) }),
    () => operations.stopTenantTask({ config, scope: localScope(), task: task({ projectId: 'project-1' }) }),
    () => operations.retryPendingTenantTasks({ config, scope: localScope(), limit: 5 }),
  ]) {
    assert.throws(call, /local_task_mutation_unavailable/u);
  }
  assert.equal(acquisitions, 1);
});

test('invalid discriminated scope, query, task and limit fail before acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopTenantTasksOperationsV2(() => ({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      assert.fail('invalid input must not acquire a lease');
    },
  }));
  const invalidCalls = [
    () => operations.loadTenantTasks({ config: runtimeConfig(), scope: { ...cloudScope(), projectId: 'project-1' } }),
    () => operations.loadTenantTasks({ config: runtimeConfig({ mode: 'local', projectId: 'project-1' }), scope: { ...localScope(), projectId: null } }),
    () => operations.loadTenantTasks({ config: runtimeConfig(), scope: cloudScope(), query: { limit: 101 } }),
    () => operations.retryTenantTask({ config: runtimeConfig(), scope: cloudScope(), task: task({ id: ' task-1' }) }),
    () => operations.retryPendingTenantTasks({ config: runtimeConfig(), scope: cloudScope(), limit: 11 }),
  ];
  for (const invalidCall of invalidCalls) {
    assert.throws(
      invalidCall,
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_tenant_tasks_operation_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
  assert.throws(
    () => createDesktopTenantTasksOperationsV2(() => null).loadTenantTasks({ config: runtimeConfig(), scope: cloudScope() }),
    (error) =>
      error instanceof DesktopTenantTasksAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
});

test('lease rejection and malformed service, authority or result shapes fail closed', async () => {
  const rejected = createDesktopTenantTasksOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return { status: 'rejected', reasonCode: 'missing_service', runtimeCode: 'missing_service' };
    },
  }));
  await assert.rejects(
    rejected.loadTenantTasks({ config: runtimeConfig(), scope: cloudScope() }),
    (error) =>
      error instanceof DesktopTenantTasksAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'missing_service',
  );

  for (const service of [
    Object.freeze({ bindOperation: null }),
    Object.freeze({ bindOperation: () => Object.freeze({ load: async () => snapshot() }) }),
  ]) {
    const operations = createDesktopTenantTasksOperationsV2(() =>
      acceptedActions(service, 'invalid-shape'),
    );
    await assert.rejects(
      operations.loadTenantTasks({ config: runtimeConfig(), scope: cloudScope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_tenant_tasks_service_invalid',
    );
  }

  const malformed = createDesktopTenantTasksOperationsV2(() =>
    acceptedActions(
      serviceFixture([], { load: { ...snapshot(), scope: localScope() } }),
      'bad-result',
    ),
  );
  await assert.rejects(
    malformed.loadTenantTasks({ config: runtimeConfig(), scope: cloudScope() }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_tenant_tasks_service_contract_invalid',
  );
});

test('escaped authority is revoked and primary failure wins over disposer failure', async () => {
  let escaped;
  await withDesktopTenantTasksAuthorityOperationV2(
    acceptedActions(serviceFixture([]), 'digest-a'),
    { config: runtimeConfig(), scope: cloudScope() },
    (authority) => {
      escaped = authority;
      return authority.load();
    },
  );
  await assert.rejects(
    escaped.load(),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_tenant_tasks_operation_released',
  );

  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopTenantTasksAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-failure', [], release),
      { config: runtimeConfig(), scope: cloudScope() },
      async () => {
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  await assert.rejects(
    withDesktopTenantTasksAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { config: runtimeConfig(), scope: cloudScope() },
      (authority) => authority.load(),
    ),
    (error) => error === release,
  );
});

test('old Tasks request stays pinned while a new request uses replacement generation', async () => {
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
        async load(query, signal) {
          await gate;
          await authority.load(query, signal);
          return snapshot(cloudScope(), { serviceVersion: 'old' });
        },
      });
    },
  });
  let actions = acceptedActions(gatedService, 'old');
  const operations = createDesktopTenantTasksOperationsV2(() => actions);
  const oldRequest = operations.loadTenantTasks({ config: runtimeConfig(), scope: cloudScope() });
  actions = acceptedActions(
    serviceFixture([], { load: snapshot(cloudScope(), { serviceVersion: 'new' }) }),
    'new',
  );
  const newRequest = operations.loadTenantTasks({ config: runtimeConfig(), scope: cloudScope() });
  releaseOld();

  assert.equal((await oldRequest).serviceVersion, 'old');
  assert.equal((await newRequest).serviceVersion, 'new');
});
