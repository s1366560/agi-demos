import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopSessionProjectionClientProviderV2,
  DesktopSessionProjectionClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/' +
    'desktopSessionProjectionClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop session projection client provider fails closed before publication', () => {
  const provider = createDesktopSessionProjectionClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopSessionProjectionClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_session_projection_client_unpublished');
      assert.equal(error.message, 'desktop_session_projection_client_unpublished');
      return true;
    },
  );
});

test('publications and operation bindings pin frozen one-method projection clients', async () => {
  const provider = createDesktopSessionProjectionClientProviderV2();
  const publicationConfig = runtimeConfig(
    'http://127.0.0.1:43701',
    'publication-session',
    'publication-launch',
  );
  const publication = provider.publish({ config: publicationConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:43702',
    'operation-session',
    'operation-launch',
  );
  const operationClient = publication.bindOperation(operationConfig);
  publicationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.apiKey = 'mutated-session';
  operationConfig.localApiToken = 'mutated-launch';

  const originalFetch = globalThis.fetch;
  const calls = [];
  const controller = new AbortController();
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return json({ schema_version: 1, snapshot_revision: 'sha256:test' });
  };

  try {
    const payload = await operationClient.getConversationSession(
      'conversation / operation',
      {
        tenantId: 'tenant / operation',
        projectId: 'project / operation',
        workspaceId: 'workspace / operation',
      },
      controller.signal,
    );

    assert.deepEqual(payload, {
      schema_version: 1,
      snapshot_revision: 'sha256:test',
    });
    assert.equal(Object.isFrozen(provider), true);
    assert.equal(Object.isFrozen(publication), true);
    assert.equal(Object.isFrozen(publication.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(provider.resolve(), publication);
    assert.deepEqual(Object.keys(publication.client), ['getConversationSession']);
    assert.deepEqual(Object.keys(operationClient), ['getConversationSession']);
    assert.equal(calls.length, 1);

    const call = calls[0];
    const url = new URL(call.input);
    const headers = new Headers(call.init.headers);
    assert.equal(url.origin, 'http://127.0.0.1:43702');
    assert.equal(
      url.pathname,
      '/api/v1/agent/conversations/conversation%20%2F%20operation/session',
    );
    assert.equal(url.searchParams.get('tenant_id'), 'tenant / operation');
    assert.equal(url.searchParams.get('project_id'), 'project / operation');
    assert.equal(url.searchParams.get('workspace_id'), 'workspace / operation');
    assert.equal(call.init.signal, controller.signal);
    assert.equal(headers.get('Authorization'), 'Bearer operation-session');
    assert.equal(headers.get('X-Agistack-Launch'), 'operation-launch');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed session projection publication keeps the last-good binding', () => {
  const provider = createDesktopSessionProjectionClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_session_projection_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_session_projection_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function runtimeConfig(apiBaseUrl, apiKey, localApiToken) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl,
    apiKey,
    localApiToken,
    tenantId: 'tenant-1',
    projectId: 'project-1',
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
