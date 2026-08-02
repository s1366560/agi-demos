import assert from 'node:assert/strict';
import { test } from 'node:test';

const { DesktopApiError } = await import(
  '/tmp/agistack-desktop-test-dist/src/api/client.js'
);
const {
  createProjectSupportClient,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/project-support/projectSupportClient.js'
);

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test('Cloud Project Support binds list, create, and close to the tenant scope', async () => {
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url: String(url), init });
    const path = new URL(String(url)).pathname;
    if (path.endsWith('/close')) {
      return jsonResponse({
        id: 'ticket-1',
        status: 'closed',
        resolved_at: '2026-08-02T02:00:00Z',
      });
    }
    if ((init?.method ?? 'GET') === 'POST') {
      const body = JSON.parse(init.body);
      return jsonResponse(
        ticket({
          id: 'ticket-2',
          subject: body.subject,
          message: body.message,
          priority: body.priority,
        }),
        201,
      );
    }
    return jsonResponse({
      tickets: [ticket()],
      total: 1,
      limit: 25,
      offset: 0,
      has_more: false,
    });
  };

  const client = createProjectSupportClient(runtimeConfig());
  const scope = cloudScope();
  const snapshot = await client.list(scope, { limit: 25, offset: 0 });
  const created = await client.create(scope, {
    subject: 'Created',
    message: 'Please help',
    priority: 'high',
  });
  const closed = await client.close(scope, 'ticket-1');

  assert.equal(snapshot.tickets[0].tenantId, 'tenant-1');
  assert.deepEqual(snapshot.allowedActions, ['view', 'list', 'create', 'close', 'retry']);
  assert.deepEqual(snapshot.tickets[0].allowedActions, ['view', 'close']);
  assert.equal(created.id, 'ticket-2');
  assert.equal(closed.status, 'closed');
  assert.deepEqual(
    requests.map(({ url, init }) => [
      new URL(url).pathname,
      init?.method ?? 'GET',
      new URL(url).searchParams.get('tenant_id'),
    ]),
    [
      ['/api/v1/support/tickets', 'GET', 'tenant-1'],
      ['/api/v1/support/tickets', 'POST', null],
      ['/api/v1/support/tickets/ticket-1/close', 'POST', null],
    ],
  );
  assert.deepEqual(JSON.parse(requests[1].init.body), {
    tenant_id: 'tenant-1',
    subject: 'Created',
    message: 'Please help',
    priority: 'high',
  });
  assert.equal(
    new Headers(requests[0].init.headers).get('Authorization'),
    'Bearer session-credential',
  );
});

test('Local Project Support is a stable not-applicable authority and never fetches', async () => {
  let fetchCalls = 0;
  globalThis.fetch = async () => {
    fetchCalls += 1;
    throw new Error('Local Project Support must not call a hosted service');
  };
  const client = createProjectSupportClient(
    runtimeConfig({ mode: 'local', apiBaseUrl: 'http://127.0.0.1:4777' }),
  );
  const scope = { ...cloudScope(), authority: 'local' };

  const snapshot = await client.list(scope);
  assert.equal(snapshot.availability, 'not_applicable');
  assert.equal(snapshot.reasonCode, 'local_support_service_not_applicable');
  assert.deepEqual(snapshot.allowedActions, []);
  await assert.rejects(
    client.create(scope, {
      subject: 'No hosted authority',
      message: 'No mutation',
      priority: 'medium',
    }),
    (error) =>
      error instanceof DesktopApiError &&
      error.status === 501 &&
      error.payload?.reason_code === 'local_support_service_not_applicable',
  );
  await assert.rejects(
    client.close(scope, 'ticket-1'),
    /local_support_service_not_applicable/u,
  );
  assert.equal(fetchCalls, 0);
});

test('Project Support client rejects cross-scope requests and malformed Cloud payloads', async () => {
  const client = createProjectSupportClient(runtimeConfig());
  await assert.rejects(
    client.list({ ...cloudScope(), projectId: 'project-other' }),
    /project_support_scope_mismatch/u,
  );

  globalThis.fetch = async () =>
    jsonResponse({
      tickets: [{ ...ticket(), tenant_id: 'tenant-other' }],
      total: 1,
      limit: 25,
      offset: 0,
      has_more: false,
    });
  await assert.rejects(
    client.list(cloudScope()),
    /cloud_project_support_contract_invalid/u,
  );
});

function runtimeConfig(overrides = {}) {
  return {
    apiBaseUrl: 'https://api.memstack.test',
    apiKey: 'session-credential',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    mode: 'cloud',
    ...overrides,
  };
}

function cloudScope() {
  return {
    authority: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
}

function ticket(overrides = {}) {
  return {
    id: 'ticket-1',
    tenant_id: 'tenant-1',
    subject: 'Need help',
    message: 'Something failed',
    priority: 'medium',
    status: 'open',
    created_at: '2026-08-02T00:00:00Z',
    updated_at: '2026-08-02T01:00:00Z',
    resolved_at: null,
    ...overrides,
  };
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
