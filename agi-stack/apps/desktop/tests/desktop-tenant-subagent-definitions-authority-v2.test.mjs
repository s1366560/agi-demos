import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const moduleV2 = require(
  `${ROOT}/src/plugins/desktopTenantSubAgentDefinitionsAuthorityModuleV2.js`,
);
const projectionV2 = require(
  `${ROOT}/src/plugins/desktopTenantSubAgentDefinitionsHttpProjectionV2.js`,
);

test('SubAgent Definitions exposes six leased operations', () => {
  assert.equal(
    Object.keys(moduleV2.createDesktopTenantSubAgentDefinitionsOperationsV2(() => null)).length,
    6,
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
const mutation = () => ({
  name: 'reviewer',
  display_name: 'Reviewer',
  system_prompt: 'Review carefully.\n',
  trigger_description: '',
  trigger_examples: [],
  trigger_keywords: [],
  model: 'inherit',
  color: 'blue',
  allowed_tools: ['*'],
  allowed_skills: [],
  allowed_mcp_servers: [],
  max_tokens: 4096,
  temperature: 0.7,
  max_iterations: 10,
  project_id: 'project-1',
  metadata: null,
});
const definition = (overrides = {}) => ({
  id: 'subagent-1',
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  name: 'reviewer',
  enabled: true,
  source: 'database',
  metadata: null,
  ...overrides,
});
const authority = (overrides = {}) => ({
  async load() {
    return [definition()];
  },
  async importFilesystem() {
    return definition();
  },
  async create() {
    return definition();
  },
  async update() {
    return definition();
  },
  async setEnabled() {
    return definition({ enabled: false });
  },
  async delete() {},
  ...overrides,
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
const service = (value) =>
  Object.freeze({
    bindOperation() {
      return value;
    },
  });
const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
afterEach(() => {
  globalThis.fetch = originalFetch;
  if (originalWindow === undefined) delete globalThis.window;
  else globalThis.window = originalWindow;
});

test('six operations use exact tenant or project leases with immutable payloads and signals', async () => {
  const lifecycle = [],
    captured = {};
  const signal = new AbortController().signal;
  const operations = moduleV2.createDesktopTenantSubAgentDefinitionsOperationsV2(() =>
    actions(
      service(
        authority({
          async create(currentScope, input, currentSignal) {
            captured.scope = currentScope;
            captured.input = input;
            captured.signal = currentSignal;
            return definition();
          },
        }),
      ),
      lifecycle,
    ),
  );
  const client = moduleV2.createDesktopTenantSubAgentDefinitionsClientV2(operations, config());
  await client.listManagedSubAgents(signal);
  await client.createManagedSubAgent(mutation(), signal);
  await client.updateManagedSubAgent('subagent-1', mutation(), 2, signal);
  await client.setManagedSubAgentEnabled('subagent-1', false, 2, signal);
  await client.deleteManagedSubAgent('subagent-1', 2, signal);
  await client.importManagedFilesystemSubAgent('reviewer', 'project-1', signal);
  const leases = lifecycle.filter(([kind]) => kind === 'acquire').map(([, input]) => input);
  assert.equal(leases.length, 6);
  assert.equal(lifecycle.filter(([kind]) => kind === 'release').length, 6);
  assert.deepEqual(leases[0].scope, { kind: 'tenant', tenant_id: 'tenant-1' });
  for (const lease of [leases[1], leases[2], leases[5]]) {
    assert.deepEqual(lease.scope, {
      kind: 'project',
      tenant_id: 'tenant-1',
      project_id: 'project-1',
    });
    assert.equal(lease.service, moduleV2.DESKTOP_TENANT_SUBAGENT_DEFINITIONS_AUTHORITY_SERVICE_V2);
    assert.equal(lease.version, '1.0.0');
  }
  assert.deepEqual(leases[3].scope, leases[0].scope);
  assert.deepEqual(leases[4].scope, leases[0].scope);
  assert.equal(captured.signal, signal);
  assert.ok(Object.isFrozen(captured.scope));
  assert.ok(Object.isFrozen(captured.input.allowed_tools));
  assert.equal(captured.input.system_prompt, 'Review carefully.\n');
});

test('unbound cloud configuration can construct clients but invalid scope never acquires', async () => {
  let acquisitions = 0;
  const operations = moduleV2.createDesktopTenantSubAgentDefinitionsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions++;
      throw new Error('unexpected');
    },
  }));
  const client = moduleV2.createDesktopTenantSubAgentDefinitionsClientV2(operations, {
    ...config(),
    tenantId: '',
    projectId: '',
    workspaceId: '',
  });
  await assert.rejects(() => client.listManagedSubAgents(), /operation input invalid/u);
  for (const invalid of [
    { config: config(), scope: scope('other-project') },
    { config: config(), scope: scope(), extra: true },
  ])
    assert.throws(
      () => operations.loadTenantSubAgentDefinitions(invalid),
      /operation input invalid/u,
    );
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    () =>
      operations.loadTenantSubAgentDefinitions({
        config: config(),
        scope: scope(),
        signal: controller.signal,
      }),
    { name: 'AbortError' },
  );
  assert.equal(acquisitions, 0);
});

test('list accepts mixed filesystem and other accessible projects and unpaginated Local items', async () => {
  const make = (items) =>
    moduleV2.createDesktopTenantSubAgentDefinitionsOperationsV2(() =>
      actions(
        service(
          authority({
            async load() {
              return items;
            },
          }),
        ),
      ),
    );
  const items = [
    definition({ project_id: 'other-project' }),
    definition({
      id: 'fs-reviewer',
      source: 'filesystem',
      project_id: null,
      file_path: '/skills/reviewer.md',
    }),
  ];
  const result = await make(items).loadTenantSubAgentDefinitions({
    config: config(),
    scope: scope(),
  });
  assert.equal(result.length, 2);
  assert.ok(Object.isFrozen(result[1]));
  const localItems = Array.from({ length: 101 }, (_, i) =>
    definition({ id: `subagent-${i}`, revision: 0 }),
  );
  assert.equal(
    (
      await make(localItems).loadTenantSubAgentDefinitions({
        config: config('local'),
        scope: scope(null, 'local'),
      })
    ).length,
    101,
  );
  for (const bad of [
    [definition({ tenant_id: 'other' })],
    [definition(), definition()],
    [definition({ enabled: 'true' })],
  ]) {
    await assert.rejects(
      () =>
        make(bad).loadTenantSubAgentDefinitions({
          config: config(),
          scope: scope(),
        }),
      /operation response invalid/u,
    );
  }
});

test('leases pin old generations, revoke escaped callbacks and preserve primary failures', async () => {
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
  const operations = moduleV2.createDesktopTenantSubAgentDefinitionsOperationsV2(() => current);
  const pending = operations.loadTenantSubAgentDefinitions({
    config: config(),
    scope: scope(),
  });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(
    service(
      authority({
        async load() {
          return [definition({ id: 'new' })];
        },
      }),
    ),
  );
  finish([definition({ id: 'old' })]);
  assert.equal((await pending)[0].id, 'old');
  await assert.rejects(() => capture.use(service(authority())), /operation released/u);
  assert.equal(
    (
      await operations.loadTenantSubAgentDefinitions({
        config: config(),
        scope: scope(),
      })
    )[0].id,
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
    () =>
      operations.loadTenantSubAgentDefinitions({
        config: config(),
        scope: scope(),
      }),
    (error) => error === primary,
  );
  assert.equal(lifecycle.filter(([kind]) => kind === 'release').length, 1);
});

test('Cloud and Local preserve routes, mutation envelopes and explicit import unavailability', async () => {
  const calls = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(input);
    calls.push({ url, init });
    if (init.method === 'DELETE')
      return url.hostname === 'api.test'
        ? new Response(null, { status: 204 })
        : Response.json({
            deleted: true,
            id: 'subagent-1',
            mutation_receipt: {},
          });
    if (init.method === 'GET') return Response.json({ items: [definition()] });
    return Response.json(definition());
  };
  for (const mode of ['cloud', 'local']) {
    const projection = projectionV2.createDesktopTenantSubAgentDefinitionsHttpProjectionV2(
      config(mode),
    );
    const current = scope('project-1', mode);
    await projection.load(scope(null, mode));
    await projection.create(current, mutation());
    await projection.update(current, 'subagent-1', mutation(), 2);
    await projection.setEnabled(current, 'subagent-1', true, 2);
    assert.equal(await projection.delete(current, 'subagent-1', 2), undefined);
    if (mode === 'cloud') await projection.importFilesystem(current, 'reviewer');
    else {
      const before = calls.length;
      await assert.rejects(
        () => projection.importFilesystem(current, 'reviewer'),
        (error) =>
          error.status === 501 &&
          error.reasonCode === 'local_subagent_registry_unavailable' &&
          error.payload.availability === 'unavailable',
      );
      await assert.rejects(
        () => projection.delete(current, 'subagent-1'),
        (error) => error.status === 428,
      );
      assert.equal(calls.length, before);
    }
  }
  assert.equal(calls.length, 11);
  assert.equal(calls[0].url.pathname, '/api/v1/subagents/');
  assert.equal(calls[0].url.searchParams.get('include_filesystem'), 'true');
  assert.equal(calls[3].url.pathname, '/api/v1/subagents/subagent-1/enable');
  assert.equal(calls[3].init.body, undefined);
  assert.equal(calls[5].url.pathname, '/api/v1/subagents/filesystem/reviewer/import');
  for (const { url, init } of calls.slice(6)) {
    assert.equal(url.hostname, '127.0.0.1');
    assert.equal(new Headers(init.headers).get('X-Agistack-Launch'), 'private-launch');
    if (init.method !== 'GET') {
      const body = JSON.parse(init.body);
      assert.equal(body.contract_version, 2);
      assert.deepEqual(body.vault_refs, []);
      assert.equal(body.expected_revision, init.method === 'POST' ? 0 : 2);
      assert.equal(typeof body.idempotency_key, 'string');
    }
  }
});

test('Cloud edits and enables accessible definitions outside the active project', async () => {
  const lifecycle = [];
  const operations = moduleV2.createDesktopTenantSubAgentDefinitionsOperationsV2(() =>
    actions(
      service(
        authority({
          async update() {
            return definition({ project_id: 'project-2' });
          },
          async setEnabled() {
            return definition({ project_id: 'project-2' });
          },
        }),
      ),
      lifecycle,
    ),
  );
  for (const projectId of ['project-1', '']) {
    const client = moduleV2.createDesktopTenantSubAgentDefinitionsClientV2(operations, {
      ...config(),
      projectId,
    });
    assert.equal(
      (
        await client.updateManagedSubAgent('subagent-1', {
          ...mutation(),
          project_id: 'project-2',
        })
      ).project_id,
      'project-2',
    );
    assert.equal(
      (await client.setManagedSubAgentEnabled('subagent-1', true)).project_id,
      'project-2',
    );
  }
  assert.deepEqual(lifecycle[0][1].scope, {
    kind: 'project',
    tenant_id: 'tenant-1',
    project_id: 'project-2',
  });
  assert.deepEqual(lifecycle[2][1].scope, {
    kind: 'tenant',
    tenant_id: 'tenant-1',
  });
  const local = moduleV2.createDesktopTenantSubAgentDefinitionsClientV2(
    operations,
    config('local'),
  );
  assert.throws(
    () => local.updateManagedSubAgent('subagent-1', { ...mutation(), project_id: 'project-2' }, 0),
    /operation input invalid/u,
  );
});

test('delete rejects successful HTTP responses that do not attest deletion', async () => {
  for (const mode of ['cloud', 'local']) {
    const projection = projectionV2.createDesktopTenantSubAgentDefinitionsHttpProjectionV2(
      config(mode),
    );
    for (const payload of [
      { error: 'failed' },
      { deleted: false, id: 'subagent-1' },
      { deleted: true, id: 'other' },
    ]) {
      globalThis.fetch = async () => Response.json(payload);
      await assert.rejects(
        () => projection.delete(scope(null, mode), 'subagent-1', 2),
        (error) =>
          error.status === 502 &&
          error.reasonCode === 'tenant_subagent_definitions_delete_response_invalid',
      );
    }
  }
});

test('Cloud vault transport avoids renderer credentials and direct fetch', async () => {
  const calls = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          calls.push({ command, request: args.request });
          return { status: 200, body: { subagents: [definition()] } };
        },
      },
    },
  };
  globalThis.fetch = async () => {
    throw new Error('unexpected fetch');
  };
  const client = projectionV2.createDesktopTenantSubAgentDefinitionsHttpProjectionV2({
    ...config(),
    apiKey: '',
  });
  assert.equal((await client.load(scope()))[0].id, 'subagent-1');
  assert.equal(calls[0].command, 'cloud_request');
  assert.equal(JSON.stringify(calls).includes('Authorization'), false);
  assert.equal(JSON.stringify(calls).includes('trusted-session'), false);
});

test('catalog Profile enables the exact service and disabling it removes authority', async () => {
  const runtime = require('@agistack/plugin-runtime');
  const entry = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) =>
      item.module_ref === moduleV2.DESKTOP_TENANT_SUBAGENT_DEFINITIONS_AUTHORITY_MODULE_REF_V2,
  );
  assert.equal(
    entry.contract_digest,
    moduleV2.desktopTenantSubAgentDefinitionsAuthorityDefinitionV2.contractDigest,
  );
  assert.deepEqual(entry.contract.services.provides, [
    {
      service: moduleV2.DESKTOP_TENANT_SUBAGENT_DEFINITIONS_AUTHORITY_SERVICE_V2,
      version: '1.0.0',
    },
  ]);
  assert.throws(
    () =>
      moduleV2.applyDesktopTenantSubAgentDefinitionsAuthorityV2(
        { provide() {} },
        { strategy: 'desktop-api-fetch', fallback: true },
      ),
    /requires desktop-api-fetch/u,
  );
  const authorities = readdirSync(`${ROOT}/src/plugins`)
    .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
    .flatMap((name) =>
      Object.values(require(`${ROOT}/src/plugins/${name}`)).filter(
        (value) => value?.moduleRef && typeof value.apply === 'function',
      ),
    );
  const profile = JSON.parse(
    readFileSync(
      new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url),
      'utf8',
    ),
  );
  const loader = new runtime.LoaderV2(
    [...runtime.createDesktopRendererDefinitionsV2(), ...authorities],
    'desktop-renderer',
  );
  const generation = await loader.stage(profile);
  assert.ok(
    generation.resolve(
      moduleV2.DESKTOP_TENANT_SUBAGENT_DEFINITIONS_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: '1.0.0' },
    ),
  );
  const disabled = structuredClone(profile);
  disabled.entries.find(
    (item) => item.entry_id === 'builtin-desktop-tenant-subagent-definitions-authority',
  ).enabled = false;
  const next = await loader.stage(disabled);
  assert.throws(
    () =>
      next.resolve(
        moduleV2.DESKTOP_TENANT_SUBAGENT_DEFINITIONS_AUTHORITY_SERVICE_V2,
        { kind: 'root' },
        { version: '1.0.0' },
      ),
    (error) => error.code === 'missing_service',
  );
  await next.dispose();
  await generation.dispose();
});
