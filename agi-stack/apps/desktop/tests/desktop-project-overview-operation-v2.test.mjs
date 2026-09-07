import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopProjectOverviewAuthorityUnavailableErrorV2,
  createDesktopProjectOverviewOperationsV2,
  withDesktopProjectOverviewAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopProjectOverviewAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46943',
    apiKey: 'overview-secret',
    localApiToken: 'overview-launch',
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

function cloudResult(operationScope = scope(), name = 'Cloud Project') {
  return {
    kind: 'cloud-ready',
    snapshot: {
      scope: operationScope,
      project: {
        id: operationScope.projectId,
        tenant_id: operationScope.tenantId,
        name,
        description: null,
        created_at: '2026-09-03T00:00:00Z',
        updated_at: null,
      },
      stats: {
        memory_count: 1,
        storage_used: 2,
        storage_limit: 3,
        active_nodes: 4,
        collaborators: 5,
      },
      latestMemories: [
        {
          id: 'memory-1',
          project_id: operationScope.projectId,
          title: 'Latest memory',
          content: 'Grounded content',
          content_type: 'text',
          status: 'active',
          metadata: {},
          created_at: '2026-09-03T00:00:00Z',
          updated_at: null,
        },
      ],
      latestMemoriesTotal: 1,
    },
  };
}

function localResult(operationScope = scope('local'), revision = 7) {
  return {
    kind: 'local-ready',
    snapshot: {
      scope: operationScope,
      capability: {
        availability: 'degraded',
        reasonCode: 'local_project_overview_timeline_projection_only',
        serviceVersion: '0.1.0',
        contractVersion: '4.0.0',
        allowedActions: ['view'],
        scope: {
          tenantId: operationScope.tenantId,
          projectId: operationScope.projectId,
          workspaceId: null,
          instanceId: null,
        },
        authorityRevision: revision,
      },
      backfillCursor: null,
      project: {
        availability: 'available',
        reasonCode: null,
        value: {
          id: operationScope.projectId,
          tenantId: operationScope.tenantId,
          name: 'Local Project',
          description: null,
          agentConversationMode: 'single',
          createdAt: '2026-09-03T00:00:00Z',
        },
      },
      conversationCount: {
        availability: 'available',
        reasonCode: null,
        value: 1,
      },
      conversationStatusSummary: {
        availability: 'available',
        reasonCode: null,
        value: {
          total: 1,
          idle: 1,
          queued: 0,
          running: 0,
          attention: 0,
          completed: 0,
          failed: 0,
          cancelled: 0,
        },
      },
      recentKnowledgeItems: {
        availability: 'degraded',
        reasonCode: 'local_project_overview_timeline_projection_only',
        source: 'desktop_timeline',
        total: 0,
        value: [],
      },
      activeNodes: {
        availability: 'unavailable',
        reasonCode: 'local_project_graph_projection_unavailable',
        value: null,
      },
      storageQuota: {
        availability: 'not_applicable',
        reasonCode: 'local_project_storage_quota_not_applicable',
        value: null,
      },
      collaborators: {
        availability: 'not_applicable',
        reasonCode: 'local_project_collaboration_governance_not_applicable',
        value: null,
      },
    },
  };
}

function capability(operationScope = scope(), overrides = {}) {
  return {
    availability: 'unavailable',
    reason_code: 'capability_authority_revision_unavailable',
    service_version: '0.1.0',
    contract_version: '3.0.0',
    allowed_actions: [],
    scope: {
      tenant_id: operationScope.tenantId,
      project_id: operationScope.projectId,
      workspace_id: null,
      instance_id: null,
    },
    authority_revision: null,
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
          return overrides.load ?? cloudResult(operationScope);
        },
        async probe(signal) {
          received.push({ type: 'probe', signal });
          return overrides.probe ?? capability(operationScope);
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

test('Project Overview operations freeze inputs before one exact project lease', async () => {
  const lifecycle = [];
  const received = [];
  const controller = new AbortController();
  const config = runtimeConfig();
  const operationScope = scope();
  const operations = createDesktopProjectOverviewOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-cloud', lifecycle)
  );

  const pendingLoad = operations.loadProjectOverview({
    config,
    scope: operationScope,
    signal: controller.signal,
  });
  config.tenantId = 'mutated';
  operationScope.projectId = 'mutated';
  const result = await pendingLoad;
  await operations.probeProjectOverview({
    config: runtimeConfig(),
    scope: scope(),
  });

  assert.equal(result.snapshot.scope.tenantId, 'tenant-1');
  assert.deepEqual(lifecycle, [
    {
      type: 'acquire',
      digest: 'digest-cloud',
      request: {
        service: 'service:desktop-renderer.project-overview-authority',
        version: '1.0.0',
        scope: {
          kind: 'project',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
        },
      },
    },
    { type: 'release', digest: 'digest-cloud' },
    {
      type: 'acquire',
      digest: 'digest-cloud',
      request: {
        service: 'service:desktop-renderer.project-overview-authority',
        version: '1.0.0',
        scope: {
          kind: 'project',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
        },
      },
    },
    { type: 'release', digest: 'digest-cloud' },
  ]);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(Object.isFrozen(received[0].scope), true);
  assert.deepEqual(received[0].scope, scope());
  assert.equal(received[1].signal, controller.signal);
});

test('Local Project Overview load and probe preserve Local revision under a project lease', async () => {
  const operationScope = scope('local');
  const lifecycle = [];
  const operations = createDesktopProjectOverviewOperationsV2(() =>
    acceptedActions(
      serviceFixture([], {
        load: localResult(operationScope),
        probe: capability(operationScope, {
          availability: 'degraded',
          reason_code: 'local_project_overview_timeline_projection_only',
          contract_version: '4.0.0',
          allowed_actions: ['view'],
          authority_revision: 7,
        }),
      }),
      'digest-local',
      lifecycle
    )
  );
  const config = runtimeConfig({ mode: 'local' });

  assert.equal(
    (await operations.loadProjectOverview({ config, scope: operationScope })).kind,
    'local-ready'
  );
  assert.equal(
    (await operations.probeProjectOverview({ config, scope: operationScope })).authority_revision,
    7
  );
  for (const event of lifecycle.filter(({ type }) => type === 'acquire')) {
    assert.deepEqual(event.request.scope, {
      kind: 'project',
      tenant_id: 'tenant-1',
      project_id: 'project-1',
    });
  }
});

test('invalid config, scope, signal and absent generation fail before acquisition', async () => {
  let acquisitions = 0;
  const operations = createDesktopProjectOverviewOperationsV2(() => ({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      assert.fail('invalid input must not acquire a lease');
    },
  }));
  for (const invalidCall of [
    () =>
      operations.loadProjectOverview({
        config: runtimeConfig(),
        scope: scope('local'),
      }),
    () =>
      operations.loadProjectOverview({
        config: runtimeConfig(),
        scope: scope('cloud', { tenantId: ' tenant-1' }),
      }),
    () =>
      operations.probeProjectOverview({
        config: runtimeConfig({ projectId: 'project-2' }),
        scope: scope(),
      }),
    () =>
      operations.loadProjectOverview({
        config: runtimeConfig(),
        scope: scope(),
        signal: {},
      }),
  ]) {
    assert.throws(
      invalidCall,
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_overview_operation_input_invalid'
    );
  }
  assert.equal(acquisitions, 0);
  assert.throws(
    () =>
      createDesktopProjectOverviewOperationsV2(() => null).loadProjectOverview({
        config: runtimeConfig(),
        scope: scope(),
      }),
    (error) =>
      error instanceof DesktopProjectOverviewAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable'
  );
});

test('lease rejection and malformed service, authority or results fail closed', async () => {
  const rejected = createDesktopProjectOverviewOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return {
        status: 'rejected',
        reasonCode: 'missing_service',
        runtimeCode: 'missing_service',
      };
    },
  }));
  await assert.rejects(
    rejected.loadProjectOverview({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof DesktopProjectOverviewAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'missing_service'
  );

  for (const service of [
    Object.freeze({ bindOperation: null }),
    Object.freeze({
      bindOperation: () => Object.freeze({ load: async () => cloudResult() }),
    }),
  ]) {
    await assert.rejects(
      createDesktopProjectOverviewOperationsV2(() =>
        acceptedActions(service, 'invalid-shape')
      ).loadProjectOverview({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error && error.code === 'desktop_project_overview_service_invalid'
    );
  }

  const malformed = createDesktopProjectOverviewOperationsV2(() =>
    acceptedActions(
      serviceFixture([], {
        load: cloudResult(scope(), ''),
        probe: capability(scope(), { allowed_actions: ['view'] }),
      }),
      'bad-result'
    )
  );
  await assert.rejects(
    malformed.loadProjectOverview({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_overview_service_contract_invalid'
  );
  await assert.rejects(
    malformed.probeProjectOverview({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_overview_service_contract_invalid'
  );
});

test('escaped authority is revoked and primary failure wins over disposer failure', async () => {
  let escaped;
  await withDesktopProjectOverviewAuthorityOperationV2(
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
      error.code === 'desktop_project_overview_operation_released'
  );

  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopProjectOverviewAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-failure', [], release),
      { config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      }
    ),
    (error) => error === primary
  );
  await assert.rejects(
    withDesktopProjectOverviewAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { config: runtimeConfig(), scope: scope() },
      (authority) => authority.load()
    ),
    (error) => error === release
  );
});

test('old Project Overview request stays pinned while a new request uses replacement generation', async () => {
  let releaseOld;
  const gate = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const oldService = serviceFixture([]);
  const gatedService = Object.freeze({
    bindOperation(...args) {
      const authority = oldService.bindOperation(...args);
      return Object.freeze({
        ...authority,
        async load(signal) {
          await gate;
          await authority.load(signal);
          return cloudResult(scope(), 'Old Project');
        },
      });
    },
  });
  let actions = acceptedActions(gatedService, 'old');
  const operations = createDesktopProjectOverviewOperationsV2(() => actions);
  const oldRequest = operations.loadProjectOverview({
    config: runtimeConfig(),
    scope: scope(),
  });
  actions = acceptedActions(
    serviceFixture([], { load: cloudResult(scope(), 'New Project') }),
    'new'
  );
  const newRequest = operations.loadProjectOverview({
    config: runtimeConfig(),
    scope: scope(),
  });
  releaseOld();

  assert.equal((await oldRequest).snapshot.project.name, 'Old Project');
  assert.equal((await newRequest).snapshot.project.name, 'New Project');
});
