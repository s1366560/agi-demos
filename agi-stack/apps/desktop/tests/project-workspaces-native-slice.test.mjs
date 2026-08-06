import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const { DesktopApiError } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const {
  createProjectWorkspacesHttpClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/project-workspaces/projectWorkspacesHttpClient.js');
const {
  createProjectWorkspacesController,
} = require('/tmp/agistack-desktop-test-dist/src/features/project-workspaces/projectWorkspacesController.js');
const {
  createProjectWorkspacesRouteModuleLoader,
} = require('/tmp/agistack-desktop-test-dist/src/features/project-workspaces/projectWorkspacesRouteModule.js');

const cloudConfig = Object.freeze({
  apiBaseUrl: 'https://cloud.memstack.test',
  deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
  apiKey: 'trusted-session',
  localApiToken: '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode: 'cloud',
  workspaceRoot: '/workspace',
});

const localConfig = Object.freeze({
  ...cloudConfig,
  apiBaseUrl: 'http://127.0.0.1:43117',
  apiKey: 'local-session',
  localApiToken: 'private-launch',
  mode: 'local',
});

const cloudScope = Object.freeze({
  authority: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
});

const localScope = Object.freeze({ ...cloudScope, authority: 'local' });

test('Project Workspaces cloud client uses trusted-session authority for lifecycle and roster actions', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  const payloads = [
    [workspacePayload()],
    workspacePayload({ id: 'workspace-2', name: 'Created' }),
    workspacePayload({ name: 'Renamed' }),
    [memberPayload()],
    memberPayload({ user_id: 'user-2' }),
    memberPayload({ role: 'editor' }),
    null,
    [agentPayload()],
    agentPayload({ agent_id: 'agent-2' }),
    null,
  ];
  globalThis.fetch = async (url, init = {}) => {
    requests.push({ url: String(url), init });
    const payload = payloads.shift();
    return response(payload, init.method === 'DELETE' ? 204 : 200);
  };
  try {
    const client = createProjectWorkspacesHttpClient(cloudConfig);
    const listed = await client.list(cloudScope);
    assert.equal(listed.availability, 'available');
    assert.equal(listed.reasonCode, null);
    assert.equal(listed.workspaces[0].tenantId, 'tenant-1');
    await client.create(cloudScope, { name: 'Created', description: '' });
    await client.update(cloudScope, 'workspace-1', {
      name: 'Renamed',
      description: 'Updated',
      archived: false,
    });
    await client.listMembers(cloudScope, 'workspace-1');
    await client.addMember(cloudScope, 'workspace-1', { userId: 'user-2', role: 'viewer' });
    await client.updateMemberRole(cloudScope, 'workspace-1', 'user-1', 'editor');
    await client.removeMember(cloudScope, 'workspace-1', 'user-1');
    await client.listAgents(cloudScope, 'workspace-1');
    await client.bindAgent(cloudScope, 'workspace-1', { agentId: 'agent-2' });
    await client.unbindAgent(cloudScope, 'workspace-1', 'binding-1');
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(
    requests.map(({ init }) => init.method ?? 'GET'),
    ['GET', 'POST', 'PATCH', 'GET', 'POST', 'PATCH', 'DELETE', 'GET', 'POST', 'DELETE'],
  );
  assert.equal(
    requests[0].url,
    'https://cloud.memstack.test/api/v1/tenants/tenant-1/projects/project-1/workspaces?limit=500&offset=0',
  );
  assert.equal(
    requests[9].url,
    'https://cloud.memstack.test/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/agents/binding-1',
  );
  for (const { init } of requests) {
    const headers = new Headers(init.headers);
    assert.equal(headers.get('Authorization'), 'Bearer trusted-session');
    assert.equal(headers.has('X-Agistack-Launch'), false);
  }
});

test('Project Workspaces local client uses sidecar authority and fails closed for unsupported mutations', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, init = {}) => {
    requests.push({ url: String(url), init });
    return response(init.method === 'POST' ? workspacePayload() : [workspacePayload()]);
  };
  try {
    const client = createProjectWorkspacesHttpClient(localConfig);
    const snapshot = await client.list(localScope);
    assert.equal(snapshot.availability, 'degraded');
    assert.equal(snapshot.reasonCode, 'local_workspace_lifecycle_partial');
    assert.deepEqual(snapshot.allowedActions, ['view', 'list', 'create', 'open-blackboard']);
    await client.create(localScope, { name: 'Local', description: '' });
    await assert.rejects(
      client.update(localScope, 'workspace-1', {
        name: 'Blocked',
        description: '',
        archived: false,
      }),
      (error) =>
        error instanceof DesktopApiError &&
        error.status === 501 &&
        error.payload.reason_code === 'local_workspace_update_unavailable',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(requests.length, 2);
  for (const { init } of requests) {
    const headers = new Headers(init.headers);
    assert.equal(headers.get('Authorization'), 'Bearer local-session');
    assert.equal(headers.get('X-Agistack-Launch'), 'private-launch');
  }
});

test('Project Workspaces controller hides stale scopes and maps forbidden authority responses', async () => {
  const deferred = Promise.withResolvers();
  const client = {
    list(scope) {
      return scope.projectId === 'project-1'
        ? deferred.promise
        : Promise.reject(
            new DesktopApiError('forbidden', 403, {
              reason_code: 'project_workspaces_forbidden',
            }),
          );
    },
  };
  const controller = createProjectWorkspacesController({
    authority: 'cloud',
    client,
    initialScope: cloudScope,
  });
  const first = controller.load(cloudScope);
  const nextScope = Object.freeze({ ...cloudScope, projectId: 'project-2' });
  await controller.load(nextScope);
  assert.equal(controller.getSnapshot().state, 'forbidden');
  assert.equal(controller.getSnapshot().scope.projectId, 'project-2');
  deferred.resolve(snapshot(cloudScope));
  await first;
  assert.equal(controller.getSnapshot().scope.projectId, 'project-2');
});

test('Project Workspaces route is native, scope-bound and opens the canonical Blackboard target', async () => {
  const opened = [];
  let renderedBinding = null;
  const module = await createProjectWorkspacesRouteModuleLoader({
    createBinding(context) {
      renderedBinding = {
        controller: readyController(cloudScope),
        scope: cloudScope,
        openBlackboard(workspaceId) {
          opened.push({ ...context, workspaceId });
        },
      };
      return renderedBinding;
    },
  })();
  assert.equal(module.routeId, 'project-project-workspaces');
  assert.equal(module.disposition, 'implemented');
  const markup = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(module.Surface, {
        context: { tenantId: 'tenant-1', projectId: 'project-1' },
        module,
      }),
    ),
  );
  assert.match(markup, /Alpha workspace/);
  assert.match(markup, /Collaboration canvas/);
  assert.doesNotMatch(markup, /iframe|webview|Open in browser/iu);
  renderedBinding.openBlackboard('workspace-1');
  assert.deepEqual(opened, [
    { tenantId: 'tenant-1', projectId: 'project-1', workspaceId: 'workspace-1' },
  ]);
});

function readyController(scope) {
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
        busyAction: null,
        allowedActions: [
          'view',
          'list',
          'create',
          'update',
          'add-member',
          'update-member-role',
          'remove-member',
          'bind-agent',
          'unbind-agent',
          'open-blackboard',
        ],
        workspaces: [workspaceRecord()],
      };
    },
    async load() {},
    async retry() {},
    async create() {},
    cancel() {},
    stop() {},
  };
}

function snapshot(scope) {
  return {
    scope,
    authority: scope.authority,
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: '1.0.0',
    authorityRevision: null,
    allowedActions: ['view', 'list', 'create', 'open-blackboard'],
    workspaces: [workspaceRecord()],
  };
}

function workspaceRecord(overrides = {}) {
  return {
    id: 'workspace-1',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    name: 'Alpha workspace',
    description: 'Native workspace',
    archived: false,
    createdAt: '2026-08-05T00:00:00Z',
    updatedAt: null,
    ...overrides,
  };
}

function workspacePayload(overrides = {}) {
  const record = workspaceRecord(overrides);
  return {
    id: record.id,
    tenant_id: record.tenantId,
    project_id: record.projectId,
    name: record.name,
    created_by: 'user-1',
    description: record.description,
    is_archived: record.archived,
    metadata: {},
    office_status: 'idle',
    hex_layout_config: {},
    created_at: record.createdAt,
    updated_at: record.updatedAt,
  };
}

function memberPayload(overrides = {}) {
  return {
    id: 'member-1',
    workspace_id: 'workspace-1',
    user_id: 'user-1',
    user_email: 'user@example.test',
    role: 'viewer',
    invited_by: 'owner-1',
    created_at: '2026-08-05T00:00:00Z',
    updated_at: null,
    ...overrides,
  };
}

function agentPayload(overrides = {}) {
  return {
    id: 'binding-1',
    workspace_id: 'workspace-1',
    agent_id: 'agent-1',
    display_name: 'Agent',
    description: null,
    config: {},
    is_active: true,
    hex_q: null,
    hex_r: null,
    theme_color: null,
    label: null,
    status: 'active',
    created_at: '2026-08-05T00:00:00Z',
    updated_at: null,
    ...overrides,
  };
}

function response(payload, status = 200) {
  const body = status === 204 ? null : JSON.stringify(payload);
  return new Response(body, {
    status,
    headers: body === null ? {} : { 'Content-Type': 'application/json' },
  });
}
