import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopSessionArtifactActionClientProviderV2,
  DesktopSessionArtifactActionClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/' +
    'desktopSessionArtifactActionClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop session artifact action client provider fails closed before publication', () => {
  const provider = createDesktopSessionArtifactActionClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopSessionArtifactActionClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_session_artifact_action_client_unpublished');
      assert.equal(error.message, 'desktop_session_artifact_action_client_unpublished');
      return true;
    },
  );
});

test('publications pin frozen artifact action clients to their exact configs', async () => {
  const provider = createDesktopSessionArtifactActionClientProviderV2();
  const firstConfig = runtimeConfig('http://127.0.0.1:43711', 'tenant-1', 'project-1');
  const first = provider.publish({ config: firstConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:43713',
    'tenant / operation',
    'project / operation',
  );
  const operationClient = first.bindOperation(operationConfig);
  firstConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  const second = provider.publish({
    config: runtimeConfig('http://127.0.0.1:43712', 'tenant-2', 'project-2'),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return json({
      accepted: true,
      status: 'accepted',
      artifact_version: {
        id: 'artifact/version-2',
        artifact_id: 'artifact-1',
        conversation_id: 'conversation-1',
        version: 2,
        status: 'approved',
        revision: 4,
      },
      delivery: {
        id: 'delivery-1',
        artifact_version_id: 'artifact/version-2',
        artifact_id: 'artifact-1',
        conversation_id: 'conversation-1',
        destination: 'local_workspace',
        receipt: {},
        idempotency_key: 'artifact/version-2:4:deliver',
        created_at: '2026-09-01T00:00:00Z',
      },
    });
  };

  try {
    await operationClient.reviewArtifactVersion('artifact / review', {
      action: 'request_changes',
      expectedRevision: 3,
      runExpectedRevision: 8,
      feedback: 'Include the missing provenance.',
    });
    await first.client.deliverArtifactVersion('artifact / delivery', {
      expectedRevision: 4,
      idempotencyKey: 'artifact / delivery:4:deliver',
      destination: 'local_workspace',
    });

    assert.equal(Object.isFrozen(provider), true);
    assert.equal(Object.isFrozen(first), true);
    assert.equal(Object.isFrozen(first.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(Object.isFrozen(second), true);
    assert.notEqual(first, second);
    assert.notEqual(first.client, second.client);
    assert.equal(provider.resolve(), second);
    assert.deepEqual(Object.keys(first.client), [
      'reviewArtifactVersion',
      'deliverArtifactVersion',
    ]);
    assert.deepEqual(Object.keys(operationClient), [
      'reviewArtifactVersion',
      'deliverArtifactVersion',
    ]);
    assert.equal(calls.length, 2);
    assertArtifactActionCall(calls[0], {
      apiBaseUrl: 'http://127.0.0.1:43713',
      artifactVersionId: 'artifact / review',
      action: 'review',
      payload: {
        action: 'request_changes',
        expected_revision: 3,
        run_expected_revision: 8,
        feedback: 'Include the missing provenance.',
      },
    });
    assertArtifactActionCall(calls[1], {
      apiBaseUrl: 'http://127.0.0.1:43711',
      artifactVersionId: 'artifact / delivery',
      action: 'deliver',
      payload: {
        expected_revision: 4,
        idempotency_key: 'artifact / delivery:4:deliver',
        destination: 'local_workspace',
      },
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed artifact action publication keeps the last-good binding', () => {
  const provider = createDesktopSessionArtifactActionClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_artifact_action_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_artifact_action_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function assertArtifactActionCall(
  call,
  { apiBaseUrl, artifactVersionId, action, payload },
) {
  const url = new URL(call.input);
  assert.equal(url.origin, apiBaseUrl);
  assert.equal(
    url.pathname,
    `/api/v1/agent/artifact-versions/${encodeURIComponent(artifactVersionId)}/${action}`,
  );
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
