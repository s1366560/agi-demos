import assert from 'node:assert/strict';
import { test } from 'node:test';

const { DesktopApiError } = await import('/tmp/agistack-desktop-test-dist/src/api/client.js');
const { createTenantAgentDashboardController } =
  await import('/tmp/agistack-desktop-test-dist/src/features/tenant/tenantAgentDashboardController.js');

test('Agent Dashboard controller loads, filters, inspects and revision-updates', async () => {
  const calls = [];
  const controller = createTenantAgentDashboardController({
    authority: 'cloud',
    initialScope: scope(),
    client: {
      async load() {
        calls.push('load');
        return snapshot();
      },
      async updateConfig(_scope, input, revision) {
        calls.push(['update', revision, input.llmModel]);
        return {
          ...snapshot().config,
          llmModel: input.llmModel,
          authorityRevision: revision + 1,
        };
      },
      async inspectTrace(_scope, conversationId, traceId) {
        calls.push(['trace', conversationId, traceId]);
        return {
          traceId,
          conversationId,
          runs: snapshot().runs,
          total: 1,
        };
      },
    },
  });
  await controller.load(scope());
  assert.equal(controller.getSnapshot().state, 'ready');
  assert.equal(controller.getSnapshot().visibleRuns.length, 1);

  controller.setFilters({ status: 'completed', search: '' });
  assert.equal(controller.getSnapshot().visibleRuns.length, 0);
  controller.setFilters({ status: null, search: 'research' });
  assert.equal(controller.getSnapshot().visibleRuns.length, 1);

  await controller.inspectRun('run-1');
  assert.equal(controller.getSnapshot().selectedTrace?.traceId, 'trace-1');
  await controller.updateConfig({
    ...editableConfig(),
    llmModel: 'claude-sonnet',
  });
  assert.equal(controller.getSnapshot().config?.llmModel, 'claude-sonnet');
  assert.equal(controller.getSnapshot().authorityRevision, 8);
  assert.deepEqual(calls, [
    'load',
    ['trace', 'conversation-1', 'trace-1'],
    ['update', 7, 'claude-sonnet'],
  ]);
});

test('Agent Dashboard controller preserves stale data on retryable failure', async () => {
  let attempts = 0;
  const controller = createTenantAgentDashboardController({
    authority: 'cloud',
    initialScope: scope(),
    client: {
      async load() {
        attempts += 1;
        if (attempts === 1) return snapshot();
        throw new Error('network');
      },
      async updateConfig() {
        throw new Error('unused');
      },
      async inspectTrace() {
        throw new Error('unused');
      },
    },
  });
  await controller.load(scope());
  await assert.rejects(controller.retry());
  assert.equal(controller.getSnapshot().state, 'stale');
  assert.equal(controller.getSnapshot().runs.length, 1);
  assert.equal(controller.getSnapshot().retryVisible, true);
});

test('Agent Dashboard controller preserves structured nested revision conflicts', async () => {
  const controller = createTenantAgentDashboardController({
    authority: 'cloud',
    initialScope: scope(),
    client: {
      async load() {
        return snapshot();
      },
      async updateConfig() {
        throw new DesktopApiError('conflict', 409, {
          detail: {
            reason_code: 'tenant_agent_config_revision_conflict',
            expected_revision: 7,
            authority_revision: 9,
          },
        });
      },
      async inspectTrace() {
        throw new Error('unused');
      },
    },
  });
  await controller.load(scope());
  await assert.rejects(controller.updateConfig(editableConfig()));
  const model = controller.getSnapshot();
  assert.equal(model.state, 'conflict');
  assert.equal(model.reasonCode, 'tenant_agent_config_revision_conflict');
  assert.deepEqual(model.configConflict, {
    expectedRevision: 7,
    authorityRevision: 9,
  });
});

function scope() {
  return { authority: 'cloud', tenantId: 'tenant-1' };
}

function editableConfig() {
  return {
    llmModel: 'gpt-5.6',
    llmTemperature: 0.2,
    patternLearningEnabled: true,
    multiLevelThinkingEnabled: false,
    maxWorkPlanSteps: 10,
    toolTimeoutSeconds: 60,
    enabledTools: ['read_file'],
    disabledTools: [],
    runtimeHooks: [],
  };
}

function snapshot() {
  return {
    scope: scope(),
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: '3.0.0',
    allowedActions: [
      'view-config',
      'update-config',
      'view-hook-catalog',
      'list-runs',
      'filter-runs',
      'inspect-run',
      'inspect-trace',
      'refresh',
      'retry',
    ],
    authorityRevision: 7,
    canModify: true,
    config: {
      id: 'config-1',
      tenantId: 'tenant-1',
      configType: 'tenant',
      ...editableConfig(),
      runtimeHookSettingsRedacted: false,
      multiAgentEnabled: true,
      authorityRevision: 7,
      createdAt: '2026-08-03T00:00:00Z',
      updatedAt: '2026-08-03T00:00:00Z',
    },
    hookCatalog: [],
    runtimeInfo: {
      edition: 'enterprise',
      features: [],
      agentRuntimeMode: 'ray',
      memoryRuntimeMode: 'dual',
      toolProviderMode: 'plugin',
      failurePersistenceEnabled: true,
    },
    runs: [
      {
        runId: 'run-1',
        conversationId: 'conversation-1',
        subagentName: 'Researcher',
        task: 'Audit runtime',
        status: 'running',
        createdAt: '2026-08-03T00:00:00Z',
        startedAt: '2026-08-03T00:00:01Z',
        endedAt: null,
        summary: null,
        error: null,
        executionTimeMs: null,
        tokensUsed: 120,
        traceId: 'trace-1',
        parentSpanId: null,
      },
    ],
    activeRunCount: 1,
  };
}
