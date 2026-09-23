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
  createProjectBlackboardV2Client,
} = require('/tmp/agistack-desktop-test-dist/src/features/project-blackboard/projectBlackboardClient.js');
const {
  createDesktopProjectBlackboardAuthorityV2,
} = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopProjectBlackboardTransportV2.js');
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

test('Project Blackboard V2 client delegates its frozen scope to the generation operations facade', async () => {
  const calls = [];
  const client = createProjectBlackboardV2Client(
    Object.freeze({ ...localConfig, mode: 'cloud', localApiToken: '' }),
    {
      async probeProjectBlackboard(input) {
        calls.push(input);
        return {
          scope: input.scope,
          authority: 'cloud',
          availability: 'available',
          reasonCode: null,
          initialSurface: 'goals',
          allowedActions: ['view', 'select-workspace', 'read-surfaces', 'mutate-surfaces'],
          authorityRevision: 4,
        };
      },
    },
  );
  const snapshot = await client.probe(cloudScope);
  assert.equal(snapshot.availability, 'available');
  assert.equal(snapshot.reasonCode, null);
  assert.equal(snapshot.initialSurface, 'goals');
  assert.equal(snapshot.authorityRevision, 4);
  assert.equal('collaborationClient' in snapshot, false);
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].scope, cloudScope);
  assert.equal(calls[0].config.mode, 'cloud');
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
    // The workspace-core tasks endpoint serves a bare JSON array
    // (Json<Vec<PublicWorkspaceTask>>) — never an {items, total} envelope.
    return jsonResponse([
      { id: 'task-1', title: 'Local task', status: 'in_progress' },
    ]);
  };
  try {
    const authority = createDesktopProjectBlackboardAuthorityV2(localConfig);
    const snapshot = await authority.probeProjectBlackboard(localScope);
    assert.equal(snapshot.availability, 'degraded');
    assert.equal(snapshot.reasonCode, 'local_workspace_plan_read_only');
    assert.equal(snapshot.initialSurface, 'status');
    assert.equal(snapshot.authorityRevision, null);
    const status = await authority.getWorkspaceSurface(
      'project-blackboard',
      'workspace-1',
      'status',
    );
    assert.equal(status.authority, 'local');
    assert.equal(status.status, 'ready');
    assert.equal(status.data.tasks[0].id, 'task-1');
    const discussion = await authority.getWorkspaceSurface(
      'project-blackboard',
      'workspace-1',
      'discussion',
    );
    assert.equal(discussion.status, 'unavailable');
    assert.equal(discussion.reason_code, 'local_blackboard_surface_unavailable');
    const mutation = await authority.mutateWorkspaceSurface(
      'project-blackboard',
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
    collaborationClient: collaborationAuthority('cloud', []),
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
