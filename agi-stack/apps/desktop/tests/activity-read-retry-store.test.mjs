import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { createLocalStorageActivityReadRetryStore } = require(
  '/tmp/agistack-desktop-test-dist/src/features/agent-authority/activityReadRetryStore.js',
);
const scope = { authority: 'cloud', principalId: 'user-1', tenantId: 'tenant-1', projectId: 'project-1' };
const receipt = { entry_id: 'run:1', entry_revision: 2, read_at: '2026-09-05T00:00:00Z' };
function fixture() {
  const values = new Map();
  return { values, store: createLocalStorageActivityReadRetryStore({
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  }) };
}

test('retry receipts are isolated by authority even for identical principal, tenant and project', () => {
  const { store } = fixture();
  store.save(scope, [receipt]);
  assert.deepEqual(store.load({ ...scope, authority: 'local' }), []);
  store.save({ ...scope, authority: 'local' }, [{ ...receipt, entry_revision: 4 }]);
  assert.deepEqual(store.load(scope), [receipt]);
});

test('legacy receipts without authority are not assigned to either runtime', () => {
  const { values, store } = fixture();
  const legacyKey = 'memstack.activity.authority-retry.v1:user-1:tenant-1:project-1';
  values.set(legacyKey, JSON.stringify([receipt]));
  assert.deepEqual(store.load(scope), []);
  assert.deepEqual(store.load({ ...scope, authority: 'local' }), []);
  assert.equal(values.has(legacyKey), true);
});

test('acknowledging a submitted snapshot preserves concurrent receipt additions and progress', () => {
  const { store } = fixture();
  store.save(scope, [receipt]);
  const submitted = store.load(scope);
  const newer = { ...receipt, entry_revision: 3 };
  const another = { ...receipt, entry_id: 'run:2' };
  store.save(scope, [newer, another]);
  store.acknowledge(scope, submitted);
  assert.deepEqual(store.load(scope), [newer, another]);
  store.acknowledge(scope, [newer]);
  assert.deepEqual(store.load(scope), [another]);
  store.acknowledge(scope, [another]);
  assert.deepEqual(store.load(scope), []);
});

test('acknowledgment requires both revision and timestamp coverage and stays scoped', () => {
  const { store } = fixture();
  const later = { ...receipt, read_at: '2026-09-05T01:00:00Z' };
  store.save(scope, [later]);
  store.acknowledge(scope, [{ ...receipt, entry_revision: 10 }]);
  assert.deepEqual(store.load(scope), [later]);
  store.acknowledge({ ...scope, authority: 'local' }, [later]);
  assert.deepEqual(store.load(scope), [later]);
  store.acknowledge(scope, [later]);
  assert.deepEqual(store.load(scope), []);
});

test('retry capacity overflow rejects before persistence and preserves the pending queue', () => {
  const { store } = fixture();
  const current = Array.from({ length: 300 }, (_, i) => ({ ...receipt, entry_id: `a:${i}` }));
  const incoming = Array.from({ length: 300 }, (_, i) => ({ ...receipt, entry_id: `b:${i}` }));
  store.save(scope, current);
  const pending = store.load(scope);
  assert.throws(() => store.save(scope, incoming), /activity_read_retry_capacity_exceeded/);
  assert.deepEqual(store.load(scope), pending);
});

for (const authority of ['cloud', 'local']) {
  test(`${authority} transport flush acknowledges its snapshot without removing concurrent writes`, async () => {
    const { createDesktopAgentAuthorityAdapter } = require(
      '/tmp/agistack-desktop-test-dist/src/features/agent-authority/cloudAgentAuthorityClient.js',
    );
    const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');
    const { store } = fixture();
    const currentScope = { ...scope, authority };
    const later = { ...receipt, entry_revision: 3 };
    const another = { ...receipt, entry_id: 'run:2' };
    store.save(currentScope, [receipt]);
    const adapter = createDesktopAgentAuthorityAdapter({
      ...DEFAULT_CONFIG, mode: authority, tenantId: scope.tenantId, projectId: scope.projectId,
      apiKey: 'test-session', localApiToken: 'test-launch',
    }, {
      retryStore: store,
      fetchImpl: async (_url, init) => {
        if (init.method === 'PUT') {
          const submitted = JSON.parse(init.body);
          assert.deepEqual(submitted.entries, [receipt]);
          store.save(currentScope, [later, another]);
          return Response.json({ project_id: scope.projectId, authority_revision: 2, entries: [receipt] });
        }
        return Response.json({ project_id: scope.projectId, authority_revision: 1, entries: [] });
      },
    });
    assert.equal((await adapter.activityClient.flushPendingActivityReadState(currentScope)).kind, 'synced');
    assert.deepEqual(store.load(currentScope), [later, another]);
  });
}
