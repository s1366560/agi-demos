import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const root = process.env.CLOUD_MEMORY_TEST_DIST ?? '/tmp/agistack-desktop-test-dist';
const { executeVaultBoundCloudRequest } = require(`${root}/electron/main/cloudRequestPolicy.js`);
const { desktopApiFetch } = require(`${root}/src/api/cloudRequestBroker.js`);
const key = '00000000-0000-0000-0000-00000000000a';
const mutation = (revision) => ({
  kind: 'memory-command',
  expected_revision: revision,
  idempotency_key: key,
});
const detailPath = '/api/v1/memories/memory-1?project_id=project-1';
const create = {
  method: 'POST',
  path: '/api/v1/memories/',
  mutation: mutation(0),
  body: {
    project_id: 'project-1',
    title: 'Title',
    content: 'Content',
    tags: ['tag'],
    metadata: { source: 'test' },
  },
};
const patch = {
  method: 'PATCH',
  path: detailPath,
  mutation: mutation(3),
  body: { version: 3, title: 'Changed' },
};
const session = {
  version: 1,
  api_base_url: 'https://cloud.memstack.test',
  runtime_mode: 'cloud',
  credential_kind: 'cloud_bearer',
  credential: 'vault-only-fixture',
  expires_at: '2099-08-10T00:00:00Z',
};
function dependencies(projectId = 'project-1', status = 200) {
  const requests = [];
  return {
    requests,
    loadTrustedSession: async () => session,
    async fetch(url, init) {
      const path = new URL(url).pathname;
      requests.push({ url, init });
      return new Response(
        path === '/api/v1/workspace-context'
          ? JSON.stringify({
              context: {
                tenant_id: 'tenant-1',
                project_id: projectId,
                revision: 7,
              },
            })
          : status === 204
            ? null
            : JSON.stringify({
                id: 'memory-1',
                project_id: 'project-1',
                version: 4,
              }),
        {
          status: path === '/api/v1/workspace-context' ? 200 : status,
          headers: { 'Content-Type': 'application/json' },
        },
      );
    },
  };
}
for (const input of [
  create,
  patch,
  { method: 'DELETE', path: detailPath, mutation: mutation(3) },
]) {
  test(`Cloud memory ${input.method} preserves command identity and dedicated revision header`, async () => {
    const deps = dependencies('project-1', input.method === 'DELETE' ? 204 : 200);
    await executeVaultBoundCloudRequest(input, deps);
    assert.equal(deps.requests.length, 2);
    const sent = deps.requests[1];
    const headers = new Headers(sent.init.headers);
    assert.equal(
      headers.get('X-Memory-Expected-Revision'),
      String(input.mutation.expected_revision),
    );
    assert.equal(headers.get('X-Expected-Revision'), null);
    assert.equal(headers.get('Idempotency-Key'), key);
    assert.equal(headers.get('Authorization'), 'Bearer vault-only-fixture');
    assert.equal(new URL(sent.url).pathname + new URL(sent.url).search, input.path);
    assert.equal(sent.init.body, input.body === undefined ? undefined : JSON.stringify(input.body));
  });
}
test('Cloud memory detail requires explicit current project', async () => {
  const deps = dependencies();
  await executeVaultBoundCloudRequest({ method: 'GET', path: detailPath }, deps);
  assert.equal(deps.requests.length, 2);
});
for (const input of [
  create,
  patch,
  { method: 'DELETE', path: detailPath, mutation: mutation(3) },
]) {
  test(`Cloud memory ${input.method} rejects stale project before any write`, async () => {
    const deps = dependencies('project-2');
    await assert.rejects(executeVaultBoundCloudRequest(input, deps), /project scope mismatch/);
    assert.equal(deps.requests.length, 1);
  });
}
for (const [name, input] of [
  ['generic revision', { ...patch, mutation: { expected_revision: 3, idempotency_key: key } }],
  ['idempotency only', { ...create, mutation: { kind: 'idempotency-only', idempotency_key: key } }],
  ['missing revision', { ...patch, mutation: undefined }],
  ['revision mismatch', { ...patch, body: { version: 2, title: 'Changed' } }],
  [
    'zero update revision',
    { ...patch, mutation: mutation(0), body: { version: 0, title: 'Changed' } },
  ],
  ['nonzero create revision', { ...create, mutation: mutation(1) }],
  ['overflow revision', { ...patch, mutation: mutation(2147483647) }],
  [
    'noncanonical key',
    {
      ...patch,
      mutation: { ...mutation(3), idempotency_key: key.toUpperCase() },
    },
  ],
  ['missing project', { ...patch, path: '/api/v1/memories/memory-1' }],
  ['duplicate project', { ...patch, path: detailPath + '&project_id=project-2' }],
  ['unscoped read', { method: 'GET', path: '/api/v1/memories/memory-1' }],
  ['unsupported sharing', { ...create, body: { ...create.body, is_public: true } }],
  ['unsupported authority field', { ...patch, body: { ...patch.body, project_id: 'project-2' } }],
  ['delete body', { method: 'DELETE', path: detailPath, mutation: mutation(3), body: {} }],
  [
    'foreign endpoint',
    {
      method: 'POST',
      path: '/api/v1/tasks/retry-pending?limit=10',
      mutation: mutation(3),
    },
  ],
]) {
  test(`Cloud memory rejects ${name} before network access`, async () => {
    const deps = dependencies();
    await assert.rejects(executeVaultBoundCloudRequest(input, deps));
    assert.deepEqual(deps.requests, []);
  });
}
test('Renderer to main forwards the exact memory revision without exposing the vault credential', async () => {
  const deps = dependencies();
  const previous = globalThis.window;
  const inputs = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        invoke: async (method, input) => {
          assert.equal(method, 'cloud_request');
          inputs.push(input.request);
          return executeVaultBoundCloudRequest(input.request, deps);
        },
      },
    },
  };
  try {
    await desktopApiFetch(
      { mode: 'cloud', apiKey: '', apiBaseUrl: session.api_base_url },
      detailPath,
      {
        method: 'PATCH',
        body: JSON.stringify(patch.body),
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': key,
          'X-Memory-Expected-Revision': '3',
        },
      },
    );
    assert.deepEqual(inputs[0].mutation, mutation(3));
    assert.equal(JSON.stringify(inputs).includes(session.credential), false);
    const before = inputs.length;
    for (const headers of [
      { 'Idempotency-Key': key, 'X-Memory-Expected-Revision': '03' },
      {
        'Idempotency-Key': key,
        'X-Memory-Expected-Revision': '3',
        'X-Expected-Revision': '3',
      },
      { 'X-Memory-Expected-Revision': '3' },
    ])
      await assert.rejects(
        desktopApiFetch(
          { mode: 'cloud', apiKey: '', apiBaseUrl: session.api_base_url },
          detailPath,
          { method: 'PATCH', body: JSON.stringify(patch.body), headers },
        ),
      );
    assert.equal(inputs.length, before);
  } finally {
    globalThis.window = previous;
  }
});
