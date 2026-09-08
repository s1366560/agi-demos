import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const root = process.env.CLOUD_MEMORY_AUTHORITY_DIST ?? '/tmp/agistack-desktop-test-dist';
const { createDesktopCloudMemoryHttpV2 } = require(
  `${root}/src/plugins/desktopCloudMemoryHttpV2.js`,
);
const scope = { authority: 'cloud', tenantId: 'tenant', projectId: 'project' };
const config = {
  apiBaseUrl: 'https://cloud.invalid',
  deviceAuthorizationBaseUrl: '',
  apiKey: '',
  localApiToken: '',
  tenantId: 'tenant',
  projectId: 'project',
  workspaceId: '',
  mode: 'cloud',
  workspaceRoot: '',
};
const options = { expectedActorId: 'actor', expectedContextRevision: 7 };
const key = '00000000-0000-0000-0000-00000000000a';
const row = {
  id: 'memory',
  project_id: 'project',
  title: 'Title',
  content: 'Body',
  content_type: 'text',
  version: 1,
  status: 'enabled',
  processing_status: 'pending',
  created_at: '2026-09-08',
  updated_at: null,
};
async function fixture(response, run) {
  const previous = globalThis.window;
  const requests = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        invoke: async (name, input) => {
          assert.equal(name, 'cloud_request');
          requests.push(input.request);
          return typeof response === 'function' ? response(input.request) : response;
        },
      },
    },
  };
  try {
    await run(createDesktopCloudMemoryHttpV2(config), requests);
  } finally {
    if (previous === undefined) delete globalThis.window;
    else globalThis.window = previous;
  }
}
test('create pins identity and revision zero without renderer credentials', async () =>
  fixture({ status: 201, body: row }, async (client, requests) => {
    const result = await client.execute(
      scope,
      { operation: 'create', idempotencyKey: key, memory: { title: 'Title', content: 'Body' } },
      options,
    );
    assert.equal(result.result.version, 1);
    assert.deepEqual(requests[0].memory_scope, {
      actor_id: 'actor',
      tenant_id: 'tenant',
      project_id: 'project',
      context_revision: 7,
    });
    assert.deepEqual(requests[0].mutation, {
      kind: 'memory-command',
      expected_revision: 0,
      idempotency_key: key,
    });
    assert.deepEqual(requests[0].body, { project_id: 'project', title: 'Title', content: 'Body' });
  }));
test('update and detail preserve exact project and row revisions', async () =>
  fixture(
    (req) => ({ status: 200, body: { ...row, version: req.method === 'PATCH' ? 3 : 2 } }),
    async (client, requests) => {
      await client.execute(scope, { operation: 'get', id: 'memory' }, options);
      await client.execute(
        scope,
        {
          operation: 'update',
          id: 'memory',
          expectedRevision: 2,
          idempotencyKey: key,
          patch: { title: 'Next' },
        },
        options,
      );
      assert.equal(requests[0].path, '/api/v1/memories/memory?project_id=project');
      assert.deepEqual(requests[1].body, { version: 2, title: 'Next' });
    },
  ));
for (const command of [
  { operation: 'create', idempotencyKey: 'bad', memory: { title: 'a', content: 'b' } },
  {
    operation: 'update',
    id: 'memory',
    expectedRevision: 0,
    idempotencyKey: key,
    patch: { title: 'a' },
  },
  { operation: 'update', id: 'memory', expectedRevision: 1, idempotencyKey: key, patch: {} },
  {
    operation: 'update',
    id: 'memory',
    expectedRevision: 1,
    idempotencyKey: key,
    patch: { contentType: 'text' },
  },
  { operation: 'get', id: '../memory' },
  { operation: 'get', id: 'memory', extra: true },
  {
    operation: 'create',
    idempotencyKey: key,
    memory: { title: 'a', content: 'b', metadata: { nested: undefined } },
  },
])
  test(`invalid command rejected before IPC ${JSON.stringify(command)}`, async () =>
    fixture({ status: 200, body: row }, async (client, requests) => {
      await assert.rejects(client.execute(scope, command, options));
      assert.equal(requests.length, 0);
    }));
for (const status of [401, 403, 404, 409])
  test(`preserve backend ${status}`, async () =>
    fixture({ status, body: { detail: { code: 'backend_code' } } }, async (client) => {
      await assert.rejects(
        client.execute(
          scope,
          { operation: 'delete', id: 'memory', expectedRevision: 1, idempotencyKey: key },
          options,
        ),
        (error) => error.status === status && error.message === 'backend_code',
      );
    }));
for (const response of [
  { status: 200, body: null },
  { status: 204, body: { deleted: true } },
])
  test(`delete rejects ambiguous success ${response.status}`, async () =>
    fixture(response, async (client) => {
      await assert.rejects(
        client.execute(
          scope,
          { operation: 'delete', id: 'memory', expectedRevision: 1, idempotencyKey: key },
          options,
        ),
      );
    }));
test('delete requires exact no-content receipt', async () =>
  fixture({ status: 204, body: null }, async (client) => {
    assert.deepEqual(
      await client.execute(
        scope,
        { operation: 'delete', id: 'memory', expectedRevision: 1, idempotencyKey: key },
        options,
      ),
      { operation: 'delete', result: { memoryId: 'memory', deleted: true } },
    );
  }));
for (const body of [
  { ...row, id: 'other' },
  { ...row, project_id: 'other' },
  { ...row, version: 7 },
])
  test(`update rejects wrong receipt ${JSON.stringify(body)}`, async () =>
    fixture({ status: 200, body }, async (client) => {
      await assert.rejects(
        client.execute(
          scope,
          {
            operation: 'update',
            id: 'memory',
            expectedRevision: 1,
            idempotencyKey: key,
            patch: { title: 'Next' },
          },
          options,
        ),
      );
    }));
test('abort after IPC rejects late successful receipt', async () =>
  fixture({ status: 201, body: row }, async (client) => {
    const abort = new AbortController();
    const pending = client.execute(
      scope,
      { operation: 'create', idempotencyKey: key, memory: { title: 'Title', content: 'Body' } },
      { ...options, signal: abort.signal },
    );
    abort.abort();
    await assert.rejects(pending, (error) => error.name === 'AbortError');
  }));
test('missing vault broker fails closed even with apiKey configured', async () => {
  const previous = globalThis.window;
  delete globalThis.window;
  try {
    await assert.rejects(
      createDesktopCloudMemoryHttpV2({ ...config, apiKey: 'fixture' }).execute(
        scope,
        { operation: 'get', id: 'memory' },
        options,
      ),
    );
  } finally {
    if (previous !== undefined) globalThis.window = previous;
  }
});
