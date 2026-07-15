import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  beginDesktopRuntimeScopeTransition,
  beginWorkspaceRuntimeTransition,
  buildWorkspaceOverviewModel,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceOverviewModel.js'
);

function conversation(id, title, runStatus, participantAgents = []) {
  return {
    id,
    project_id: 'project-1',
    tenant_id: 'tenant-1',
    user_id: 'user-1',
    workspace_id: 'workspace-1',
    title,
    status: 'active',
    message_count: 3,
    participant_agents: participantAgents,
    created_at: '2026-07-13T00:00:00Z',
    updated_at: '2026-07-14T09:30:00Z',
    agent_config: { capability_mode: id === 'conversation-code' ? 'code' : 'work' },
    metadata: { run: { status: runStatus } },
  };
}

test('workspace overview projects only authoritative workspace and project fields', () => {
  const model = buildWorkspaceOverviewModel({
    workspace: {
      id: 'workspace-1',
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      name: 'Desktop Client',
      description: 'Application experience, frontend, and Rust runtime delivery.',
      office_status: 'online',
      metadata: {
        collaboration_mode: 'multi_agent_shared',
        member_count: 8,
      },
      updated_at: '2026-07-14T09:32:00Z',
    },
    project: {
      id: 'project-1',
      tenant_id: 'tenant-1',
      name: 'Desktop Client',
      stats: {
        memory_count: 248,
        node_count: 1842,
        storage_used: 641728512,
        recent_activity: [
          { title: 'Targeted test suite passed', detail: 'Code agent · 2 min ago' },
        ],
      },
    },
    conversations: [
      conversation('conversation-code', 'Fix flaky data-pipeline test', 'running', [
        'planner',
        'coder',
      ]),
      conversation('conversation-input', 'Review auth middleware refactor', 'needs_approval', [
        'reviewer',
      ]),
      conversation('conversation-ready', 'Add task search shortcuts', 'ready_review', [
        'planner',
        'researcher',
      ]),
    ],
    plan: {
      root_goal: {
        title: 'Ship a dependable desktop agent workspace across Work and Code.',
      },
    },
    sandboxStatus: 'connected',
    connection: 'ready',
  });

  assert.equal(model.workspaceName, 'Desktop Client');
  assert.equal(model.officeStatus, 'online');
  assert.equal(model.rootGoal, 'Ship a dependable desktop agent workspace across Work and Code.');
  assert.deepEqual(model.sessionCounts, { total: 3, running: 1, attention: 1, ready: 1 });
  assert.equal(model.memberCount, 8);
  assert.equal(model.activeAgentCount, 4);
  assert.deepEqual(model.knowledge, {
    memories: 248,
    graphNodes: 1842,
    storageBytes: 641728512,
  });
  assert.equal(model.recentSessions[0].capabilityMode, 'code');
  assert.equal(model.recentSessions[1].status, 'needs_approval');
  assert.deepEqual(model.recentActivity, [
    { title: 'Targeted test suite passed', detail: 'Code agent · 2 min ago' },
  ]);
  assert.deepEqual(model.environment, { sandboxStatus: 'connected', connection: 'ready' });
});

test('workspace overview exposes unavailable values instead of inventing operational data', () => {
  const model = buildWorkspaceOverviewModel({
    workspace: null,
    project: null,
    conversations: [],
    plan: null,
    sandboxStatus: null,
    connection: 'idle',
  });

  assert.equal(model.workspaceName, null);
  assert.equal(model.rootGoal, null);
  assert.equal(model.memberCount, null);
  assert.equal(model.activeAgentCount, null);
  assert.deepEqual(model.knowledge, {
    memories: null,
    graphNodes: null,
    storageBytes: null,
  });
  assert.deepEqual(model.recentSessions, []);
  assert.deepEqual(model.recentActivity, []);
});

test('workspace transition clears only payload owned by the previous workspace', () => {
  const dataset = {
    workspaces: [{ id: 'workspace-a' }, { id: 'workspace-b' }],
    workspacesByProject: {
      'project-1': [{ id: 'workspace-a' }, { id: 'workspace-b' }],
    },
    conversationsByWorkspace: {
      'workspace-a': [conversation('conversation-a', 'Old session', 'running')],
      'workspace-b': [conversation('conversation-b', 'New session', 'ready_review')],
    },
    nodeState: { projects: {}, workspaces: {} },
    messages: [{ id: 'message-a', content: 'old workspace message' }],
    tasks: [{ id: 'task-a', title: 'Old workspace task' }],
    plan: { workspace_id: 'workspace-a', root_goal: 'Old workspace goal' },
    sandbox: { id: 'sandbox-a', status: 'running' },
    myWork: [{ id: 'work-a', project_id: 'project-1' }],
    myWorkError: null,
  };

  const transitioned = beginWorkspaceRuntimeTransition(dataset);

  assert.equal(transitioned.workspaces, dataset.workspaces);
  assert.equal(transitioned.conversationsByWorkspace, dataset.conversationsByWorkspace);
  assert.equal(transitioned.myWork, dataset.myWork);
  assert.deepEqual(transitioned.messages, []);
  assert.deepEqual(transitioned.tasks, []);
  assert.equal(transitioned.plan, null);
  assert.equal(transitioned.sandbox, dataset.sandbox);
});

test('desktop runtime transition invalidates data at its exact authority boundary', () => {
  const dataset = {
    workspaces: [{ id: 'workspace-a' }],
    workspacesByProject: { 'project-1': [{ id: 'workspace-a' }] },
    conversationsByWorkspace: { 'workspace-a': [] },
    nodeState: { projects: {}, workspaces: {} },
    messages: [{ id: 'message-a', content: 'workspace message' }],
    tasks: [{ id: 'task-a', title: 'Workspace task' }],
    plan: { workspace_id: 'workspace-a' },
    sandbox: { id: 'sandbox-a', status: 'running' },
    myWork: [{ id: 'work-a', project_id: 'project-1' }],
    myWorkError: 'stale project warning',
  };
  const previousConfig = {
    mode: 'cloud',
    apiBaseUrl: 'http://127.0.0.1:8000',
    apiKey: 'session-a',
    localApiToken: '',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-a',
  };

  assert.equal(
    beginDesktopRuntimeScopeTransition(dataset, previousConfig, previousConfig),
    dataset
  );

  const workspaceChanged = beginDesktopRuntimeScopeTransition(dataset, previousConfig, {
    ...previousConfig,
    workspaceId: 'workspace-b',
  });
  assert.deepEqual(workspaceChanged.messages, []);
  assert.equal(workspaceChanged.sandbox, dataset.sandbox);
  assert.equal(workspaceChanged.myWork, dataset.myWork);

  const projectChanged = beginDesktopRuntimeScopeTransition(dataset, previousConfig, {
    ...previousConfig,
    projectId: 'project-2',
    workspaceId: '',
  });
  assert.deepEqual(projectChanged, {
    workspaces: [],
    workspacesByProject: {},
    conversationsByWorkspace: {},
    nodeState: { projects: {}, workspaces: {} },
    messages: [],
    tasks: [],
    plan: null,
    sandbox: null,
    myWork: [],
    myWorkError: null,
  });
});
