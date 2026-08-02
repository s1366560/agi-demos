import assert from 'node:assert/strict';
import { test } from 'node:test';

const { createRuntimePoolHttpClient } = await import(
  '/tmp/agistack-desktop-test-dist/src/features/runtime-pool/runtimePoolClient.js'
);

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test('Runtime Pool client sends tenant authority on every Cloud request', async () => {
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), init });
    const url = new URL(String(input));
    if (url.pathname.endsWith('/status')) return json(statusPayload());
    if (url.pathname.endsWith('/metrics')) return json(metricsPayload());
    if (url.pathname.endsWith('/instances')) return json(instancesPayload());
    if (url.pathname.endsWith('/pause') || url.pathname.endsWith('/resume')) {
      return json(operationPayload());
    }
    if (init?.method === 'DELETE') return json(operationPayload());
    return new Response(null, { status: 404 });
  };
  const client = createRuntimePoolHttpClient(runtimeConfig());
  const authority = scope();

  await client.getStatus(authority);
  await client.listInstances(authority, {
    tier: 'hot',
    status: 'ready',
    page: 2,
    pageSize: 25,
  });
  await client.getMetrics(authority);
  await client.pauseInstance(authority, 'tenant-1:project-1:chat');
  await client.resumeInstance(authority, 'tenant-1:project-1:chat');
  await client.terminateInstance(
    authority,
    'tenant-1:project-1:chat',
    true,
  );

  assert.equal(calls.length, 6);
  for (const call of calls) {
    const url = new URL(call.url);
    assert.equal(url.searchParams.get('scope'), 'tenant');
    assert.equal(url.searchParams.get('tenant_id'), 'tenant-1');
    assert.match(call.init.headers.get('Authorization'), /^Bearer /u);
  }
  const listUrl = new URL(calls[1].url);
  assert.equal(listUrl.searchParams.get('tier'), 'hot');
  assert.equal(listUrl.searchParams.get('status'), 'ready');
  assert.equal(listUrl.searchParams.get('page'), '2');
  assert.equal(listUrl.searchParams.get('page_size'), '25');
  assert.equal(calls[3].init.method, 'POST');
  assert.equal(calls[5].init.method, 'DELETE');
  assert.equal(
    new URL(calls[5].url).searchParams.get('graceful'),
    'true',
  );
});

test('Runtime Pool client rejects cross-scope responses and never calls Cloud in Local mode', async () => {
  let fetchCount = 0;
  globalThis.fetch = async () => {
    fetchCount += 1;
    return json(statusPayload({ tenant_id: 'tenant-other' }));
  };
  const cloudClient = createRuntimePoolHttpClient(runtimeConfig());
  await assert.rejects(
    cloudClient.getStatus(scope()),
    /runtime_pool_response_scope_mismatch/u,
  );

  const localClient = createRuntimePoolHttpClient(
    runtimeConfig({ mode: 'local' }),
  );
  await assert.rejects(
    localClient.getStatus({ authority: 'local', tenantId: 'tenant-1' }),
    /cloud_runtime_pool_not_applicable/u,
  );
  await assert.rejects(
    localClient.listInstances(
      { authority: 'local', tenantId: 'tenant-1' },
      { page: 1, pageSize: 20 },
    ),
    /cloud_runtime_pool_not_applicable/u,
  );
  assert.equal(fetchCount, 1);
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
  return { authority: 'cloud', tenantId: 'tenant-1' };
}

function statusPayload(overrides = {}) {
  return {
    enabled: true,
    status: 'running',
    total_instances: 1,
    hot_instances: 1,
    warm_instances: 0,
    cold_instances: 0,
    ready_instances: 1,
    executing_instances: 0,
    unhealthy_instances: 0,
    prewarm_pool: null,
    resource_usage: null,
    resolved_scope: 'tenant',
    tenant_id: 'tenant-1',
    reason_code: 'global_pool_capacity_not_available_in_tenant_scope',
    ...overrides,
  };
}

function instancesPayload() {
  return {
    instances: [
      {
        instance_key: 'tenant-1:project-1:chat',
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        agent_mode: 'chat',
        tier: 'hot',
        status: 'ready',
        created_at: '2026-08-01T00:00:00Z',
        last_request_at: '2026-08-01T00:01:00Z',
        active_requests: 0,
        total_requests: 3,
        memory_used_mb: 128,
        health_status: 'healthy',
      },
    ],
    total: 1,
    page: 2,
    page_size: 25,
    resolved_scope: 'tenant',
    tenant_id: 'tenant-1',
  };
}

function metricsPayload() {
  return {
    instances: {
      total: 1,
      by_tier: { hot: 1, warm: 0, cold: 0 },
      by_status: { ready: 1, executing: 0, unhealthy: 0 },
    },
    health: { unhealthy_count: 0 },
    prewarm: null,
    resolved_scope: 'tenant',
    tenant_id: 'tenant-1',
    reason_code: 'global_pool_capacity_not_available_in_tenant_scope',
  };
}

function operationPayload() {
  return {
    success: true,
    message: 'ok',
    resolved_scope: 'tenant',
    tenant_id: 'tenant-1',
  };
}

function json(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}
