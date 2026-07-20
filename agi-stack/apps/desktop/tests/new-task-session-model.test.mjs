import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  browserTaskSessionCreationStorage,
  buildLocalTaskSessionRequest,
  canUseNewTaskWorkspaceSelection,
  clearTaskSessionCreationAttempt,
  newTaskWorkspaceLabel,
  readTaskSessionCreationAttempt,
  resolveNewTaskWorkspaceAuthority,
  resolveTaskSessionConflictWorkspace,
  taskSessionCreationAttempt,
  taskSessionCreationFingerprint,
  writeTaskSessionCreationAttempt,
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
  const first = taskSessionCreationAttempt(null, 'definition-a', createKey, 1_000);
  const retry = taskSessionCreationAttempt(first, 'definition-a', createKey, 2_000);
  const changed = taskSessionCreationAttempt(retry, 'definition-b', createKey, 2_000);

  assert.equal(retry, first);
  assert.equal(retry.idempotencyKey, 'task-session-1');
  assert.notEqual(changed.idempotencyKey, retry.idempotencyKey);
  assert.equal(changed.idempotencyKey, 'task-session-2');
});

test('task-session attempt ledger survives modal remount until success clears it', () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  const fingerprint = `sha256:${'a'.repeat(64)}`;
  const attempt = taskSessionCreationAttempt(
    null,
    fingerprint,
    () => 'task-session-durable',
    1_000,
  );

  assert.equal(writeTaskSessionCreationAttempt(storage, attempt), true);
  assert.deepEqual(readTaskSessionCreationAttempt(storage, fingerprint), attempt);
  assert.equal(clearTaskSessionCreationAttempt(storage, fingerprint), true);
  assert.equal(readTaskSessionCreationAttempt(storage, fingerprint), null);
  assert.equal(browserTaskSessionCreationStorage(), null);
});

test('task-session fingerprint tracks only the exact scoped atomic request', () => {
  const config = {
    apiBaseUrl: 'HTTP://LOCALHOST:4317/api/',
    mode: 'local',
    tenantId: ' tenant-1 ',
    projectId: ' project-1 ',
  };
  const definition = {
    title: 'Atomic planning',
    objective: 'Create one reviewable plan',
    kind: 'general',
    workspaceRoot: '/workspace/ignored-for-general',
    contextSources: ['project_files'],
  };
  const fingerprint = taskSessionCreationFingerprint(
    config,
    'actor-a',
    definition,
    'workspace-a',
  );

  assert.match(fingerprint, /^sha256:[a-f0-9]{64}$/);
  assert.equal(
    fingerprint,
    taskSessionCreationFingerprint(
      config,
      'actor-a',
      {
        ...definition,
        workspaceRoot: '/workspace/planning-only',
        contextSources: ['web_research'],
      },
      'workspace-a',
    ),
  );
  assert.notEqual(
    fingerprint,
    taskSessionCreationFingerprint(
      config,
      'actor-a',
      { ...definition, objective: 'Create a different plan' },
      'workspace-a',
    ),
  );
  assert.notEqual(
    fingerprint,
    taskSessionCreationFingerprint(config, 'actor-a', definition, 'workspace-b'),
  );
  assert.equal(
    fingerprint,
    taskSessionCreationFingerprint(config, ' actor-a ', definition, 'workspace-a'),
  );
  assert.equal(
    taskSessionCreationFingerprint(config, null, definition, 'workspace-a'),
    '',
  );
});

test('task-session attempt ledger isolates actors in the same request scope', () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  const config = {
    apiBaseUrl: 'https://desktop.memstack.test/api',
    mode: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
  const definition = {
    title: 'Review provider UX',
    objective: 'Create an actor-scoped review plan',
    kind: 'general',
    workspaceRoot: '',
    contextSources: ['project_memory'],
  };
  const actorAFingerprint = taskSessionCreationFingerprint(
    config,
    'actor-a',
    definition,
    'workspace-a',
  );
  const actorBFingerprint = taskSessionCreationFingerprint(
    config,
    'actor-b',
    definition,
    'workspace-a',
  );
  const actorAAttempt = taskSessionCreationAttempt(
    null,
    actorAFingerprint,
    () => 'task-session-actor-a',
    1_000,
  );
  const actorBAttempt = taskSessionCreationAttempt(
    null,
    actorBFingerprint,
    () => 'task-session-actor-b',
    2_000,
  );

  assert.notEqual(actorAFingerprint, actorBFingerprint);
  assert.equal(writeTaskSessionCreationAttempt(storage, actorAAttempt), true);
  assert.equal(readTaskSessionCreationAttempt(storage, actorBFingerprint), null);
  assert.equal(clearTaskSessionCreationAttempt(storage, actorBFingerprint), true);
  assert.deepEqual(
    readTaskSessionCreationAttempt(storage, actorAFingerprint),
    actorAAttempt,
  );
  assert.equal(writeTaskSessionCreationAttempt(storage, actorBAttempt), true);
  assert.deepEqual(
    readTaskSessionCreationAttempt(storage, actorAFingerprint),
    actorAAttempt,
  );
  assert.deepEqual(
    readTaskSessionCreationAttempt(storage, actorBFingerprint),
    actorBAttempt,
  );
  assert.equal(clearTaskSessionCreationAttempt(storage, actorAFingerprint), true);
  assert.equal(readTaskSessionCreationAttempt(storage, actorAFingerprint), null);
  assert.deepEqual(
    readTaskSessionCreationAttempt(storage, actorBFingerprint),
    actorBAttempt,
  );
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

test('tombstone recovery resolves one live workspace by exact trimmed task title', () => {
  const live = {
    id: 'workspace-live',
    name: 'Retention brief',
    is_archived: false,
  };

  assert.equal(
    resolveTaskSessionConflictWorkspace([live], ' Retention brief '),
    live,
  );
  assert.equal(
    resolveTaskSessionConflictWorkspace(
      [{ ...live, name: 'retention brief' }],
      'Retention brief',
    ),
    null,
  );
  assert.equal(
    resolveTaskSessionConflictWorkspace(
      [{ ...live, is_archived: true }],
      'Retention brief',
    ),
    null,
  );
  assert.equal(
    resolveTaskSessionConflictWorkspace(
      [live, { ...live, id: 'workspace-duplicate' }],
      'Retention brief',
    ),
    null,
  );
});
