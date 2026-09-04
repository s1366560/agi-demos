import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const runtime = require('@agistack/plugin-runtime');
const moduleV2 = require(`${ROOT}/src/plugins/desktopTenantEvolutionAuthorityModuleV2.js`);
const projectionV2 = require(`${ROOT}/src/plugins/desktopTenantEvolutionHttpProjectionV2.js`);

const config = (mode = 'cloud') => ({
  apiBaseUrl: mode === 'cloud' ? 'https://api.test' : 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: 'https://api.test',
  apiKey: mode === 'cloud' ? 'trusted-session' : 'local-session',
  localApiToken: mode === 'local' ? 'private-launch' : '',
  tenantId: 'tenant-1',
  projectId: '',
  workspaceId: '',
  mode,
  workspaceRoot: '',
});
const scope = (authority = 'cloud') => ({ authority, tenantId: 'tenant-1' });
const policy = (overrides = {}) => ({
  enabled: true,
  min_sessions_per_skill: 3,
  scoring_min_sessions_per_skill: 2,
  min_avg_score: 0.75,
  max_sessions_per_batch: 20,
  evolution_interval_minutes: 30,
  publish_mode: 'review',
  auto_apply: false,
  ...overrides,
});
const overview = () => ({
  stats: { total_sessions: 1 },
  skills: [{ skill_id: 'skill-1' }],
  recent_sessions: [],
  recent_jobs: [],
  trigger: { enabled: true },
});
const observation = (marker) => ({
  scope: scope(),
  authority: 'cloud',
  availability: 'available',
  reasonCode: null,
  allowedActions: ['view', 'configure', 'run', 'apply-job', 'reject-job'],
  itemCount: 1,
  overview: { ...overview(), stats: { ...overview().stats, marker } },
  config: policy(),
});
const client = (observe = async () => observation('load')) =>
  ({
    observe,
    async run() {},
    async updateConfig(_scope, input) {
      return policy(input);
    },
    async reviewJob() {},
  });
const service = (value) => Object.freeze({ bindOperation: () => value });
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

test('catalog registers the exact Tenant Evolution Provider', () => {
  const entry = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === moduleV2.DESKTOP_TENANT_EVOLUTION_AUTHORITY_MODULE_REF_V2,
  );
  assert.equal(moduleV2.desktopTenantEvolutionAuthorityDefinitionV2.contractDigest, entry.contract_digest);
  assert.deepEqual(entry.contract.services.provides, [
    {
      service: moduleV2.DESKTOP_TENANT_EVOLUTION_AUTHORITY_SERVICE_V2,
      version: '1.0.0',
    },
  ]);
});

test('all operations hold exact tenant leases and freeze operation input', async () => {
  const lifecycle = [];
  let observedConfig;
  let observedScope;
  let observedUpdate;
  const authority = client();
  authority.updateConfig = async (currentScope, input) => {
    observedScope = currentScope;
    observedUpdate = input;
    return policy(input);
  };
  const operations = moduleV2.createDesktopTenantEvolutionOperationsV2(() =>
    actions(
      Object.freeze({
        bindOperation(currentConfig) {
          observedConfig = currentConfig;
          return authority;
        },
      }),
      lifecycle,
    ),
  );
  await operations.observeTenantEvolution({ config: config(), scope: scope() });
  await operations.runTenantEvolution({ config: config(), scope: scope() });
  await operations.updateTenantEvolutionConfig({
    config: config(),
    scope: scope(),
    update: { enabled: false, min_avg_score: 0.5 },
  });
  await operations.reviewTenantEvolutionJob({
    config: config(),
    scope: scope(),
    jobId: 'job-1',
    action: 'apply',
  });
  assert.equal(Object.isFrozen(observedConfig), true);
  assert.equal(Object.isFrozen(observedScope), true);
  assert.equal(Object.isFrozen(observedUpdate), true);
  assert.deepEqual(
    lifecycle.filter(([kind]) => kind === 'acquire').map(([, value]) => value.scope),
    Array(4).fill({ kind: 'tenant', tenant_id: 'tenant-1' }),
  );
  assert.equal(lifecycle.filter(([kind]) => kind === 'release').length, 4);
});

test('input, service and response contracts fail closed before promotion', async () => {
  let acquisitions = 0;
  const operations = moduleV2.createDesktopTenantEvolutionOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      return actions(service(client(async () => ({})))).acquireServiceOperationLease({});
    },
  }));
  assert.throws(
    () =>
      operations.updateTenantEvolutionConfig({
        config: config(),
        scope: scope(),
        update: { enabled: false, unexpected: true },
      }),
    (error) => error.code === 'desktop_tenant_evolution_operation_input_invalid',
  );
  assert.equal(acquisitions, 0);
  await assert.rejects(
    () => operations.observeTenantEvolution({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_evolution_operation_response_invalid',
  );
  const malformed = moduleV2.createDesktopTenantEvolutionOperationsV2(() =>
    actions(Object.freeze({ bindOperation: () => ({ observe() {} }), extra: true })),
  );
  await assert.rejects(
    () => malformed.observeTenantEvolution({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_evolution_service_invalid',
  );
  const malformedAuthority = moduleV2.createDesktopTenantEvolutionOperationsV2(() =>
    actions(Object.freeze({ bindOperation: () => ({ observe() {} }) })),
  );
  await assert.rejects(
    () => malformedAuthority.observeTenantEvolution({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_evolution_service_invalid',
  );
  await assert.rejects(
    () =>
      moduleV2
        .createDesktopTenantEvolutionOperationsV2(() => null)
        .observeTenantEvolution({ config: config(), scope: scope() }),
    (error) =>
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable' &&
      error.name === 'DesktopTenantEvolutionAuthorityUnavailableErrorV2',
  );
});

test('HMR pins in-flight work, revokes escaped use and preserves error precedence', async () => {
  let finish;
  const capture = {};
  let current = actions(
    service(
      client(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      ),
    ),
    [],
    undefined,
    capture,
  );
  const operations = moduleV2.createDesktopTenantEvolutionOperationsV2(() => current);
  const pending = operations.observeTenantEvolution({ config: config(), scope: scope() });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(service(client(async () => observation('new'))));
  finish(observation('old'));
  assert.equal((await pending).overview.stats.marker, 'old');
  assert.equal(
    (await operations.observeTenantEvolution({ config: config(), scope: scope() })).overview.stats
      .marker,
    'new',
  );
  await assert.rejects(
    () => capture.use(service(client())),
    (error) => error.code === 'desktop_tenant_evolution_operation_released',
  );
  const primary = new Error('primary');
  const failing = moduleV2.createDesktopTenantEvolutionOperationsV2(() =>
    actions(service(client(async () => { throw primary; })), [], new Error('release')),
  );
  await assert.rejects(
    () => failing.observeTenantEvolution({ config: config(), scope: scope() }),
    primary,
  );
  const release = new Error('release-only');
  const releaseFailing = moduleV2.createDesktopTenantEvolutionOperationsV2(() =>
    actions(service(client()), [], release),
  );
  await assert.rejects(
    () => releaseFailing.observeTenantEvolution({ config: config(), scope: scope() }),
    release,
  );
});

test('Cloud projection uses trusted transport while Local mutations remain zero-network', async () => {
  const cloudRequests = [];
  const signal = new AbortController().signal;
  const restoreCloud = mockFetch(cloudRequests, [
    overview(),
    policy(),
    { tenant_id: 'tenant-1', result: {} },
    policy({ enabled: false }),
    { status: 'applied' },
  ]);
  try {
    const authority = projectionV2.createDesktopTenantEvolutionHttpProjectionV2(config());
    await authority.observe(scope(), signal);
    await authority.run(scope(), signal);
    await authority.updateConfig(scope(), { enabled: false }, signal);
    await authority.reviewJob(scope(), 'job-1', 'apply', signal);
  } finally {
    restoreCloud();
  }
  assert.deepEqual(
    cloudRequests.map((request) => [new URL(request.url).pathname, request.init.method ?? 'GET']),
    [
      ['/api/v1/skills/evolution/overview', 'GET'],
      ['/api/v1/skills/evolution/config', 'GET'],
      ['/api/v1/skills/evolution/run', 'POST'],
      ['/api/v1/skills/evolution/config', 'PUT'],
      ['/api/v1/skills/evolution/jobs/job-1/apply', 'POST'],
    ],
  );
  for (const request of cloudRequests) {
    const headers = new Headers(request.init.headers);
    assert.equal(headers.get('Authorization'), 'Bearer trusted-session');
    assert.equal(request.init.credentials, 'omit');
    assert.equal(request.init.signal, signal);
  }

  const localRequests = [];
  const restoreLocal = mockFetch(localRequests, [
    { __error: true, status: 501, payload: { reason_code: 'local_skill_evolution_authority_unavailable' } },
  ]);
  try {
    const authority = projectionV2.createDesktopTenantEvolutionHttpProjectionV2(config('local'));
    await assert.rejects(
      () => authority.observe(scope('local')),
      (error) => error.reasonCode === 'local_skill_evolution_authority_unavailable',
    );
    for (const operation of [
      () => authority.run(scope('local')),
      () => authority.updateConfig(scope('local'), { enabled: false }),
      () => authority.reviewJob(scope('local'), 'job-1', 'reject'),
    ]) {
      await assert.rejects(
        operation,
        (error) => error.reasonCode === 'local_skill_evolution_authority_unavailable',
      );
    }
  } finally {
    restoreLocal();
  }
  assert.equal(localRequests.length, 1);
  assert.equal(new URL(localRequests[0].url).pathname, '/api/v1/skills/evolution/overview');
});

test('Cloud projection uses the vault broker without renderer credentials', async () => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          calls.push({ command, args });
          const path = args.request.path;
          if (path.includes('/overview?')) return { status: 200, body: overview() };
          if (path.includes('/config?')) {
            return {
              status: 200,
              body: policy(args.request.method === 'PUT' ? args.request.body : {}),
            };
          }
          return { status: 200, body: { tenant_id: 'tenant-1' } };
        },
      },
    },
  };
  globalThis.fetch = async () => {
    throw new Error('vault_bound_cloud_must_not_fetch');
  };
  try {
    const authority = projectionV2.createDesktopTenantEvolutionHttpProjectionV2({
      ...config(),
      apiKey: '',
    });
    await authority.observe(scope());
    await authority.run(scope());
    await authority.updateConfig(scope(), { enabled: false });
    await authority.reviewJob(scope(), 'job-1', 'reject');
  } finally {
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
    globalThis.fetch = originalFetch;
  }
  assert.deepEqual(
    calls.map(({ command, args }) => [command, args.request.method]),
    [
      ['cloud_request', 'GET'],
      ['cloud_request', 'GET'],
      ['cloud_request', 'POST'],
      ['cloud_request', 'PUT'],
      ['cloud_request', 'POST'],
    ],
  );
  assert.equal(JSON.stringify(calls).includes('trusted-session'), false);
  assert.equal(JSON.stringify(calls).includes('Authorization'), false);
});

function mockFetch(requests, payloads) {
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => {
    requests.push({ url: String(url), init });
    const next = payloads.shift();
    if (next?.__error) return response(next.payload, next.status);
    return response(next);
  };
  return () => {
    globalThis.fetch = original;
  };
}

function response(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
