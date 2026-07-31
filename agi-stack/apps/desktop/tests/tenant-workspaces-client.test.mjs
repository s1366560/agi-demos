import assert from 'node:assert/strict';
import { test } from 'node:test';

const { createTenantWorkspacesHttpClient } =
  await import('/tmp/agistack-desktop-test-dist/src/features/tenant/tenantWorkspacesHttpClient.js');

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test('Cloud Tenant Workspaces binds list and create to the selected project', async () => {
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url: String(url), init });
    if ((init?.method ?? 'GET') === 'POST') {
      return jsonResponse(workspace({ id: 'workspace-created', name: 'Created' }), 201);
    }
    return jsonResponse([workspace()]);
  };

  const client = createTenantWorkspacesHttpClient(runtimeConfig());
  const catalog = await client.list(scope());
  const created = await client.create(scope(), {
    name: 'Created',
    description: 'Native workspace',
  });

  assert.equal(catalog.availability, 'degraded');
  assert.equal(catalog.reasonCode, 'desktop_tenant_workspaces_advanced_management_partial');
  assert.deepEqual(catalog.allowedActions, ['view', 'list', 'create']);
  assert.equal(catalog.workspaces[0].projectId, 'project-1');
  assert.equal(created.id, 'workspace-created');
  assert.deepEqual(
    requests.map(({ url, init }) => [new URL(url).pathname, init?.method ?? 'GET']),
    [
      ['/api/v1/tenants/tenant-1/projects/project-1/workspaces', 'GET'],
      ['/api/v1/tenants/tenant-1/projects/project-1/workspaces', 'POST'],
    ],
  );
  assert.equal(JSON.parse(requests[1].init.body).collaboration_mode, 'multi_agent_shared');
});

test('Local Tenant Workspaces retains the stable degraded lifecycle contract', async () => {
  globalThis.fetch = async () => jsonResponse([workspace()]);
  const client = createTenantWorkspacesHttpClient(
    runtimeConfig({
      mode: 'local',
      apiBaseUrl: 'http://127.0.0.1:4777',
    }),
  );

  const catalog = await client.list({ ...scope(), authority: 'local' });

  assert.equal(catalog.authority, 'local');
  assert.equal(catalog.availability, 'degraded');
  assert.equal(catalog.reasonCode, 'local_workspace_lifecycle_partial');
  assert.deepEqual(catalog.allowedActions, ['view', 'list', 'create']);
});

test('Tenant Workspaces fails closed before fetch when runtime scope drifts', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return jsonResponse([]);
  };
  const client = createTenantWorkspacesHttpClient(runtimeConfig());

  await assert.rejects(
    client.list({ ...scope(), projectId: 'other-project' }),
    /tenant_workspaces_runtime_scope_mismatch/u,
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

function workspace(overrides = {}) {
  return {
    id: 'workspace-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    name: 'Alpha workspace',
    description: 'Workspace description',
    status: 'active',
    is_archived: false,
    created_at: '2026-07-31T00:00:00Z',
    updated_at: null,
    metadata: {},
    ...overrides,
  };
}

function jsonResponse(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
