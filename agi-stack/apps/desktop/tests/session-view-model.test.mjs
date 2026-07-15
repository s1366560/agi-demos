import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  authoritativeRunFromSocketEvent,
  authoritativeRunsFromSocketEvents,
  buildSessionDetailViewModel,
  conversationWithAuthoritativeRun,
  mergeConversationListWithCurrentRunAuthority,
  sessionRecoveryPresentation,
  sessionStatusPresentation,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/sessionViewModel.js'
);

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
    projection: null,
    ...overrides,
  });
}

function projection(overrides = {}) {
  const authorityConversation = conversation({
    current_mode: 'build',
    agent_config: { model: 'claude-sonnet-4.5', capability_mode: 'code' },
  });
  const currentRun = {
    id: 'run-1',
    conversation_id: 'conversation-1',
    project_id: 'project-1',
    plan_version_id: 'plan-1',
    idempotency_key: 'approval-1',
    message_id: 'message-1',
    request_message: 'Execute',
    status: 'running',
    revision: 4,
    created_at: '2026-07-13T00:00:00Z',
    updated_at: '2026-07-13T00:24:19Z',
    started_at: '2026-07-13T00:00:01Z',
    permission_profile: 'workspace_write',
    environment: {
      id: 'environment-1',
      kind: 'worktree',
      label: 'Worktree · agistack/environment-1',
      workspace_path: '/tmp/environment-1',
      branch: 'agistack/environment-1',
      created_at: '2026-07-13T00:00:00Z',
    },
    authorization_snapshot: {},
  };
  const currentPlan = {
    id: 'plan-1',
    conversation_id: 'conversation-1',
    version: 1,
    status: 'approved',
    tasks: [{ id: 'task-1', conversation_id: 'conversation-1' }],
    created_at: '2026-07-13T00:00:00Z',
  };
  return {
    schemaVersion: 1,
    conversation: authorityConversation,
    executionAuthority: {
      kind: 'desktop_run',
      currentRun,
      runHistory: [currentRun],
      currentAttempt: null,
      attemptHistory: [],
    },
    planAuthority: {
      kind: 'desktop_plan_version',
      currentPlan,
      planHistory: [currentPlan],
      tasks: currentPlan.tasks,
      workspacePlanContext: null,
    },
    hitlAuthority: { kind: 'desktop_hitl', pending: [] },
    artifactAuthority: {
      kind: 'desktop_artifact_versions',
      versions: [],
      deliveries: [],
    },
    activityAuthority: { kind: 'desktop_tool_invocations', invocations: [] },
    cloudEvidenceSummary: null,
    currentRun,
    runHistory: [currentRun],
    currentPlan,
    planHistory: [currentPlan],
    tasks: currentPlan.tasks,
    pendingHitl: [],
    artifactVersions: [],
    artifactDeliveries: [],
    toolInvocations: [],
    evidenceSummary: {
      artifactVersionCount: 0,
      artifactDeliveryCount: 0,
      artifactSourceCount: 0,
      toolInvocationCount: 0,
      unknownOutcomeCount: 0,
      checks: null,
      changes: null,
    },
    capabilities: {
      canSendMessage: false,
      canApprovePlan: false,
      canRespondToHitl: false,
      canSteerNow: true,
      canQueueNext: true,
      canReviewArtifacts: false,
      canDeliverArtifacts: false,
      runActions: ['pause', 'cancel'],
      allowedActions: ['steer_now', 'queue_next', 'pause', 'cancel'],
    },
    snapshotRevision: 'snapshot-1',
    updatedAt: '2026-07-13T00:24:19Z',
    ...overrides,
  };
}

test('session view model reads only the scoped authority projection', () => {
  const view = build({
    conversation: conversation({
      metadata: {
        run: {
          status: 'failed',
          stage: 'verify',
          permission_policy: 'full_access',
          elapsed_seconds: 99,
          usage_usd: 99,
        },
      },
    }),
    projection: projection(),
  });

  assert.equal(view.capabilityMode, 'code');
  assert.equal(view.status, 'running');
  assert.equal(view.executionMode, 'build');
  assert.equal(view.stage, 'unavailable');
  assert.equal(view.environmentLabel, 'Worktree · agistack/environment-1');
  assert.equal(view.branchLabel, 'agistack/environment-1');
  assert.equal(view.modelLabel, 'claude-sonnet-4.5');
  assert.equal(view.permissionLabel, 'workspace_write');
  assert.equal(view.elapsedLabel, '00:24:18');
  assert.equal(view.usageLabel, null);
  assert.equal(view.taskCount, 1);
  assert.equal(view.eventCount, 1);
  assert.equal(view.hasPlan, true);
  assert.deepEqual(view.runActions, ['pause', 'cancel']);
});

test('cloud workspace attempts remain visible without fabricated desktop runtime facts', () => {
  const cloudConversation = conversation({
    current_mode: 'build',
    agent_config: { capability_mode: 'work' },
  });
  const currentAttempt = {
    id: 'attempt-2',
    workspaceTaskId: 'workspace-task-1',
    rootGoalTaskId: 'workspace-task-root',
    workspaceId: 'workspace-1',
    conversationId: 'conversation-1',
    attemptNumber: 2,
    status: 'running',
    workerAgentId: 'agent-worker',
    leaderAgentId: 'agent-leader',
    candidateSummary: null,
    candidateArtifactRefs: [],
    candidateVerificationRefs: [],
    leaderFeedback: null,
    adjudicationReason: null,
    createdAt: '2026-07-13T00:00:00Z',
    updatedAt: '2026-07-13T00:01:00Z',
    completedAt: null,
  };
  const view = build({
    projection: {
      ...projection(),
      schemaVersion: 2,
      conversation: cloudConversation,
      executionAuthority: {
        kind: 'workspace_attempt',
        currentRun: null,
        runHistory: [],
        currentAttempt,
        attemptHistory: [currentAttempt],
      },
      planAuthority: {
        kind: 'agent_task_list',
        currentPlan: null,
        planHistory: [],
        tasks: [{ id: 'task-1', conversation_id: 'conversation-1' }],
        workspacePlanContext: {
          id: 'workspace-plan-1',
          workspaceId: 'workspace-1',
          goalId: 'goal-1',
          status: 'active',
          createdAt: '2026-07-13T00:00:00Z',
          updatedAt: null,
          linkedNodes: [],
        },
      },
      currentRun: null,
      runHistory: [],
      currentPlan: null,
      planHistory: [],
      tasks: [{ id: 'task-1', conversation_id: 'conversation-1' }],
      capabilities: {
        canSendMessage: true,
        canApprovePlan: false,
        canRespondToHitl: false,
        canSteerNow: false,
        canQueueNext: false,
        canReviewArtifacts: false,
        canDeliverArtifacts: false,
        runActions: [],
        allowedActions: ['send_message'],
      },
    },
  });

  assert.equal(view.executionAuthorityKind, 'workspace_attempt');
  assert.equal(view.status, 'running');
  assert.equal(view.attemptNumber, 2);
  assert.equal(view.workerAgentId, 'agent-worker');
  assert.equal(view.leaderAgentId, 'agent-leader');
  assert.equal(view.hasPlan, true);
  assert.equal(view.taskCount, 1);
  assert.equal(view.runId, null);
  assert.equal(view.runRevision, null);
  assert.equal(view.environmentLabel, null);
  assert.equal(view.permissionLabel, null);
  assert.deepEqual(view.runActions, []);
});

test('cloud explore sessions keep their exact runtime mode visible', () => {
  const view = build({
    projection: projection({
      conversation: conversation({
        current_mode: 'explore',
        agent_config: { capability_mode: 'code' },
      }),
    }),
  });

  assert.equal(view.executionMode, 'explore');
});

test('session view model preserves stale read-only context while revoking mutation authority', () => {
  const view = build({
    projection: projection(),
    authorityAvailable: false,
  });

  assert.equal(view.status, 'running');
  assert.equal(view.hasPlan, true);
  assert.equal(view.taskCount, 1);
  assert.deepEqual(view.runActions, []);
});

test('session view model fails closed instead of reading authority from conversation metadata', () => {
  const view = build({
    conversation: conversation({
      title: 'Implement code and run tests before review',
      current_mode: 'build',
      agent_config: { model: 'unsafe-fallback', capability_mode: 'code' },
      metadata: {
        run: {
          id: 'metadata-run',
          status: 'running',
          revision: 9,
          environment: { label: 'Unsafe fallback' },
        },
      },
    }),
    projection: null,
  });

  assert.equal(view.capabilityMode, 'unavailable');
  assert.equal(view.status, 'unavailable');
  assert.equal(view.executionMode, 'unavailable');
  assert.equal(view.stage, 'unavailable');
  assert.equal(view.environmentLabel, null);
  assert.equal(view.modelLabel, null);
  assert.equal(view.permissionLabel, null);
  assert.equal(view.elapsedLabel, null);
  assert.equal(view.usageLabel, null);
  assert.equal(view.runId, null);
  assert.deepEqual(view.runActions, []);
});

test('authoritative run socket events update run metadata without changing conversation lifecycle', () => {
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
  assert.equal(updated.status, 'active');
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

test('conversation list refresh preserves a newer current run without overwriting lifecycle', () => {
  const currentRun = {
    id: 'run-1',
    conversation_id: 'conversation-1',
    project_id: 'project-1',
    plan_version_id: 'plan-1',
    idempotency_key: 'approval-1',
    message_id: 'message-1',
    request_message: 'Execute',
    status: 'needs_approval',
    revision: 5,
    created_at: '2026-07-13T00:00:00Z',
    updated_at: '2026-07-13T00:00:05Z',
    authorization_snapshot: {},
  };
  const current = conversation({ metadata: { run: currentRun } });
  const staleListRow = conversation({
    status: 'active',
    updated_at: '2026-07-13T00:00:03Z',
    metadata: { run: { ...currentRun, status: 'running', revision: 3 } },
  });

  const [merged] = mergeConversationListWithCurrentRunAuthority([staleListRow], [current]);

  assert.equal(merged.status, 'active');
  assert.equal(merged.metadata.run.status, 'needs_approval');
  assert.equal(merged.metadata.run.revision, 5);
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
