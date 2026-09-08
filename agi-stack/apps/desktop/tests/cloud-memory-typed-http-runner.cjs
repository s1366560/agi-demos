const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const root = process.argv[2];
const { executeVaultBoundCloudRequest } = require(`${root}/electron/main/cloudRequestPolicy.js`);
const { createDesktopProjectMemoriesHttpAuthorityV2 } = require(
  `${root}/src/plugins/desktopProjectMemoriesHttpProjectionV2.js`,
);
const { createDesktopProjectMemoriesOperationsV2, createDesktopCloudMemoryClientV2 } = require(
  `${root}/src/plugins/desktopProjectMemoriesAuthorityModuleV2.js`,
);
const base = process.argv[3];
const enabled = process.argv[4] === 'enabled';
const config = {
  apiBaseUrl: base,
  deviceAuthorizationBaseUrl: '',
  apiKey: '',
  localApiToken: '',
  tenantId: 'tenant',
  projectId: 'project',
  workspaceId: '',
  mode: 'cloud',
  workspaceRoot: '',
};
const scope = { authority: 'cloud', tenantId: 'tenant', projectId: 'project' };
const options = { expectedActorId: 'actor', expectedContextRevision: 1 };
const session = {
  version: 1,
  api_base_url: base,
  runtime_mode: 'cloud',
  credential_kind: 'cloud_bearer',
  credential: 'isolated-http-fixture',
  expires_at: '2099-08-10T00:00:00Z',
};
globalThis.window = {
  __MEMSTACK_DESKTOP__: {
    core: {
      invoke: (method, input) => {
        assert.equal(method, 'cloud_request');
        return executeVaultBoundCloudRequest(input.request, {
          loadTrustedSession: async () => session,
          fetch: globalThis.fetch,
        });
      },
    },
  },
};
let leases = 0;
let releases = 0;
const actions = {
  async acquireServiceOperationLease(input) {
    assert.deepEqual(input.scope, { kind: 'project', tenant_id: 'tenant', project_id: 'project' });
    leases++;
    return {
      status: 'admitted',
      useService: (fn) => fn({ bindOperation: createDesktopProjectMemoriesHttpAuthorityV2 }),
      async release() {
        releases++;
      },
    };
  },
};
const client = createDesktopCloudMemoryClientV2(
  createDesktopProjectMemoriesOperationsV2(() => actions),
  config,
);
async function run() {
  await assert.rejects(
    client.execute(
      scope,
      { operation: 'get', id: 'missing' },
      { ...options, expectedActorId: 'other' },
    ),
    (error) => error.message === 'cloud_memory_scope_conflict',
  );
  const createKey = randomUUID();
  const create = {
    operation: 'create',
    idempotencyKey: createKey,
    memory: {
      title: 'Real bridge',
      content: 'Preserved content',
      tags: ['bridge'],
      metadata: { origin: 'node-python-postgres' },
    },
  };
  if (!enabled) {
    await assert.rejects(
      client.execute(scope, create, options),
      (error) => error.status === 503 && error.message === 'memory_command_unavailable',
    );
    assert.equal(leases, releases);
    process.stdout.write(JSON.stringify({ disabled: true }));
    return;
  }
  const created = await client.execute(scope, create, options);
  const memoryId = created.result.id;
  assert.equal(created.result.version, 1);
  assert.deepEqual(await client.execute(scope, create, options), created);
  assert.equal(
    (await client.execute(scope, { operation: 'get', id: memoryId }, options)).result.id,
    memoryId,
  );
  const patchKey = randomUUID();
  const patch = {
    operation: 'update',
    id: memoryId,
    expectedRevision: 1,
    idempotencyKey: patchKey,
    patch: { title: 'Edited through main' },
  };
  const updated = await client.execute(scope, patch, options);
  assert.equal(updated.result.version, 2);
  assert.deepEqual(await client.execute(scope, patch, options), updated);
  await assert.rejects(
    client.execute(scope, { ...patch, idempotencyKey: randomUUID() }, options),
    (error) => error.status === 409,
  );
  const deleteKey = randomUUID();
  const remove = {
    operation: 'delete',
    id: memoryId,
    expectedRevision: 2,
    idempotencyKey: deleteKey,
  };
  assert.deepEqual(await client.execute(scope, remove, options), {
    operation: 'delete',
    result: { memoryId, deleted: true },
  });
  await client.execute(scope, remove, options);
  await assert.rejects(
    client.execute(scope, { operation: 'get', id: memoryId }, options),
    (error) => error.status === 404,
  );
  assert.equal(leases, releases);
  process.stdout.write(JSON.stringify({ memoryId, createKey, patchKey, deleteKey }));
}
run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
