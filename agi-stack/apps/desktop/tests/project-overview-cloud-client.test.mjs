import assert from 'node:assert/strict';
import test from 'node:test';

import { DesktopApiError } from '/tmp/agistack-desktop-test-dist/src/api/client.js';
import {
  createCloudProjectOverviewClient,
} from '/tmp/agistack-desktop-test-dist/src/features/project/projectOverviewCloudClient.js';

const scope = {
  authority: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
};

const config = {
  apiBaseUrl: 'https://cloud.example.test/',
  deviceAuthorizationBaseUrl: 'https://auth.example.test',
  apiKey: ' cloud-token ',
  localApiToken: 'must-not-be-used-in-cloud-mode',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  mode: 'cloud',
  workspaceRoot: '',
};

const projectPayload = {
  id: 'project-1',
  tenant_id: 'tenant-1',
  name: 'Desktop parity',
  description: 'Native Project Overview',
  created_at: '2026-07-30T00:00:00Z',
  updated_at: '2026-07-30T01:00:00Z',
};

const statsPayload = {
  memory_count: 8,
  storage_used: 1024,
  storage_limit: 8192,
  active_nodes: 4,
  collaborators: 3,
};

const memoryPayload = {
  memories: [
    {
      id: 'memory-1',
      project_id: 'project-1',
      title: 'Cloud authority',
      content: 'Values come from the Cloud service.',
      content_type: 'text',
      status: 'ACTIVE',
      metadata: {},
      created_at: '2026-07-30T00:30:00Z',
      updated_at: null,
    },
  ],
  total: 1,
  page: 1,
  page_size: 5,
};

test('Cloud Project Overview adapter uses exact endpoints, credentials, and signal', async () => {
  const signal = new AbortController().signal;
  const requests = [];
  await withFetch(async (input, init) => {
    requests.push({ input, init });
    if (String(input).includes('/stats')) return jsonResponse(statsPayload);
    if (String(input).includes('/memories/')) return jsonResponse(memoryPayload);
    return jsonResponse(projectPayload);
  }, async () => {
    const client = createCloudProjectOverviewClient(config);
    assert.deepEqual(await client.getProject(scope, { signal }), projectPayload);
    assert.deepEqual(await client.getProjectStats(scope, { signal }), statsPayload);
    assert.deepEqual(
      await client.listMemories(scope, { page: 1, page_size: 5 }, { signal }),
      memoryPayload,
    );
  });

  assert.deepEqual(
    requests.map(({ input }) => String(input)),
    [
      'https://cloud.example.test/api/v1/projects/project-1?tenant_id=tenant-1',
      'https://cloud.example.test/api/v1/projects/project-1/stats',
      'https://cloud.example.test/api/v1/memories/?page=1&page_size=5&project_id=project-1',
    ],
  );
  for (const { init } of requests) {
    const headers = new Headers(init.headers);
    assert.equal(init.method, 'GET');
    assert.equal(init.signal, signal);
    assert.equal(headers.get('Accept'), 'application/json');
    assert.equal(headers.get('Authorization'), 'Bearer cloud-token');
    assert.equal(headers.has('X-Agistack-Launch'), false);
  }
});

test('Cloud Project Overview adapter preserves forbidden DesktopApiError authority', async () => {
  await withFetch(
    async () =>
      jsonResponse(
        { detail: 'Forbidden', reason_code: 'project_read_forbidden' },
        { status: 403 },
      ),
    async () => {
      const client = createCloudProjectOverviewClient(config);
      await assert.rejects(
        client.getProject(scope),
        (error) =>
          error instanceof DesktopApiError &&
          error.status === 403 &&
          error.payload.reason_code === 'project_read_forbidden',
      );
    },
  );
});

test('Cloud Project Overview adapter requires structured Cloud config and scope marker', async () => {
  assert.throws(
    () => createCloudProjectOverviewClient({ ...config, mode: 'local' }),
    (error) =>
      error instanceof DesktopApiError &&
      error.payload.reason_code === 'cloud_project_overview_config_required',
  );

  const client = createCloudProjectOverviewClient(config);
  await assert.rejects(
    client.getProject({ tenantId: 'tenant-1', projectId: 'project-1' }),
    (error) =>
      error instanceof DesktopApiError &&
      error.payload.reason_code === 'cloud_project_overview_scope_invalid',
  );
});

test('Cloud Project Overview adapter rejects empty and mismatched project contracts', async () => {
  const client = createCloudProjectOverviewClient(config);
  await withFetch(
    async () => new Response('', { status: 200 }),
    async () => {
      await assert.rejects(
        client.getProject(scope),
        hasReasonCode('cloud_project_overview_response_invalid'),
      );
    },
  );
  await withFetch(
    async () => jsonResponse({ ...projectPayload, tenant_id: 'tenant-2' }),
    async () => {
      await assert.rejects(
        client.getProject(scope),
        hasReasonCode('cloud_project_overview_project_scope_invalid'),
      );
    },
  );
});

test('Cloud Project Overview adapter rejects non-finite, missing, or negative stats', async () => {
  const client = createCloudProjectOverviewClient(config);
  for (const payload of [
    { ...statsPayload, memory_count: -1 },
    { ...statsPayload, storage_used: null },
    { ...statsPayload, active_nodes: '4' },
    { ...statsPayload, collaborators: Number.POSITIVE_INFINITY },
  ]) {
    await withFetch(
      async () => inMemoryJsonResponse(payload),
      async () => {
        await assert.rejects(
          client.getProjectStats(scope),
          hasReasonCode('cloud_project_overview_stats_invalid'),
        );
      },
    );
  }
  await withFetch(
    async () => jsonResponse({ ...statsPayload, project_id: 'project-2' }),
    async () => {
      await assert.rejects(
        client.getProjectStats(scope),
        hasReasonCode('cloud_project_overview_stats_scope_invalid'),
      );
    },
  );
});

test('Cloud Project Overview adapter rejects invalid memory page and metadata contracts', async () => {
  const client = createCloudProjectOverviewClient(config);
  for (const payload of [
    { ...memoryPayload, page: 2 },
    { ...memoryPayload, page_size: 50 },
    { ...memoryPayload, total: -1 },
    { ...memoryPayload, memories: null },
    {
      ...memoryPayload,
      memories: Array.from({ length: 6 }, (_, index) => ({
        ...memoryPayload.memories[0],
        id: `memory-${index}`,
      })),
      total: 6,
    },
    {
      ...memoryPayload,
      memories: [{ ...memoryPayload.memories[0], metadata: [] }],
    },
  ]) {
    await withFetch(
      async () => jsonResponse(payload),
      async () => {
        await assert.rejects(
          client.listMemories(scope, { page: 1, page_size: 5 }),
          hasReasonCode('cloud_project_overview_memory_page_invalid'),
        );
      },
    );
  }
  await withFetch(
    async () => jsonResponse({ ...memoryPayload, tenant_id: 'tenant-2' }),
    async () => {
      await assert.rejects(
        client.listMemories(scope, { page: 1, page_size: 5 }),
        hasReasonCode('cloud_project_overview_memory_scope_invalid'),
      );
    },
  );
});

test('Cloud Project Overview adapter rejects memory records outside the project scope', async () => {
  await withFetch(
    async () =>
      jsonResponse({
        ...memoryPayload,
        memories: [{ ...memoryPayload.memories[0], project_id: 'project-2' }],
      }),
    async () => {
      const client = createCloudProjectOverviewClient(config);
      await assert.rejects(
        client.listMemories(scope, { page: 1, page_size: 5 }),
        hasReasonCode('cloud_project_overview_memory_scope_invalid'),
      );
    },
  );
});

function jsonResponse(payload, init = {}) {
  return new Response(JSON.stringify(payload), {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init.headers },
  });
}

function inMemoryJsonResponse(payload) {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ 'Content-Type': 'application/json' }),
    json: async () => payload,
    text: async () => '',
  };
}

function hasReasonCode(reasonCode) {
  return (error) =>
    error instanceof DesktopApiError &&
    error.status === 0 &&
    error.payload.reason_code === reasonCode;
}

async function withFetch(fetchImplementation, operation) {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = fetchImplementation;
  try {
    return await operation();
  } finally {
    globalThis.fetch = previousFetch;
  }
}
