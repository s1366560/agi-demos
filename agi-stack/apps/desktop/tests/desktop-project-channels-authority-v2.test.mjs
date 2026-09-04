import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const moduleV2 = require(`${ROOT}/src/plugins/desktopProjectChannelsAuthorityModuleV2.js`);
const projectionV2 = require(`${ROOT}/src/plugins/desktopProjectChannelsHttpProjectionV2.js`);
const runtime = require('@agistack/plugin-runtime');
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
  projectId: 'project-1',
});
const catalogItem = () => ({
  channel_type: 'slack', plugin_name: 'slack', source: 'entrypoint',
  package: 'memstack-slack', version: '1.0.0', enabled: true, discovered: true,
  schema_supported: true,
});
const schema = () => ({
  channel_type: 'slack', plugin_name: 'slack', source: 'entrypoint',
  schema_supported: true,
  config_schema: { type: 'object', properties: { token: { type: 'string' } }, required: ['token'] },
  config_ui_hints: { token: { sensitive: true } }, defaults: {}, secret_paths: ['token'],
});
const channelConfig = (overrides = {}) => ({
  id: 'channel-1', project_id: 'project-1', channel_type: 'slack', name: 'Alerts',
  enabled: true, connection_mode: 'websocket', dm_policy: 'open', group_policy: 'open',
  rate_limit_per_minute: 60, status: 'connected', created_at: '2026-09-05T00:00:00Z',
  ...overrides,
});
const actionsList = Object.freeze([
  'view', 'view-channel-catalog', 'view-channel-schema', 'list-channel-configs',
  'create-channel-config', 'update-channel-config', 'delete-channel-config',
  'test-channel-config',
]);
const snapshot = (id = 'channel-1') => ({
  scope: scope(), authority: 'cloud', availability: 'available', reasonCode: null,
  allowedActions: actionsList, itemCount: 1, catalog: [catalogItem()],
  configs: [channelConfig({ id })],
});
const authority = (overrides = {}) => Object.freeze({
  async load() { return snapshot(); },
  async schema() { return schema(); },
  async create() { return channelConfig({ id: 'channel-2' }); },
  async update() { return channelConfig({ enabled: false }); },
  async test() { return { success: true, message: 'ok' }; },
  async remove() {},
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

test('catalog, apply and Profile register the exact root Provider', async () => {
  const entry = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === moduleV2.DESKTOP_PROJECT_CHANNELS_AUTHORITY_MODULE_REF_V2,
  );
  assert.equal(moduleV2.desktopProjectChannelsAuthorityDefinitionV2.contractDigest, entry.contract_digest);
  assert.deepEqual(entry.contract.services.provides, [{
    service: moduleV2.DESKTOP_PROJECT_CHANNELS_AUTHORITY_SERVICE_V2,
    version: '1.0.0',
  }]);
  const provided = {};
  moduleV2.applyDesktopProjectChannelsAuthorityV2({
    provide(key, value) { provided.key = key; provided.value = value; },
  }, { strategy: 'desktop-api-fetch' });
  assert.equal(provided.key, moduleV2.DESKTOP_PROJECT_CHANNELS_AUTHORITY_SERVICE_V2);
  assert.deepEqual(Object.keys(provided.value), ['bindOperation']);
  assert.throws(
    () => moduleV2.applyDesktopProjectChannelsAuthorityV2(
      { provide() {} },
      { strategy: 'desktop-api-fetch', fallback: true },
    ),
    (error) => error.code === 'desktop_project_channels_authority_config_invalid',
  );

  const bootstrap = JSON.parse(readFileSync(bootstrapPath, 'utf8'));
  const loader = new runtime.LoaderV2(
    [...runtime.createDesktopRendererDefinitionsV2(), ...authorityModules],
    'desktop-renderer',
  );
  const generation = await loader.stage(bootstrap);
  assert.ok(generation.resolve(
    moduleV2.DESKTOP_PROJECT_CHANNELS_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: '1.0.0' },
  ));
  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    (item) => item.entry_id === 'builtin-desktop-project-channels-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () => disabledGeneration.resolve(
      moduleV2.DESKTOP_PROJECT_CHANNELS_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: '1.0.0' },
    ),
    (error) => error.code === 'missing_service',
  );
  await disabledGeneration.dispose();
  await generation.dispose();
});

test('six operations acquire exact project leases and freeze inputs', async () => {
  const lifecycle = [];
  const capture = {};
  const signal = new AbortController().signal;
  const operations = moduleV2.createDesktopProjectChannelsOperationsV2(() =>
    actions(service(authority({
      async load(currentScope, currentSignal) {
        capture.scope = currentScope; capture.signal = currentSignal; return snapshot();
      },
      async schema(_scope, channelType) { capture.channelType = channelType; return schema(); },
      async create(_scope, input) { capture.create = input; return channelConfig({ id: 'channel-2' }); },
      async update(_scope, id, input) { capture.updateId = id; capture.update = input; return channelConfig({ enabled: false }); },
      async test(_scope, id) { capture.testId = id; return { success: true, message: 'ok' }; },
      async remove(_scope, id) { capture.removeId = id; },
    }), capture), lifecycle),
  );
  await operations.loadProjectChannels({ config: config(), scope: scope(), signal });
  await operations.getProjectChannelSchema({ config: config(), scope: scope(), channelType: 'slack' });
  await operations.createProjectChannelConfig({ config: config(), scope: scope(), input: { channel_type: 'slack', name: 'Alerts' } });
  await operations.updateProjectChannelConfig({ config: config(), scope: scope(), configId: 'channel-1', input: { enabled: false } });
  await operations.testProjectChannelConfig({ config: config(), scope: scope(), configId: 'channel-1' });
  await operations.removeProjectChannelConfig({ config: config(), scope: scope(), configId: 'channel-1' });
  const acquisitions = lifecycle.filter(([kind]) => kind === 'acquire').map(([, value]) => value);
  assert.equal(acquisitions.length, 6);
  assert.equal(lifecycle.filter(([kind]) => kind === 'release').length, 6);
  assert.equal(acquisitions.every(({ service: key, version, scope: leaseScope }) =>
    key === moduleV2.DESKTOP_PROJECT_CHANNELS_AUTHORITY_SERVICE_V2 && version === '1.0.0' &&
    leaseScope.kind === 'project' && leaseScope.tenant_id === 'tenant-1' &&
    leaseScope.project_id === 'project-1'), true);
  assert.equal(capture.signal, signal);
  assert.equal(Object.isFrozen(capture.config), true);
  assert.equal(Object.isFrozen(capture.scope), true);
  assert.equal(Object.isFrozen(capture.create), true);
  assert.equal(Object.isFrozen(capture.update), true);
  assert.equal(capture.channelType, 'slack');
  assert.equal(capture.updateId, 'channel-1');
  assert.equal(capture.testId, 'channel-1');
  assert.equal(capture.removeId, 'channel-1');
});

test('service, authority, input and response drift fail closed', async () => {
  let acquisitions = 0;
  const rejected = moduleV2.createDesktopProjectChannelsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      return { status: 'rejected', reasonCode: 'missing_service_provider' };
    },
  }));
  assert.throws(
    () => rejected.loadProjectChannels({ config: config(), scope: scope(), extra: true }),
    (error) => error.code === 'desktop_project_channels_operation_input_invalid',
  );
  assert.equal(acquisitions, 0);
  await assert.rejects(
    () => rejected.loadProjectChannels({ config: config(), scope: scope() }),
    (error) => error.reasonCode === 'missing_service_provider',
  );
  await assert.rejects(
    () => moduleV2.createDesktopProjectChannelsOperationsV2(() => null)
      .loadProjectChannels({ config: config(), scope: scope() }),
    (error) => error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
  const malformedService = moduleV2.createDesktopProjectChannelsOperationsV2(() =>
    actions(Object.freeze({ bindOperation() { return authority(); }, extra: true })),
  );
  await assert.rejects(
    () => malformedService.loadProjectChannels({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_project_channels_service_invalid',
  );
  const malformedAuthority = moduleV2.createDesktopProjectChannelsOperationsV2(() =>
    actions(service(Object.freeze({ ...authority(), extra: true }))),
  );
  await assert.rejects(
    () => malformedAuthority.loadProjectChannels({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_project_channels_service_invalid',
  );
  const badResponse = moduleV2.createDesktopProjectChannelsOperationsV2(() =>
    actions(service(authority({ load: async () => ({ ...snapshot(), allowedActions: [] }) }))),
  );
  await assert.rejects(
    () => badResponse.loadProjectChannels({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_project_channels_operation_response_invalid',
  );
});

test('HMR pins old work, escaped authority revokes, and primary errors outrank release', async () => {
  let finish;
  const capture = {};
  let current = actions(service(authority({
    load: () => new Promise((resolve) => { finish = resolve; }),
  })), [], undefined, capture);
  const operations = moduleV2.createDesktopProjectChannelsOperationsV2(() => current);
  const pending = operations.loadProjectChannels({ config: config(), scope: scope() });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(service(authority({ load: async () => snapshot('new') })));
  finish(snapshot('old'));
  assert.equal((await pending).configs[0].id, 'old');
  assert.equal((await operations.loadProjectChannels({ config: config(), scope: scope() })).configs[0].id, 'new');
  await assert.rejects(
    () => capture.use(service(authority())),
    (error) => error.code === 'desktop_project_channels_operation_released',
  );
  const primary = new Error('primary');
  const primaryFailing = moduleV2.createDesktopProjectChannelsOperationsV2(() =>
    actions(service(authority({ load: async () => { throw primary; } })), [], new Error('release')),
  );
  await assert.rejects(
    () => primaryFailing.loadProjectChannels({ config: config(), scope: scope() }), primary,
  );
});

test('Cloud routes use one load authority and mutations once; vault transport hides credentials', async () => {
  const requests = [];
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(String(input));
    requests.push({ url, init });
    return responseFor(url.pathname, init.method ?? 'GET');
  };
  const client = projectionV2.createDesktopProjectChannelsHttpProjectionV2(config());
  const signal = new AbortController().signal;
  await client.load(scope(), signal);
  await client.schema(scope(), 'slack', signal);
  await client.create(scope(), { channel_type: 'slack', name: 'Alerts' }, signal);
  await client.update(scope(), 'channel-1', { enabled: false }, signal);
  await client.test(scope(), 'channel-1', signal);
  await client.remove(scope(), 'channel-1', signal);
  assert.deepEqual(requests.map(({ url, init }) => [url.pathname, init.method ?? 'GET']), [
    ['/api/v1/channels/tenants/tenant-1/plugins/channel-catalog', 'GET'],
    ['/api/v1/channels/projects/project-1/configs', 'GET'],
    ['/api/v1/channels/tenants/tenant-1/plugins/channel-catalog/slack/schema', 'GET'],
    ['/api/v1/channels/projects/project-1/configs', 'POST'],
    ['/api/v1/channels/configs/channel-1', 'PUT'],
    ['/api/v1/channels/configs/channel-1/test', 'POST'],
    ['/api/v1/channels/configs/channel-1', 'DELETE'],
  ]);
  assert.equal(requests.every(({ init }) => init.signal === signal), true);

  const calls = [];
  globalThis.window = { __MEMSTACK_DESKTOP__: { core: {
    async invoke(command, args) {
      calls.push({ command, request: args.request });
      const response = responseFor(new URL(args.request.path, 'https://api.test').pathname, args.request.method ?? 'GET');
      return { status: response.status, body: response.status === 204 ? null : await response.json() };
    },
  } } };
  globalThis.fetch = async () => { throw new Error('vault_bound_cloud_must_not_fetch'); };
  assert.equal((await projectionV2.createDesktopProjectChannelsHttpProjectionV2({ ...config(), apiKey: '' })
    .load(scope())).itemCount, 1);
  assert.equal(calls.length, 2);
  assert.equal(JSON.stringify(calls).includes('trusted-session'), false);
  assert.equal(JSON.stringify(calls).includes('Authorization'), false);
});

test('Local stays on authenticated sidecar and 404/501 stop each operation', async () => {
  const calls = [];
  globalThis.fetch = async (input, init = {}) => {
    calls.push({ input: String(input), init });
    return Response.json({ reason_code: 'sidecar_unavailable' }, { status: calls.length % 2 ? 404 : 501 });
  };
  const client = projectionV2.createDesktopProjectChannelsHttpProjectionV2(config('local'));
  const localScope = scope('local');
  for (const operation of [
    () => client.load(localScope),
    () => client.schema(localScope, 'slack'),
    () => client.create(localScope, { channel_type: 'slack', name: 'Alerts' }),
    () => client.update(localScope, 'channel-1', { enabled: false }),
    () => client.test(localScope, 'channel-1'),
    () => client.remove(localScope, 'channel-1'),
  ]) {
    await assert.rejects(operation, (error) =>
      error.reasonCode === 'local_channel_runtime_not_applicable' &&
      (error.status === 404 || error.status === 501));
  }
  assert.equal(calls.length, 6);
  assert.equal(calls.every(({ input }) => new URL(input).origin === 'http://127.0.0.1:43117'), true);
  assert.equal(calls.every(({ init }) => new Headers(init.headers).get('X-Agistack-Launch') === 'private-launch'), true);
});

function responseFor(pathname, method) {
  if (pathname.endsWith('/channel-catalog')) return json({ items: [catalogItem()] });
  if (pathname.endsWith('/schema')) return json(schema());
  if (pathname.endsWith('/configs') && method === 'GET') return json({ items: [channelConfig()] });
  if (pathname.endsWith('/configs') && method === 'POST') return json(channelConfig({ id: 'channel-2' }));
  if (pathname.endsWith('/test')) return json({ success: true, message: 'ok' });
  if (method === 'PUT') return json(channelConfig({ enabled: false }));
  if (method === 'DELETE') return new Response(null, { status: 204 });
  throw new Error(`unexpected request ${method} ${pathname}`);
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
