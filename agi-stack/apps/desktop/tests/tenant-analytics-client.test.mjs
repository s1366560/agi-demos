import assert from 'node:assert/strict';
import { test } from 'node:test';

const {
  createTenantAnalyticsHttpClient,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/tenantAnalyticsHttpClient.js'
);

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test('cloud analytics client validates the 30-day tenant authority contract', async () => {
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init });
    return jsonResponse({
      memoryGrowth: [
        { date: '2026-07-01', count: 2 },
        { date: '2026-07-02', count: 4 },
      ],
      projectStorage: [
        {
          name: 'Alpha',
          storage_bytes: 2048,
          memory_count: 6,
        },
      ],
      summary: {
        total_memories: 6,
        total_storage_bytes: 2048,
        total_projects: 1,
        period_days: 30,
      },
    });
  };

  const client = createTenantAnalyticsHttpClient(
    runtimeConfig({ mode: 'cloud', tenantId: 'tenant-1' }),
  );
  const result = await client.load(
    { authority: 'cloud', tenantId: 'tenant-1', period: '30d' },
    {},
  );

  assert.equal(
    requests[0].url,
    'https://cloud.example/api/v1/tenants/tenant-1/analytics?period=30d',
  );
  assert.equal(requests[0].init.method, 'GET');
  assert.equal(
    new Headers(requests[0].init.headers).get('Authorization'),
    'Bearer cloud-token',
  );
  assert.equal(result.availability, 'available');
  assert.equal(result.summary.totalMemories.value, 6);
  assert.equal(result.summary.totalProjects.value, 1);
  assert.equal(result.memoryGrowth.value[1].count, 4);
  assert.equal(result.projectStorage.value[0].storageBytes.value, 2048);
});

test('local analytics client preserves degraded field authority without fabricating memory data', async () => {
  globalThis.fetch = async () =>
    jsonResponse({
      capability: 'tenant_analytics',
      availability: 'degraded',
      reason_code: 'local_tenant_analytics_memory_projection_unavailable',
      service_version: '0.1.0',
      contract_version: '3.0.0',
      allowed_actions: ['view', 'retry'],
      scope: {
        tenant_id: 'tenant-local',
        project_id: null,
        workspace_id: null,
        instance_id: null,
      },
      authority_revision: 9,
      memoryGrowth: {
        availability: 'unavailable',
        reason_code: 'local_tenant_memory_projection_unavailable',
        value: [],
      },
      projectStorage: {
        availability: 'degraded',
        reason_code: 'local_project_storage_projection_unavailable',
        value: [
          {
            name: 'Local project',
            storage_bytes: {
              availability: 'unavailable',
              reason_code: 'local_project_storage_projection_unavailable',
              value: null,
            },
            memory_count: {
              availability: 'unavailable',
              reason_code: 'local_project_memory_projection_unavailable',
              value: null,
            },
          },
        ],
      },
      summary: {
        total_memories: {
          availability: 'unavailable',
          reason_code: 'local_tenant_memory_projection_unavailable',
          value: null,
        },
        total_storage_bytes: {
          availability: 'unavailable',
          reason_code: 'local_tenant_storage_projection_unavailable',
          value: null,
        },
        total_projects: {
          availability: 'available',
          reason_code: null,
          value: 1,
        },
        period_days: 30,
      },
    });

  const client = createTenantAnalyticsHttpClient(
    runtimeConfig({
      mode: 'local',
      tenantId: 'tenant-local',
      apiBaseUrl: 'http://127.0.0.1:43121',
    }),
  );
  const result = await client.load({
    authority: 'local',
    tenantId: 'tenant-local',
    period: '30d',
  });

  assert.equal(result.availability, 'degraded');
  assert.equal(
    result.reasonCode,
    'local_tenant_analytics_memory_projection_unavailable',
  );
  assert.equal(result.summary.totalMemories.value, null);
  assert.equal(
    result.summary.totalStorageBytes.reasonCode,
    'local_tenant_storage_projection_unavailable',
  );
  assert.equal(result.summary.totalProjects.value, 1);
  assert.equal(result.projectStorage.value[0].storageBytes.value, null);
  assert.deepEqual(result.allowedActions, ['view', 'retry']);
  assert.equal(result.authorityRevision, 9);
});

test('analytics client fails closed on scope drift and malformed payloads', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return jsonResponse({
      memoryGrowth: [],
      projectStorage: [],
      summary: {
        total_memories: -1,
        total_storage_bytes: 0,
        total_projects: 0,
        period_days: 30,
      },
    });
  };
  const client = createTenantAnalyticsHttpClient(
    runtimeConfig({ mode: 'cloud', tenantId: 'tenant-1' }),
  );

  await assert.rejects(
    client.load({
      authority: 'cloud',
      tenantId: 'tenant-other',
      period: '30d',
    }),
    /tenant_analytics_runtime_scope_mismatch/u,
  );
  assert.equal(calls, 0);

  await assert.rejects(
    client.load({
      authority: 'cloud',
      tenantId: 'tenant-1',
      period: '30d',
    }),
    /cloud_tenant_analytics_contract_invalid/u,
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
