import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopHitlResponseClientProviderV2,
  DesktopHitlResponseClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/' +
    'desktopHitlResponseClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop HITL response client provider fails closed before publication', () => {
  const provider = createDesktopHitlResponseClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopHitlResponseClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_hitl_response_client_unpublished');
      assert.equal(error.message, 'desktop_hitl_response_client_unpublished');
      return true;
    },
  );
});

test('publications pin frozen HITL response clients to their exact configs', async () => {
  const provider = createDesktopHitlResponseClientProviderV2();
  const firstConfig = runtimeConfig('http://127.0.0.1:43811', 'tenant-1', 'project-1');
  const first = provider.publish({ config: firstConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:43813',
    'tenant / operation',
    'project / operation',
  );
  const operationClient = first.bindOperation(operationConfig);
  firstConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  const second = provider.publish({
    config: runtimeConfig('http://127.0.0.1:43812', 'tenant-2', 'project-2'),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return json({ success: true, status: 'accepted' });
  };

  try {
    await operationClient.respondToHitl({
      requestId: 'permission / operation',
      hitlType: 'permission',
      responseData: {
        granted: false,
        feedback: 'Keep the denial in the canonical response.',
      },
      expectedRevision: 7,
      idempotencyKey: 'permission / operation:7:deny',
    });
    await first.client.respondToHitl({
      requestId: 'clarification / publication',
      hitlType: 'clarification',
      responseData: { answer: 'Use the indexed repository.' },
    });

    assert.equal(Object.isFrozen(provider), true);
    assert.equal(Object.isFrozen(first), true);
    assert.equal(Object.isFrozen(first.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(Object.isFrozen(second), true);
    assert.notEqual(first, second);
    assert.notEqual(first.client, second.client);
    assert.equal(provider.resolve(), second);
    assert.deepEqual(Object.keys(first.client), ['respondToHitl']);
    assert.deepEqual(Object.keys(operationClient), ['respondToHitl']);
    assert.equal(calls.length, 2);
    assertHitlResponseCall(calls[0], {
      apiBaseUrl: 'http://127.0.0.1:43813',
      payload: {
        request_id: 'permission / operation',
        hitl_type: 'permission',
        response_data: {
          granted: false,
          feedback: 'Keep the denial in the canonical response.',
        },
        expected_revision: 7,
        idempotency_key: 'permission / operation:7:deny',
      },
    });
    assertHitlResponseCall(calls[1], {
      apiBaseUrl: 'http://127.0.0.1:43811',
      payload: {
        request_id: 'clarification / publication',
        hitl_type: 'clarification',
        response_data: { answer: 'Use the indexed repository.' },
      },
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed HITL response publication keeps the last-good binding', () => {
  const provider = createDesktopHitlResponseClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_hitl_response_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_hitl_response_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function assertHitlResponseCall(call, { apiBaseUrl, payload }) {
  const url = new URL(call.input);
  assert.equal(url.origin, apiBaseUrl);
  assert.equal(url.pathname, '/api/v1/agent/hitl/respond');
  assert.equal(call.init.method, 'POST');
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
