import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopTenantAgentDashboardAuthorityUnavailableErrorV2,
  createDesktopTenantAgentDashboardOperationsV2,
  withDesktopTenantAgentDashboardAuthorityOperationV2,
} = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantAgentDashboardAuthorityModuleV2.js'
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46942',
    apiKey: 'dashboard-secret',
    localApiToken: 'dashboard-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: '',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

function scope(overrides = {}) {
  return { authority: 'local', tenantId: 'tenant-1', ...overrides };
}

function editableConfig(overrides = {}) {
  return {
    llmModel: 'gpt-5.6',
    llmTemperature: 0.2,
    patternLearningEnabled: true,
    multiLevelThinkingEnabled: false,
    maxWorkPlanSteps: 10,
    toolTimeoutSeconds: 60,
    enabledTools: ['read_file'],
    disabledTools: [],
    runtimeHooks: [],
    ...overrides,
  };
}

function agentConfig(overrides = {}) {
  return {
    ...editableConfig(),
    id: 'config-1',
    tenantId: 'tenant-1',
    configType: 'tenant',
    runtimeHookSettingsRedacted: false,
    multiAgentEnabled: true,
    authorityRevision: 7,
    createdAt: '2026-09-03T00:00:00Z',
    updatedAt: '2026-09-03T00:00:00Z',
    ...overrides,
  };
}

function snapshot(overrides = {}) {
  return {
    scope: scope(),
    authority: 'local',
    availability: 'unavailable',
    reasonCode: 'local_agent_dashboard_authority_unavailable',
    serviceVersion: '0.1.0',
    contractVersion: '3.0.0',
    allowedActions: [],
    authorityRevision: null,
    canModify: false,
    config: null,
    hookCatalog: [],
    runtimeInfo: null,
    runs: [],
    activeRunCount: 0,
    ...overrides,
  };
}

function trace(overrides = {}) {
  return {
    traceId: 'trace-1',
    conversationId: 'conversation-1',
    runs: [],
    total: 0,
    ...overrides,
  };
}

function serviceFixture(received, overrides = {}) {
  return Object.freeze({
    bindOperation(config, operationScope) {
      received.push({ type: 'bind', config, scope: operationScope });
      return Object.freeze({
        async load(signal) {
          received.push({ type: 'load', signal });
          return overrides.load ?? snapshot();
        },
        async updateConfig(input, expectedRevision, signal) {
          received.push({ type: 'update', input, expectedRevision, signal });
          return overrides.update ?? agentConfig({ authorityRevision: expectedRevision + 1 });
        },
        async inspectTrace(conversationId, traceId, signal) {
          received.push({ type: 'trace', conversationId, traceId, signal });
          return overrides.trace ?? trace({ conversationId, traceId });
        },
      });
    },
  });
}

function acceptedActions(service, digest, lifecycle = [], releaseError = null) {
  return {
    acquireServiceOperationLease: async (request) => {
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

test('each dashboard operation freezes inputs before one exact tenant lease', async () => {
  const lifecycle = [];
  const received = [];
  const controller = new AbortController();
  const config = runtimeConfig();
  const operationScope = scope();
  const input = editableConfig({
    runtimeHooks: [
      {
        hookName: 'before_tool',
        pluginName: 'audit',
        hookFamily: null,
        executorKind: 'plugin',
        sourceRef: null,
        entrypoint: null,
        enabled: true,
        priority: 10,
        settings: { nested: { redact: true } },
      },
    ],
  });
  const operations = createDesktopTenantAgentDashboardOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-a', lifecycle),
  );

  const pendingLoad = operations.loadTenantAgentDashboard({
    config,
    scope: operationScope,
    signal: controller.signal,
  });
  config.tenantId = 'tenant-mutated';
  operationScope.tenantId = 'tenant-mutated';
  await pendingLoad;
  const pendingUpdate = operations.updateTenantAgentDashboardConfig({
    config: runtimeConfig(),
    scope: scope(),
    input,
    expectedRevision: 7,
  });
  input.runtimeHooks[0].settings.nested.redact = false;
  const updated = await pendingUpdate;
  const inspected = await operations.inspectTenantAgentDashboardTrace({
    config: runtimeConfig(),
    scope: scope(),
    conversationId: 'conversation-1',
    traceId: 'trace-1',
  });

  assert.equal(lifecycle.length, 6);
  for (const event of lifecycle.filter(({ type }) => type === 'acquire')) {
    assert.deepEqual(event.request, {
      service: 'service:desktop-renderer.tenant-agent-dashboard-authority',
      version: '1.0.0',
      scope: { kind: 'tenant', tenant_id: 'tenant-1' },
    });
  }
  assert.equal(received[0].config.tenantId, 'tenant-1');
  assert.deepEqual(received[0].scope, { authority: 'local', tenantId: 'tenant-1' });
  assert.equal(received[1].signal, controller.signal);
  assert.equal(received[3].input.runtimeHooks[0].settings.nested.redact, true);
  assert.equal(Object.isFrozen(received[3].input.runtimeHooks[0].settings.nested), true);
  assert.equal(updated.authorityRevision, 8);
  assert.equal(Object.isFrozen(updated), true);
  assert.equal(inspected.traceId, 'trace-1');
  assert.equal(Object.isFrozen(inspected.runs), true);
});

test('invalid scope, revision and trace identity fail before acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopTenantAgentDashboardOperationsV2(() => ({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      assert.fail('invalid input must not acquire a lease');
    },
  }));

  assert.throws(
    () =>
      operations.loadTenantAgentDashboard({
        config: runtimeConfig(),
        scope: scope({ authority: 'cloud' }),
      }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_tenant_agent_dashboard_operation_input_invalid',
  );
  assert.throws(
    () =>
      operations.updateTenantAgentDashboardConfig({
        config: runtimeConfig(),
        scope: scope(),
        input: editableConfig(),
        expectedRevision: 0,
      }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_tenant_agent_dashboard_operation_input_invalid',
  );
  assert.throws(
    () =>
      operations.inspectTenantAgentDashboardTrace({
        config: runtimeConfig(),
        scope: scope(),
        conversationId: ' conversation-1',
        traceId: 'trace-1',
      }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_tenant_agent_dashboard_operation_input_invalid',
  );
  assert.equal(acquisitions, 0);
  assert.throws(
    () =>
      createDesktopTenantAgentDashboardOperationsV2(() => null).loadTenantAgentDashboard({
        config: runtimeConfig(),
        scope: scope(),
      }),
    (error) =>
      error instanceof DesktopTenantAgentDashboardAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
});

test('lease rejection and malformed service or authority shapes fail closed', async () => {
  const rejectedOperations = createDesktopTenantAgentDashboardOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return {
        status: 'rejected',
        reasonCode: 'missing_service',
        runtimeCode: 'missing_service',
      };
    },
  }));
  await assert.rejects(
    rejectedOperations.loadTenantAgentDashboard({
      config: runtimeConfig(),
      scope: scope(),
    }),
    (error) =>
      error instanceof DesktopTenantAgentDashboardAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'missing_service' &&
      error.runtimeCode === 'missing_service',
  );

  for (const service of [
    Object.freeze({ bindOperation: null }),
    Object.freeze({
      bindOperation() {
        return Object.freeze({ load: async () => snapshot() });
      },
    }),
  ]) {
    const operations = createDesktopTenantAgentDashboardOperationsV2(() =>
      acceptedActions(service, 'invalid-shape'),
    );
    await assert.rejects(
      operations.loadTenantAgentDashboard({
        config: runtimeConfig(),
        scope: scope(),
      }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_tenant_agent_dashboard_service_invalid',
    );
  }
});

test('escaped authority is revoked and primary failure wins over disposer failure', async () => {
  let escaped;
  await withDesktopTenantAgentDashboardAuthorityOperationV2(
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
      error.code === 'desktop_tenant_agent_dashboard_operation_released',
  );

  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopTenantAgentDashboardAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-failure', [], release),
      { config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  await assert.rejects(
    withDesktopTenantAgentDashboardAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { config: runtimeConfig(), scope: scope() },
      (authority) => authority.load(),
    ),
    (error) => error === release,
  );
});

test('old dashboard request stays pinned while a new request uses replacement generation', async () => {
  let releaseOld;
  const gate = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const oldService = serviceFixture([], {
    load: new Proxy(snapshot({ serviceVersion: 'old' }), {}),
  });
  const originalBind = oldService.bindOperation;
  const gatedService = Object.freeze({
    bindOperation(...args) {
      const authority = originalBind(...args);
      return Object.freeze({
        ...authority,
        async load(signal) {
          await gate;
          return authority.load(signal).then(() => snapshot({ serviceVersion: 'old' }));
        },
      });
    },
  });
  let actions = acceptedActions(gatedService, 'old');
  const operations = createDesktopTenantAgentDashboardOperationsV2(() => actions);
  const oldRequest = operations.loadTenantAgentDashboard({
    config: runtimeConfig(),
    scope: scope(),
  });
  actions = acceptedActions(
    serviceFixture([], { load: snapshot({ serviceVersion: 'new' }) }),
    'new',
  );
  const newRequest = operations.loadTenantAgentDashboard({
    config: runtimeConfig(),
    scope: scope(),
  });
  releaseOld();

  assert.equal((await oldRequest).serviceVersion, 'old');
  assert.equal((await newRequest).serviceVersion, 'new');
});
