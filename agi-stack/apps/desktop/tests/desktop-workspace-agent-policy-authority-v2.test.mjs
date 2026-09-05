import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test, afterEach } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist/src';
const moduleV2 = require(`${ROOT}/plugins/desktopWorkspaceAgentPolicyAuthorityModuleV2.js`);
const { createDesktopWorkspaceAgentPolicyHttpProjectionV2 } = require(
  `${ROOT}/plugins/desktopWorkspaceAgentPolicyHttpProjectionV2.js`,
);
const { DEFAULT_CONFIG } = require(`${ROOT}/types.js`);
const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
afterEach(() => {
  globalThis.fetch = originalFetch;
  globalThis.window = originalWindow;
});
const config = (mode = 'cloud', overrides = {}) => ({
  ...DEFAULT_CONFIG,
  mode,
  apiBaseUrl: mode === 'cloud' ? 'https://api.test' : 'http://127.0.0.1:8088',
  apiKey: 'trusted-session',
  localApiToken: 'launch-capability',
  tenantId: 'tenant / 1',
  projectId: 'project / 1',
  workspaceId: 'workspace / 1',
  ...overrides,
});
const route = { provider_id: 'provider-1', model_id: 'model-1' };
const policy = (overrides = {}) => ({
  tenant_id: 'tenant / 1',
  project_id: 'project / 1',
  workspace_id: 'workspace / 1',
  revision: 2,
  roles: { default: route, fast: null, coding: route, vision: null },
  fallbacks: [],
  updated_at: '2026-09-05T00:00:00Z',
  reasoning_effort: 'medium',
  permission_mode: 'ask',
  capability_version: 'workspace-agent-policy-v1',
  ...overrides,
});
const mutation = () => ({
  projectId: 'project / 1',
  workspaceId: 'workspace / 1',
  expected_revision: 2,
  capabilityMode: 'code',
  route: { ...route },
  reasoning_effort: 'high',
  permission_mode: 'automatic',
});
function fixture(
  runtime = config(),
  bind = createDesktopWorkspaceAgentPolicyHttpProjectionV2,
  cleanup = async () => {},
) {
  const events = [];
  const operations = moduleV2.createDesktopWorkspaceAgentPolicyOperationsV2(() => ({
    async acquireServiceOperationLease(input) {
      events.push(['acquire', input]);
      return {
        status: 'accepted',
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
    events,
    operations,
    client: moduleV2.createDesktopWorkspaceAgentPolicyClientV2(operations, runtime),
  };
}
test('Cloud and Local use the exact scoped GET/PATCH contract with signals and CAS body', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: new URL(url), init });
    return Response.json(policy());
  };
  for (const mode of ['cloud', 'local']) {
    const { client, events } = fixture(config(mode));
    const signal = new AbortController().signal;
    const loaded = await client.getWorkspaceAgentPolicy('project / 1', 'workspace / 1', signal);
    const updated = await client.updateWorkspaceAgentPolicy(mutation(), signal);
    assert.equal(Object.isFrozen(loaded.roles.default), true);
    assert.equal(updated.capability_version, 'workspace-agent-policy-v1');
    const [read, patch] = calls.slice(-2);
    assert.equal(
      read.url.pathname,
      '/api/v1/tenants/tenant%20%2F%201/projects/project%20%2F%201/workspaces/workspace%20%2F%201/agent-policy',
    );
    assert.equal(read.init.method, 'GET');
    assert.equal(patch.init.method, 'PATCH');
    assert.deepEqual(JSON.parse(patch.init.body), {
      expected_revision: 2,
      capability_mode: 'code',
      route,
      reasoning_effort: 'high',
      permission_mode: 'automatic',
    });
    for (const { init } of [read, patch]) {
      assert.equal(init.signal, signal);
      assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer trusted-session');
      assert.equal(
        new Headers(init.headers).get('X-Agistack-Launch'),
        mode === 'local' ? 'launch-capability' : null,
      );
    }
    assert.deepEqual(
      events.map(([kind]) => kind),
      ['acquire', 'release', 'acquire', 'release'],
    );
    assert.deepEqual(events[0][1].scope, {
      kind: 'project',
      tenant_id: 'tenant / 1',
      project_id: 'project / 1',
    });
  }
});
test('404/405/501 fail without a legacy routing request or fabricated policy', async () => {
  const calls = [];
  for (const status of [404, 405, 501]) {
    globalThis.fetch = async (url) => {
      calls.push(String(url));
      return Response.json({ code: 'policy_unavailable' }, { status });
    };
    await assert.rejects(
      () => fixture().client.getWorkspaceAgentPolicy('project / 1', 'workspace / 1'),
      (e) => e.status === status,
    );
  }
  assert.equal(calls.length, 3);
  assert.ok(calls.every((url) => url.endsWith('/agent-policy')));
  const hook = readFileSync(
    new URL('../src/features/settings/useWorkspaceAgentPolicy.ts', import.meta.url),
    'utf8',
  );
  assert.doesNotMatch(
    hook,
    /DesktopApiClient|DesktopApiError|getLlmProviderRoutingPolicy|legacy-routing-policy-v1/,
  );
  assert.match(hook, /policyClient\.getWorkspaceAgentPolicy/);
  assert.match(hook, /providerClient\.listLlmProviders/);
});
test('blank scope construction is inert and malformed mutations reject before acquisition', async () => {
  const empty = fixture(config('cloud', { tenantId: '' }));
  await assert.rejects(async () =>
    empty.client.getWorkspaceAgentPolicy('project / 1', 'workspace / 1'),
  );
  assert.equal(empty.events.length, 0);
  const current = fixture();
  for (const invalid of [
    { expected_revision: -1 },
    { capabilityMode: 'other' },
    { permission_mode: 'other' },
    { route: { provider_id: '', model_id: 'x' } },
  ]) {
    assert.throws(() => current.client.updateWorkspaceAgentPolicy({ ...mutation(), ...invalid }));
  }
  assert.equal(current.events.length, 0);
});
test('foreign identity and legacy capability response are rejected while provider errors survive release', async () => {
  for (const overrides of [
    { tenant_id: 'foreign' },
    { workspace_id: 'foreign' },
    { capability_version: 'legacy-routing-policy-v1' },
  ]) {
    const { client } = fixture(config(), () =>
      Object.freeze({ load: async () => policy(overrides), update: async () => policy(overrides) }),
    );
    await assert.rejects(
      () => client.getWorkspaceAgentPolicy('project / 1', 'workspace / 1'),
      /workspace_agent_policy_response_invalid/,
    );
  }
  const primary = new Error('primary');
  const current = fixture(
    config(),
    () =>
      Object.freeze({
        load: async () => {
          throw primary;
        },
        update: async () => policy(),
      }),
    async () => {
      throw new Error('release');
    },
  );
  await assert.rejects(
    () => current.client.getWorkspaceAgentPolicy('project / 1', 'workspace / 1'),
    (e) => e === primary,
  );
});
test('real Loader applies the policy provider and disabled profile refuses real lease without HTTP', async () => {
  const runtime = require('@agistack/plugin-runtime');
  const { acquireDesktopRendererServiceOperationLeaseV2 } = require(
    `${ROOT}/plugins/desktopRendererServiceOperationLeaseV2.js`,
  );
  const authorities = readdirSync(`${ROOT}/plugins`)
    .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
    .flatMap((name) =>
      Object.values(require(`${ROOT}/plugins/${name}`)).filter(
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
  const manager = new runtime.GenerationManagerV2();
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return Response.json(policy());
  };
  const clientFor = (generation) =>
    moduleV2.createDesktopWorkspaceAgentPolicyClientV2(
      moduleV2.createDesktopWorkspaceAgentPolicyOperationsV2(() => ({
        acquireServiceOperationLease: (request) =>
          acquireDesktopRendererServiceOperationLeaseV2(generation, request, (target) =>
            manager.acquire(target),
          ),
      })),
      config(),
    );
  try {
    const active = await loader.stage(profile);
    await manager.publish(active);
    assert.equal(
      (await clientFor(active).getWorkspaceAgentPolicy('project / 1', 'workspace / 1')).revision,
      2,
    );
    await clientFor(active).updateWorkspaceAgentPolicy(mutation());
    assert.equal(active.leaseCount, 0);
    assert.equal(calls, 2);
    const disabled = structuredClone(profile);
    disabled.entries.find(
      (entry) => entry.entry_id === 'builtin-desktop-workspace-agent-policy-authority',
    ).enabled = false;
    const next = await loader.stage(disabled);
    await manager.publish(next);
    await assert.rejects(
      () => clientFor(next).getWorkspaceAgentPolicy('project / 1', 'workspace / 1'),
      /desktop_renderer_service_resolve_failed/,
    );
    assert.equal(calls, 2);
    assert.equal(next.leaseCount, 0);
  } finally {
    await manager.close();
  }
});

test('Cloud vault-bound policy transport sends no renderer bearer secret and never uses direct fetch', async () => {
  const calls = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          calls.push({ command, request: args.request });
          return { status: 200, body: policy() };
        },
      },
    },
  };
  globalThis.fetch = async () => {
    assert.fail('unexpected direct fetch');
  };
  const client = fixture(config('cloud', { apiKey: '' })).client;
  assert.equal((await client.getWorkspaceAgentPolicy('project / 1', 'workspace / 1')).revision, 2);
  assert.equal(calls[0].command, 'cloud_request');
  assert.equal(JSON.stringify(calls).includes('Authorization'), false);
  assert.equal(JSON.stringify(calls).includes('trusted-session'), false);
});
test('abort during admission prevents binding and escaped use callbacks cannot revive a released policy', async () => {
  const controller = new AbortController();
  let resume;
  const gate = new Promise((resolve) => {
    resume = resolve;
  });
  let binds = 0;
  let releases = 0;
  let escaped;
  const service = Object.freeze({
    bindOperation() {
      binds += 1;
      return Object.freeze({ load: async () => policy(), update: async () => policy() });
    },
  });
  const ops = moduleV2.createDesktopWorkspaceAgentPolicyOperationsV2(() => ({
    async acquireServiceOperationLease() {
      await gate;
      return {
        status: 'accepted',
        async useService(use) {
          escaped = use;
          return use(service);
        },
        async release() {
          releases += 1;
        },
      };
    },
  }));
  const client = moduleV2.createDesktopWorkspaceAgentPolicyClientV2(ops, config());
  const pending = client.getWorkspaceAgentPolicy('project / 1', 'workspace / 1', controller.signal);
  controller.abort();
  resume();
  await assert.rejects(() => pending, { name: 'AbortError' });
  assert.equal(binds, 0);
  assert.equal(releases, 1);
  await assert.rejects(
    () => escaped(service),
    (error) => error.code === 'workspace_agent_policy_operation_released',
  );
  assert.equal(binds, 0);
});

test('App injects both V2 clients and retired HTTP methods stay absent while task-session policy parsing remains', () => {
  const readSource = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
  const app = readSource('App.tsx').replace(/\s+/gu, ' ');
  const hook = readSource('features/settings/useWorkspaceAgentPolicy.ts');
  const api = readSource('api/client.ts');
  const { DesktopApiClient } = require(`${ROOT}/api/client.js`);
  assert.match(
    app,
    /createDesktopWorkspaceAgentPolicyOperationsV2\( \(\) => desktopPluginMarketplaceGenerationActionsRefV2\.current,/u,
  );
  assert.match(
    app,
    /createDesktopTenantProvidersOperationsV2\( \(\) => desktopPluginMarketplaceGenerationActionsRefV2\.current,/u,
  );
  assert.match(
    app,
    /createDesktopWorkspaceAgentPolicyClientV2\( desktopWorkspaceAgentPolicyOperationsV2, newThreadRuntimeConfig,/u,
  );
  assert.match(
    app,
    /createDesktopTenantProvidersClientV2\( desktopTenantProvidersOperationsV2, newThreadRuntimeConfig,/u,
  );
  assert.match(
    app,
    /useWorkspaceAgentPolicy\( newThreadRuntimeConfig, [^;]*?desktopWorkspaceRosterOperationsV2, newThreadWorkspaceAgentPolicyClientV2, newThreadTenantProvidersClientV2, \)/u,
  );
  assert.match(hook, /policyClient: DesktopWorkspaceAgentPolicyClientV2/u);
  assert.match(hook, /providerClient: Pick<DesktopTenantProvidersClientV2, 'listLlmProviders'>/u);
  assert.doesNotMatch(
    hook,
    /DesktopApiClient|getLlmProviderRoutingPolicy|legacy-routing-policy-v1/u,
  );
  for (const method of [
    'listLlmProviders',
    'getLlmProviderRoutingPolicy',
    'updateLlmProviderRoutingPolicy',
    'createLlmProvider',
    'listLlmProviderTypes',
    'listLlmProviderModels',
    'discoverLlmProviderModels',
    'getLlmProviderUsage',
    'testLlmProviderDraft',
    'updateLlmProvider',
    'deleteLlmProvider',
    'checkLlmProvider',
    'getWorkspaceAgentPolicy',
    'updateWorkspaceAgentPolicy',
  ]) {
    assert.equal(method in DesktopApiClient.prototype, false, `${method} must resolve through V2`);
  }
  assert.match(
    api,
    /function normalizeWorkspaceAgentPolicy\(payload: unknown\): WorkspaceAgentPolicy/u,
  );
  assert.match(api, /policy: normalizeWorkspaceAgentPolicy\(payload\.policy\)/u);
});
