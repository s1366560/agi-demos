import assert from 'node:assert/strict';
import { test } from 'node:test';

const { DesktopApiError } =
  await import('/tmp/agistack-desktop-test-dist/src/api/client.js');
const { createTenantTasksController } =
  await import('/tmp/agistack-desktop-test-dist/src/features/tenant/tenantTasksController.js');

test('Tenant Tasks suppresses stale completion after a Local project scope switch', async () => {
  const pending = new Map();
  const controller = createTenantTasksController({
    authority: 'local',
    client: {
      load(scope, _query, options) {
        const request = deferred();
        pending.set(scope.projectId, { ...request, signal: options.signal });
        return request.promise;
      },
    },
    initialScope: localScope('project-1'),
  });

  const first = controller.load(localScope('project-1'));
  const second = controller.load(localScope('project-2'));
  assert.equal(pending.get('project-1').signal.aborted, true);
  assert.equal(controller.getSnapshot().state, 'scope_switch');

  pending.get('project-1').resolve(localSnapshot('project-1'));
  await first;
  assert.equal(controller.getSnapshot().scope.projectId, 'project-2');

  pending.get('project-2').resolve(localSnapshot('project-2'));
  await second;
  assert.equal(controller.getSnapshot().state, 'degraded');
  assert.equal(controller.getSnapshot().tasks[0].projectId, 'project-2');
});

test('Tenant Tasks retains authoritative rows as stale after a retryable refresh failure', async () => {
  let fail = false;
  const controller = createTenantTasksController({
    authority: 'cloud',
    client: {
      async load(scopeValue) {
        if (fail) {
          throw new DesktopApiError('unavailable', 503, {
            reason_code: 'task_authority_unavailable',
          });
        }
        return snapshot(scopeValue.projectId);
      },
    },
    initialScope: scope(),
  });

  await controller.load(scope());
  fail = true;
  await controller.retry();

  assert.equal(controller.getSnapshot().state, 'stale');
  assert.equal(
    controller.getSnapshot().reasonCode,
    'task_authority_unavailable',
  );
  assert.equal(controller.getSnapshot().retryVisible, true);
  assert.equal(controller.getSnapshot().tasks.length, 1);
});

test('Tenant Tasks exposes structured conflict and forbidden mutation states', async () => {
  const conflict = controllerWithMutationError(
    new DesktopApiError('conflict', 409, {
      reason_code: 'task_revision_conflict',
    }),
  );
  await conflict.load(scope());
  await assert.rejects(conflict.retryTask('task-1'), /conflict/u);
  assert.equal(conflict.getSnapshot().state, 'conflict');
  assert.equal(conflict.getSnapshot().reasonCode, 'task_revision_conflict');

  const forbidden = controllerWithMutationError(
    new DesktopApiError('forbidden', 403, {
      reason_code: 'task_access_forbidden',
    }),
  );
  await forbidden.load(scope());
  await assert.rejects(forbidden.stopTask('task-1'), /forbidden/u);
  assert.equal(forbidden.getSnapshot().state, 'forbidden');
  assert.equal(forbidden.getSnapshot().reasonCode, 'task_access_forbidden');
});

function controllerWithMutationError(error) {
  return createTenantTasksController({
    authority: 'cloud',
    client: {
      async load(scopeValue) {
        return snapshot(scopeValue.projectId, {
          tasks: [task(scopeValue.projectId, { canStop: true })],
        });
      },
      async retryTask() {
        throw error;
      },
      async stopTask() {
        throw error;
      },
    },
    initialScope: scope(),
  });
}

function scope() {
  return {
    authority: 'cloud',
    tenantId: 'tenant-1',
    projectId: null,
  };
}

function localScope(projectId) {
  return { authority: 'local', tenantId: 'tenant-1', projectId };
}

function localSnapshot(projectId) {
  return {
    ...snapshot(null),
    scope: localScope(projectId),
    authority: 'local',
    availability: 'degraded',
    reasonCode: 'local_task_dashboard_partial',
    allowedActions: ['view', 'list', 'search', 'filter', 'paginate', 'refresh', 'open-workspace'],
    tasks: [task(projectId)],
  };
}

function snapshot(projectId, overrides = {}) {
  return {
    scope: scope(),
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: '3.0.0',
    authorityRevision: null,
    allowedActions: [
      'view',
      'list',
      'search',
      'filter',
      'paginate',
      'refresh',
      'retry-task',
      'stop-task',
      'retry-pending',
    ],
    stats: {
      total: 1,
      pending: 0,
      processing: 0,
      completed: 0,
      failed: 1,
      throughputPerMinute: 0,
      errorRate: 100,
    },
    queue: { current: 0, history: [] },
    tasks: [task(null)],
    total: 1,
    limit: 50,
    offset: 0,
    hasMore: false,
    ...overrides,
  };
}

function task(projectId, overrides = {}) {
  return {
    id: 'task-1',
    projectId,
    workspaceId: null,
    conversationId: null,
    taskType: 'add_episode',
    name: 'Process episode',
    status: 'failed',
    createdAt: '2026-07-31T00:00:00Z',
    completedAt: null,
    error: 'failed',
    duration: null,
    entityId: null,
    entityType: null,
    revision: null,
    canRetry: true,
    canStop: false,
    ...overrides,
  };
}

function deferred() {
  let resolve;
  const promise = new Promise((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}
