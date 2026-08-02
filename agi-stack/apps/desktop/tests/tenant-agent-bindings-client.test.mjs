import assert from 'node:assert/strict';
import { test } from 'node:test';

const {
  createTenantAgentBindingsHttpClient,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/tenantAgentBindingsHttpClient.js'
);

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test('Cloud Agent Bindings client loads tenant bindings, definitions and mutation authority', async () => {
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url: String(url), init });
    const parsed = new URL(String(url));
    if (parsed.pathname === '/api/v1/agent/bindings') {
      return jsonResponse([binding()]);
    }
    if (parsed.pathname === '/api/v1/agent/definitions') {
      return jsonResponse([
        {
          id: 'agent-1',
          tenant_id: 'tenant-1',
          project_id: null,
          name: 'support',
          display_name: 'Support',
          enabled: true,
        },
      ]);
    }
    if (parsed.pathname === '/api/v1/workspace-context') {
      return jsonResponse({
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: 7,
          updated_at: '2026-08-03T00:00:00Z',
        },
        membership_role: 'admin',
      });
    }
    throw new Error(`Unexpected request ${parsed.pathname}`);
  };

  const client = createTenantAgentBindingsHttpClient(runtimeConfig());
  const snapshot = await client.list(scope());

  assert.deepEqual(
    requests.map(({ url }) => url),
    [
      'https://cloud.example/api/v1/agent/bindings?tenant_id=tenant-1',
      'https://cloud.example/api/v1/agent/definitions?tenant_id=tenant-1&scope=tenant&enabled_only=true&limit=100',
      'https://cloud.example/api/v1/workspace-context',
    ],
  );
  assert.ok(
    requests.every(
      ({ init }) =>
        new Headers(init.headers).get('Authorization') === 'Bearer cloud-token',
    ),
  );
  assert.equal(snapshot.availability, 'available');
  assert.equal(snapshot.bindings[0].agentName, 'Support');
  assert.equal(snapshot.bindings[0].specificityScore, 3);
  assert.deepEqual(snapshot.allowedActions, [
    'view',
    'list',
    'create',
    'delete',
    'set-enabled',
    'test',
  ]);
  assert.equal(snapshot.authorityRevision, 7);
});

test('Cloud Agent Bindings client binds create, delete, enablement and resolution test only', async () => {
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({
      url: String(url),
      method: init?.method ?? 'GET',
      body: init?.body ? JSON.parse(init.body) : null,
    });
    const path = new URL(String(url)).pathname;
    if (path.endsWith('/enabled')) {
      return jsonResponse(binding({ enabled: false }));
    }
    if (path.endsWith('/test')) {
      return jsonResponse({
        agent_id: 'agent-1',
        agent_name: 'Support',
        binding_id: 'binding-1',
        specificity_score: 3,
        confidence: 1,
        matched: true,
        trace: [
          {
            binding_id: 'binding-1',
            agent_id: 'agent-1',
            specificity_score: 3,
            channel_type: 'slack',
            channel_id: 'channel-1',
            account_id: null,
            peer_id: null,
            priority: 0,
            eliminated: false,
            elimination_reason: null,
            selected: true,
          },
        ],
      });
    }
    if ((init?.method ?? 'GET') === 'DELETE') {
      return jsonResponse({ deleted: true, id: 'binding-1' });
    }
    return jsonResponse(binding(), 201);
  };

  const client = createTenantAgentBindingsHttpClient(runtimeConfig());
  await client.create(
    scope(),
    {
      agentId: 'agent-1',
      channelType: 'slack',
      channelId: 'channel-1',
      accountId: null,
      peerId: null,
      groupId: null,
      priority: 0,
    },
    { idempotencyKey: 'desktop-binding-create' },
  );
  await client.setEnabled(scope(), 'binding-1', false);
  await client.delete(scope(), 'binding-1');
  const result = await client.test(scope(), {
    channelType: 'slack',
    channelId: 'channel-1',
    accountId: null,
    peerId: null,
  });

  assert.deepEqual(
    requests.map(({ method, url }) => [method, new URL(url).pathname]),
    [
      ['POST', '/api/v1/agent/bindings'],
      ['PATCH', '/api/v1/agent/bindings/binding-1/enabled'],
      ['DELETE', '/api/v1/agent/bindings/binding-1'],
      ['POST', '/api/v1/agent/bindings/test'],
    ],
  );
  assert.deepEqual(requests[0].body, {
    agent_id: 'agent-1',
    channel_type: 'slack',
    channel_id: 'channel-1',
    priority: 0,
  });
  assert.equal(result.matched, true);
  assert.equal(result.trace[0].selected, true);
  assert.equal(Object.hasOwn(client, 'update'), false);
});

test('Local Agent Bindings client preserves stable structured unavailable authority', async () => {
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url: String(url), init });
    return jsonResponse({
      capability: 'tenant_agent_bindings',
      availability: 'unavailable',
      reason_code: 'local_agent_binding_routing_authority_unavailable',
      service_version: '0.1.0',
      contract_version: '3.0.0',
      allowed_actions: [],
      scope: {
        tenant_id: 'tenant-local',
        project_id: null,
        workspace_id: null,
        instance_id: null,
      },
      authority_revision: 11,
      bindings: [],
      definitions: [],
    });
  };

  const client = createTenantAgentBindingsHttpClient(
    runtimeConfig({
      mode: 'local',
      tenantId: 'tenant-local',
      apiBaseUrl: 'http://127.0.0.1:43121',
    }),
  );
  const snapshot = await client.list({
    authority: 'local',
    tenantId: 'tenant-local',
  });

  assert.equal(
    requests[0].url,
    'http://127.0.0.1:43121/api/v1/agent/bindings?tenant_id=tenant-local',
  );
  assert.equal(
    new Headers(requests[0].init.headers).get('X-Agistack-Launch'),
    'launch-capability',
  );
  assert.equal(snapshot.availability, 'unavailable');
  assert.equal(
    snapshot.reasonCode,
    'local_agent_binding_routing_authority_unavailable',
  );
  assert.deepEqual(snapshot.allowedActions, []);
  assert.deepEqual(snapshot.bindings, []);
  assert.deepEqual(snapshot.definitions, []);
  assert.equal(snapshot.authorityRevision, 11);
});

test('Agent Bindings client fails closed on scope drift and malformed authority', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return jsonResponse([{ id: 'malformed' }]);
  };
  const client = createTenantAgentBindingsHttpClient(runtimeConfig());

  await assert.rejects(
    client.list({ authority: 'cloud', tenantId: 'tenant-other' }),
    /tenant_agent_bindings_runtime_scope_mismatch/u,
  );
  assert.equal(calls, 0);

  await assert.rejects(
    client.list(scope()),
    /cloud_tenant_agent_bindings_contract_invalid/u,
  );
});

function runtimeConfig(overrides = {}) {
  return {
    mode: 'cloud',
    apiBaseUrl: 'https://cloud.example',
    deviceAuthorizationBaseUrl: 'https://cloud.example',
    apiKey: 'cloud-token',
    localApiToken: 'launch-capability',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

function scope() {
  return { authority: 'cloud', tenantId: 'tenant-1' };
}

function binding(overrides = {}) {
  return {
    id: 'binding-1',
    tenant_id: 'tenant-1',
    agent_id: 'agent-1',
    channel_type: 'slack',
    channel_id: 'channel-1',
    account_id: null,
    peer_id: null,
    group_id: null,
    priority: 0,
    enabled: true,
    created_at: '2026-08-03T00:00:00Z',
    specificity_score: 3,
    ...overrides,
  };
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
