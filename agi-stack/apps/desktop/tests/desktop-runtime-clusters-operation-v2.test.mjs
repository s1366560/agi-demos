import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopRuntimeClustersAuthorityUnavailableErrorV2,
  createDesktopRuntimeClustersOperationsV2,
  withDesktopRuntimeClustersAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopRuntimeClustersAuthorityModuleV2.js');
const { createDesktopRuntimeClustersHttpAuthorityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopRuntimeClustersHttpProjectionV2.js',
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

const CLOUD_ACTIONS = Object.freeze([
  'view',
  'list',
  'refresh',
  'search-current-page',
  'filter-status-current-page',
  'paginate',
  'inspect-health',
]);

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://cloud.memstack.test',
    deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
    apiKey: 'clusters-session',
    localApiToken: 'clusters-launch',
    mode: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

function scope(authority = 'cloud', overrides = {}) {
  return { authority, tenantId: 'tenant-1', ...overrides };
}

function cluster(id = 'cluster-1') {
  return {
    id,
    name: 'Primary',
    computeProvider: 'kubernetes',
    proxyEndpoint: 'https://cluster.memstack.test',
    status: 'active',
    healthStatus: 'healthy',
    lastHealthCheck: null,
    createdAt: '2026-09-03T00:00:00Z',
    updatedAt: null,
  };
}

function page(overrides = {}) {
  return { clusters: [cluster()], total: 1, page: 1, pageSize: 20, ...overrides };
}

function health(overrides = {}) {
  return {
    status: 'healthy',
    nodeCount: 3,
    cpuUsage: 20.5,
    memoryUsage: 40.25,
    checkedAt: null,
    ...overrides,
  };
}

function capability(operationScope = scope()) {
  const local = operationScope.authority === 'local';
  return {
    availability: local ? 'not_applicable' : 'degraded',
    reason_code: local
      ? 'cloud_cluster_control_not_applicable'
      : 'runtime_clusters_detail_and_mutations_partial',
    service_version: local ? null : '0.1.0',
    contract_version: local ? null : '3.0.0',
    allowed_actions: local ? [] : [...CLOUD_ACTIONS],
    scope: {
      tenant_id: operationScope.tenantId,
      project_id: null,
      workspace_id: null,
      instance_id: null,
    },
    authority_revision: null,
  };
}

function serviceFixture(received, overrides = {}) {
  return Object.freeze({
    bindOperation(config, operationScope) {
      received.push({ type: 'bind', config, scope: operationScope });
      return Object.freeze({
        async list(query, signal) {
          received.push({ type: 'list', query, signal });
          return overrides.page ?? page({ page: query.page, pageSize: query.pageSize });
        },
        async getHealth(clusterId, signal) {
          received.push({ type: 'getHealth', clusterId, signal });
          return overrides.health ?? health();
        },
        async probe(signal) {
          received.push({ type: 'probe', signal });
          return overrides.capability ?? capability(operationScope);
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

test('Runtime Clusters operations freeze inputs and acquire one exact tenant lease per call', async () => {
  const received = [];
  const lifecycle = [];
  const config = runtimeConfig();
  const operationScope = scope();
  const query = { page: 2, pageSize: 25, search: 'primary', status: 'active' };
  const controller = new AbortController();
  const operations = createDesktopRuntimeClustersOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-clusters', lifecycle),
  );

  const pending = operations.listRuntimeClusters({
    config,
    scope: operationScope,
    query,
    signal: controller.signal,
  });
  config.tenantId = 'mutated';
  operationScope.tenantId = 'mutated';
  query.page = 9;
  const result = await pending;
  await operations.getRuntimeClusterHealth({
    config: runtimeConfig(),
    scope: scope(),
    clusterId: 'cluster-1',
  });
  await operations.probeRuntimeClusters({ config: runtimeConfig(), scope: scope() });

  for (const value of [result, result.clusters, result.clusters[0]]) {
    assert.equal(Object.isFrozen(value), true);
  }
  assert.equal(lifecycle.filter(({ type }) => type === 'acquire').length, 3);
  assert.equal(lifecycle.filter(({ type }) => type === 'release').length, 3);
  for (const event of lifecycle.filter(({ type }) => type === 'acquire')) {
    assert.deepEqual(event.request, {
      service: 'service:desktop-renderer.runtime-clusters-authority',
      version: '1.0.0',
      scope: { kind: 'tenant', tenant_id: 'tenant-1' },
    });
  }
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(Object.isFrozen(received[0].scope), true);
  assert.deepEqual(received[1], {
    type: 'list',
    query: { page: 2, pageSize: 25, search: 'primary', status: 'active' },
    signal: controller.signal,
  });
});

test('invalid config, scope, query, identity, signal and unknown fields fail before acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopRuntimeClustersOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      assert.fail('invalid input must not acquire');
    },
  }));
  for (const invalidInput of [
    { config: runtimeConfig({ mode: 'remote' }), scope: scope() },
    { config: runtimeConfig(), scope: scope('local') },
    { config: runtimeConfig(), scope: scope(), signal: {} },
    { config: runtimeConfig(), scope: scope(), query: { pageSize: 101 } },
    { config: runtimeConfig(), scope: scope(), query: { search: 'x'.repeat(201) } },
    { config: runtimeConfig(), scope: scope(), extra: true },
  ]) {
    assert.throws(
      () => operations.listRuntimeClusters(invalidInput),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_runtime_clusters_operation_input_invalid',
    );
  }
  for (const clusterId of ['', ' cluster-1']) {
    assert.throws(
      () =>
        operations.getRuntimeClusterHealth({
          config: runtimeConfig(),
          scope: scope(),
          clusterId,
        }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_runtime_clusters_operation_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
  assert.throws(
    () =>
      createDesktopRuntimeClustersOperationsV2(() => null).listRuntimeClusters({
        config: runtimeConfig(),
        scope: scope(),
      }),
    (error) =>
      error instanceof DesktopRuntimeClustersAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
});

test('missing or malformed service, authority and response contracts fail closed', async () => {
  await assert.rejects(
    createDesktopRuntimeClustersOperationsV2(() => ({
      async acquireServiceOperationLease() {
        return { status: 'rejected', reasonCode: 'missing_service', runtimeCode: 'missing_service' };
      },
    })).listRuntimeClusters({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof DesktopRuntimeClustersAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'missing_service',
  );
  for (const service of [
    Object.freeze({ bindOperation: null }),
    Object.freeze({ bindOperation: () => Object.freeze({ list: null }) }),
    Object.freeze({
      bindOperation: () => Object.freeze({ list: async () => page(), getHealth: null, probe: null }),
    }),
  ]) {
    await assert.rejects(
      createDesktopRuntimeClustersOperationsV2(() =>
        acceptedActions(service, 'invalid-shape'),
      ).listRuntimeClusters({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_runtime_clusters_service_invalid',
    );
  }
  for (const invalidPage of [
    { ...page(), total: 0 },
    { ...page(), page: 0 },
    { ...page(), clusters: [{ ...cluster(), id: '' }] },
    { ...page(), clusters: [cluster(), cluster()] },
    { ...page(), extra: true },
  ]) {
    await assert.rejects(
      createDesktopRuntimeClustersOperationsV2(() =>
        acceptedActions(serviceFixture([], { page: invalidPage }), 'invalid-page'),
      ).listRuntimeClusters({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_runtime_clusters_service_contract_invalid',
    );
  }
  for (const invalidHealth of [
    { ...health(), nodeCount: -1 },
    { ...health(), cpuUsage: Number.NaN },
    { ...health(), extra: true },
  ]) {
    await assert.rejects(
      createDesktopRuntimeClustersOperationsV2(() =>
        acceptedActions(serviceFixture([], { health: invalidHealth }), 'invalid-health'),
      ).getRuntimeClusterHealth({
        config: runtimeConfig(),
        scope: scope(),
        clusterId: 'cluster-1',
      }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_runtime_clusters_service_contract_invalid',
    );
  }
  await assert.rejects(
    createDesktopRuntimeClustersOperationsV2(() =>
      acceptedActions(
        serviceFixture([], { capability: { ...capability(), allowed_actions: ['view'] } }),
        'invalid-capability',
      ),
    ).probeRuntimeClusters({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_runtime_clusters_service_contract_invalid',
  );
});

test('HTTP projection uses the vault-bound Cloud path and rejects Local before network', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (input, init = {}) => {
    requests.push({ input: String(input), init });
    if (String(input).endsWith('/health')) {
      return jsonResponse({
        status: 'healthy',
        node_count: 3,
        cpu_usage: 20.5,
        memory_usage: 40.25,
        checked_at: null,
        registration_token: 'must-not-cross-renderer',
      });
    }
    return jsonResponse({
      clusters: [
        {
          id: 'cluster-1',
          name: 'Primary',
          tenant_id: 'tenant-1',
          compute_provider: 'kubernetes',
          proxy_endpoint: null,
          status: 'active',
          health_status: 'healthy',
          last_health_check: null,
          created_at: '2026-09-03T00:00:00Z',
          updated_at: null,
          provider_config: { kubeconfig: 'must-not-cross-renderer' },
        },
      ],
      total: 1,
      page: 2,
      page_size: 25,
    });
  };
  try {
    const authority = createDesktopRuntimeClustersHttpAuthorityV2(runtimeConfig(), scope());
    const result = await authority.list({ page: 2, pageSize: 25, search: '', status: 'all' });
    assert.equal(result.clusters[0].id, 'cluster-1');
    assert.equal(JSON.stringify(result).includes('kubeconfig'), false);
    assert.match(requests[0].input, /clusters\/\?page=2&page_size=25$/u);
    assert.equal(new Headers(requests[0].init.headers).get('Authorization'), 'Bearer clusters-session');
    assert.doesNotMatch(JSON.stringify(requests[0].init), /clusters-launch/u);
    const observedHealth = await authority.getHealth('cluster-1');
    assert.equal(observedHealth.nodeCount, 3);
    assert.equal(JSON.stringify(observedHealth).includes('registration_token'), false);
    const observedCapability = await authority.probe();
    assert.deepEqual(observedCapability, capability());
    assert.equal(requests.length, 3);

    const local = createDesktopRuntimeClustersHttpAuthorityV2(
      runtimeConfig({ mode: 'local' }),
      scope('local'),
    );
    await assert.rejects(
      local.list({ page: 1, pageSize: 20, search: '', status: 'all' }),
      (error) => error.reasonCode === 'cloud_cluster_control_not_applicable',
    );
    await assert.rejects(
      local.getHealth('cluster-1'),
      (error) => error.reasonCode === 'cloud_cluster_control_not_applicable',
    );
    assert.deepEqual(await local.probe(), capability(scope('local')));
    assert.equal(requests.length, 3);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('escaped authority is revoked and primary operation failure wins over release failure', async () => {
  let escaped;
  await withDesktopRuntimeClustersAuthorityOperationV2(
    acceptedActions(serviceFixture([]), 'digest-a'),
    { kind: 'list', config: runtimeConfig(), scope: scope() },
    (authority) => {
      escaped = authority;
      return authority.list({ page: 1, pageSize: 20, search: '', status: 'all' });
    },
  );
  await assert.rejects(
    escaped.probe(),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_runtime_clusters_operation_released',
  );
  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopRuntimeClustersAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-primary', [], release),
      { kind: 'probe', config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  await assert.rejects(
    withDesktopRuntimeClustersAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { kind: 'probe', config: runtimeConfig(), scope: scope() },
      (authority) => authority.probe(),
    ),
    (error) => error === release,
  );
});

test('old Runtime Clusters request stays pinned while the next request uses a new generation', async () => {
  let releaseOld;
  const gate = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const oldService = serviceFixture([], { page: page({ clusters: [cluster('old-cluster')] }) });
  const gatedService = Object.freeze({
    bindOperation(...args) {
      const authority = oldService.bindOperation(...args);
      return Object.freeze({
        async list(...listArgs) {
          await gate;
          return authority.list(...listArgs);
        },
        getHealth: authority.getHealth,
        probe: authority.probe,
      });
    },
  });
  let actions = acceptedActions(gatedService, 'old');
  const operations = createDesktopRuntimeClustersOperationsV2(() => actions);
  const oldRequest = operations.listRuntimeClusters({ config: runtimeConfig(), scope: scope() });
  actions = acceptedActions(
    serviceFixture([], { page: page({ clusters: [cluster('new-cluster')] }) }),
    'new',
  );
  const newRequest = operations.listRuntimeClusters({ config: runtimeConfig(), scope: scope() });
  releaseOld();
  assert.equal((await oldRequest).clusters[0].id, 'old-cluster');
  assert.equal((await newRequest).clusters[0].id, 'new-cluster');
});

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
