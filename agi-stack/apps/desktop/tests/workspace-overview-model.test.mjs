import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { buildWorkspaceOverviewModel } = require(
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
