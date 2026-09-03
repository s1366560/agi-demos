import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopProjectAgentPatternsAuthorityUnavailableErrorV2,
  createDesktopProjectAgentPatternsOperationsV2,
  withDesktopProjectAgentPatternsAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopProjectAgentPatternsAuthorityModuleV2.js');
const { createDesktopProjectAgentPatternsHttpAuthorityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectAgentPatternsHttpProjectionV2.js',
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://cloud.memstack.test',
    apiKey: 'patterns-session',
    localApiToken: 'patterns-launch',
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

function result(operationScope = scope(), name = 'Review pattern') {
  return {
    scope: operationScope,
    scopeRevision: 17,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    allowedActions: ['view', 'list-patterns', 'inspect-shared-scope'],
    scopeKind: 'tenant_shared',
    patterns: [
      {
        id: 'pattern-1',
        tenantId: 'tenant-1',
        name,
        description: 'Shared review workflow',
        successRate: 0.75,
        usageCount: 2,
        createdAt: '2026-09-03T00:00:00Z',
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

test('Project Agent Patterns freezes exact input and holds one project generation lease', async () => {
  const received = [];
  const lifecycle = [];
  const config = runtimeConfig();
  const operationScope = scope();
  const controller = new AbortController();
  const operations = createDesktopProjectAgentPatternsOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-patterns', lifecycle),
  );
  const pending = operations.loadProjectAgentPatterns({
    config,
    scope: operationScope,
    signal: controller.signal,
  });
  config.tenantId = 'mutated';
  operationScope.projectId = 'mutated';

  const snapshot = await pending;
  assert.equal(snapshot.patterns[0].name, 'Review pattern');
  for (const value of [snapshot, snapshot.scope, snapshot.allowedActions, snapshot.patterns, snapshot.patterns[0]]) {
    assert.equal(Object.isFrozen(value), true);
  }
  assert.deepEqual(lifecycle, [
    {
      type: 'acquire',
      digest: 'digest-patterns',
      request: {
        service: 'service:desktop-renderer.project-agent-patterns-authority',
        version: '1.0.0',
        scope: {
          kind: 'project',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
        },
      },
    },
    { type: 'release', digest: 'digest-patterns' },
  ]);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(Object.isFrozen(received[0].scope), true);
  assert.deepEqual(received[1], { type: 'load', signal: controller.signal });
});

test('invalid mode, scope, signal, unknown input and absent generation fail before acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopProjectAgentPatternsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      assert.fail('invalid input must not acquire');
    },
  }));
  for (const invalidInput of [
    { config: runtimeConfig({ mode: 'remote' }), scope: scope() },
    { config: runtimeConfig(), scope: scope('local') },
    { config: runtimeConfig(), scope: scope(), signal: {} },
    { config: runtimeConfig(), scope: scope(), extra: true },
  ]) {
    assert.throws(
      () => operations.loadProjectAgentPatterns(invalidInput),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_agent_patterns_operation_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
  assert.throws(
    () =>
      createDesktopProjectAgentPatternsOperationsV2(() => null).loadProjectAgentPatterns({
        config: runtimeConfig(),
        scope: scope(),
      }),
    (error) =>
      error instanceof DesktopProjectAgentPatternsAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
});

test('missing or malformed service, authority and response fail closed', async () => {
  await assert.rejects(
    createDesktopProjectAgentPatternsOperationsV2(() => ({
      async acquireServiceOperationLease() {
        return { status: 'rejected', reasonCode: 'missing_service', runtimeCode: 'missing_service' };
      },
    })).loadProjectAgentPatterns({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof DesktopProjectAgentPatternsAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'missing_service',
  );
  for (const service of [
    Object.freeze({ bindOperation: null }),
    Object.freeze({ bindOperation: () => Object.freeze({ load: null }) }),
  ]) {
    await assert.rejects(
      createDesktopProjectAgentPatternsOperationsV2(() =>
        acceptedActions(service, 'invalid-shape'),
      ).loadProjectAgentPatterns({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_agent_patterns_service_invalid',
    );
  }
  for (const invalidResult of [
    { ...result(), scopeKind: 'project' },
    { ...result(), total: 0 },
    { ...result(), patterns: [{ ...result().patterns[0], tenantId: 'tenant-2' }] },
    { ...result(), patterns: [{ ...result().patterns[0], successRate: 1.1 }] },
    { ...result(), patterns: [{ ...result().patterns[0], usageCount: -1 }] },
    { ...result(), patterns: [{ ...result().patterns[0], createdAt: '' }] },
    { ...result(), scopeRevision: -1 },
    { ...result(), scope: scope('cloud', { projectId: 'project-2' }) },
    { ...result(), extra: true },
  ]) {
    await assert.rejects(
      createDesktopProjectAgentPatternsOperationsV2(() =>
        acceptedActions(serviceFixture([], { result: invalidResult }), 'invalid-result'),
      ).loadProjectAgentPatterns({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_agent_patterns_service_contract_invalid',
    );
  }
});

test('HTTP projection keeps workspace and patterns reads inside authority and rejects Local before network', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (input, init = {}) => {
    requests.push({ input: String(input), init });
    const url = new URL(String(input));
    if (url.pathname === '/api/v1/workspace-context') {
      return jsonResponse({
        context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 19 },
      });
    }
    return jsonResponse({
      project_id: 'project-1',
      tenant_id: 'tenant-1',
      scope_kind: 'tenant_shared',
      patterns: [rawPattern()],
      total: 1,
      page: 1,
      page_size: 100,
    });
  };
  try {
    const snapshot = await createDesktopProjectAgentPatternsHttpAuthorityV2(
      runtimeConfig(),
      scope(),
    ).load();
    assert.equal(snapshot.scopeRevision, 19);
    assert.equal(snapshot.scopeKind, 'tenant_shared');
    assert.equal(snapshot.patterns[0].id, 'pattern-1');
    assert.equal(requests.length, 2);
    assert.equal(
      new URL(requests[1].input).pathname,
      '/api/v1/agent/workflows/patterns/project/project-1',
    );
    for (const { init } of requests) {
      assert.equal(init.credentials, 'omit');
      assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer patterns-session');
      assert.doesNotMatch(JSON.stringify(init), /patterns-launch/u);
    }
    await assert.rejects(
      createDesktopProjectAgentPatternsHttpAuthorityV2(
        runtimeConfig({ mode: 'local' }),
        scope('local'),
      ).load(),
      (error) =>
        error.status === 501 &&
        error.payload.reason_code === 'local_project_agent_patterns_authority_unavailable',
    );
    assert.equal(requests.length, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('escaped authority is revoked and primary failure wins over release failure', async () => {
  let escaped;
  await withDesktopProjectAgentPatternsAuthorityOperationV2(
    acceptedActions(serviceFixture([]), 'digest-a'),
    { config: runtimeConfig(), scope: scope() },
    (authority) => {
      escaped = authority;
      return authority.load();
    },
  );
  await assert.rejects(
    escaped.load(),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_agent_patterns_operation_released',
  );
  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopProjectAgentPatternsAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-failure', [], release),
      { config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  await assert.rejects(
    withDesktopProjectAgentPatternsAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { config: runtimeConfig(), scope: scope() },
      (authority) => authority.load(),
    ),
    (error) => error === release,
  );
});

test('old Patterns request stays pinned while replacement generation serves new requests', async () => {
  let releaseOld;
  const gate = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const oldService = serviceFixture([], { result: result(scope(), 'Old Pattern') });
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
  const operations = createDesktopProjectAgentPatternsOperationsV2(() => actions);
  const oldRequest = operations.loadProjectAgentPatterns({
    config: runtimeConfig(),
    scope: scope(),
  });
  actions = acceptedActions(
    serviceFixture([], { result: result(scope(), 'New Pattern') }),
    'new',
  );
  const newRequest = operations.loadProjectAgentPatterns({
    config: runtimeConfig(),
    scope: scope(),
  });
  releaseOld();
  assert.equal((await oldRequest).patterns[0].name, 'Old Pattern');
  assert.equal((await newRequest).patterns[0].name, 'New Pattern');
});

function rawPattern() {
  return {
    id: 'pattern-1',
    tenant_id: 'tenant-1',
    name: 'Review pattern',
    description: 'Shared review workflow',
    success_rate: 0.75,
    usage_count: 2,
    created_at: '2026-09-03T00:00:00Z',
  };
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
