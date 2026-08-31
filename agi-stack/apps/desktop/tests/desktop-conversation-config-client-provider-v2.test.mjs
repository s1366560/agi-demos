import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopConversationConfigClientProviderV2,
  DesktopConversationConfigClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/' +
    'desktopConversationConfigClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop conversation config client provider fails closed before publication', () => {
  const provider = createDesktopConversationConfigClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopConversationConfigClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_conversation_config_client_unpublished');
      assert.equal(error.message, 'desktop_conversation_config_client_unpublished');
      return true;
    },
  );
});

test('publications pin frozen config clients with exact set and reset payloads', async () => {
  const provider = createDesktopConversationConfigClientProviderV2();
  const firstConfig = runtimeConfig('http://127.0.0.1:43701', 'tenant-1', 'project-1');
  const first = provider.publish({ config: firstConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:43703',
    'tenant / operation',
    'project / operation',
  );
  const operationClient = first.bindOperation(operationConfig);
  firstConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  const second = provider.publish({
    config: runtimeConfig('http://127.0.0.1:43702', 'tenant-2', 'project-2'),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return json({ id: 'conversation-1', project_id: 'project-1', agent_config: {} });
  };

  try {
    await operationClient.updateAgentConversationConfig(
      'conversation / set',
      {
        llm_model_override: 'model / set',
        llm_route_override: {
          provider_id: 'provider / set',
          model_id: 'model / set',
        },
      },
      'project / operation',
    );
    await first.client.updateAgentConversationConfig(
      'conversation / reset',
      {
        llm_model_override: null,
        llm_route_override: null,
      },
      'project-1',
    );

    assert.equal(Object.isFrozen(provider), true);
    assert.equal(Object.isFrozen(first), true);
    assert.equal(Object.isFrozen(first.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(Object.isFrozen(second), true);
    assert.notEqual(first, second);
    assert.notEqual(first.client, second.client);
    assert.equal(provider.resolve(), second);
    assert.deepEqual(Object.keys(first.client), ['updateAgentConversationConfig']);
    assert.deepEqual(Object.keys(operationClient), ['updateAgentConversationConfig']);
    assert.equal(calls.length, 2);
    assertConfigCall(calls[0], {
      apiBaseUrl: 'http://127.0.0.1:43703',
      conversationId: 'conversation / set',
      projectId: 'project / operation',
      payload: {
        llm_model_override: 'model / set',
        llm_route_override: {
          provider_id: 'provider / set',
          model_id: 'model / set',
        },
      },
    });
    assertConfigCall(calls[1], {
      apiBaseUrl: 'http://127.0.0.1:43701',
      conversationId: 'conversation / reset',
      projectId: 'project-1',
      payload: {
        llm_model_override: null,
        llm_route_override: null,
      },
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed conversation config publication keeps the last-good binding', () => {
  const provider = createDesktopConversationConfigClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_conversation_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_conversation_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function assertConfigCall(call, { apiBaseUrl, conversationId, projectId, payload }) {
  const url = new URL(call.input);
  assert.equal(url.origin, apiBaseUrl);
  assert.equal(
    url.pathname,
    `/api/v1/agent/conversations/${encodeURIComponent(conversationId)}/config`,
  );
  assert.equal(url.searchParams.get('project_id'), projectId);
  assert.equal(call.init.method, 'PATCH');
  assert.deepEqual(JSON.parse(String(call.init.body)), payload);
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
