import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { applyWorkspaceLifecycleStreamEvent } = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/workspaceLifecycleEventModel.js',
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const ready = (items) => ({ status: 'ready', items, error: null });
const workspace = (id, name, projectId = 'project-1') => ({
  id,
  tenant_id: 'tenant-1',
  project_id: projectId,
  name,
  created_by: 'user-1',
  is_archived: false,
  created_at: '2026-07-22T08:00:00Z',
});
const dataset = () => ({
  workspaces: [workspace('workspace-1', 'Alpha'), workspace('workspace-2', 'Beta')],
  workspacesByProject: {
    'project-1': [workspace('workspace-1', 'Alpha'), workspace('workspace-2', 'Beta')],
  },
  conversationsByWorkspace: {
    'workspace-1': [{ id: 'conversation-1' }],
    'workspace-2': [{ id: 'conversation-2' }],
  },
  nodeState: {
    projects: { 'project-1': { loading: false, error: null } },
    workspaces: {
      'workspace-1': { loading: false, error: null },
      'workspace-2': { loading: false, error: null },
    },
  },
  messages: [{ id: 'message-1', content: 'old workspace' }],
  tasks: [{ id: 'task-1' }],
  plan: { workspace_id: 'workspace-1' },
  workspaceMembers: ready([{ id: 'member-1' }]),
  workspaceAgents: ready([{ id: 'binding-1' }]),
  sandbox: null,
  myWork: [],
  myWorkError: null,
});
const scope = {
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
};

test('workspace lifecycle updates replace the authoritative workspace record', () => {
  const current = dataset();
  const renamed = workspace('workspace-1', 'Renamed');
  const result = applyWorkspaceLifecycleStreamEvent(current, {
    type: 'workspace_updated',
    data: { workspace_id: 'workspace-1', workspace: renamed },
  }, scope);

  assert.equal(result.handled, true);
  assert.equal(result.activeWorkspaceDeleted, false);
  assert.equal(result.dataset.workspaces[0].name, 'Renamed');
  assert.equal(result.dataset.workspacesByProject['project-1'][0].name, 'Renamed');
  assert.equal(result.nextWorkspaceId, 'workspace-1');
});

test('deleting the active workspace prunes its hierarchy and clears workspace-owned state', () => {
  const result = applyWorkspaceLifecycleStreamEvent(dataset(), {
    type: 'workspace_deleted', data: { workspace_id: 'workspace-1' },
  }, scope);

  assert.equal(result.handled, true);
  assert.equal(result.activeWorkspaceDeleted, true);
  assert.equal(result.nextWorkspaceId, 'workspace-2');
  assert.deepEqual(result.dataset.workspaces.map(({ id }) => id), ['workspace-2']);
  assert.deepEqual(Object.keys(result.dataset.conversationsByWorkspace), ['workspace-2']);
  assert.deepEqual(Object.keys(result.dataset.nodeState.workspaces), ['workspace-2']);
  assert.deepEqual(result.dataset.messages, []);
  assert.deepEqual(result.dataset.tasks, []);
  assert.equal(result.dataset.plan, null);
  assert.equal(result.dataset.workspaceMembers.status, 'unavailable');
  assert.equal(result.dataset.workspaceAgents.status, 'unavailable');
});

test('workspace lifecycle events fail closed for malformed or cross-scope records', () => {
  const current = dataset();
  for (const event of [
    { type: 'workspace_updated', data: {
      workspace_id: 'workspace-1', workspace: workspace('workspace-1', 'Wrong', 'project-2'),
    } },
    { type: 'workspace_updated', data: {
      workspace_id: 'workspace-1', workspace: { id: 'workspace-1', name: 'Incomplete' },
    } },
    { type: 'workspace_deleted', data: { workspace_id: 'workspace-unknown' } },
  ]) {
    const result = applyWorkspaceLifecycleStreamEvent(current, event, scope);
    assert.equal(result.handled, false);
    assert.equal(result.dataset, current);
  }
});

test('Desktop applies workspace lifecycle socket events and refreshes a deleted selection', () => {
  assert.match(appSource, /applyWorkspaceLifecycleStreamEvent\(/);
  assert.match(appSource, /workspaceLifecycleEventsHeadRef/);
  assert.match(appSource, /activeWorkspaceDeleted/);
  assert.match(appSource, /refreshRuntime\(nextConfig\)/);
});
