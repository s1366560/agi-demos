import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  activeConversationId,
  buildSidebarTree,
  chatDeepLink,
  findSidebarOwner,
  linkForAction,
  readConversationSources,
  settledWorkspaceNodes,
  signedDeepLink,
  signedSidebarLoadPhase,
  signedSidebarRetryTarget,
  workspacePagePath,
} = require('/tmp/agistack-desktop-test-dist/src/fullHost/signedSidebarModel.js');

const rowsBinding = {
  command: 'chat-list',
  route: '/tenant/:tenantId/agent-workspace',
  row_route: '/tenant/:tenantId/agent-workspace/:conversationId',
  row_param: 'conversationId',
  group_query: 'workspaceId',
};

function page(overrides) {
  return {
    enabled: true,
    projectId: 'p',
    pluginId: 'memstack-agent',
    commands: ['chat-list', 'chat-create', 'list-directory'],
    page: {
      id: 'chat',
      title: 'Chat',
      routes: ['/tenant/:tenantId/agent-workspace', '/tenant/:tenantId/agent-workspace/:conversationId'],
      targets: ['desktop-renderer'],
      sidebar: { rows: rowsBinding },
      navigation_actions: ['primary-create'],
      ...overrides,
    },
  };
}

test('the full workbench sidebar is the original workspace tree', () => {
  const source = readFileSync(new URL('../src/fullHost/FullWorkbench.tsx', import.meta.url), 'utf8');
  assert.match(source, /<WorkspaceDock/);
  assert.match(source, /selectionMode=\{sidebar\.selectionMode\}/);
  assert.match(source, /onExecutionTargetChange=\{sidebar\.setFilter\}/);
  assert.doesNotMatch(source, /function NavigationGroups/);
});

test('conversation links carry the cloud scope and workspace params', () => {
  const owner = page();
  const path = chatDeepLink(owner, 't', 'p', 'conversation 1', 'workspace 1');
  const query = new URLSearchParams(path.split('?')[1]);
  assert.equal(path.split('?')[0], '/tenant/t/agent-workspace/conversation%201');
  assert.equal(query.get('tenant'), 't');
  assert.equal(query.get('project'), 'p');
  assert.equal(query.get('projectId'), 'p');
  assert.equal(query.get('businessPackage'), 'memstack-agent');
  assert.equal(query.get('workspaceId'), 'workspace 1');
  assert.equal(query.get('packageScope'), null);
  assert.equal(activeConversationId(owner, path), 'conversation 1');
});

test('a tenant page uses packageScope instead of a project id', () => {
  const path = signedDeepLink('/tenant/t/billing', {}, {
    tenant: 't',
    project: null,
    plugin: 'memstack-billing',
  });
  const query = new URLSearchParams(path.split('?')[1]);
  assert.equal(query.get('packageScope'), 'tenant');
  assert.equal(query.get('project'), null);
  assert.equal(query.get('businessPackage'), 'memstack-billing');
});

test('the tree keeps directory groups, local sessions, and unbound chats', () => {
  const sources = readConversationSources([
    { id: 'local-1', label: 'On this computer', target: 'local', group: 'ws', groupLabel: 'Lab' },
    { id: 'cloud-1', label: 'In the cloud', target: 'cloud', group: 'missing', groupLabel: 'Extra' },
    { id: 'loose', label: 'No workspace', hidden: false },
    { id: 'secret', label: 'Hidden', hidden: true },
  ]);
  const all = buildSidebarTree(sources, [{ id: 'ws', name: 'Lab' }], 'all', 't', 'p');
  assert.deepEqual(all.workspaces.map((workspace) => workspace.name), ['Lab', 'Extra']);
  assert.equal(all.conversationsByWorkspace.ws[0].execution_target, 'local');
  assert.equal(all.conversationsByWorkspace[''][0].title, 'No workspace');
  const localOnly = buildSidebarTree(sources, [{ id: 'ws', name: 'Lab' }], 'local', 't', 'p');
  assert.deepEqual(
    Object.values(localOnly.conversationsByWorkspace).flat().map((conversation) => conversation.id),
    ['local-1'],
  );
});

function sessionAvailability(state, count) {
  if (count > 0 && state?.loading) return 'refreshing';
  if (count > 0 && state?.error) return 'stale-error';
  if (count > 0) return 'ready';
  if (!state) return 'deferred';
  if (state.loading) return 'loading';
  if (state.error) return 'error';
  return 'empty';
}

test('a finished workspace with no sessions is empty, not waiting to load', () => {
  const filtered = buildSidebarTree(
    readConversationSources([{ id: 'local-1', label: 'Local only', target: 'local', group: 'ws', groupLabel: 'Lab' }]),
    [{ id: 'ws', name: 'Lab' }],
    'cloud',
    't',
    'p',
  );
  assert.equal(filtered.conversationsByWorkspace.ws, undefined);
  const settled = settledWorkspaceNodes(filtered.workspaces.map((workspace) => workspace.id), {
    loading: false,
    error: '',
  });
  assert.equal(sessionAvailability(undefined, 0), 'deferred');
  assert.equal(sessionAvailability(settled.ws, 0), 'empty');
  assert.equal(
    sessionAvailability(settledWorkspaceNodes(['ws'], { loading: false, error: 'offline' }).ws, 0),
    'error',
  );
});

test('workspace selection opens the detail page, not a nested task route', () => {
  const entries = [
    page(),
    {
      enabled: true,
      projectId: 'p',
      pluginId: 'memstack-workspace',
      commands: [],
      page: {
        id: 'detail',
        title: 'Workspace',
        routes: [
          '/tenant/:tenantId/project/:projectId/workspaces/:workspaceId/tasks/:taskId',
          '/tenant/:tenantId/project/:projectId/workspaces/:workspaceId',
        ],
        targets: ['desktop-renderer'],
      },
    },
  ];
  const path = workspacePagePath(entries, 't', 'p', 'ws');
  assert.equal(path.split('?')[0], '/tenant/t/project/p/workspaces/ws');
  assert.equal(new URLSearchParams(path.split('?')[1]).get('businessPackage'), 'memstack-workspace');
});

test('the sidebar follows the signed page that owns the open route', () => {
  const chat = page();
  const other = page();
  other.pluginId = 'memstack-other';
  other.page = { ...other.page, id: 'other', routes: ['/tenant/:tenantId/project/:projectId/elsewhere'] };
  const owner = findSidebarOwner(
    [other, chat],
    't',
    'p',
    'rows',
    '/tenant/t/agent-workspace/c?tenant=t&project=p',
  );
  assert.equal(owner.pluginId, 'memstack-agent');
  assert.equal(
    linkForAction([chat], [{ id: 'p/memstack-agent/chat', path: '/chat?businessPackage=memstack-agent' }], 't', 'primary-create'),
    '/chat?businessPackage=memstack-agent',
  );
});

test('a tenant installation owns the sidebar when the address names no project', () => {
  const tenant = page();
  tenant.projectId = null;
  tenant.pluginId = 'memstack-billing';
  tenant.page = {
    ...tenant.page,
    id: 'billing',
    routes: ['/tenant/:tenantId/billing'],
    sidebar: { rows: rowsBinding },
  };
  const owner = findSidebarOwner(
    [page(), tenant],
    't',
    null,
    'rows',
    '/tenant/t/billing?packageScope=tenant',
  );
  assert.equal(owner.pluginId, 'memstack-billing');
  assert.equal(
    findSidebarOwner([page()], 't', null, 'rows', '/tenant/t/agent-workspace'),
    null,
  );
});

test('a project page matches the tenant address once the query names that project', () => {
  const chat = page();
  chat.page = {
    ...chat.page,
    routes: ['/tenant/:tenantId/project/:projectId/agent-workspace/:conversationId'],
  };
  const owner = findSidebarOwner(
    [chat],
    't',
    'p',
    'rows',
    '/tenant/t/agent-workspace/c?project=p',
  );
  assert.equal(owner.pluginId, 'memstack-agent');
});

test('the session tree waits out a project switch instead of showing an empty project', () => {
  const base = { project: 'project-next', scopeBlocked: false, pagesLoading: false, switchFailed: false };
  assert.equal(signedSidebarLoadPhase({ ...base, scopeBlocked: true }), 'wait');
  assert.equal(signedSidebarLoadPhase({ ...base, pagesLoading: true }), 'wait');
  assert.equal(signedSidebarLoadPhase({ ...base, switchFailed: true, scopeBlocked: true }), 'blocked');
  assert.equal(signedSidebarLoadPhase(base), 'ready');
  assert.equal(signedSidebarLoadPhase({ ...base, project: null, pagesLoading: true }), 'ready');
  const hook = readFileSync(new URL('../src/fullHost/useSignedSidebar.ts', import.meta.url), 'utf8');
  assert.match(hook, /phase === 'wait'/);
  assert.match(hook, /phase === 'blocked'/);
  assert.match(hook, /setLoading\(true\)/);
  assert.equal(signedSidebarRetryTarget(true), 'scope-switch');
  assert.equal(signedSidebarRetryTarget(false), 'catalog');
  const workbench = readFileSync(new URL('../src/fullHost/FullWorkbench.tsx', import.meta.url), 'utf8');
  assert.match(workbench, /signedSidebarRetryTarget\(Boolean\(scopeSwitchError\)\)/);
  assert.match(workbench, /setSwitchAttempt\(\(attempt\) => attempt \+ 1\)/);
  assert.match(workbench, /switchAttempt,/);
  assert.match(workbench, /onRetryProject=\{retrySidebar\}/);
  assert.doesNotMatch(workbench, /onRetryProject=\{sidebar\.reload\}/);
});
