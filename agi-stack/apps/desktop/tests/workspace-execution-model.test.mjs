import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { summarizeWorkspaceExecution } = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceExecutionModel.js',
);

test('workspace execution summary counts only explicit structured states', () => {
  const summary = summarizeWorkspaceExecution(
    [
      { id: 'task-1', status: 'completed' },
      { id: 'task-2', status: 'in_progress' },
      { id: 'task-3' },
    ],
    {
      conversation_plans: [
        { conversation_id: 'conversation-1' },
        { conversation_id: 'conversation-2' },
      ],
      run_health: [
        { id: 'run-1', status: 'running' },
        { id: 'run-2', status: 'needs_approval' },
        { id: 'run-3', status: 'completed' },
      ],
      pending_hitl: [{ id: 'hitl-1' }, { id: 'hitl-2' }],
      artifact_index: [{ id: 'artifact-1' }, { id: 'artifact-2' }],
      delivery: [{ id: 'delivery-1' }],
    },
  );

  assert.deepEqual(summary, {
    conversations: 2,
    activeRuns: 2,
    attentionRuns: 1,
    taskTotal: 3,
    completedTasks: 1,
    pendingRequests: 2,
    artifacts: 2,
    deliveries: 1,
  });
});

test('workspace execution summary keeps missing projection state explicitly empty', () => {
  assert.deepEqual(summarizeWorkspaceExecution([], null), {
    conversations: 0,
    activeRuns: 0,
    attentionRuns: 0,
    taskTotal: 0,
    completedTasks: 0,
    pendingRequests: 0,
    artifacts: 0,
    deliveries: 0,
  });
});
