import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const root = process.env.CLOUD_MEMORY_AUTHORITY_DIST ?? '/tmp/agistack-desktop-test-dist';
const { executeVaultBoundCloudRequest } = require(`${root}/electron/main/cloudRequestPolicy.js`);
const { desktopVaultBoundCloudRequestBroker } = require(`${root}/src/api/cloudRequestBroker.js`);
const memoryScope = {
  actor_id: 'actor',
  tenant_id: 'tenant',
  project_id: 'project',
  context_revision: 7,
};
const request = {
  path: '/api/v1/memories/',
  method: 'POST',
  memory_scope: memoryScope,
  mutation: {
    kind: 'memory-command',
    expected_revision: 0,
    idempotency_key: '00000000-0000-0000-0000-00000000000a',
  },
  body: { project_id: 'project', title: 'Title', content: 'Body' },
};
function dependencies({
  actor = 'actor',
  tenant = 'tenant',
  project = 'project',
  revision = 7,
} = {}) {
  const paths = [];
  let loads = 0;
  return {
    paths,
    get loads() {
      return loads;
    },
    async loadTrustedSession() {
      loads++;
      return {
        version: 1,
        api_base_url: 'https://example.test',
        runtime_mode: 'cloud',
        credential_kind: 'cloud_bearer',
        credential: `fixture-session-${loads}`,
        expires_at: null,
      };
    },
    async fetch(url, init) {
      const path = new URL(url).pathname;
      paths.push(path);
      assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer fixture-session-1');
      const body =
        path === '/api/v1/workspace-context'
          ? { context: { tenant_id: tenant, project_id: project, revision } }
          : path === '/api/v1/auth/me'
            ? { user_id: actor }
            : { id: 'memory' };
      return new Response(JSON.stringify(body), {
        headers: { 'content-type': 'application/json' },
      });
    },
  };
}
test('memory scope uses one captured vault session for context, actor and write', async () => {
  const deps = dependencies();
  await executeVaultBoundCloudRequest(request, deps);
  assert.equal(deps.loads, 1);
  assert.deepEqual(deps.paths, [
    '/api/v1/workspace-context',
    '/api/v1/auth/me',
    '/api/v1/memories/',
  ]);
});
for (const changed of [
  { actor: 'other' },
  { tenant: 'other' },
  { revision: 8 },
  { revision: null },
]) {
  test(`memory scope rejects drift before mutation: ${JSON.stringify(changed)}`, async () => {
    const deps = dependencies(changed);
    await assert.rejects(executeVaultBoundCloudRequest(request, deps));
    assert.equal(deps.paths.includes('/api/v1/memories/'), false);
  });
}
test('memory scope cannot authorize a different product endpoint', async () => {
  const deps = dependencies();
  await assert.rejects(
    executeVaultBoundCloudRequest({ path: '/api/v1/auth/me', memory_scope: memoryScope }, deps),
  );
  assert.equal(deps.loads, 0);
});
test('scoped detail read also binds the expected actor', async () => {
  const deps = dependencies();
  await executeVaultBoundCloudRequest(
    { path: '/api/v1/memories/memory?project_id=project', memory_scope: memoryScope },
    deps,
  );
  assert.deepEqual(deps.paths, [
    '/api/v1/workspace-context',
    '/api/v1/auth/me',
    '/api/v1/memories/memory',
  ]);
});
test('renderer broker preserves the memory scope across IPC', async (t) => {
  let wire;
  const previous = globalThis.window;
  t.after(() => {
    if (previous === undefined) delete globalThis.window;
    else globalThis.window = previous;
  });
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        invoke: async (_, args) => {
          wire = args.request;
          return { status: 200, body: {} };
        },
      },
    },
  };
  await desktopVaultBoundCloudRequestBroker().requestResponse(request);
  assert.deepEqual(wire.memory_scope, memoryScope);
});
