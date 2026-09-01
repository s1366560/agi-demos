import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopSessionRunChangesClientProviderV2,
  DesktopSessionRunChangesClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/' +
    'desktopSessionRunChangesClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop session run-changes client provider fails closed before publication', () => {
  const provider = createDesktopSessionRunChangesClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopSessionRunChangesClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_session_run_changes_client_unpublished');
      assert.equal(error.message, 'desktop_session_run_changes_client_unpublished');
      return true;
    },
  );
});

test('publications pin frozen one-method run-changes clients to exact configs', async () => {
  const provider = createDesktopSessionRunChangesClientProviderV2();
  const publicationConfig = runtimeConfig(
    'http://127.0.0.1:44111',
    'publication-session',
    'publication-launch',
  );
  const publication = provider.publish({ config: publicationConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:44112',
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
    return json(changeSnapshot());
  };

  try {
    const snapshot = await operationClient.getRunChanges('run / one', 7);

    assert.equal(snapshot.id, 'snapshot-1');
    assert.equal(Object.isFrozen(provider), true);
    assert.equal(Object.isFrozen(publication), true);
    assert.equal(Object.isFrozen(publication.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(provider.resolve(), publication);
    assert.deepEqual(Object.keys(publication.client), ['getRunChanges']);
    assert.deepEqual(Object.keys(operationClient), ['getRunChanges']);
    assert.equal(calls.length, 1);

    const call = calls[0];
    const url = new URL(call.input);
    const headers = new Headers(call.init.headers);
    assert.equal(url.origin, 'http://127.0.0.1:44112');
    assert.equal(url.pathname, '/api/v1/agent/runs/run%20%2F%20one/changes');
    assert.equal(url.searchParams.get('expected_revision'), '7');
    assert.equal(call.init.method, 'GET');
    assert.equal(headers.get('Authorization'), 'Bearer operation-session');
    assert.equal(headers.get('X-Agistack-Launch'), 'operation-launch');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed run-changes publication keeps the last-good binding', () => {
  const provider = createDesktopSessionRunChangesClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_session_run_changes_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_session_run_changes_config_invalid/u,
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

function changeSnapshot() {
  return {
    id: 'snapshot-1',
    run_id: 'run / one',
    run_revision: 7,
    environment_id: 'environment-1',
    files: [],
    created_at: '2026-09-01T00:00:00Z',
  };
}

function json(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}
