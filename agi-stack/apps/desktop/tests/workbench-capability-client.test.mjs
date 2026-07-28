import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopWorkbenchCapabilityClient,
  normalizeAutomationCapabilityContract,
  normalizeSearchCapabilityContract,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/runtime/workbenchCapabilityClient.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

const searchContract = {
  search_types: {
    semantic: {
      description: 'Semantic search',
      endpoint: '/api/v1/memory/search',
      parameters: {},
    },
    advanced: {
      description: 'Advanced semantic search',
      endpoint: '/api/v1/search-enhanced/advanced',
      parameters: {
        query: 'string (required)',
        strategy: 'string (optional)',
        focal_node_uuid: 'string (optional)',
        reranker: 'string (optional)',
        limit: 'integer (1-200)',
        tenant_id: 'string (optional)',
        project_id: 'string (optional)',
        since: 'ISO datetime string (optional)',
      },
    },
    graph_traversal: {
      description: 'Graph traversal',
      endpoint: '/api/v1/search-enhanced/graph-traversal',
      parameters: {},
    },
    community: {
      description: 'Community search',
      endpoint: '/api/v1/search-enhanced/community',
      parameters: {},
    },
    temporal: {
      description: 'Temporal search',
      endpoint: '/api/v1/search-enhanced/temporal',
      parameters: {},
    },
    faceted: {
      description: 'Faceted search',
      endpoint: '/api/v1/search-enhanced/faceted',
      parameters: {},
    },
  },
  filters: {
    entity_types: [],
    relationship_types: [],
  },
};

const automationContract = {
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

test('cloud client validates structured Search and Automation authorities', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return new Response(JSON.stringify(searchContract), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = createDesktopWorkbenchCapabilityClient(
      {
        getAutomationCapabilities: async () => automationContract,
      },
      {
        ...DEFAULT_CONFIG,
        apiBaseUrl: 'https://api.memstack.test',
        apiKey: 'session-credential',
        mode: 'cloud',
        projectId: 'project/1',
      },
    );
    const snapshot = await client.loadSnapshot();

    assert.deepEqual(snapshot.capabilities.search, {
      available: true,
      reason_code: null,
    });
    assert.deepEqual(snapshot.capabilities.automation_run, {
      available: true,
      reason_code: null,
    });
    assert.equal(
      calls[0]?.input,
      'https://api.memstack.test/api/v1/search-enhanced/capabilities',
    );
    assert.equal(calls[0]?.init?.headers.get('Authorization'), 'Bearer session-credential');
    assert.equal(calls[0]?.init?.headers.has('X-Agistack-Launch'), false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('local workbench capability client never probes an absent Search route', async () => {
  const originalFetch = globalThis.fetch;
  let fetchCalls = 0;
  globalThis.fetch = async () => {
    fetchCalls += 1;
    throw new Error('local Search capability route must not be probed');
  };

  try {
    const client = createDesktopWorkbenchCapabilityClient(
      {
        getAutomationCapabilities: async () => ({
          ...automationContract,
          durable_execution: false,
          run_now: {
            allowed: false,
            reason_code: 'durable_automation_execution_unavailable',
          },
        }),
      },
      {
        ...DEFAULT_CONFIG,
        localApiToken: 'launch-capability',
        mode: 'local',
        projectId: 'local-project',
      },
    );
    const snapshot = await client.loadSnapshot();

    assert.equal(fetchCalls, 0);
    assert.deepEqual(snapshot.capabilities.search, {
      available: false,
      reason_code: 'local_search_routes_unavailable',
    });
    assert.deepEqual(snapshot.capabilities.automation_run, {
      available: false,
      reason_code: 'durable_automation_execution_unavailable',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('malformed capability authorities fail closed without status heuristics', async () => {
  assert.deepEqual(normalizeSearchCapabilityContract({ search_types: {} }), {
    available: false,
    reason_code: 'search_capability_contract_invalid',
  });
  assert.deepEqual(
    normalizeAutomationCapabilityContract({
      ...automationContract,
      durable_execution: false,
    }),
    {
      available: false,
      reason_code: 'automation_capability_contract_invalid',
    },
  );

  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: 'not declared' }), {
      status: 404,
      headers: { 'content-type': 'application/json' },
    });
  try {
    const client = createDesktopWorkbenchCapabilityClient(
      {
        getAutomationCapabilities: async () => {
          throw new Error('capability authority unavailable');
        },
      },
      {
        ...DEFAULT_CONFIG,
        apiBaseUrl: 'https://api.memstack.test',
        mode: 'cloud',
        projectId: 'project-1',
      },
    );
    const snapshot = await client.loadSnapshot();
    assert.deepEqual(snapshot.capabilities.search, {
      available: false,
      reason_code: 'search_capability_contract_unavailable',
    });
    assert.deepEqual(snapshot.capabilities.automation_run, {
      available: false,
      reason_code: 'automation_capability_contract_unavailable',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('capability normalizers reject endpoint and guard drift', () => {
  assert.deepEqual(
    normalizeSearchCapabilityContract({
      ...searchContract,
      search_types: {
        ...searchContract.search_types,
        temporal: {
          ...searchContract.search_types.temporal,
          endpoint: '/api/v1/search-enhanced/renamed',
        },
      },
    }),
    {
      available: false,
      reason_code: 'search_capability_contract_invalid',
    },
  );
  assert.deepEqual(normalizeAutomationCapabilityContract(automationContract), {
    available: true,
    reason_code: null,
  });
  const missingAdvanced = structuredClone(searchContract);
  delete missingAdvanced.search_types.advanced;
  assert.deepEqual(normalizeSearchCapabilityContract(missingAdvanced), {
    available: false,
    reason_code: 'search_capability_contract_invalid',
  });
});

test('Search capability normalizer rejects incomplete or drifted advanced parameters', () => {
  const missingParameter = structuredClone(searchContract);
  delete missingParameter.search_types.advanced.parameters.since;
  assert.deepEqual(normalizeSearchCapabilityContract(missingParameter), {
    available: false,
    reason_code: 'search_capability_contract_invalid',
  });

  const driftedParameter = structuredClone(searchContract);
  driftedParameter.search_types.advanced.parameters.limit = 'integer (1-100)';
  assert.deepEqual(normalizeSearchCapabilityContract(driftedParameter), {
    available: false,
    reason_code: 'search_capability_contract_invalid',
  });
});
