import assert from 'node:assert/strict';
import test from 'node:test';

import { DesktopApiError } from '/tmp/agistack-desktop-test-dist/src/api/client.js';
import {
  createLocalProjectOverviewClient,
  parseLocalProjectOverviewPayload,
} from '/tmp/agistack-desktop-test-dist/src/features/project/projectOverviewLocalClient.js';

const scope = {
  authority: 'local',
  tenantId: 'tenant-1',
  projectId: 'project-1',
};

const config = {
  apiBaseUrl: 'http://127.0.0.1:4777/',
  deviceAuthorizationBaseUrl: 'https://auth.example.test',
  apiKey: ' local-session ',
  localApiToken: ' launch-capability ',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  mode: 'local',
  workspaceRoot: '/workspace',
};

const rawPayload = {
  capability: 'project_overview',
  availability: 'degraded',
  reason_code: 'local_project_overview_timeline_projection_only',
  service_version: '0.1.0',
  contract_version: '3.0.0',
  allowed_actions: ['view'],
  scope: {
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    workspace_id: null,
    instance_id: null,
  },
  authority_revision: 7,
  backfill_cursor: null,
  project: {
    availability: 'available',
    reason_code: null,
    value: {
      id: 'project-1',
      tenant_id: 'tenant-1',
      name: 'Local Project',
      description: 'Timeline projection',
      agent_conversation_mode: 'workspace',
      created_at: '2026-07-30T00:00:00Z',
    },
  },
  conversation_count: {
    availability: 'available',
    reason_code: null,
    value: 3,
  },
  recent_knowledge_items: {
    availability: 'degraded',
    reason_code: 'local_project_overview_timeline_projection_only',
    source: 'desktop_timeline',
    total: 1,
    value: [
      {
        id: 'timeline-1',
        conversation_id: 'conversation-1',
        title: 'Local result',
        content: 'This is a timeline-backed knowledge item.',
        result_type: 'assistant_message',
        source: 'desktop_timeline',
        created_at: '2026-07-30T00:30:00Z',
        tags: ['local', 'verified'],
      },
    ],
  },
  active_nodes: {
    availability: 'unavailable',
    reason_code: 'local_project_graph_projection_unavailable',
    value: null,
  },
  storage_quota: {
    availability: 'not_applicable',
    reason_code: 'local_project_storage_quota_not_applicable',
    value: null,
  },
  collaborators: {
    availability: 'not_applicable',
    reason_code: 'local_project_collaboration_governance_not_applicable',
    value: null,
  },
};

test('Local Project Overview adapter uses the scoped sidecar route, credentials, and signal', async () => {
  const signal = new AbortController().signal;
  const requests = [];
  let snapshot;
  await withFetch(
    async (input, init) => {
      requests.push({ input, init });
      return jsonResponse(rawPayload);
    },
    async () => {
      snapshot = await createLocalProjectOverviewClient(config).load(scope, { signal });
    },
  );

  assert.equal(requests.length, 1);
  assert.equal(
    String(requests[0].input),
    'http://127.0.0.1:4777/api/v1/projects/project-1/overview',
  );
  assert.equal(requests[0].init.method, 'GET');
  assert.equal(requests[0].init.signal, signal);
  assert.equal(requests[0].init.credentials, 'omit');
  const headers = new Headers(requests[0].init.headers);
  assert.equal(headers.get('Accept'), 'application/json');
  assert.equal(headers.get('Authorization'), 'Bearer local-session');
  assert.equal(headers.get('X-Agistack-Launch'), 'launch-capability');

  assert.deepEqual(snapshot, {
    scope,
    capability: {
      availability: 'degraded',
      reasonCode: 'local_project_overview_timeline_projection_only',
      serviceVersion: '0.1.0',
      contractVersion: '3.0.0',
      allowedActions: ['view'],
      scope: {
        tenantId: 'tenant-1',
        projectId: 'project-1',
        workspaceId: null,
        instanceId: null,
      },
      authorityRevision: 7,
    },
    backfillCursor: null,
    project: {
      availability: 'available',
      reasonCode: null,
      value: {
        id: 'project-1',
        tenantId: 'tenant-1',
        name: 'Local Project',
        description: 'Timeline projection',
        agentConversationMode: 'workspace',
        createdAt: '2026-07-30T00:00:00Z',
      },
    },
    conversationCount: {
      availability: 'available',
      reasonCode: null,
      value: 3,
    },
    recentKnowledgeItems: {
      availability: 'degraded',
      reasonCode: 'local_project_overview_timeline_projection_only',
      source: 'desktop_timeline',
      total: 1,
      value: [
        {
          id: 'timeline-1',
          conversationId: 'conversation-1',
          title: 'Local result',
          content: 'This is a timeline-backed knowledge item.',
          resultType: 'assistant_message',
          source: 'desktop_timeline',
          createdAt: '2026-07-30T00:30:00Z',
          tags: ['local', 'verified'],
        },
      ],
    },
    activeNodes: {
      availability: 'unavailable',
      reasonCode: 'local_project_graph_projection_unavailable',
      value: null,
    },
    storageQuota: {
      availability: 'not_applicable',
      reasonCode: 'local_project_storage_quota_not_applicable',
      value: null,
    },
    collaborators: {
      availability: 'not_applicable',
      reasonCode: 'local_project_collaboration_governance_not_applicable',
      value: null,
    },
  });
  assertNoMemoryKeys(snapshot);
});

test('Local Project Overview parser rejects capability authority drift and unknown fields', () => {
  for (const payload of [
    { ...rawPayload, capability: 'memory_overview' },
    { ...rawPayload, availability: 'available' },
    { ...rawPayload, reason_code: 'local_project_overview_available' },
    { ...rawPayload, service_version: 'latest' },
    { ...rawPayload, contract_version: '2.0.0' },
    { ...rawPayload, allowed_actions: [] },
    { ...rawPayload, allowed_actions: ['view', 'edit'] },
    { ...rawPayload, authority_revision: -1 },
    { ...rawPayload, authority_revision: 1.5 },
    { ...rawPayload, backfill_cursor: 'opaque' },
    { ...rawPayload, unexpected: true },
    {
      ...rawPayload,
      scope: { ...rawPayload.scope, tenant_id: 'tenant-2' },
    },
    {
      ...rawPayload,
      scope: { ...rawPayload.scope, workspace_id: 'workspace-1' },
    },
  ]) {
    assert.equal(parseLocalProjectOverviewPayload(payload, scope), null);
  }
});

test('Local Project Overview parser requires available project and conversation authorities', () => {
  for (const payload of [
    {
      ...rawPayload,
      project: { ...rawPayload.project, availability: 'degraded' },
    },
    {
      ...rawPayload,
      project: { ...rawPayload.project, reason_code: 'fallback' },
    },
    {
      ...rawPayload,
      project: {
        ...rawPayload.project,
        value: { ...rawPayload.project.value, tenant_id: 'tenant-2' },
      },
    },
    {
      ...rawPayload,
      project: {
        ...rawPayload.project,
        value: { ...rawPayload.project.value, unexpected: true },
      },
    },
    {
      ...rawPayload,
      conversation_count: {
        ...rawPayload.conversation_count,
        value: -1,
      },
    },
    {
      ...rawPayload,
      conversation_count: {
        ...rawPayload.conversation_count,
        reason_code: 'estimated',
      },
    },
  ]) {
    assert.equal(parseLocalProjectOverviewPayload(payload, scope), null);
  }
});

test('Local Project Overview parser keeps timeline knowledge degraded and never accepts Memory shape', () => {
  for (const payload of [
    {
      ...rawPayload,
      recent_knowledge_items: {
        ...rawPayload.recent_knowledge_items,
        availability: 'available',
      },
    },
    {
      ...rawPayload,
      recent_knowledge_items: {
        ...rawPayload.recent_knowledge_items,
        source: 'memory',
      },
    },
    {
      ...rawPayload,
      recent_knowledge_items: {
        ...rawPayload.recent_knowledge_items,
        total: 0,
      },
    },
    {
      ...rawPayload,
      recent_knowledge_items: {
        ...rawPayload.recent_knowledge_items,
        memories: rawPayload.recent_knowledge_items.value,
      },
    },
    {
      ...rawPayload,
      recent_knowledge_items: {
        ...rawPayload.recent_knowledge_items,
        value: [
          {
            ...rawPayload.recent_knowledge_items.value[0],
            source: 'cloud_memory',
          },
        ],
      },
    },
    {
      ...rawPayload,
      recent_knowledge_items: {
        ...rawPayload.recent_knowledge_items,
        value: Array.from({ length: 6 }, (_, index) => ({
          ...rawPayload.recent_knowledge_items.value[0],
          id: `timeline-${index}`,
        })),
        total: 6,
      },
    },
  ]) {
    assert.equal(parseLocalProjectOverviewPayload(payload, scope), null);
  }
});

test('Local Project Overview parser rejects fabricated cloud-only values', () => {
  for (const [field, value] of [
    ['active_nodes', 0],
    ['storage_quota', { used: 0, limit: 0 }],
    ['collaborators', 1],
  ]) {
    assert.equal(
      parseLocalProjectOverviewPayload(
        {
          ...rawPayload,
          [field]: { ...rawPayload[field], value },
        },
        scope,
      ),
      null,
    );
  }
  assert.equal(
    parseLocalProjectOverviewPayload(
      {
        ...rawPayload,
        active_nodes: {
          ...rawPayload.active_nodes,
          availability: 'not_applicable',
        },
      },
      scope,
    ),
    null,
  );
});

test('Local Project Overview adapter fails closed for mode, scope, and missing credentials', async () => {
  assert.throws(
    () => createLocalProjectOverviewClient({ ...config, mode: 'cloud' }),
    hasReasonCode('local_project_overview_config_required'),
  );

  const client = createLocalProjectOverviewClient(config);
  await assert.rejects(
    client.load({ ...scope, authority: 'cloud' }),
    hasReasonCode('local_project_overview_scope_invalid'),
  );
  await assert.rejects(
    client.load({ ...scope, tenantId: 'tenant-2' }),
    hasReasonCode('local_project_overview_runtime_scope_mismatch'),
  );
  await assert.rejects(
    createLocalProjectOverviewClient({ ...config, apiKey: ' ' }).load(scope),
    hasReasonCode('local_project_overview_session_credential_required'),
  );
  await assert.rejects(
    createLocalProjectOverviewClient({ ...config, localApiToken: ' ' }).load(scope),
    hasReasonCode('local_project_overview_launch_capability_required'),
  );
});

test('Local Project Overview adapter preserves HTTP errors and rejects malformed responses', async () => {
  const client = createLocalProjectOverviewClient(config);
  await withFetch(
    async () =>
      jsonResponse(
        {
          detail: 'request is outside the active workspace context',
          reason_code: 'local_project_scope_forbidden',
        },
        { status: 403 },
      ),
    async () => {
      await assert.rejects(
        client.load(scope),
        (error) =>
          error instanceof DesktopApiError &&
          error.status === 403 &&
          error.payload.reason_code === 'local_project_scope_forbidden',
      );
    },
  );
  await withFetch(
    async () =>
      new Response(JSON.stringify(rawPayload), {
        headers: { 'Content-Type': 'text/plain' },
      }),
    async () => {
      await assert.rejects(
        client.load(scope),
        hasReasonCode('local_project_overview_response_not_json'),
      );
    },
  );
  await withFetch(
    async () => jsonResponse({ ...rawPayload, unexpected: true }),
    async () => {
      await assert.rejects(
        client.load(scope),
        hasReasonCode('local_project_overview_contract_invalid'),
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

function hasReasonCode(reasonCode) {
  return (error) =>
    error instanceof DesktopApiError &&
    error.status === 0 &&
    error.payload.reason_code === reasonCode;
}

function assertNoMemoryKeys(value) {
  if (Array.isArray(value)) {
    for (const item of value) assertNoMemoryKeys(item);
    return;
  }
  if (value === null || typeof value !== 'object') return;
  for (const [key, nested] of Object.entries(value)) {
    assert.equal(key.toLowerCase().includes('memory'), false, `unexpected Memory key: ${key}`);
    assertNoMemoryKeys(nested);
  }
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
