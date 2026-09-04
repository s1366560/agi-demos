import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const runtime = require('@agistack/plugin-runtime');
const moduleV2 = require(`${ROOT}/src/plugins/desktopTenantTemplatesAuthorityModuleV2.js`);
const projectionV2 = require(`${ROOT}/src/plugins/desktopTenantTemplatesHttpProjectionV2.js`);
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
const scope = (authority = 'cloud') => ({
  authority,
  tenantId: authority === 'cloud' ? 'tenant-1' : 'local',
});
const query = Object.freeze({ page: 1, pageSize: 12, category: '', search: '' });
const allowedActions = Object.freeze([
  'view', 'list', 'search', 'filter', 'view-detail', 'install', 'seed', 'retry',
]);
const template = (id = 'template-1', tenantId = 'tenant-1') => ({
  id,
  tenant_id: tenantId,
  name: 'release-reviewer',
  version: '1.0.0',
  display_name: 'Release reviewer',
  description: 'Reviews release evidence.',
  category: 'engineering',
  tags: ['release'],
  system_prompt: 'Review the release.',
  trigger_description: 'Use for release review.',
  trigger_keywords: ['release'],
  trigger_examples: [],
  model: 'inherit',
  max_tokens: 4096,
  temperature: 0.4,
  max_iterations: 10,
  allowed_tools: ['run_tests'],
  author: 'MemStack',
  is_builtin: true,
  is_published: true,
  install_count: 4,
  rating: 4.8,
  metadata: null,
  created_at: null,
  updated_at: null,
});
const installed = (tenantId = 'tenant-1') => ({
  id: 'subagent-release-reviewer',
  tenant_id: tenantId,
  project_id: 'project-1',
  name: 'release-reviewer',
  enabled: true,
  source: 'database',
});
const snapshot = (id = 'template-1') => ({
  scope: scope(),
  authority: 'cloud',
  availability: 'available',
  reasonCode: null,
  allowedActions,
  itemCount: 1,
  templates: [template(id)],
  categories: ['engineering'],
  total: 1,
  page: 1,
  pageSize: 12,
});
const authority = (overrides = {}) => Object.freeze({
  async load() { return snapshot(); },
  async get() { return template(); },
  async install() { return installed(); },
  async seed() { return 2; },
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
    (item) => item.module_ref === moduleV2.DESKTOP_TENANT_TEMPLATES_AUTHORITY_MODULE_REF_V2,
  );
  assert.equal(moduleV2.desktopTenantTemplatesAuthorityDefinitionV2.contractDigest, entry.contract_digest);
  assert.deepEqual(entry.contract.services.provides, [{
    service: moduleV2.DESKTOP_TENANT_TEMPLATES_AUTHORITY_SERVICE_V2,
    version: '1.0.0',
  }]);
  const provided = {};
  moduleV2.applyDesktopTenantTemplatesAuthorityV2({
    provide(key, value) { provided.key = key; provided.value = value; },
  }, { strategy: 'desktop-api-fetch' });
  assert.equal(provided.key, moduleV2.DESKTOP_TENANT_TEMPLATES_AUTHORITY_SERVICE_V2);
  assert.deepEqual(Object.keys(provided.value), ['bindOperation']);
  assert.throws(
    () => moduleV2.applyDesktopTenantTemplatesAuthorityV2(
      { provide() {} },
      { strategy: 'desktop-api-fetch', fallback: true },
    ),
    (error) => error.code === 'desktop_tenant_templates_authority_config_invalid',
  );

  const bootstrap = JSON.parse(readFileSync(bootstrapPath, 'utf8'));
  const loader = new runtime.LoaderV2(
    [...runtime.createDesktopRendererDefinitionsV2(), ...authorityModules],
    'desktop-renderer',
  );
  const generation = await loader.stage(bootstrap);
  assert.ok(generation.resolve(
    moduleV2.DESKTOP_TENANT_TEMPLATES_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: '1.0.0' },
  ));
  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    (item) => item.entry_id === 'builtin-desktop-tenant-templates-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () => disabledGeneration.resolve(
      moduleV2.DESKTOP_TENANT_TEMPLATES_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: '1.0.0' },
    ),
    (error) => error.code === 'missing_service',
  );
  await disabledGeneration.dispose();
  await generation.dispose();
});

test('four operations hold exact tenant leases and freeze operation inputs', async () => {
  const lifecycle = [];
  const captured = {};
  const serviceCapture = {};
  const signal = new AbortController().signal;
  const operations = moduleV2.createDesktopTenantTemplatesOperationsV2(() =>
    actions(service(authority({
      async load(currentScope, currentQuery, currentSignal) {
        captured.scope = currentScope;
        captured.query = currentQuery;
        captured.signal = currentSignal;
        return snapshot();
      },
      async get(_scope, templateId) { captured.getId = templateId; return template(); },
      async install(_scope, templateId) { captured.installId = templateId; return installed(); },
    }), serviceCapture), lifecycle),
  );
  await operations.loadTenantTemplates({
    config: config(), scope: scope(), query: { page: 1, pageSize: 12 }, signal,
  });
  await operations.getTenantTemplate({ config: config(), scope: scope(), templateId: 'template-1' });
  await operations.installTenantTemplate({ config: config(), scope: scope(), templateId: 'template-1' });
  await operations.seedTenantTemplates({ config: config(), scope: scope() });
  const acquisitions = lifecycle.filter(([kind]) => kind === 'acquire').map(([, value]) => value);
  assert.equal(acquisitions.length, 4);
  assert.equal(lifecycle.filter(([kind]) => kind === 'release').length, 4);
  assert.equal(acquisitions.every((value) =>
    value.service === moduleV2.DESKTOP_TENANT_TEMPLATES_AUTHORITY_SERVICE_V2 &&
    value.version === '1.0.0' && value.scope.kind === 'tenant' &&
    value.scope.tenant_id === 'tenant-1'), true);
  assert.equal(captured.signal, signal);
  assert.equal(captured.getId, 'template-1');
  assert.equal(captured.installId, 'template-1');
  assert.equal(Object.isFrozen(captured.scope), true);
  assert.equal(Object.isFrozen(captured.query), true);
  assert.equal(Object.isFrozen(serviceCapture.config), true);
  assert.equal(Object.isFrozen(serviceCapture.scope), true);
});

test('input, service, authority and response drift fail closed', async () => {
  let acquisitions = 0;
  const rejected = moduleV2.createDesktopTenantTemplatesOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      return { status: 'rejected', reasonCode: 'missing_service_provider' };
    },
  }));
  assert.throws(
    () => rejected.loadTenantTemplates({ config: config(), scope: scope(), extra: true }),
    (error) => error.code === 'desktop_tenant_templates_operation_input_invalid',
  );
  assert.equal(acquisitions, 0);
  await assert.rejects(
    () => rejected.loadTenantTemplates({ config: config(), scope: scope() }),
    (error) => error.reasonCode === 'missing_service_provider',
  );
  await assert.rejects(
    () => moduleV2.createDesktopTenantTemplatesOperationsV2(() => null)
      .loadTenantTemplates({ config: config(), scope: scope() }),
    (error) => error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
  const malformedService = moduleV2.createDesktopTenantTemplatesOperationsV2(() =>
    actions(Object.freeze({ bindOperation() { return authority(); }, extra: true })),
  );
  await assert.rejects(
    () => malformedService.loadTenantTemplates({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_templates_service_invalid',
  );
  const malformedAuthority = moduleV2.createDesktopTenantTemplatesOperationsV2(() =>
    actions(service(Object.freeze({ ...authority(), extra: true }))),
  );
  await assert.rejects(
    () => malformedAuthority.loadTenantTemplates({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_templates_service_invalid',
  );
  const cases = [
    ['loadTenantTemplates', {}, { load: async () => ({ ...snapshot(), allowedActions: [] }) }],
    ['getTenantTemplate', { templateId: 'template-1' }, { get: async () => ({ ...template(), extra: true }) }],
    ['installTenantTemplate', { templateId: 'template-1' }, { install: async () => installed('other') }],
    ['seedTenantTemplates', {}, { seed: async () => -1 }],
  ];
  for (const [operation, extra, override] of cases) {
    const current = moduleV2.createDesktopTenantTemplatesOperationsV2(() =>
      actions(service(authority(override))),
    );
    await assert.rejects(
      () => current[operation]({ config: config(), scope: scope(), ...extra }),
      (error) => error.code === 'desktop_tenant_templates_operation_response_invalid',
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
  const operations = moduleV2.createDesktopTenantTemplatesOperationsV2(() => current);
  const pending = operations.loadTenantTemplates({ config: config(), scope: scope() });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(service(authority({ load: async () => snapshot('new') })));
  finish(snapshot('old'));
  assert.equal((await pending).templates[0].id, 'old');
  assert.equal((await operations.loadTenantTemplates({
    config: config(), scope: scope(),
  })).templates[0].id, 'new');
  await assert.rejects(
    () => capture.use(service(authority())),
    (error) => error.code === 'desktop_tenant_templates_operation_released',
  );
  const primary = new Error('primary');
  const primaryFailing = moduleV2.createDesktopTenantTemplatesOperationsV2(() =>
    actions(service(authority({ load: async () => { throw primary; } })), [], new Error('release')),
  );
  await assert.rejects(
    () => primaryFailing.loadTenantTemplates({ config: config(), scope: scope() }),
    primary,
  );
  const release = new Error('release-only');
  const releaseFailing = moduleV2.createDesktopTenantTemplatesOperationsV2(() =>
    actions(service(authority()), [], release),
  );
  await assert.rejects(
    () => releaseFailing.loadTenantTemplates({ config: config(), scope: scope() }),
    release,
  );
});

test('Cloud transport uses exact routes once and vault transport hides credentials', async () => {
  const requests = [];
  const signal = new AbortController().signal;
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(String(input));
    requests.push({ url, init });
    return cloudResponse(url.pathname);
  };
  const client = projectionV2.createDesktopTenantTemplatesHttpProjectionV2(config());
  await client.load(scope(), query, signal);
  await client.get(scope(), 'template-1', signal);
  await client.install(scope(), 'template-1', signal);
  await client.seed(scope(), signal);
  assert.deepEqual(requests.map(({ url, init }) => [url.pathname, init.method ?? 'GET']), [
    ['/api/v1/subagents/templates/list', 'GET'],
    ['/api/v1/subagents/templates/categories', 'GET'],
    ['/api/v1/subagents/templates/template-1', 'GET'],
    ['/api/v1/subagents/templates/template-1/install', 'POST'],
    ['/api/v1/subagents/templates/seed', 'POST'],
  ]);
  assert.equal(requests.every(({ init }) => init.signal === signal), true);
  assert.equal(requests.filter(({ init }) => init.method === 'POST').length, 2);

  const calls = [];
  globalThis.window = { __MEMSTACK_DESKTOP__: { core: {
    async invoke(command, args) {
      calls.push({ command, request: args.request });
      const response = cloudResponse(new URL(args.request.path, 'https://api.test').pathname);
      return { status: response.status, body: await response.json() };
    },
  } } };
  globalThis.fetch = async () => { throw new Error('vault_bound_cloud_must_not_fetch'); };
  const vaultClient = projectionV2.createDesktopTenantTemplatesHttpProjectionV2({
    ...config(), apiKey: '',
  });
  assert.equal((await vaultClient.load(scope(), query)).itemCount, 1);
  assert.equal(calls.length, 2);
  assert.equal(calls.every(({ command }) => command === 'cloud_request'), true);
  assert.equal(JSON.stringify(calls).includes('trusted-session'), false);
  assert.equal(JSON.stringify(calls).includes('Authorization'), false);
});

test('Local operations stay on authenticated sidecar and normalize 404 and 501', async () => {
  const calls = [];
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(String(input));
    calls.push({ url, init });
    const status = calls.length % 2 === 0 ? 501 : 404;
    return json({ reason_code: `sidecar_${status}` }, status);
  };
  const client = projectionV2.createDesktopTenantTemplatesHttpProjectionV2(config('local'));
  const localScope = scope('local');
  for (const operation of [
    () => client.load(localScope, query),
    () => client.get(localScope, 'template-1'),
    () => client.install(localScope, 'template-1'),
    () => client.seed(localScope),
  ]) {
    await assert.rejects(operation, (error) =>
      error.reasonCode === 'local_subagent_registry_unavailable' &&
      (error.status === 404 || error.status === 501));
  }
  assert.equal(calls.length, 4);
  assert.equal(calls.every(({ url }) => url.origin === 'http://127.0.0.1:43117'), true);
  assert.equal(calls.every(({ init }) =>
    new Headers(init.headers).get('X-Agistack-Launch') === 'private-launch'), true);
});

function cloudResponse(pathname) {
  if (pathname === '/api/v1/subagents/templates/list') {
    return json({ templates: [template()], total: 1 });
  }
  if (pathname === '/api/v1/subagents/templates/categories') {
    return json({ categories: ['engineering'] });
  }
  if (pathname === '/api/v1/subagents/templates/template-1') return json(template());
  if (pathname === '/api/v1/subagents/templates/template-1/install') return json(installed());
  if (pathname === '/api/v1/subagents/templates/seed') return json({ created: 2 });
  throw new Error(`unexpected request ${pathname}`);
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
