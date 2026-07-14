import type {
  AgentConversation,
  DesktopApprovalRequest,
  DesktopArtifactDelivery,
  DesktopArtifactVersion,
  DesktopRun,
  DesktopRunStatus,
  DesktopToolInvocation,
} from '../../types';
import type {
  ConversationSessionProjection,
  SessionAllowedAction,
  SessionProjectionCapabilities,
  SessionProjectionEvidenceSummary,
  SessionProjectionPlan,
  SessionProjectionScope,
  SessionProjectionTask,
  SessionRunAction,
} from './sessionProjectionTypes';
import { canonicalJsonSha256 } from './canonicalJsonDigest';
import { decodeDecisionContext } from './sessionDecisionContextDecoder';

const runStatuses = new Set<DesktopRunStatus>([
  'queued',
  'running',
  'needs_input',
  'needs_approval',
  'paused',
  'ready_review',
  'completed',
  'failed',
  'disconnected',
  'interrupted',
  'cancelled',
]);
const planStatuses = new Set(['draft', 'approved']);
const artifactStatuses = new Set(['draft', 'ready', 'approved', 'delivered', 'superseded']);
const hitlKinds = new Set(['clarification', 'decision', 'env_var', 'permission']);
const invocationStatuses = new Set([
  'prepared',
  'executing',
  'completed',
  'failed',
  'unknown_outcome',
]);
const runActionValues = new Set<SessionRunAction>([
  'pause',
  'resume',
  'cancel',
  'reconnect',
  'fork',
  'request_changes',
  'approve',
]);
const allowedActionValues = new Set<SessionAllowedAction>([
  'send_message',
  'approve_plan_and_start',
  'respond_to_hitl',
  'steer_now',
  'queue_next',
  'review_artifact',
  'deliver_artifact',
  ...runActionValues,
]);
const sha256DigestPattern = /^[a-f0-9]{64}$/;
const sessionAuthorityEventTypes = new Set([
  'act',
  'observe',
  'run_status',
  'run_input_queued',
  'run_input_promoted',
  'recovery_forked',
  'review_decision',
  'worktree_created',
  'environment_selected',
  'clarification_asked',
  'decision_asked',
  'env_var_requested',
  'permission_asked',
  'hitl_responded',
  'artifact_created',
  'artifact_ready',
  'artifact_error',
  'artifacts_batch',
  'artifact_approved',
  'artifact_changes_requested',
  'artifact_delivered',
  'task_list_updated',
  'task_updated',
  'task_execution_session_updated',
]);

export function decodeConversationSessionProjection(
  payload: unknown,
  expectedScope: string | SessionProjectionScope,
): ConversationSessionProjection | null {
  const scope =
    typeof expectedScope === 'string'
      ? { conversationId: expectedScope }
      : expectedScope;
  const root = recordValue(payload);
  if (!root || root.schema_version !== 1) return null;
  const snapshotRevision =
    typeof root.snapshot_revision === 'string' ? root.snapshot_revision : null;
  if (!snapshotRevision || !sha256DigestPattern.test(snapshotRevision)) return null;
  const { snapshot_revision: _snapshotRevision, ...unsignedPayload } = root;
  if (canonicalJsonSha256(unsignedPayload) !== snapshotRevision) return null;

  const conversation = readConversation(root.conversation, scope);
  const runHistory = readArray(root.run_history, (value) => readRun(value, scope));
  const planHistory = readArray(root.plan_history, (value) => readPlan(value, scope));
  const tasks = readArray(root.tasks, (value) => readTask(value, scope));
  if (!conversation || !runHistory || !planHistory || !tasks) return null;

  const currentRun = readNullable(root.current_run, (value) => readRun(value, scope));
  const currentPlan = readNullable(root.current_plan, (value) => readPlan(value, scope));
  if (currentRun === undefined || currentPlan === undefined) return null;
  if ((currentRun === null) !== (runHistory.length === 0)) return null;
  if ((currentPlan === null) !== (planHistory.length === 0)) return null;
  if (currentRun && !sameJson(currentRun, runHistory[0])) return null;
  if (currentPlan && !sameJson(currentPlan, planHistory[0])) return null;
  if (!sameJson(tasks, currentPlan?.tasks ?? [])) return null;
  if (!hasUniqueIds(runHistory) || !hasUniqueIds(planHistory) || !hasUniqueIds(tasks)) return null;

  const runsById = new Map(runHistory.map((run) => [run.id, run]));
  const plansById = new Map(planHistory.map((plan) => [plan.id, plan]));
  if (runHistory.some((run) => !plansById.has(run.plan_version_id))) return null;

  const pendingHitl = readArray(root.pending_hitl, (value) =>
    readHitl(value, scope, runHistory),
  );
  const artifactVersions = readArray(root.artifact_versions, (value) =>
    readArtifactVersion(value, scope, runsById),
  );
  const artifactDeliveries = readArray(root.artifact_deliveries, (value) =>
    readArtifactDelivery(value, scope, runsById),
  );
  const toolInvocations = readArray(root.tool_invocations, (value) =>
    readToolInvocation(value, runsById, plansById),
  );
  if (!pendingHitl || !artifactVersions || !artifactDeliveries || !toolInvocations) return null;
  if (
    !hasUniqueIds(pendingHitl) ||
    !hasUniqueIds(artifactVersions) ||
    !hasUniqueIds(artifactDeliveries)
  ) {
    return null;
  }
  if (
    new Set(toolInvocations.map((invocation) => invocation.invocation_id)).size !==
    toolInvocations.length
  ) {
    return null;
  }
  const artifactVersionsById = new Map(
    artifactVersions.map((artifact) => [artifact.id, artifact]),
  );
  if (
    artifactDeliveries.some((delivery) => {
      const artifact = artifactVersionsById.get(delivery.artifact_version_id);
      return !artifact || artifact.artifact_id !== delivery.artifact_id;
    })
  ) {
    return null;
  }

  const evidenceSummary = readEvidenceSummary(root.evidence_summary);
  const capabilities = readCapabilities(root.capabilities);
  const updatedAt = nonEmptyString(root.updated_at);
  if (
    !evidenceSummary ||
    !capabilities ||
    !updatedAt
  ) {
    return null;
  }
  if (
    !capabilitiesAreConsistent(
      capabilities,
      conversation,
      currentRun,
      currentPlan,
      pendingHitl,
      artifactVersions,
    )
  ) {
    return null;
  }
  if (
    evidenceSummary.artifactVersionCount !== artifactVersions.length ||
    evidenceSummary.artifactDeliveryCount !== artifactDeliveries.length ||
    evidenceSummary.artifactSourceCount !==
      artifactVersions.reduce((total, artifact) => total + artifact.sources.length, 0) ||
    evidenceSummary.toolInvocationCount !== toolInvocations.length ||
    evidenceSummary.unknownOutcomeCount !==
      toolInvocations.filter((invocation) => invocation.status === 'unknown_outcome').length ||
    !evidenceChecksAreConsistent(evidenceSummary, artifactVersions)
  ) {
    return null;
  }

  return {
    schemaVersion: 1,
    conversation,
    currentRun,
    runHistory,
    currentPlan,
    planHistory,
    tasks,
    pendingHitl,
    artifactVersions,
    artifactDeliveries,
    toolInvocations,
    evidenceSummary,
    capabilities,
    snapshotRevision,
    updatedAt,
  };
}

export function socketEventInvalidatesSessionProjection(event: unknown): boolean {
  const root = recordValue(event);
  if (!root) return false;
  const queue = [root];
  const seen = new Set<Record<string, unknown>>();
  while (queue.length) {
    const current = queue.shift();
    if (!current || seen.has(current)) continue;
    seen.add(current);
    const eventType = nonEmptyString(current.event_type) ?? nonEmptyString(current.type);
    if (eventType && sessionAuthorityEventTypes.has(eventType)) return true;
    for (const key of ['payload', 'data']) {
      const nested = recordValue(current[key]);
      if (nested) queue.push(nested);
    }
  }
  return false;
}

function readConversation(
  value: unknown,
  scope: SessionProjectionScope,
): AgentConversation | null {
  const conversation = recordValue(value);
  const agentConfig = conversation ? recordValue(conversation.agent_config) : null;
  const metadata = conversation ? recordValue(conversation.metadata) : null;
  if (
    !conversation ||
    nonEmptyString(conversation.id) !== scope.conversationId ||
    !nonEmptyString(conversation.project_id) ||
    !nonEmptyString(conversation.tenant_id) ||
    !nonEmptyString(conversation.user_id) ||
    typeof conversation.title !== 'string' ||
    typeof conversation.status !== 'string' ||
    !nonNegativeInteger(conversation.message_count) ||
    !nonEmptyString(conversation.created_at) ||
    !nonEmptyString(conversation.updated_at) ||
    !Object.hasOwn(conversation, 'summary') ||
    !optionalString(conversation.summary) ||
    !agentConfig ||
    !['work', 'code', 'unavailable'].includes(String(agentConfig.capability_mode)) ||
    !metadata ||
    !nonEmptyString(conversation.conversation_mode) ||
    !['plan', 'build'].includes(String(conversation.current_mode))
  ) {
    return null;
  }
  if (
    !Object.hasOwn(conversation, 'workspace_id') ||
    !Object.hasOwn(conversation, 'linked_workspace_task_id') ||
    !optionalString(conversation.workspace_id) ||
    !optionalString(conversation.linked_workspace_task_id) ||
    typeof conversation.workspace_name !== 'string' ||
    !Array.isArray(conversation.participant_agents) ||
    !conversation.participant_agents.every((participant) => nonEmptyString(participant)) ||
    !Object.hasOwn(conversation, 'coordinator_agent_id') ||
    !Object.hasOwn(conversation, 'focused_agent_id') ||
    !optionalString(conversation.coordinator_agent_id) ||
    !optionalString(conversation.focused_agent_id)
  ) {
    return null;
  }
  if (scope.projectId && conversation.project_id !== scope.projectId) return null;
  if (scope.tenantId && conversation.tenant_id !== scope.tenantId) return null;
  if (
    Object.hasOwn(scope, 'workspaceId') &&
    (conversation.workspace_id ?? null) !== scope.workspaceId
  ) {
    return null;
  }
  return conversation as AgentConversation;
}

function readRun(value: unknown, scope: SessionProjectionScope): DesktopRun | null {
  const run = recordValue(value);
  const status = run ? nonEmptyString(run.status) : null;
  if (
    !run ||
    !nonEmptyString(run.id) ||
    run.conversation_id !== scope.conversationId ||
    !nonEmptyString(run.project_id) ||
    !nonEmptyString(run.plan_version_id) ||
    !nonEmptyString(run.idempotency_key) ||
    !nonEmptyString(run.message_id) ||
    typeof run.request_message !== 'string' ||
    !status ||
    !runStatuses.has(status as DesktopRunStatus) ||
    !nonNegativeInteger(run.revision) ||
    !nonEmptyString(run.created_at) ||
    !nonEmptyString(run.updated_at) ||
    !Object.hasOwn(run, 'started_at') ||
    !Object.hasOwn(run, 'completed_at') ||
    !Object.hasOwn(run, 'last_heartbeat_at') ||
    !Object.hasOwn(run, 'error') ||
    !optionalString(run.started_at) ||
    !optionalString(run.completed_at) ||
    !optionalString(run.last_heartbeat_at) ||
    !optionalString(run.error) ||
    !Object.hasOwn(run, 'authorization_snapshot') ||
    run.authorization_snapshot === undefined
  ) {
    return null;
  }
  if (scope.projectId && run.project_id !== scope.projectId) return null;
  if (run.environment !== undefined && run.environment !== null) {
    const environment = recordValue(run.environment);
    if (
      !environment ||
      !nonEmptyString(environment.id) ||
      !['local', 'worktree'].includes(String(environment.kind)) ||
      !nonEmptyString(environment.label) ||
      typeof environment.workspace_path !== 'string' ||
      !Object.hasOwn(environment, 'repository_root') ||
      !Object.hasOwn(environment, 'branch') ||
      !Object.hasOwn(environment, 'source_run_id') ||
      !optionalString(environment.repository_root) ||
      !optionalString(environment.branch) ||
      !optionalString(environment.base_commit) ||
      !optionalString(environment.source_run_id) ||
      !nonEmptyString(environment.created_at)
    ) {
      return null;
    }
  }
  if (
    run.permission_profile !== 'read_only' &&
    run.permission_profile !== 'workspace_write' &&
    run.permission_profile !== 'full_access'
  ) {
    return null;
  }
  return run as DesktopRun;
}

function readPlan(value: unknown, scope: SessionProjectionScope): SessionProjectionPlan | null {
  const plan = recordValue(value);
  const status = plan ? nonEmptyString(plan.status) : null;
  const tasks = plan ? readArray(plan.tasks, (task) => readTask(task, scope)) : null;
  if (
    !plan ||
    !nonEmptyString(plan.id) ||
    plan.conversation_id !== scope.conversationId ||
    !nonNegativeInteger(plan.version) ||
    !status ||
    !planStatuses.has(status) ||
    !tasks ||
    !nonEmptyString(plan.created_at) ||
    !Object.hasOwn(plan, 'approved_at') ||
    !optionalString(plan.approved_at)
  ) {
    return null;
  }
  return { ...(plan as SessionProjectionPlan), tasks };
}

function readTask(value: unknown, scope: SessionProjectionScope): SessionProjectionTask | null {
  const task = recordValue(value);
  if (!task || !nonEmptyString(task.id)) return null;
  if (
    task.conversation_id !== undefined &&
    task.conversation_id !== scope.conversationId
  ) {
    return null;
  }
  return task as SessionProjectionTask;
}

function readHitl(
  value: unknown,
  scope: SessionProjectionScope,
  runs: DesktopRun[],
): DesktopApprovalRequest | null {
  const request = recordValue(value);
  const kind = request ? nonEmptyString(request.kind) : null;
  const status = request ? nonEmptyString(request.status) : null;
  if (
    !request ||
    !nonEmptyString(request.id) ||
    request.conversation_id !== scope.conversationId ||
    !nonNegativeInteger(request.round) ||
    !kind ||
    !hitlKinds.has(kind) ||
    typeof request.prompt !== 'string' ||
    status !== 'pending' ||
    !nonEmptyString(request.created_at) ||
    !Object.hasOwn(request, 'run_id') ||
    !Object.hasOwn(request, 'responded_at') ||
    request.responded_at !== null ||
    ['response_data', 'response_actor', 'response_revision', 'idempotency_key'].some((key) =>
      Object.hasOwn(request, key),
    )
  ) {
    return null;
  }
  const runId = request.run_id === null ? null : nonEmptyString(request.run_id);
  if (request.run_id !== undefined && request.run_id !== null && !runId) return null;
  const runRevision = runId ? runs.find((run) => run.id === runId)?.revision : undefined;
  if (runId && runRevision === undefined) return null;
  let decision: DesktopApprovalRequest['decision'];
  if (Object.hasOwn(request, 'decision')) {
    decision = request.decision === null ? null : decodeDecisionContext(request.decision);
    if (decision === null && request.decision !== null) return null;
  }
  return {
    ...(request as DesktopApprovalRequest),
    ...(decision === undefined ? {} : { decision }),
    ...(runRevision === undefined ? {} : { run_revision: runRevision }),
  };
}

function readArtifactVersion(
  value: unknown,
  scope: SessionProjectionScope,
  runsById: Map<string, DesktopRun>,
): DesktopArtifactVersion | null {
  const artifact = recordValue(value);
  const status = artifact ? nonEmptyString(artifact.status) : null;
  if (
    !artifact ||
    !nonEmptyString(artifact.id) ||
    !nonEmptyString(artifact.artifact_id) ||
    !nonEmptyString(artifact.source_artifact_id) ||
    artifact.conversation_id !== scope.conversationId ||
    !nonNegativeInteger(artifact.version) ||
    !status ||
    !artifactStatuses.has(status) ||
    !nonNegativeInteger(artifact.revision) ||
    !nonEmptyString(artifact.filename) ||
    !nonEmptyString(artifact.mime_type) ||
    typeof artifact.path !== 'string' ||
    typeof artifact.relative_path !== 'string' ||
    !nonNegativeInteger(artifact.bytes) ||
    !Array.isArray(artifact.sources) ||
    !Array.isArray(artifact.checks) ||
    !nonEmptyString(artifact.created_at) ||
    !nonEmptyString(artifact.updated_at) ||
    !Object.hasOwn(artifact, 'run_id') ||
    !Object.hasOwn(artifact, 'approved_at') ||
    !Object.hasOwn(artifact, 'delivered_at') ||
    !Object.hasOwn(artifact, 'superseded_at') ||
    !Object.hasOwn(artifact, 'feedback') ||
    !optionalString(artifact.approved_at) ||
    !optionalString(artifact.delivered_at) ||
    !optionalString(artifact.superseded_at) ||
    !optionalString(artifact.feedback)
  ) {
    return null;
  }
  if (!optionalScopedRunId(artifact.run_id, runsById)) return null;
  return artifact as DesktopArtifactVersion;
}

function readArtifactDelivery(
  value: unknown,
  scope: SessionProjectionScope,
  runsById: Map<string, DesktopRun>,
): DesktopArtifactDelivery | null {
  const delivery = recordValue(value);
  if (
    !delivery ||
    !nonEmptyString(delivery.id) ||
    !nonEmptyString(delivery.artifact_version_id) ||
    !nonEmptyString(delivery.artifact_id) ||
    delivery.conversation_id !== scope.conversationId ||
    !nonEmptyString(delivery.destination) ||
    !Object.hasOwn(delivery, 'receipt') ||
    delivery.receipt === undefined ||
    !nonEmptyString(delivery.idempotency_key) ||
    !nonEmptyString(delivery.created_at) ||
    !Object.hasOwn(delivery, 'run_id') ||
    !optionalScopedRunId(delivery.run_id, runsById)
  ) {
    return null;
  }
  return delivery as DesktopArtifactDelivery;
}

function readToolInvocation(
  value: unknown,
  runsById: Map<string, DesktopRun>,
  plansById: Map<string, SessionProjectionPlan>,
): DesktopToolInvocation | null {
  const invocation = recordValue(value);
  const status = invocation ? nonEmptyString(invocation.status) : null;
  const run = invocation ? runsById.get(String(invocation.run_id)) : undefined;
  const plan = invocation ? plansById.get(String(invocation.plan_version_id)) : undefined;
  if (
    !invocation ||
    !nonEmptyString(invocation.invocation_id) ||
    !run ||
    !plan ||
    plan.id !== run.plan_version_id ||
    !nonNegativeInteger(invocation.run_revision) ||
    (invocation.run_revision as number) > run.revision ||
    !nonEmptyString(invocation.environment_id) ||
    (run.environment && invocation.environment_id !== run.environment.id) ||
    !nonEmptyString(invocation.tool_name) ||
    !Object.hasOwn(invocation, 'target') ||
    invocation.target === undefined ||
    !['read', 'mutate'].includes(String(invocation.effect)) ||
    typeof invocation.input_digest !== 'string' ||
    !sha256DigestPattern.test(invocation.input_digest) ||
    !Object.hasOwn(invocation, 'redacted_input') ||
    invocation.redacted_input === undefined ||
    !status ||
    !invocationStatuses.has(status) ||
    !nonNegativeInteger(invocation.prepared_at_ms) ||
    !optionalNonNegativeInteger(invocation.started_at_ms) ||
    !optionalNonNegativeInteger(invocation.finished_at_ms) ||
    (invocation.grant_id !== undefined &&
      invocation.grant_id !== null &&
      !nonEmptyString(invocation.grant_id)) ||
    (invocation.effect === 'mutate' && !nonEmptyString(invocation.grant_id))
  ) {
    return null;
  }
  return invocation as DesktopToolInvocation;
}

function readEvidenceSummary(value: unknown): SessionProjectionEvidenceSummary | null {
  const summary = recordValue(value);
  if (
    !summary ||
    !nonNegativeInteger(summary.artifact_version_count) ||
    !nonNegativeInteger(summary.artifact_delivery_count) ||
    !nonNegativeInteger(summary.artifact_source_count) ||
    !nonNegativeInteger(summary.tool_invocation_count) ||
    !nonNegativeInteger(summary.unknown_outcome_count)
  ) {
    return null;
  }
  let checks: SessionProjectionEvidenceSummary['checks'] = null;
  if (summary.checks !== null) {
    const valueChecks = recordValue(summary.checks);
    if (
      !valueChecks ||
      !nonNegativeInteger(valueChecks.total) ||
      !nonNegativeInteger(valueChecks.artifact_versions_without_checks)
    ) {
      return null;
    }
    checks = {
      total: valueChecks.total as number,
      artifactVersionsWithoutChecks: valueChecks.artifact_versions_without_checks as number,
    };
  }
  if (summary.changes !== null) return null;
  return {
    artifactVersionCount: summary.artifact_version_count as number,
    artifactDeliveryCount: summary.artifact_delivery_count as number,
    artifactSourceCount: summary.artifact_source_count as number,
    toolInvocationCount: summary.tool_invocation_count as number,
    unknownOutcomeCount: summary.unknown_outcome_count as number,
    checks,
    changes: null,
  };
}

function readCapabilities(value: unknown): SessionProjectionCapabilities | null {
  const capabilities = recordValue(value);
  if (!capabilities) return null;
  const booleanKeys = [
    'can_send_message',
    'can_approve_plan',
    'can_respond_to_hitl',
    'can_steer_now',
    'can_queue_next',
    'can_review_artifacts',
    'can_deliver_artifacts',
  ] as const;
  if (booleanKeys.some((key) => typeof capabilities[key] !== 'boolean')) return null;
  const runActions = readEnumArray(capabilities.run_actions, runActionValues);
  const allowedActions = readEnumArray(capabilities.allowed_actions, allowedActionValues);
  if (!runActions || !allowedActions) return null;
  return {
    canSendMessage: capabilities.can_send_message as boolean,
    canApprovePlan: capabilities.can_approve_plan as boolean,
    canRespondToHitl: capabilities.can_respond_to_hitl as boolean,
    canSteerNow: capabilities.can_steer_now as boolean,
    canQueueNext: capabilities.can_queue_next as boolean,
    canReviewArtifacts: capabilities.can_review_artifacts as boolean,
    canDeliverArtifacts: capabilities.can_deliver_artifacts as boolean,
    runActions,
    allowedActions,
  };
}

function capabilitiesAreConsistent(
  capabilities: SessionProjectionCapabilities,
  conversation: AgentConversation,
  currentRun: DesktopRun | null,
  currentPlan: SessionProjectionPlan | null,
  pendingHitl: DesktopApprovalRequest[],
  artifactVersions: DesktopArtifactVersion[],
): boolean {
  const expected: Array<[boolean, SessionAllowedAction]> = [
    [capabilities.canSendMessage, 'send_message'],
    [capabilities.canApprovePlan, 'approve_plan_and_start'],
    [capabilities.canRespondToHitl, 'respond_to_hitl'],
    [capabilities.canSteerNow, 'steer_now'],
    [capabilities.canQueueNext, 'queue_next'],
    [capabilities.canReviewArtifacts, 'review_artifact'],
    [capabilities.canDeliverArtifacts, 'deliver_artifact'],
  ];
  const expectedRunActions = runActionsForStatus(currentRun?.status ?? null);
  const expectedAllowedActions = [
    ...expected.filter(([enabled]) => enabled).map(([, action]) => action),
    ...expectedRunActions,
  ];
  const reviewableArtifact = artifactVersions.some((artifact) =>
    ['draft', 'ready', 'approved'].includes(artifact.status),
  );
  const deliverableArtifact = artifactVersions.some(
    (artifact) => artifact.status === 'approved',
  );
  return (
    sameStrings(capabilities.allowedActions, expectedAllowedActions) &&
    sameStrings(capabilities.runActions, expectedRunActions) &&
    capabilities.canSendMessage === (conversation.current_mode === 'plan') &&
    capabilities.canApprovePlan ===
      (conversation.current_mode === 'plan' && currentPlan?.status === 'draft') &&
    capabilities.canRespondToHitl === (pendingHitl.length > 0) &&
    capabilities.canQueueNext === (currentRun?.status === 'running') &&
    (!capabilities.canSteerNow || currentRun?.status === 'running') &&
    capabilities.canReviewArtifacts === reviewableArtifact &&
    capabilities.canDeliverArtifacts === deliverableArtifact
  );
}

function evidenceChecksAreConsistent(
  summary: SessionProjectionEvidenceSummary,
  artifactVersions: DesktopArtifactVersion[],
): boolean {
  if (!artifactVersions.length) return summary.checks === null;
  if (!summary.checks) return false;
  return (
    summary.checks.total ===
      artifactVersions.reduce((total, artifact) => total + artifact.checks.length, 0) &&
    summary.checks.artifactVersionsWithoutChecks ===
      artifactVersions.filter((artifact) => artifact.checks.length === 0).length
  );
}

function runActionsForStatus(status: DesktopRunStatus | null): SessionRunAction[] {
  switch (status) {
    case 'running':
      return ['pause', 'cancel'];
    case 'paused':
      return ['resume', 'cancel'];
    case 'disconnected':
    case 'interrupted':
      return ['reconnect', 'fork', 'cancel'];
    case 'ready_review':
      return ['request_changes', 'approve'];
    default:
      return [];
  }
}

function readArray<T>(value: unknown, reader: (item: unknown) => T | null): T[] | null {
  if (!Array.isArray(value)) return null;
  const result: T[] = [];
  for (const item of value) {
    const parsed = reader(item);
    if (parsed === null) return null;
    result.push(parsed);
  }
  return result;
}

function readNullable<T>(
  value: unknown,
  reader: (item: unknown) => T | null,
): T | null | undefined {
  if (value === null) return null;
  return reader(value) ?? undefined;
}

function readEnumArray<T extends string>(value: unknown, allowed: Set<T>): T[] | null {
  if (!Array.isArray(value) || !value.every((item) => typeof item === 'string')) return null;
  const result = value as T[];
  if (new Set(result).size !== result.length || result.some((item) => !allowed.has(item))) {
    return null;
  }
  return [...result];
}

function hasUniqueIds(values: Array<{ id: string }>): boolean {
  return new Set(values.map((value) => value.id)).size === values.length;
}

function sameStrings(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function optionalScopedRunId(value: unknown, runsById: Map<string, DesktopRun>): boolean {
  return value === null || (nonEmptyString(value) !== null && runsById.has(value as string));
}

function sameJson(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  if (Array.isArray(left) || Array.isArray(right)) {
    return (
      Array.isArray(left) &&
      Array.isArray(right) &&
      left.length === right.length &&
      left.every((value, index) => sameJson(value, right[index]))
    );
  }
  const leftRecord = recordValue(left);
  const rightRecord = recordValue(right);
  if (!leftRecord || !rightRecord) return false;
  const leftKeys = Object.keys(leftRecord).sort();
  const rightKeys = Object.keys(rightRecord).sort();
  return (
    sameStrings(leftKeys, rightKeys) &&
    leftKeys.every((key) => sameJson(leftRecord[key], rightRecord[key]))
  );
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function optionalString(value: unknown): boolean {
  return value === undefined || value === null || typeof value === 'string';
}

function optionalNonNegativeInteger(value: unknown): boolean {
  return value === undefined || value === null || nonNegativeInteger(value);
}

function nonNegativeInteger(value: unknown): boolean {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}
