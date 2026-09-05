import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const m = require(`${ROOT}/src/plugins/desktopTenantProvidersAuthorityModuleV2.js`);
const p = require(`${ROOT}/src/plugins/desktopTenantProvidersHttpProjectionV2.js`);
const { DesktopApiError } = require(`${ROOT}/src/api/client.js`);
const config = (mode = 'cloud') => ({
  apiBaseUrl: mode === 'local' ? 'http://127.0.0.1:43117' : 'https://api.test',
  deviceAuthorizationBaseUrl: 'https://api.test',
  apiKey: 'trusted-session',
  localApiToken: mode === 'local' ? 'private-launch' : '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode,
  workspaceRoot: '',
});
const provider = (extra = {}) => ({
  id: 'provider-1',
  tenant_id: 'tenant-1',
  name: 'Provider',
  provider_type: 'openai',
  auth_method: 'api_key',
  credential_configured: true,
  api_key_masked: 'server-mask',
  revision: 2,
  ...extra,
});
const mutation = () => ({
  name: 'Provider',
  providerType: 'openai',
  authMethod: 'api_key',
  baseUrl: '',
  primaryModel: 'model-1',
  allowedModels: ['model-1'],
  active: true,
  apiKey: '  test-only-secret  ',
});
const routing = () => ({
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  workspace_id: 'workspace-1',
  revision: 2,
  roles: { default: null, fast: null, coding: null, vision: null },
  fallbacks: [],
  updated_at: '2026-09-05T00:00:00Z',
});
const catalog = (extra = {}) => ({
  provider_type: 'openai',
  provider_id: 'provider-1',
  availability: 'available',
  source: 'provider',
  models: { chat: ['model-1'], embedding: [], rerank: [] },
  ...extra,
});
function fixture(
  runtime = config(),
  authority = p.createDesktopTenantProvidersHttpProjectionV2(runtime),
) {
  const events = [];
  const ops = m.createDesktopTenantProvidersOperationsV2(() => ({
    async acquireServiceOperationLease(descriptor) {
      events.push(['acquire', descriptor]);
      return {
        status: 'accepted',
        useService: (use) =>
          use({
            bindOperation: (frozen) => {
              assert.ok(Object.isFrozen(frozen));
              return authority;
            },
          }),
        async release() {
          events.push(['release']);
        },
      };
    },
  }));
  return { client: m.createDesktopTenantProvidersClientV2(ops, runtime), ops, events };
}
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  delete globalThis.window;
});
const json = (value) =>
  new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });

test('providers V2 exposes twelve operations and rejects blank-tenant input before acquiring', async () => {
  const runtime = { ...config(), tenantId: '', projectId: '', workspaceId: '' };
  const f = fixture(runtime);
  assert.equal(Object.keys(f.ops).length, 12);
  await assert.rejects(f.client.listLlmProviders(), /identifier_invalid/u);
  assert.equal(f.events.length, 0);
  await assert.rejects(f.client.createLlmProvider(mutation(), 'key'), /identifier_invalid/u);
  assert.equal(f.events.length, 0);
});

test('providers V2 cloud twelve operations preserve wire bodies, masking and tenant lease', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    const path = new URL(url).pathname;
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ url: String(url), init, body });
    if (init.method === 'DELETE') return new Response(null, { status: 204 });
    if (path.endsWith('/routing-policy')) return json(routing());
    if (path.endsWith('/types'))
      return json([
        { provider_type: 'openai', operation_type: 'llm', auth_methods: ['api_key', 'oauth'] },
      ]);
    if (path.endsWith('/models/openai') || path.endsWith('/models/discover'))
      return json(catalog());
    if (path.endsWith('/usage'))
      return json({ provider_id: 'provider-1', tenant_id: null, statistics: [] });
    if (path.endsWith('/test-connection') || path.endsWith('/health-check'))
      return json({ status: 'healthy', probed: true, provider: provider(), catalog: catalog() });
    return json(init.method === 'GET' ? [provider()] : provider());
  };
  const { client, events } = fixture();
  const list = await client.listLlmProviders();
  assert.equal(list[0].api_key_masked, '••••••••••••');
  assert.ok(Object.isFrozen(list[0]));
  await client.getLlmProviderRoutingPolicy('project-1', 'workspace-1');
  await client.updateLlmProviderRoutingPolicy({
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    roles: routing().roles,
    fallbacks: [],
    expectedRevision: 2,
  });
  await client.createLlmProvider(mutation(), 'create-provider-1');
  await client.listLlmProviderTypes();
  await client.listLlmProviderModels('openai');
  await client.discoverLlmProviderModels('provider-1', 2);
  await client.getLlmProviderUsage('provider-1');
  await client.testLlmProviderDraft(mutation());
  await client.updateLlmProvider('provider-1', { ...mutation(), expectedRevision: 2 });
  await client.deleteLlmProvider('provider-1', 2, 'delete-provider-1');
  await client.checkLlmProvider('provider-1', 2);
  assert.equal(calls.length, 12);
  assert.equal(events.length, 24);
  assert.deepEqual(events[0][1], {
    service: m.DESKTOP_TENANT_PROVIDERS_AUTHORITY_SERVICE_V2,
    version: '1.0.0',
    scope: { kind: 'tenant', tenant_id: 'tenant-1' },
  });
  assert.equal(calls[3].init.headers.get('Idempotency-Key'), 'create-provider-1');
  assert.equal(calls[3].body.api_key, 'test-only-secret');
  assert.equal(calls[3].body.llm_model, 'model-1');
  assert.deepEqual(calls[10].body, { expected_revision: 2, idempotency_key: 'delete-provider-1' });
  assert.deepEqual(calls[11].body, {});
  assert.equal('llm_model' in calls[8].body, false);
  assert.equal('allowed_models' in calls[8].body, false);
});

test('providers V2 Local keeps launch authentication, revision bodies and delete receipt validation', async () => {
  let response = { deleted: true, id: 'provider-1' };
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push(init);
    return json(response);
  };
  const f = fixture(config('local'));
  await f.client.deleteLlmProvider('provider-1', 2, 'delete-key');
  assert.equal(calls[0].headers.get('X-Agistack-Launch'), 'private-launch');
  assert.deepEqual(JSON.parse(calls[0].body), {
    expected_revision: 2,
    idempotency_key: 'delete-key',
  });
  response = { deleted: true, id: 'other' };
  await assert.rejects(
    f.client.deleteLlmProvider('provider-1', 2, 'delete-key'),
    /delete_response_invalid/u,
  );
  response = { status: 'healthy', probed: true, provider: provider() };
  await f.client.checkLlmProvider('provider-1', 2);
  assert.deepEqual(JSON.parse(calls[2].body), { expected_revision: 2 });
  response = provider({ tenant_id: 'other' });
  await assert.rejects(
    f.client.updateLlmProvider('provider-1', { ...mutation(), expectedRevision: 2 }),
    /response_scope_invalid/u,
  );
});

test('providers V2 rejects malformed routing, identity and mutation preconditions', async () => {
  const f = fixture(config(), {
    async execute() {
      return provider({ id: 'other' });
    },
  });
  await assert.rejects(
    f.client.updateLlmProvider('provider-1', { ...mutation(), expectedRevision: 2 }),
    /response_scope_invalid/u,
  );
  const count = f.events.length;
  await assert.rejects(f.client.discoverLlmProviderModels('provider-1', NaN), /json_invalid/u);
  await assert.rejects(f.client.discoverLlmProviderModels('provider-1', -1), /revision_required/u);
  await assert.rejects(
    f.client.testLlmProviderDraft({ ...mutation(), authMethod: 'oauth' }),
    /auth_method_unavailable/u,
  );
  assert.equal(f.events.length, count);
  const mismatch = fixture(config(), {
    async execute() {
      return { ...routing(), workspace_id: 'other' };
    },
  });
  await assert.rejects(
    mismatch.client.getLlmProviderRoutingPolicy('project-1', 'workspace-1'),
    /routing_response_scope_invalid/u,
  );
  const deletion = fixture(config(), {
    async execute() {
      return { error: 'not deleted' };
    },
  });
  await assert.rejects(
    deletion.client.deleteLlmProvider('provider-1', 2, 'key'),
    /delete_response_invalid/u,
  );
});

test('providers V2 snapshots request input before lease acquisition and preserves failed operation over release failure', async () => {
  let continueAcquire;
  let captured;
  const pending = new Promise((resolve) => {
    continueAcquire = resolve;
  });
  const failure = new DesktopApiError('conflict', 409, null);
  const ops = m.createDesktopTenantProvidersOperationsV2(() => ({
    async acquireServiceOperationLease() {
      await pending;
      return {
        status: 'accepted',
        useService: (use) =>
          use({
            bindOperation: () => ({
              async execute(method, input) {
                captured = input;
                throw failure;
              },
            }),
          }),
        async release() {
          throw new Error('release failed');
        },
      };
    },
  }));
  const runtime = config();
  const input = mutation();
  const job = ops.createLlmProvider({
    config: runtime,
    scope: { authority: 'cloud', tenantId: 'tenant-1' },
    args: [input, 'key'],
  });
  runtime.tenantId = 'changed';
  input.allowedModels.push('changed');
  input.apiKey = 'changed';
  continueAcquire();
  await assert.rejects(job, (error) => error === failure);
  assert.equal(captured.config.tenantId, 'tenant-1');
  assert.deepEqual(captured.args[0].allowedModels, ['model-1']);
  assert.equal(captured.args[0].apiKey, '  test-only-secret  ');
});

test('providers V2 abort after delayed acquisition releases without binding and escaped callbacks cannot rebind', async () => {
  const controller = new AbortController();
  let proceed;
  let callback;
  let binds = 0;
  let releases = 0;
  const pending = new Promise((resolve) => {
    proceed = resolve;
  });
  const service = {
    bindOperation() {
      binds++;
      return {
        async execute() {
          return [];
        },
      };
    },
  };
  const ops = m.createDesktopTenantProvidersOperationsV2(() => ({
    async acquireServiceOperationLease() {
      await pending;
      return {
        status: 'accepted',
        useService: (use) => {
          callback = use;
          return use(service);
        },
        async release() {
          releases++;
        },
      };
    },
  }));
  const client = m.createDesktopTenantProvidersClientV2(ops, config());
  const job = client.listLlmProviders(controller.signal);
  controller.abort();
  proceed();
  await assert.rejects(job, { name: 'AbortError' });
  assert.equal(binds, 0);
  assert.equal(releases, 1);
  await assert.rejects(callback(service), /released/u);
  assert.equal(binds, 0);
});

test('providers V2 real Loader publishes service and disabling removes it from the next generation', async () => {
  const runtime = require('@agistack/plugin-runtime');
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
  try {
    const service = generation.resolve(
      m.DESKTOP_TENANT_PROVIDERS_AUTHORITY_SERVICE_V2,
      { kind: 'tenant', tenant_id: 'tenant-1' },
      { version: '1.0.0' },
    );
    assert.equal(typeof service.bindOperation, 'function');
    const disabled = structuredClone(profile);
    disabled.entries.find(
      (item) => item.entry_id === 'builtin-desktop-tenant-providers-authority',
    ).enabled = false;
    const next = await loader.stage(disabled);
    try {
      assert.throws(
        () =>
          next.resolve(
            m.DESKTOP_TENANT_PROVIDERS_AUTHORITY_SERVICE_V2,
            { kind: 'tenant', tenant_id: 'tenant-1' },
            { version: '1.0.0' },
          ),
        (error) => error.code === 'missing_service',
      );
      assert.equal(typeof service.bindOperation(config()).execute, 'function');
    } finally {
      await next.dispose();
    }
  } finally {
    await generation.dispose();
  }
});

test('providers V2 preserves vault-bound cloud broker idempotency and never falls back to fetch', async () => {
  const requests = [];
  globalThis.fetch = async () => {
    throw new Error('unexpected direct fetch');
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, input) {
          assert.equal(command, 'cloud_request');
          requests.push(input.request);
          return { status: 201, body: provider() };
        },
      },
    },
  };
  const f = fixture({ ...config(), apiKey: '' });
  await f.client.createLlmProvider(
    {
      ...mutation(),
      authMethod: 'environment',
      apiKey: undefined,
      environmentVariable: '  TEST_PROVIDER_KEY  ',
    },
    'create-vault-provider',
  );
  assert.deepEqual(requests[0].mutation, {
    kind: 'idempotency-only',
    idempotency_key: 'create-vault-provider',
  });
  assert.equal(requests[0].body.environment_variable, 'TEST_PROVIDER_KEY');
  assert.equal('api_key' in requests[0].body, false);
  assert.equal(requests[0].path, '/api/v1/llm-providers/');
  assert.equal(f.events.at(-1)[0], 'release');
});
