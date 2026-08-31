import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopSessionTimelineClientProviderV2,
  DesktopSessionTimelineClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/' +
    'desktopSessionTimelineClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop session timeline client provider fails closed before publication', () => {
  const provider = createDesktopSessionTimelineClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopSessionTimelineClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_session_timeline_client_unpublished');
      assert.equal(error.message, 'desktop_session_timeline_client_unpublished');
      return true;
    },
  );
});

test('publications and operation bindings pin frozen session timeline clients', async () => {
  const provider = createDesktopSessionTimelineClientProviderV2();
  const firstConfig = runtimeConfig('http://127.0.0.1:43601', 'tenant-1', 'project-1');
  const first = provider.publish({ config: firstConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:43603',
    'tenant / operation',
    'project / operation',
  );
  const operationClient = first.bindOperation(operationConfig);
  firstConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  const second = provider.publish({
    config: runtimeConfig('http://127.0.0.1:43602', 'tenant-2', 'project-2'),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  const controller = new AbortController();
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return json({ timeline: [], has_more: false });
  };

  try {
    await operationClient.getConversationMessages(
      'conversation / operation',
      'project / operation',
      {
        limit: 75,
        fromTimeUs: 1_000,
        fromCounter: 4,
        beforeTimeUs: 2_000,
        beforeCounter: 7,
        signal: controller.signal,
      },
    );
    await first.client.getConversationMessages('conversation / first', 'project-1', {
      limit: 50,
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
    assert.deepEqual(Object.keys(first.client), ['getConversationMessages']);
    assert.deepEqual(Object.keys(operationClient), ['getConversationMessages']);
    assert.equal(calls.length, 2);
    assertTimelineCall(calls[0], {
      apiBaseUrl: 'http://127.0.0.1:43603',
      conversationId: 'conversation / operation',
      projectId: 'project / operation',
      limit: '75',
      fromTimeUs: '1000',
      fromCounter: '4',
      beforeTimeUs: '2000',
      beforeCounter: '7',
      signal: controller.signal,
    });
    assertTimelineCall(calls[1], {
      apiBaseUrl: 'http://127.0.0.1:43601',
      conversationId: 'conversation / first',
      projectId: 'project-1',
      limit: '50',
      fromTimeUs: null,
      fromCounter: null,
      beforeTimeUs: null,
      beforeCounter: null,
      signal: controller.signal,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed session timeline publication keeps the last-good binding', () => {
  const provider = createDesktopSessionTimelineClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_session_timeline_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_session_timeline_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function assertTimelineCall(
  call,
  {
    apiBaseUrl,
    conversationId,
    projectId,
    limit,
    fromTimeUs,
    fromCounter,
    beforeTimeUs,
    beforeCounter,
    signal,
  },
) {
  const url = new URL(call.input);
  assert.equal(url.origin, apiBaseUrl);
  assert.equal(
    url.pathname,
    `/api/v1/agent/conversations/${encodeURIComponent(conversationId)}/messages`,
  );
  assert.equal(url.searchParams.get('project_id'), projectId);
  assert.equal(url.searchParams.get('limit'), limit);
  assert.equal(url.searchParams.get('from_time_us'), fromTimeUs);
  assert.equal(url.searchParams.get('from_counter'), fromCounter);
  assert.equal(url.searchParams.get('before_time_us'), beforeTimeUs);
  assert.equal(url.searchParams.get('before_counter'), beforeCounter);
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
