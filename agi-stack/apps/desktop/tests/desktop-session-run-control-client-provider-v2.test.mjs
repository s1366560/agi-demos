import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopSessionRunControlClientProviderV2,
  DesktopSessionRunControlClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/' +
    'desktopSessionRunControlClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop session run-control client provider fails closed before publication', () => {
  const provider = createDesktopSessionRunControlClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopSessionRunControlClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_session_run_control_client_unpublished');
      assert.equal(error.message, 'desktop_session_run_control_client_unpublished');
      return true;
    },
  );
});

test('publications pin frozen five-method run-control clients to exact configs', async () => {
  const provider = createDesktopSessionRunControlClientProviderV2();
  const publicationConfig = runtimeConfig(
    'http://127.0.0.1:44011',
    'local',
    'publication-session',
    'publication-launch',
  );
  const publication = provider.publish({ config: publicationConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:44012',
    'local',
    'operation-session',
    'operation-launch',
  );
  const operationClient = publication.bindOperation(operationConfig);
  publicationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.localApiToken = 'mutated-launch';

  const cloud = provider.publish({
    config: runtimeConfig('https://cloud.example.test', 'cloud', '', ''),
  });
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const fetchCalls = [];
  const cloudCommands = [];
  globalThis.fetch = async (input, init) => {
    fetchCalls.push({ input: String(input), init });
    return json(runOutcome('operation-run'));
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          cloudCommands.push({ command, args });
          return { status: 200, body: runOutcome('cloud-run') };
        },
      },
    },
  };

  try {
    await operationClient.pauseRun('run / one', 7);
    await operationClient.resumeRun('run / one', 8);
    await operationClient.forkRecoveryRun(
      'run / one',
      9,
      'desktop-recovery-fork:run / one:9',
    );
    await operationClient.cancelRun('run / one', 10);
    await operationClient.reviewRun('run / one', {
      action: 'request_changes',
      expectedRevision: 11,
      feedback: 'Add the missing evidence.',
    });
    await cloud.client.pauseRun('cloud-run', 12);

    const expectedMethods = [
      'pauseRun',
      'resumeRun',
      'forkRecoveryRun',
      'cancelRun',
      'reviewRun',
    ];
    assert.equal(Object.isFrozen(provider), true);
    assert.equal(Object.isFrozen(publication), true);
    assert.equal(Object.isFrozen(publication.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(Object.isFrozen(cloud), true);
    assert.notEqual(publication, cloud);
    assert.notEqual(publication.client, cloud.client);
    assert.equal(provider.resolve(), cloud);
    assert.deepEqual(Object.keys(publication.client), expectedMethods);
    assert.deepEqual(Object.keys(operationClient), expectedMethods);

    assert.equal(fetchCalls.length, 5);
    assertRunCall(fetchCalls[0], 'pause', { expected_revision: 7 });
    assertRunCall(fetchCalls[1], 'resume', { expected_revision: 8 });
    assertRunCall(fetchCalls[2], 'fork', {
      expected_revision: 9,
      idempotency_key: 'desktop-recovery-fork:run / one:9',
    });
    assertRunCall(fetchCalls[3], 'cancel', { expected_revision: 10 });
    assertRunCall(fetchCalls[4], 'review', {
      action: 'request_changes',
      expected_revision: 11,
      feedback: 'Add the missing evidence.',
    });
    for (const call of fetchCalls) {
      assert.equal(new URL(call.input).origin, 'http://127.0.0.1:44012');
      const headers = new Headers(call.init.headers);
      assert.equal(headers.get('Authorization'), 'Bearer operation-session');
      assert.equal(headers.get('X-Agistack-Launch'), 'operation-launch');
    }

    assert.equal(cloudCommands.length, 1);
    assert.equal(cloudCommands[0].command, 'cloud_request');
    assert.deepEqual(cloudCommands[0].args.request, {
      path: '/api/v1/agent/runs/cloud-run/pause',
      method: 'POST',
      body: { expected_revision: 12 },
    });
    assert.equal(JSON.stringify(cloudCommands).includes('Bearer'), false);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('failed run-control publication keeps the last-good binding', () => {
  const provider = createDesktopSessionRunControlClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_session_run_control_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_session_run_control_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function assertRunCall(call, action, body) {
  const url = new URL(call.input);
  assert.equal(url.pathname, `/api/v1/agent/runs/run%20%2F%20one/${action}`);
  assert.equal(call.init.method, 'POST');
  assert.deepEqual(JSON.parse(String(call.init.body)), body);
}

function runtimeConfig(apiBaseUrl, mode, apiKey, localApiToken) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl,
    mode,
    apiKey,
    localApiToken,
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
  };
}

function runOutcome(runId) {
  return {
    accepted: true,
    created: true,
    status: 'running',
    source_run: { id: 'source-run', status: 'disconnected', revision: 4 },
    run: {
      id: runId,
      conversation_id: 'conversation-1',
      status: 'running',
      revision: 12,
    },
  };
}

function json(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}
