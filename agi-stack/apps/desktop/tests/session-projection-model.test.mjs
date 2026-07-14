import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { decodeConversationSessionProjection, socketEventInvalidatesSessionProjection } = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/sessionProjectionModel.js'
);

function canonicalizeJson(value) {
  if (Array.isArray(value)) return value.map(canonicalizeJson);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value)
        .sort((left, right) => Buffer.compare(Buffer.from(left), Buffer.from(right)))
        .map((key) => [key, canonicalizeJson(value[key])])
    );
  }
  return value;
}

function stampProjection(projection) {
  const { snapshot_revision: _snapshotRevision, ...unsignedProjection } = projection;
  projection.snapshot_revision = createHash('sha256')
    .update(JSON.stringify(canonicalizeJson(unsignedProjection)))
    .digest('hex');
  return projection;
}

function decodeSignedProjection(projection, scope = 'conversation-1') {
  return decodeConversationSessionProjection(stampProjection(projection), scope);
}

function validProjection() {
  const task = {
    id: 'task-1',
    conversation_id: 'conversation-1',
    content: 'Implement the reviewed change',
    status: 'in_progress',
    priority: 'high',
    order_index: 0,
    created_at: '2026-07-14T00:00:00Z',
    updated_at: '2026-07-14T00:01:00Z',
  };
  const plan = {
    id: 'plan-1',
    conversation_id: 'conversation-1',
    version: 1,
    status: 'approved',
    tasks: [task],
    created_at: '2026-07-14T00:00:00Z',
    approved_at: '2026-07-14T00:00:30Z',
  };
  const run = {
    id: 'run-1',
    conversation_id: 'conversation-1',
    project_id: 'project-1',
    plan_version_id: 'plan-1',
    idempotency_key: 'approval-1',
    message_id: 'message-1',
    request_message: 'Execute the reviewed plan',
    status: 'running',
    revision: 3,
    created_at: '2026-07-14T00:00:30Z',
    updated_at: '2026-07-14T00:01:00Z',
    started_at: '2026-07-14T00:00:31Z',
    completed_at: null,
    last_heartbeat_at: '2026-07-14T00:01:00Z',
    error: null,
    environment: {
      id: 'environment-1',
      kind: 'worktree',
      label: 'Worktree · codex/session-projection',
      workspace_path: '/tmp/session-projection',
      repository_root: '/repo',
      branch: 'codex/session-projection',
      base_commit: 'abc123',
      source_run_id: null,
      created_at: '2026-07-14T00:00:30Z',
    },
    permission_profile: 'workspace_write',
    authorization_snapshot: {},
  };
  return stampProjection({
    schema_version: 1,
    conversation: {
      id: 'conversation-1',
      project_id: 'project-1',
      tenant_id: 'tenant-1',
      user_id: 'user-1',
      title: 'Implement session authority projection',
      status: 'running',
      message_count: 2,
      created_at: '2026-07-14T00:00:00Z',
      updated_at: '2026-07-14T00:01:00Z',
      summary: null,
      agent_config: { capability_mode: 'code', model: 'gpt-5.5' },
      metadata: { run: { status: 'failed', revision: 99 } },
      conversation_mode: 'workspace',
      current_mode: 'build',
      workspace_id: 'workspace-1',
      linked_workspace_task_id: 'workspace-task-1',
      workspace_name: 'Desktop Client',
      participant_agents: ['agent-1'],
      coordinator_agent_id: 'agent-1',
      focused_agent_id: 'agent-1',
    },
    current_run: run,
    run_history: [run],
    current_plan: plan,
    plan_history: [plan],
    tasks: [task],
    pending_hitl: [],
    artifact_versions: [],
    artifact_deliveries: [],
    tool_invocations: [],
    evidence_summary: {
      artifact_version_count: 0,
      artifact_delivery_count: 0,
      artifact_source_count: 0,
      tool_invocation_count: 0,
      unknown_outcome_count: 0,
      checks: null,
      changes: null,
    },
    capabilities: {
      can_send_message: false,
      can_approve_plan: false,
      can_respond_to_hitl: false,
      can_steer_now: true,
      can_queue_next: true,
      can_review_artifacts: false,
      can_deliver_artifacts: false,
      run_actions: ['pause', 'cancel'],
      allowed_actions: ['steer_now', 'queue_next', 'pause', 'cancel'],
    },
    snapshot_revision: '',
    updated_at: '2026-07-14T00:01:00Z',
  });
}

function validDecisionContext() {
  return {
    action: { name: 'write_file', label: 'Write reviewed file' },
    target: { kind: 'file', id: 'README.md', path: 'README.md' },
    data: { summary: 'Apply the reviewed README change' },
    reason: 'The approved plan requires this file update.',
    risk: { level: 'medium', rationale: 'This mutates the local worktree.' },
    reversibility: { mode: 'reversible', recovery: 'Revert the worktree change.' },
    scope: { kind: 'files', ids: ['README.md'] },
    evidence: [
      {
        kind: 'plan',
        id: 'plan-1',
        label: 'Reviewed plan',
        uri: 'plan://plan-1',
        digest: 'b'.repeat(64),
      },
    ],
  };
}

function pendingHitlRequest(overrides = {}) {
  return {
    id: 'hitl-1',
    conversation_id: 'conversation-1',
    run_id: 'run-1',
    round: 1,
    kind: 'permission',
    prompt: 'Approve the reviewed mutation',
    decision: validDecisionContext(),
    status: 'pending',
    created_at: '2026-07-14T00:00:40Z',
    responded_at: null,
    ...overrides,
  };
}

function withPendingHitl(projection, request) {
  projection.pending_hitl = [request];
  projection.capabilities.can_respond_to_hitl = true;
  projection.capabilities.allowed_actions = [
    'respond_to_hitl',
    ...projection.capabilities.allowed_actions,
  ];
  return projection;
}

function toolInvocation(overrides = {}) {
  return {
    invocation_id: 'invocation-1',
    run_id: 'run-1',
    plan_version_id: 'plan-1',
    run_revision: 3,
    environment_id: 'environment-1',
    tool_name: 'read_file',
    target: { path: 'README.md' },
    effect: 'read',
    input_digest: 'c'.repeat(64),
    redacted_input: { path: 'README.md' },
    status: 'completed',
    prepared_at_ms: 1,
    ...overrides,
  };
}

function withToolInvocation(projection, invocation) {
  projection.tool_invocations = [invocation];
  projection.evidence_summary.tool_invocation_count = 1;
  projection.evidence_summary.unknown_outcome_count =
    invocation.status === 'unknown_outcome' ? 1 : 0;
  return projection;
}

test('session projection decoder accepts one scoped schema-v1 authority snapshot', () => {
  const projection = decodeSignedProjection(validProjection());

  assert.equal(projection?.conversation.id, 'conversation-1');
  assert.equal(projection?.currentRun?.status, 'running');
  assert.equal(projection?.currentPlan?.id, 'plan-1');
  assert.equal(projection?.tasks[0]?.id, 'task-1');
  assert.deepEqual(projection?.capabilities.runActions, ['pause', 'cancel']);
  assert.deepEqual(projection?.capabilities.allowedActions, [
    'steer_now',
    'queue_next',
    'pause',
    'cancel',
  ]);
  assert.match(projection?.snapshotRevision ?? '', /^[a-f0-9]{64}$/);
});

test('session projection decoder rejects a stale canonical snapshot revision', () => {
  const staleProjection = validProjection();
  staleProjection.updated_at = '2026-07-14T00:02:00Z';

  assert.equal(
    decodeConversationSessionProjection(staleProjection, 'conversation-1'),
    null,
  );
});

test('session projection decoder fails closed on cross-conversation or inconsistent authority', () => {
  const crossConversation = validProjection();
  crossConversation.tasks[0].conversation_id = 'conversation-2';
  assert.equal(
    decodeSignedProjection(crossConversation),
    null,
  );

  const inconsistentCapabilities = validProjection();
  inconsistentCapabilities.capabilities.can_send_message = true;
  assert.equal(
    decodeSignedProjection(inconsistentCapabilities),
    null,
  );

  const unsupportedSchema = validProjection();
  unsupportedSchema.schema_version = 2;
  assert.equal(
    decodeSignedProjection(unsupportedSchema),
    null,
  );
});

test('session projection decoder accepts minimally structured tasks and rejects scope drift', () => {
  const minimalTaskProjection = validProjection();
  minimalTaskProjection.current_plan.tasks = [{ id: 'task-minimal' }];
  minimalTaskProjection.tasks = [{ id: 'task-minimal' }];
  assert.equal(
    decodeSignedProjection(minimalTaskProjection, {
      conversationId: 'conversation-1',
      projectId: 'project-1',
      tenantId: 'tenant-1',
      workspaceId: 'workspace-1',
    })?.tasks[0]?.id,
    'task-minimal',
  );

  const wrongProject = validProjection();
  assert.equal(
    decodeSignedProjection(wrongProject, {
      conversationId: 'conversation-1',
      projectId: 'project-2',
    }),
    null,
  );

  const malformedHistory = validProjection();
  malformedHistory.run_history.push({ id: 'invalid-run' });
  assert.equal(
    decodeSignedProjection(malformedHistory),
    null,
  );
});

test('session projection decoder rejects incomplete or internally divergent authority', () => {
  const missingRequiredNullableField = validProjection();
  delete missingRequiredNullableField.current_run.started_at;
  assert.equal(
    decodeSignedProjection(missingRequiredNullableField),
    null,
  );

  const divergentCurrentRun = validProjection();
  divergentCurrentRun.current_run = {
    ...divergentCurrentRun.current_run,
    status: 'paused',
  };
  divergentCurrentRun.capabilities.can_steer_now = false;
  divergentCurrentRun.capabilities.can_queue_next = false;
  divergentCurrentRun.capabilities.run_actions = ['resume', 'cancel'];
  divergentCurrentRun.capabilities.allowed_actions = ['resume', 'cancel'];
  assert.equal(
    decodeSignedProjection(divergentCurrentRun),
    null,
  );

  const divergentTask = validProjection();
  divergentTask.tasks = [{ ...divergentTask.tasks[0], content: 'Different task content' }];
  assert.equal(
    decodeSignedProjection(divergentTask),
    null,
  );
});

test('session projection decoder rejects non-pending HITL and extra allowed run actions', () => {
  const respondedHitl = validProjection();
  respondedHitl.pending_hitl = [
    {
      id: 'hitl-1',
      conversation_id: 'conversation-1',
      run_id: 'run-1',
      round: 1,
      kind: 'clarification',
      prompt: 'Choose a direction',
      status: 'responded',
      created_at: '2026-07-14T00:00:40Z',
      responded_at: '2026-07-14T00:00:50Z',
    },
  ];
  respondedHitl.capabilities.can_respond_to_hitl = true;
  respondedHitl.capabilities.allowed_actions = [
    'respond_to_hitl',
    ...respondedHitl.capabilities.allowed_actions,
  ];
  assert.equal(
    decodeSignedProjection(respondedHitl),
    null,
  );

  const extraRunAction = validProjection();
  extraRunAction.capabilities.allowed_actions.push('resume');
  assert.equal(
    decodeSignedProjection(extraRunAction),
    null,
  );
});

test('session projection decoder structurally validates pending HITL authority', () => {
  const validPending = withPendingHitl(validProjection(), pendingHitlRequest());
  assert.equal(decodeSignedProjection(validPending)?.pendingHitl[0]?.id, 'hitl-1');

  const malformedDecision = withPendingHitl(
    validProjection(),
    pendingHitlRequest({ decision: {} }),
  );
  assert.equal(decodeSignedProjection(malformedDecision), null);

  const alreadyResponded = withPendingHitl(
    validProjection(),
    pendingHitlRequest({ responded_at: '2026-07-14T00:00:50Z' }),
  );
  assert.equal(decodeSignedProjection(alreadyResponded), null);

  const leakedResponseState = withPendingHitl(
    validProjection(),
    pendingHitlRequest({ response_data: { granted: true } }),
  );
  assert.equal(decodeSignedProjection(leakedResponseState), null);
});

test('session projection decoder enforces invocation binding and evidence summary integrity', () => {
  const invalidInvocation = validProjection();
  invalidInvocation.tool_invocations = [
    {
      invocation_id: 'invocation-1',
      run_id: 'run-1',
      plan_version_id: 'plan-1',
      run_revision: 4,
      environment_id: 'environment-1',
      tool_name: 'read_file',
      target: { path: 'README.md' },
      effect: 'read',
      input_digest: 'c'.repeat(64),
      redacted_input: { path: 'README.md' },
      status: 'completed',
      prepared_at_ms: 1,
    },
  ];
  invalidInvocation.evidence_summary.tool_invocation_count = 1;
  assert.equal(
    decodeSignedProjection(invalidInvocation),
    null,
  );

  const invalidChecks = validProjection();
  invalidChecks.artifact_versions = [approvedArtifact()];
  invalidChecks.evidence_summary.artifact_version_count = 1;
  invalidChecks.evidence_summary.checks = {
    total: 4,
    artifact_versions_without_checks: 0,
  };
  invalidChecks.capabilities.can_review_artifacts = true;
  invalidChecks.capabilities.can_deliver_artifacts = true;
  invalidChecks.capabilities.allowed_actions = [
    'steer_now',
    'queue_next',
    'review_artifact',
    'deliver_artifact',
    'pause',
    'cancel',
  ];
  assert.equal(
    decodeSignedProjection(invalidChecks),
    null,
  );
});

test('session projection decoder enforces tool digest and mutation-grant authority', () => {
  const malformedInputDigest = withToolInvocation(
    validProjection(),
    toolInvocation({ input_digest: 'not-a-canonical-digest' }),
  );
  assert.equal(decodeSignedProjection(malformedInputDigest), null);

  const mutationWithoutGrant = withToolInvocation(
    validProjection(),
    toolInvocation({ effect: 'mutate', tool_name: 'write_file' }),
  );
  assert.equal(decodeSignedProjection(mutationWithoutGrant), null);

  const authorizedMutation = withToolInvocation(
    validProjection(),
    toolInvocation({
      effect: 'mutate',
      tool_name: 'write_file',
      grant_id: 'grant-1',
    }),
  );
  assert.equal(decodeSignedProjection(authorizedMutation)?.toolInvocations[0]?.grant_id, 'grant-1');
});

test('session projection decoder accepts arbitrary JSON delivery receipts and rejects bad digests', () => {
  const arbitraryReceipt = validProjection();
  const artifact = approvedArtifact();
  arbitraryReceipt.artifact_versions = [artifact];
  arbitraryReceipt.artifact_deliveries = [
    {
      id: 'delivery-1',
      artifact_version_id: artifact.id,
      artifact_id: artifact.artifact_id,
      conversation_id: 'conversation-1',
      run_id: 'run-1',
      destination: 'local_workspace',
      receipt: null,
      idempotency_key: 'delivery-key-1',
      created_at: '2026-07-14T00:01:00Z',
    },
  ];
  arbitraryReceipt.evidence_summary = {
    artifact_version_count: 1,
    artifact_delivery_count: 1,
    artifact_source_count: 1,
    tool_invocation_count: 0,
    unknown_outcome_count: 0,
    checks: { total: 1, artifact_versions_without_checks: 0 },
    changes: null,
  };
  arbitraryReceipt.capabilities.can_review_artifacts = true;
  arbitraryReceipt.capabilities.can_deliver_artifacts = true;
  arbitraryReceipt.capabilities.allowed_actions = [
    'steer_now',
    'queue_next',
    'review_artifact',
    'deliver_artifact',
    'pause',
    'cancel',
  ];
  assert.equal(
    decodeSignedProjection(arbitraryReceipt)?.artifactDeliveries[0]?.receipt,
    null,
  );

  const invalidDigest = validProjection();
  invalidDigest.snapshot_revision = 'sha256:projection-1';
  assert.equal(
    decodeConversationSessionProjection(invalidDigest, 'conversation-1'),
    null,
  );
});

function approvedArtifact() {
  return {
    id: 'artifact-version-1',
    artifact_id: 'artifact-1',
    source_artifact_id: 'source-artifact-1',
    conversation_id: 'conversation-1',
    run_id: 'run-1',
    version: 1,
    status: 'approved',
    revision: 2,
    filename: 'report.md',
    mime_type: 'text/markdown',
    path: '/tmp/report.md',
    relative_path: 'report.md',
    bytes: 128,
    sources: [{ id: 'source-1' }],
    checks: [{ id: 'check-1', status: 'passed' }],
    created_at: '2026-07-14T00:00:45Z',
    updated_at: '2026-07-14T00:00:50Z',
    approved_at: '2026-07-14T00:00:50Z',
    delivered_at: null,
    superseded_at: null,
    feedback: null,
  };
}

test('session authority invalidation reads nested envelopes and ignores narrative streaming', () => {
  assert.equal(
    socketEventInvalidatesSessionProjection({
      type: 'event',
      payload: { data: { event_type: 'run_status', conversation_id: 'conversation-1' } },
    }),
    true,
  );
  assert.equal(
    socketEventInvalidatesSessionProjection({
      event_type: 'text_delta',
      conversation_id: 'conversation-1',
    }),
    false,
  );
});
