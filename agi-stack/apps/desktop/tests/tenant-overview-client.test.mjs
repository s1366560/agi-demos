import assert from 'node:assert/strict';
import { test } from 'node:test';

const {
  createTenantOverviewHttpClient,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/tenantOverviewHttpClient.js'
);

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test('cloud client validates and projects the authoritative tenant stats contract', async () => {
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init });
    return jsonResponse({
      storage: { used: 1024, total: 4096, percentage: 25 },
      projects: {
        active: 1,
        new_this_week: 1,
        list: [
          {
            id: 'project-1',
            name: 'Alpha',
            owner: 'Ada',
            memory_consumed: '1.0 KB',
            status: 'active',
          },
        ],
      },
      members: { total: 3, new_added: 1 },
      memory_history: [
        {
          date: '2026-07-30',
          used: 1024,
          daily_added: 128,
          memory_count: 2,
          percentage: 25,
        },
      ],
      tenant_info: {
        organization_id: '#TEN-ABC',
        plan: 'Pro',
        region: null,
        next_billing_date: null,
      },
    });
  };

  const client = createTenantOverviewHttpClient(
    runtimeConfig({ mode: 'cloud', tenantId: 'tenant-1' }),
  );
  const result = await client.load({
    authority: 'cloud',
    tenantId: 'tenant-1',
  });

  assert.equal(requests.length, 1);
  assert.equal(
    requests[0].url,
    'https://cloud.example/api/v1/tenants/tenant-1/stats',
  );
  assert.equal(requests[0].init.method, 'GET');
  assert.equal(
    new Headers(requests[0].init.headers).get('Authorization'),
    'Bearer cloud-token',
  );
  assert.equal(result.availability, 'available');
  assert.equal(result.reasonCode, null);
  assert.equal(result.storage.availability, 'available');
  assert.equal(result.storage.value.used, 1024);
  assert.equal(result.projects.value[0].owner.value, 'Ada');
  assert.equal(result.memoryHistory.value.length, 1);
});

test('local client accepts only the declared degraded sidecar projection', async () => {
  globalThis.fetch = async () =>
    jsonResponse({
      capability: 'tenant_overview',
      availability: 'degraded',
      reason_code: 'local_tenant_overview_memory_projection_unavailable',
      service_version: '0.1.0',
      contract_version: '3.0.0',
      allowed_actions: ['view'],
      scope: {
        tenant_id: 'tenant-local',
        project_id: null,
        workspace_id: null,
        instance_id: null,
      },
      authority_revision: 7,
      tenant_info: {
        organization_id: '#TEN-LOCAL',
        plan: 'Local',
        region: {
          availability: 'not_applicable',
          reason_code: 'local_tenant_region_not_applicable',
          value: null,
        },
        next_billing_date: {
          availability: 'not_applicable',
          reason_code: 'local_billing_authority_not_applicable',
          value: null,
        },
      },
      storage: {
        availability: 'unavailable',
        reason_code: 'local_tenant_memory_projection_unavailable',
        value: null,
      },
      projects: {
        availability: 'degraded',
        reason_code: 'local_tenant_project_owner_projection_unavailable',
        active: 2,
        new_this_week: 1,
        list: [
          {
            id: 'local-project',
            name: 'Local project',
            owner: {
              availability: 'unavailable',
              reason_code: 'local_project_owner_projection_unavailable',
              value: null,
            },
            memory_consumed: {
              availability: 'unavailable',
              reason_code: 'local_project_memory_projection_unavailable',
              value: null,
            },
            status: 'active',
          },
        ],
      },
      members: { total: 1, new_added: 0 },
      memory_history: {
        availability: 'unavailable',
        reason_code: 'local_tenant_memory_projection_unavailable',
        value: [],
      },
    });

  const client = createTenantOverviewHttpClient(
    runtimeConfig({
      mode: 'local',
      tenantId: 'tenant-local',
      apiBaseUrl: 'http://127.0.0.1:43121',
    }),
  );
  const result = await client.load({
    authority: 'local',
    tenantId: 'tenant-local',
  });

  assert.equal(result.availability, 'degraded');
  assert.equal(
    result.reasonCode,
    'local_tenant_overview_memory_projection_unavailable',
  );
  assert.equal(result.storage.availability, 'unavailable');
  assert.equal(result.storage.value, null);
  assert.equal(result.projects.value[0].owner.value, null);
  assert.equal(result.members.value.total, 1);
  assert.deepEqual(result.allowedActions, ['view']);
  assert.equal(result.authorityRevision, 7);
});

test('client fails closed on runtime scope drift and malformed payloads', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return jsonResponse({
      storage: { used: -1, total: 1, percentage: 0 },
      projects: { active: 0, new_this_week: 0, list: [] },
      members: { total: 0, new_added: 0 },
      memory_history: [],
      tenant_info: { organization_id: '#TEN-X', plan: 'Free' },
    });
  };
  const client = createTenantOverviewHttpClient(
    runtimeConfig({ mode: 'cloud', tenantId: 'tenant-1' }),
  );

  await assert.rejects(
    client.load({ authority: 'cloud', tenantId: 'tenant-other' }),
    /tenant_overview_runtime_scope_mismatch/u,
  );
  assert.equal(calls, 0);

  await assert.rejects(
    client.load({ authority: 'cloud', tenantId: 'tenant-1' }),
    /cloud_tenant_overview_contract_invalid/u,
  );
});

function runtimeConfig(overrides) {
  return {
    mode: 'cloud',
    apiBaseUrl: 'https://cloud.example',
    deviceAuthorizationBaseUrl: 'https://cloud.example',
    wsUrl: 'wss://cloud.example/api/v1/agent/ws',
    apiKey: 'cloud-token',
    localApiToken: 'launch-capability',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
