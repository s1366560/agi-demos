import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const root = process.env.CLOUD_MEMORY_AUTHORITY_DIST ?? '/tmp/agistack-desktop-test-dist';
const {
  createDesktopProjectMemoriesOperationsV2,
  createDesktopCloudMemoryClientV2,
  withDesktopProjectMemoriesAuthorityOperationV2,
} = require(`${root}/src/plugins/desktopProjectMemoriesAuthorityModuleV2.js`);
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
const command = {
  operation: 'delete',
  id: 'memory',
  expectedRevision: 2,
  idempotencyKey: '00000000-0000-0000-0000-00000000000a',
};
const options = { expectedActorId: 'actor', expectedContextRevision: 7 };
const result = { operation: 'delete', result: { memoryId: 'memory', deleted: true } };
function fixture(executeCloudMemory = async () => result) {
  const events = [];
  const authority = {
    load: async () => {
      throw Error('unused');
    },
    executeSync: async () => {
      throw Error('unused');
    },
    ...(executeCloudMemory ? { executeCloudMemory } : {}),
  };
  const actions = {
    async acquireServiceOperationLease(input) {
      events.push(['acquire', input]);
      return {
        status: 'admitted',
        async useService(fn) {
          events.push(['use']);
          return fn({
            bindOperation(c, s) {
              events.push(['bind', c, s]);
              return authority;
            },
          });
        },
        async release() {
          events.push(['release']);
        },
      };
    },
  };
  return {
    events,
    authority,
    actions,
    client: createDesktopCloudMemoryClientV2(
      createDesktopProjectMemoriesOperationsV2(() => actions),
      config,
    ),
  };
}
test('cloud command uses exactly one scoped lease and releases after receipt', async () => {
  const f = fixture();
  assert.deepEqual(await f.client.execute(scope, command, options), result);
  assert.deepEqual(
    f.events.map((e) => e[0]),
    ['acquire', 'use', 'bind', 'release'],
  );
  assert.deepEqual(f.events[0][1].scope, {
    kind: 'project',
    tenant_id: 'tenant',
    project_id: 'project',
  });
});
test('invalid command rejected before lease', async () => {
  const f = fixture();
  await assert.rejects(f.client.execute(scope, { ...command, expectedRevision: 0 }, options));
  assert.equal(f.events.length, 0);
});
test('old authority without cloud commands fails closed and releases', async () => {
  const f = fixture(null);
  await assert.rejects(f.client.execute(scope, command, options), /unavailable/);
  assert.equal(f.events.at(-1)[0], 'release');
});
test('malformed or wrong memory receipt never confirms delete', async () => {
  for (const r of [
    { ...result, result: { memoryId: 'other', deleted: true } },
    { ...result, result: { memoryId: 'memory', deleted: false } },
    { ...result, operation: 'get' },
  ]) {
    const f = fixture(async () => r);
    await assert.rejects(f.client.execute(scope, command, options));
    assert.equal(f.events.at(-1)[0], 'release');
  }
});
test('receipt and command snapshots are immutable', async () => {
  const input = { ...command };
  const f = fixture(async (c, o) => {
    assert.ok(Object.isFrozen(c));
    assert.ok(Object.isFrozen(o));
    assert.equal(c.id, 'memory');
    return result;
  });
  const pending = f.client.execute(scope, input, options);
  input.id = 'changed';
  const receipt = await pending;
  assert.ok(Object.isFrozen(receipt.result));
});
test('retained cloud authority is revoked after callback settles', async () => {
  const f = fixture();
  let retained;
  await withDesktopProjectMemoriesAuthorityOperationV2(
    f.actions,
    { kind: 'cloud', config, scope, command, ...options },
    (authority) => {
      retained = authority;
    },
  );
  await assert.rejects(retained.executeCloudMemory(command, options), /released/);
});
test('late cloud result after lease callback escapes is discarded', async () => {
  let resolve;
  const f = fixture(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  let pending;
  await withDesktopProjectMemoriesAuthorityOperationV2(
    f.actions,
    { kind: 'cloud', config, scope, command, ...options },
    (authority) => {
      pending = authority.executeCloudMemory(command, options);
    },
  );
  resolve(result);
  await assert.rejects(pending, /released/);
});
test('backend failure releases once preserving error', async () => {
  const error = new Error('backend');
  const f = fixture(async () => {
    throw error;
  });
  await assert.rejects(f.client.execute(scope, command, options), (e) => e === error);
  assert.equal(f.events.filter((e) => e[0] === 'release').length, 1);
});
