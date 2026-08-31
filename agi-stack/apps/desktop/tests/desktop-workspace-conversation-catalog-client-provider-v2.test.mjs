import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopWorkspaceConversationCatalogClientProviderV2,
  DesktopWorkspaceConversationCatalogClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/' +
    'desktopWorkspaceConversationCatalogClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop workspace conversation catalog client provider fails closed before publication', () => {
  const provider = createDesktopWorkspaceConversationCatalogClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopWorkspaceConversationCatalogClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_workspace_conversation_catalog_client_unpublished');
      assert.equal(error.message, 'desktop_workspace_conversation_catalog_client_unpublished');
      return true;
    },
  );
});

test('publications and operation bindings pin frozen workspace conversation catalog clients', async () => {
  const provider = createDesktopWorkspaceConversationCatalogClientProviderV2();
  const firstConfig = runtimeConfig('http://127.0.0.1:43501', 'tenant-1', 'project-1');
  const first = provider.publish({ config: firstConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:43503',
    'tenant / operation',
    'project / operation',
  );
  operationConfig.workspaceId = 'workspace / operation';
  const operationClient = first.bindOperation(operationConfig);
  firstConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  const second = provider.publish({
    config: runtimeConfig('http://127.0.0.1:43502', 'tenant-2', 'project-2'),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  const controller = new AbortController();
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return json({
      items: [],
      total: 0,
      has_more: false,
      offset: 0,
      limit: 500,
      next_offset: null,
    });
  };

  try {
    await operationClient.listConversations('project / operation', {
      workspaceId: 'workspace / operation',
      signal: controller.signal,
    });
    await first.client.listConversations('project-1', {
      unboundOnly: true,
      signal: controller.signal,
    });

    assert.equal(Object.isFrozen(provider), true);
    assert.equal(Object.isFrozen(first), true);
    assert.equal(Object.isFrozen(first.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(Object.isFrozen(second), true);
    assert.notEqual(first, second);
    assert.notEqual(first.client, second.client);
    assert.equal(provider.resolve(), second);
    assert.deepEqual(Object.keys(first.client), ['listConversations']);
    assert.deepEqual(Object.keys(operationClient), ['listConversations']);
    assert.equal(calls.length, 2);
    assertConversationCatalogCall(calls[0], {
      apiBaseUrl: 'http://127.0.0.1:43503',
      projectId: 'project / operation',
      workspaceId: 'workspace / operation',
      unboundOnly: null,
      signal: controller.signal,
    });
    assertConversationCatalogCall(calls[1], {
      apiBaseUrl: 'http://127.0.0.1:43501',
      projectId: 'project-1',
      workspaceId: null,
      unboundOnly: 'true',
      signal: controller.signal,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed workspace conversation catalog publication keeps the last-good binding', () => {
  const provider = createDesktopWorkspaceConversationCatalogClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_workspace_conversation_catalog_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_workspace_conversation_catalog_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function assertConversationCatalogCall(
  call,
  { apiBaseUrl, projectId, workspaceId, unboundOnly, signal },
) {
  const url = new URL(call.input);
  assert.equal(url.origin, apiBaseUrl);
  assert.equal(url.pathname, '/api/v1/agent/conversations');
  assert.equal(url.searchParams.get('project_id'), projectId);
  assert.equal(url.searchParams.get('workspace_id'), workspaceId);
  assert.equal(url.searchParams.get('unbound_only'), unboundOnly);
  assert.equal(url.searchParams.get('status'), 'active');
  assert.equal(url.searchParams.get('limit'), '500');
  assert.equal(url.searchParams.get('offset'), '0');
  assert.equal(call.init.method, 'GET');
  assert.equal(call.init.signal, signal);
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
