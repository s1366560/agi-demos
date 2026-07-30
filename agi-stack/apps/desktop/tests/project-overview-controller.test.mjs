import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { DesktopApiError } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const { createProjectOverviewController } = require(
  '/tmp/agistack-desktop-test-dist/src/features/project/projectOverviewController.js'
);
const { useProjectOverviewController } = require(
  '/tmp/agistack-desktop-test-dist/src/features/project/useProjectOverviewController.js'
);

const cloudScope = Object.freeze({
  authority: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
});
const nextCloudScope = Object.freeze({
  authority: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-2',
});
const localScope = Object.freeze({
  authority: 'local',
  tenantId: 'local-tenant',
  projectId: 'local-project',
});

test('controller constructs with only the adapter for its production authority', async () => {
  const cloudController = createProjectOverviewController({
    authority: 'cloud',
    cloudClient: cloudClientFor(async (scope) => cloudProject(scope)),
    initialScope: cloudScope,
  });
  await cloudController.load(cloudScope);
  assert.equal(cloudController.getSnapshot().state, 'ready');
  cloudController.stop();

  const localController = createProjectOverviewController({
    authority: 'local',
    localClient: {
      async load(scope) {
        return localSnapshot(scope);
      },
    },
    initialScope: localScope,
  });
  await localController.load(localScope);
  assert.equal(localController.getSnapshot().state, 'degraded');
  localController.stop();
});

test('controller fails closed when a scope authority does not match its adapter', async () => {
  let cloudReads = 0;
  const cloudController = createProjectOverviewController({
    authority: 'cloud',
    cloudClient: cloudClientFor(async (scope) => {
      cloudReads += 1;
      return cloudProject(scope);
    }),
    initialScope: cloudScope,
  });
  await cloudController.load(localScope);
  assert.equal(cloudReads, 0);
  assert.deepEqual(pickTerminal(cloudController.getSnapshot()), {
    state: 'unavailable',
    authority: 'local',
    reasonCode: 'project_overview_controller_authority_mismatch',
    detail: null,
    retryVisible: false,
  });
  cloudController.stop();

  let localReads = 0;
  const localController = createProjectOverviewController({
    authority: 'local',
    localClient: {
      async load(scope) {
        localReads += 1;
        return localSnapshot(scope);
      },
    },
    initialScope: localScope,
  });
  await localController.load(cloudScope);
  assert.equal(localReads, 0);
  assert.deepEqual(pickTerminal(localController.getSnapshot()), {
    state: 'unavailable',
    authority: 'cloud',
    reasonCode: 'project_overview_controller_authority_mismatch',
    detail: null,
    retryVisible: false,
  });
  localController.stop();

  const invalidInitialController = createProjectOverviewController({
    authority: 'cloud',
    cloudClient: cloudClientFor(async (scope) => cloudProject(scope)),
    initialScope: localScope,
  });
  assert.deepEqual(pickTerminal(invalidInitialController.getSnapshot()), {
    state: 'unavailable',
    authority: 'local',
    reasonCode: 'project_overview_controller_authority_mismatch',
    detail: null,
    retryVisible: false,
  });
  invalidInitialController.stop();
});

test('controller suppresses stale Cloud results during rapid scope changes', async () => {
  const firstProject = deferred();
  const signals = [];
  const cloudClient = cloudClientFor(async (scope, options) => {
    signals.push(options.signal);
    if (scope.projectId === cloudScope.projectId) return firstProject.promise;
    return cloudProject(scope);
  });
  const controller = createProjectOverviewController({
    authority: 'cloud',
    cloudClient,
    initialScope: cloudScope,
  });
  const states = [];
  const unsubscribe = controller.subscribe(() => states.push(controller.getSnapshot().state));

  const firstLoad = controller.load(cloudScope);
  await Promise.resolve();
  const nextLoad = controller.load(nextCloudScope);
  assert.equal(controller.getSnapshot().state, 'scope_switch');
  await nextLoad;

  assert.equal(signals[0].aborted, true);
  assert.equal(controller.getSnapshot().state, 'ready');
  assert.equal(controller.getSnapshot().scope.projectId, nextCloudScope.projectId);

  firstProject.resolve(cloudProject(cloudScope));
  await firstLoad;
  assert.equal(controller.getSnapshot().scope.projectId, nextCloudScope.projectId);
  assert.equal(controller.getSnapshot().project.name, 'Project project-2');
  assert.deepEqual(states.slice(0, 3), ['loading', 'scope_switch', 'ready']);

  unsubscribe();
  controller.stop();
});

test('controller aborts stopped work and retries a structured transient error', async () => {
  const pendingProject = deferred();
  let pendingSignal;
  const stoppedController = createProjectOverviewController({
    authority: 'cloud',
    cloudClient: cloudClientFor(async (_scope, options) => {
      pendingSignal = options.signal;
      return pendingProject.promise;
    }),
    initialScope: cloudScope,
  });
  const stoppedLoad = stoppedController.load(cloudScope);
  await Promise.resolve();
  stoppedController.stop();
  assert.equal(pendingSignal.aborted, true);
  pendingProject.resolve(cloudProject(cloudScope));
  await stoppedLoad;
  assert.equal(stoppedController.getSnapshot().state, 'loading');

  let attempts = 0;
  const retryController = createProjectOverviewController({
    authority: 'cloud',
    cloudClient: cloudClientFor(async (scope) => {
      attempts += 1;
      if (attempts === 1) {
        throw new DesktopApiError('must not leak', 500, {
          reason_code: 'project_overview_fetch_failed',
        });
      }
      return cloudProject(scope);
    }),
    initialScope: cloudScope,
  });

  await retryController.load(cloudScope);
  assert.equal(retryController.getSnapshot().state, 'error');
  assert.equal(retryController.getSnapshot().reasonCode, 'project_overview_fetch_failed');
  assert.equal(retryController.getSnapshot().detail, null);
  assert.equal(retryController.getSnapshot().retryVisible, true);

  await retryController.retry();
  assert.equal(attempts, 2);
  assert.equal(retryController.getSnapshot().state, 'ready');
  retryController.stop();
});

test('controller maps only structured DesktopApiError fields to forbidden', async () => {
  const controller = createProjectOverviewController({
    authority: 'cloud',
    cloudClient: cloudClientFor(async () => {
      throw new DesktopApiError('message text must not classify the result', 403, {
        detail: 'also not presentation detail',
        reason_code: 'project_overview_scope_forbidden',
      });
    }),
    initialScope: cloudScope,
  });

  await controller.load(cloudScope);

  assert.deepEqual(pickTerminal(controller.getSnapshot()), {
    state: 'forbidden',
    authority: 'cloud',
    reasonCode: 'project_overview_scope_forbidden',
    detail: null,
    retryVisible: false,
  });
  controller.stop();
});

test('controller maps Local contract failures to structured unavailable', async () => {
  let receivedScope;
  let receivedSignal;
  const controller = createProjectOverviewController({
    authority: 'local',
    localClient: {
      async load(scope, options) {
        receivedScope = scope;
        receivedSignal = options.signal;
        throw new DesktopApiError('forbidden-looking words are ignored', 0, {
          reason_code: 'local_project_overview_contract_unavailable',
        });
      },
    },
    initialScope: localScope,
  });

  await controller.load(localScope);

  assert.deepEqual(receivedScope, localScope);
  assert.equal(receivedSignal.aborted, false);
  assert.deepEqual(pickTerminal(controller.getSnapshot()), {
    state: 'unavailable',
    authority: 'local',
    reasonCode: 'local_project_overview_contract_unavailable',
    detail: null,
    retryVisible: false,
  });
  controller.stop();
});

test('controller delegates empty and degraded states to the presentation model', async () => {
  const emptyController = createProjectOverviewController({
    authority: 'cloud',
    cloudClient: {
      async getProject() {
        return null;
      },
      async getProjectStats() {
        return cloudStats();
      },
      async listMemories() {
        return { memories: [], total: 0, page: 1, page_size: 5 };
      },
    },
    initialScope: cloudScope,
  });
  await emptyController.load(cloudScope);
  assert.equal(emptyController.getSnapshot().state, 'empty');
  assert.equal(emptyController.getSnapshot().retryVisible, true);
  emptyController.stop();

  let localLoads = 0;
  const localController = createProjectOverviewController({
    authority: 'local',
    localClient: {
      async load(scope) {
        localLoads += 1;
        return localSnapshot(scope);
      },
    },
    initialScope: localScope,
  });
  await localController.load(localScope);
  assert.equal(localLoads, 1);
  assert.equal(localController.getSnapshot().state, 'degraded');
  assert.equal(localController.getSnapshot().authority, 'local');
  assert.equal(localController.getSnapshot().recent.kind, 'knowledge_items');
  localController.stop();
});

test('React hook owns controller load, cancellation, and retry delegation', () => {
  const controller = createProjectOverviewController({
    authority: 'cloud',
    cloudClient: unexpectedCloudClient(),
    initialScope: cloudScope,
  });
  const markup = renderToStaticMarkup(
    React.createElement(function ProjectOverviewProbe() {
      const { model, retry } = useProjectOverviewController(controller, cloudScope);
      return React.createElement('output', {
        'data-project': model.scope.projectId,
        'data-retry': typeof retry,
        'data-state': model.state,
      });
    }),
  );
  const source = readFileSync(
    new URL('../src/features/project/useProjectOverviewController.ts', import.meta.url),
    'utf8',
  );

  assert.match(
    markup,
    /data-project="project-1" data-retry="function" data-state="loading"/u,
  );
  assert.match(source, /useSyncExternalStore\(/u);
  assert.match(source, /controller\.load\(stableScope\)/u);
  assert.match(source, /controller\.cancel/u);
  assert.match(source, /controller\.retry\(\)/u);
  controller.stop();
});

function cloudClientFor(getProject) {
  return {
    getProject,
    async getProjectStats() {
      return cloudStats();
    },
    async listMemories(scope) {
      return {
        memories: [cloudMemory(scope)],
        total: 1,
        page: 1,
        page_size: 5,
      };
    },
  };
}

function cloudProject(scope) {
  return {
    id: scope.projectId,
    tenant_id: scope.tenantId,
    name: `Project ${scope.projectId}`,
    description: null,
    created_at: '2026-07-30T00:00:00Z',
    updated_at: null,
  };
}

function cloudStats() {
  return {
    memory_count: 1,
    storage_used: 10,
    storage_limit: 100,
    active_nodes: 1,
    collaborators: 1,
  };
}

function cloudMemory(scope) {
  return {
    id: `memory-${scope.projectId}`,
    project_id: scope.projectId,
    title: 'Latest knowledge',
    content: 'Grounded content',
    content_type: 'text',
    status: 'active',
    metadata: {},
    created_at: '2026-07-30T00:00:00Z',
    updated_at: null,
  };
}

function localSnapshot(scope) {
  return {
    scope,
    capability: {
      availability: 'degraded',
      reasonCode: 'local_project_overview_timeline_projection_only',
      serviceVersion: '0.1.0',
      contractVersion: '3.0.0',
      allowedActions: ['view'],
      scope: {
        tenantId: scope.tenantId,
        projectId: scope.projectId,
        workspaceId: null,
        instanceId: null,
      },
      authorityRevision: 1,
    },
    backfillCursor: null,
    project: {
      availability: 'available',
      reasonCode: null,
      value: {
        id: scope.projectId,
        tenantId: scope.tenantId,
        name: 'Local Project',
        description: null,
        agentConversationMode: 'single',
        createdAt: '2026-07-30T00:00:00Z',
      },
    },
    conversationCount: {
      availability: 'available',
      reasonCode: null,
      value: 1,
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
  };
}

function unexpectedCloudClient() {
  const fail = async () => {
    throw new Error('Cloud client must not be selected');
  };
  return {
    getProject: fail,
    getProjectStats: fail,
    listMemories: fail,
  };
}

function pickTerminal(model) {
  return {
    state: model.state,
    authority: model.authority,
    reasonCode: model.reasonCode,
    detail: model.detail,
    retryVisible: model.retryVisible,
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}
