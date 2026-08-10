import assert from 'node:assert/strict';
import { test } from 'node:test';

const { createTenantAgentDashboardHttpClient } =
  await import('/tmp/agistack-desktop-test-dist/src/features/tenant/tenantAgentDashboardHttpClient.js');

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test('Cloud Agent Dashboard loads revisioned config, hooks and tenant traces', async () => {
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url: String(url), init });
    const path = new URL(String(url)).pathname;
    if (path === '/api/v1/system/info') return jsonResponse(systemInfo());
    if (path === '/api/v1/agent/config') return jsonResponse(config());
    if (path.endsWith('/can-modify')) return jsonResponse({ can_modify: true });
    if (path.endsWith('/hooks/catalog')) {
      return jsonResponse({ hooks: [hookCatalogEntry()] });
    }
    if (path.endsWith('/active/count')) {
      return jsonResponse({ tenant_id: 'tenant-1', active_count: 1 });
    }
    if (path.endsWith('/tenant/tenant-1')) {
      return jsonResponse({ tenant_id: 'tenant-1', runs: [run()], total: 1 });
    }
    throw new Error(`Unexpected request: ${path}`);
  };

  const snapshot = await createTenantAgentDashboardHttpClient(runtimeConfig()).load(scope());

  assert.equal(snapshot.availability, 'available');
  assert.equal(snapshot.serviceVersion, '0.1.0');
  assert.equal(snapshot.authorityRevision, 7);
  assert.equal(snapshot.canModify, true);
  assert.equal(snapshot.config?.llmModel, 'gpt-5.6');
  assert.equal(snapshot.runtimeInfo?.agentRuntimeMode, 'ray');
  assert.equal(snapshot.runtimeInfo?.memoryRuntimeMode, 'dual');
  assert.equal(snapshot.runtimeInfo?.toolProviderMode, 'plugin');
  assert.equal(snapshot.runtimeInfo?.failurePersistenceEnabled, true);
  assert.equal(snapshot.hookCatalog[0].key, 'audit.before_tool');
  assert.equal(snapshot.runs[0].runId, 'run-1');
  assert.equal(snapshot.activeRunCount, 1);
  assert.deepEqual(snapshot.allowedActions, [
    'view-config',
    'update-config',
    'view-hook-catalog',
    'list-runs',
    'filter-runs',
    'inspect-run',
    'inspect-trace',
    'refresh',
    'retry',
  ]);
  assert.ok(
    requests.every(
      ({ init }) => new Headers(init.headers).get('Authorization') === 'Bearer cloud-token',
    ),
  );
});

test('Cloud Agent Dashboard update and trace inspection preserve authority identity', async () => {
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({
      url: String(url),
      method: init?.method ?? 'GET',
      body: init?.body ? JSON.parse(init.body) : null,
    });
    const path = new URL(String(url)).pathname;
    if (path === '/api/v1/agent/config') {
      return jsonResponse(config({ llm_model: 'claude-sonnet', authority_revision: 8 }));
    }
    return jsonResponse({
      trace_id: 'trace-1',
      conversation_id: 'conversation-1',
      runs: [run()],
      total: 1,
    });
  };
  const client = createTenantAgentDashboardHttpClient(runtimeConfig());

  const updated = await client.updateConfig(
    scope(),
    {
      llmModel: 'claude-sonnet',
      llmTemperature: 0.4,
      patternLearningEnabled: true,
      multiLevelThinkingEnabled: true,
      maxWorkPlanSteps: 12,
      toolTimeoutSeconds: 90,
      enabledTools: ['read_file'],
      disabledTools: ['terminal'],
      runtimeHooks: [runtimeHook()],
    },
    7,
  );
  const trace = await client.inspectTrace(scope(), 'conversation-1', 'trace-1');

  assert.equal(updated.authorityRevision, 8);
  assert.equal(trace.runs[0].runId, 'run-1');
  assert.equal(
    requests[0].url,
    'https://cloud.example/api/v1/agent/config?tenant_id=tenant-1&expected_revision=7',
  );
  assert.deepEqual(requests[0].body, {
    llm_model: 'claude-sonnet',
    llm_temperature: 0.4,
    pattern_learning_enabled: true,
    multi_level_thinking_enabled: true,
    max_work_plan_steps: 12,
    tool_timeout_seconds: 90,
    enabled_tools: ['read_file'],
    disabled_tools: ['terminal'],
    runtime_hooks: [
      {
        hook_name: 'before_tool',
        plugin_name: 'audit',
        hook_family: 'policy',
        executor_kind: 'plugin',
        source_ref: 'audit',
        entrypoint: 'before_tool',
        enabled: false,
        priority: 25,
        settings: { redact: true },
      },
    ],
  });
  assert.equal(
    requests[1].url,
    'https://cloud.example/api/v1/agent/trace/runs/conversation-1/trace/trace-1',
  );
});

test('Local Agent Dashboard returns stable unavailable authority without network access', async () => {
  globalThis.fetch = async () => {
    throw new Error('Local unavailable authority must not fetch');
  };
  const snapshot = await createTenantAgentDashboardHttpClient(
    runtimeConfig({
      mode: 'local',
      apiBaseUrl: 'http://127.0.0.1:43121',
      tenantId: 'tenant-local',
    }),
  ).load({ authority: 'local', tenantId: 'tenant-local' });

  assert.equal(snapshot.availability, 'unavailable');
  assert.equal(snapshot.reasonCode, 'local_agent_dashboard_authority_unavailable');
  assert.deepEqual(snapshot.allowedActions, []);
  assert.equal(snapshot.config, null);
  assert.equal(snapshot.runtimeInfo, null);
  assert.deepEqual(snapshot.runs, []);
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

function config(overrides = {}) {
  return {
    id: 'config-1',
    tenant_id: 'tenant-1',
    config_type: 'tenant',
    llm_model: 'gpt-5.6',
    llm_temperature: 0.2,
    pattern_learning_enabled: true,
    multi_level_thinking_enabled: false,
    max_work_plan_steps: 10,
    tool_timeout_seconds: 60,
    enabled_tools: ['read_file'],
    disabled_tools: [],
    runtime_hooks: [],
    runtime_hook_settings_redacted: false,
    multi_agent_enabled: true,
    authority_revision: 7,
    created_at: '2026-08-03T00:00:00Z',
    updated_at: '2026-08-03T00:00:00Z',
    ...overrides,
  };
}

function run() {
  return {
    run_id: 'run-1',
    conversation_id: 'conversation-1',
    subagent_name: 'Researcher',
    task: 'Audit runtime',
    status: 'running',
    created_at: '2026-08-03T00:00:00Z',
    started_at: '2026-08-03T00:00:01Z',
    ended_at: null,
    summary: null,
    error: null,
    execution_time_ms: null,
    tokens_used: 120,
    metadata: {},
    frozen_result_text: null,
    frozen_at: null,
    trace_id: 'trace-1',
    parent_span_id: null,
  };
}

function hookCatalogEntry() {
  return {
    plugin_name: 'audit',
    hook_name: 'before_tool',
    hook_family: 'tool',
    display_name: 'Before tool',
    description: 'Audit tool calls',
    default_priority: 10,
    default_enabled: true,
    default_executor_kind: 'builtin',
    default_source_ref: null,
    default_entrypoint: null,
    default_settings: {},
    settings_schema: {},
  };
}

function runtimeHook() {
  return {
    hookName: 'before_tool',
    pluginName: 'audit',
    hookFamily: 'policy',
    executorKind: 'plugin',
    sourceRef: 'audit',
    entrypoint: 'before_tool',
    enabled: false,
    priority: 25,
    settings: { redact: true },
  };
}

function systemInfo() {
  return {
    edition: 'enterprise',
    features: [{ name: 'multi-agent' }],
    agent_runtime: { mode: 'ray' },
    memory_runtime: {
      mode: 'dual',
      tool_provider_mode: 'plugin',
      failure_persistence_enabled: true,
    },
  };
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
