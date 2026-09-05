import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const moduleV2 = require(`${ROOT}/src/plugins/desktopTenantPromptTemplatesAuthorityModuleV2.js`);
const projectionV2 = require(`${ROOT}/src/plugins/desktopTenantPromptTemplatesHttpProjectionV2.js`);
const runtime = require('@agistack/plugin-runtime');
const authorityModules = readdirSync(`${ROOT}/src/plugins`)
  .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
  .flatMap((name) =>
    Object.values(require(`${ROOT}/src/plugins/${name}`)).filter(
      (value) => value?.moduleRef && typeof value?.apply === 'function',
    ),
  );
const bootstrapPath = new URL(
  '../../../../shared/profiles/memstack-default-bootstrap.v2.json',
  import.meta.url,
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const managedClientSource = readFileSync(
  new URL('../src/api/managedResourcesClient.ts', import.meta.url),
  'utf8',
);
const apiClientSource = readFileSync(new URL('../src/api/client.ts', import.meta.url), 'utf8');
const generationSource = readFileSync(
  new URL('../src/plugins/useDesktopPluginGenerationV2.ts', import.meta.url),
  'utf8',
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
const createInput = () => ({ title: 'Release', content: 'Review this.', category: 'code' });
const template = (tenantId = 'tenant-1') => ({
  id: 'template-1', revision: 2, tenant_id: tenantId, project_id: null,
  created_by: 'user-1', title: 'Release', content: 'Review this.', category: 'code',
  variables: [], is_system: false, usage_count: 0,
  created_at: '2026-09-05T00:00:00Z', updated_at: '2026-09-05T00:00:00Z',
});
const authority = (overrides = {}) => Object.freeze({
  async list() { return [template()]; },
  async create() { return template(); },
  async delete() {},
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
      useService(use) { capture.use = use; return use(value); },
      async release() { lifecycle.push(['release']); if (releaseError) throw releaseError; },
    };
  },
});

test('saving a message normalizes draft whitespace before the authority call', async () => {
  let received;
  const operations = moduleV2.createDesktopTenantPromptTemplatesOperationsV2(() =>
    actions(service(authority({
      async create(_scope, input) {
        received = input;
        return template();
      },
    }))),
  );
  await operations.createTenantPromptTemplate({
    config: config(), scope: scope(),
    input: { title: ' Release ', content: '\nReview this.\n', category: ' code ' },
  });
  assert.deepEqual(received, createInput());
  assert.throws(() => operations.createTenantPromptTemplate({
    config: config(), scope: scope(),
    input: { ...createInput(), content: ' \n ' },
  }), (error) => error.code === 'desktop_tenant_prompt_templates_operation_input_invalid');
});

test('catalog, apply and Profile register one exact root Provider', async () => {
  const entry = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === moduleV2.DESKTOP_TENANT_PROMPT_TEMPLATES_AUTHORITY_MODULE_REF_V2,
  );
  assert.equal(moduleV2.desktopTenantPromptTemplatesAuthorityDefinitionV2.contractDigest, entry.contract_digest);
  assert.deepEqual(entry.contract.services.provides, [{
    service: moduleV2.DESKTOP_TENANT_PROMPT_TEMPLATES_AUTHORITY_SERVICE_V2,
    version: '1.0.0',
  }]);
  const provided = {};
  moduleV2.applyDesktopTenantPromptTemplatesAuthorityV2({
    provide(key, value) { provided.key = key; provided.value = value; },
  }, { strategy: 'desktop-api-fetch' });
  assert.equal(provided.key, moduleV2.DESKTOP_TENANT_PROMPT_TEMPLATES_AUTHORITY_SERVICE_V2);
  assert.deepEqual(Object.keys(provided.value), ['bindOperation']);
  assert.throws(
    () => moduleV2.applyDesktopTenantPromptTemplatesAuthorityV2(
      { provide() {} },
      { strategy: 'desktop-api-fetch', fallback: true },
    ),
    (error) => error.code === 'desktop_tenant_prompt_templates_authority_config_invalid',
  );
  const bootstrap = JSON.parse(readFileSync(bootstrapPath, 'utf8'));
  const loader = new runtime.LoaderV2(
    [...runtime.createDesktopRendererDefinitionsV2(), ...authorityModules],
    'desktop-renderer',
  );
  const generation = await loader.stage(bootstrap);
  assert.ok(generation.resolve(
    moduleV2.DESKTOP_TENANT_PROMPT_TEMPLATES_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: '1.0.0' },
  ));
  await generation.dispose();
});

test('production composer paths require V2 operations with no static client authority', () => {
  assert.match(appSource, /createDesktopTenantPromptTemplatesOperationsV2\(/u);
  assert.match(appSource, /createDesktopTenantPromptTemplatesClientV2\(/u);
  assert.match(appSource, /tenantPromptTemplatesOperationsV2:\s*desktopTenantPromptTemplatesOperationsV2/u);
  assert.match(generationSource, /desktopTenantPromptTemplatesAuthorityDefinitionV2/u);
  for (const source of [managedClientSource, apiClientSource]) {
    assert.doesNotMatch(source, /async (?:list|create|delete)PromptTemplate\(/u);
  }
  assert.doesNotMatch(appSource, /remainingComposerCatalogAuthority\.(?:list|create|delete)PromptTemplate/u);
});

test('three operations use tenant leases and freeze input without replacing signal', async () => {
  const lifecycle = [];
  const captured = {};
  const serviceCapture = {};
  const signal = new AbortController().signal;
  const operations = moduleV2.createDesktopTenantPromptTemplatesOperationsV2(() =>
    actions(service(authority({
      async list(currentScope, currentSignal) {
        captured.scope = currentScope; captured.signal = currentSignal; return [template()];
      },
      async create(_scope, input) { captured.input = input; return template(); },
      async delete(_scope, id, revision) { captured.id = id; captured.revision = revision; },
    }), serviceCapture), lifecycle),
  );
  await operations.listTenantPromptTemplates({ config: config(), scope: scope(), signal });
  await operations.createTenantPromptTemplate({ config: config(), scope: scope(), input: createInput(), signal });
  await operations.deleteTenantPromptTemplate({ config: config(), scope: scope(), templateId: 'template-1', expectedRevision: 2, signal });
  assert.equal(lifecycle.filter(([kind]) => kind === 'acquire').length, 3);
  assert.equal(lifecycle.filter(([kind]) => kind === 'release').length, 3);
  assert.equal(lifecycle.filter(([kind]) => kind === 'acquire').every(([, value]) =>
    value.service === moduleV2.DESKTOP_TENANT_PROMPT_TEMPLATES_AUTHORITY_SERVICE_V2 &&
    value.version === '1.0.0' && value.scope.kind === 'tenant' && value.scope.tenant_id === 'tenant-1'), true);
  assert.equal(captured.signal, signal);
  assert.equal(captured.id, 'template-1');
  assert.equal(captured.revision, 2);
  assert.equal(Object.isFrozen(captured.scope), true);
  assert.equal(Object.isFrozen(captured.input), true);
  assert.equal(Object.isFrozen(serviceCapture.config), true);
  assert.equal(Object.isFrozen(serviceCapture.scope), true);
});

test('cloud workspace_context_unavailable config can bind without acquiring an empty tenant lease', async () => {
  // hydrateCloudSession clears all scope fields after the supported context-unavailable 404.
  const unavailableContextConfig = {
    ...config('cloud'), tenantId: '', projectId: '', workspaceId: '',
  };
  let acquisitions = 0;
  const operations = moduleV2.createDesktopTenantPromptTemplatesOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      return { status: 'rejected', reasonCode: 'missing_service_provider' };
    },
  }));
  const client = moduleV2.createDesktopTenantPromptTemplatesClientV2(
    operations, unavailableContextConfig,
  );
  assert.equal(acquisitions, 0);
  await assert.rejects(
    () => client.listPromptTemplates(''),
    (error) => error.code === 'desktop_tenant_prompt_templates_operation_input_invalid',
  );
  assert.equal(acquisitions, 0);
});

test('input, service, authority and response drift fail closed', async () => {
  let acquisitions = 0;
  const rejected = moduleV2.createDesktopTenantPromptTemplatesOperationsV2(() => ({
    async acquireServiceOperationLease() { acquisitions += 1; return { status: 'rejected', reasonCode: 'missing_service_provider' }; },
  }));
  assert.throws(
    () => rejected.listTenantPromptTemplates({ config: config(), scope: scope(), extra: true }),
    (error) => error.code === 'desktop_tenant_prompt_templates_operation_input_invalid',
  );
  assert.equal(acquisitions, 0);
  await assert.rejects(
    () => rejected.listTenantPromptTemplates({ config: config(), scope: scope() }),
    (error) => error.reasonCode === 'missing_service_provider',
  );
  await assert.rejects(
    () => moduleV2.createDesktopTenantPromptTemplatesOperationsV2(() => actions(Object.freeze({ bindOperation() { return authority(); }, extra: true })))
      .listTenantPromptTemplates({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_prompt_templates_service_invalid',
  );
  await assert.rejects(
    () => moduleV2.createDesktopTenantPromptTemplatesOperationsV2(() => actions(service(Object.freeze({ ...authority(), extra: true }))))
      .listTenantPromptTemplates({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_prompt_templates_service_invalid',
  );
  await assert.rejects(
    () => moduleV2.createDesktopTenantPromptTemplatesOperationsV2(() => actions(service(authority({ list: async () => [{ ...template(), tenant_id: 'other' }] }))))
      .listTenantPromptTemplates({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_prompt_templates_operation_response_invalid',
  );
});

test('HMR pins old work, escaped use is revoked, and primary errors win', async () => {
  let finish;
  const capture = {};
  let current = actions(service(authority({ list: () => new Promise((resolve) => { finish = resolve; }) })), [], undefined, capture);
  const operations = moduleV2.createDesktopTenantPromptTemplatesOperationsV2(() => current);
  const pending = operations.listTenantPromptTemplates({ config: config(), scope: scope() });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(service(authority({ list: async () => [{ ...template(), id: 'new' }] })));
  finish([{ ...template(), id: 'old' }]);
  assert.equal((await pending)[0].id, 'old');
  assert.equal((await operations.listTenantPromptTemplates({ config: config(), scope: scope() }))[0].id, 'new');
  await assert.rejects(
    () => capture.use(service(authority())),
    (error) => error.code === 'desktop_tenant_prompt_templates_operation_released',
  );
  const primary = new Error('primary');
  await assert.rejects(
    () => moduleV2.createDesktopTenantPromptTemplatesOperationsV2(() => actions(service(authority({ list: async () => { throw primary; } })), [], new Error('release')))
      .listTenantPromptTemplates({ config: config(), scope: scope() }), primary,
  );
  const release = new Error('release-only');
  await assert.rejects(
    () => moduleV2.createDesktopTenantPromptTemplatesOperationsV2(() =>
      actions(service(authority()), [], release))
      .listTenantPromptTemplates({ config: config(), scope: scope() }),
    release,
  );
});

test('Cloud uses vault-bound routes and Local stays on authenticated sidecar', async () => {
  const requests = [];
  const signal = new AbortController().signal;
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(String(input)); requests.push({ url, init });
    if (url.pathname.endsWith('/template-1') && init.method === 'DELETE') return new Response(null, { status: 204 });
    if (init.method === 'POST') return json(template(url.hostname === '127.0.0.1' ? 'local' : 'tenant-1'));
    return json([template(url.hostname === '127.0.0.1' ? 'local' : 'tenant-1')]);
  };
  const cloud = projectionV2.createDesktopTenantPromptTemplatesHttpProjectionV2(config());
  await cloud.list(scope(), signal);
  await cloud.create(scope(), createInput(), signal);
  await cloud.delete(scope(), 'template-1', 2, signal);
  assert.equal(requests.every(({ init }) => init.signal === signal), true);
  assert.deepEqual(requests.map(({ url, init }) => [url.pathname, init.method ?? 'GET']), [
    ['/api/v1/agent/templates', 'GET'], ['/api/v1/agent/templates', 'POST'], ['/api/v1/agent/templates/template-1', 'DELETE'],
  ]);
  const calls = [];
  globalThis.window = { __MEMSTACK_DESKTOP__: { core: { async invoke(command, args) {
    calls.push({ command, request: args.request }); return { status: 200, body: [template()] };
  } } } };
  globalThis.fetch = async () => { throw new Error('vault_bound_cloud_must_not_fetch'); };
  assert.equal((await projectionV2.createDesktopTenantPromptTemplatesHttpProjectionV2({ ...config(), apiKey: '' }).list(scope())).length, 1);
  assert.equal(JSON.stringify(calls).includes('trusted-session'), false);

  globalThis.window = originalWindow;
  const localRequests = [];
  globalThis.fetch = async (input, init = {}) => {
    localRequests.push({ input: String(input), init });
    return json({ reason_code: 'not_implemented' }, 501);
  };
  const local = projectionV2.createDesktopTenantPromptTemplatesHttpProjectionV2(config('local'));
  await assert.rejects(() => local.list(scope('local')), (error) =>
    error.reasonCode === 'local_prompt_template_authority_unavailable' && error.status === 501);
  assert.equal(localRequests.length, 1);
  assert.equal(new URL(localRequests[0].input).origin, 'http://127.0.0.1:43117');
  assert.equal(new Headers(localRequests[0].init.headers).get('X-Agistack-Launch'), 'private-launch');
});

function json(payload, status = 200) {
  return new Response(status === 204 ? null : JSON.stringify(payload), {
    status, headers: { 'content-type': 'application/json' },
  });
}
