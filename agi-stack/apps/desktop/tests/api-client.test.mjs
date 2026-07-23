import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const clientModule = require(
  '/tmp/agistack-desktop-test-dist/src/api/client.js'
);
const {
  classifyDeviceTokenError,
  desktopApiCredential,
  desktopLaunchCapability,
  DesktopApiClient,
  DesktopApiError,
  isTaskSessionIdempotencyConflictError,
  isWorkspaceContextUnavailableError,
} = clientModule;
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

function workspaceRecord(index, overrides = {}) {
  return {
    id: `workspace-${index}`,
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    name: `Workspace ${index}`,
    created_by: 'user-1',
    description: null,
    is_archived: false,
    metadata: {},
    office_status: 'idle',
    hex_layout_config: {},
    created_at: '2026-07-19T00:00:00Z',
    updated_at: null,
    ...overrides,
  };
}

function conversationRecord(index, overrides = {}) {
  return {
    id: `conversation-${index}`,
    project_id: 'project-1',
    tenant_id: 'tenant-1',
    user_id: 'user-1',
    title: `Conversation ${index}`,
    status: 'active',
    message_count: 0,
    created_at: '2026-07-19T00:00:00Z',
    updated_at: null,
    summary: null,
    agent_config: null,
    metadata: null,
    conversation_mode: 'single_agent',
    workspace_id: 'workspace-1',
    linked_workspace_task_id: null,
    workspace_name: 'Workspace 1',
    participant_agents: [],
    coordinator_agent_id: null,
    focused_agent_id: null,
    ...overrides,
  };
}

test('workspace context unavailable detection requires the structured server code', () => {
  assert.equal(
    isWorkspaceContextUnavailableError(
      new DesktopApiError('workspace unavailable', 404, {
        detail: { code: 'workspace_context_unavailable' },
      }),
    ),
    true,
  );
  assert.equal(
    isWorkspaceContextUnavailableError(
      new DesktopApiError('project unavailable', 404, {
        detail: { code: 'workspace_context_project_unavailable' },
      }),
    ),
    false,
  );
  assert.equal(
    isWorkspaceContextUnavailableError(
      new DesktopApiError('workspace unavailable', 500, {
        detail: { code: 'workspace_context_unavailable' },
      }),
    ),
    false,
  );
  assert.equal(isWorkspaceContextUnavailableError(new Error('workspace_context_unavailable')), false);
});

test('task-session idempotency conflict requires the exact structured 409 contract', () => {
  assert.equal(
    isTaskSessionIdempotencyConflictError(
      new DesktopApiError('conflict', 409, {
        code: 'TASK_SESSION_IDEMPOTENCY_CONFLICT',
        detail: 'Task session is tombstoned',
      }),
    ),
    true,
  );
  assert.equal(
    isTaskSessionIdempotencyConflictError(
      new DesktopApiError('nested code', 409, {
        detail: { code: 'TASK_SESSION_IDEMPOTENCY_CONFLICT' },
      }),
    ),
    false,
  );
  assert.equal(
    isTaskSessionIdempotencyConflictError(
      new DesktopApiError('wrong status', 400, {
        code: 'TASK_SESSION_IDEMPOTENCY_CONFLICT',
      }),
    ),
    false,
  );
  assert.equal(
    isTaskSessionIdempotencyConflictError(
      new Error('TASK_SESSION_IDEMPOTENCY_CONFLICT'),
    ),
    false,
  );
});

test('identity catalogs exhaust every authoritative page before resolving context', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const tenants = Array.from({ length: 101 }, (_, index) => ({
    id: `tenant-${index + 1}`,
    name: `Tenant ${index + 1}`,
  }));
  const projects = Array.from({ length: 101 }, (_, index) => ({
    id: `project-${index + 1}`,
    tenant_id: 'tenant-101',
    name: `Project ${index + 1}`,
  }));
  globalThis.fetch = async (input) => {
    const url = new URL(String(input));
    calls.push(url);
    const page = Number(url.searchParams.get('page'));
    const pageSize = Number(url.searchParams.get('page_size'));
    const start = (page - 1) * pageSize;
    const items = url.pathname.endsWith('/tenants') ? tenants : projects;
    const key = url.pathname.endsWith('/tenants') ? 'tenants' : 'projects';
    return new Response(
      JSON.stringify({
        [key]: items.slice(start, start + pageSize),
        total: items.length,
        page,
        page_size: pageSize,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'cloud',
      apiBaseUrl: 'https://api.memstack.test',
      apiKey: 'cloud-session',
    });
    assert.equal((await client.listTenants()).at(-1)?.id, 'tenant-101');
    assert.equal((await client.listProjects('tenant-101')).at(-1)?.id, 'project-101');
    assert.deepEqual(
      calls.map((url) => ({
        path: url.pathname,
        tenantId: url.searchParams.get('tenant_id'),
        page: url.searchParams.get('page'),
        pageSize: url.searchParams.get('page_size'),
      })),
      [
        { path: '/api/v1/tenants', tenantId: null, page: '1', pageSize: '100' },
        { path: '/api/v1/tenants', tenantId: null, page: '2', pageSize: '100' },
        {
          path: '/api/v1/projects',
          tenantId: 'tenant-101',
          page: '1',
          pageSize: '100',
        },
        {
          path: '/api/v1/projects',
          tenantId: 'tenant-101',
          page: '2',
          pageSize: '100',
        },
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('identity catalogs fail closed on malformed pages and cross-tenant projects', async () => {
  const originalFetch = globalThis.fetch;
  const client = new DesktopApiClient({
    ...DEFAULT_CONFIG,
    mode: 'cloud',
    apiBaseUrl: 'https://api.memstack.test',
    apiKey: 'cloud-session',
  });

  try {
    for (const payload of [
      { tenants: [{ id: 'tenant-1', name: 'Tenant 1' }], total: 2, page: 2, page_size: 100 },
      { tenants: [{ id: 'tenant-1', name: 'Tenant 1' }], total: 1, page: 1 },
      { tenants: [{ id: '', name: 'Tenant 1' }], total: 1, page: 1, page_size: 100 },
    ]) {
      globalThis.fetch = async () =>
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      await assert.rejects(client.listTenants(), (error) => {
        assert.equal(error instanceof DesktopApiError, true);
        assert.equal(error.status, 502);
        return true;
      });
    }

    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({
          projects: [
            { id: 'project-cross-scope', tenant_id: 'tenant-b', name: 'Foreign project' },
          ],
          total: 1,
          page: 1,
          page_size: 100,
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    await assert.rejects(client.listProjects('tenant-a'), (error) => {
      assert.equal(error instanceof DesktopApiError, true);
      assert.equal(error.status, 502);
      return true;
    });

    globalThis.fetch = async (input) => {
      const url = new URL(String(input));
      const page = Number(url.searchParams.get('page'));
      const firstPage = Array.from({ length: 100 }, (_, index) => ({
        id: `tenant-${index + 1}`,
        name: `Tenant ${index + 1}`,
      }));
      return new Response(
        JSON.stringify({
          tenants: page === 1 ? firstPage : [firstPage[0]],
          total: 101,
          page,
          page_size: 100,
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    };
    await assert.rejects(client.listTenants(), (error) => {
      assert.equal(error instanceof DesktopApiError, true);
      assert.equal(error.status, 502);
      return true;
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('local identity catalogs use the same authoritative page contract', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input) => {
    const url = new URL(String(input));
    calls.push(url);
    const page = Number(url.searchParams.get('page'));
    const pageSize = Number(url.searchParams.get('page_size'));
    const payload = url.pathname.endsWith('/tenants')
      ? {
          tenants: [{ id: 'tenant-local', name: 'Local tenant', role: 'owner' }],
          total: 1,
          page,
          page_size: pageSize,
        }
      : {
          projects: [
            {
              id: 'project-local',
              tenant_id: 'tenant-local',
              name: 'Local project',
              stats: {},
            },
          ],
          total: 1,
          page,
          page_size: pageSize,
        };
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'local',
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'local-session',
      localApiToken: 'launch-capability',
    });
    assert.deepEqual(await client.listTenants(), [
      { id: 'tenant-local', name: 'Local tenant' },
    ]);
    assert.deepEqual(await client.listProjects('tenant-local'), [
      {
        id: 'project-local',
        tenant_id: 'tenant-local',
        name: 'Local project',
        stats: {},
      },
    ]);
    assert.deepEqual(
      calls.map((url) => ({
        path: url.pathname,
        tenantId: url.searchParams.get('tenant_id'),
        page: url.searchParams.get('page'),
        pageSize: url.searchParams.get('page_size'),
      })),
      [
        { path: '/api/v1/tenants', tenantId: null, page: '1', pageSize: '100' },
        {
          path: '/api/v1/projects',
          tenantId: 'tenant-local',
          page: '1',
          pageSize: '100',
        },
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('workspace catalog exhausts every scoped limit-offset page', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const workspaces = Array.from({ length: 501 }, (_, index) =>
    workspaceRecord(index + 1, { ignored_server_field: 'drop-me' }),
  );
  globalThis.fetch = async (input) => {
    const url = new URL(String(input));
    calls.push(url);
    const limit = Number(url.searchParams.get('limit'));
    const offset = Number(url.searchParams.get('offset'));
    return new Response(JSON.stringify(workspaces.slice(offset, offset + limit)), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      tenantId: 'tenant-1',
      projectId: 'project-1',
    });
    const result = await client.listWorkspacesForProject('project-1', 'tenant-1');

    assert.equal(result.length, 501);
    assert.equal(result.at(-1)?.id, 'workspace-501');
    assert.equal(Object.hasOwn(result[0], 'ignored_server_field'), false);
    assert.deepEqual(
      calls.map((url) => ({
        path: url.pathname,
        limit: url.searchParams.get('limit'),
        offset: url.searchParams.get('offset'),
      })),
      [
        {
          path: '/api/v1/tenants/tenant-1/projects/project-1/workspaces',
          limit: '500',
          offset: '0',
        },
        {
          path: '/api/v1/tenants/tenant-1/projects/project-1/workspaces',
          limit: '500',
          offset: '500',
        },
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('workspace catalog fails closed on wrapped, malformed, duplicate, or cross-scope rows', async () => {
  const originalFetch = globalThis.fetch;
  const client = new DesktopApiClient({
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:8088',
    apiKey: 'authenticated-session',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  });

  try {
    for (const payload of [
      { items: [] },
      [workspaceRecord(1, { name: '' })],
      [workspaceRecord(1, { tenant_id: 'tenant-2' })],
      [workspaceRecord(1, { project_id: 'project-2' })],
    ]) {
      globalThis.fetch = async () =>
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      await assert.rejects(
        client.listWorkspacesForProject('project-1', 'tenant-1'),
        (error) => {
          assert.equal(error instanceof DesktopApiError, true);
          assert.equal(error.status, 502);
          return true;
        },
      );
    }

    globalThis.fetch = async (input) => {
      const offset = Number(new URL(String(input)).searchParams.get('offset'));
      const page =
        offset === 0
          ? Array.from({ length: 500 }, (_, index) => workspaceRecord(index + 1))
          : [workspaceRecord(1)];
      return new Response(JSON.stringify(page), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    };
    await assert.rejects(
      client.listWorkspacesForProject('project-1', 'tenant-1'),
      (error) => {
        assert.equal(error instanceof DesktopApiError, true);
        assert.equal(error.status, 502);
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('conversation catalog exhausts every authoritative scoped page', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const conversations = Array.from({ length: 501 }, (_, index) =>
    conversationRecord(index + 1, { ignored_server_field: 'drop-me' }),
  );
  globalThis.fetch = async (input) => {
    const url = new URL(String(input));
    calls.push(url);
    const limit = Number(url.searchParams.get('limit'));
    const offset = Number(url.searchParams.get('offset'));
    const items = conversations.slice(offset, offset + limit);
    const nextOffset = Math.min(offset + limit, conversations.length);
    return new Response(
      JSON.stringify({
        items,
        total: conversations.length,
        has_more: nextOffset < conversations.length,
        offset,
        limit,
        next_offset: nextOffset,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      tenantId: 'tenant-1',
      projectId: 'project-1',
      workspaceId: 'workspace-1',
    });
    const result = await client.listConversations('project-1', 'workspace-1');

    assert.equal(result.items.length, 501);
    assert.equal(result.total, 501);
    assert.equal(Object.hasOwn(result.items[0], 'ignored_server_field'), false);
    assert.deepEqual(
      calls.map((url) => ({
        projectId: url.searchParams.get('project_id'),
        workspaceId: url.searchParams.get('workspace_id'),
        status: url.searchParams.get('status'),
        limit: url.searchParams.get('limit'),
        offset: url.searchParams.get('offset'),
      })),
      [
        {
          projectId: 'project-1',
          workspaceId: 'workspace-1',
          status: 'active',
          limit: '500',
          offset: '0',
        },
        {
          projectId: 'project-1',
          workspaceId: 'workspace-1',
          status: 'active',
          limit: '500',
          offset: '500',
        },
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('conversation catalog retries one transport failure without changing scope', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    if (calls.length === 1) throw new TypeError('Failed to fetch');
    return new Response(
      JSON.stringify({
        items: [conversationRecord(1)],
        total: 1,
        has_more: false,
        offset: 0,
        limit: 500,
        next_offset: null,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      tenantId: 'tenant-1',
      projectId: 'project-1',
      workspaceId: 'workspace-1',
    });
    const result = await client.listConversations('project-1', 'workspace-1');

    assert.deepEqual(result.items.map((item) => item.id), ['conversation-1']);
    assert.equal(calls.length, 2);
    assert.equal(calls[0].input, calls[1].input);
    assert.equal(calls[0].init?.signal, calls[1].init?.signal);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('conversation catalog does not retry HTTP failures or aborted reads', async () => {
  const originalFetch = globalThis.fetch;
  const client = new DesktopApiClient({
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:8088',
    apiKey: 'authenticated-session',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
  });

  try {
    let calls = 0;
    globalThis.fetch = async () => {
      calls += 1;
      return new Response(JSON.stringify({ detail: 'Unavailable' }), {
        status: 503,
        headers: { 'content-type': 'application/json' },
      });
    };
    await assert.rejects(client.listConversations('project-1', 'workspace-1'), (error) => {
      assert.equal(error instanceof DesktopApiError, true);
      assert.equal(error.status, 503);
      return true;
    });
    assert.equal(calls, 1);

    const controller = new AbortController();
    controller.abort();
    calls = 0;
    globalThis.fetch = async (_input, init) => {
      calls += 1;
      throw init?.signal?.reason ?? new DOMException('Aborted', 'AbortError');
    };
    await assert.rejects(
      client.listConversations('project-1', 'workspace-1', controller.signal),
      { name: 'AbortError' },
    );
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('conversation catalog accepts the Rust null terminal cursor', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        items: [conversationRecord(1)],
        total: 1,
        has_more: false,
        offset: 0,
        limit: 500,
        next_offset: null,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      tenantId: 'tenant-1',
      projectId: 'project-1',
      workspaceId: 'workspace-1',
    });
    const result = await client.listConversations('project-1', 'workspace-1');
    assert.deepEqual(result.items.map((item) => item.id), ['conversation-1']);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('conversation catalog fails closed on malformed pagination and scope drift', async () => {
  const originalFetch = globalThis.fetch;
  const client = new DesktopApiClient({
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:8088',
    apiKey: 'authenticated-session',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
  });

  try {
    for (const payload of [
      {
        items: [],
        total: 1,
        has_more: false,
        offset: 0,
        limit: 500,
        next_offset: null,
      },
      {
        items: [conversationRecord(1)],
        total: 2,
        has_more: true,
        offset: 0,
        limit: 500,
        next_offset: 0,
      },
      {
        items: [conversationRecord(1)],
        total: 1,
        has_more: false,
        offset: 1,
        limit: 500,
        next_offset: null,
      },
      {
        items: [conversationRecord(1)],
        total: 1,
        has_more: false,
        offset: 0,
        limit: 100,
        next_offset: null,
      },
      {
        items: [conversationRecord(1)],
        total: Number.MAX_SAFE_INTEGER + 1,
        has_more: false,
        offset: 0,
        limit: 500,
        next_offset: null,
      },
      {
        items: [conversationRecord(1)],
        total: 1,
        has_more: 'false',
        offset: 0,
        limit: 500,
        next_offset: null,
      },
      {
        items: [conversationRecord(1)],
        total: 1,
        has_more: false,
        offset: 0,
        limit: 500,
      },
      {
        items: [conversationRecord(1, { tenant_id: 'tenant-2' })],
        total: 1,
        has_more: false,
        offset: 0,
        limit: 500,
        next_offset: null,
      },
      {
        items: [conversationRecord(1, { project_id: 'project-2' })],
        total: 1,
        has_more: false,
        offset: 0,
        limit: 500,
        next_offset: null,
      },
      {
        items: [conversationRecord(1, { workspace_id: 'workspace-2' })],
        total: 1,
        has_more: false,
        offset: 0,
        limit: 500,
        next_offset: null,
      },
    ]) {
      globalThis.fetch = async () =>
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      await assert.rejects(client.listConversations('project-1', 'workspace-1'), (error) => {
        assert.equal(error instanceof DesktopApiError, true);
        assert.equal(error.status, 502);
        return true;
      });
    }

    for (const secondPageKind of ['duplicate', 'total-drift']) {
      globalThis.fetch = async (input) => {
        const url = new URL(String(input));
        const offset = Number(url.searchParams.get('offset'));
        const firstPage = Array.from({ length: 500 }, (_, index) =>
          conversationRecord(index + 1),
        );
        const items =
          offset === 0
            ? firstPage
            : secondPageKind === 'duplicate'
              ? [conversationRecord(1)]
              : [conversationRecord(501), conversationRecord(502)];
        const total = offset === 500 && secondPageKind === 'total-drift' ? 502 : 501;
        return new Response(
          JSON.stringify({
            items,
            total,
            has_more: offset === 0,
            offset,
            limit: 500,
            next_offset: offset === 0 ? 500 : null,
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        );
      };
      await assert.rejects(client.listConversations('project-1', 'workspace-1'), (error) => {
        assert.equal(error instanceof DesktopApiError, true);
        assert.equal(error.status, 502);
        return true;
      });
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('device authorization client preserves the exact unauthenticated server contract', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    if (calls.length === 3) {
      return new Response(null, { status: 204 });
    }
    const payload =
      calls.length === 1
        ? {
            device_code: 'device-secret',
            user_code: 'ABCD2345',
            verification_uri: '/device',
            verification_uri_complete: '/device?user_code=ABCD2345',
            expires_in: 600,
            interval: 5,
          }
        : { access_token: 'ms_sk_session', token_type: 'Bearer' };
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'must-not-be-sent',
    });

    assert.deepEqual(await client.createDeviceCode(), {
      device_code: 'device-secret',
      user_code: 'ABCD2345',
      verification_uri: '/device',
      verification_uri_complete: '/device?user_code=ABCD2345',
      expires_in: 600,
      interval: 5,
    });
    assert.deepEqual(await client.pollDeviceToken(' device-secret '), {
      access_token: 'ms_sk_session',
      token_type: 'bearer',
    });
    await client.cancelDeviceCode(' device-secret ');

    assert.deepEqual(
      calls.map(({ input, init }) => ({
        url: input,
        method: init?.method,
        authorization: new Headers(init?.headers).get('authorization'),
        body: JSON.parse(String(init?.body)),
      })),
      [
        {
          url: 'http://127.0.0.1:8088/api/v1/auth/device/code',
          method: 'POST',
          authorization: null,
          body: {},
        },
        {
          url: 'http://127.0.0.1:8088/api/v1/auth/device/token',
          method: 'POST',
          authorization: null,
          body: { device_code: 'device-secret' },
        },
        {
          url: 'http://127.0.0.1:8088/api/v1/auth/device/cancel',
          method: 'POST',
          authorization: null,
          body: { device_code: 'device-secret' },
        },
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('device authorization client rejects malformed successful responses', async () => {
  const originalFetch = globalThis.fetch;
  const client = new DesktopApiClient({
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:8088',
  });

  try {
    for (const payload of [
      null,
      {
        device_code: 'device-secret',
        user_code: 'ABCD2345',
        verification_uri: 'https://evil.example/device',
        verification_uri_complete: '/device?user_code=ABCD2345',
        expires_in: 600,
        interval: 5,
      },
      {
        device_code: 'device-secret',
        user_code: 'ABCD2345',
        verification_uri: '/device',
        verification_uri_complete: '/device?user_code=ABCD2345',
        expires_in: '600',
        interval: 5,
      },
      {
        device_code: 'device-secret',
        user_code: 'ABCD2345',
        verification_uri: '/device',
        verification_uri_complete: '/device?user_code=ABCD2345',
        expires_in: 600,
        interval: 0,
      },
      {
        device_code: 'device-secret',
        user_code: 'ABCD2345',
        verification_uri: '/device',
        verification_uri_complete: '/device?user_code=ABCD2345',
        expires_in: 600,
        interval: 5,
        status: 'pending',
      },
      {
        device_code: 'device-secret',
        user_code: 'ABCD1234',
        verification_uri: '/device',
        verification_uri_complete: '/device?user_code=ABCD1234',
        expires_in: 600,
        interval: 5,
      },
      {
        device_code: 'device-secret',
        user_code: 'ABCD234',
        verification_uri: '/device',
        verification_uri_complete: '/device?user_code=ABCD234',
        expires_in: 600,
        interval: 5,
      },
      {
        device_code: 'device-secret',
        user_code: 'ABCD2345',
        verification_uri: '/device',
        verification_uri_complete: '/device?user_code=ABCD2345',
        expires_in: 0,
        interval: 5,
      },
      {
        device_code: 'device-secret',
        user_code: 'ABCD2345',
        verification_uri: '/device',
        verification_uri_complete: '/device?user_code=ABCD2345',
        expires_in: 601,
        interval: 5,
      },
      {
        device_code: 'device-secret',
        user_code: 'ABCD2345',
        verification_uri: '/device',
        verification_uri_complete: '/device?user_code=ABCD2345',
        expires_in: 600,
        interval: 61,
      },
    ]) {
      globalThis.fetch = async () =>
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      await assert.rejects(client.createDeviceCode(), (error) => {
        assert.equal(error instanceof DesktopApiError, true);
        assert.equal(error.status, 502);
        assert.match(error.message, /Invalid device code response/);
        assert.deepEqual(error.payload, { detail: 'invalid_device_code_response' });
        return true;
      });
    }

    for (const payload of [
      {},
      { access_token: '', token_type: 'bearer' },
      { access_token: 'ms_sk_session', token_type: 1 },
      { access_token: 'ms_sk_session', token_type: 'mac' },
      { access_token: 'ms_sk_session', token_type: 'bearer', expires_in: 3600 },
    ]) {
      globalThis.fetch = async () =>
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      await assert.rejects(client.pollDeviceToken('device-secret'), (error) => {
        assert.equal(error instanceof DesktopApiError, true);
        assert.equal(error.status, 502);
        assert.match(error.message, /Invalid device token response/);
        assert.deepEqual(error.payload, { detail: 'invalid_device_token_response' });
        return true;
      });
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('device token polling preserves pending and expired errors for the caller', async () => {
  const originalFetch = globalThis.fetch;
  const client = new DesktopApiClient({
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:8088',
  });

  try {
    for (const response of [
      {
        status: 428,
        payload: { detail: { error: 'authorization_pending', interval: 5 } },
      },
      { status: 410, payload: { detail: 'expired_token' } },
    ]) {
      globalThis.fetch = async () =>
        new Response(JSON.stringify(response.payload), {
          status: response.status,
          headers: { 'content-type': 'application/json' },
        });
      await assert.rejects(client.pollDeviceToken('device-secret'), (error) => {
        assert.equal(error instanceof DesktopApiError, true);
        assert.equal(error.status, response.status);
        assert.deepEqual(error.payload, response.payload);
        assert.deepEqual(
          classifyDeviceTokenError(error),
          response.status === 428
            ? { code: 'authorization_pending', interval: 5 }
            : { code: 'expired_token' },
        );
        return true;
      });
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('device token error classification rejects message and malformed payload guesses', () => {
  assert.equal(
    classifyDeviceTokenError(new Error('authorization_pending; retry in 5 seconds')),
    null,
  );
  assert.equal(
    classifyDeviceTokenError(
      new DesktopApiError('authorization_pending', 428, {
        detail: { error: 'authorization_pending', interval: '5' },
      }),
    ),
    null,
  );
  assert.equal(
    classifyDeviceTokenError(
      new DesktopApiError('expired_token', 400, { detail: 'expired_token' }),
    ),
    null,
  );
  assert.deepEqual(
    classifyDeviceTokenError(
      new DesktopApiError('expired_token', 410, {
        detail: { error: 'expired_token' },
      }),
    ),
    { code: 'expired_token' },
  );
});

test('device token error classification accepts protocol errors from another JavaScript realm', () => {
  assert.deepEqual(
    classifyDeviceTokenError({
      name: 'DesktopApiError',
      status: 428,
      payload: { detail: { error: 'authorization_pending', interval: 5 } },
    }),
    { code: 'authorization_pending', interval: 5 },
  );
});

test('conversation history requests preserve forward and backward cursor pairs', async () => {
  let requestUrl = null;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    requestUrl = new URL(String(input));
    return new Response(JSON.stringify({ conversationId: 'conversation/1', timeline: [] }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      projectId: 'project/1',
    });
    await client.getConversationMessages('conversation/1', 'project/1', {
      limit: 75,
      fromTimeUs: 1_000,
      fromCounter: 4,
      beforeTimeUs: 2_000,
      beforeCounter: 7,
    });

    assert.equal(requestUrl?.pathname, '/api/v1/agent/conversations/conversation%2F1/messages');
    assert.deepEqual(Object.fromEntries(requestUrl?.searchParams ?? []), {
      project_id: 'project/1',
      limit: '75',
      from_time_us: '1000',
      from_counter: '4',
      before_time_us: '2000',
      before_counter: '7',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('conversation execution carries an explicit structured workload role', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return new Response(JSON.stringify({ queued: true }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      projectId: 'project-1',
    });
    await client.runAgentMessage(
      'conversation-1',
      'Analyze the attached image.',
      'message-1',
      'project-1',
      'vision',
    );

    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      project_id: 'project-1',
      message: 'Analyze the attached image.',
      message_id: 'message-1',
      workload_role: 'vision',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('workspace context requests preserve the authoritative revision contract', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    const context = {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      revision: calls.length - 1,
      updated_at: '2026-07-14T00:00:00Z',
    };
    return new Response(
      JSON.stringify(
        calls.length === 1
          ? { context, membership_role: 'owner' }
          : { context, changed: true },
      ),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
    });
    const current = await client.getWorkspaceContext();
    const switched = await client.switchWorkspaceContext(
      'tenant-1',
      'project-1',
      current.context.revision,
      'context-switch-1',
    );

    assert.equal(current.membership_role, 'owner');
    assert.equal(switched.context.revision, 1);
    assert.deepEqual(
      calls.map((call) => [String(call.input), call.init?.method ?? 'GET']),
      [
        ['http://127.0.0.1:8088/api/v1/workspace-context', 'GET'],
        ['http://127.0.0.1:8088/api/v1/workspace-context/switch', 'POST'],
      ],
    );
    assert.deepEqual(JSON.parse(String(calls[1].init.body)), {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      expected_revision: 0,
      idempotency_key: 'context-switch-1',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('workspace roster requests stay inside the selected scope', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    const url = String(input);
    calls.push(url);
    const payload = url.includes('/members?')
      ? [
          {
            id: 'member-1',
            workspace_id: 'workspace/1',
            user_id: 'user-1',
            user_email: 'member@example.com',
            role: 'owner',
            invited_by: null,
            created_at: '2026-07-15T00:00:00Z',
            updated_at: null,
          },
        ]
      : [
          {
            id: 'binding-1',
            workspace_id: 'workspace/1',
            agent_id: 'agent-1',
            display_name: 'Planner',
            description: null,
            config: {},
            is_active: true,
            hex_q: null,
            hex_r: null,
            theme_color: null,
            label: null,
            status: 'idle',
            created_at: '2026-07-15T00:00:00Z',
            updated_at: null,
          },
        ];
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      tenantId: 'tenant/1',
      projectId: 'project/1',
      workspaceId: 'workspace/1',
    });

    const [members, agents] = await Promise.all([
      client.listWorkspaceMembers(),
      client.listWorkspaceAgents(),
    ]);

    assert.equal(members[0].user_email, 'member@example.com');
    assert.equal(agents[0].display_name, 'Planner');
    const rosterBaseUrl =
      'http://127.0.0.1:8088/api/v1/tenants/tenant%2F1/projects/project%2F1' +
      '/workspaces/workspace%2F1';
    assert.deepEqual(calls.sort(), [
      `${rosterBaseUrl}/agents?active_only=true&limit=500&offset=0`,
      `${rosterBaseUrl}/members?limit=500&offset=0`,
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('workspace roster requests reject wrapped collections', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ items: [] }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      tenantId: 'tenant-1',
      projectId: 'project-1',
      workspaceId: 'workspace-1',
    });

    await assert.rejects(client.listWorkspaceMembers(), (error) => {
      assert.equal(error instanceof DesktopApiError, true);
      assert.equal(error.status, 502);
      assert.match(error.message, /Invalid workspace members response/);
      return true;
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('workspace roster requests reject malformed and cross-scope rows', async () => {
  const originalFetch = globalThis.fetch;
  const client = new DesktopApiClient({
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:8088',
    apiKey: 'authenticated-session',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
  });

  try {
    for (const payload of [
      [null],
      [{ id: 'member-1', workspace_id: 'workspace-1', user_id: 'user-1' }],
      [
        {
          id: 'member-1',
          workspace_id: 'workspace-2',
          user_id: 'user-1',
          role: 'owner',
        },
      ],
    ]) {
      globalThis.fetch = async () =>
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      await assert.rejects(client.listWorkspaceMembers(), (error) => {
        assert.equal(error instanceof DesktopApiError, true);
        assert.equal(error.status, 502);
        return true;
      });
    }

    globalThis.fetch = async () =>
      new Response(
        JSON.stringify([
          {
            id: 'binding-1',
            workspace_id: 'workspace-1',
            agent_id: 'agent-1',
          },
        ]),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    await assert.rejects(client.listWorkspaceAgents(), (error) => {
      assert.equal(error instanceof DesktopApiError, true);
      assert.equal(error.status, 502);
      return true;
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('workspace member roster exhausts every authoritative page', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    const url = String(input);
    calls.push(url);
    const offset = new URL(url).searchParams.get('offset');
    const items =
      offset === '0'
        ? Array.from({ length: 500 }, (_, index) => ({
            id: `member-${index}`,
            workspace_id: 'workspace-1',
            user_id: `user-${index}`,
            role: 'member',
          }))
        : [
            {
              id: 'member-500',
              workspace_id: 'workspace-1',
              user_id: 'user-500',
              role: 'member',
            },
          ];
    return new Response(JSON.stringify(items), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      tenantId: 'tenant-1',
      projectId: 'project-1',
      workspaceId: 'workspace-1',
    });

    const members = await client.listWorkspaceMembers();

    assert.equal(members.length, 501);
    assert.deepEqual(
      calls.map((url) => new URL(url).searchParams.get('offset')),
      ['0', '500'],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('conversation session authority request preserves scoped identity without legacy fallback', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    calls.push(String(input));
    return new Response(
      JSON.stringify({
        schema_version: 1,
        conversation: { id: 'conversation/1' },
        snapshot_revision: 'snapshot-1',
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
    });
    const payload = await client.getConversationSession('conversation/1', {
      tenantId: 'tenant/1',
      projectId: 'project/1',
      workspaceId: 'workspace/1',
    });

    assert.equal(payload.snapshot_revision, 'snapshot-1');
    assert.deepEqual(calls, [
      'http://127.0.0.1:8088/api/v1/agent/conversations/conversation%2F1/session?tenant_id=tenant%2F1&project_id=project%2F1&workspace_id=workspace%2F1',
    ]);
    assert.equal(clientModule.isLegacyConversationSessionRouteMissing, undefined);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('plan workflow preflight proves route support without creating server artifacts', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  const responses = [
    new Response(JSON.stringify({
      schema_version: 2,
      atomic_creation: true,
      initial_conversation_mode: 'workspace',
      initial_plan_mode: 'plan',
    }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }),
    new Response(JSON.stringify({
      schema_version: 1,
      atomic_creation: false,
      initial_conversation_mode: 'workspace',
      initial_plan_mode: 'plan',
    }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }),
    new Response('Not Found', {
      status: 404,
      headers: { 'content-type': 'text/plain' },
    }),
  ];
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return responses.shift();
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      tenantId: 'tenant-1',
      projectId: 'project-1',
    });

    assert.equal(await client.supportsAgentPlanWorkflow(), true);
    assert.equal(await client.supportsAgentPlanWorkflow(), false);
    assert.equal(await client.supportsAgentPlanWorkflow(), false);
    assert.deepEqual(
      calls.map((call) => [String(call.input), call.init?.method ?? 'GET', call.init?.body]),
      [
        [
          'http://127.0.0.1:8088/api/v1/tenants/tenant-1/projects/project-1/task-sessions/capabilities',
          'GET',
          undefined,
        ],
        [
          'http://127.0.0.1:8088/api/v1/tenants/tenant-1/projects/project-1/task-sessions/capabilities',
          'GET',
          undefined,
        ],
        [
          'http://127.0.0.1:8088/api/v1/tenants/tenant-1/projects/project-1/task-sessions/capabilities',
          'GET',
          undefined,
        ],
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('respondToHitl sends the authenticated unified HITL payload', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({ success: true, message: 'Decision response received' }),
      {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'stale-cloud-token',
      localApiToken: 'local-session-token',
    });

    await client.respondToHitl({
      requestId: 'request-1',
      hitlType: 'decision',
      responseData: { decision: 'approve' },
    });

    assert.equal(calls.length, 1);
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/agent/hitl/respond'
    );
    assert.equal(
      new Headers(calls[0]?.init?.headers).get('Authorization'),
      'Bearer stale-cloud-token'
    );
    assert.equal(
      new Headers(calls[0]?.init?.headers).get('X-Agistack-Launch'),
      'local-session-token'
    );
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      request_id: 'request-1',
      hitl_type: 'decision',
      response_data: { decision: 'approve' },
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('authoritative run controls preserve run identity and expected revision', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        accepted: true,
        status: 'pause_requested',
        run: { id: 'run/1', status: 'running', revision: 7 },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      localApiToken: 'launch-capability',
    });

    await client.pauseRun('run/1', 7);
    await client.resumeRun('run/1', 8);
    await client.cancelRun('run/1', 9);

    assert.deepEqual(
      calls.map((call) => [String(call.input), JSON.parse(String(call.init?.body))]),
      [
        [
          'http://127.0.0.1:8088/api/v1/agent/runs/run%2F1/pause',
          { expected_revision: 7 },
        ],
        [
          'http://127.0.0.1:8088/api/v1/agent/runs/run%2F1/resume',
          { expected_revision: 8 },
        ],
        [
          'http://127.0.0.1:8088/api/v1/agent/runs/run%2F1/cancel',
          { expected_revision: 9 },
        ],
      ]
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('run changes and structured inputs preserve snapshot, revision, and delivery contracts', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    const url = String(input);
    if (url.includes('/changes?')) {
      return new Response(
        JSON.stringify({ id: 'snapshot-1', run_id: 'run/1', run_revision: 7, status: 'ready' }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      );
    }
    if (url.endsWith('/inputs') && init?.method !== 'POST') {
      return new Response(
        JSON.stringify({ run_id: 'run/1', run_revision: 7, inputs: [], total_count: 0 }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      );
    }
    if (url.endsWith('/promote-to-plan')) {
      return new Response(
        JSON.stringify({
          accepted: true,
          created: true,
          action: 'start_plan_turn',
          input: { id: 'input-1', status: 'promoted_to_plan' },
          conversation: { id: 'conversation-1', current_mode: 'plan' },
          source_run: { id: 'run/1', revision: 8, status: 'completed' },
        }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      );
    }
    return new Response(
      JSON.stringify({
        accepted: true,
        created: true,
        action: 'send_message',
        conversation_id: 'conversation-1',
        message_id: 'message-1',
        delivery_mode: 'steer_now',
        run_id: 'run/1',
        run_revision: 7,
        queue_position: null,
        input: { id: 'input-1', status: 'pending_boundary' },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });
    await client.getRunChanges('run/1', 7);
    await client.createRunInput('run/1', {
      expectedRunRevision: 7,
      message: 'Keep the API stable',
      messageId: 'message-1',
      idempotencyKey: 'input-request-1',
      delivery: 'steer_now',
      references: [
        {
          type: 'code_range',
          snapshot_id: 'snapshot-1',
          environment_id: 'environment-1',
          path: 'src/lib.rs',
          start_line: 12,
          end_line: 12,
          side: 'new',
          patch_digest: 'patch-1',
        },
      ],
    });
    await client.listRunInputs('run/1');
    await client.promoteRunInput('input/1', 8, 'promote-input-1');

    assert.equal(
      String(calls[0].input),
      'http://127.0.0.1:8088/api/v1/agent/runs/run%2F1/changes?expected_revision=7'
    );
    assert.equal(
      String(calls[1].input),
      'http://127.0.0.1:8088/api/v1/agent/runs/run%2F1/inputs'
    );
    assert.deepEqual(JSON.parse(String(calls[1].init.body)), {
      expected_run_revision: 7,
      message: 'Keep the API stable',
      message_id: 'message-1',
      idempotency_key: 'input-request-1',
      delivery: 'steer_now',
      references: [
        {
          type: 'code_range',
          snapshot_id: 'snapshot-1',
          environment_id: 'environment-1',
          path: 'src/lib.rs',
          start_line: 12,
          end_line: 12,
          side: 'new',
          patch_digest: 'patch-1',
        },
      ],
    });
    assert.equal(
      String(calls[2].input),
      'http://127.0.0.1:8088/api/v1/agent/runs/run%2F1/inputs'
    );
    assert.equal(
      String(calls[3].input),
      'http://127.0.0.1:8088/api/v1/agent/run-inputs/input%2F1/promote-to-plan'
    );
    assert.deepEqual(JSON.parse(String(calls[3].init.body)), {
      expected_source_run_revision: 8,
      idempotency_key: 'promote-input-1',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('forkRecoveryRun binds one recovery fork to the source run revision', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        accepted: true,
        created: true,
        status: 'running',
        source_run: { id: 'run/1', status: 'disconnected', revision: 4 },
        run: { id: 'run/2', status: 'running', revision: 2 },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });

    const result = await client.forkRecoveryRun(
      'run/1',
      4,
      'desktop-recovery-fork:run/1:4'
    );

    assert.equal(result.run.id, 'run/2');
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/agent/runs/run%2F1/fork'
    );
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      expected_revision: 4,
      idempotency_key: 'desktop-recovery-fork:run/1:4',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('startTerminal requests a terminal scoped to the authoritative run environment', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        success: true,
        session_id: 'terminal-1',
        run_id: 'run/1',
        run_revision: 7,
        conversation_id: 'conversation-1',
        project_id: 'project-1',
        environment_id: 'environment-1',
        resumable: false,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      projectId: 'project-1',
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });

    await client.startTerminal('run/1', 7);

    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/projects/project-1/sandbox/terminal'
    );
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      run_id: 'run/1',
      expected_run_revision: 7,
    });
    assert.equal(
      client.terminalProxyUrl('terminal/1', 'bound/project'),
      'ws://127.0.0.1:8088/api/v1/projects/bound%2Fproject/sandbox/terminal/proxy/ws?session_id=terminal%2F1',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('automation reads and capability authority stay project scoped', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    const url = String(input);
    if (url.endsWith('/runs?limit=50&offset=0')) {
      return new Response(JSON.stringify({ items: [], total: 0 }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (url.includes('/cron-jobs/automation%2F1')) {
      return new Response(
        JSON.stringify({ id: 'automation/1', project_id: 'project/1', name: 'Review' }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    return new Response(JSON.stringify({ items: [], total: 0 }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      projectId: 'project/1',
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
    });

    await client.listAutomations();
    await client.getAutomationCapabilities();
    await client.getAutomation('automation/1');
    await client.listAutomationRuns('automation/1');

    assert.deepEqual(
      calls.map((call) => String(call.input)),
      [
        'http://127.0.0.1:8088/api/v1/projects/project%2F1/cron-jobs?include_disabled=true&limit=100&offset=0',
        'http://127.0.0.1:8088/api/v1/projects/project%2F1/cron-jobs/capabilities',
        'http://127.0.0.1:8088/api/v1/projects/project%2F1/cron-jobs/automation%2F1',
        'http://127.0.0.1:8088/api/v1/projects/project%2F1/cron-jobs/automation%2F1/runs?limit=50&offset=0',
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('automation mutations carry idempotency and revision authority in the request body', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    if (init?.method === 'DELETE') return new Response(null, { status: 204 });
    return new Response(JSON.stringify({ id: 'automation/1', revision: 2 }), {
      status: init?.method === 'POST' && !String(input).endsWith('/toggle') ? 201 : 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      projectId: 'project/1',
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
    });
    const create = {
      idempotency_key: 'create-1',
      name: 'Daily brief',
      schedule: { kind: 'cron', config: { expression: '0 9 * * *' } },
      payload: { kind: 'agent_turn', config: { message: 'Prepare brief' } },
    };

    await client.createAutomation(create);
    await client.updateAutomation('automation/1', {
      idempotency_key: 'update-1',
      expected_revision: 1,
      name: 'Weekday brief',
    });
    await client.toggleAutomation('automation/1', {
      idempotency_key: 'toggle-1',
      expected_revision: 2,
      enabled: false,
    });
    await client.deleteAutomation('automation/1', {
      idempotency_key: 'delete-1',
      expected_revision: 3,
    });

    assert.deepEqual(
      calls.map((call) => [String(call.input), call.init?.method, JSON.parse(call.init?.body)]),
      [
        [
          'http://127.0.0.1:8088/api/v1/projects/project%2F1/cron-jobs',
          'POST',
          create,
        ],
        [
          'http://127.0.0.1:8088/api/v1/projects/project%2F1/cron-jobs/automation%2F1',
          'PATCH',
          { idempotency_key: 'update-1', expected_revision: 1, name: 'Weekday brief' },
        ],
        [
          'http://127.0.0.1:8088/api/v1/projects/project%2F1/cron-jobs/automation%2F1/toggle',
          'POST',
          { idempotency_key: 'toggle-1', expected_revision: 2, enabled: false },
        ],
        [
          'http://127.0.0.1:8088/api/v1/projects/project%2F1/cron-jobs/automation%2F1',
          'DELETE',
          { idempotency_key: 'delete-1', expected_revision: 3 },
        ],
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('listMyWork loads the project-scoped authoritative attention queue', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        project_id: 'project/1',
        total: 2,
        items: [
          {
            id: 'run-1',
            authority_kind: 'desktop_run',
            authority_id: 'run-1',
            run_id: 'run-1',
            conversation_id: 'conversation-1',
            project_id: 'project/1',
            title: 'Review the run',
            capability_mode: 'code',
            group: 'ready_review',
            status: 'ready_review',
            required_action: 'review_result',
            revision: 4,
            permission_profile: 'workspace_write',
            attempt_number: null,
            created_at: '2026-07-13T00:00:00Z',
            updated_at: '2026-07-13T00:05:00Z',
          },
          {
            id: 'attempt-2',
            authority_kind: 'workspace_attempt',
            authority_id: 'attempt-2',
            run_id: null,
            conversation_id: 'conversation-2',
            workspace_id: 'workspace-1',
            project_id: 'project/1',
            title: 'Execute the workspace task',
            capability_mode: null,
            group: 'running',
            status: 'running',
            required_action: 'observe',
            revision: null,
            permission_profile: null,
            attempt_number: 2,
            environment: null,
            created_at: '2026-07-13T00:00:00Z',
            updated_at: '2026-07-13T00:06:00Z',
            last_heartbeat_at: null,
          },
        ],
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      localApiToken: 'launch-capability',
    });

    const result = await client.listMyWork('project/1');

    assert.equal(result.items[0]?.group, 'ready_review');
    assert.equal(result.items[0]?.authority_kind, 'desktop_run');
    assert.equal(result.items[1]?.authority_kind, 'workspace_attempt');
    assert.equal(result.items[1]?.permission_profile, null);
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/projects/project%2F1/my-work'
    );
    assert.equal(
      new Headers(calls[0]?.init?.headers).get('Authorization'),
      'Bearer authenticated-session'
    );
    assert.equal(
      new Headers(calls[0]?.init?.headers).get('X-Agistack-Launch'),
      'launch-capability'
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('reviewRun sends explicit approval or change feedback against one revision', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        accepted: true,
        status: 'completed',
        run: { id: 'run-1', status: 'completed', revision: 5 },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });

    await client.reviewRun('run-1', {
      action: 'request_changes',
      expectedRevision: 4,
      feedback: 'Add the missing verification evidence.',
    });

    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/agent/runs/run-1/review'
    );
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      action: 'request_changes',
      expected_revision: 4,
      feedback: 'Add the missing verification evidence.',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('artifact review and delivery stay bound to immutable version revisions', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        accepted: true,
        status: 'approved',
        artifact_version: { id: 'artifact/version-2', status: 'approved', revision: 4 },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });

    await client.reviewArtifactVersion('artifact/version-2', {
      action: 'request_changes',
      expectedRevision: 3,
      runExpectedRevision: 8,
      feedback: 'Include the missing provenance.',
    });
    await client.deliverArtifactVersion('artifact/version-2', {
      expectedRevision: 4,
      idempotencyKey: 'artifact/version-2:4:deliver',
      destination: 'local_workspace',
    });

    assert.deepEqual(
      calls.map((call) => [String(call.input), JSON.parse(String(call.init?.body))]),
      [
        [
          'http://127.0.0.1:8088/api/v1/agent/artifact-versions/artifact%2Fversion-2/review',
          {
            action: 'request_changes',
            expected_revision: 3,
            run_expected_revision: 8,
            feedback: 'Include the missing provenance.',
          },
        ],
        [
          'http://127.0.0.1:8088/api/v1/agent/artifact-versions/artifact%2Fversion-2/deliver',
          {
            expected_revision: 4,
            idempotency_key: 'artifact/version-2:4:deliver',
            destination: 'local_workspace',
          },
        ],
      ]
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('desktop identity credentials stay separate from the Tauri launch capability', () => {
  assert.equal(
    desktopApiCredential({
      ...DEFAULT_CONFIG,
      apiKey: 'manual-local-key',
      localApiToken: '',
    }),
    'manual-local-key'
  );
  assert.equal(
    desktopApiCredential({
      ...DEFAULT_CONFIG,
      apiKey: 'manual-local-key',
      localApiToken: 'tauri-capability',
    }),
    'manual-local-key'
  );
  assert.equal(
    desktopLaunchCapability({
      ...DEFAULT_CONFIG,
      apiKey: 'authenticated-session',
      localApiToken: 'tauri-capability',
    }),
    'tauri-capability'
  );
});

test('agent WebSocket keeps launch and identity credentials in separate subprotocols', () => {
  const client = new DesktopApiClient({
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:8088',
    apiKey: 'authenticated-session',
    localApiToken: 'tauri-capability',
  });

  const url = client.agentWsUrl('session-1');
  assert.equal(url, 'ws://127.0.0.1:8088/api/v1/agent/ws?session_id=session-1');
  assert.doesNotMatch(url, /tauri-capability/);
  assert.deepEqual(client.agentWsProtocols(), [
    'memstack.launch',
    'tauri-capability',
    'memstack.auth',
    'authenticated-session',
  ]);
});

test('local session bootstrap and context switch preserve the dual credential boundary', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(JSON.stringify({ success: true, context: {} }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const bootstrap = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: '',
      localApiToken: 'tauri-capability',
    });
    await bootstrap.createLocalSession(false);

    const authenticated = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'authenticated-session',
      localApiToken: 'tauri-capability',
    });
    await authenticated.switchWorkspaceContext('orbital', 'agent-evals', 4, 'switch-5');
    await authenticated.signOut();

    const bootstrapHeaders = new Headers(calls[0]?.init?.headers);
    assert.equal(bootstrapHeaders.get('Authorization'), null);
    assert.equal(bootstrapHeaders.get('X-Agistack-Launch'), 'tauri-capability');
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), { trusted_device: false });

    const switchHeaders = new Headers(calls[1]?.init?.headers);
    assert.equal(switchHeaders.get('Authorization'), 'Bearer authenticated-session');
    assert.equal(switchHeaders.get('X-Agistack-Launch'), 'tauri-capability');
    assert.deepEqual(JSON.parse(String(calls[1]?.init?.body)), {
      tenant_id: 'orbital',
      project_id: 'agent-evals',
      expected_revision: 4,
      idempotency_key: 'switch-5',
    });
    assert.equal(
      String(calls[2]?.input),
      'http://127.0.0.1:8088/api/v1/auth/signout',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('trusted local resume sends only the launch capability and non-secret session reference', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    if (calls.length === 2) {
      return new Response(JSON.stringify({ detail: 'trusted local session unavailable' }), {
        status: 401,
        headers: { 'content-type': 'application/json' },
      });
    }
    return new Response(
      JSON.stringify({
        access_token: 'rotated-bearer',
        token_type: 'bearer',
        must_change_password: false,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'stale-bearer-must-not-be-sent',
      localApiToken: 'current-launch-capability',
    });
    const resumed = await client.resumeLocalSession('local-session-1');
    const unavailable = await client.resumeLocalSession('revoked-session');

    assert.equal(resumed?.access_token, 'rotated-bearer');
    assert.equal(unavailable, null);
    const headers = new Headers(calls[0]?.init?.headers);
    assert.equal(headers.get('Authorization'), null);
    assert.equal(headers.get('X-Agistack-Launch'), 'current-launch-capability');
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      session_id: 'local-session-1',
    });
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/auth/local-session/resume',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('createAgentConversation preserves the explicit Work or Code capability', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        id: 'conversation-1',
        project_id: 'project-1',
        agent_config: { capability_mode: 'code' },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });

    await client.createAgentConversation('Implement review flow', 'project-1', 'code');

    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      project_id: 'project-1',
      title: 'Implement review flow',
      agent_config: {
        selected_agent_id: 'builtin:all-access',
        capability_mode: 'code',
      },
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('updateAgentConversationMode can switch the active capability explicitly', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        id: 'conversation-1',
        project_id: 'project-1',
        agent_config: { capability_mode: 'work' },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });

    await client.updateAgentConversationMode(
      'conversation-1',
      { capability_mode: 'work' },
      'project-1'
    );

    assert.equal(calls[0]?.init?.method, 'PATCH');
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      capability_mode: 'work',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('updateAgentConversationConfig persists and clears a scoped model override', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        id: 'conversation-1',
        project_id: 'project-1',
        agent_config: { llm_model_override: null },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });

    await client.updateAgentConversationConfig(
      'conversation/1',
      { llm_model_override: 'gpt-reasoning' },
      'project/1'
    );
    await client.updateAgentConversationConfig(
      'conversation/1',
      { llm_model_override: null },
      'project/1'
    );

    assert.equal(calls[0]?.init?.method, 'PATCH');
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/agent/conversations/conversation%2F1/config?project_id=project%2F1'
    );
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      llm_model_override: 'gpt-reasoning',
    });
    assert.deepEqual(JSON.parse(String(calls[1]?.init?.body)), {
      llm_model_override: null,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('createTaskSession posts one strictly scoped atomic task-session contract', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        replayed: false,
        workspace: workspaceRecord(1, {
          tenant_id: 'tenant/1',
          project_id: 'project/1',
          name: 'Atomic task',
        }),
        conversation: conversationRecord(1, {
          tenant_id: 'tenant/1',
          project_id: 'project/1',
          title: 'Atomic task',
          conversation_mode: 'workspace',
          current_mode: 'plan',
          workspace_id: 'workspace-1',
          workspace_name: 'Atomic task',
          agent_config: {
            selected_agent_id: 'builtin:all-access',
            capability_mode: 'code',
          },
        }),
        initial_message: {
          id: 'message-1',
          workspace_id: 'workspace-1',
          sender_id: 'user-1',
          sender_type: 'human',
          content: 'Create the reviewable plan',
          mentions: [],
          parent_message_id: null,
          metadata: {
            source: 'task_session',
            conversation_id: 'conversation-1',
          },
          created_at: '2026-07-19T00:00:00Z',
        },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      tenantId: 'tenant/1',
      projectId: 'project/1',
      localApiToken: 'local-session-token',
    });
    const request = {
      idempotency_key: 'desktop-task-session-1',
      workspace: {
        kind: 'create',
        name: 'Atomic task',
        description: 'Create the reviewable plan',
        metadata: { source: 'desktop' },
        use_case: 'programming',
        collaboration_mode: 'multi_agent_shared',
        sandbox_code_root: '/workspace/repository',
      },
      conversation: { title: 'Atomic task', capability_mode: 'code' },
      initial_message: { content: 'Create the reviewable plan' },
    };

    const result = await client.createTaskSession(request);

    assert.equal(result.replayed, false);
    assert.equal(result.conversation.workspace_id, result.workspace.id);
    assert.equal(calls.length, 1);
    assert.equal(calls[0]?.init?.method, 'POST');
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/tenants/tenant%2F1/projects/project%2F1/task-sessions',
    );
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), request);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('createTaskSession retries one transport failure with the identical idempotent request', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const request = {
    idempotency_key: 'desktop-task-session-retry-1',
    workspace: { kind: 'existing', workspace_id: 'workspace-1' },
    conversation: { title: 'Retry atomic task', capability_mode: 'work' },
    initial_message: { content: 'Create the reviewable plan' },
  };
  const payload = {
    replayed: false,
    workspace: workspaceRecord(1),
    conversation: conversationRecord(1, {
      title: request.conversation.title,
      conversation_mode: 'workspace',
      current_mode: 'plan',
      workspace_id: 'workspace-1',
      agent_config: {
        selected_agent_id: 'builtin:all-access',
        capability_mode: 'work',
      },
    }),
    initial_message: {
      id: 'message-retry-1',
      workspace_id: 'workspace-1',
      sender_id: 'user-1',
      sender_type: 'human',
      content: request.initial_message.content,
      mentions: [],
      parent_message_id: null,
      metadata: {
        source: 'task_session',
        conversation_id: 'conversation-1',
      },
      created_at: '2026-07-19T00:00:00Z',
    },
  };
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    if (calls.length === 1) throw new TypeError('Failed to fetch');
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      tenantId: 'tenant-1',
      projectId: 'project-1',
    });

    const result = await client.createTaskSession(request);

    assert.equal(result.conversation.id, 'conversation-1');
    assert.equal(calls.length, 2);
    assert.equal(String(calls[0]?.input), String(calls[1]?.input));
    assert.equal(calls[0]?.init?.body, calls[1]?.init?.body);
    assert.deepEqual(JSON.parse(String(calls[1]?.init?.body)), request);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('createTaskSession rejects malformed, cross-scope, unbound, or non-Plan success payloads', async () => {
  const request = {
    idempotency_key: 'desktop-task-session-1',
    workspace: { kind: 'existing', workspace_id: 'workspace-1' },
    conversation: { title: 'Atomic task', capability_mode: 'code' },
    initial_message: { content: 'Create the reviewable plan' },
  };
  const validPayload = {
    replayed: false,
    workspace: workspaceRecord(1, { name: 'Atomic task' }),
    conversation: conversationRecord(1, {
      title: 'Atomic task',
      conversation_mode: 'workspace',
      current_mode: 'plan',
      workspace_id: 'workspace-1',
      workspace_name: 'Atomic task',
      agent_config: {
        selected_agent_id: 'builtin:all-access',
        capability_mode: 'code',
      },
    }),
    initial_message: {
      id: 'message-1',
      workspace_id: 'workspace-1',
      sender_id: 'user-1',
      sender_type: 'human',
      content: 'Create the reviewable plan',
      mentions: [],
      parent_message_id: null,
      metadata: {
        source: 'task_session',
        conversation_id: 'conversation-1',
      },
      created_at: '2026-07-19T00:00:00Z',
    },
  };
  const invalidPayloads = [
    { ...validPayload, unexpected: true },
    {
      ...validPayload,
      workspace: { ...validPayload.workspace, tenant_id: 'tenant-other' },
    },
    {
      ...validPayload,
      conversation: { ...validPayload.conversation, workspace_id: 'workspace-other' },
    },
    {
      ...validPayload,
      conversation: { ...validPayload.conversation, current_mode: 'build' },
    },
    {
      ...validPayload,
      initial_message: { ...validPayload.initial_message, metadata: {} },
    },
  ];
  const originalFetch = globalThis.fetch;
  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      tenantId: 'tenant-1',
      projectId: 'project-1',
      localApiToken: 'local-session-token',
    });
    for (const payload of invalidPayloads) {
      globalThis.fetch = async () =>
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      await assert.rejects(
        client.createTaskSession(request),
        (error) => error instanceof DesktopApiError && error.status === 502,
      );
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('switchPlanMode persists the explicit plan authority contract', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({ conversation_id: 'conversation-1', mode: 'plan' }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });

    const result = await client.switchPlanMode('conversation-1', 'plan');

    assert.deepEqual(result, { conversation_id: 'conversation-1', mode: 'plan' });
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/agent/plan/mode'
    );
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      conversation_id: 'conversation-1',
      mode: 'plan',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('approvePlanAndStart uses one idempotent authority request', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        queued: true,
        created: true,
        conversation: { id: 'conversation-1', current_mode: 'build' },
        run: { id: 'run-1', status: 'queued', revision: 1 },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });

    const result = await client.approvePlanAndStart({
      conversationId: 'conversation-1',
      projectId: 'project-1',
      planVersionId: 'plan-version-3',
      expectedPlanVersion: 3,
      permissionProfile: 'workspace_write',
      message: 'Execute the approved plan.',
      messageId: 'message-1',
      idempotencyKey: 'approval-1',
      environmentKind: 'worktree',
    });

    assert.equal(result.run.id, 'run-1');
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/agent/plans/approve-and-start'
    );
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      conversation_id: 'conversation-1',
      project_id: 'project-1',
      plan_version_id: 'plan-version-3',
      expected_plan_version: 3,
      permission_profile: 'workspace_write',
      message: 'Execute the approved plan.',
      message_id: 'message-1',
      idempotency_key: 'approval-1',
      environment: { kind: 'worktree' },
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('listAgentPlanTasks loads the structured plan for human review', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        conversation_id: 'conversation 1',
        tasks: [],
        total_count: 0,
        plan_version: {
          id: 'plan-version-4',
          conversation_id: 'conversation 1',
          version: 4,
          status: 'draft',
          tasks: [],
          created_at: '2026-07-13T08:00:00Z',
        },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
    });
    const result = await client.listAgentPlanTasks('conversation 1');

    assert.equal(result.total_count, 0);
    assert.equal(result.plan_version?.id, 'plan-version-4');
    assert.equal(result.plan_version?.version, 4);
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/agent/plan/tasks/conversation%201'
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('managed skill APIs preserve tenant and project collection scope and status contracts', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify(
        calls.length === 1
          ? {
              items: [
                {
                  id: 'skill/1',
                  name: 'Repository review',
                  description: 'Review repository changes',
                  status: 'active',
                  scope: 'tenant',
                  tools: ['git_diff'],
                },
              ],
            }
          : {
              id: 'skill/1',
              name: 'Repository review',
              description: 'Review repository changes',
              status: 'disabled',
              scope: 'tenant',
              tools: ['git_diff'],
            }
      ),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
      tenantId: 'tenant 1',
      projectId: 'project/1',
    });

    const skills = await client.listManagedSkills();
    const updated = await client.setManagedSkillStatus(skills[0].id, 'disabled');

    assert.equal(skills[0].id, 'skill/1');
    assert.equal(updated.status, 'disabled');
    assert.deepEqual(
      calls.map((call) => [String(call.input), call.init?.method, call.init?.body]),
      [
        [
          'http://127.0.0.1:8088/api/v1/skills/?limit=100&tenant_id=tenant+1&project_id=project%2F1',
          'GET',
          undefined,
        ],
        [
          'http://127.0.0.1:8088/api/v1/skills/skill%2F1/status?status=disabled&tenant_id=tenant+1',
          'PATCH',
          undefined,
        ],
      ]
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('managed skill author APIs preserve tenant scope and SKILL.md content contracts', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    const method = init?.method ?? 'GET';
    if (method === 'DELETE') return new Response(null, { status: 204 });
    if (String(input).includes('/content') && method === 'GET') {
      return new Response(
        JSON.stringify({
          skill_id: 'skill/1',
          name: 'repository-review',
          full_content: '# Repository review',
          scope: 'tenant',
          is_system_skill: false,
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    return new Response(
      JSON.stringify({
        id: 'skill/1',
        name: 'repository-review',
        description: 'Review repository changes',
        status: 'active',
        scope: 'tenant',
        tools: ['git_diff'],
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
      tenantId: 'tenant 1',
    });
    const createInput = {
      name: 'repository-review',
      description: 'Review repository changes',
      scope: 'tenant',
      project_id: null,
      tools: ['git_diff'],
      full_content: '# Repository review',
      metadata: {},
      license: null,
      compatibility: null,
      allowed_tools_raw: 'git_diff',
      spec_version: '1.0',
    };

    const created = await client.createManagedSkill(createInput);
    const content = await client.getManagedSkillContent(created.id);
    await client.updateManagedSkill(created.id, {
      name: createInput.name,
      description: 'Review repository changes safely',
      tools: createInput.tools,
      metadata: createInput.metadata,
      license: createInput.license,
      compatibility: createInput.compatibility,
      allowed_tools_raw: createInput.allowed_tools_raw,
      spec_version: createInput.spec_version,
    });
    await client.updateManagedSkillContent(created.id, '# Repository review\n\nUpdated.');
    await client.deleteManagedSkill(created.id);

    assert.equal(content.full_content, '# Repository review');
    assert.deepEqual(
      calls.map((call) => [
        String(call.input),
        call.init?.method ?? 'GET',
        call.init?.body ? JSON.parse(call.init.body) : undefined,
      ]),
      [
        [
          'http://127.0.0.1:8088/api/v1/skills/?tenant_id=tenant+1',
          'POST',
          createInput,
        ],
        [
          'http://127.0.0.1:8088/api/v1/skills/skill%2F1/content?tenant_id=tenant+1',
          'GET',
          undefined,
        ],
        [
          'http://127.0.0.1:8088/api/v1/skills/skill%2F1?tenant_id=tenant+1',
          'PUT',
          {
            name: 'repository-review',
            description: 'Review repository changes safely',
            tools: ['git_diff'],
            metadata: {},
            license: null,
            compatibility: null,
            allowed_tools_raw: 'git_diff',
            spec_version: '1.0',
          },
        ],
        [
          'http://127.0.0.1:8088/api/v1/skills/skill%2F1/content?tenant_id=tenant+1',
          'PUT',
          { full_content: '# Repository review\n\nUpdated.' },
        ],
        [
          'http://127.0.0.1:8088/api/v1/skills/skill%2F1?tenant_id=tenant+1',
          'DELETE',
          undefined,
        ],
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('managed plugin APIs preserve authoritative ids and toggle by id', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        items: [
          {
            id: 'runtime/github',
            name: 'github-display-name',
            source: 'entrypoint',
            enabled: true,
            discovered: true,
            channel_types: [],
          },
          {
            name: 'legacy-plugin',
            source: 'entrypoint',
            enabled: false,
            discovered: true,
            channel_types: [],
          },
        ],
        diagnostics: [],
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
      tenantId: 'tenant 1',
    });
    const plugins = await client.listManagedPlugins();
    await client.setManagedPluginEnabled(plugins[0].id, false);
    await client.setManagedPluginEnabled(plugins[1].id, true);

    assert.equal(plugins[0].id, 'runtime/github');
    assert.equal(plugins[1].id, 'legacy-plugin');
    assert.deepEqual(
      calls.map((call) => [String(call.input), call.init?.method, call.init?.body]),
      [
        [
          'http://127.0.0.1:8088/api/v1/channels/tenants/tenant%201/plugins',
          'GET',
          undefined,
        ],
        [
          'http://127.0.0.1:8088/api/v1/channels/tenants/tenant%201/plugins/runtime%2Fgithub/disable',
          'POST',
          undefined,
        ],
        [
          'http://127.0.0.1:8088/api/v1/channels/tenants/tenant%201/plugins/legacy-plugin/enable',
          'POST',
          undefined,
        ],
      ]
    );
    assert.doesNotMatch(String(calls[0]?.input), /mcp\/apps/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('managed plugin lifecycle and configuration preserve tenant control-plane contracts', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    const url = String(input);
    if (url.endsWith('/config-schema')) {
      return new Response(
        JSON.stringify({
          plugin_name: 'release/notifier',
          providers: [],
          skills: [],
          enabled: true,
          discovered: true,
          schema_supported: true,
          config_schema: { type: 'object', properties: {} },
          secret_paths: [],
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    if (url.endsWith('/config') && init?.method !== 'PUT') {
      return new Response(
        JSON.stringify({
          tenant_id: 'tenant 1',
          plugin_name: 'release/notifier',
          config: { endpoint: 'https://example.test' },
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    return new Response(JSON.stringify({ success: true, message: 'ok' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
      tenantId: 'tenant 1',
    });

    await client.installManagedPlugin('memstack-release-notifier>=2.0');
    await client.reloadManagedPlugins();
    await client.getManagedPluginConfigSchema('release/notifier');
    await client.getManagedPluginConfig('release/notifier');
    await client.updateManagedPluginConfig('release/notifier', {
      config: { endpoint: 'https://example.test/v2' },
    });
    await client.uninstallManagedPlugin('release/notifier');

    assert.deepEqual(
      calls.map((call) => [String(call.input), call.init?.method, call.init?.body]),
      [
        [
          'http://127.0.0.1:8088/api/v1/channels/tenants/tenant%201/plugins/install',
          'POST',
          JSON.stringify({ requirement: 'memstack-release-notifier>=2.0' }),
        ],
        [
          'http://127.0.0.1:8088/api/v1/channels/tenants/tenant%201/plugins/reload',
          'POST',
          undefined,
        ],
        [
          'http://127.0.0.1:8088/api/v1/channels/tenants/tenant%201/plugins/release%2Fnotifier/config-schema',
          'GET',
          undefined,
        ],
        [
          'http://127.0.0.1:8088/api/v1/channels/tenants/tenant%201/plugins/release%2Fnotifier/config',
          'GET',
          undefined,
        ],
        [
          'http://127.0.0.1:8088/api/v1/channels/tenants/tenant%201/plugins/release%2Fnotifier/config',
          'PUT',
          JSON.stringify({ config: { endpoint: 'https://example.test/v2' } }),
        ],
        [
          'http://127.0.0.1:8088/api/v1/channels/tenants/tenant%201/plugins/release%2Fnotifier/uninstall',
          'POST',
          undefined,
        ],
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('cloud managed plugins use the response name as the operation key when id is absent', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        plugins: [
          {
            name: 'github',
            source: 'entrypoint',
            enabled: true,
            discovered: true,
            channel_types: [],
          },
        ],
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'https://api.memstack.test',
      apiKey: 'cloud-session-token',
      localApiToken: '',
      tenantId: 'tenant 1',
      mode: 'cloud',
    });
    const plugins = await client.listManagedPlugins();
    await client.setManagedPluginEnabled(plugins[0].id, false);

    assert.equal(plugins[0].id, 'github');
    assert.deepEqual(
      calls.map((call) => [String(call.input), call.init?.method]),
      [
        ['https://api.memstack.test/api/v1/channels/tenants/tenant%201/plugins', 'GET'],
        [
          'https://api.memstack.test/api/v1/channels/tenants/tenant%201/plugins/github/disable',
          'POST',
        ],
      ]
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('managed agent APIs preserve project scope and the enabled mutation body', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify(
        calls.length === 1
          ? {
              items: [
                {
                  id: 'agent/1',
                  name: 'coding-agent',
                  display_name: 'Coding agent',
                  enabled: false,
                },
              ],
            }
          : {
              id: 'agent/1',
              name: 'coding-agent',
              display_name: 'Coding agent',
              enabled: true,
            }
      ),
      { status: 200, headers: { 'content-type': 'application/json' } }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
      tenantId: 'tenant 1',
      projectId: 'project/1',
    });

    const agents = await client.listManagedAgents();
    const updated = await client.setManagedAgentEnabled(agents[0].id, true);

    assert.equal(updated.enabled, true);
    assert.deepEqual(
      calls.map((call) => [String(call.input), call.init?.method, call.init?.body]),
      [
        [
          'http://127.0.0.1:8088/api/v1/agent/definitions?limit=100&enabled_only=false&project_id=project%2F1&tenant_id=tenant+1',
          'GET',
          undefined,
        ],
        [
          'http://127.0.0.1:8088/api/v1/agent/definitions/agent%2F1/enabled?tenant_id=tenant+1&project_id=project%2F1',
          'PATCH',
          JSON.stringify({ enabled: true }),
        ],
      ]
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('managed external ACP Agent catalog preserves tenant scope', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify([
        {
          id: 'acp-agent-1',
          agentKey: 'review-agent',
          name: 'Review Agent',
          enabled: true,
          available: true,
        },
      ]),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'https://api.memstack.test',
      apiKey: 'cloud-session-token',
      tenantId: 'tenant 1',
      mode: 'cloud',
    });

    assert.equal((await client.listManagedExternalAcpAgents())[0].agentKey, 'review-agent');
    assert.deepEqual(
      calls.map((call) => [String(call.input), call.init?.method]),
      [
        [
          'https://api.memstack.test/api/v1/acp/tenants/tenant%201/external-agents',
          'GET',
        ],
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('managed Agent definition CRUD preserves tenant scope and request bodies', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    if (init?.method === 'DELETE') {
      return new Response(JSON.stringify({ deleted: true, id: 'agent/1' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    return new Response(
      JSON.stringify({
        id: 'agent/1',
        name: 'release_reviewer',
        display_name: 'Release reviewer',
        system_prompt: 'Review releases.',
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  const mutation = {
    name: 'release_reviewer',
    display_name: 'Release reviewer',
    system_prompt: 'Review releases.',
    project_id: 'project/1',
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
      tenantId: 'tenant 1',
      projectId: 'project/1',
    });

    const created = await client.createManagedAgentDefinition(mutation);
    const updated = await client.updateManagedAgentDefinition(created.id, mutation);
    const deleted = await client.deleteManagedAgentDefinition(updated.id);

    assert.equal(deleted.deleted, true);
    assert.deepEqual(
      calls.map((call) => [String(call.input), call.init?.method, call.init?.body]),
      [
        [
          'http://127.0.0.1:8088/api/v1/agent/definitions?tenant_id=tenant+1',
          'POST',
          JSON.stringify(mutation),
        ],
        [
          'http://127.0.0.1:8088/api/v1/agent/definitions/agent%2F1?tenant_id=tenant+1',
          'PUT',
          JSON.stringify(mutation),
        ],
        [
          'http://127.0.0.1:8088/api/v1/agent/definitions/agent%2F1?tenant_id=tenant+1',
          'DELETE',
          undefined,
        ],
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('managed subagent APIs preserve tenant scope and enabled mutation contracts', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify(
        calls.length === 1
          ? {
              subagents: [
                {
                  id: 'subagent/1',
                  tenant_id: 'tenant 1',
                  project_id: 'project/1',
                  name: 'release-reviewer',
                  display_name: 'Release reviewer',
                  trigger: { description: 'Review release readiness' },
                  enabled: false,
                },
              ],
              total: 1,
            }
          : {
              id: 'subagent/1',
              tenant_id: 'tenant 1',
              project_id: 'project/1',
              name: 'release-reviewer',
              display_name: 'Release reviewer',
              trigger: { description: 'Review release readiness' },
              enabled: true,
            },
      ),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
      tenantId: 'tenant 1',
      projectId: 'project/1',
    });

    const subagents = await client.listManagedSubAgents();
    const updated = await client.setManagedSubAgentEnabled(subagents[0].id, true);

    assert.equal(updated.enabled, true);
    assert.deepEqual(
      calls.map((call) => [String(call.input), call.init?.method, call.init?.body]),
      [
        [
          'http://127.0.0.1:8088/api/v1/subagents/?limit=100&include_filesystem=true&tenant_id=tenant+1',
          'GET',
          undefined,
        ],
        [
          'http://127.0.0.1:8088/api/v1/subagents/subagent%2F1/enable?enabled=true&tenant_id=tenant+1',
          'PATCH',
          undefined,
        ],
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
