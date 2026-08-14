import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createDesktopWorkbenchCapabilityClient } from '/tmp/agistack-desktop-test-dist/src/features/runtime/workbenchCapabilityClient.js';
import { DEFAULT_CONFIG } from '/tmp/agistack-desktop-test-dist/src/types.js';

const automationContract = {
  service_version: '0.1.0',
  contract_version: '2.0.0',
  schema_version: 1,
  read: true,
  revision_guarded: true,
  idempotency_guarded: true,
  durable_execution: true,
  supported_read_trigger_kinds: ['manual', 'schedule', 'event'],
  create: { allowed: true },
  edit: { allowed: true },
  toggle: { allowed: true },
  run_now: { allowed: true },
  delete: { allowed: true },
};

const cloudProject = {
  id: 'project-1',
  tenant_id: 'tenant-1',
  name: 'Project One',
  description: null,
  created_at: '2026-07-30T00:00:00Z',
  updated_at: null,
};

const cloudProjectStats = {
  memory_count: 4,
  storage_used: 1024,
  storage_limit: 4096,
  active_nodes: 3,
  collaborators: 2,
};

const localProjectOverview = {
  capability: 'project_overview',
  availability: 'degraded',
  reason_code: 'local_project_overview_timeline_projection_only',
  service_version: '0.1.0',
  contract_version: '4.0.0',
  allowed_actions: ['view'],
  scope: {
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    workspace_id: null,
    instance_id: null,
  },
  authority_revision: 11,
  backfill_cursor: null,
  project: {
    availability: 'available',
    reason_code: null,
    value: {
      id: 'project-1',
      tenant_id: 'tenant-1',
      name: 'Project One',
      description: null,
      agent_conversation_mode: 'workspace',
      created_at: '2026-07-30T00:00:00Z',
    },
  },
  conversation_count: {
    availability: 'available',
    reason_code: null,
    value: 0,
  },
  conversation_status_summary: {
    availability: 'available',
    reason_code: null,
    value: {
      total: 0,
      idle: 0,
      queued: 0,
      running: 0,
      attention: 0,
      completed: 0,
      failed: 0,
      cancelled: 0,
    },
  },
  recent_knowledge_items: {
    availability: 'degraded',
    reason_code: 'local_project_overview_timeline_projection_only',
    source: 'desktop_timeline',
    total: 0,
    value: [],
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

const cloudTenantOverview = {
  storage: { used: 1024, total: 4096, percentage: 25 },
  projects: {
    active: 1,
    new_this_week: 1,
    list: [
      {
        id: 'project-1',
        name: 'Project One',
        owner: 'Ada',
        memory_consumed: '1.0 KB',
        status: 'active',
      },
    ],
  },
  members: { total: 2, new_added: 1 },
  memory_history: [
    {
      date: '2026-07-30',
      used: 1024,
      daily_added: 128,
      memory_count: 4,
      percentage: 25,
    },
  ],
  tenant_info: {
    organization_id: '#TENANT-1',
    plan: 'Pro',
    region: null,
    next_billing_date: null,
  },
};

const localTenantOverview = {
  capability: 'tenant_overview',
  availability: 'degraded',
  reason_code: 'local_tenant_overview_memory_projection_unavailable',
  service_version: '0.1.0',
  contract_version: '3.0.0',
  allowed_actions: ['view'],
  scope: {
    tenant_id: 'tenant-1',
    project_id: null,
    workspace_id: null,
    instance_id: null,
  },
  authority_revision: 13,
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
    active: 1,
    new_this_week: 0,
    list: [
      {
        id: 'project-1',
        name: 'Project One',
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
};

const projectScope = {
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  workspace_id: null,
  instance_id: null,
};

test('Cloud workbench keeps unversioned Overview probes unavailable', async () => {
  const signal = new AbortController().signal;
  const calls = [];
  await withFetch(
    async (input, init) => {
      calls.push({ input: String(input), init });
      if (String(input).endsWith('/api/v1/tenants/tenant-1/stats')) {
        return jsonResponse(cloudTenantOverview);
      }
      if (String(input).includes('/api/v1/projects/project-1?')) {
        return jsonResponse(cloudProject);
      }
      if (String(input).endsWith('/api/v1/projects/project-1/stats')) {
        return jsonResponse(cloudProjectStats);
      }
      return jsonResponse({}, { status: 404 });
    },
    async () => {
      const snapshot = await createClient(cloudConfig()).loadSnapshot(signal);
      assert.deepEqual(snapshot.capabilities['project-project-overview'], {
        availability: 'unavailable',
        reason_code: 'capability_authority_revision_unavailable',
        service_version: '0.1.0',
        contract_version: '3.0.0',
        allowed_actions: [],
        scope: projectScope,
        authority_revision: null,
        retryable: false,
        authority_source: 'cloud_service',
        supporting_authority_sources: [],
        provenance: 'observed',
      });
      assert.deepEqual(snapshot.capabilities['tenant-tenant-overview'], {
        availability: 'unavailable',
        reason_code: 'capability_authority_revision_unavailable',
        service_version: '0.1.0',
        contract_version: '3.0.0',
        allowed_actions: [],
        scope: {
          tenant_id: 'tenant-1',
          project_id: null,
          workspace_id: null,
          instance_id: null,
        },
        authority_revision: null,
        retryable: false,
        authority_source: 'cloud_service',
        supporting_authority_sources: [],
        provenance: 'observed',
      });
    },
  );

  const projectCall = calls.find(({ input }) => input.includes('/api/v1/projects/project-1?'));
  assert.equal(
    projectCall?.input,
    'https://api.memstack.test/api/v1/projects/project-1?tenant_id=tenant-1',
  );
  assert.equal(projectCall?.init?.signal, signal);
  assert.equal(
    new Headers(projectCall?.init?.headers).get('Authorization'),
    'Bearer cloud-session',
  );
  const statsCall = calls.find(({ input }) => input.endsWith('/api/v1/projects/project-1/stats'));
  assert.equal(statsCall?.init?.signal, signal);
  assert.equal(new Headers(statsCall?.init?.headers).get('Authorization'), 'Bearer cloud-session');
});

test('Cloud workbench does not advertise inspect-stats when stats authority fails', async () => {
  await withFetch(
    async (input) => {
      if (String(input).includes('/api/v1/projects/project-1?')) {
        return jsonResponse(cloudProject);
      }
      if (String(input).endsWith('/api/v1/projects/project-1/stats')) {
        return jsonResponse({ detail: 'project_stats_authority_unavailable' }, { status: 503 });
      }
      return jsonResponse({}, { status: 404 });
    },
    async () => {
      const snapshot = await createClient(cloudConfig()).loadSnapshot();
      assert.deepEqual(snapshot.capabilities['project-project-overview'], {
        availability: 'unavailable',
        reason_code: 'project_overview_authority_unavailable',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: projectScope,
        authority_revision: null,
        retryable: false,
        authority_source: 'cloud_service',
        supporting_authority_sources: [],
        provenance: 'observed',
      });
    },
  );
});

test('Cloud Project Overview failures stay structured and never infer reason from text', async () => {
  for (const [response, expectedReason] of [
    [
      jsonResponse({ detail: 'cloud_project_overview_project_scope_invalid' }, { status: 403 }),
      'project_overview_forbidden',
    ],
    [
      jsonResponse({ detail: 'cloud_project_overview_project_scope_invalid' }, { status: 503 }),
      'project_overview_authority_unavailable',
    ],
    [
      jsonResponse({ ...cloudProject, tenant_id: 'tenant-other' }),
      'project_overview_contract_invalid',
    ],
  ]) {
    await withFetch(
      async (input) => {
        if (String(input).includes('/api/v1/projects/project-1?')) return response;
        return jsonResponse({}, { status: 404 });
      },
      async () => {
        const snapshot = await createClient(cloudConfig()).loadSnapshot();
        assert.deepEqual(snapshot.capabilities['project-project-overview'], {
          availability: 'unavailable',
          reason_code: expectedReason,
          service_version: null,
          contract_version: null,
          allowed_actions: [],
          scope: projectScope,
          authority_revision: null,
          retryable: false,
          authority_source: 'cloud_service',
          supporting_authority_sources: [],
          provenance: 'observed',
        });
      },
    );
  }
});

test('Local workbench preserves degraded Project Overview authority metadata', async () => {
  const signal = new AbortController().signal;
  const calls = [];
  await withFetch(
    async (input, init) => {
      calls.push({ input: String(input), init });
      if (String(input).endsWith('/api/v1/tenants/tenant-1/stats')) {
        return jsonResponse(localTenantOverview);
      }
      if (String(input).endsWith('/api/v1/projects/project-1/overview')) {
        return jsonResponse(localProjectOverview);
      }
      return jsonResponse({}, { status: 404 });
    },
    async () => {
      const snapshot = await createClient(localConfig()).loadSnapshot(signal);
      assert.deepEqual(snapshot.capabilities['project-project-overview'], {
        availability: 'degraded',
        reason_code: 'local_project_overview_timeline_projection_only',
        service_version: '0.1.0',
        contract_version: '4.0.0',
        allowed_actions: ['view'],
        scope: projectScope,
        authority_revision: 11,
        retryable: false,
        authority_source: 'sidecar',
        supporting_authority_sources: [],
        provenance: 'observed',
      });
      assert.deepEqual(snapshot.capabilities['tenant-tenant-overview'], {
        availability: 'degraded',
        reason_code: 'local_tenant_overview_memory_projection_unavailable',
        service_version: '0.1.0',
        contract_version: '3.0.0',
        allowed_actions: ['view'],
        scope: {
          tenant_id: 'tenant-1',
          project_id: null,
          workspace_id: null,
          instance_id: null,
        },
        authority_revision: 13,
        retryable: false,
        authority_source: 'sidecar',
        supporting_authority_sources: [],
        provenance: 'observed',
      });
    },
  );

  const projectCall = calls.find(({ input }) =>
    input.endsWith('/api/v1/projects/project-1/overview'),
  );
  assert.equal(projectCall?.init?.signal, signal);
  const headers = new Headers(projectCall?.init?.headers);
  assert.equal(headers.get('Authorization'), 'Bearer local-session');
  assert.equal(headers.get('X-Agistack-Launch'), 'launch-capability');
});

test('Cloud and Local Project Overview authority propagate AbortSignal cancellation', async () => {
  const controller = new AbortController();
  controller.abort();
  await withFetch(
    async (_input, init) => {
      if (init?.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return jsonResponse({}, { status: 404 });
    },
    async () => {
      for (const config of [cloudConfig(), localConfig()]) {
        await assert.rejects(
          createClient(config).loadSnapshot(controller.signal),
          (error) => error instanceof DOMException && error.name === 'AbortError',
        );
      }
    },
  );
});

function createClient(config) {
  return createDesktopWorkbenchCapabilityClient(
    { getAutomationCapabilities: async () => automationContract },
    config,
  );
}

function cloudConfig() {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://api.memstack.test',
    apiKey: 'cloud-session',
    mode: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
}

function localConfig() {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:4777',
    apiKey: 'local-session',
    localApiToken: 'launch-capability',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
}

function jsonResponse(payload, init = {}) {
  return new Response(JSON.stringify(payload), {
    ...init,
    headers: { 'content-type': 'application/json', ...init.headers },
  });
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
