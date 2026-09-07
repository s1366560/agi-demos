import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const moduleV2 = require(`${ROOT}/src/plugins/desktopTenantSkillDefinitionsAuthorityModuleV2.js`);
const projectionV2 = require(
  `${ROOT}/src/plugins/desktopTenantSkillDefinitionsHttpProjectionV2.js`,
);

test('skill definitions exposes all seven operations', () => {
  assert.equal(
    Object.keys(moduleV2.createDesktopTenantSkillDefinitionsOperationsV2(() => null)).length,
    7,
  );
});

const config = (mode = 'cloud') => ({
  apiBaseUrl: mode === 'cloud' ? 'https://api.test' : 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: 'https://api.test',
  apiKey: 'trusted-session',
  localApiToken: mode === 'local' ? 'private-launch' : '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  mode,
  workspaceRoot: '',
});
const scope = (projectId = null, authority = 'cloud') => ({
  authority,
  tenantId: 'tenant-1',
  projectId,
});
const metadata = () => ({
  name: 'reviewer',
  description: 'Review changes.',
  tools: ['read_file'],
  metadata: {},
  license: null,
  compatibility: null,
  allowed_tools_raw: null,
  spec_version: '1.0',
});
const mutation = () => ({
  ...metadata(),
  scope: 'project',
  project_id: 'project-1',
  full_content: 'Review changes.\n',
});
const skill = (extra = {}) => ({
  id: 'skill-1',
  tenant_id: 'tenant-1',
  project_id: null,
  name: 'reviewer',
  description: 'Review changes.',
  tools: ['read_file'],
  status: 'active',
  scope: 'tenant',
  source: 'database',
  is_system_skill: false,
  ...extra,
});
const content = () => ({
  skill_id: 'skill-1',
  name: 'reviewer',
  full_content: 'Review changes.\n',
  scope: 'tenant',
  is_system_skill: false,
});
const authority = (extra = {}) => ({
  async load() {
    return [skill()];
  },
  async create() {
    return skill();
  },
  async getContent() {
    return content();
  },
  async update() {
    return skill({ revision: 3 });
  },
  async updateContent() {
    return skill({ revision: 4 });
  },
  async setStatus() {
    return skill({ status: 'disabled' });
  },
  async delete() {},
  ...extra,
});
const service = (value) =>
  Object.freeze({
    bindOperation() {
      return value;
    },
  });
const actions = (value, lifecycle = [], capture = {}, releaseError) => ({
  async acquireServiceOperationLease(input) {
    lifecycle.push(['acquire', input]);
    return {
      status: 'accepted',
      async useService(callback) {
        capture.use = callback;
        return callback(value);
      },
      async release() {
        lifecycle.push(['release']);
        if (releaseError) throw releaseError;
      },
    };
  },
});
const originalFetch = globalThis.fetch,
  originalWindow = globalThis.window;
afterEach(() => {
  globalThis.fetch = originalFetch;
  if (originalWindow === undefined) delete globalThis.window;
  else globalThis.window = originalWindow;
});

test('seven operations pin exact scope and retain metadata then content revisions', async () => {
  const lifecycle = [],
    captured = {};
  const signal = new AbortController().signal;
  const operations = moduleV2.createDesktopTenantSkillDefinitionsOperationsV2(() =>
    actions(
      service(
        authority({
          async create(current, input, currentSignal) {
            captured.input = input;
            captured.scope = current;
            captured.signal = currentSignal;
            return skill({ scope: input.scope, project_id: input.project_id });
          },
          async updateContent(_scope, _id, _value, revision) {
            captured.revision = revision;
            return skill({ revision: 4 });
          },
        }),
      ),
      lifecycle,
    ),
  );
  const client = moduleV2.createDesktopTenantSkillDefinitionsClientV2(operations, config());
  await client.listManagedSkills(signal);
  await client.createManagedSkill(mutation(), signal);
  await client.getManagedSkillContent('skill-1', signal);
  const updated = await client.updateManagedSkill('skill-1', metadata(), 2, signal);
  await client.updateManagedSkillContent('skill-1', 'Review\n', updated.revision, signal);
  await client.setManagedSkillStatus('skill-1', 'disabled', 4, signal);
  await client.deleteManagedSkill('skill-1', 4, signal);
  const leases = lifecycle.filter(([kind]) => kind === 'acquire').map(([, input]) => input);
  assert.equal(leases.length, 7);
  assert.equal(lifecycle.filter(([kind]) => kind === 'release').length, 7);
  for (const lease of leases.slice(0, 2))
    assert.deepEqual(lease.scope, {
      kind: 'project',
      tenant_id: 'tenant-1',
      project_id: 'project-1',
    });
  for (const lease of leases.slice(2))
    assert.deepEqual(lease.scope, { kind: 'tenant', tenant_id: 'tenant-1' });
  assert.ok(
    leases.every(
      (lease) =>
        lease.version === '1.0.0' &&
        lease.service === moduleV2.DESKTOP_TENANT_SKILL_DEFINITIONS_AUTHORITY_SERVICE_V2,
    ),
  );
  assert.equal(captured.revision, 3);
  assert.equal(captured.signal, signal);
  assert.ok(Object.isFrozen(captured.input.tools));
  assert.ok(Object.isFrozen(captured.scope));
});

test('blank tenant binds safely while invalid inputs and pre-aborted calls never acquire', async () => {
  let acquired = 0;
  const ops = moduleV2.createDesktopTenantSkillDefinitionsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquired++;
      throw new Error('unexpected');
    },
  }));
  const client = moduleV2.createDesktopTenantSkillDefinitionsClientV2(ops, {
    ...config(),
    tenantId: '',
    projectId: '',
  });
  await assert.rejects(() => client.listManagedSkills(), /operation input invalid/u);
  assert.throws(
    () =>
      ops.createTenantSkillDefinition({
        config: config(),
        scope: scope('project-1'),
        input: { ...mutation(), project_id: 'project-2' },
      }),
    /operation input invalid/u,
  );
  assert.throws(
    () =>
      ops.setTenantSkillStatus({
        config: config(),
        scope: scope(),
        skillId: 'skill-1',
        status: 'invalid',
      }),
    /operation input invalid/u,
  );
  assert.throws(
    () =>
      ops.getTenantSkillContent({
        config: config(),
        scope: scope(),
        skillId: 'skill-1',
        extra: true,
      }),
    /operation input invalid/u,
  );
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    () =>
      ops.loadTenantSkillDefinitions({
        config: config(),
        scope: scope(),
        signal: controller.signal,
      }),
    { name: 'AbortError' },
  );
  assert.equal(acquired, 0);
});

test('system scope and equal ids across tenant/project are valid; Local catalog is unpaginated', async () => {
  const load = async (items, mode = 'cloud') =>
    moduleV2
      .createDesktopTenantSkillDefinitionsOperationsV2(() =>
        actions(
          service(
            authority({
              async load() {
                return items;
              },
            }),
          ),
        ),
      )
      .loadTenantSkillDefinitions({ config: config(mode), scope: scope('project-1', mode) });
  const items = [
    skill(),
    skill({ scope: 'project', project_id: 'project-1' }),
    skill({ scope: 'system', tenant_id: 'system', is_system_skill: true, source: 'filesystem' }),
  ];
  assert.equal((await load(items)).length, 3);
  assert.equal(
    (
      await load(
        Array.from({ length: 101 }, (_, i) => skill({ id: `skill-${i}` })),
        'local',
      )
    ).length,
    101,
  );
  await assert.rejects(() => load([skill(), skill()]), /response invalid/u);
  await assert.rejects(() => load([skill({ tenant_id: 'other' })]), /response invalid/u);
  const ops = moduleV2.createDesktopTenantSkillDefinitionsOperationsV2(() =>
    actions(
      service(
        authority({
          async getContent() {
            return { ...content(), skill_id: 'other' };
          },
        }),
      ),
    ),
  );
  await assert.rejects(
    () => ops.getTenantSkillContent({ config: config(), scope: scope(), skillId: 'skill-1' }),
    /response invalid/u,
  );
});

test('HMR preserves pinned work and released callback rejection; primary error wins release failure', async () => {
  let finish;
  const capture = {},
    lifecycle = [];
  let current = actions(
    service(
      authority({
        load: () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      }),
    ),
    lifecycle,
    capture,
  );
  const ops = moduleV2.createDesktopTenantSkillDefinitionsOperationsV2(() => current);
  const pending = ops.loadTenantSkillDefinitions({ config: config(), scope: scope() });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(
    service(
      authority({
        async load() {
          return [skill({ id: 'new' })];
        },
      }),
    ),
  );
  finish([skill({ id: 'old' })]);
  assert.equal((await pending)[0].id, 'old');
  await assert.rejects(() => capture.use(service(authority())), /operation released/u);
  assert.equal(
    (await ops.loadTenantSkillDefinitions({ config: config(), scope: scope() }))[0].id,
    'new',
  );
  const primary = new Error('primary');
  current = actions(
    service(
      authority({
        async load() {
          throw primary;
        },
      }),
    ),
    [],
    {},
    new Error('release'),
  );
  await assert.rejects(
    () => ops.loadTenantSkillDefinitions({ config: config(), scope: scope() }),
    (error) => error === primary,
  );
  assert.equal(lifecycle.filter(([kind]) => kind === 'release').length, 1);
});

test('Cloud and Local use their exact wire contracts, including deletion receipts', async () => {
  const calls = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(input);
    calls.push({ url, init });
    if (init.method === 'DELETE')
      return url.hostname === 'api.test'
        ? new Response(null, { status: 204 })
        : Response.json({ deleted: true, id: 'skill-1', mutation_receipt: {} });
    if (init.method === 'GET')
      return Response.json(url.pathname.endsWith('/content') ? content() : { items: [skill()] });
    return Response.json(skill());
  };
  for (const mode of ['cloud', 'local']) {
    const projection = projectionV2.createDesktopTenantSkillDefinitionsHttpProjectionV2(
      config(mode),
    );
    const current = scope(null, mode);
    await projection.load(scope('project-1', mode));
    await projection.create(scope('project-1', mode), mutation());
    await projection.getContent(current, 'skill-1');
    await projection.update(current, 'skill-1', metadata(), 2);
    await projection.updateContent(current, 'skill-1', 'Keep trailing newline\n', 3);
    await projection.setStatus(current, 'skill-1', 'disabled', 4);
    assert.equal(await projection.delete(current, 'skill-1', 5), undefined);
  }
  assert.equal(calls.length, 14);
  assert.equal(calls[0].url.pathname, '/api/v1/skills/');
  assert.equal(calls[0].url.searchParams.get('project_id'), 'project-1');
  assert.equal(calls[5].init.body, undefined);
  assert.equal(calls[5].url.searchParams.get('status'), 'disabled');
  assert.equal(JSON.parse(calls[4].init.body).full_content, 'Keep trailing newline\n');
  for (const { url, init } of calls.slice(7)) {
    assert.equal(url.hostname, '127.0.0.1');
    assert.equal(new Headers(init.headers).get('X-Agistack-Launch'), 'private-launch');
    if (init.method !== 'GET') {
      const body = JSON.parse(init.body);
      assert.equal(body.contract_version, 2);
      assert.equal(typeof body.idempotency_key, 'string');
      assert.deepEqual(body.vault_refs, []);
    }
  }
  assert.equal(JSON.parse(calls[8].init.body).expected_revision, 0);
  assert.equal(typeof JSON.parse(calls[8].init.body).resource_id, 'string');
  assert.equal(JSON.parse(calls[11].init.body).expected_revision, 3);
  const local = projectionV2.createDesktopTenantSkillDefinitionsHttpProjectionV2(config('local'));
  const before = calls.length;
  await assert.rejects(
    () => local.delete(scope(null, 'local'), 'skill-1'),
    (error) => error.status === 428,
  );
  assert.equal(calls.length, before);
  for (const mode of ['cloud', 'local'])
    for (const payload of [
      { deleted: false, id: 'skill-1' },
      { deleted: true, id: 'other' },
      { error: 'failed' },
    ]) {
      globalThis.fetch = async () => Response.json(payload);
      await assert.rejects(
        () =>
          projectionV2
            .createDesktopTenantSkillDefinitionsHttpProjectionV2(config(mode))
            .delete(scope(null, mode), 'skill-1', 0),
        (error) => error.status === 502,
      );
    }
});

test('vault-bound Cloud load does not expose credentials or use renderer fetch', async () => {
  const calls = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          calls.push({ command, request: args.request });
          return { status: 200, body: { skills: [skill()] } };
        },
      },
    },
  };
  globalThis.fetch = async () => {
    throw new Error('unexpected fetch');
  };
  const projection = projectionV2.createDesktopTenantSkillDefinitionsHttpProjectionV2({
    ...config(),
    apiKey: '',
  });
  assert.equal((await projection.load(scope()))[0].id, 'skill-1');
  assert.equal(calls[0].command, 'cloud_request');
  assert.equal(JSON.stringify(calls).includes('Authorization'), false);
  assert.equal(JSON.stringify(calls).includes('trusted-session'), false);
});

test('abort during acquisition releases the lease without calling a provider', async () => {
  const controller = new AbortController();
  let calls = 0,
    released = 0;
  const operations = moduleV2.createDesktopTenantSkillDefinitionsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      controller.abort();
      return {
        status: 'accepted',
        async useService(callback) {
          return callback(
            service(
              authority({
                async load() {
                  calls++;
                  return [];
                },
              }),
            ),
          );
        },
        async release() {
          released++;
        },
      };
    },
  }));
  await assert.rejects(
    () =>
      operations.loadTenantSkillDefinitions({
        config: config(),
        scope: scope(),
        signal: controller.signal,
      }),
    { name: 'AbortError' },
  );
  assert.equal(calls, 0);
  assert.equal(released, 1);
});

test('list preserves project overrides while create verifies the requested resource scope', async () => {
  const operations = moduleV2.createDesktopTenantSkillDefinitionsOperationsV2(() =>
    actions(
      service(
        authority({
          async load() {
            return [skill({ scope: 'project', project_id: 'project-2' })];
          },
          async create() {
            return skill({ scope: 'tenant' });
          },
        }),
      ),
    ),
  );
  assert.equal(
    (
      await operations.loadTenantSkillDefinitions({ config: config(), scope: scope('project-1') })
    )[0].project_id,
    'project-2',
  );
  await assert.rejects(
    () =>
      operations.createTenantSkillDefinition({
        config: config(),
        scope: scope('project-1'),
        input: mutation(),
      }),
    /response invalid/u,
  );
});
