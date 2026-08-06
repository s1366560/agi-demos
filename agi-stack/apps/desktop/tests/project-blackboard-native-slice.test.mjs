import assert from 'node:assert/strict';
import { copyFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const compiledWorkspaceDirectory = '/tmp/agistack-desktop-test-dist/src/features/workspace';
mkdirSync(compiledWorkspaceDirectory, { recursive: true });
copyFileSync(
  new URL('../src/features/workspace/WorkspaceCollaborationCanvas.css', import.meta.url),
  `${compiledWorkspaceDirectory}/WorkspaceCollaborationCanvas.css`,
);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  createProjectBlackboardCloudClient,
  createProjectBlackboardLocalClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/project-blackboard/projectBlackboardClient.js');
const {
  createProjectBlackboardController,
} = require('/tmp/agistack-desktop-test-dist/src/features/project-blackboard/projectBlackboardController.js');
const {
  createProjectBlackboardRouteModuleLoader,
} = require('/tmp/agistack-desktop-test-dist/src/features/project-blackboard/projectBlackboardRouteModule.js');

const cloudScope = Object.freeze({
  authority: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
});
const localScope = Object.freeze({ ...cloudScope, authority: 'local' });

const localConfig = Object.freeze({
  apiBaseUrl: 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: 'http://127.0.0.1:43117',
  apiKey: 'local-session',
  localApiToken: 'private-launch',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode: 'local',
  workspaceRoot: '/workspace',
});

test('Project Blackboard cloud client probes the existing canonical collaboration authority', async () => {
  const calls = [];
  const collaborationClient = collaborationAuthority('cloud', calls);
  const client = createProjectBlackboardCloudClient(
    Object.freeze({ ...localConfig, mode: 'cloud', localApiToken: '' }),
    { collaborationClient },
  );
  const snapshot = await client.probe(cloudScope);
  assert.equal(snapshot.availability, 'available');
  assert.equal(snapshot.reasonCode, null);
  assert.equal(snapshot.initialSurface, 'goals');
  assert.equal(snapshot.collaborationClient, collaborationClient);
  assert.deepEqual(calls, [
    { method: 'getSurface', workspaceId: 'workspace-1', surface: 'goals' },
  ]);
});

test('Project Blackboard local client reads sidecar plan/tasks and makes every unsupported surface structured unavailable', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, init = {}) => {
    requests.push({ url: String(url), init });
    if (String(url).endsWith('/plan')) {
      return jsonResponse({
        workspace_id: 'workspace-1',
        project_id: 'project-1',
        plan: null,
        conversation_plans: [{ conversation_id: 'conversation-1', plan: { version: 2 } }],
        plan_history: [],
        run_health: [],
        pending_hitl: [],
        delivery: [],
        artifact_index: [],
      });
    }
    return jsonResponse({
      workspace_id: 'workspace-1',
      items: [{ id: 'task-1', title: 'Local task', status: 'in_progress' }],
      total: 1,
    });
  };
  try {
    const client = createProjectBlackboardLocalClient(localConfig);
    const snapshot = await client.probe(localScope);
    assert.equal(snapshot.availability, 'degraded');
    assert.equal(snapshot.reasonCode, 'local_workspace_plan_read_only');
    assert.equal(snapshot.initialSurface, 'status');
    const status = await snapshot.collaborationClient.getSurface('workspace-1', 'status');
    assert.equal(status.authority, 'local');
    assert.equal(status.status, 'ready');
    assert.equal(status.data.tasks[0].id, 'task-1');
    const discussion = await snapshot.collaborationClient.getSurface(
      'workspace-1',
      'discussion',
    );
    assert.equal(discussion.status, 'unavailable');
    assert.equal(discussion.reason_code, 'local_blackboard_surface_unavailable');
    const mutation = await snapshot.collaborationClient.mutateSurface(
      'workspace-1',
      'status',
      {
        action: 'update_task',
        expected_revision: 0,
        idempotency_key: 'mutation-key',
        payload: { task_id: 'task-1' },
      },
    );
    assert.equal(mutation.status, 'unavailable');
    assert.equal(mutation.reason_code, 'local_blackboard_mutation_unavailable');
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(requests.length, 4);
  for (const { init } of requests) {
    const headers = new Headers(init.headers);
    assert.equal(headers.get('Authorization'), 'Bearer local-session');
    assert.equal(headers.get('X-Agistack-Launch'), 'private-launch');
  }
});

test('Project Blackboard controller maps authority mismatch and forbidden states without leaking stale data', async () => {
  const controller = createProjectBlackboardController({
    authority: 'cloud',
    client: {
      async probe() {
        const error = new Error('forbidden');
        error.status = 403;
        error.payload = { reason_code: 'project_blackboard_forbidden' };
        throw error;
      },
    },
    initialScope: cloudScope,
  });
  await controller.load(cloudScope);
  assert.equal(controller.getSnapshot().state, 'forbidden');
  assert.equal(controller.getSnapshot().reasonCode, 'project_blackboard_forbidden');
  await controller.load(localScope);
  assert.equal(controller.getSnapshot().state, 'unavailable');
  assert.equal(
    controller.getSnapshot().reasonCode,
    'project_blackboard_controller_authority_mismatch',
  );
});

test('Project Blackboard route renders the native collaboration canvas and fails closed without exact scope', async () => {
  let bindingCalls = 0;
  const collaborationClient = collaborationAuthority('cloud', []);
  const module = await createProjectBlackboardRouteModuleLoader({
    createBinding() {
      bindingCalls += 1;
      return {
        controller: readyController(cloudScope, collaborationClient),
        scope: cloudScope,
      };
    },
  })();
  assert.equal(module.routeId, 'project-blackboard-dynamic-project-blackboard');
  const markup = render(module, {
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
  });
  assert.equal(bindingCalls, 1);
  assert.match(markup, /Collaboration canvas/);
  assert.match(markup, /Goals|Discussion|Status/);
  assert.doesNotMatch(markup, /iframe|webview|Open in browser/iu);

  const unavailable = render(module, { tenantId: 'tenant-1', projectId: 'project-1' });
  assert.equal(bindingCalls, 1);
  assert.match(unavailable, /project_blackboard_route_context_unavailable/);
});

function render(module, context) {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(module.Surface, { context, module }),
    ),
  );
}

function readyController(scope, collaborationClient) {
  return {
    subscribe() {
      return () => {};
    },
    getSnapshot() {
      return {
        state: 'ready',
        scope,
        authority: scope.authority,
        reasonCode: null,
        retryVisible: false,
        initialSurface: 'goals',
        collaborationClient,
      };
    },
    async load() {},
    async retry() {},
    cancel() {},
    stop() {},
  };
}

function collaborationAuthority(authority, calls) {
  return Object.freeze({
    async getSurface(workspaceId, surface) {
      calls.push({ method: 'getSurface', workspaceId, surface });
      return {
        workspace_id: workspaceId,
        surface,
        authority,
        status: 'ready',
        revision: 4,
        cursor: 'cursor-4',
        data: { objectives: [], tasks: [] },
        reason_code: null,
      };
    },
    async refetchAuthority(workspaceId, surface) {
      return this.getSurface(workspaceId, surface);
    },
    async mutateSurface(workspaceId, surface) {
      return this.getSurface(workspaceId, surface);
    },
  });
}

function jsonResponse(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}
