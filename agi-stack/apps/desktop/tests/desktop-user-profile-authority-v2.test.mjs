import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const moduleV2 = require(`${ROOT}/src/plugins/desktopUserProfileAuthorityModuleV2.js`);
const projectionV2 = require(`${ROOT}/src/plugins/desktopUserProfileHttpProjectionV2.js`);
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
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode,
  workspaceRoot: '/workspace',
});
const scope = (authority = 'cloud') => ({ authority });
const user = (overrides = {}) => ({
  user_id: 'user-1',
  email: 'user@example.test',
  name: 'User',
  roles: ['user'],
  global_roles: [],
  is_active: true,
  is_superuser: false,
  created_at: '2026-09-05T00:00:00Z',
  profile: {},
  preferred_language: 'en-US',
  ...overrides,
});
const observation = (authority = 'cloud', overrides = {}) => ({
  scope: scope(authority),
  authority,
  availability: authority === 'local' ? 'degraded' : 'available',
  reasonCode: authority === 'local' ? 'local_profile_mutation_authority_unavailable' : null,
  allowedActions:
    authority === 'local'
      ? ['view']
      : ['view', 'update', 'change-language', 'change-password'],
  itemCount: 1,
  user: user(),
  ...overrides,
});
const authority = (overrides = {}) =>
  Object.freeze({
    async observe(currentScope) {
      return observation(currentScope.authority);
    },
    async update() {
      return user({ name: 'Updated' });
    },
    async changePassword() {},
    ...overrides,
  });
const service = (value, capture = {}) =>
  Object.freeze({
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
    (item) => item.module_ref === moduleV2.DESKTOP_USER_PROFILE_AUTHORITY_MODULE_REF_V2,
  );
  assert.equal(
    moduleV2.desktopUserProfileAuthorityDefinitionV2.contractDigest,
    entry.contract_digest,
  );
  assert.deepEqual(entry.contract.services.provides, [
    {
      service: moduleV2.DESKTOP_USER_PROFILE_AUTHORITY_SERVICE_V2,
      version: '1.0.0',
    },
  ]);
  const provided = {};
  moduleV2.applyDesktopUserProfileAuthorityV2(
    {
      provide(key, value) {
        provided.key = key;
        provided.value = value;
      },
    },
    { strategy: 'desktop-api-fetch' },
  );
  assert.equal(provided.key, moduleV2.DESKTOP_USER_PROFILE_AUTHORITY_SERVICE_V2);
  assert.deepEqual(Object.keys(provided.value), ['bindOperation']);
  assert.throws(
    () =>
      moduleV2.applyDesktopUserProfileAuthorityV2(
        { provide() {} },
        { strategy: 'desktop-api-fetch', fallback: true },
      ),
    (error) => error.code === 'desktop_user_profile_authority_config_invalid',
  );

  const bootstrap = JSON.parse(readFileSync(bootstrapPath, 'utf8'));
  const loader = new runtime.LoaderV2(
    [...runtime.createDesktopRendererDefinitionsV2(), ...authorityModules],
    'desktop-renderer',
  );
  const generation = await loader.stage(bootstrap);
  assert.ok(
    generation.resolve(
      moduleV2.DESKTOP_USER_PROFILE_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: '1.0.0' },
    ),
  );
  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    (item) => item.entry_id === 'builtin-desktop-user-profile-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        moduleV2.DESKTOP_USER_PROFILE_AUTHORITY_SERVICE_V2,
        { kind: 'root' },
        { version: '1.0.0' },
      ),
    (error) => error.code === 'missing_service',
  );
  await disabledGeneration.dispose();
  await generation.dispose();
});

test('all operations acquire root leases and snapshot config, scope, input and signal', async () => {
  const lifecycle = [];
  const capture = {};
  const signal = new AbortController().signal;
  const operations = moduleV2.createDesktopUserProfileOperationsV2(() =>
    actions(
      service(
        authority({
          async observe(currentScope, currentSignal) {
            capture.observeScope = currentScope;
            capture.signal = currentSignal;
            return observation();
          },
          async update(_scope, input) {
            capture.update = input;
            return user({ name: 'Updated' });
          },
          async changePassword(_scope, input) {
            capture.password = input;
          },
        }),
        capture,
      ),
      lifecycle,
    ),
  );
  await operations.observeUserProfile({ config: config(), scope: scope(), signal });
  await operations.updateUserProfile({
    config: config(),
    scope: scope(),
    input: { name: 'Updated', profile: { department: 'Engineering' } },
  });
  await operations.changeUserProfilePassword({
    config: config(),
    scope: scope(),
    input: { oldPassword: 'old-password', newPassword: 'new-password' },
  });
  const acquisitions = lifecycle.filter(([kind]) => kind === 'acquire');
  assert.equal(acquisitions.length, 3);
  assert.equal(lifecycle.filter(([kind]) => kind === 'release').length, 3);
  assert.equal(
    acquisitions.every(
      ([, descriptor]) =>
        descriptor.service === moduleV2.DESKTOP_USER_PROFILE_AUTHORITY_SERVICE_V2 &&
        descriptor.version === '1.0.0' &&
        Object.keys(descriptor.scope).length === 1 &&
        descriptor.scope.kind === 'root',
    ),
    true,
  );
  assert.equal(capture.signal, signal);
  assert.equal(Object.isFrozen(capture.config), true);
  assert.equal(Object.isFrozen(capture.scope), true);
  assert.equal(Object.isFrozen(capture.observeScope), true);
  assert.equal(Object.isFrozen(capture.update), true);
  assert.equal(Object.isFrozen(capture.update.profile), true);
  assert.equal(Object.isFrozen(capture.password), true);
});

test('service, authority, input and response drift fail closed before escape', async () => {
  let acquisitions = 0;
  const rejected = moduleV2.createDesktopUserProfileOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      return { status: 'rejected', reasonCode: 'missing_service_provider' };
    },
  }));
  assert.throws(
    () => rejected.observeUserProfile({ config: config(), scope: scope(), extra: true }),
    (error) => error.code === 'desktop_user_profile_operation_input_invalid',
  );
  assert.equal(acquisitions, 0);
  await assert.rejects(
    () => rejected.observeUserProfile({ config: config(), scope: scope() }),
    (error) => error.reasonCode === 'missing_service_provider',
  );
  await assert.rejects(
    () =>
      moduleV2
        .createDesktopUserProfileOperationsV2(() => null)
        .observeUserProfile({ config: config(), scope: scope() }),
    (error) => error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
  await assert.rejects(
    () =>
      moduleV2
        .createDesktopUserProfileOperationsV2(() =>
          actions(Object.freeze({ bindOperation() { return authority(); }, extra: true })),
        )
        .observeUserProfile({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_user_profile_service_invalid',
  );
  await assert.rejects(
    () =>
      moduleV2
        .createDesktopUserProfileOperationsV2(() =>
          actions(service(Object.freeze({ ...authority(), extra: true }))),
        )
        .observeUserProfile({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_user_profile_service_invalid',
  );
  await assert.rejects(
    () =>
      moduleV2
        .createDesktopUserProfileOperationsV2(() =>
          actions(service(authority({ observe: async () => observation('cloud', { itemCount: 2 }) }))),
        )
        .observeUserProfile({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_user_profile_operation_response_invalid',
  );
  await assert.rejects(
    () =>
      moduleV2
        .createDesktopUserProfileOperationsV2(() =>
          actions(service(authority({ update: async () => ({ ...user(), email: null }) }))),
        )
        .updateUserProfile({ config: config(), scope: scope(), input: { name: 'Updated' } }),
    (error) => error.code === 'desktop_user_profile_operation_response_invalid',
  );
  await assert.rejects(
    () =>
      moduleV2
        .createDesktopUserProfileOperationsV2(() =>
          actions(service(authority({ changePassword: async () => ({ leaked: true }) }))),
        )
        .changeUserProfilePassword({
          config: config(),
          scope: scope(),
          input: { oldPassword: 'old', newPassword: 'new' },
        }),
    (error) => error.code === 'desktop_user_profile_operation_response_invalid',
  );
});

test('HMR pins old work, escaped authority revokes, and primary errors outrank release', async () => {
  let finish;
  const capture = {};
  let current = actions(
    service(
      authority({
        observe: () => new Promise((resolve) => { finish = resolve; }),
      }),
    ),
    [],
    undefined,
    capture,
  );
  const operations = moduleV2.createDesktopUserProfileOperationsV2(() => current);
  const pending = operations.observeUserProfile({ config: config(), scope: scope() });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(
    service(authority({ observe: async () => observation('cloud', { user: user({ name: 'New' }) }) })),
  );
  finish(observation('cloud', { user: user({ name: 'Old' }) }));
  assert.equal((await pending).user.name, 'Old');
  assert.equal(
    (await operations.observeUserProfile({ config: config(), scope: scope() })).user.name,
    'New',
  );
  await assert.rejects(
    () => capture.use(service(authority())),
    (error) => error.code === 'desktop_user_profile_operation_released',
  );
  const primary = new Error('primary');
  const primaryFailing = moduleV2.createDesktopUserProfileOperationsV2(() =>
    actions(
      service(authority({ observe: async () => { throw primary; } })),
      [],
      new Error('release'),
    ),
  );
  await assert.rejects(
    () => primaryFailing.observeUserProfile({ config: config(), scope: scope() }),
    primary,
  );
  await assert.rejects(
    () =>
      moduleV2
        .createDesktopUserProfileOperationsV2(() =>
          actions(service(authority()), [], new Error('release-only')),
        )
        .observeUserProfile({ config: config(), scope: scope() }),
    /release-only/u,
  );
});

test('Cloud uses vault-bound exact routes without exposing profile passwords', async () => {
  const calls = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          calls.push({ command, request: args.request });
          const path = new URL(args.request.path, 'https://api.test').pathname;
          if (path === '/api/v1/auth/me') return { status: 200, body: user() };
          if (path === '/api/v1/users/me') {
            return { status: 200, body: user({ name: 'Updated' }) };
          }
          if (path === '/api/v1/auth/force-change-password') {
            return { status: 200, body: { success: true, message: 'changed' } };
          }
          throw new Error(`unexpected path ${path}`);
        },
      },
    },
  };
  globalThis.fetch = async () => { throw new Error('vault_bound_cloud_must_not_fetch'); };
  const client = projectionV2.createDesktopUserProfileHttpProjectionV2({
    ...config(),
    apiKey: '',
  });
  const signal = new AbortController().signal;
  await client.observe(scope(), signal);
  await client.update(scope(), { name: 'Updated' }, signal);
  await client.changePassword(
    scope(),
    { oldPassword: 'old-password', newPassword: 'new-password' },
    signal,
  );
  assert.deepEqual(
    calls.map(({ request }) => [new URL(request.path, 'https://api.test').pathname, request.method]),
    [
      ['/api/v1/auth/me', 'GET'],
      ['/api/v1/users/me', 'PUT'],
      ['/api/v1/auth/force-change-password', 'POST'],
    ],
  );
  assert.equal(calls.every(({ request }) => request.signal === undefined), true);
  assert.equal(JSON.stringify(calls).includes('trusted-session'), false);
  assert.equal(JSON.stringify(calls).includes('Authorization'), false);
});

test('Local observes through authenticated sidecar and rejects both mutations before traffic', async () => {
  const calls = [];
  globalThis.fetch = async (input, init = {}) => {
    calls.push({ input: String(input), init });
    return json(user({ user_id: 'local-user' }));
  };
  const client = projectionV2.createDesktopUserProfileHttpProjectionV2(config('local'));
  const observed = await client.observe(scope('local'));
  assert.equal(observed.user.user_id, 'local-user');
  assert.equal(observed.availability, 'degraded');
  assert.deepEqual(observed.allowedActions, ['view']);
  await assert.rejects(
    () => client.update(scope('local'), { name: 'Blocked' }),
    (error) =>
      error.status === 501 && error.reasonCode === 'local_profile_mutation_authority_unavailable',
  );
  await assert.rejects(
    () =>
      client.changePassword(scope('local'), {
        oldPassword: 'old-password',
        newPassword: 'new-password',
      }),
    (error) =>
      error.status === 501 && error.reasonCode === 'local_profile_mutation_authority_unavailable',
  );
  assert.equal(calls.length, 1);
  assert.equal(new URL(calls[0].input).pathname, '/api/v1/auth/me');
  assert.equal(new Headers(calls[0].init.headers).get('Authorization'), 'Bearer local-session');
  assert.equal(new Headers(calls[0].init.headers).get('X-Agistack-Launch'), 'private-launch');
});

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
