import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  buildLocalTaskSessionRequest,
  canUseNewTaskWorkspaceSelection,
  newTaskWorkspaceLabel,
  resolveNewTaskWorkspaceAuthority,
  taskSessionCreationAttempt,
} = require('/tmp/agistack-desktop-test-dist/src/features/task/newTaskSessionModel.js');

const workspaces = [
  { id: 'workspace-a', name: 'Workspace A' },
  { id: 'workspace-b', name: 'Workspace B' },
];

test('workspace authority fails closed while loading, errored, unavailable, or stale', () => {
  const unavailable = resolveNewTaskWorkspaceAuthority(undefined, workspaces);
  const loading = resolveNewTaskWorkspaceAuthority(
    { loading: true, error: null },
    workspaces,
  );
  const failed = resolveNewTaskWorkspaceAuthority(
    { loading: false, error: 'offline' },
    workspaces,
  );
  const ready = resolveNewTaskWorkspaceAuthority(
    { loading: false, error: null },
    workspaces,
  );
  const readyEmpty = resolveNewTaskWorkspaceAuthority(
    { loading: false, error: null },
    [],
  );

  assert.equal(unavailable.status, 'unavailable');
  assert.equal(loading.status, 'loading');
  assert.equal(failed.status, 'error');
  assert.equal(ready.status, 'ready');
  assert.equal(canUseNewTaskWorkspaceSelection(unavailable, '__new_workspace__'), false);
  assert.equal(canUseNewTaskWorkspaceSelection(loading, '__new_workspace__'), false);
  assert.equal(canUseNewTaskWorkspaceSelection(failed, 'workspace-a'), false);
  assert.equal(canUseNewTaskWorkspaceSelection(ready, 'workspace-stale'), false);
  assert.equal(canUseNewTaskWorkspaceSelection(ready, 'workspace-a'), true);
  assert.equal(canUseNewTaskWorkspaceSelection(ready, '__new_workspace__'), true);
  assert.equal(readyEmpty.status, 'ready');
  assert.equal(canUseNewTaskWorkspaceSelection(readyEmpty, '__new_workspace__'), true);
});

test('task-session idempotency remains stable for one unchanged creation attempt', () => {
  let sequence = 0;
  const createKey = () => `task-session-${++sequence}`;
  const first = taskSessionCreationAttempt(null, 'definition-a', createKey);
  const retry = taskSessionCreationAttempt(first, 'definition-a', createKey);
  const changed = taskSessionCreationAttempt(retry, 'definition-b', createKey);

  assert.equal(retry, first);
  assert.equal(retry.idempotencyKey, 'task-session-1');
  assert.notEqual(changed.idempotencyKey, retry.idempotencyKey);
  assert.equal(changed.idempotencyKey, 'task-session-2');
});

test('local task-session request uses the exact create workspace union', () => {
  assert.deepEqual(
    buildLocalTaskSessionRequest(
      {
        title: 'Implement atomic planning',
        objective: 'Persist one bound planning session',
        kind: 'programming',
        workspaceRoot: '/workspace/repository',
        contextSources: ['project_files'],
      },
      '__new_workspace__',
      'task-session-1',
    ),
    {
      idempotency_key: 'task-session-1',
      workspace: {
        kind: 'create',
        name: 'Implement atomic planning',
        description: 'Persist one bound planning session',
        metadata: { source: 'desktop' },
        use_case: 'programming',
        collaboration_mode: 'multi_agent_shared',
        sandbox_code_root: '/workspace/repository',
      },
      conversation: {
        title: 'Implement atomic planning',
        capability_mode: 'code',
      },
      initial_message: { content: 'Persist one bound planning session' },
    },
  );
});

test('local task-session request uses the exact existing workspace union', () => {
  const request = buildLocalTaskSessionRequest(
    {
      title: 'Research provider UX',
      objective: 'Summarize the current provider workflow',
      kind: 'general',
      workspaceRoot: '/workspace/repository',
      contextSources: ['project_memory'],
    },
    'workspace-a',
    'task-session-existing',
  );

  assert.deepEqual(request.workspace, {
    kind: 'existing',
    workspace_id: 'workspace-a',
  });
  assert.deepEqual(request.conversation, {
    title: 'Research provider UX',
    capability_mode: 'work',
  });
});

test('planning label prefers the atomically persisted workspace before catalog refresh', () => {
  assert.equal(
    newTaskWorkspaceLabel(
      { id: 'workspace-retention', name: 'Retention workspace' },
      null,
      'workspace-retention',
      'Create a new workspace',
    ),
    'Retention workspace',
  );
  assert.equal(
    newTaskWorkspaceLabel(
      { id: 'workspace-retention', title: 'Retention title' },
      { id: 'workspace-retention', name: 'Stale catalog name' },
      'workspace-retention',
      'Create a new workspace',
    ),
    'Retention title',
  );
});
