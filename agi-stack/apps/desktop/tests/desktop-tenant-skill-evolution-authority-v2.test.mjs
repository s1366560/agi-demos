import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test, afterEach } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist/src';
const moduleV2 = require(`${ROOT}/plugins/desktopTenantSkillEvolutionAuthorityModuleV2.js`);
const { createDesktopTenantSkillEvolutionHttpProjectionV2 } = require(
  `${ROOT}/plugins/desktopTenantSkillEvolutionHttpProjectionV2.js`,
);
const { DEFAULT_CONFIG } = require(`${ROOT}/types.js`);
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});
const config = (mode = 'cloud', overrides = {}) => ({
  ...DEFAULT_CONFIG,
  mode,
  apiBaseUrl: 'https://api.test',
  apiKey: 'trusted-session',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  ...overrides,
});
const detail = {
  skill_id: 'review/1',
  skill_name: 'review',
  captured_session_count: 2,
  jobs: [],
  route: [],
  trigger: {},
};
const runResult = { skill_id: 'review/1', skill_name: 'review', result: { queued: true } };
function fixture(
  runtime = config(),
  bind = createDesktopTenantSkillEvolutionHttpProjectionV2,
  cleanup = async () => {},
) {
  const events = [];
  const operations = moduleV2.createDesktopTenantSkillEvolutionOperationsV2(() => ({
    async acquireServiceOperationLease(input) {
      events.push(['acquire', input]);
      return {
        status: 'acquired',
        async useService(use) {
          return use(Object.freeze({ bindOperation: bind }));
        },
        async release() {
          events.push(['release']);
          await cleanup();
        },
      };
    },
  }));
  return {
    operations,
    client: moduleV2.createDesktopTenantSkillEvolutionClientV2(operations, runtime),
    events,
  };
}
test('per-skill evolution retains Cloud GET/POST scope, encoding, signal and results via exact leases', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: new URL(url), init });
    return Response.json(init.method === 'POST' ? runResult : detail);
  };
  const { client, events } = fixture();
  const signal = new AbortController().signal;
  assert.deepEqual(await client.getManagedSkillEvolution('review/1', signal), detail);
  assert.deepEqual(await client.runManagedSkillEvolution('review/1', signal), runResult);
  assert.deepEqual(
    calls.map(({ url, init }) => [url.pathname, url.search, init.method]),
    [
      ['/api/v1/skills/review%2F1/evolution', '?tenant_id=tenant-1', 'GET'],
      ['/api/v1/skills/review%2F1/evolution/run', '?tenant_id=tenant-1', 'POST'],
    ],
  );
  for (const { init } of calls) {
    assert.equal(init.signal, signal);
    assert.equal(init.body, undefined);
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer trusted-session');
  }
  assert.deepEqual(
    events.map(([kind]) => kind),
    ['acquire', 'release', 'acquire', 'release'],
  );
  assert.deepEqual(events[0][1], {
    service: moduleV2.DESKTOP_TENANT_SKILL_EVOLUTION_AUTHORITY_SERVICE_V2,
    version: '1.0.0',
    scope: { kind: 'tenant', tenant_id: 'tenant-1' },
  });
});
test('Local evolution explicitly fails closed and never synthesizes Cloud success', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return Response.json(runResult);
  };
  const { client, events } = fixture(config('local'));
  for (const method of ['getManagedSkillEvolution', 'runManagedSkillEvolution']) {
    await assert.rejects(
      () => client[method]('review/1'),
      (e) => e.status === 501 && e.payload.code === 'local_skill_evolution_authority_unavailable',
    );
  }
  assert.equal(calls, 0);
  assert.equal(events.filter(([kind]) => kind === 'release').length, 2);
});
test('blank scope construction is inert; malformed response and missing services are rejected', async () => {
  const empty = fixture(config('cloud', { tenantId: '' }));
  await assert.rejects(async () => empty.client.getManagedSkillEvolution('review/1'));
  assert.equal(empty.events.length, 0);
  const bad = fixture(config(), () =>
    Object.freeze({
      get: async () => ({ ...detail, skill_id: 'foreign' }),
      run: async () => runResult,
    }),
  );
  await assert.rejects(
    () => bad.client.getManagedSkillEvolution('review/1'),
    /tenant_skill_evolution_response_invalid/,
  );
  const ops = moduleV2.createDesktopTenantSkillEvolutionOperationsV2(() => null);
  await assert.rejects(async () =>
    moduleV2
      .createDesktopTenantSkillEvolutionClientV2(ops, config())
      .runManagedSkillEvolution('review/1'),
  );
});
test('operation retains original error when lease release also fails', async () => {
  const primary = new Error('primary');
  const current = fixture(
    config(),
    () =>
      Object.freeze({
        get: async () => {
          throw primary;
        },
        run: async () => runResult,
      }),
    async () => {
      throw new Error('release');
    },
  );
  await assert.rejects(
    () => current.client.getManagedSkillEvolution('review/1'),
    (e) => e === primary,
  );
  assert.equal(current.events.filter(([kind]) => kind === 'release').length, 1);
});
