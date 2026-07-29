import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  DesktopArtifactRequestError,
  createHttpDesktopArtifactClient,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/desktopArtifactClient.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

const SERVER_HASH = `sha256:${'a'.repeat(64)}`;
const DRAFT_HASH = `sha256:${'b'.repeat(64)}`;

function config() {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://api.memstack.test',
    apiKey: 'artifact-session',
    mode: 'cloud',
  };
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

test('loads a strict authenticated V2 text contract', async () => {
  const originalFetch = globalThis.fetch;
  let captured;
  globalThis.fetch = async (input, init) => {
    captured = { url: String(input), init };
    return json({
      contract_version: 2,
      artifact_id: 'artifact / one',
      revision: 7,
      content_hash: SERVER_HASH,
      mime_type: 'text/markdown',
      content: '# Authority',
    });
  };
  try {
    const value = await createHttpDesktopArtifactClient(config()).loadContent(
      'artifact / one',
    );
    assert.equal(value.revision, 7);
    assert.equal(
      captured.url,
      'https://api.memstack.test/api/v1/artifacts/artifact%20%2F%20one/content',
    );
    assert.equal(captured.init.headers.get('Authorization'), 'Bearer artifact-session');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('sends revision and idempotency authority and validates the receipt', async () => {
  const originalFetch = globalThis.fetch;
  let captured;
  globalThis.fetch = async (input, init) => {
    captured = { url: String(input), init };
    return json({
      artifact_id: 'artifact-1',
      revision: 8,
      content_hash: DRAFT_HASH,
      duplicate: false,
    });
  };
  try {
    const receipt = await createHttpDesktopArtifactClient(config()).saveContent(
      'artifact-1',
      {
        contract_version: 2,
        expected_revision: 7,
        content_hash: DRAFT_HASH,
        idempotency_key: 'artifact-save-7',
        content: '# Draft',
      },
    );
    assert.equal(receipt.revision, 8);
    assert.equal(captured.init.method, 'PUT');
    assert.equal(captured.init.headers.get('X-Expected-Revision'), '7');
    assert.equal(captured.init.headers.get('Idempotency-Key'), 'artifact-save-7');
    assert.deepEqual(JSON.parse(captured.init.body), {
      contract_version: 2,
      expected_revision: 7,
      content_hash: DRAFT_HASH,
      idempotency_key: 'artifact-save-7',
      content: '# Draft',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('preserves structured revision conflicts without interpreting message text', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    json(
      {
        reason_code: 'artifact_revision_conflict',
        server_revision: 9,
        server_content_hash: SERVER_HASH,
      },
      409,
    );
  try {
    await assert.rejects(
      createHttpDesktopArtifactClient(config()).saveContent('artifact-1', {
        contract_version: 2,
        expected_revision: 7,
        content_hash: DRAFT_HASH,
        idempotency_key: 'artifact-save-7',
        content: '# Draft',
      }),
      (error) => {
        assert.ok(error instanceof DesktopArtifactRequestError);
        assert.equal(error.httpStatus, 409);
        assert.equal(error.reasonCode, 'artifact_revision_conflict');
        assert.equal(error.serverRevision, 9);
        assert.equal(error.serverContentHash, SERVER_HASH);
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('downloads authenticated bytes without exposing a storage URL', async () => {
  const originalFetch = globalThis.fetch;
  let captured;
  globalThis.fetch = async (input, init) => {
    captured = { url: String(input), init };
    return new Response(new Uint8Array([1, 2, 3]), {
      status: 200,
      headers: { 'content-type': 'application/pdf' },
    });
  };
  try {
    const blob = await createHttpDesktopArtifactClient(config()).download('artifact-1');
    assert.equal(blob.type, 'application/pdf');
    assert.equal(blob.size, 3);
    assert.equal(
      captured.url,
      'https://api.memstack.test/api/v1/artifacts/artifact-1/content/bytes',
    );
    assert.equal(captured.init.headers.get('Authorization'), 'Bearer artifact-session');
    assert.equal(captured.init.redirect, 'follow');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('local mode uses the same authenticated Artifact Content V2 authority path', async () => {
  const originalFetch = globalThis.fetch;
  let captured;
  globalThis.fetch = async (input, init) => {
    captured = { url: String(input), init };
    return json({
      contract_version: 2,
      artifact_id: 'conversation-1:artifact-1',
      revision: 0,
      content_hash: SERVER_HASH,
      mime_type: 'text/markdown',
      content: '# Local authority',
    });
  };
  try {
    const authority = await createHttpDesktopArtifactClient({
      ...config(),
      mode: 'local',
    }).loadContent(
      'conversation-1:artifact-1',
    );
    assert.equal(authority.revision, 0);
    assert.equal(
      captured.url,
      'https://api.memstack.test/api/v1/artifacts/conversation-1%3Aartifact-1/content',
    );
    assert.equal(captured.init.headers.get('Authorization'), 'Bearer artifact-session');
  } finally {
    globalThis.fetch = originalFetch;
  }
});
