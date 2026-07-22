import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { applyWorkspaceTaskStreamEvent } = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/workspaceTaskEventModel.js',
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

test('workspace task events merge incremental create, update, status, assignment, and delete', () => {
  let tasks = [];
  tasks = applyWorkspaceTaskStreamEvent(tasks, {
    type: 'workspace_task_created',
    data: {
      workspace_id: 'workspace-1',
      task_id: 'task-1',
      title: 'Verify release',
      metadata: { priority: 'p0' },
    },
  }, 'workspace-1').tasks;
  assert.deepEqual(tasks, [{
    id: 'task-1',
    workspace_id: 'workspace-1',
    title: 'Verify release',
    metadata: { priority: 'p0' },
  }]);

  tasks = applyWorkspaceTaskStreamEvent(tasks, {
    type: 'workspace_task_updated',
    data: { workspace_id: 'workspace-1', task_id: 'task-1', changes: { description: 'Run 50 races' } },
  }, 'workspace-1').tasks;
  tasks = applyWorkspaceTaskStreamEvent(tasks, {
    type: 'workspace_task_status_changed',
    data: { workspace_id: 'workspace-1', task_id: 'task-1', new_status: 'in_progress' },
  }, 'workspace-1').tasks;
  tasks = applyWorkspaceTaskStreamEvent(tasks, {
    type: 'workspace_task_assigned',
    data: {
      workspace_id: 'workspace-1', task_id: 'task-1', workspace_agent_id: 'binding-1', status: 'in_progress',
    },
  }, 'workspace-1').tasks;
  assert.deepEqual(tasks[0], {
    id: 'task-1', workspace_id: 'workspace-1', title: 'Verify release',
    description: 'Run 50 races', status: 'in_progress', metadata: { priority: 'p0' },
    workspace_agent_id: 'binding-1',
  });

  tasks = applyWorkspaceTaskStreamEvent(tasks, {
    type: 'workspace_task_deleted',
    data: { workspace_id: 'workspace-1', task_id: 'task-1' },
  }, 'workspace-1').tasks;
  assert.deepEqual(tasks, []);
});

test('workspace task events reject scope drift and identity mutation', () => {
  const existing = [{ id: 'task-1', workspace_id: 'workspace-1', title: 'Stable' }];
  assert.equal(applyWorkspaceTaskStreamEvent(existing, {
    type: 'workspace_task_updated',
    data: { workspace_id: 'workspace-2', task_id: 'task-1', changes: { title: 'Other' } },
  }, 'workspace-1').handled, false);
  assert.equal(applyWorkspaceTaskStreamEvent(existing, {
    type: 'workspace_task_updated',
    data: { workspace_id: 'workspace-1', task_id: 'task-1', changes: { id: 'task-2' } },
  }, 'workspace-1').handled, false);
  assert.equal(applyWorkspaceTaskStreamEvent(existing, {
    type: 'workspace_task_created',
    data: { workspace_id: 'workspace-1', task_id: '', title: 'Invalid' },
  }, 'workspace-1').handled, false);
});

test('Desktop applies workspace task socket events to the active dataset', () => {
  assert.match(appSource, /applyWorkspaceTaskStreamEvent\(/);
  assert.match(appSource, /workspaceTaskEventsHeadRef/);
});
