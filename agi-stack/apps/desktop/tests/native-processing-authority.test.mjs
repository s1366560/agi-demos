import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import {
  wireCases,
  nativeScope,
  projectScope,
  config,
  capability,
  json,
  response,
  operation,
} from './nativeKnowledgeProcessingFixtures.mjs';
const require = createRequire(import.meta.url);
const root = process.env.CLOUD_MEMORY_AUTHORITY_DIST ?? '/tmp/agistack-desktop-test-dist';
const {
  createDesktopProjectMemoriesOperationsV2,
  createDesktopNativeKnowledgeProcessingClientV2,
  createDesktopNativeKnowledgeProcessingCommandClientV2,
  withDesktopProjectMemoriesAuthorityOperationV2,
} = require(`${root}/src/plugins/desktopProjectMemoriesAuthorityModuleV2.js`);
const { createDesktopProjectMemoriesHttpAuthorityV2 } = require(
  `${root}/src/plugins/desktopProjectMemoriesHttpProjectionV2.js`,
);
function fixture(bind = createDesktopProjectMemoriesHttpAuthorityV2, cap = () => capability) {
  const events = [];
  const leases = [];
  const actions = {
    async acquireServiceOperationLease(input) {
      events.push('acquire');
      const lease = { id: leases.length + 1, uses: 0, releases: 0 };
      leases.push(lease);
      assert.deepEqual(input.scope, {
        kind: 'project',
        tenant_id: projectScope.tenantId,
        project_id: projectScope.projectId,
      });
      return {
        status: 'admitted',
        useService: (fn) => {
          lease.uses += 1;
          return fn({ bindOperation: bind });
        },
        async release() {
          events.push('release');
          lease.releases += 1;
          assert.equal(lease.releases, 1, `lease ${lease.id} released more than once`);
        },
      };
    },
  };
  const ops = createDesktopProjectMemoriesOperationsV2(() => actions, cap);
  return {
    events,
    leases,
    actions,
    query: createDesktopNativeKnowledgeProcessingClientV2(ops, config),
    command: createDesktopNativeKnowledgeProcessingCommandClientV2(ops, config),
  };
}
test('every native processing fixture uses and releases its own scoped generation lease once', async () => {
  const old = globalThis.fetch;
  let current;
  globalThis.fetch = async (url) =>
    String(url).endsWith('/context')
      ? json({ contract_version: '1.0.0', scope: nativeScope })
      : json(response(current.name));
  try {
    const f = fixture();
    for (current of wireCases) {
      const previousLeases = f.leases.length;
      const previousEvents = f.events.length;
      const options = { expectedScope: nativeScope };
      const got = current.request.command
        ? await f.command.execute(projectScope, operation(current.name), options)
        : await f.query.query(projectScope, operation(current.name), options);
      assert.deepEqual(got, response(current.name));
      assert.equal(f.leases.length, previousLeases + 1, current.name);
      assert.deepEqual(f.events.slice(previousEvents), ['acquire', 'release'], current.name);
      assert.deepEqual(f.leases.at(-1), {
        id: previousLeases + 1, uses: 1, releases: 1,
      }, current.name);
    }
    assert.equal(f.leases.length, wireCases.length);
  } finally {
    globalThis.fetch = old;
  }
});
test('missing observed capability cannot make an HTTP call', async () => {
  const old = globalThis.fetch;
  globalThis.fetch = () => assert.fail('must not fetch');
  try {
    const f = fixture(undefined, () => null);
    await assert.rejects(f.query.query(projectScope, operation('configuration')), /unavailable/);
    assert.deepEqual(f.events, ['acquire', 'release']);
  } finally {
    globalThis.fetch = old;
  }
});
test('semantic and write expected scope is required before acquiring lease', async () => {
  const f = fixture();
  for (const op of [operation('semantic'), operation('configure_embedding')]) {
    await assert.rejects(async () =>
      op.operation === 'semantic'
        ? f.query.query(projectScope, op)
        : f.command.execute(projectScope, op),
    );
  }
  assert.deepEqual(f.events, []);
});
test('legacy authority without processing stays fail closed and releases', async () => {
  const f = fixture(() => ({ load: async () => {}, executeSync: async () => {} }));
  await assert.rejects(f.query.query(projectScope, operation('configuration')), /unavailable/);
  assert.deepEqual(f.events, ['acquire', 'release']);
});
test('late native processing receipt and retained handle are revoked', async () => {
  let resolve;
  const f = fixture(() => ({
    load: async () => {},
    executeSync: async () => {},
    queryProcessing: () => new Promise((r) => (resolve = r)),
  }));
  let retained;
  let pending;
  await withDesktopProjectMemoriesAuthorityOperationV2(
    f.actions,
    { kind: 'processing-query', config, scope: projectScope, query: operation('configuration') },
    (authority) => {
      retained = authority;
      pending = authority.queryProcessing(operation('configuration'));
    },
  );
  resolve(response('configuration'));
  await assert.rejects(pending, /released/);
  await assert.rejects(retained.queryProcessing(operation('configuration')), /released/);
});
test('malformed provider response never bypasses transport-independent validation', async () => {
  const f = fixture(() => ({
    load: async () => {},
    executeSync: async () => {},
    queryProcessing: async () => ({
      ...response('configuration'),
      scope: { ...nativeScope, context_revision: 99 },
    }),
  }));
  await assert.rejects(
    f.query.query(projectScope, operation('configuration'), { expectedScope: nativeScope }),
    /scope_conflict/,
  );
  assert.deepEqual(f.events, ['acquire', 'release']);
});


test('overlapping successful and failed operations each release only their own lease', async () => {
  const pending = [];
  const f = fixture(() => ({
    load: async () => {},
    executeSync: async () => {},
    queryProcessing: () => new Promise((resolve, reject) => pending.push({ resolve, reject })),
  }));
  const options = { expectedScope: nativeScope };
  const first = f.query.query(projectScope, operation('configuration'), options);
  const second = f.query.query(projectScope, operation('configuration'), options);
  const firstFailure = assert.rejects(first, /first operation failed/);
  await Promise.resolve();
  assert.equal(pending.length, 2);
  assert.deepEqual(f.leases, [
    { id: 1, uses: 1, releases: 0 },
    { id: 2, uses: 1, releases: 0 },
  ]);

  pending[1].resolve(response('configuration'));
  await second;
  assert.deepEqual(f.leases, [
    { id: 1, uses: 1, releases: 0 },
    { id: 2, uses: 1, releases: 1 },
  ]);

  pending[0].reject(new Error('first operation failed'));
  await firstFailure;
  assert.deepEqual(f.leases, [
    { id: 1, uses: 1, releases: 1 },
    { id: 2, uses: 1, releases: 1 },
  ]);
});
