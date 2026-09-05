import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test, afterEach } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist/src';
const moduleV2 = require(`${ROOT}/plugins/desktopTenantSkillPackagesAuthorityModuleV2.js`);
const { createDesktopTenantSkillPackagesHttpProjectionV2 } = require(
  `${ROOT}/plugins/desktopTenantSkillPackagesHttpProjectionV2.js`,
);
const { DEFAULT_CONFIG } = require(`${ROOT}/types.js`);
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});
const config = (mode = 'cloud', overrides = {}) => ({
  ...DEFAULT_CONFIG,
  mode,
  apiBaseUrl: mode === 'local' ? 'http://127.0.0.1:8088' : 'https://api.test',
  apiKey: 'trusted-session',
  localApiToken: 'launch-capability',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  ...overrides,
});
const skill = (overrides = {}) => ({
  id: 'review',
  tenant_id: 'tenant-1',
  name: 'review',
  description: 'Review',
  tools: [],
  status: 'active',
  scope: 'tenant',
  project_id: null,
  revision: 4,
  ...overrides,
});
const version = (overrides = {}) => ({
  id: 'review:4',
  skill_id: 'review',
  version_number: 4,
  version_label: null,
  change_summary: null,
  created_by: 'local-runtime',
  created_at: '2026-09-05',
  ...overrides,
});
const lifecycle = (row = skill()) => ({
  action: 'imported',
  skill: row,
  version_number: 4,
  version_label: null,
});
const packageInput = (overrides = {}) => ({
  skill_md_content: '---\nname: review\n---\n\nReview',
  scope: 'tenant',
  ...overrides,
});
function fixture(
  runtime = config(),
  bind = createDesktopTenantSkillPackagesHttpProjectionV2,
  events = [],
  cleanup = async () => {},
) {
  const operations = moduleV2.createDesktopTenantSkillPackagesOperationsV2(() => ({
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
    client: moduleV2.createDesktopTenantSkillPackagesClientV2(operations, runtime),
    events,
  };
}
function authority(overrides = {}) {
  return Object.freeze({
    importPackage: async () => lifecycle(),
    importZip: async () => lifecycle(),
    listVersions: async () => ({ versions: [version()], total: 1 }),
    rollback: async () => skill(),
    exportPackage: async () => ({
      format: 'agentskills.io/skill-package',
      skill: skill(),
      skill_md_content: 'content',
      resource_files: {},
      version_number: 4,
      version_label: null,
    }),
    getVersion: async () => ({ ...version(), skill_md_content: 'content', resource_files: {} }),
    ...overrides,
  });
}
test('all six Cloud package operations retain routes, multipart, signal and tenant leases', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: new URL(url), init });
    const path = new URL(url).pathname;
    if (path.endsWith('/versions')) return Response.json({ versions: [version()], total: 1 });
    if (path.endsWith('/versions/4'))
      return Response.json({ ...version(), skill_md_content: 'content', resource_files: {} });
    if (path.endsWith('/rollback')) return Response.json(skill());
    if (path.endsWith('/export'))
      return Response.json({
        format: 'agentskills.io/skill-package',
        skill: skill(),
        skill_md_content: 'content',
        resource_files: {},
        version_number: 4,
        version_label: null,
      });
    return Response.json(lifecycle());
  };
  const { client, events } = fixture();
  const signal = new AbortController().signal;
  await client.importManagedSkillPackage(packageInput(), signal);
  await client.importManagedSkillZip(new File(['zip'], 'skill.zip'), {}, signal);
  await client.listManagedSkillVersions('review', signal);
  await client.rollbackManagedSkill('review', 4, undefined, signal);
  await client.exportManagedSkillPackage('review', signal);
  await client.getManagedSkillVersion('review', 4, signal);
  assert.deepEqual(
    calls.map(({ url, init }) => [url.pathname, init.method]),
    [
      ['/api/v1/skills/import', 'POST'],
      ['/api/v1/skills/import/zip', 'POST'],
      ['/api/v1/skills/review/versions', 'GET'],
      ['/api/v1/skills/review/rollback', 'POST'],
      ['/api/v1/skills/review/export', 'GET'],
      ['/api/v1/skills/review/versions/4', 'GET'],
    ],
  );
  assert.deepEqual(JSON.parse(calls[0].init.body), packageInput());
  assert.equal(calls[1].init.body.get('archive').name, 'skill.zip');
  assert.equal(new Headers(calls[1].init.headers).has('Content-Type'), false);
  assert.equal(calls[2].url.searchParams.get('limit'), '50');
  assert.deepEqual(JSON.parse(calls[3].init.body), { version_number: 4 });
  for (const { url, init } of calls) {
    assert.equal(url.searchParams.get('tenant_id'), 'tenant-1');
    assert.equal(init.signal, signal);
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer trusted-session');
    assert.equal(new Headers(init.headers).has('X-Agistack-Launch'), false);
  }
  assert.equal(events.length, 12);
  for (let i = 0; i < events.length; i += 2) {
    assert.deepEqual(events[i], [
      'acquire',
      {
        service: moduleV2.DESKTOP_TENANT_SKILL_PACKAGES_AUTHORITY_SERVICE_V2,
        version: '1.0.0',
        scope: { kind: 'tenant', tenant_id: 'tenant-1' },
      },
    ]);
    assert.deepEqual(events[i + 1], ['release']);
  }
});
test('Local import selects exact resource scope revision within one package lease and preserves rollback', async () => {
  const calls = [];
  const events = [];
  const runtime = config('local');
  globalThis.fetch = async (url, init) => {
    calls.push({ url: new URL(url), init });
    if (init.method === 'GET')
      return Response.json({
        items: [skill(), skill({ scope: 'project', project_id: 'project-1', revision: 9 })],
      });
    return Response.json(new URL(url).pathname.endsWith('/rollback') ? skill() : lifecycle());
  };
  const { client } = fixture(runtime, createDesktopTenantSkillPackagesHttpProjectionV2, events);
  await client.importManagedSkillPackage(packageInput({ overwrite: true }));
  assert.equal(JSON.parse(calls[1].init.body).expected_revision, 4);
  assert.equal(JSON.parse(calls[1].init.body).resource_id, 'review');
  assert.equal(JSON.parse(calls[1].init.body).value.full_content, packageInput().skill_md_content);
  assert.deepEqual(
    events.map(([kind]) => kind),
    ['acquire', 'release'],
  );
  assert.equal(calls[0].url.searchParams.get('project_id'), 'project-1');
  assert.equal(new Headers(calls[1].init.headers).get('X-Agistack-Launch'), 'launch-capability');
  await client.rollbackManagedSkill('review', 0, 4);
  const body = JSON.parse(calls[2].init.body);
  assert.equal(body.expected_revision, 4);
  assert.equal(body.target_revision, 0);
  assert.equal(body.value, null);
  assert.deepEqual(body.vault_refs, []);
  assert.match(body.idempotency_key, /^[0-9a-f-]{36}$/i);
});
test('Local import refuses overwrite, ambiguous matches, absent revisions and unsafe frontmatter before POST', async () => {
  let rows = [skill()];
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push(init.method);
    return Response.json({ items: rows });
  };
  const { client } = fixture(config('local'));
  await assert.rejects(
    () => client.importManagedSkillPackage(packageInput()),
    (e) => e.status === 409,
  );
  rows = [skill(), skill()];
  await assert.rejects(
    () => client.importManagedSkillPackage(packageInput({ overwrite: true })),
    (error) => error.code === 'desktop_tenant_skill_definitions_operation_response_invalid',
  );
  rows = [skill({ revision: undefined })];
  await assert.rejects(
    () => client.importManagedSkillPackage(packageInput({ overwrite: true })),
    (e) => e.status === 428,
  );
  const before = calls.length;
  await assert.rejects(
    () =>
      client.importManagedSkillPackage(
        packageInput({ skill_md_content: '---\nname: ../escape\n---\ntext' }),
      ),
    /invalid_managed_resource_id/,
  );
  assert.equal(calls.length, before);
  assert.ok(calls.every((method) => method === 'GET'));
});
test('Cloud project import targets requested project while Local cross-project input fails before lease', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return Response.json(lifecycle(skill({ scope: 'project', project_id: 'project-2' })));
  };
  const cloud = fixture();
  await cloud.client.importManagedSkillPackage(
    packageInput({ scope: 'project', project_id: 'project-2' }),
  );
  assert.equal(JSON.parse(calls[0].init.body).project_id, 'project-2');
  const local = fixture(config('local'));
  await assert.rejects(async () =>
    local.client.importManagedSkillPackage(
      packageInput({ scope: 'project', project_id: 'project-2' }),
    ),
  );
  assert.equal(local.events.length, 0);
});
test('blank tenant client constructs; invalid scope, aborted inputs and unavailable services do not fetch', async () => {
  const empty = fixture(config('cloud', { tenantId: '' }));
  await assert.rejects(async () => empty.client.listManagedSkillVersions('review'));
  assert.equal(empty.events.length, 0);
  const current = fixture();
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(async () =>
    current.client.listManagedSkillVersions('review', controller.signal),
  );
  assert.equal(current.events.length, 0);
  const ops = moduleV2.createDesktopTenantSkillPackagesOperationsV2(() => null);
  const missing = moduleV2.createDesktopTenantSkillPackagesClientV2(ops, config());
  await assert.rejects(
    async () => missing.listManagedSkillVersions('review'),
    /desktop_renderer_generation_actions_unavailable/,
  );
});
test('malformed and wrong identity responses fail; primary errors survive release failures', async () => {
  const bad = fixture(config(), () =>
    authority({
      getVersion: async () => ({
        ...version(),
        skill_id: 'foreign',
        skill_md_content: '',
        resource_files: {},
      }),
    }),
  );
  await assert.rejects(() => bad.client.getManagedSkillVersion('review', 4));
  assert.equal(bad.events.at(-1)[0], 'release');
  const primary = new Error('primary');
  const failing = fixture(
    config(),
    () =>
      authority({
        listVersions: async () => {
          throw primary;
        },
      }),
    [],
    async () => {
      throw new Error('cleanup');
    },
  );
  await assert.rejects(
    () => failing.client.listManagedSkillVersions('review'),
    (e) => e === primary,
  );
});
test('Local ZIP is explicitly unavailable without HTTP and releases acquired lease', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return Response.json({});
  };
  const { client, events } = fixture(config('local'));
  await assert.rejects(
    () => client.importManagedSkillZip(new File(['zip'], 'skill.zip')),
    (e) => e.status === 501 && e.payload.code === 'managed_resource_contract_v2_required',
  );
  assert.equal(calls, 0);
  assert.deepEqual(
    events.map(([kind]) => kind),
    ['acquire', 'release'],
  );
});

test('Local metadata-only history preserves null content while Cloud still rejects null content', async () => {
  globalThis.fetch = async () =>
    Response.json({ ...version(), skill_md_content: null, resource_files: {} });
  const local = fixture(config('local'));
  const record = await local.client.getManagedSkillVersion('review', 4);
  assert.equal(record.skill_md_content, null);
  assert.equal(Object.isFrozen(record), true);
  await assert.rejects(() => fixture().client.getManagedSkillVersion('review', 4));
});
test('abort while acquiring a lease prevents provider bind and releases; escaped callback cannot rebind', async () => {
  const controller = new AbortController();
  let bindCount = 0;
  let releases = 0;
  let resume;
  let escaped;
  const gate = new Promise((resolve) => {
    resume = resolve;
  });
  const service = Object.freeze({
    bindOperation() {
      bindCount += 1;
      return authority();
    },
  });
  const operations = moduleV2.createDesktopTenantSkillPackagesOperationsV2(() => ({
    async acquireServiceOperationLease() {
      await gate;
      return {
        status: 'acquired',
        async useService(callback) {
          escaped = callback;
          return callback(service);
        },
        async release() {
          releases += 1;
        },
      };
    },
  }));
  const client = moduleV2.createDesktopTenantSkillPackagesClientV2(operations, config());
  const pending = client.listManagedSkillVersions('review', controller.signal);
  controller.abort();
  resume();
  await assert.rejects(() => pending, { name: 'AbortError' });
  assert.equal(bindCount, 0);
  assert.equal(releases, 1);
  await assert.rejects(() => escaped(service), (error) => error.code === 'tenant_skill_operation_released');
  assert.equal(bindCount, 0);
});
