import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const root = process.env.CLOUD_MEMORY_CLIENT_DIST ?? '/tmp/agistack-desktop-test-dist';
const { createDesktopProjectMemoriesHttpAuthorityV2 } = require(
  root + '/src/plugins/desktopProjectMemoriesHttpProjectionV2.js',
);
const { requireDesktopProjectMemoriesSnapshotV2 } = require(
  root + '/src/plugins/desktopProjectMemoriesOperationContractV2.js',
);
const config = {
  mode: 'cloud',
  apiBaseUrl: 'https://example.test',
  apiKey: 'fixture',
  deviceAuthorizationBaseUrl: '',
  localApiToken: '',
  tenantId: 'tenant',
  projectId: 'project',
  workspaceId: '',
  workspaceRoot: '',
};
const scope = { authority: 'cloud', tenantId: 'tenant', projectId: 'project' };
const memory = {
  id: 'memory',
  project_id: 'project',
  title: 'Title',
  content: 'Body',
  content_type: 'text',
  version: 3,
  status: 'enabled',
  processing_status: 'pending',
  created_at: '2026-09-08T00:00:00Z',
  updated_at: null,
};
const capabilities = () => ({
  protocol_version: 1,
  tenant_id: 'tenant',
  project_id: 'project',
  actor_id: 'actor',
  allowed_actions: ['create'],
  objects: [{ memory_id: 'memory', revision: 3, allowed_actions: ['update'] }],
});

async function load(t, capability, actor = 'actor', identityStatus = 200) {
  const paths = [];
  t.mock.method(globalThis, 'fetch', async (url) => {
    const path = new URL(url).pathname;
    paths.push(path);
    const body =
      path === '/api/v1/workspace-context'
        ? {
            context: {
              tenant_id: 'tenant',
              project_id: 'project',
              revision: 2,
            },
          }
        : path === '/api/v1/auth/me'
          ? { user_id: actor }
          : {
              memories: [memory],
              total: 1,
              page: 1,
              page_size: 50,
              ...(capability === undefined ? {} : { command_capabilities: capability }),
            };
    return new Response(JSON.stringify(body), {
      status: path === '/api/v1/auth/me' ? identityStatus : 200,
      headers: { 'content-type': 'application/json' },
    });
  });
  const result = await createDesktopProjectMemoriesHttpAuthorityV2(config, scope).load();
  return { result, paths };
}
test('HTTP capabilities use authenticated actor and survive the authority result guard', async (t) => {
  const { result, paths } = await load(t, capabilities());
  assert.equal(result.commandCapabilities.actorId, 'actor');
  assert.deepEqual(paths, ['/api/v1/workspace-context', '/api/v1/memories/', '/api/v1/auth/me']);
  assert.deepEqual(requireDesktopProjectMemoriesSnapshotV2(result, scope), result);
});
test('identity capability service failure disables writes while preserving the page', async (t) => {
  const { result } = await load(t, capabilities(), 'actor', 503);
  assert.equal(result.memories[0].content, 'Body');
  assert.equal(result.commandCapabilities, undefined);
});
test('expired identity rejects the complete operation', async (t) => {
  await assert.rejects(load(t, capabilities(), 'actor', 401), (error) => error.status === 401);
});
test('older server preserves the original read snapshot without a new identity request', async (t) => {
  const { result, paths } = await load(t, undefined);
  assert.equal(Object.hasOwn(result, 'commandCapabilities'), false);
  assert.equal(paths.includes('/api/v1/auth/me'), false);
  assert.deepEqual(requireDesktopProjectMemoriesSnapshotV2(result, scope), result);
});
test('malformed capability leaves memory content readable', async (t) => {
  const { result } = await load(t, {
    ...capabilities(),
    allowed_actions: ['delete'],
  });
  assert.equal(result.memories[0].content, 'Body');
  assert.equal(result.commandCapabilities, undefined);
});
test('a different authenticated actor rejects the whole response', async (t) => {
  await assert.rejects(load(t, capabilities(), 'other'), /cloud_memory_capability_scope_conflict/);
});
test('authority result guard rejects mutated capability scope', async (t) => {
  const { result } = await load(t, capabilities());
  assert.throws(
    () =>
      requireDesktopProjectMemoriesSnapshotV2(
        {
          ...result,
          commandCapabilities: {
            ...result.commandCapabilities,
            projectId: 'other',
          },
        },
        scope,
      ),
    /invalid result/,
  );
});
