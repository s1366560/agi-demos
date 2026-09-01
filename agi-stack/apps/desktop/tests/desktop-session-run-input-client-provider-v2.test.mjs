import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopSessionRunInputClientProviderV2,
  DesktopSessionRunInputClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/' +
    'desktopSessionRunInputClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop session run-input client provider fails closed before publication', () => {
  const provider = createDesktopSessionRunInputClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopSessionRunInputClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_session_run_input_client_unpublished');
      assert.equal(error.message, 'desktop_session_run_input_client_unpublished');
      return true;
    },
  );
});

test('publications pin frozen three-method run-input clients to exact configs', async () => {
  const provider = createDesktopSessionRunInputClientProviderV2();
  const publicationConfig = runtimeConfig(
    'http://127.0.0.1:44211',
    'publication-session',
    'publication-launch',
  );
  const publication = provider.publish({ config: publicationConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:44212',
    'operation-session',
    'operation-launch',
  );
  const operationClient = publication.bindOperation(operationConfig);
  publicationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.localApiToken = 'mutated-launch';

  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return json({ call: calls.length });
  };

  try {
    const created = await operationClient.createRunInput('run / one', {
      expectedRunRevision: 7,
      message: 'Review the selected change',
      messageId: 'message-1',
      idempotencyKey: 'run-input-1',
      delivery: 'queue_next',
      references: [],
      contextItems: [],
    });
    const listed = await operationClient.listRunInputs('run / one');
    const promoted = await operationClient.promoteRunInput(
      'input / one',
      8,
      'promote-input-1',
    );

    assert.equal(created.call, 1);
    assert.equal(listed.call, 2);
    assert.equal(promoted.call, 3);
    assert.equal(Object.isFrozen(provider), true);
    assert.equal(Object.isFrozen(publication), true);
    assert.equal(Object.isFrozen(publication.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(provider.resolve(), publication);
    assert.deepEqual(Object.keys(publication.client), [
      'createRunInput',
      'listRunInputs',
      'promoteRunInput',
    ]);
    assert.deepEqual(Object.keys(operationClient), [
      'createRunInput',
      'listRunInputs',
      'promoteRunInput',
    ]);
    assert.equal(calls.length, 3);

    const createCall = requestDetails(calls[0]);
    assert.equal(createCall.url.origin, 'http://127.0.0.1:44212');
    assert.equal(createCall.url.pathname, '/api/v1/agent/runs/run%20%2F%20one/inputs');
    assert.equal(createCall.init.method, 'POST');
    assert.deepEqual(JSON.parse(createCall.init.body), {
      expected_run_revision: 7,
      message: 'Review the selected change',
      message_id: 'message-1',
      idempotency_key: 'run-input-1',
      delivery: 'queue_next',
      references: [],
      context_items: [],
    });

    const listCall = requestDetails(calls[1]);
    assert.equal(listCall.url.pathname, '/api/v1/agent/runs/run%20%2F%20one/inputs');
    assert.equal(listCall.init.method, 'GET');

    const promoteCall = requestDetails(calls[2]);
    assert.equal(
      promoteCall.url.pathname,
      '/api/v1/agent/run-inputs/input%20%2F%20one/promote-to-plan',
    );
    assert.equal(promoteCall.init.method, 'POST');
    assert.deepEqual(JSON.parse(promoteCall.init.body), {
      expected_source_run_revision: 8,
      idempotency_key: 'promote-input-1',
    });

    for (const call of calls) {
      const headers = new Headers(call.init.headers);
      assert.equal(headers.get('Authorization'), 'Bearer operation-session');
      assert.equal(headers.get('X-Agistack-Launch'), 'operation-launch');
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed run-input publication keeps the last-good binding', () => {
  const provider = createDesktopSessionRunInputClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_session_run_input_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_session_run_input_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function runtimeConfig(apiBaseUrl, apiKey, localApiToken) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl,
    mode: 'local',
    apiKey,
    localApiToken,
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
  };
}

function requestDetails(call) {
  return {
    url: new URL(call.input),
    init: call.init,
  };
}

function json(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}
