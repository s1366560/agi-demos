import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopProjectMaintenanceAuthorityUnavailableErrorV2,
  createDesktopProjectMaintenanceOperationsV2,
  withDesktopProjectMaintenanceAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopProjectMaintenanceAuthorityModuleV2.js');
const { createDesktopProjectMaintenanceHttpAuthorityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectMaintenanceHttpProjectionV2.js',
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://cloud.memstack.test',
    apiKey: 'maintenance-session',
    localApiToken: 'maintenance-launch',
    mode: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

function scope(authority = 'cloud', overrides = {}) {
  return { authority, tenantId: 'tenant-1', projectId: 'project-1', ...overrides };
}

function result(operationScope = scope(), entityCount = 4) {
  return {
    scope: operationScope,
    scopeRevision: 74,
    authority: 'cloud',
    availability: 'degraded',
    reasonCode: 'desktop_project_maintenance_surface_and_endpoints_incomplete',
    contractVersion: '4.0.0',
    allowedActions: ['view'],
    membershipRole: 'member',
    stats: { entityCount, episodeCount: 5, communityCount: 2, edgeCount: 8 },
    maintenanceStatus: {
      entities: entityCount,
      episodes: 5,
      communities: 2,
      oldEpisodes: 1,
      recommendations: ['refresh'],
      lastChecked: '2026-09-03T00:00:00Z',
    },
    embeddingStatus: {
      currentProvider: 'openai',
      currentDimension: 1536,
      existingDimension: 1536,
      compatible: true,
      missingEmbeddings: 0,
    },
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

test('Project Maintenance load pins frozen input and result to one project lease', async () => {
  const received = [];
  const lifecycle = [];
  const config = runtimeConfig();
  const operationScope = scope();
  const controller = new AbortController();
  const operations = createDesktopProjectMaintenanceOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-maintenance', lifecycle),
  );
  const pending = operations.loadProjectMaintenance({
    config,
    scope: operationScope,
    signal: controller.signal,
  });
  config.tenantId = 'mutated';
  operationScope.projectId = 'mutated';

  const snapshot = await pending;
  for (const value of [
    snapshot,
    snapshot.scope,
    snapshot.allowedActions,
    snapshot.stats,
    snapshot.maintenanceStatus,
    snapshot.maintenanceStatus.recommendations,
    snapshot.embeddingStatus,
  ]) {
    assert.equal(Object.isFrozen(value), true);
  }
  assert.deepEqual(lifecycle, [
    {
      type: 'acquire',
      digest: 'digest-maintenance',
      request: {
        service: 'service:desktop-renderer.project-maintenance-authority',
        version: '1.0.0',
        scope: {
          kind: 'project',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
        },
      },
    },
    { type: 'release', digest: 'digest-maintenance' },
  ]);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(Object.isFrozen(received[0].scope), true);
  assert.deepEqual(received[1], { type: 'load', signal: controller.signal });
});

test('invalid and Local Project Maintenance inputs fail before generation acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopProjectMaintenanceOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      assert.fail('invalid or Local input must not acquire');
    },
  }));
  for (const invalidInput of [
    { config: runtimeConfig({ mode: 'remote' }), scope: scope() },
    { config: runtimeConfig(), scope: scope('local') },
    { config: runtimeConfig(), scope: scope(), signal: {} },
    { config: runtimeConfig(), scope: scope(), extra: true },
  ]) {
    assert.throws(
      () => operations.loadProjectMaintenance(invalidInput),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_maintenance_operation_input_invalid',
    );
  }
  assert.throws(
    () =>
      operations.loadProjectMaintenance({
        config: runtimeConfig({ mode: 'local' }),
        scope: scope('local'),
      }),
    (error) =>
      error instanceof DesktopProjectMaintenanceAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'local_project_maintenance_authority_unavailable' &&
      error.status === 501,
  );
  assert.equal(acquisitions, 0);
});

test('missing or malformed Project Maintenance services and snapshots fail closed', async () => {
  await assert.rejects(
    createDesktopProjectMaintenanceOperationsV2(() => ({
      async acquireServiceOperationLease() {
        return {
          status: 'rejected',
          reasonCode: 'missing_service',
          runtimeCode: 'missing_service',
        };
      },
    })).loadProjectMaintenance({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof DesktopProjectMaintenanceAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'missing_service',
  );
  for (const service of [
    Object.freeze({ bindOperation: null }),
    Object.freeze({ bindOperation: () => Object.freeze({ load: null }) }),
    Object.freeze({
      bindOperation: () => Object.freeze({ load: async () => result(), extra: true }),
    }),
  ]) {
    await assert.rejects(
      createDesktopProjectMaintenanceOperationsV2(() =>
        acceptedActions(service, 'invalid-shape'),
      ).loadProjectMaintenance({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_maintenance_service_invalid',
    );
  }
  const valid = result();
  for (const invalidResult of [
    { ...valid, availability: 'available', reasonCode: null },
    { ...valid, reasonCode: 'partial' },
    { ...valid, contractVersion: '3.0.0' },
    { ...valid, allowedActions: ['view', 'deduplicate'] },
    { ...valid, scopeRevision: -1 },
    { ...valid, scope: scope('cloud', { projectId: 'project-2' }) },
    { ...valid, membershipRole: 'superuser' },
    { ...valid, stats: { ...valid.stats, entityCount: -1 } },
    { ...valid, maintenanceStatus: { ...valid.maintenanceStatus, recommendations: [''] } },
    { ...valid, embeddingStatus: { ...valid.embeddingStatus, compatible: 'yes' } },
    { ...valid, extra: true },
  ]) {
    await assert.rejects(
      createDesktopProjectMaintenanceOperationsV2(() =>
        acceptedActions(serviceFixture([], { result: invalidResult }), 'invalid-result'),
      ).loadProjectMaintenance({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_maintenance_service_contract_invalid',
    );
  }
});

test('HTTP projection keeps scope observation and Maintenance reads together', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (input, init = {}) => {
    requests.push({ input: String(input), init });
    const path = new URL(String(input)).pathname;
    if (path === '/api/v1/workspace-context') {
      return jsonResponse({
        context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 75 },
      });
    }
    if (path === '/api/v1/auth/me') return jsonResponse({ user_id: 'user-1' });
    if (path === '/api/v1/projects/project-1/members') {
      return jsonResponse({ members: [{ user_id: 'user-1', role: 'owner' }], total: 1 });
    }
    if (path === '/api/v1/maintenance/status') {
      return jsonResponse({
        stats: { entities: 4, episodes: 5, communities: 2, old_episodes: 1 },
        recommendations: ['refresh'],
        last_checked: '2026-09-03T00:00:00Z',
      });
    }
    if (path === '/api/v1/data/stats') {
      return jsonResponse({
        entity_count: 4,
        episodic_count: 5,
        community_count: 2,
        edge_count: 8,
      });
    }
    if (path === '/api/v1/maintenance/embeddings/status') {
      return jsonResponse({
        current_provider: 'openai',
        current_dimension: 1536,
        existing_dimension: 1536,
        is_compatible: true,
        missing_embeddings: 0,
      });
    }
    throw new Error(`unexpected request: ${String(input)}`);
  };
  try {
    const authority = createDesktopProjectMaintenanceHttpAuthorityV2(runtimeConfig(), scope());
    const snapshot = await authority.load();
    assert.equal(snapshot.scopeRevision, 75);
    assert.equal(
      snapshot.reasonCode,
      'desktop_project_maintenance_surface_and_endpoints_incomplete',
    );
    assert.deepEqual(snapshot.allowedActions, ['view']);
    assert.equal(snapshot.membershipRole, 'owner');
    assert.equal(snapshot.stats.entityCount, 4);
    assert.equal(snapshot.maintenanceStatus.oldEpisodes, 1);
    assert.equal(snapshot.embeddingStatus.currentDimension, 1536);
    assert.equal(requests.length, 6);
    for (const { input, init } of requests) {
      assert.equal(init.credentials, 'omit');
      assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer maintenance-session');
      assert.doesNotMatch(JSON.stringify(init), /maintenance-launch/u);
      const url = new URL(input);
      if (
        url.pathname.startsWith('/api/v1/maintenance/') ||
        url.pathname === '/api/v1/data/stats'
      ) {
        assert.equal(url.searchParams.get('tenant_id'), 'tenant-1');
        assert.equal(url.searchParams.get('project_id'), 'project-1');
      }
    }
    await assert.rejects(
      createDesktopProjectMaintenanceHttpAuthorityV2(
        runtimeConfig({ mode: 'local' }),
        scope('local'),
      ).load(),
      (error) =>
        error.status === 501 &&
        error.payload.reason_code === 'local_project_maintenance_authority_unavailable',
    );
    assert.equal(requests.length, 6);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('escaped Project Maintenance authority is revoked and primary failure wins', async () => {
  let escaped;
  await withDesktopProjectMaintenanceAuthorityOperationV2(
    acceptedActions(serviceFixture([]), 'digest-a'),
    { kind: 'load', config: runtimeConfig(), scope: scope() },
    (authority) => {
      escaped = authority;
      return authority.load();
    },
  );
  await assert.rejects(
    escaped.load(),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_maintenance_operation_released',
  );
  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopProjectMaintenanceAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-failure', [], release),
      { kind: 'load', config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  await assert.rejects(
    withDesktopProjectMaintenanceAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { kind: 'load', config: runtimeConfig(), scope: scope() },
      (authority) => authority.load(),
    ),
    (error) => error === release,
  );
});

test('old Maintenance request stays pinned while replacement serves new requests', async () => {
  let releaseOld;
  const gate = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const oldService = serviceFixture([], { result: result(scope(), 4) });
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
  const operations = createDesktopProjectMaintenanceOperationsV2(() => actions);
  const oldRequest = operations.loadProjectMaintenance({ config: runtimeConfig(), scope: scope() });
  actions = acceptedActions(serviceFixture([], { result: result(scope(), 9) }), 'new');
  const newRequest = operations.loadProjectMaintenance({ config: runtimeConfig(), scope: scope() });
  releaseOld();
  assert.equal((await oldRequest).stats.entityCount, 4);
  assert.equal((await newRequest).stats.entityCount, 9);
});

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
