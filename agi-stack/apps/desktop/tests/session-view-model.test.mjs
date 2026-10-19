import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const {
  authoritativeRunFromSessionProjection,
  authoritativeRunFromSocketEvent,
  authoritativeRunsFromSocketEvents,
  buildSessionDetailViewModel,
  conversationWithAuthoritativeRun,
  mergeConversationListWithCurrentRunAuthority,
  respondableHitlRequestsForProjection,
  sessionLiveIndicator,
  sessionRecoveryPresentation,
  sessionRunStatusIsTerminal,
  sessionStatusPresentation,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/sessionViewModel.js'
);
const { buildWorkspaceOverviewModel } = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceOverviewModel.js'
);
const { conversationTreeStatusValue, conversationTreeStatusPresentation } = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceTreeModel.js'
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

test('waiting runs render an enabled formal Stop without offering Resume', () => {
  const React = require('react');
  const jsx = require('react/jsx-runtime');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
  const { SessionWorkspace } = require('/tmp/agistack-desktop-test-dist/src/features/session/SessionWorkspace.js');
  const originals = { jsx: jsx.jsx, jsxs: jsx.jsxs };
  const buttons = [];
  const intercept = (delegate) => (type, props, ...rest) => {
    if (type === 'button') buttons.push(props);
    return delegate(type, props, ...rest);
  };
  try {
    jsx.jsx = intercept(originals.jsx);
    jsx.jsxs = intercept(originals.jsxs);
    for (const status of ['needs_input', 'needs_approval']) {
      const authority = projection();
      authority.currentRun.status = status;
      authority.capabilities.runActions = ['cancel'];
      authority.capabilities.allowedActions = ['cancel'];
      const view = build({ projection: authority });
      const actions = [];
      buttons.length = 0;
      const html = renderToStaticMarkup(React.createElement(I18nProvider, null,
        React.createElement(SessionWorkspace, {
          viewModel: view, thread: null, onOpenCanvas() {}, runActionPending: null,
          liveConnected: false, liveError: null,
          onRunAction: (action) => actions.push(action),
        })));
      assert.deepEqual(view.runActions, ['cancel']);
      assert.doesNotMatch(html, /Resume|Reattach/u);
      const stop = buttons.find((button) => React.Children.toArray(button.children).includes('Stop'));
      assert.ok(stop, status);
      assert.equal(stop.disabled, false);
      stop.onClick();
      assert.deepEqual(actions, ['cancel']);
    }
  } finally {
    jsx.jsx = originals.jsx;
    jsx.jsxs = originals.jsxs;
  }
});

test('loaded tool activity pairs events without changing authority evidence', () => {
  const items = [
    { id: 'thought', type: 'thought', eventTimeUs: 1, eventCounter: 1 },
    { id: 'call', type: 'act', toolName: 'read', execution_id: 'read-1', eventTimeUs: 2, eventCounter: 2 },
    { id: 'result', type: 'observe', toolName: 'read', execution_id: 'read-1', eventTimeUs: 3, eventCounter: 3 },
    { id: 'failed', type: 'observe', toolName: 'read', execution_id: 'read-2', isError: true, eventTimeUs: 4, eventCounter: 4 },
  ];
  for (const hasMore of [false, true]) {
    const planProjection = projection({
      conversation: conversation({ current_mode: 'plan' }),
      currentRun: null,
    });
    const view = build({
      projection: planProjection,
      timeline: { conversationId: 'conversation-1', items, loading: false, loadingEarlier: hasMore, hasMore, error: null },
    });
    assert.equal(view.observedToolActivityCount, 2);
    assert.equal(view.observedFailedToolActivityCount, 1);
    assert.equal(view.toolActivityCount, 0);
    assert.equal(view.failedToolActivityCount, 0);
    assert.equal(view.executionMode, 'plan');
    assert.equal(view.permissionLabel, null);
  }
});

test('loaded tool activity ignores a different conversation and unavailable history', () => {
  for (const timeline of [
    { conversationId: 'conversation-2', items: [{ type: 'act', toolName: 'read' }], loading: false },
    { conversationId: null, items: [], loading: false },
    { conversationId: 'conversation-1', items: [], loading: true },
    { conversationId: 'conversation-1', items: [], loading: false, error: 'history unavailable' },
  ]) {
    const view = build({ projection: projection(), timeline });
    assert.equal(view.observedToolActivityCount, null);
    assert.equal(view.observedFailedToolActivityCount, null);
  }
  const empty = build();
  assert.equal(empty.observedToolActivityCount, 0);
  assert.equal(empty.observedFailedToolActivityCount, 0);
});

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
  assert.equal(view.summary, null);
  assert.equal(view.conversationMode, null);
  assert.equal(view.participantCount, 1);
  assert.equal(view.linkedTaskId, null);
  assert.equal(view.environmentLabel, 'Worktree · agistack/environment-1');
  assert.equal(view.branchLabel, 'agistack/environment-1');
  assert.equal(view.modelLabel, 'claude-sonnet-4.5');
  assert.equal(view.permissionLabel, 'workspace_write');
  assert.equal(view.elapsedLabel, '00:24:18');
  assert.equal(view.usageLabel, null);
  assert.equal(view.taskCount, 1);
  assert.equal(view.eventCount, 1);
  assert.equal(view.hasPlan, true);
  assert.equal(view.planStatus, 'approved');
  assert.equal(view.artifactCount, 0);
  assert.equal(view.sourceCount, 0);
  assert.equal(view.verificationCount, null);
  assert.equal(view.toolActivityCount, 0);
  assert.equal(view.failedToolActivityCount, 0);
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
      cloudEvidenceSummary: {
        candidateArtifactRefCount: 0,
        candidateVerificationRefCount: 0,
        artifactRecordCount: 0,
        toolExecutionRecordCount: 0,
        failedToolExecutionCount: 0,
      },
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
  assert.equal(view.planStatus, 'active');
  assert.equal(view.taskCount, 1);
  assert.equal(view.artifactCount, 0);
  assert.equal(view.verificationCount, 0);
  assert.equal(view.toolActivityCount, 0);
  assert.equal(view.failedToolActivityCount, 0);
  assert.equal(view.runId, null);
  assert.equal(view.runRevision, null);
  assert.equal(view.environmentLabel, null);
  assert.equal(view.permissionLabel, null);
  assert.deepEqual(view.runActions, []);
});

test('cloud agent plan versions remain visible without a workspace plan context', () => {
  const currentPlan = {
    id: 'cloud-plan-version-2',
    conversation_id: 'conversation-1',
    version: 2,
    status: 'draft',
    tasks: [],
    created_at: '2026-07-13T00:02:00Z',
    approved_at: null,
  };
  const view = build({
    projection: projection({
      schemaVersion: 2,
      currentPlan,
      planHistory: [currentPlan],
      planAuthority: {
        kind: 'agent_task_list',
        currentPlan: null,
        planHistory: [],
        tasks: [],
        workspacePlanContext: null,
      },
    }),
  });

  assert.equal(view.hasPlan, true);
  assert.equal(view.planStatus, 'draft');
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
  assert.equal(view.participantCount, null);
  assert.equal(view.linkedTaskId, null);
  assert.equal(view.planStatus, null);
  assert.equal(view.artifactCount, null);
  assert.equal(view.sourceCount, null);
  assert.equal(view.verificationCount, null);
  assert.equal(view.toolActivityCount, null);
  assert.equal(view.failedToolActivityCount, null);
  assert.equal(view.environmentLabel, null);
  assert.equal(view.modelLabel, null);
  assert.equal(view.permissionLabel, null);
  assert.equal(view.elapsedLabel, null);
  assert.equal(view.usageLabel, null);
  assert.equal(view.runId, null);
  assert.deepEqual(view.runActions, []);
});

test('session view model keeps a blank title blank so the shell can localize the fallback', () => {
  const view = build({ conversation: conversation({ title: '   ' }) });

  assert.equal(view.title, '');
});

test('native user control outcomes do not rewrite the authoritative parent run status', () => {
  for (const status of ['running', 'completed', 'failed']) {
    for (const controlOutcome of ['user_paused', 'user_stopped']) {
      const view = build({
        projection: projection({ currentRun: { ...projection().currentRun, status } }),
        timeline: {
          conversationId: 'conversation-1', items: [{
            id: 'control', type: 'observe', toolName: 'computer_click',
            controlOutcome, isError: false, eventTimeUs: 1, eventCounter: 1,
          }], loading: false, error: null,
        },
      });
      assert.equal(view.status, status);
      assert.equal(view.observedFailedToolActivityCount, 0);
    }
  }
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

test('same-authority lifecycle updates settle sidebar and recent sessions without a revision bump', () => {
  const queuedRun = {
    ...projection().currentRun,
    status: 'queued',
    revision: 1,
    updated_at: '2026-10-15T10:49:26.963687Z',
  };
  const queued = conversation({ metadata: { run: queuedRun } });
  const runningRun = {
    ...queuedRun,
    status: 'running',
    updated_at: '2026-10-15T10:49:32.543628Z',
  };
  const running = conversationWithAuthoritativeRun(queued, runningRun);
  assert.equal(conversationTreeStatusValue(running), 'running');

  for (const status of ['failed', 'cancelled', 'completed']) {
    const terminalRun = {
      ...runningRun,
      status,
      updated_at: '2026-10-15T10:52:00.140641Z',
    };
    const settled = conversationWithAuthoritativeRun(running, terminalRun);
    const [refreshed] = mergeConversationListWithCurrentRunAuthority([queued], [settled]);
    assert.equal(refreshed.status, 'active');
    assert.equal(refreshed.metadata.run.revision, 1);
    assert.equal(conversationTreeStatusValue(refreshed), status);
    assert.equal(
      conversationTreeStatusPresentation(conversationTreeStatusValue(refreshed)).labelKey,
      `workspaceTree.${status}`,
    );
    const overview = buildWorkspaceOverviewModel({
      workspace: null,
      project: null,
      conversations: [refreshed],
      plan: null,
      sandboxStatus: null,
      members: { status: 'unavailable', items: [], error: null },
      agents: { status: 'unavailable', items: [], error: null },
    });
    assert.equal(overview.sessionCounts.running, 0);
    assert.equal(overview.recentSessions[0].status, status);
    for (const stale of [queuedRun, runningRun, terminalRun]) {
      assert.equal(conversationWithAuthoritativeRun(settled, stale), settled);
    }
    const events = [queuedRun, runningRun, terminalRun, runningRun].map((payload) => ({
      type: 'run_status',
      payload,
    }));
    assert.deepEqual(authoritativeRunsFromSocketEvents(events), [terminalRun]);
  }
});

test('equal-revision updates require a strictly later valid timestamp', () => {
  const run = projection().currentRun;
  const current = conversation({ metadata: { run } });
  for (const updated_at of [run.updated_at, '2026-07-13T00:00:00Z', 'invalid', undefined]) {
    assert.equal(
      conversationWithAuthoritativeRun(current, { ...run, status: 'failed', updated_at }),
      current,
    );
  }
  assert.equal(
    conversationWithAuthoritativeRun(current, {
      ...run,
      status: 'failed',
      revision: run.revision - 1,
      updated_at: '2026-07-14T00:00:00Z',
    }),
    current,
  );
});

test('settled session projection corrects workspace running count after asynchronous cancellation', () => {
  const initial = projection();
  const running = conversation({ metadata: { run: initial.currentRun } });
  const input = {
    workspace: null,
    project: null,
    conversations: [running],
    plan: null,
    sandboxStatus: null,
    members: { status: 'unavailable', items: [], error: null },
    agents: { status: 'unavailable', items: [], error: null },
  };
  assert.equal(buildWorkspaceOverviewModel(input).sessionCounts.running, 1);
  const settled = projection({
    currentRun: { ...initial.currentRun, status: 'cancelled', revision: 5 },
  });
  const run = authoritativeRunFromSessionProjection(settled, {
    conversationId: running.id,
    tenantId: running.tenant_id,
    projectId: running.project_id,
    workspaceId: null,
  });
  assert.ok(run);
  const updated = conversationWithAuthoritativeRun(running, run);
  const [refreshed] = mergeConversationListWithCurrentRunAuthority([running], [updated]);
  const overview = buildWorkspaceOverviewModel({ ...input, conversations: [refreshed] });
  assert.equal(overview.sessionCounts.running, 0);
  assert.equal(overview.recentSessions[0].status, 'cancelled');
  assert.equal(refreshed.status, 'active');
  assert.equal(conversationWithAuthoritativeRun(refreshed, initial.currentRun), refreshed);
});

test('session projection run rejects stale owners and cannot overwrite a newer run', () => {
  const snapshot = projection();
  const scope = {
    conversationId: 'conversation-1',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: null,
  };
  for (const key of ['conversationId', 'tenantId', 'projectId', 'workspaceId']) {
    assert.equal(
      authoritativeRunFromSessionProjection(snapshot, { ...scope, [key]: 'other' }),
      null,
    );
  }
  assert.equal(authoritativeRunFromSessionProjection(null, scope), null);
  assert.equal(
    authoritativeRunFromSessionProjection(projection({ currentRun: null }), scope),
    null,
  );
  for (const key of ['conversation_id', 'project_id']) {
    assert.equal(
      authoritativeRunFromSessionProjection(
        projection({
          currentRun: { ...snapshot.currentRun, [key]: 'other' },
        }),
        scope,
      ),
      null,
    );
  }
  const newer = conversation({
    metadata: {
      run: {
        ...snapshot.currentRun,
        id: 'run-2',
        revision: 1,
        created_at: '2026-07-14T00:00:00Z',
        updated_at: '2026-07-14T00:00:00Z',
      },
    },
  });
  const older = authoritativeRunFromSessionProjection(snapshot, scope);
  assert.equal(conversationWithAuthoritativeRun(newer, older), newer);
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

test('terminal session never claims reconnecting live updates', () => {
  for (const status of ['completed', 'failed', 'cancelled']) {
    assert.deepEqual(sessionLiveIndicator(status, true), {
      labelKey: 'session.liveUpdatesEnded',
      tone: 'ended',
    });
    assert.deepEqual(sessionLiveIndicator(status, false), {
      labelKey: 'session.liveUpdatesEnded',
      tone: 'ended',
    });
  }
  assert.deepEqual(sessionLiveIndicator('running', true), {
    labelKey: 'session.liveConnected',
    tone: 'live',
  });
  assert.deepEqual(sessionLiveIndicator('running', false), {
    labelKey: 'session.liveReconnecting',
    tone: 'reconnecting',
  });
  assert.deepEqual(sessionLiveIndicator('ready_review', false), {
    labelKey: 'session.liveReconnecting',
    tone: 'reconnecting',
  });
  assert.equal(sessionRunStatusIsTerminal('completed'), true);
  assert.equal(sessionRunStatusIsTerminal('running'), false);
  assert.equal(sessionRunStatusIsTerminal(null), false);
});

test('terminal run leaves no respondable HITL requests', () => {
  const pendingHitl = [{ id: 'hitl-1' }, { id: 'hitl-2' }];
  const respondableCapabilities = {
    ...projection().capabilities,
    canRespondToHitl: true,
    allowedActions: ['respond_to_hitl'],
  };
  const base = projection({ pendingHitl, capabilities: respondableCapabilities });

  assert.deepEqual(
    respondableHitlRequestsForProjection(base).map((request) => request.id),
    ['hitl-1', 'hitl-2']
  );

  for (const status of ['completed', 'failed', 'cancelled']) {
    const terminal = projection({
      pendingHitl,
      capabilities: respondableCapabilities,
      currentRun: { ...base.currentRun, status },
    });
    assert.deepEqual(respondableHitlRequestsForProjection(terminal), [], status);
  }

  assert.deepEqual(respondableHitlRequestsForProjection(null), []);
  assert.deepEqual(respondableHitlRequestsForProjection(projection({ pendingHitl })), []);
});


test('session view model maps the server-derived execution stage through', () => {
  for (const stage of ['understand', 'implement', 'verify', 'review']) {
    const view = build({ projection: projection({ executionStage: stage }) });
    assert.equal(view.stage, stage);
  }
});

test('session view model falls back to unavailable without a derived stage', () => {
  assert.equal(build({ projection: projection() }).stage, 'unavailable');
  assert.equal(
    build({ projection: projection({ executionStage: null }) }).stage,
    'unavailable',
  );
  assert.equal(build().stage, 'unavailable');
});

test('terminal failed run without artifacts never renders a stage stepper', () => {
  const failedWithoutArtifacts = projection({
    currentRun: { ...projection().currentRun, status: 'failed' },
    executionStage: null,
  });

  const view = build({ projection: failedWithoutArtifacts });

  assert.equal(view.status, 'failed');
  assert.equal(view.stage, 'unavailable');
});
