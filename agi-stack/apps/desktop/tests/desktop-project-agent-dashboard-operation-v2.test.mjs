import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopProjectAgentDashboardAuthorityUnavailableErrorV2,
  createDesktopProjectAgentDashboardOperationsV2,
  withDesktopProjectAgentDashboardAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopProjectAgentDashboardAuthorityModuleV2.js');
const { createDesktopProjectAgentDashboardHttpAuthorityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectAgentDashboardHttpProjectionV2.js'
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://cloud.memstack.test',
    apiKey: 'dashboard-session',
    localApiToken: 'dashboard-launch',
    mode: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

function scope(authority = 'cloud', overrides = {}) {
  return {
    authority,
    tenantId: 'tenant-1',
    projectId: 'project-1',
    ...overrides,
  };
}

function result(operationScope = scope(), title = 'Dashboard') {
  return {
    scope: operationScope,
    scopeRevision: 17,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    allowedActions: ['view', 'list-runs', 'inspect-active-count'],
    runs: [
      {
        id: 'run-1',
        title,
        detail: 'Inspect dashboard authority',
        status: 'completed',
        createdAt: '2026-09-03T00:00:00Z',
        summary: null,
      },
    ],
    total: 1,
    activeCount: 1,
  };
}

function serviceFixture(received, overrides = {}) {
  return Object.freeze({
    bindOperation(config, operationScope) {
      received.push({ type: 'bind', config, scope: operationScope });
      return Object.freeze({
        async load(signal) {
          received.push({ type: 'load', signal });
          return overrides.result ?? result(operationScope);
        },
      });
    },
  });
}

function acceptedActions(service, digest, lifecycle = [], releaseError = null) {
  return {
    async acquireServiceOperationLease(request) {
      lifecycle.push({ type: 'acquire', digest, request });
      let released = false;
      return {
        status: 'accepted',
        digest,
        useService(operation) {
          if (released) throw new Error('lease_released');
          return operation(service);
        },
        async release() {
          if (released) return;
          released = true;
          lifecycle.push({ type: 'release', digest });
          if (releaseError) throw releaseError;
        },
      };
    },
  };
}

test('Project Agent Dashboard freezes exact input and holds one project generation lease', async () => {
  const received = [];
  const lifecycle = [];
  const config = runtimeConfig();
  const operationScope = scope();
  const controller = new AbortController();
  const operations = createDesktopProjectAgentDashboardOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-dashboard', lifecycle)
  );
  const pending = operations.loadProjectAgentDashboard({
    config,
    scope: operationScope,
    signal: controller.signal,
  });
  config.tenantId = 'mutated';
  operationScope.projectId = 'mutated';

  const snapshot = await pending;
  assert.equal(snapshot.runs[0].title, 'Dashboard');
  assert.equal(Object.isFrozen(snapshot), true);
  assert.equal(Object.isFrozen(snapshot.scope), true);
  assert.equal(Object.isFrozen(snapshot.allowedActions), true);
  assert.equal(Object.isFrozen(snapshot.runs), true);
  assert.equal(Object.isFrozen(snapshot.runs[0]), true);
  assert.deepEqual(lifecycle, [
    {
      type: 'acquire',
      digest: 'digest-dashboard',
      request: {
        service: 'service:desktop-renderer.project-agent-dashboard-authority',
        version: '1.0.0',
        scope: {
          kind: 'project',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
        },
      },
    },
    { type: 'release', digest: 'digest-dashboard' },
  ]);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(Object.isFrozen(received[0].scope), true);
  assert.deepEqual(received[1], { type: 'load', signal: controller.signal });
});

test('invalid scope, signal, unknown input and absent generation fail before acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopProjectAgentDashboardOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      assert.fail('invalid input must not acquire');
    },
  }));
  for (const invalidInput of [
    { config: runtimeConfig(), scope: scope('local') },
    { config: runtimeConfig(), scope: scope(), signal: {} },
    { config: runtimeConfig(), scope: scope(), extra: true },
  ]) {
    assert.throws(
      () => operations.loadProjectAgentDashboard(invalidInput),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_agent_dashboard_operation_input_invalid'
    );
  }
  assert.equal(acquisitions, 0);
  assert.throws(
    () =>
      createDesktopProjectAgentDashboardOperationsV2(() => null).loadProjectAgentDashboard({
        config: runtimeConfig(),
        scope: scope(),
      }),
    (error) =>
      error instanceof DesktopProjectAgentDashboardAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable'
  );
});

test('missing or malformed service, authority and response fail closed', async () => {
  await assert.rejects(
    createDesktopProjectAgentDashboardOperationsV2(() => ({
      async acquireServiceOperationLease() {
        return {
          status: 'rejected',
          reasonCode: 'missing_service',
          runtimeCode: 'missing_service',
        };
      },
    })).loadProjectAgentDashboard({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof DesktopProjectAgentDashboardAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'missing_service'
  );
  for (const service of [
    Object.freeze({ bindOperation: null }),
    Object.freeze({ bindOperation: () => Object.freeze({ load: null }) }),
  ]) {
    await assert.rejects(
      createDesktopProjectAgentDashboardOperationsV2(() =>
        acceptedActions(service, 'invalid-shape')
      ).loadProjectAgentDashboard({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_agent_dashboard_service_invalid'
    );
  }
  for (const invalidResult of [
    { ...result(), total: 0 },
    { ...result(), activeCount: -1 },
    { ...result(), scopeRevision: -1 },
    { ...result(), runs: [{ ...result().runs[0], id: '' }] },
    { ...result(), scope: scope('cloud', { projectId: 'project-2' }) },
    { ...result(), extra: true },
  ]) {
    await assert.rejects(
      createDesktopProjectAgentDashboardOperationsV2(() =>
        acceptedActions(serviceFixture([], { result: invalidResult }), 'invalid-result')
      ).loadProjectAgentDashboard({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_agent_dashboard_service_contract_invalid'
    );
  }
});

test('HTTP projection keeps all three Cloud reads inside authority and rejects Local before network', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (input, init = {}) => {
    requests.push({ input: String(input), init });
    const url = new URL(String(input));
    if (url.pathname === '/api/v1/workspace-context') {
      return jsonResponse({
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: 19,
        },
      });
    }
    if (url.pathname.endsWith('/active/count')) {
      return jsonResponse({ project_id: 'project-1', active_count: 1 });
    }
    return jsonResponse({ project_id: 'project-1', runs: [rawRun()], total: 1 });
  };
  try {
    const snapshot = await createDesktopProjectAgentDashboardHttpAuthorityV2(
      runtimeConfig(),
      scope()
    ).load();
    assert.equal(snapshot.scopeRevision, 19);
    assert.equal(snapshot.runs[0].id, 'run-1');
    assert.equal(snapshot.activeCount, 1);
    assert.equal(requests.length, 3);
    assert.deepEqual(
      requests
        .slice(1)
        .map(({ input }) => new URL(input).pathname)
        .sort(),
      [
        '/api/v1/agent/trace/runs/project/project-1',
        '/api/v1/agent/trace/runs/project/project-1/active/count',
      ]
    );
    for (const { init } of requests) {
      assert.equal(init.credentials, 'omit');
      assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer dashboard-session');
      assert.doesNotMatch(JSON.stringify(init), /dashboard-launch/u);
    }
    await assert.rejects(
      createDesktopProjectAgentDashboardHttpAuthorityV2(
        runtimeConfig({ mode: 'local' }),
        scope('local')
      ).load(),
      (error) =>
        error.status === 501 &&
        error.payload.reason_code === 'local_project_agent_dashboard_authority_unavailable'
    );
    assert.equal(requests.length, 3);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('escaped authority is revoked and primary failure wins over release failure', async () => {
  let escaped;
  await withDesktopProjectAgentDashboardAuthorityOperationV2(
    acceptedActions(serviceFixture([]), 'digest-a'),
    { config: runtimeConfig(), scope: scope() },
    (authority) => {
      escaped = authority;
      return authority.load();
    }
  );
  await assert.rejects(
    escaped.load(),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_agent_dashboard_operation_released'
  );
  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopProjectAgentDashboardAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-failure', [], release),
      { config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      }
    ),
    (error) => error === primary
  );
  await assert.rejects(
    withDesktopProjectAgentDashboardAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { config: runtimeConfig(), scope: scope() },
      (authority) => authority.load()
    ),
    (error) => error === release
  );
});

test('old Dashboard request stays pinned while replacement generation serves new requests', async () => {
  let releaseOld;
  const gate = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const oldService = serviceFixture([], { result: result(scope(), 'Old Dashboard') });
  const gatedService = Object.freeze({
    bindOperation(...args) {
      const authority = oldService.bindOperation(...args);
      return Object.freeze({
        async load(...loadArgs) {
          await gate;
          return authority.load(...loadArgs);
        },
      });
    },
  });
  let actions = acceptedActions(gatedService, 'old');
  const operations = createDesktopProjectAgentDashboardOperationsV2(() => actions);
  const oldRequest = operations.loadProjectAgentDashboard({
    config: runtimeConfig(),
    scope: scope(),
  });
  actions = acceptedActions(
    serviceFixture([], { result: result(scope(), 'New Dashboard') }),
    'new'
  );
  const newRequest = operations.loadProjectAgentDashboard({
    config: runtimeConfig(),
    scope: scope(),
  });
  releaseOld();
  assert.equal((await oldRequest).runs[0].title, 'Old Dashboard');
  assert.equal((await newRequest).runs[0].title, 'New Dashboard');
});

function rawRun() {
  return {
    run_id: 'run-1',
    subagent_name: 'Dashboard',
    task: 'Inspect dashboard authority',
    status: 'completed',
    created_at: '2026-09-03T00:00:00Z',
    summary: null,
  };
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
