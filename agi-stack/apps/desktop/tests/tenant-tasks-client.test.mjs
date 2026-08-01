import assert from 'node:assert/strict';
import { test } from 'node:test';

const { createTenantTasksHttpClient } =
  await import('/tmp/agistack-desktop-test-dist/src/features/tenant/tenantTasksHttpClient.js');

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test('Cloud Tenant Tasks binds the complete Web task dashboard authority', async () => {
  const requests = [];
  globalThis.fetch = async (url, init) => {
    const parsed = new URL(String(url));
    requests.push([parsed.pathname, parsed.search, init?.method ?? 'GET']);
    if (parsed.pathname.endsWith('/stats')) {
      return jsonResponse({
        total: 4,
        pending: 1,
        processing: 1,
        completed: 1,
        failed: 1,
        throughput_per_minute: 0.5,
        error_rate: 25,
      });
    }
    if (parsed.pathname.endsWith('/queue-depth')) {
      return jsonResponse([
        { timestamp: '09:00', depth: 2 },
        { timestamp: '12:00', depth: 1 },
      ]);
    }
    if (parsed.pathname.endsWith('/recent')) {
      return jsonResponse({
        tasks: [cloudTask()],
        total: 1,
        limit: 25,
        offset: 0,
        has_more: false,
      });
    }
    if (parsed.pathname.endsWith('/retry-pending')) {
      return jsonResponse({
        submitted: 1,
        skipped: 0,
        limit: 5,
        task_ids: ['task-1'],
      });
    }
    return jsonResponse({ accepted: true });
  };

  const client = createTenantTasksHttpClient(runtimeConfig());
  const snapshot = await client.load(scope(), {
    status: 'failed',
    search: 'episode',
    limit: 25,
    offset: 0,
  });
  await client.retryTask(scope(), snapshot.tasks[0]);
  await client.stopTask(scope(), snapshot.tasks[0]);
  const resumed = await client.retryPending(scope(), 5);

  assert.equal(snapshot.availability, 'available');
  assert.equal(snapshot.reasonCode, null);
  assert.deepEqual(snapshot.allowedActions, [
    'view',
    'list',
    'search',
    'filter',
    'paginate',
    'refresh',
    'retry-task',
    'stop-task',
    'retry-pending',
    'navigate-dead-letter-queue',
  ]);
  assert.equal(snapshot.queue.current, 1);
  assert.equal(snapshot.tasks[0].projectId, null);
  assert.equal(snapshot.tasks[0].canRetry, true);
  assert.equal(snapshot.tasks[0].canStop, false);
  assert.equal(resumed.submitted, 1);
  assert.deepEqual(
    requests.map(([path, , method]) => [path, method]),
    [
      ['/api/v1/tasks/stats', 'GET'],
      ['/api/v1/tasks/queue-depth', 'GET'],
      ['/api/v1/tasks/recent', 'GET'],
      ['/api/v1/tasks/task-1/retry', 'POST'],
      ['/api/v1/tasks/task-1/stop', 'POST'],
      ['/api/v1/tasks/retry-pending', 'POST'],
    ],
  );
  assert.match(requests[2][1], /status=failed/u);
  assert.match(requests[2][1], /search=episode/u);
});

test('Local Tenant Tasks projects My Work and fails closed for unsupported mutations', async () => {
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push([new URL(String(url)).pathname, init?.method ?? 'GET']);
    return jsonResponse({
      project_id: 'project-1',
      total: 1,
      items: [
        {
          id: 'run-1',
          authority_kind: 'desktop_run',
          authority_id: 'run-1',
          run_id: 'run-1',
          revision: 3,
          attempt_number: null,
          conversation_id: 'conversation-1',
          workspace_id: 'workspace-1',
          project_id: 'project-1',
          title: 'Native local run',
          capability_mode: 'build',
          group: 'running',
          status: 'running',
          required_action: 'observe',
          permission_profile: 'workspace_write',
          environment: null,
          created_at: '2026-07-31T01:00:00Z',
          updated_at: '2026-07-31T01:01:00Z',
        },
      ],
    });
  };

  const client = createTenantTasksHttpClient(
    runtimeConfig({ mode: 'local', apiBaseUrl: 'http://127.0.0.1:4777' }),
  );
  const localScope = { ...scope(), authority: 'local' };
  const snapshot = await client.load(localScope);

  assert.equal(snapshot.availability, 'degraded');
  assert.equal(snapshot.reasonCode, 'local_task_dashboard_partial');
  assert.deepEqual(snapshot.allowedActions, [
    'view',
    'list',
    'search',
    'filter',
    'paginate',
    'refresh',
    'open-workspace',
  ]);
  assert.equal(snapshot.tasks[0].workspaceId, 'workspace-1');
  assert.equal(snapshot.tasks[0].projectId, 'project-1');
  assert.equal(snapshot.tasks[0].canRetry, false);
  assert.equal(snapshot.tasks[0].canStop, false);
  await assert.rejects(
    client.retryTask(localScope, snapshot.tasks[0]),
    /local_task_mutation_unavailable:retry-task/u,
  );
  assert.deepEqual(requests, [['/api/v1/projects/project-1/my-work', 'GET']]);
});

test('Tenant Tasks fails closed before fetch when runtime scope drifts', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return jsonResponse({});
  };
  const client = createTenantTasksHttpClient(runtimeConfig());

  await assert.rejects(
    client.load({ ...scope(), tenantId: 'other-tenant' }),
    /tenant_tasks_runtime_scope_mismatch/u,
  );
  assert.equal(calls, 0);
});

function runtimeConfig(overrides = {}) {
  return {
    mode: 'cloud',
    apiBaseUrl: 'https://memstack.test',
    deviceAuthorizationBaseUrl: 'https://memstack.test',
    apiKey: 'test-token',
    localApiToken: 'test-local-token',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '/workspace',
    ...overrides,
  };
}

function scope() {
  return {
    authority: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
}

function cloudTask(overrides = {}) {
  return {
    id: 'task-1',
    task_type: 'add_episode',
    name: 'Process episode',
    status: 'failed',
    created_at: '2026-07-31T00:00:00Z',
    completed_at: '2026-07-31T00:01:00Z',
    error: 'failed',
    worker_id: 'worker-1',
    retries: 1,
    duration: '1m',
    entity_id: 'episode-1',
    entity_type: 'episode',
    ...overrides,
  };
}

function jsonResponse(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
