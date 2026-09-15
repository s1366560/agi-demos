import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopProjectSettingsAuthorityUnavailableErrorV2,
  createDesktopProjectSettingsOperationsV2,
  withDesktopProjectSettingsAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopProjectSettingsAuthorityModuleV2.js');
const { createDesktopProjectSettingsHttpAuthorityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectSettingsHttpProjectionV2.js',
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://cloud.memstack.test',
    apiKey: 'settings-session',
    localApiToken: 'settings-launch',
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

function result(operationScope = scope(), projectName = 'Project One') {
  return {
    scope: operationScope,
    scopeRevision: 74,
    authority: 'cloud',
    availability: 'degraded',
    reasonCode: 'desktop_project_settings_actions_unwired',
    contractVersion: '4.0.0',
    allowedActions: ['view'],
    membershipRole: 'member',
    project: {
      id: 'project-1',
      tenantId: 'tenant-1',
      name: projectName,
      description: 'Settings fixture',
      ownerId: 'user-1',
      isPublic: false,
      memoryRules: {
        maxEpisodes: 200,
        retentionDays: 30,
        autoRefresh: true,
        refreshInterval: 10,
      },
      graphConfig: {
        maxNodes: 1000,
        maxEdges: 2000,
        similarityThreshold: 0.75,
        communityDetection: true,
      },
      sandboxType: 'docker',
      conversationMode: 'threaded',
      createdAt: '2026-09-03T00:00:00Z',
      updatedAt: null,
    },
    sandbox: {
      id: 'sandbox-1',
      status: 'running',
      healthy: true,
      createdAt: '2026-09-03T00:00:00Z',
    },
    sandboxStats: {
      sandboxId: 'sandbox-1',
      status: 'running',
      cpuPercent: 12.5,
      memoryUsage: 512,
      memoryLimit: 1024,
      memoryPercent: 50,
      pids: 4,
      collectedAt: '2026-09-03T00:01:00Z',
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

test('Project Settings load pins frozen input and result to one project lease', async () => {
  const received = [];
  const lifecycle = [];
  const config = runtimeConfig();
  const operationScope = scope();
  const controller = new AbortController();
  const operations = createDesktopProjectSettingsOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-settings', lifecycle),
  );
  const pending = operations.loadProjectSettings({
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
    snapshot.project,
    snapshot.project.memoryRules,
    snapshot.project.graphConfig,
    snapshot.sandbox,
    snapshot.sandboxStats,
  ]) {
    assert.equal(Object.isFrozen(value), true);
  }
  assert.deepEqual(lifecycle, [
    {
      type: 'acquire',
      digest: 'digest-settings',
      request: {
        service: 'service:desktop-renderer.project-settings-authority',
        version: '1.0.0',
        scope: {
          kind: 'project',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
        },
      },
    },
    { type: 'release', digest: 'digest-settings' },
  ]);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(Object.isFrozen(received[0].scope), true);
  assert.deepEqual(received[1], { type: 'load', signal: controller.signal });
});

test('invalid and Local Project Settings inputs fail before generation acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopProjectSettingsOperationsV2(() => ({
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
      () => operations.loadProjectSettings(invalidInput),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_settings_operation_input_invalid',
    );
  }
  assert.throws(
    () =>
      operations.loadProjectSettings({
        config: runtimeConfig({ mode: 'local' }),
        scope: scope('local'),
      }),
    (error) =>
      error instanceof DesktopProjectSettingsAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'local_project_settings_authority_unavailable' &&
      error.status === 501,
  );
  assert.equal(acquisitions, 0);
});

test('missing or malformed Project Settings services and snapshots fail closed', async () => {
  await assert.rejects(
    createDesktopProjectSettingsOperationsV2(() => ({
      async acquireServiceOperationLease() {
        return {
          status: 'rejected',
          reasonCode: 'missing_service',
          runtimeCode: 'missing_service',
        };
      },
    })).loadProjectSettings({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof DesktopProjectSettingsAuthorityUnavailableErrorV2 &&
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
      createDesktopProjectSettingsOperationsV2(() =>
        acceptedActions(service, 'invalid-shape'),
      ).loadProjectSettings({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_settings_service_invalid',
    );
  }
  const valid = result();
  for (const invalidResult of [
    { ...valid, availability: 'available', reasonCode: null },
    { ...valid, reasonCode: 'partial' },
    { ...valid, contractVersion: '3.0.0' },
    { ...valid, allowedActions: ['view', 'update'] },
    { ...valid, scopeRevision: -1 },
    { ...valid, scope: scope('cloud', { projectId: 'project-2' }) },
    { ...valid, membershipRole: 'superuser' },
    { ...valid, project: { ...valid.project, tenantId: 'tenant-2' } },
    { ...valid, project: { ...valid.project, memoryRules: { ...valid.project.memoryRules, maxEpisodes: -1 } } },
    { ...valid, sandbox: { ...valid.sandbox, healthy: 'yes' } },
    { ...valid, sandboxStats: { ...valid.sandboxStats, sandboxId: 'sandbox-2' } },
    { ...valid, extra: true },
  ]) {
    await assert.rejects(
      createDesktopProjectSettingsOperationsV2(() =>
        acceptedActions(serviceFixture([], { result: invalidResult }), 'invalid-result'),
      ).loadProjectSettings({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_settings_service_contract_invalid',
    );
  }
});

test('HTTP projection keeps scope observation and Settings reads together', async () => {
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
    if (path === '/api/v1/projects/project-1') {
      return jsonResponse({
        id: 'project-1',
        tenant_id: 'tenant-1',
        name: 'Project One',
        description: 'Settings fixture',
        owner_id: 'user-1',
        is_public: false,
        memory_rules: {
          max_episodes: 200,
          retention_days: 30,
          auto_refresh: true,
          refresh_interval: 10,
        },
        graph_config: {
          max_nodes: 1000,
          max_edges: 2000,
          similarity_threshold: 0.75,
          community_detection: true,
        },
        sandbox_config: { sandbox_type: 'docker' },
        agent_conversation_mode: 'threaded',
        created_at: '2026-09-03T00:00:00Z',
        updated_at: null,
      });
    }
    if (path === '/api/v1/projects/project-1/sandbox') {
      return jsonResponse({
        project_id: 'project-1',
        tenant_id: 'tenant-1',
        sandbox_id: 'sandbox-1',
        status: 'running',
        is_healthy: true,
        created_at: '2026-09-03T00:00:00Z',
      });
    }
    if (path === '/api/v1/projects/project-1/sandbox/stats') {
      return jsonResponse({
        project_id: 'project-1',
        sandbox_id: 'sandbox-1',
        status: 'running',
        cpu_percent: 12.5,
        memory_usage: 512,
        memory_limit: 1024,
        memory_percent: 50,
        pids: 4,
        collected_at: '2026-09-03T00:01:00Z',
      });
    }
    throw new Error(`unexpected request: ${String(input)}`);
  };
  try {
    const authority = createDesktopProjectSettingsHttpAuthorityV2(runtimeConfig(), scope());
    const snapshot = await authority.load();
    assert.equal(snapshot.scopeRevision, 75);
    assert.equal(
      snapshot.reasonCode,
      'desktop_project_settings_actions_unwired',
    );
    assert.deepEqual(snapshot.allowedActions, ['view']);
    assert.equal(snapshot.membershipRole, 'owner');
    assert.equal(snapshot.project.name, 'Project One');
    assert.equal(snapshot.sandbox.id, 'sandbox-1');
    assert.equal(snapshot.sandboxStats.memoryPercent, 50);
    assert.equal(requests.length, 6);
    for (const { input, init } of requests) {
      assert.equal(init.credentials, 'omit');
      assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer settings-session');
      assert.doesNotMatch(JSON.stringify(init), /settings-launch/u);
      assert.equal(new URL(input).search, new URL(input).pathname === '/api/v1/projects/project-1' ? '?tenant_id=tenant-1' : '');
    }
    await assert.rejects(
      createDesktopProjectSettingsHttpAuthorityV2(
        runtimeConfig({ mode: 'local' }),
        scope('local'),
      ).load(),
      (error) =>
        error.status === 501 &&
        error.payload.reason_code === 'local_project_settings_authority_unavailable',
    );
    assert.equal(requests.length, 6);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('escaped Project Settings authority is revoked and primary failure wins', async () => {
  let escaped;
  await withDesktopProjectSettingsAuthorityOperationV2(
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
      error.code === 'desktop_project_settings_operation_released',
  );
  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopProjectSettingsAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-failure', [], release),
      { kind: 'load', config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  await assert.rejects(
    withDesktopProjectSettingsAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { kind: 'load', config: runtimeConfig(), scope: scope() },
      (authority) => authority.load(),
    ),
    (error) => error === release,
  );
});

test('old Settings request stays pinned while replacement serves new requests', async () => {
  let releaseOld;
  const gate = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const oldService = serviceFixture([], { result: result(scope(), 'Old Project') });
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
  const operations = createDesktopProjectSettingsOperationsV2(() => actions);
  const oldRequest = operations.loadProjectSettings({ config: runtimeConfig(), scope: scope() });
  actions = acceptedActions(serviceFixture([], { result: result(scope(), 'New Project') }), 'new');
  const newRequest = operations.loadProjectSettings({ config: runtimeConfig(), scope: scope() });
  releaseOld();
  assert.equal((await oldRequest).project.name, 'Old Project');
  assert.equal((await newRequest).project.name, 'New Project');
});

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
