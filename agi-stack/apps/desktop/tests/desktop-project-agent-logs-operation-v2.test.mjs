import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopProjectAgentLogsAuthorityUnavailableErrorV2,
  createDesktopProjectAgentLogsOperationsV2,
  withDesktopProjectAgentLogsAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopProjectAgentLogsAuthorityModuleV2.js');
const { createDesktopProjectAgentLogsHttpAuthorityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectAgentLogsHttpProjectionV2.js'
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://cloud.memstack.test',
    apiKey: 'logs-secret',
    localApiToken: 'logs-launch',
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

function result(operationScope = scope(), title = 'Logs') {
  return {
    scope: operationScope,
    scopeRevision: 17,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    allowedActions: ['view', 'list-runs', 'filter-status'],
    runs: [
      {
        id: 'run-1',
        title,
        detail: 'Inspect authority',
        status: 'completed',
        createdAt: '2026-09-03T00:00:00Z',
        summary: null,
      },
    ],
    total: 1,
  };
}

function serviceFixture(received, overrides = {}) {
  return Object.freeze({
    bindOperation(config, operationScope) {
      received.push({ type: 'bind', config, scope: operationScope });
      return Object.freeze({
        async load(status, limit, signal) {
          received.push({ type: 'load', status, limit, signal });
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

test('Project Agent Logs freezes exact input and holds one project generation lease', async () => {
  const received = [];
  const lifecycle = [];
  const config = runtimeConfig();
  const operationScope = scope();
  const controller = new AbortController();
  const operations = createDesktopProjectAgentLogsOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-logs', lifecycle)
  );
  const pending = operations.loadProjectAgentLogs({
    config,
    scope: operationScope,
    status: 'completed',
    limit: 25,
    signal: controller.signal,
  });
  config.tenantId = 'mutated';
  operationScope.projectId = 'mutated';

  assert.equal((await pending).runs[0].title, 'Logs');
  assert.deepEqual(lifecycle, [
    {
      type: 'acquire',
      digest: 'digest-logs',
      request: {
        service: 'service:desktop-renderer.project-agent-logs-authority',
        version: '1.0.0',
        scope: {
          kind: 'project',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
        },
      },
    },
    { type: 'release', digest: 'digest-logs' },
  ]);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(Object.isFrozen(received[0].scope), true);
  assert.deepEqual(received[1], {
    type: 'load',
    status: 'completed',
    limit: 25,
    signal: controller.signal,
  });
});

test('invalid scope, status, limit, signal and absent generation fail before acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopProjectAgentLogsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      assert.fail('invalid input must not acquire');
    },
  }));
  for (const invalidInput of [
    { config: runtimeConfig(), scope: scope('local') },
    { config: runtimeConfig(), scope: scope(), status: ' completed' },
    { config: runtimeConfig(), scope: scope(), limit: 0 },
    { config: runtimeConfig(), scope: scope(), limit: 201 },
    { config: runtimeConfig(), scope: scope(), signal: {} },
    { config: runtimeConfig(), scope: scope(), extra: true },
  ]) {
    assert.throws(
      () => operations.loadProjectAgentLogs(invalidInput),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_agent_logs_operation_input_invalid'
    );
  }
  assert.equal(acquisitions, 0);
  assert.throws(
    () =>
      createDesktopProjectAgentLogsOperationsV2(() => null).loadProjectAgentLogs({
        config: runtimeConfig(),
        scope: scope(),
      }),
    (error) =>
      error instanceof DesktopProjectAgentLogsAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable'
  );
});

test('malformed service, authority and response fail closed', async () => {
  await assert.rejects(
    createDesktopProjectAgentLogsOperationsV2(() => ({
      async acquireServiceOperationLease() {
        return {
          status: 'rejected',
          reasonCode: 'missing_service',
          runtimeCode: 'missing_service',
        };
      },
    })).loadProjectAgentLogs({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof DesktopProjectAgentLogsAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'missing_service'
  );
  for (const service of [
    Object.freeze({ bindOperation: null }),
    Object.freeze({ bindOperation: () => Object.freeze({ load: null }) }),
  ]) {
    await assert.rejects(
      createDesktopProjectAgentLogsOperationsV2(() =>
        acceptedActions(service, 'invalid-shape')
      ).loadProjectAgentLogs({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_agent_logs_service_invalid'
    );
  }
  await assert.rejects(
    createDesktopProjectAgentLogsOperationsV2(() =>
      acceptedActions(serviceFixture([], { result: { ...result(), total: 0 } }), 'invalid-result')
    ).loadProjectAgentLogs({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_agent_logs_service_contract_invalid'
  );
});

test('HTTP projection uses Cloud authority and rejects Local before network access', async () => {
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
    return jsonResponse({
      project_id: 'project-1',
      runs: [rawRun()],
      total: 1,
    });
  };
  try {
    const snapshot = await createDesktopProjectAgentLogsHttpAuthorityV2(
      runtimeConfig(),
      scope()
    ).load('completed', 20);
    assert.equal(snapshot.scopeRevision, 19);
    assert.equal(snapshot.runs[0].id, 'run-1');
    assert.match(requests[1].input, /status=completed&limit=20/u);
    await assert.rejects(
      createDesktopProjectAgentLogsHttpAuthorityV2(
        runtimeConfig({ mode: 'local' }),
        scope('local')
      ).load(undefined, 100),
      (error) =>
        error.status === 501 &&
        error.payload.reason_code === 'local_project_agent_logs_authority_unavailable'
    );
    assert.equal(requests.length, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('escaped authority is revoked and primary failure wins over release failure', async () => {
  let escaped;
  await withDesktopProjectAgentLogsAuthorityOperationV2(
    acceptedActions(serviceFixture([]), 'digest-a'),
    { config: runtimeConfig(), scope: scope() },
    (authority) => {
      escaped = authority;
      return authority.load(undefined, 100);
    }
  );
  await assert.rejects(
    escaped.load(undefined, 100),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_agent_logs_operation_released'
  );
  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopProjectAgentLogsAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-failure', [], release),
      { config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      }
    ),
    (error) => error === primary
  );
  await assert.rejects(
    withDesktopProjectAgentLogsAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { config: runtimeConfig(), scope: scope() },
      (authority) => authority.load(undefined, 100)
    ),
    (error) => error === release
  );
});

test('old Logs request remains pinned while replacement generation serves new requests', async () => {
  let releaseOld;
  const gate = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const oldService = serviceFixture([], {
    result: result(scope(), 'Old Logs'),
  });
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
  const operations = createDesktopProjectAgentLogsOperationsV2(() => actions);
  const oldRequest = operations.loadProjectAgentLogs({
    config: runtimeConfig(),
    scope: scope(),
  });
  actions = acceptedActions(serviceFixture([], { result: result(scope(), 'New Logs') }), 'new');
  const newRequest = operations.loadProjectAgentLogs({
    config: runtimeConfig(),
    scope: scope(),
  });
  releaseOld();
  assert.equal((await oldRequest).runs[0].title, 'Old Logs');
  assert.equal((await newRequest).runs[0].title, 'New Logs');
});

function rawRun() {
  return {
    run_id: 'run-1',
    subagent_name: 'Logs',
    task: 'Inspect authority',
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
