import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const {
  requestProjectKnowledgeJson,
  requestProjectKnowledgeNoContent,
} = require('/tmp/agistack-project-knowledge-test-dist/src/features/project-knowledge/projectKnowledgeClient.js');
const { DesktopApiError } = require('/tmp/agistack-project-knowledge-test-dist/src/api/client.js');
const config = Object.freeze({
  apiBaseUrl: 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: 'https://cloud.test',
  apiKey: 'trusted-identity',
  localApiToken: 'private-launch',
  tenantId: 'tenant',
  projectId: 'project',
  workspaceId: '',
  workspaceRoot: '',
  mode: 'local',
});
const path = '/api/v1/knowledge/sync-resolve-push';
const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
async function capture(run, response = () => json({ accepted: true })) {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init, headers: new Headers(init.headers) });
    return response();
  };
  try {
    await run(requests);
  } finally {
    globalThis.fetch = original;
  }
}

test('local knowledge carries separate launch and identity; cloud never carries launch', async () => {
  await capture(async (requests) => {
    await requestProjectKnowledgeJson(config, '/api/v1/knowledge/context');
    await requestProjectKnowledgeJson(
      { ...config, mode: 'cloud', apiBaseUrl: 'https://cloud.test' },
      '/api/v1/memories/',
    );
    assert.equal(requests[0].headers.get('X-Agistack-Launch'), 'private-launch');
    assert.equal(requests[0].headers.get('Authorization'), 'Bearer trusted-identity');
    assert.equal(requests[0].headers.get('Idempotency-Key'), null);
    assert.equal(requests[0].headers.get('X-Expected-Revision'), null);
    assert.equal(requests[1].headers.get('X-Agistack-Launch'), null);
    assert.equal(requests[1].headers.get('Authorization'), 'Bearer trusted-identity');
  });
});

test('mutation authority accepts only idempotency and optional revision headers', async () => {
  await capture(async (requests) => {
    const body = {
      scope: { tenant_id: 'tenant' },
      resolution: { decision: 'keep_current' },
    };
    await requestProjectKnowledgeJson(config, path, {
      method: 'POST',
      body,
      mutation: { idempotencyKey: 'stable-key' },
    });
    await requestProjectKnowledgeJson(config, '/api/v1/knowledge/mutations', {
      method: 'POST',
      body,
      mutation: { idempotencyKey: 'stable-cas', expectedRevision: 7 },
      headers: { Authorization: 'forged', 'X-Agistack-Launch': 'forged' },
    });
    assert.equal(requests[0].headers.get('Idempotency-Key'), 'stable-key');
    assert.equal(requests[0].headers.get('X-Expected-Revision'), null);
    assert.equal(requests[1].headers.get('X-Expected-Revision'), '7');
    assert.equal(requests[1].headers.get('Authorization'), 'Bearer trusted-identity');
    assert.equal(requests[1].headers.get('X-Agistack-Launch'), 'private-launch');
    assert.deepEqual(JSON.parse(requests[0].init.body), body);
  });
});

test('invalid mutation header authority fails before transport', async () => {
  await capture(async (requests) => {
    for (const mutation of [
      null,
      {},
      { idempotencyKey: '' },
      { idempotencyKey: ' key' },
      { idempotencyKey: 'x'.repeat(513) },
      { idempotencyKey: 'line\nbreak' },
      { idempotencyKey: '非ASCII' },
      { idempotencyKey: 'k', authorization: 'forged' },
      ...[-1, 0.5, NaN, Infinity, 4_294_967_296].map((expectedRevision) => ({
        idempotencyKey: 'k',
        expectedRevision,
      })),
    ]) {
      await assert.rejects(
        requestProjectKnowledgeJson(config, path, {
          method: 'POST',
          body: {},
          mutation,
        }),
        (error) => error instanceof DesktopApiError && error.status === 422,
      );
    }
    await assert.rejects(
      requestProjectKnowledgeJson(config, path, {
        method: 'GET',
        mutation: { idempotencyKey: 'must-not-send-on-read' },
      }),
      (error) => error instanceof DesktopApiError && error.status === 422,
    );
    assert.equal(requests.length, 0);
  });
});

test('native structured errors preserve recovery identity and original evidence', async () => {
  const payload = {
    error: {
      code: 'knowledge_sync_resolution_stale',
      target: 'desktop-sidecar',
      resolution_id: '00000000-0000-4000-8000-000000000001',
      message: 'refresh',
    },
  };
  await capture(
    async () => {
      await assert.rejects(
        requestProjectKnowledgeJson(config, path, { method: 'POST', body: {} }),
        (error) => {
          assert(error instanceof DesktopApiError);
          assert.equal(error.status, 409);
          assert.equal(error.message, 'knowledge_sync_resolution_stale');
          assert.deepEqual(error.payload, payload);
          return true;
        },
      );
    },
    () => json(payload, 409),
  );
  for (const [payload, code] of [
    [{ detail: { code: 'cloud_forbidden' } }, 'cloud_forbidden'],
    [{ reason_code: 'scope_changed' }, 'scope_changed'],
    [{ error: { code: ' invalid ' } }, 'HTTP 403'],
  ]) {
    await capture(
      async () => {
        await assert.rejects(
          requestProjectKnowledgeJson(config, path),
          (error) => error.message === code,
        );
      },
      () => json(payload, 403),
    );
  }
});

test('no-content knowledge requests use the same launch and revision contract', async () => {
  await capture(
    async (requests) => {
      await requestProjectKnowledgeNoContent(config, '/api/v1/knowledge/mutations', {
        method: 'POST',
        body: {},
        mutation: {
          idempotencyKey: 'delete-key',
          expectedRevision: 4_294_967_295,
        },
      });
      assert.equal(requests[0].headers.get('X-Agistack-Launch'), 'private-launch');
      assert.equal(requests[0].headers.get('Idempotency-Key'), 'delete-key');
      assert.equal(requests[0].headers.get('X-Expected-Revision'), '4294967295');
    },
    () => new Response(null, { status: 204 }),
  );
});
