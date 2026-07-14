import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  authoritativeRunFromSocketEvent,
  authoritativeRunsFromSocketEvents,
  buildSessionDetailViewModel,
  conversationWithAuthoritativeRun,
  sessionRecoveryPresentation,
  sessionRunActions,
  sessionStatusPresentation,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/sessionViewModel.js'
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

function conversation(overrides = {}) {
  return {
    id: 'conversation-1',
    project_id: 'project-1',
    tenant_id: 'tenant-1',
    user_id: 'user-1',
    title: 'Fix flaky data-pipeline test',
    status: 'active',
    message_count: 3,
    created_at: '2026-07-13T00:00:00Z',
    ...overrides,
  };
}

function build(overrides = {}) {
  return buildSessionDetailViewModel({
    conversation: conversation(),
    config: { ...DEFAULT_CONFIG, llmModel: 'gpt-5.5' },
    workspace: { id: 'workspace-1', name: 'Desktop Client' },
    timeline: {
      conversationId: 'conversation-1',
      items: [{ id: 'event-1', type: 'user_message', eventTimeUs: 1, eventCounter: 1 }],
      loading: false,
      loadingEarlier: false,
      error: null,
      hasMore: false,
      firstCursor: null,
      lastCursor: null,
    },
    tasks: [{ id: 'task-1' }],
    plan: { revision: 2 },
    ...overrides,
  });
}

test('session view model reads explicit mode, stage, environment, permission, and usage', () => {
  const view = build({
    conversation: conversation({
      current_mode: 'build',
      agent_config: { model: 'claude-sonnet-4.5', capability_mode: 'code' },
      metadata: {
        run: {
          stage: 'verify',
          permission_policy: 'ask',
          elapsed_seconds: 1458,
          usage_usd: 1.84,
          environment: {
            id: 'environment-1',
            kind: 'worktree',
            label: 'Worktree · agistack/environment-1',
            branch: 'agistack/environment-1',
          },
        },
        environment: { label: 'Stale environment', branch: 'stale-branch' },
      },
    }),
  });

  assert.equal(view.capabilityMode, 'code');
  assert.equal(view.executionMode, 'build');
  assert.equal(view.stage, 'verify');
  assert.equal(view.environmentLabel, 'Worktree · agistack/environment-1');
  assert.equal(view.branchLabel, 'agistack/environment-1');
  assert.equal(view.modelLabel, 'claude-sonnet-4.5');
  assert.equal(view.permissionLabel, 'ask');
  assert.equal(view.elapsedLabel, '00:24:18');
  assert.equal(view.usageLabel, '$1.84');
  assert.equal(view.taskCount, 1);
  assert.equal(view.eventCount, 1);
  assert.equal(view.hasPlan, true);
});

test('session view model does not infer subjective mode or stage from the title or events', () => {
  const view = build({
    conversation: conversation({
      title: 'Implement code and run tests before review',
      metadata: {},
    }),
  });

  assert.equal(view.capabilityMode, 'unavailable');
  assert.equal(view.executionMode, 'unavailable');
  assert.equal(view.stage, 'unavailable');
  assert.equal(view.permissionLabel, 'Permission policy unavailable');
  assert.equal(view.elapsedLabel, 'Elapsed unavailable');
  assert.equal(view.usageLabel, 'Usage unavailable');
});

test('authoritative run socket events update conversation status by monotonic revision', () => {
  const event = {
    type: 'run_status',
    conversation_id: 'conversation-1',
    payload: {
      id: 'run-1',
      conversation_id: 'conversation-1',
      project_id: 'project-1',
      plan_version_id: 'plan-1',
      idempotency_key: 'approval-1',
      message_id: 'message-1',
      request_message: 'Execute',
      status: 'running',
      revision: 2,
      created_at: '2026-07-13T00:00:00Z',
      updated_at: '2026-07-13T00:00:01Z',
      authorization_snapshot: {},
    },
  };
  const run = authoritativeRunFromSocketEvent(event);
  assert.equal(run?.status, 'running');
  const updated = conversationWithAuthoritativeRun(conversation(), run);
  assert.equal(updated.status, 'running');
  assert.equal(updated.metadata.run.revision, 2);

  const stale = conversationWithAuthoritativeRun(updated, { ...run, status: 'queued', revision: 1 });
  assert.equal(stale, updated);
  const conflicting = conversationWithAuthoritativeRun(updated, {
    ...run,
    status: 'failed',
    revision: 2,
  });
  assert.equal(conflicting, updated);
  const forked = conversationWithAuthoritativeRun(updated, {
    ...run,
    id: 'run-2',
    status: 'running',
    revision: 1,
    created_at: '2026-07-13T00:00:02Z',
    updated_at: '2026-07-13T00:00:02Z',
    authorization_snapshot: { source_run_id: 'run-1', recovery: 'fork' },
  });
  assert.equal(forked.metadata.run.id, 'run-2');
  assert.equal(forked.metadata.run.revision, 1);
  assert.equal(authoritativeRunFromSocketEvent({ type: 'assistant_message', payload: event.payload }), null);
});

test('authoritative run parsing preserves attention, control, recovery, and review states', () => {
  const base = {
    id: 'run-1',
    conversation_id: 'conversation-1',
    project_id: 'project-1',
    plan_version_id: 'plan-1',
    idempotency_key: 'approval-1',
    message_id: 'message-1',
    request_message: 'Execute',
    revision: 3,
    created_at: '2026-07-13T00:00:00Z',
    updated_at: '2026-07-13T00:00:01Z',
    authorization_snapshot: {},
  };
  for (const status of [
    'needs_input',
    'needs_approval',
    'paused',
    'disconnected',
    'cancelled',
    'ready_review',
    'failed',
  ]) {
    assert.equal(authoritativeRunFromSocketEvent({ type: 'run_status', payload: { ...base, status } })?.status, status);
  }
});

test('latest authoritative runs are found across the socket event window', () => {
  const run = (conversationId, revision, status) => ({
    type: 'run_status',
    payload: {
      id: `run-${conversationId}`,
      conversation_id: conversationId,
      project_id: 'project-1',
      plan_version_id: 'plan-1',
      idempotency_key: `approval-${conversationId}`,
      message_id: `message-${conversationId}`,
      request_message: 'Execute',
      status,
      revision,
      created_at: '2026-07-13T00:00:00Z',
      updated_at: `2026-07-13T00:00:0${revision}Z`,
      authorization_snapshot: {},
    },
  });
  const runs = authoritativeRunsFromSocketEvents([
    { type: 'assistant_message', payload: {} },
    run('conversation-1', 3, 'needs_approval'),
    run('conversation-2', 2, 'running'),
    run('conversation-1', 2, 'running'),
  ]);
  assert.deepEqual(
    runs.map((item) => [item.conversation_id, item.revision, item.status]),
    [
      ['conversation-1', 3, 'needs_approval'],
      ['conversation-2', 2, 'running'],
    ]
  );

  const recoveryRuns = authoritativeRunsFromSocketEvents([
    run('conversation-1', 5, 'disconnected'),
    {
      ...run('conversation-1', 1, 'running'),
      payload: {
        ...run('conversation-1', 1, 'running').payload,
        id: 'run-conversation-1-fork',
        created_at: '2026-07-13T00:00:10Z',
        updated_at: '2026-07-13T00:00:10Z',
        authorization_snapshot: {
          source_run_id: 'run-conversation-1',
          recovery: 'fork',
        },
      },
    },
  ]);
  assert.equal(recoveryRuns[0]?.id, 'run-conversation-1-fork');
});

test('session status presentation distinguishes human gates, failure, and review', () => {
  assert.deepEqual(sessionStatusPresentation('needs_input'), {
    tone: 'attention',
    titleKey: 'session.needsInput',
    descriptionKey: 'session.needsInputDescription',
  });
  assert.equal(sessionStatusPresentation('needs_approval')?.titleKey, 'session.needsApproval');
  assert.equal(sessionStatusPresentation('failed')?.tone, 'danger');
  assert.equal(sessionStatusPresentation('interrupted')?.tone, 'warning');
  assert.equal(sessionStatusPresentation('paused')?.titleKey, 'session.runPaused');
  assert.equal(sessionStatusPresentation('disconnected')?.tone, 'danger');
  assert.equal(sessionStatusPresentation('ready_review')?.tone, 'success');
  assert.equal(sessionStatusPresentation('running'), null);
});

test('session run actions expose only valid authoritative transitions', () => {
  assert.deepEqual(sessionRunActions('running'), ['pause', 'cancel']);
  assert.deepEqual(sessionRunActions('paused'), ['resume', 'cancel']);
  assert.deepEqual(sessionRunActions('disconnected'), ['reconnect', 'fork', 'cancel']);
  assert.deepEqual(sessionRunActions('interrupted'), ['reconnect', 'fork', 'cancel']);
  assert.deepEqual(sessionRunActions('ready_review'), ['request_changes', 'approve']);
  assert.deepEqual(sessionRunActions('completed'), []);
  assert.deepEqual(sessionRunActions('needs_approval'), []);
});

test('session recovery choices distinguish reattach authority from a lossy fork', () => {
  assert.deepEqual(sessionRecoveryPresentation('reconnect'), {
    action: 'reconnect',
    labelKey: 'session.reconnectRun',
    titleKey: 'session.reattachTitle',
    descriptionKey: 'session.reattachDescription',
    confirmationRequired: false,
    primary: true,
  });
  assert.deepEqual(sessionRecoveryPresentation('fork'), {
    action: 'fork',
    labelKey: 'session.forkRecovery',
    titleKey: 'session.forkRecoveryTitle',
    descriptionKey: 'session.forkRecoveryDescription',
    confirmationRequired: true,
    primary: false,
    warnings: [
      'session.forkRecoveryNewRun',
      'session.forkRecoveryVerifiedHead',
      'session.forkRecoveryLocalChanges',
    ],
  });
});
