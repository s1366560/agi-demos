import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopNewTaskFlowClientProviderV2,
  DesktopNewTaskFlowClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/task/' +
    'desktopNewTaskFlowClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop new-task flow client provider fails closed before publication', () => {
  const provider = createDesktopNewTaskFlowClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopNewTaskFlowClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_new_task_flow_client_unpublished');
      assert.equal(error.message, 'desktop_new_task_flow_client_unpublished');
      return true;
    },
  );
});

test('publications pin frozen new-task flow clients to their exact configs', async () => {
  const provider = createDesktopNewTaskFlowClientProviderV2();
  const firstConfig = runtimeConfig('http://127.0.0.1:43101', 'tenant-1', 'project-1');
  const first = provider.publish({ config: firstConfig });
  const operationConfig = runtimeConfig('http://127.0.0.1:43103', 'tenant-3', 'project-3');
  const operationClient = first.bindOperation(operationConfig);
  firstConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  const second = provider.publish({
    config: runtimeConfig('http://127.0.0.1:43102', 'tenant-2', 'project-2'),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input) => {
    calls.push(String(input));
    return json({
      schema_version: 2,
      atomic_creation: true,
      initial_conversation_mode: 'workspace',
      initial_plan_mode: 'plan',
    });
  };

  try {
    assert.equal(await first.client.supportsAgentPlanWorkflow(), true);
    assert.equal(await operationClient.supportsAgentPlanWorkflow(), true);
    assert.equal(Object.isFrozen(first), true);
    assert.equal(Object.isFrozen(first.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(Object.isFrozen(second), true);
    assert.notEqual(first, second);
    assert.notEqual(first.client, second.client);
    assert.equal(provider.resolve(), second);
    assert.deepEqual(Object.keys(first.client).sort(), ownedMethodNames());
    assert.deepEqual(calls, [
      'http://127.0.0.1:43101/api/v1/tenants/tenant-1/projects/project-1/task-sessions/capabilities',
      'http://127.0.0.1:43103/api/v1/tenants/tenant-3/projects/project-3/task-sessions/capabilities',
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed new-task flow publication keeps the last-good binding', () => {
  const provider = createDesktopNewTaskFlowClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_new_task_flow_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_new_task_flow_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function ownedMethodNames() {
  return [
    'approvePlanAndStart',
    'createTaskSession',
    'getConversationMessages',
    'listAgentPlanTasks',
    'listWorkspaces',
    'sendMessage',
    'supportsAgentPlanWorkflow',
    'switchPlanMode',
  ];
}

function runtimeConfig(apiBaseUrl, tenantId, projectId) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl,
    localApiToken: 'local-session-token',
    tenantId,
    projectId,
    workspaceId: 'workspace-1',
    mode: 'local',
  };
}

function json(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}
