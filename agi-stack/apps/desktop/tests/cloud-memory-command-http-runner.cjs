const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { executeVaultBoundCloudRequest } = require(
  `${process.argv[2]}/electron/main/cloudRequestPolicy.js`,
);
const { desktopApiFetch, desktopVaultBoundCloudRequestBroker } = require(
  `${process.argv[2]}/src/api/cloudRequestBroker.js`,
);
const baseUrl = process.argv[3];
const enabled = process.argv[4] === 'enabled';
const scoped = process.argv[5] === 'scoped';
const session = {
  version: 1,
  api_base_url: baseUrl,
  runtime_mode: 'cloud',
  credential_kind: 'cloud_bearer',
  credential: 'isolated-http-fixture',
  expires_at: '2099-08-10T00:00:00Z',
};
const dependencies = {
  loadTrustedSession: async () => session,
  fetch: globalThis.fetch,
};
globalThis.window = {
  __MEMSTACK_DESKTOP__: {
    core: {
      invoke: async (method, input) => {
        assert.equal(method, 'cloud_request');
        return executeVaultBoundCloudRequest(input.request, dependencies);
      },
    },
  },
};
const config = { mode: 'cloud', apiKey: '', apiBaseUrl: baseUrl };
async function request(method, path, revision, key, body) {
  if (scoped) {
    const result = await desktopVaultBoundCloudRequestBroker().requestResponse({
      method,
      path,
      memory_scope: {
        actor_id: 'actor',
        tenant_id: 'tenant',
        project_id: 'project',
        context_revision: 1,
      },
      ...(body === undefined ? {} : { body }),
      ...(revision === undefined
        ? {}
        : {
            mutation: {
              kind: 'memory-command',
              expected_revision: revision,
              idempotency_key: key,
            },
          }),
    });
    return new Response(result.status === 204 ? null : JSON.stringify(result.body), {
      status: result.status,
      headers: { 'content-type': 'application/json' },
    });
  }
  return desktopApiFetch(config, path, {
    method,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    headers:
      revision === undefined
        ? {}
        : {
            'Content-Type': 'application/json',
            'X-Memory-Expected-Revision': String(revision),
            'Idempotency-Key': key,
          },
  });
}
async function run() {
  if (scoped) {
    await assert.rejects(
      desktopVaultBoundCloudRequestBroker().requestResponse({
        path: '/api/v1/memories/missing?project_id=project',
        memory_scope: {
          actor_id: 'other',
          tenant_id: 'tenant',
          project_id: 'project',
          context_revision: 1,
        },
      }),
      /cloud_memory_scope_conflict/,
    );
  }
  const createKey = randomUUID();
  const body = {
    project_id: 'project',
    title: 'Real bridge',
    content: 'Preserved content',
    tags: ['bridge'],
    metadata: { origin: 'node-python-postgres' },
  };
  const created = await request('POST', '/api/v1/memories/', 0, createKey, body);
  if (!enabled) {
    assert.equal(created.status, 503);
    assert.equal((await created.json()).detail.code, 'memory_command_unavailable');
    process.stdout.write(JSON.stringify({ disabled: true }));
    return;
  }
  assert.equal(created.status, 201, await created.clone().text());
  const memory = await created.json();
  const replay = await request('POST', '/api/v1/memories/', 0, createKey, body);
  assert.equal(replay.status, 201);
  assert.deepEqual(await replay.json(), memory);
  const path = `/api/v1/memories/${memory.id}?project_id=project`;
  assert.equal((await request('GET', path)).status, 200);
  const patchKey = randomUUID();
  const patch = { version: 1, title: 'Edited through main' };
  const edited = await request('PATCH', path, 1, patchKey, patch);
  assert.equal(edited.status, 200, await edited.clone().text());
  assert.equal((await edited.json()).version, 2);
  assert.equal((await request('PATCH', path, 1, patchKey, patch)).status, 200);
  assert.equal((await request('PATCH', path, 1, randomUUID(), patch)).status, 409);
  await assert.rejects(
    request('GET', path.replace('project_id=project', 'project_id=other')),
    /project scope mismatch/,
  );
  const deleteKey = randomUUID();
  assert.equal((await request('DELETE', path, 2, deleteKey)).status, 204);
  assert.equal((await request('DELETE', path, 2, deleteKey)).status, 204);
  assert.equal((await request('GET', path)).status, 404);
  process.stdout.write(JSON.stringify({ memoryId: memory.id, createKey, patchKey, deleteKey }));
}
run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
