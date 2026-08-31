import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopArtifactClientProviderV2,
  DesktopArtifactClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/' +
    'desktopArtifactClientProviderV2.js',
);

const CONTENT_HASH = `sha256:${'a'.repeat(64)}`;

test('desktop artifact client provider fails closed before publication', () => {
  const provider = createDesktopArtifactClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopArtifactClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_artifact_client_unpublished');
      assert.equal(error.message, 'desktop_artifact_client_unpublished');
      return true;
    },
  );
});

test('each publication returns one frozen generation-pinned artifact client binding', async () => {
  const provider = createDesktopArtifactClientProviderV2();
  const cloudConfig = runtimeConfig('https://cloud-artifacts.example.test', 'cloud');
  const cloud = provider.publish({ config: cloudConfig });
  cloudConfig.apiBaseUrl = 'https://mutated.example.test';
  const local = provider.publish({
    config: runtimeConfig('http://127.0.0.1:43123', 'local'),
  });
  const originalFetch = globalThis.fetch;
  const urls = [];
  globalThis.fetch = async (input) => {
    const url = String(input);
    urls.push(url);
    const artifactId = url.includes('cloud-artifact') ? 'cloud-artifact' : 'local-artifact';
    return json({
      contract_version: 2,
      artifact_id: artifactId,
      revision: 1,
      content_hash: CONTENT_HASH,
      mime_type: 'text/plain',
      content: artifactId,
    });
  };
  try {
    assert.equal(Object.isFrozen(cloud), true);
    assert.equal(Object.isFrozen(local), true);
    assert.notEqual(cloud, local);
    assert.equal(provider.resolve(), local);
    assert.equal((await cloud.client.loadContent('cloud-artifact')).content, 'cloud-artifact');
    assert.equal((await local.client.loadContent('local-artifact')).content, 'local-artifact');
    assert.deepEqual(urls, [
      'https://cloud-artifacts.example.test/api/v1/artifacts/cloud-artifact/content',
      'http://127.0.0.1:43123/api/v1/artifacts/local-artifact/content',
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed artifact client publication keeps the last-good binding', () => {
  const provider = createDesktopArtifactClientProviderV2();
  const lastGood = provider.publish({
    config: runtimeConfig('https://cloud-artifacts.example.test', 'cloud'),
  });
  const poisonedConfig = {
    ...runtimeConfig('https://unused.example.test', 'cloud'),
    get apiBaseUrl() {
      throw new Error('candidate_artifact_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_artifact_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function runtimeConfig(apiBaseUrl, mode) {
  return {
    apiBaseUrl,
    deviceAuthorizationBaseUrl: 'https://auth.example.test',
    apiKey: '',
    localApiToken: '',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    mode,
    workspaceRoot: '/workspace',
  };
}

function json(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}
