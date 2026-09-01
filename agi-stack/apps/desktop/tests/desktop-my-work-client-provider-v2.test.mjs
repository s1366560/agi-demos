import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopMyWorkClientProviderV2,
  DesktopMyWorkClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/my-work/' +
    'desktopMyWorkClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop My Work client provider fails closed before publication', () => {
  const provider = createDesktopMyWorkClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopMyWorkClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_my_work_client_unpublished');
      assert.equal(error.message, 'desktop_my_work_client_unpublished');
      return true;
    },
  );
});

test('publications pin frozen one-method Local My Work clients to exact configs', async () => {
  const provider = createDesktopMyWorkClientProviderV2();
  const publicationConfig = runtimeConfig(
    'http://127.0.0.1:44311',
    'publication-session',
    'publication-launch',
  );
  const publication = provider.publish({ config: publicationConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:44312',
    'operation-session',
    'operation-launch',
  );
  operationConfig.projectId = 'project / operation';
  const operationClient = publication.bindOperation(operationConfig);
  publicationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.localApiToken = 'mutated-launch';

  const originalFetch = globalThis.fetch;
  const calls = [];
  const controller = new AbortController();
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return json({ project_id: 'project / operation', items: [] });
  };

  try {
    const response = await operationClient.listMyWork(
      'project / operation',
      controller.signal,
    );

    assert.deepEqual(response, { project_id: 'project / operation', items: [] });
    assert.equal(Object.isFrozen(provider), true);
    assert.equal(Object.isFrozen(publication), true);
    assert.equal(Object.isFrozen(publication.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(provider.resolve(), publication);
    assert.deepEqual(Object.keys(publication.client), ['listMyWork']);
    assert.deepEqual(Object.keys(operationClient), ['listMyWork']);
    assert.equal(calls.length, 1);

    const call = calls[0];
    const url = new URL(call.input);
    const headers = new Headers(call.init.headers);
    assert.equal(url.origin, 'http://127.0.0.1:44312');
    assert.equal(url.pathname, '/api/v1/projects/project%20%2F%20operation/my-work');
    assert.equal(call.init.method, 'GET');
    assert.equal(call.init.signal, controller.signal);
    assert.equal(headers.get('Authorization'), 'Bearer operation-session');
    assert.equal(headers.get('X-Agistack-Launch'), 'operation-launch');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed My Work publication keeps the last-good binding', () => {
  const provider = createDesktopMyWorkClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_my_work_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_my_work_config_invalid/u,
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

function json(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}
