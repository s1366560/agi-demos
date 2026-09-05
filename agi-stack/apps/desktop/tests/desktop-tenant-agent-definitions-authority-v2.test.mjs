import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const runtime = require('@agistack/plugin-runtime');
const moduleV2 = require(`${ROOT}/src/plugins/desktopTenantAgentDefinitionsAuthorityModuleV2.js`);
const projectionV2 = require(`${ROOT}/src/plugins/desktopTenantAgentDefinitionsHttpProjectionV2.js`);
const pluginRoot = `${ROOT}/src/plugins`;
const authorityModules = readdirSync(pluginRoot)
  .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
  .flatMap((name) =>
    Object.values(require(`${pluginRoot}/${name}`)).filter(
      (value) => value?.moduleRef && typeof value?.apply === 'function',
    ),
  );
const bootstrapPath = new URL(
  '../../../../shared/profiles/memstack-default-bootstrap.v2.json',
  import.meta.url,
);
const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;

afterEach(() => {
  globalThis.fetch = originalFetch;
  if (originalWindow === undefined) delete globalThis.window;
  else globalThis.window = originalWindow;
});

const config = (mode = 'cloud') => ({
  apiBaseUrl: mode === 'cloud' ? 'https://api.test' : 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: 'https://api.test',
  apiKey: mode === 'cloud' ? 'trusted-session' : 'local-session',
  localApiToken: mode === 'local' ? 'private-launch' : '',
  tenantId: mode === 'cloud' ? 'tenant-1' : 'local',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode,
  workspaceRoot: '',
});
const scope = (authority = 'cloud', projectId = 'project-1') => ({
  authority,
  tenantId: authority === 'cloud' ? 'tenant-1' : 'local',
  projectId,
});
const mutation = (projectId = 'project-1') => ({
  name: 'release-reviewer',
  display_name: 'Release reviewer',
  system_prompt: 'Review releases.',
  project_id: projectId,
  trigger_description: 'Review releases.',
  trigger_examples: ['Review this release.'],
  trigger_keywords: ['release'],
  model: 'inherit',
  temperature: 0.4,
  max_tokens: 4096,
  max_iterations: 10,
  allowed_tools: ['run_tests'],
  allowed_skills: [],
  allowed_mcp_servers: [],
  can_spawn: false,
  max_spawn_depth: 3,
  agent_to_agent_enabled: false,
  agent_to_agent_allowlist: null,
  discoverable: true,
  max_retries: 0,
  fallback_models: [],
  execution_backend: { type: 'memstack' },
  workspace_config: { type: 'inherited' },
});
const definition = (id = 'agent-1', projectId = 'project-1') => ({
  id,
  revision: 3,
  tenant_id: 'tenant-1',
  project_id: projectId,
  name: 'release-reviewer',
  display_name: 'Release reviewer',
  system_prompt: 'Review releases.',
  enabled: true,
  status: 'active',
  trigger: { description: 'Review releases.', keywords: ['release'], examples: [] },
  model: 'inherit',
  temperature: 0.4,
  max_tokens: 4096,
  max_iterations: 10,
  allowed_tools: ['run_tests'],
  allowed_skills: [],
  allowed_mcp_servers: [],
  execution_backend: { type: 'memstack' },
  workspace_config: { type: 'inherited' },
  updated_at: '2026-09-05T00:00:00Z',
});
const external = () => ({
  id: 'acp-agent-1',
  agentKey: 'release-reviewer',
  name: 'Release reviewer',
  enabled: true,
  available: true,
});
const authority = (overrides = {}) => Object.freeze({
  async load() { return [definition()]; },
  async listExternal() { return [external()]; },
  async create() { return definition(); },
  async update() { return definition(); },
  async setEnabled() { return definition(); },
  async delete() { return { deleted: true, id: 'agent-1' }; },
  ...overrides,
});
const service = (value, capture = {}) => Object.freeze({
  bindOperation(currentConfig, currentScope) {
    capture.config = currentConfig;
    capture.scope = currentScope;
    return value;
  },
});
const actions = (value, lifecycle = [], releaseError, capture = {}) => ({
  async acquireServiceOperationLease(descriptor) {
    lifecycle.push(['acquire', descriptor]);
    return {
      status: 'accepted',
      useService(use) {
        capture.use = use;
        return use(value);
      },
      async release() {
        lifecycle.push(['release']);
        if (releaseError) throw releaseError;
      },
    };
  },
});

test('catalog, apply and Profile register the exact root Provider', async () => {
  const entry = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === moduleV2.DESKTOP_TENANT_AGENT_DEFINITIONS_AUTHORITY_MODULE_REF_V2,
  );
  assert.equal(
    moduleV2.desktopTenantAgentDefinitionsAuthorityDefinitionV2.contractDigest,
    entry.contract_digest,
  );
  assert.deepEqual(entry.contract.services.provides, [{
    service: moduleV2.DESKTOP_TENANT_AGENT_DEFINITIONS_AUTHORITY_SERVICE_V2,
    version: '1.0.0',
  }]);
  const provided = {};
  moduleV2.applyDesktopTenantAgentDefinitionsAuthorityV2({
    provide(key, value) { provided.key = key; provided.value = value; },
  }, { strategy: 'desktop-api-fetch' });
  assert.equal(provided.key, moduleV2.DESKTOP_TENANT_AGENT_DEFINITIONS_AUTHORITY_SERVICE_V2);
  assert.deepEqual(Object.keys(provided.value), ['bindOperation']);
  assert.throws(
    () => moduleV2.applyDesktopTenantAgentDefinitionsAuthorityV2(
      { provide() {} },
      { strategy: 'desktop-api-fetch', fallback: true },
    ),
    (error) => error.code === 'desktop_tenant_agent_definitions_authority_config_invalid',
  );

  const bootstrap = JSON.parse(readFileSync(bootstrapPath, 'utf8'));
  const loader = new runtime.LoaderV2(
    [...runtime.createDesktopRendererDefinitionsV2(), ...authorityModules],
    'desktop-renderer',
  );
  const generation = await loader.stage(bootstrap);
  assert.ok(generation.resolve(
    moduleV2.DESKTOP_TENANT_AGENT_DEFINITIONS_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: '1.0.0' },
  ));
  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    (item) => item.entry_id === 'builtin-desktop-tenant-agent-definitions-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () => disabledGeneration.resolve(
      moduleV2.DESKTOP_TENANT_AGENT_DEFINITIONS_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: '1.0.0' },
    ),
    (error) => error.code === 'missing_service',
  );
  await disabledGeneration.dispose();
  await generation.dispose();
});

test('six operations hold exact tenant or project leases and freeze inputs', async () => {
  const lifecycle = [];
  const captured = {};
  const serviceCapture = {};
  const signal = new AbortController().signal;
  const operations = moduleV2.createDesktopTenantAgentDefinitionsOperationsV2(() =>
    actions(service(authority({
      async load(currentScope, currentSignal) {
        captured.loadScope = currentScope;
        captured.signal = currentSignal;
        return [definition()];
      },
      async create(_scope, input) { captured.createInput = input; return definition(); },
    }), serviceCapture), lifecycle),
  );
  await operations.loadTenantAgentDefinitions({ config: config(), scope: scope(), signal });
  await operations.listTenantAgentDefinitionExternalAcpAgents({
    config: config(), scope: scope('cloud', null), signal,
  });
  await operations.createTenantAgentDefinition({
    config: config(), scope: scope(), input: mutation(), signal,
  });
  await operations.updateTenantAgentDefinition({
    config: config(), scope: scope(), definitionId: 'agent-1', input: mutation(),
    expectedRevision: 3, signal,
  });
  await operations.setTenantAgentDefinitionEnabled({
    config: config(), scope: scope(), definitionId: 'agent-1', enabled: false,
    expectedRevision: 3, signal,
  });
  await operations.deleteTenantAgentDefinition({
    config: config(), scope: scope(), definitionId: 'agent-1', expectedRevision: 3, signal,
  });
  const acquisitions = lifecycle.filter(([kind]) => kind === 'acquire').map(([, value]) => value);
  assert.equal(acquisitions.length, 6);
  assert.equal(lifecycle.filter(([kind]) => kind === 'release').length, 6);
  assert.deepEqual(acquisitions.map((value) => value.scope.kind), [
    'project', 'tenant', 'project', 'project', 'project', 'project',
  ]);
  assert.equal(acquisitions.every((value) =>
    value.service === moduleV2.DESKTOP_TENANT_AGENT_DEFINITIONS_AUTHORITY_SERVICE_V2 &&
    value.version === '1.0.0' && value.scope.tenant_id === 'tenant-1'), true);
  assert.equal(captured.signal, signal);
  assert.equal(Object.isFrozen(captured.loadScope), true);
  assert.equal(Object.isFrozen(captured.createInput), true);
  assert.equal(Object.isFrozen(captured.createInput.execution_backend), true);
  assert.equal(Object.isFrozen(serviceCapture.config), true);
  assert.equal(Object.isFrozen(serviceCapture.scope), true);
});

test('cloud workspace_context_unavailable config can bind without acquiring an empty tenant lease', async () => {
  // hydrateCloudSession clears all scope fields after the supported context-unavailable 404.
  const unavailableContextConfig = {
    ...config('cloud'), tenantId: '', projectId: '', workspaceId: '',
  };
  let acquisitions = 0;
  const operations = moduleV2.createDesktopTenantAgentDefinitionsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      return { status: 'rejected', reasonCode: 'missing_service_provider' };
    },
  }));
  const client = moduleV2.createDesktopTenantAgentDefinitionsClientV2(
    operations, unavailableContextConfig,
  );
  assert.equal(acquisitions, 0);
  await assert.rejects(
    () => client.listManagedAgents(),
    (error) => error.code === 'desktop_tenant_agent_definitions_operation_input_invalid',
  );
  assert.equal(acquisitions, 0);
});

test('input, service, authority and response drift fail closed', async () => {
  let acquisitions = 0;
  const rejected = moduleV2.createDesktopTenantAgentDefinitionsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      return { status: 'rejected', reasonCode: 'missing_service_provider' };
    },
  }));
  assert.throws(
    () => rejected.loadTenantAgentDefinitions({ config: config(), scope: scope(), extra: true }),
    (error) => error.code === 'desktop_tenant_agent_definitions_operation_input_invalid',
  );
  assert.equal(acquisitions, 0);
  await assert.rejects(
    () => rejected.loadTenantAgentDefinitions({ config: config(), scope: scope() }),
    (error) => error.reasonCode === 'missing_service_provider',
  );
  await assert.rejects(
    () => moduleV2.createDesktopTenantAgentDefinitionsOperationsV2(() => null)
      .loadTenantAgentDefinitions({ config: config(), scope: scope() }),
    (error) => error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
  await assert.rejects(
    () => moduleV2.createDesktopTenantAgentDefinitionsOperationsV2(() =>
      actions(Object.freeze({ bindOperation() { return authority(); }, extra: true })),
    ).loadTenantAgentDefinitions({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_agent_definitions_service_invalid',
  );
  await assert.rejects(
    () => moduleV2.createDesktopTenantAgentDefinitionsOperationsV2(() =>
      actions(service(Object.freeze({ ...authority(), extra: true }))),
    ).loadTenantAgentDefinitions({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_agent_definitions_service_invalid',
  );
  const malformed = [
    ['loadTenantAgentDefinitions', {}, { load: async () => [{ ...definition(), id: '' }] }],
    ['listTenantAgentDefinitionExternalAcpAgents', { scope: scope('cloud', null) },
      { listExternal: async () => [{ ...external(), available: 'yes' }] }],
    ['createTenantAgentDefinition', { input: mutation() }, { create: async () => ({}) }],
    ['updateTenantAgentDefinition', { definitionId: 'agent-1', input: mutation() },
      { update: async () => ({}) }],
    ['setTenantAgentDefinitionEnabled', { definitionId: 'agent-1', enabled: true },
      { setEnabled: async () => ({}) }],
    ['deleteTenantAgentDefinition', { definitionId: 'agent-1' },
      { delete: async () => ({ deleted: false, id: 'agent-1' }) }],
  ];
  for (const [operation, extra, override] of malformed) {
    const current = moduleV2.createDesktopTenantAgentDefinitionsOperationsV2(() =>
      actions(service(authority(override))),
    );
    await assert.rejects(
      () => current[operation]({ config: config(), scope: scope(), ...extra }),
      (error) => error.code === 'desktop_tenant_agent_definitions_operation_response_invalid',
      operation,
    );
  }
});

test('HMR pins old work, escaped use is revoked, and primary errors win', async () => {
  let finish;
  const capture = {};
  let current = actions(service(authority({
    load: () => new Promise((resolve) => { finish = resolve; }),
  })), [], undefined, capture);
  const operations = moduleV2.createDesktopTenantAgentDefinitionsOperationsV2(() => current);
  const pending = operations.loadTenantAgentDefinitions({ config: config(), scope: scope() });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(service(authority({ load: async () => [definition('new')] })));
  finish([definition('old')]);
  assert.equal((await pending)[0].id, 'old');
  assert.equal((await operations.loadTenantAgentDefinitions({ config: config(), scope: scope() }))[0].id, 'new');
  await assert.rejects(
    () => capture.use(service(authority())),
    (error) => error.code === 'desktop_tenant_agent_definitions_operation_released',
  );
  const primary = new Error('primary');
  await assert.rejects(
    () => moduleV2.createDesktopTenantAgentDefinitionsOperationsV2(() =>
      actions(service(authority({ load: async () => { throw primary; } })), [], new Error('release')),
    ).loadTenantAgentDefinitions({ config: config(), scope: scope() }),
    primary,
  );
  const release = new Error('release-only');
  await assert.rejects(
    () => moduleV2.createDesktopTenantAgentDefinitionsOperationsV2(() =>
      actions(service(authority()), [], release),
    ).loadTenantAgentDefinitions({ config: config(), scope: scope() }),
    release,
  );
});

test('Cloud transport uses exact routes once and vault transport hides credentials', async () => {
  const requests = [];
  const signal = new AbortController().signal;
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(String(input));
    requests.push({ url, init });
    return cloudResponse(url.pathname, init.method ?? 'GET');
  };
  const client = projectionV2.createDesktopTenantAgentDefinitionsHttpProjectionV2(config());
  await client.load(scope(), signal);
  await client.listExternal(scope('cloud', null), signal);
  await client.create(scope(), mutation(), signal);
  await client.update(scope(), 'agent-1', mutation(), 3, signal);
  await client.setEnabled(scope(), 'agent-1', false, 3, signal);
  await client.delete(scope(), 'agent-1', 3, signal);
  assert.deepEqual(requests.map(({ url, init }) => [url.pathname, init.method ?? 'GET']), [
    ['/api/v1/agent/definitions', 'GET'],
    ['/api/v1/acp/tenants/tenant-1/external-agents', 'GET'],
    ['/api/v1/agent/definitions', 'POST'],
    ['/api/v1/agent/definitions/agent-1', 'PUT'],
    ['/api/v1/agent/definitions/agent-1/enabled', 'PATCH'],
    ['/api/v1/agent/definitions/agent-1', 'DELETE'],
  ]);
  assert.equal(requests.every(({ init }) => init.signal === signal), true);
  assert.equal(requests.filter(({ init }) => init.method !== 'GET').length, 4);

  const calls = [];
  globalThis.window = { __MEMSTACK_DESKTOP__: { core: {
    async invoke(command, args) {
      calls.push({ command, request: args.request });
      const url = new URL(args.request.path, 'https://api.test');
      const response = cloudResponse(url.pathname, args.request.method ?? 'GET');
      return { status: response.status, body: await response.json() };
    },
  } } };
  globalThis.fetch = async () => { throw new Error('vault_bound_cloud_must_not_fetch'); };
  const vault = projectionV2.createDesktopTenantAgentDefinitionsHttpProjectionV2({
    ...config(), apiKey: '',
  });
  assert.equal((await vault.load(scope()))[0].id, 'agent-1');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].command, 'cloud_request');
  assert.equal(JSON.stringify(calls).includes('trusted-session'), false);
  assert.equal(JSON.stringify(calls).includes('Authorization'), false);
});

test('Local uses only authenticated sidecar and external catalog fails closed', async () => {
  const requests = [];
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(String(input));
    requests.push({ url, init });
    if (url.pathname.endsWith('/external-agents')) {
      return json({ reason_code: 'managed_read_unavailable' }, 501);
    }
    const response = cloudResponse(url.pathname, init.method ?? 'GET', 'local');
    return response;
  };
  const client = projectionV2.createDesktopTenantAgentDefinitionsHttpProjectionV2(config('local'));
  const localScope = scope('local');
  assert.equal((await client.load(localScope))[0].tenant_id, 'local');
  await client.create(localScope, mutation(), undefined);
  await client.update(localScope, 'agent-1', mutation(), 3);
  await client.setEnabled(localScope, 'agent-1', true, 3);
  await client.delete(localScope, 'agent-1', 3);
  await assert.rejects(
    () => client.listExternal(scope('local', null)),
    (error) => error.reasonCode === 'local_external_acp_registry_unavailable' && error.status === 501,
  );
  assert.equal(requests.length, 6);
  assert.equal(requests.every(({ url }) => url.origin === 'http://127.0.0.1:43117'), true);
  assert.equal(requests.every(({ init }) =>
    new Headers(init.headers).get('X-Agistack-Launch') === 'private-launch'), true);
  const mutationBodies = requests
    .filter(({ init }) => init.method && init.method !== 'GET')
    .map(({ init }) => JSON.parse(String(init.body)));
  assert.equal(mutationBodies.every((body) => body.contract_version === 2), true);
  assert.equal(mutationBodies.every((body) => Array.isArray(body.vault_refs)), true);
});

function cloudResponse(pathname, method, tenantId = 'tenant-1') {
  if (pathname.endsWith('/external-agents')) return json([external()]);
  if (pathname === '/api/v1/agent/definitions' && method === 'GET') {
    return json({ definitions: [definition('agent-1', 'project-1').tenant_id === tenantId
      ? definition()
      : { ...definition(), tenant_id: tenantId }] });
  }
  if (pathname === '/api/v1/agent/definitions' && method === 'POST') {
    return json({ ...definition(), tenant_id: tenantId });
  }
  if (pathname.endsWith('/enabled')) return json({ ...definition(), tenant_id: tenantId });
  if (pathname === '/api/v1/agent/definitions/agent-1' && method === 'PUT') {
    return json({ ...definition(), tenant_id: tenantId });
  }
  if (pathname === '/api/v1/agent/definitions/agent-1' && method === 'DELETE') {
    return json({ deleted: true, id: 'agent-1' });
  }
  throw new Error(`unexpected request ${method} ${pathname}`);
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
