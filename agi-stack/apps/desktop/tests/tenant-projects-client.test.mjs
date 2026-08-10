import assert from 'node:assert/strict';
import { test } from 'node:test';

const {
  createTenantProjectsHttpClient,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/tenantProjectsHttpClient.js'
);
const {
  loadTenantProjectsCapability,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/tenantProjectsCapability.js'
);

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test('Cloud Projects client binds list, detail, create, update and delete to the tenant scope', async () => {
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url: String(url), init });
    const path = new URL(String(url)).pathname;
    const method = init?.method ?? 'GET';
    if (path === '/api/v1/auth/me') {
      return jsonResponse({ user_id: 'user-1' });
    }
    if (path === '/api/v1/workspace-context') {
      return jsonResponse({
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: 4,
          updated_at: '2026-07-31T00:00:00Z',
        },
        membership_role: 'admin',
      });
    }
    if (path === '/api/v1/projects/project-1/members') {
      return jsonResponse({
        members: [{ user_id: 'user-1', role: 'owner' }],
        total: 1,
      });
    }
    if (method === 'DELETE') return new Response(null, { status: 204 });
    if (method === 'POST') {
      return jsonResponse(project({ id: 'project-created', name: 'Created' }), 201);
    }
    if (method === 'PUT') {
      return jsonResponse(project({ id: 'project-1', name: 'Updated' }));
    }
    if (String(url).includes('/projects/project-1?')) {
      return jsonResponse(project({ id: 'project-1' }));
    }
    return jsonResponse({
      projects: [project({ id: 'project-1' })],
      total: 1,
      page: 1,
      page_size: 20,
      owner_ids: ['user-1'],
    });
  };

  const client = createTenantProjectsHttpClient(runtimeConfig());
  const scope = { authority: 'cloud', tenantId: 'tenant-1' };
  const list = await client.list(scope, {
    page: 1,
    pageSize: 20,
    search: 'alpha',
    visibility: 'private',
    ownerId: 'user-1',
  });
  const detail = await client.get(scope, 'project-1');
  const created = await client.create(scope, {
    name: 'Created',
    description: 'A project',
  });
  const updated = await client.update(scope, 'project-1', {
    name: 'Updated',
    description: 'Changed',
  });
  await client.delete(scope, 'project-1');

  assert.equal(list.projects[0].tenantId, 'tenant-1');
  assert.equal(list.serviceVersion, '0.1.0');
  assert.deepEqual(list.allowedActions, ['view', 'list', 'create', 'update', 'delete']);
  assert.deepEqual(list.projects[0].allowedActions, ['view', 'update', 'delete']);
  assert.equal(detail.id, 'project-1');
  assert.equal(created.id, 'project-created');
  assert.equal(updated.name, 'Updated');
  assert.deepEqual(
    requests
      .filter(({ url }) => {
        const path = new URL(url).pathname;
        return (
          path !== '/api/v1/auth/me' &&
          path !== '/api/v1/workspace-context' &&
          !path.endsWith('/members')
        );
      })
      .map(({ url, init }) => [new URL(url).pathname, init?.method ?? 'GET']),
    [
      ['/api/v1/projects/', 'GET'],
      ['/api/v1/projects/project-1', 'GET'],
      ['/api/v1/projects/', 'POST'],
      ['/api/v1/projects/project-1', 'PUT'],
      ['/api/v1/projects/project-1', 'DELETE'],
    ],
  );
  const projectRequests = requests.filter(({ url }) =>
    new URL(url).pathname.startsWith('/api/v1/projects'),
  );
  assert.equal(new URL(projectRequests[0].url).searchParams.get('tenant_id'), 'tenant-1');
  assert.equal(new URL(projectRequests[0].url).searchParams.get('search'), 'alpha');
  assert.equal(new URL(projectRequests[2].url).searchParams.get('tenant_id'), 'tenant-1');
  assert.equal(JSON.parse(projectRequests[3].init.body).tenant_id, 'tenant-1');
  assert.match(
    new Headers(projectRequests[3].init.headers).get('Idempotency-Key'),
    /^desktop-project-create-/u,
  );
});

test('Projects client preserves a caller-owned idempotency key across transport retries', async () => {
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url: String(url), init });
    return jsonResponse(
      project({
        id: 'local-replayed',
        tenant_id: 'tenant-local',
        name: 'Retried',
      }),
    );
  };
  const client = createTenantProjectsHttpClient(
    runtimeConfig({
      mode: 'local',
      tenantId: 'tenant-local',
      apiBaseUrl: 'http://127.0.0.1:4777',
    }),
  );
  const scope = { authority: 'local', tenantId: 'tenant-local' };
  const input = { name: 'Retried', description: 'Same logical submission' };
  const options = { idempotencyKey: 'desktop-project-create-stable-retry' };

  await client.create(scope, input, options);
  await client.create(scope, input, options);

  assert.deepEqual(
    requests.map(({ init }) =>
      new Headers(init.headers).get('Idempotency-Key'),
    ),
    [
      'desktop-project-create-stable-retry',
      'desktop-project-create-stable-retry',
    ],
  );
});

test('Cloud Projects exposes only authority-backed actions for an ordinary member', async () => {
  globalThis.fetch = async (url) => {
    const path = new URL(String(url)).pathname;
    if (path === '/api/v1/auth/me') return jsonResponse({ user_id: 'member-1' });
    if (path === '/api/v1/workspace-context') {
      return jsonResponse({
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: 2,
          updated_at: '2026-07-31T00:00:00Z',
        },
        membership_role: 'member',
      });
    }
    if (path === '/api/v1/projects/project-1/members') {
      return jsonResponse({
        members: [{ user_id: 'member-1', role: 'member' }],
        total: 1,
      });
    }
    return jsonResponse({
      projects: [project({ id: 'project-1', owner_id: 'owner-1' })],
      total: 1,
      page: 1,
      page_size: 20,
    });
  };

  const result = await createTenantProjectsHttpClient(runtimeConfig()).list({
    authority: 'cloud',
    tenantId: 'tenant-1',
  });

  assert.deepEqual(result.allowedActions, ['view', 'list']);
  assert.deepEqual(result.projects[0].allowedActions, ['view']);
});

test('Cloud Projects client normalizes nullable optional ProjectResponse fields', async () => {
  globalThis.fetch = async (url) => {
    const path = new URL(String(url)).pathname;
    if (path === '/api/v1/auth/me') return jsonResponse({ user_id: 'user-1' });
    if (path === '/api/v1/workspace-context') {
      return jsonResponse({
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: 4,
          updated_at: '2026-07-31T00:00:00Z',
        },
        membership_role: 'admin',
      });
    }
    if (path === '/api/v1/projects/project-1/members') {
      return jsonResponse({
        members: [{ user_id: 'user-1', role: 'owner' }],
        total: 1,
      });
    }
    return jsonResponse({
      projects: [
        project({
          description: null,
          updated_at: undefined,
          stats: null,
        }),
      ],
      total: 1,
      page: 1,
      page_size: 20,
    });
  };

  const result = await createTenantProjectsHttpClient(runtimeConfig()).list({
    authority: 'cloud',
    tenantId: 'tenant-1',
  });

  assert.equal(result.projects[0].description, '');
  assert.equal(result.projects[0].updatedAt, null);
  assert.deepEqual(result.projects[0].stats, {});
});

test('Local Projects client requires the exact sidecar scope and never accepts cross-tenant rows', async () => {
  globalThis.fetch = async () =>
    jsonResponse({
      projects: [project({ id: 'local-project', tenant_id: 'tenant-local' })],
      total: 1,
      page: 1,
      page_size: 20,
      owner_ids: ['local-user'],
      availability: 'degraded',
      reason_code: 'local_project_configuration_projection_partial',
      service_version: '0.1.0',
      contract_version: '3.0.0',
      allowed_actions: ['view', 'list', 'create', 'update', 'delete'],
      authority_revision: 7,
      scope: {
        tenant_id: 'tenant-local',
        project_id: null,
        workspace_id: null,
        instance_id: null,
      },
    });

  const client = createTenantProjectsHttpClient(
    runtimeConfig({
      mode: 'local',
      tenantId: 'tenant-local',
      apiBaseUrl: 'http://127.0.0.1:4777',
    }),
  );
  const result = await client.list({
    authority: 'local',
    tenantId: 'tenant-local',
  });

  assert.equal(result.availability, 'degraded');
  assert.equal(result.authorityRevision, 7);
  assert.deepEqual(result.allowedActions, ['view', 'list', 'create', 'update', 'delete']);
  assert.equal(result.projects[0].id, 'local-project');

  globalThis.fetch = async () =>
    jsonResponse({
      projects: [project({ tenant_id: 'other-tenant' })],
      total: 1,
      page: 1,
      page_size: 20,
    });
  await assert.rejects(
    client.list({ authority: 'local', tenantId: 'tenant-local' }),
    /local_tenant_projects_contract_invalid/u,
  );
});

test('Tenant Projects capability accepts an ordered safe action subset for Local members', async () => {
  globalThis.fetch = async () =>
    jsonResponse({
      projects: [],
      total: 0,
      page: 1,
      page_size: 1,
      owner_ids: ['local-user'],
      availability: 'degraded',
      reason_code: 'local_project_configuration_projection_partial',
      service_version: '0.1.0',
      contract_version: '3.0.0',
      allowed_actions: ['view', 'list'],
      authority_revision: 7,
      scope: {
        tenant_id: 'tenant-local',
        project_id: null,
        workspace_id: null,
        instance_id: null,
      },
    });

  const capability = await loadTenantProjectsCapability(
    runtimeConfig({
      mode: 'local',
      tenantId: 'tenant-local',
      apiBaseUrl: 'http://127.0.0.1:4777',
    }),
  );

  assert.equal(capability.availability, 'degraded');
  assert.deepEqual(capability.allowed_actions, ['view', 'list']);
});

test('Projects client fails closed before fetch on runtime scope drift', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return jsonResponse({});
  };
  const client = createTenantProjectsHttpClient(runtimeConfig());

  await assert.rejects(
    client.list({ authority: 'cloud', tenantId: 'other-tenant' }),
    /tenant_projects_runtime_scope_mismatch/u,
  );
  assert.equal(calls, 0);
});

function project(overrides = {}) {
  return {
    id: 'project-1',
    tenant_id: 'tenant-1',
    name: 'Alpha',
    description: 'Project Alpha',
    owner_id: 'user-1',
    member_ids: ['user-1'],
    memory_rules: {
      max_episodes: 1000,
      retention_days: 30,
      auto_refresh: true,
      refresh_interval: 24,
    },
    graph_config: {
      max_nodes: 5000,
      max_edges: 10000,
      similarity_threshold: 0.7,
      community_detection: true,
    },
    graph_store_id: null,
    retrieval_store_id: null,
    is_public: false,
    created_at: '2026-07-31T00:00:00Z',
    updated_at: null,
    stats: {},
    ...overrides,
  };
}

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

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
