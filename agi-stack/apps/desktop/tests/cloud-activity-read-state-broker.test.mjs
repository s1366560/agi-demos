import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const {
  executeVaultBoundCloudRequest,
} = require('/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js');
const endpoint = '/api/v1/projects/project-one/activity/read-state';
const receipt = { entry_id: 'entry-one', entry_revision: 2, read_at: '2026-09-05T00:00:00.000Z' };
const body = { expected_authority_revision: 3, entries: [receipt] };
function fixture({ projectId = 'project-one', status = 200 } = {}) {
  const calls = [];
  const dependencies = {
    async loadTrustedSession() {
      return {
        version: 1,
        api_base_url: 'https://cloud.example',
        runtime_mode: 'cloud',
        credential_kind: 'cloud_bearer',
        credential: 'synthetic-test-token',
        expires_at: '2099-01-01T00:00:00Z',
      };
    },
    async fetch(url, init) {
      const pathname = new URL(url).pathname;
      calls.push({ pathname, method: init.method, body: init.body });
      const context = pathname === '/api/v1/workspace-context';
      return new Response(
        JSON.stringify(
          context
            ? {
                context: {
                  tenant_id: 'tenant-one',
                  project_id: projectId,
                  workspace_id: 'workspace-one',
                  revision: 1,
                },
              }
            : { project_id: 'project-one', authority_revision: 4, entries: [receipt] },
        ),
        { status: context ? 200 : status, headers: { 'content-type': 'application/json' } },
      );
    },
  };
  return {
    calls,
    request: (method, payload, path = endpoint, extra = {}) =>
      executeVaultBoundCloudRequest(
        {
          path,
          method,
          ...(payload === undefined ? {} : { body: payload }),
          ...extra,
        },
        dependencies,
      ),
  };
}
for (const method of ['GET', 'PUT']) {
  test(`native Activity ${method} reaches exact endpoint after observed project authorization`, async () => {
    const f = fixture();
    const result = await f.request(method, method === 'PUT' ? body : undefined);
    assert.equal(result.status, 200);
    assert.equal(result.body.project_id, 'project-one');
    assert.deepEqual(
      f.calls.map((call) => call.pathname),
      ['/api/v1/workspace-context', endpoint],
    );
    assert.equal(f.calls[1].method, method);
    if (method === 'PUT') assert.deepEqual(JSON.parse(f.calls[1].body), body);
  });
}
for (const [label, invalid] of [
  ['missing revision', { entries: [receipt] }],
  ['negative revision', { ...body, expected_authority_revision: -1 }],
  ['string revision', { ...body, expected_authority_revision: '3' }],
  ['extra body field', { ...body, principal_id: 'another-user' }],
  ['duplicate ids', { ...body, entries: [receipt, receipt] }],
  [
    'over 500 entries',
    {
      ...body,
      entries: Array.from({ length: 501 }, (_, index) => ({
        ...receipt,
        entry_id: `entry-${index}`,
      })),
    },
  ],
  ['oversize id', { ...body, entries: [{ ...receipt, entry_id: 'x'.repeat(256) }] }],
  ['negative entry revision', { ...body, entries: [{ ...receipt, entry_revision: -1 }] }],
  ['invalid timestamp', { ...body, entries: [{ ...receipt, read_at: 'invalid' }] }],
  ['extra receipt field', { ...body, entries: [{ ...receipt, user_id: 'another-user' }] }],
]) {
  test(`native Activity rejects ${label} before network`, async () => {
    const f = fixture();
    await assert.rejects(f.request('PUT', invalid));
    assert.equal(f.calls.length, 0);
  });
}
test('native Activity keeps exact route method and query restrictions', async () => {
  for (const [method, payload, path] of [
    ['POST', body, endpoint],
    ['DELETE', undefined, endpoint],
    ['GET', body, endpoint],
    ['GET', undefined, `${endpoint}?principal_id=another-user`],
    ['PUT', body, `${endpoint}/extra`],
    ['GET', undefined, endpoint.replace('read-state', 'admin')],
  ]) {
    const f = fixture();
    await assert.rejects(f.request(method, payload, path));
    assert.equal(f.calls.length, 0);
  }
});
test('native Activity project mismatch stops before activity read or write', async () => {
  for (const method of ['GET', 'PUT']) {
    const f = fixture({ projectId: 'another-project' });
    await assert.rejects(f.request(method, method === 'PUT' ? body : undefined));
    assert.deepEqual(
      f.calls.map((call) => call.pathname),
      ['/api/v1/workspace-context'],
    );
  }
});
test('native Activity preserves revision conflict response', async () => {
  const f = fixture({ status: 409 });
  const result = await f.request('PUT', body);
  assert.equal(result.status, 409);
});

test('only authorized Activity PUT transport failure gets a safe offline marker', async () => {
  const calls = [];
  const dependencies = {
    loadTrustedSession: async () => ({
      version: 1,
      api_base_url: 'https://cloud.example',
      runtime_mode: 'cloud',
      credential_kind: 'cloud_bearer',
      credential: 'synthetic-test-token',
      expires_at: null,
    }),
    fetch: async (url) => {
      const path = new URL(url).pathname;
      calls.push(path);
      if (path === '/api/v1/workspace-context')
        return new Response(
          JSON.stringify({
            context: {
              tenant_id: 'tenant-one',
              project_id: 'project-one',
              workspace_id: 'workspace-one',
              revision: 1,
            },
          }),
          { headers: { 'content-type': 'application/json' } },
        );
      throw new Error('synthetic transport detail must not escape');
    },
  };
  const result = await executeVaultBoundCloudRequest(
    { path: endpoint, method: 'PUT', body },
    dependencies,
  );
  assert.deepEqual(result, {
    status: 503,
    body: { reason_code: 'activity_read_state_transport_unavailable' },
  });
  assert.deepEqual(calls, ['/api/v1/workspace-context', endpoint]);
  await assert.rejects(
    executeVaultBoundCloudRequest({ path: endpoint, method: 'GET' }, dependencies),
  );
  await assert.rejects(
    executeVaultBoundCloudRequest(
      { path: endpoint, method: 'PUT', body },
      {
        ...dependencies,
        fetch: async () => {
          throw new Error('scope observation failed');
        },
      },
    ),
  );
});
test('Activity PUT cancellation is never represented as an offline receipt', async () => {
  const controller = new AbortController();
  await assert.rejects(
    executeVaultBoundCloudRequest(
      { path: endpoint, method: 'PUT', body },
      {
        signal: controller.signal,
        loadTrustedSession: async () => ({
          version: 1,
          api_base_url: 'https://cloud.example',
          runtime_mode: 'cloud',
          credential_kind: 'cloud_bearer',
          credential: 'synthetic-test-token',
          expires_at: null,
        }),
        fetch: async (url) => {
          if (new URL(url).pathname === '/api/v1/workspace-context')
            return new Response(
              JSON.stringify({
                context: {
                  tenant_id: 'tenant-one',
                  project_id: 'project-one',
                  workspace_id: 'workspace-one',
                  revision: 1,
                },
              }),
              { headers: { 'content-type': 'application/json' } },
            );
          controller.abort();
          throw new Error('network cancellation');
        },
      },
    ),
    { name: 'AbortError' },
  );
});
