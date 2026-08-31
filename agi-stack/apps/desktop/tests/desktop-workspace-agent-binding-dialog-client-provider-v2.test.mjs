import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopWorkspaceAgentBindingDialogClientProviderV2,
  DesktopWorkspaceAgentBindingDialogClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/' +
    'desktopWorkspaceAgentBindingDialogClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop workspace Agent-binding dialog client provider fails closed before publication', () => {
  const provider = createDesktopWorkspaceAgentBindingDialogClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(
        error instanceof DesktopWorkspaceAgentBindingDialogClientProviderErrorV2,
        true,
      );
      assert.equal(
        error.reasonCode,
        'desktop_workspace_agent_binding_dialog_client_unpublished',
      );
      assert.equal(
        error.message,
        'desktop_workspace_agent_binding_dialog_client_unpublished',
      );
      return true;
    },
  );
});

test('publications and operation bindings pin frozen workspace Agent-binding dialog clients', async () => {
  const provider = createDesktopWorkspaceAgentBindingDialogClientProviderV2();
  const firstConfig = runtimeConfig('http://127.0.0.1:43401', 'tenant-1', 'project-1');
  const first = provider.publish({ config: firstConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:43403',
    'tenant / operation',
    'project / operation',
  );
  operationConfig.workspaceId = 'workspace / operation';
  const operationClient = first.bindOperation(operationConfig);
  firstConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  const second = provider.publish({
    config: runtimeConfig('http://127.0.0.1:43402', 'tenant-2', 'project-2'),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  const controller = new AbortController();
  let responseMode = 'definitions';
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    if (responseMode === 'definitions') {
      return json({
        items: [
          {
            id: 'agent / operation',
            project_id: 'project / operation',
            name: 'project-agent',
            display_name: 'Project Agent',
            enabled: true,
            model: 'project-model',
          },
        ],
      });
    }
    if (responseMode === 'unbind') return new Response(null, { status: 204 });
    return json(
      {
        id: 'binding / operation',
        workspace_id: 'workspace / operation',
        agent_id: 'agent / operation',
        display_name: 'Project Agent',
        description: 'Workspace helper',
        config: {},
        is_active: true,
        hex_q: null,
        hex_r: null,
        theme_color: null,
        label: null,
        status: null,
        created_at: '2026-09-01T00:00:00Z',
        updated_at: '2026-09-01T00:01:00Z',
      },
      201,
    );
  };

  try {
    const definitions =
      await operationClient.listWorkspaceBindingAgentDefinitionsForProject(
        'project / operation',
        'tenant / operation',
        controller.signal,
      );
    responseMode = 'bind';
    const binding = await operationClient.bindWorkspaceAgentForProject(
      'project / operation',
      'workspace / operation',
      {
        agentId: 'agent / operation',
        displayName: ' Project Agent ',
        description: ' Workspace helper ',
      },
      'tenant / operation',
      controller.signal,
    );
    responseMode = 'unbind';
    await operationClient.unbindWorkspaceAgentForProject(
      'project / operation',
      'workspace / operation',
      'binding / operation',
      'tenant / operation',
      controller.signal,
    );

    assert.deepEqual(definitions.map(({ id }) => id), ['agent / operation']);
    assert.equal(binding.id, 'binding / operation');
    assert.equal(Object.isFrozen(provider), true);
    assert.equal(Object.isFrozen(first), true);
    assert.equal(Object.isFrozen(first.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(Object.isFrozen(second), true);
    assert.notEqual(first, second);
    assert.notEqual(first.client, second.client);
    assert.equal(provider.resolve(), second);
    assert.deepEqual(Object.keys(first.client).sort(), ownedMethodNames());
    assert.deepEqual(Object.keys(operationClient).sort(), ownedMethodNames());
    const definitionsPath =
      'http://127.0.0.1:43403/api/v1/agent/definitions?' +
      'limit=100&enabled_only=true&project_id=project+%2F+operation&tenant_id=tenant+%2F+operation';
    const bindingPath =
      'http://127.0.0.1:43403/api/v1/tenants/tenant%20%2F%20operation/' +
      'projects/project%20%2F%20operation/workspaces/workspace%20%2F%20operation/agents';
    assert.deepEqual(
      calls.map((call) => [call.input, call.init.method]),
      [
        [definitionsPath, 'GET'],
        [bindingPath, 'POST'],
        [`${bindingPath}/binding%20%2F%20operation`, 'DELETE'],
      ],
    );
    assert.deepEqual(JSON.parse(calls[1].init.body), {
      agent_id: 'agent / operation',
      display_name: 'Project Agent',
      description: 'Workspace helper',
    });
    for (const call of calls) assert.equal(call.init.signal, controller.signal);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed workspace Agent-binding dialog publication keeps the last-good binding', () => {
  const provider = createDesktopWorkspaceAgentBindingDialogClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_workspace_agent_binding_dialog_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_workspace_agent_binding_dialog_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function ownedMethodNames() {
  return [
    'bindWorkspaceAgentForProject',
    'listWorkspaceBindingAgentDefinitionsForProject',
    'unbindWorkspaceAgentForProject',
  ];
}

function runtimeConfig(apiBaseUrl, tenantId, projectId) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl,
    apiKey: 'trusted-session',
    localApiToken: 'launch-capability',
    tenantId,
    projectId,
    workspaceId: 'workspace-1',
    mode: 'local',
  };
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
