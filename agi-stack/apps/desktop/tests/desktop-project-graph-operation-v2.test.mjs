import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopProjectGraphAuthorityUnavailableErrorV2,
  createDesktopProjectGraphOperationsV2,
  withDesktopProjectGraphAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopProjectGraphAuthorityModuleV2.js');
const { createDesktopProjectGraphHttpAuthorityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectGraphHttpProjectionV2.js',
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://cloud.memstack.test',
    apiKey: 'graph-session',
    localApiToken: 'graph-launch',
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

function result(operationScope = scope(), name = 'Memory node') {
  return {
    scope: operationScope,
    scopeRevision: 23,
    authority: 'cloud',
    availability: 'degraded',
    reasonCode: 'desktop_project_graph_actions_partial',
    allowedActions: ['view'],
    nodes: [
      {
        id: 'node-1',
        label: 'Memory',
        type: 'Entity',
        name,
        summary: null,
      },
      {
        id: 'node-2',
        label: 'Episode',
        type: 'Episodic',
        name: 'Episode node',
        summary: 'Grounded summary',
      },
    ],
    edges: [
      {
        id: 'edge-1',
        source: 'node-1',
        target: 'node-2',
        label: 'RELATES_TO',
        weight: 0.75,
      },
    ],
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

test('Project Graph freezes exact input and holds one project generation lease', async () => {
  const received = [];
  const lifecycle = [];
  const config = runtimeConfig();
  const operationScope = scope();
  const controller = new AbortController();
  const operations = createDesktopProjectGraphOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-graph', lifecycle),
  );
  const pending = operations.loadProjectGraph({
    config,
    scope: operationScope,
    signal: controller.signal,
  });
  config.tenantId = 'mutated';
  operationScope.projectId = 'mutated';

  const snapshot = await pending;
  assert.equal(snapshot.nodes[0].name, 'Memory node');
  for (const value of [
    snapshot,
    snapshot.scope,
    snapshot.allowedActions,
    snapshot.nodes,
    snapshot.nodes[0],
    snapshot.edges,
    snapshot.edges[0],
  ]) {
    assert.equal(Object.isFrozen(value), true);
  }
  assert.deepEqual(lifecycle, [
    {
      type: 'acquire',
      digest: 'digest-graph',
      request: {
        service: 'service:desktop-renderer.project-graph-authority',
        version: '1.0.0',
        scope: {
          kind: 'project',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
        },
      },
    },
    { type: 'release', digest: 'digest-graph' },
  ]);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(Object.isFrozen(received[0].scope), true);
  assert.deepEqual(received[1], { type: 'load', signal: controller.signal });
});

test('invalid mode, scope, signal, unknown input and absent generation fail before acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopProjectGraphOperationsV2(() => ({
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
      () => operations.loadProjectGraph(invalidInput),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_graph_operation_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
  assert.throws(
    () =>
      createDesktopProjectGraphOperationsV2(() => null).loadProjectGraph({
        config: runtimeConfig(),
        scope: scope(),
      }),
    (error) =>
      error instanceof DesktopProjectGraphAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
});

test('missing or malformed service, authority and graph response fail closed', async () => {
  await assert.rejects(
    createDesktopProjectGraphOperationsV2(() => ({
      async acquireServiceOperationLease() {
        return { status: 'rejected', reasonCode: 'missing_service', runtimeCode: 'missing_service' };
      },
    })).loadProjectGraph({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof DesktopProjectGraphAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'missing_service',
  );
  for (const service of [
    Object.freeze({ bindOperation: null }),
    Object.freeze({ bindOperation: () => Object.freeze({ load: null }) }),
  ]) {
    await assert.rejects(
      createDesktopProjectGraphOperationsV2(() =>
        acceptedActions(service, 'invalid-shape'),
      ).loadProjectGraph({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_graph_service_invalid',
    );
  }
  const valid = result();
  for (const invalidResult of [
    { ...valid, availability: 'available', reasonCode: null },
    { ...valid, reasonCode: 'another_reason' },
    { ...valid, allowedActions: ['view', 'inspect-node'] },
    { ...valid, scopeRevision: -1 },
    { ...valid, scope: scope('cloud', { projectId: 'project-2' }) },
    { ...valid, nodes: [{ ...valid.nodes[0], type: 'Unknown' }] },
    { ...valid, nodes: [valid.nodes[0], { ...valid.nodes[0] }] },
    { ...valid, edges: [{ ...valid.edges[0], target: 'missing-node' }] },
    { ...valid, edges: [{ ...valid.edges[0], weight: Number.NaN }] },
    { ...valid, extra: true },
  ]) {
    await assert.rejects(
      createDesktopProjectGraphOperationsV2(() =>
        acceptedActions(serviceFixture([], { result: invalidResult }), 'invalid-result'),
      ).loadProjectGraph({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_graph_service_contract_invalid',
    );
  }
});

test('HTTP projection keeps scope observation and graph GET in one authority operation', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (input, init = {}) => {
    requests.push({ input: String(input), init });
    const url = new URL(String(input));
    if (url.pathname === '/api/v1/workspace-context') {
      return jsonResponse({
        context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 29 },
      });
    }
    return jsonResponse({
      elements: {
        nodes: [
          {
            data: {
              id: 'node-1',
              label: 'Memory',
              type: 'Entity',
              name: 'Memory node',
              summary: null,
              tenant_id: 'tenant-1',
              project_id: 'project-1',
            },
          },
        ],
        edges: [],
      },
    });
  };
  try {
    const snapshot = await createDesktopProjectGraphHttpAuthorityV2(
      runtimeConfig(),
      scope(),
    ).load();
    assert.equal(snapshot.scopeRevision, 29);
    assert.equal(snapshot.reasonCode, 'desktop_project_graph_actions_partial');
    assert.deepEqual(snapshot.allowedActions, ['view']);
    assert.equal(snapshot.nodes[0].id, 'node-1');
    assert.equal(requests.length, 2);
    const graphUrl = new URL(requests[1].input);
    assert.equal(graphUrl.pathname, '/api/v1/graph/memory/graph');
    assert.equal(graphUrl.searchParams.get('tenant_id'), 'tenant-1');
    assert.equal(graphUrl.searchParams.get('project_id'), 'project-1');
    assert.equal(graphUrl.searchParams.get('limit'), '1000');
    for (const { init } of requests) {
      assert.equal(init.credentials, 'omit');
      assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer graph-session');
      assert.doesNotMatch(JSON.stringify(init), /graph-launch/u);
    }
    await assert.rejects(
      createDesktopProjectGraphHttpAuthorityV2(
        runtimeConfig({ mode: 'local' }),
        scope('local'),
      ).load(),
      (error) =>
        error.status === 501 &&
        error.payload.reason_code === 'local_project_graph_authority_unavailable',
    );
    assert.equal(requests.length, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('escaped Graph authority is revoked and primary failure wins over release failure', async () => {
  let escaped;
  await withDesktopProjectGraphAuthorityOperationV2(
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
      error.code === 'desktop_project_graph_operation_released',
  );
  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopProjectGraphAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-failure', [], release),
      { config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  await assert.rejects(
    withDesktopProjectGraphAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { config: runtimeConfig(), scope: scope() },
      (authority) => authority.load(),
    ),
    (error) => error === release,
  );
});

test('old Graph request stays pinned while replacement generation serves new requests', async () => {
  let releaseOld;
  const gate = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const oldService = serviceFixture([], { result: result(scope(), 'Old Graph') });
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
  const operations = createDesktopProjectGraphOperationsV2(() => actions);
  const oldRequest = operations.loadProjectGraph({
    config: runtimeConfig(),
    scope: scope(),
  });
  actions = acceptedActions(
    serviceFixture([], { result: result(scope(), 'New Graph') }),
    'new',
  );
  const newRequest = operations.loadProjectGraph({
    config: runtimeConfig(),
    scope: scope(),
  });
  releaseOld();
  assert.equal((await oldRequest).nodes[0].name, 'Old Graph');
  assert.equal((await newRequest).nodes[0].name, 'New Graph');
});

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
