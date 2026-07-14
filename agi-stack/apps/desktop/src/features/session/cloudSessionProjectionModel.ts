import type {
  AgentConversation,
  AgentRuntimeMode,
  DesktopApprovalRequest,
} from '../../types';
import type {
  CloudEvidenceSummary,
  CloudToolExecutionRecord,
  CloudToolExecutionRecords,
  CloudWorkspaceAttempt,
  CloudWorkspacePlanContext,
  CloudWorkspacePlanNode,
  ConversationSessionProjection,
  SessionAllowedAction,
  SessionProjectionCapabilities,
  SessionProjectionScope,
  SessionProjectionTask,
} from './sessionProjectionTypes';

export function decodeCloudConversationSessionProjection(
  root: Record<string, unknown>,
  expectedScope: string | SessionProjectionScope,
): ConversationSessionProjection | null {
  const scope =
    typeof expectedScope === 'string' ? { conversationId: expectedScope } : expectedScope;
  if (root.projection_kind !== 'workspace_session') return null;

  const snapshotRevision = nonEmptyString(root.snapshot_revision);
  const updatedAt = nonEmptyString(root.updated_at);
  const conversation = readCloudConversation(root.conversation, scope);
  if (!snapshotRevision || snapshotRevision.length > 256 || !updatedAt || !conversation) return null;

  const execution = recordValue(root.execution);
  const attemptHistory = execution
    ? readArray(execution.attempt_history, (value) => readCloudAttempt(value, scope, conversation))
    : null;
  const currentAttempt = execution
    ? readNullable(execution.current_attempt, (value) =>
        readCloudAttempt(value, scope, conversation),
      )
    : undefined;
  if (!execution || !attemptHistory || currentAttempt === undefined) return null;
  if ((currentAttempt === null) !== (attemptHistory.length === 0)) return null;
  if (currentAttempt && !sameJson(currentAttempt, attemptHistory[0])) return null;
  if (!hasUniqueIds(attemptHistory)) return null;

  const authorityKind = nonEmptyString(root.authority_kind);
  const authorityId = nonEmptyString(root.authority_id);
  if (
    !authorityId ||
    (currentAttempt
      ? authorityKind !== 'workspace_attempt' || authorityId !== currentAttempt.id
      : authorityKind !== 'conversation_record' || authorityId !== conversation.id)
  ) {
    return null;
  }

  const tasks = readArray(root.conversation_tasks, (value) => readCloudTask(value, scope));
  if (!tasks || !hasUniqueIds(tasks)) return null;
  const workspacePlanContext = readNullable(root.workspace_plan_context, (value) =>
    readCloudWorkspacePlanContext(value, conversation),
  );
  if (workspacePlanContext === undefined) return null;

  const pendingHitl = readArray(root.pending_hitl, (value) => readCloudHitl(value, scope));
  if (!pendingHitl || !hasUniqueIds(pendingHitl)) return null;
  const artifactRecordIds = readCloudArtifactRecordIds(root.artifact_records);
  const activityAuthority = readCloudToolExecutionRecords(root.tool_execution_records);
  const cloudEvidenceSummary = readCloudEvidenceSummary(root.evidence_summary);
  const capabilities = readCloudCapabilities(root.capabilities, pendingHitl);
  if (!artifactRecordIds || !activityAuthority || !cloudEvidenceSummary || !capabilities) {
    return null;
  }
  if (cloudEvidenceSummary.artifactRecordCount !== artifactRecordIds.length) return null;
  const candidateArtifactRefCount = attemptHistory.reduce(
    (total, attempt) => total + attempt.candidateArtifactRefs.length,
    0,
  );
  const candidateVerificationRefCount = attemptHistory.reduce(
    (total, attempt) => total + attempt.candidateVerificationRefs.length,
    0,
  );
  const visibleFailedToolCount = activityAuthority.items.filter(
    (record) => record.status === 'failed',
  ).length;
  if (
    cloudEvidenceSummary.candidateArtifactRefCount !== candidateArtifactRefCount ||
    cloudEvidenceSummary.candidateVerificationRefCount !== candidateVerificationRefCount ||
    cloudEvidenceSummary.toolExecutionRecordCount !== activityAuthority.total ||
    cloudEvidenceSummary.failedToolExecutionCount < visibleFailedToolCount ||
    cloudEvidenceSummary.failedToolExecutionCount > activityAuthority.total ||
    (!activityAuthority.truncated &&
      cloudEvidenceSummary.failedToolExecutionCount !== visibleFailedToolCount)
  ) {
    return null;
  }

  const executionAuthority: ConversationSessionProjection['executionAuthority'] = currentAttempt
    ? ({
        kind: 'workspace_attempt',
        currentRun: null,
        runHistory: [],
        currentAttempt,
        attemptHistory,
      })
    : ({
        kind: 'conversation_record',
        currentRun: null,
        runHistory: [],
        currentAttempt: null,
        attemptHistory: [],
      });
  const planAuthority: ConversationSessionProjection['planAuthority'] = {
    kind: 'agent_task_list',
    currentPlan: null,
    planHistory: [],
    tasks,
    workspacePlanContext,
  };
  const hitlAuthority: ConversationSessionProjection['hitlAuthority'] = {
    kind: 'cloud_hitl',
    pending: pendingHitl,
  };

  return {
    schemaVersion: 2,
    conversation,
    executionAuthority,
    planAuthority,
    hitlAuthority,
    artifactAuthority: { kind: 'unavailable', versions: [], deliveries: [] },
    activityAuthority,
    cloudEvidenceSummary,
    currentRun: null,
    runHistory: [],
    currentPlan: null,
    planHistory: [],
    tasks,
    pendingHitl,
    artifactVersions: [],
    artifactDeliveries: [],
    toolInvocations: [],
    evidenceSummary: {
      artifactVersionCount: null,
      artifactDeliveryCount: null,
      artifactSourceCount: null,
      toolInvocationCount: null,
      unknownOutcomeCount: null,
      checks: null,
      changes: null,
    },
    capabilities,
    snapshotRevision,
    updatedAt,
  };
}

function readCloudConversation(
  value: unknown,
  scope: SessionProjectionScope,
): AgentConversation | null {
  const conversation = recordValue(value);
  if (!conversation) return null;
  const id = nonEmptyString(conversation.id);
  const projectId = nonEmptyString(conversation.project_id);
  const tenantId = nonEmptyString(conversation.tenant_id);
  const userId = nonEmptyString(conversation.user_id);
  const createdAt = nonEmptyString(conversation.created_at);
  const currentMode = nonEmptyString(conversation.current_mode);
  const capabilityMode = conversation.capability_mode;
  if (
    id !== scope.conversationId ||
    !projectId ||
    !tenantId ||
    !userId ||
    typeof conversation.title !== 'string' ||
    typeof conversation.status !== 'string' ||
    !nonNegativeInteger(conversation.message_count) ||
    !createdAt ||
    !Object.hasOwn(conversation, 'updated_at') ||
    !optionalString(conversation.updated_at) ||
    !Object.hasOwn(conversation, 'summary') ||
    !optionalString(conversation.summary) ||
    !['plan', 'build', 'explore'].includes(currentMode ?? '') ||
    (capabilityMode !== null && capabilityMode !== 'work' && capabilityMode !== 'code') ||
    !Object.hasOwn(conversation, 'conversation_mode') ||
    !optionalString(conversation.conversation_mode) ||
    !Object.hasOwn(conversation, 'workspace_id') ||
    !optionalString(conversation.workspace_id) ||
    !Object.hasOwn(conversation, 'linked_workspace_task_id') ||
    !optionalString(conversation.linked_workspace_task_id) ||
    !Object.hasOwn(conversation, 'workspace_name') ||
    !optionalString(conversation.workspace_name) ||
    !Array.isArray(conversation.participant_agents) ||
    !conversation.participant_agents.every((participant) => nonEmptyString(participant)) ||
    !Object.hasOwn(conversation, 'coordinator_agent_id') ||
    !optionalString(conversation.coordinator_agent_id) ||
    !Object.hasOwn(conversation, 'focused_agent_id') ||
    !optionalString(conversation.focused_agent_id)
  ) {
    return null;
  }
  if (scope.projectId && projectId !== scope.projectId) return null;
  if (scope.tenantId && tenantId !== scope.tenantId) return null;
  if (
    Object.hasOwn(scope, 'workspaceId') &&
    (conversation.workspace_id ?? null) !== scope.workspaceId
  ) {
    return null;
  }
  return {
    id,
    project_id: projectId,
    tenant_id: tenantId,
    user_id: userId,
    title: conversation.title as string,
    status: conversation.status as string,
    message_count: conversation.message_count as number,
    created_at: createdAt,
    updated_at: (conversation.updated_at as string | null) ?? null,
    summary: (conversation.summary as string | null) ?? null,
    agent_config: {
      capability_mode:
        capabilityMode === 'work' || capabilityMode === 'code' ? capabilityMode : 'unavailable',
    },
    metadata: {},
    conversation_mode: (conversation.conversation_mode as string | null) ?? null,
    current_mode: currentMode as AgentRuntimeMode,
    workspace_id: (conversation.workspace_id as string | null) ?? null,
    linked_workspace_task_id:
      (conversation.linked_workspace_task_id as string | null) ?? null,
    workspace_name: (conversation.workspace_name as string | null) ?? null,
    participant_agents: [...(conversation.participant_agents as string[])],
    coordinator_agent_id: (conversation.coordinator_agent_id as string | null) ?? null,
    focused_agent_id: (conversation.focused_agent_id as string | null) ?? null,
  };
}

function readCloudAttempt(
  value: unknown,
  scope: SessionProjectionScope,
  conversation: AgentConversation,
): CloudWorkspaceAttempt | null {
  const attempt = recordValue(value);
  if (!attempt) return null;
  const id = nonEmptyString(attempt.id);
  const workspaceTaskId = nonEmptyString(attempt.workspace_task_id);
  const rootGoalTaskId = nonEmptyString(attempt.root_goal_task_id);
  const workspaceId = nonEmptyString(attempt.workspace_id);
  const conversationId = nonEmptyString(attempt.conversation_id);
  const status = nonEmptyString(attempt.status);
  const createdAt = nonEmptyString(attempt.created_at);
  if (
    !id ||
    !workspaceTaskId ||
    !rootGoalTaskId ||
    !workspaceId ||
    conversationId !== scope.conversationId ||
    workspaceId !== conversation.workspace_id ||
    (conversation.linked_workspace_task_id !== null &&
      workspaceTaskId !== conversation.linked_workspace_task_id) ||
    !nonNegativeInteger(attempt.attempt_number) ||
    !status ||
    !createdAt ||
    !Object.hasOwn(attempt, 'worker_agent_id') ||
    !optionalString(attempt.worker_agent_id) ||
    !Object.hasOwn(attempt, 'leader_agent_id') ||
    !optionalString(attempt.leader_agent_id) ||
    !Object.hasOwn(attempt, 'candidate_summary') ||
    !optionalString(attempt.candidate_summary) ||
    !stringArray(attempt.candidate_artifact_refs) ||
    !stringArray(attempt.candidate_verification_refs) ||
    !Object.hasOwn(attempt, 'leader_feedback') ||
    !optionalString(attempt.leader_feedback) ||
    !Object.hasOwn(attempt, 'adjudication_reason') ||
    !optionalString(attempt.adjudication_reason) ||
    !Object.hasOwn(attempt, 'updated_at') ||
    !optionalString(attempt.updated_at) ||
    !Object.hasOwn(attempt, 'completed_at') ||
    !optionalString(attempt.completed_at)
  ) {
    return null;
  }
  return {
    id,
    workspaceTaskId,
    rootGoalTaskId,
    workspaceId,
    conversationId,
    attemptNumber: attempt.attempt_number as number,
    status,
    workerAgentId: (attempt.worker_agent_id as string | null) ?? null,
    leaderAgentId: (attempt.leader_agent_id as string | null) ?? null,
    candidateSummary: (attempt.candidate_summary as string | null) ?? null,
    candidateArtifactRefs: [...(attempt.candidate_artifact_refs as string[])],
    candidateVerificationRefs: [...(attempt.candidate_verification_refs as string[])],
    leaderFeedback: (attempt.leader_feedback as string | null) ?? null,
    adjudicationReason: (attempt.adjudication_reason as string | null) ?? null,
    createdAt,
    updatedAt: (attempt.updated_at as string | null) ?? null,
    completedAt: (attempt.completed_at as string | null) ?? null,
  };
}

function readCloudTask(value: unknown, scope: SessionProjectionScope): SessionProjectionTask | null {
  const task = recordValue(value);
  if (!task) return null;
  const id = nonEmptyString(task.id);
  const conversationId = nonEmptyString(task.conversation_id);
  const content = nonEmptyString(task.content);
  const status = nonEmptyString(task.status);
  const priority = nonEmptyString(task.priority);
  const createdAt = nonEmptyString(task.created_at);
  if (
    !id ||
    conversationId !== scope.conversationId ||
    !content ||
    !status ||
    !priority ||
    !nonNegativeInteger(task.order_index) ||
    !createdAt ||
    !Object.hasOwn(task, 'updated_at') ||
    !optionalString(task.updated_at)
  ) {
    return null;
  }
  return {
    id,
    conversation_id: conversationId,
    content,
    status,
    priority,
    order_index: task.order_index,
    created_at: createdAt,
    updated_at: (task.updated_at as string | null) ?? null,
  };
}

function readCloudWorkspacePlanContext(
  value: unknown,
  conversation: AgentConversation,
): CloudWorkspacePlanContext | null {
  const plan = recordValue(value);
  if (!plan) return null;
  const id = nonEmptyString(plan.id);
  const workspaceId = nonEmptyString(plan.workspace_id);
  const goalId = nonEmptyString(plan.goal_id);
  const status = nonEmptyString(plan.status);
  const createdAt = nonEmptyString(plan.created_at);
  const linkedNodes = readArray(plan.linked_nodes, (node) =>
    readCloudWorkspacePlanNode(node, id, conversation.linked_workspace_task_id ?? null),
  );
  if (
    !id ||
    !workspaceId ||
    workspaceId !== conversation.workspace_id ||
    !goalId ||
    !status ||
    !createdAt ||
    !Object.hasOwn(plan, 'updated_at') ||
    !optionalString(plan.updated_at) ||
    !linkedNodes ||
    !hasUniqueIds(linkedNodes)
  ) {
    return null;
  }
  return {
    id,
    workspaceId,
    goalId,
    status,
    createdAt,
    updatedAt: (plan.updated_at as string | null) ?? null,
    linkedNodes,
  };
}

function readCloudWorkspacePlanNode(
  value: unknown,
  planId: string | null,
  linkedTaskId: string | null,
): CloudWorkspacePlanNode | null {
  const node = recordValue(value);
  if (!node || !planId || !linkedTaskId) return null;
  const id = nonEmptyString(node.id);
  const workspaceTaskId = nonEmptyString(node.workspace_task_id);
  const kind = nonEmptyString(node.kind);
  const title = nonEmptyString(node.title);
  const intent = nonEmptyString(node.intent);
  const execution = nonEmptyString(node.execution);
  const createdAt = nonEmptyString(node.created_at);
  const progress = recordValue(node.progress);
  if (
    !id ||
    node.plan_id !== planId ||
    workspaceTaskId !== linkedTaskId ||
    !kind ||
    !title ||
    typeof node.description !== 'string' ||
    !intent ||
    !execution ||
    !progress ||
    !Object.hasOwn(node, 'assignee_agent_id') ||
    !optionalString(node.assignee_agent_id) ||
    !Object.hasOwn(node, 'current_attempt_id') ||
    !optionalString(node.current_attempt_id) ||
    !createdAt ||
    !Object.hasOwn(node, 'updated_at') ||
    !optionalString(node.updated_at) ||
    !Object.hasOwn(node, 'completed_at') ||
    !optionalString(node.completed_at)
  ) {
    return null;
  }
  return {
    id,
    planId,
    workspaceTaskId,
    kind,
    title,
    description: node.description as string,
    intent,
    execution,
    progress: { ...progress },
    assigneeAgentId: (node.assignee_agent_id as string | null) ?? null,
    currentAttemptId: (node.current_attempt_id as string | null) ?? null,
    createdAt,
    updatedAt: (node.updated_at as string | null) ?? null,
    completedAt: (node.completed_at as string | null) ?? null,
  };
}

function readCloudHitl(
  value: unknown,
  scope: SessionProjectionScope,
): DesktopApprovalRequest | null {
  const request = recordValue(value);
  if (!request) return null;
  const id = nonEmptyString(request.id);
  const kind = nonEmptyString(request.request_type);
  const prompt = nonEmptyString(request.question);
  const createdAt = nonEmptyString(request.created_at);
  const expiresAt = nonEmptyString(request.expires_at);
  if (
    !id ||
    request.conversation_id !== scope.conversationId ||
    !kind ||
    !['clarification', 'decision', 'env_var', 'permission', 'a2ui_action'].includes(kind) ||
    !prompt ||
    request.status !== 'pending' ||
    !createdAt ||
    !expiresAt ||
    !Object.hasOwn(request, 'message_id') ||
    !optionalString(request.message_id)
  ) {
    return null;
  }
  return {
    id,
    conversation_id: scope.conversationId,
    run_id: null,
    kind: kind as DesktopApprovalRequest['kind'],
    prompt,
    status: 'pending',
    created_at: createdAt,
    responded_at: null,
    message_id: (request.message_id as string | null) ?? null,
    expires_at: expiresAt,
  };
}

function readCloudArtifactRecordIds(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  const ids: string[] = [];
  for (const item of value) {
    const id = nonEmptyString(recordValue(item)?.id);
    if (!id) return null;
    ids.push(id);
  }
  return new Set(ids).size === ids.length ? ids : null;
}

function readCloudToolExecutionRecords(value: unknown):
  | ({ kind: 'cloud_tool_records'; invocations: [] } & CloudToolExecutionRecords)
  | null {
  const page = recordValue(value);
  const items = page
    ? readArray(page.items, (item) => readCloudToolExecutionRecord(item))
    : null;
  if (
    !page ||
    !items ||
    !hasUniqueIds(items) ||
    !nonNegativeInteger(page.total) ||
    (page.total as number) < items.length ||
    typeof page.truncated !== 'boolean' ||
    page.truncated !== ((page.total as number) > items.length)
  ) {
    return null;
  }
  return {
    kind: 'cloud_tool_records',
    invocations: [],
    items,
    total: page.total as number,
    truncated: page.truncated as boolean,
  };
}

function readCloudToolExecutionRecord(value: unknown): CloudToolExecutionRecord | null {
  const record = recordValue(value);
  if (!record) return null;
  const id = nonEmptyString(record.id);
  const messageId = nonEmptyString(record.message_id);
  const callId = nonEmptyString(record.call_id);
  const toolName = nonEmptyString(record.tool_name);
  const status = nonEmptyString(record.status);
  const startedAt = nonEmptyString(record.started_at);
  if (
    !id ||
    !messageId ||
    !callId ||
    !toolName ||
    !status ||
    !startedAt ||
    !Object.hasOwn(record, 'error') ||
    !optionalString(record.error) ||
    !optionalNonNegativeInteger(record.step_number) ||
    !nonNegativeInteger(record.sequence_number) ||
    !Object.hasOwn(record, 'completed_at') ||
    !optionalString(record.completed_at) ||
    !optionalNonNegativeInteger(record.duration_ms)
  ) {
    return null;
  }
  return {
    id,
    messageId,
    callId,
    toolName,
    status,
    error: (record.error as string | null) ?? null,
    stepNumber: (record.step_number as number | null) ?? null,
    sequenceNumber: record.sequence_number as number,
    startedAt,
    completedAt: (record.completed_at as string | null) ?? null,
    durationMs: (record.duration_ms as number | null) ?? null,
  };
}

function readCloudEvidenceSummary(value: unknown): CloudEvidenceSummary | null {
  const summary = recordValue(value);
  if (!summary) return null;
  const keys = [
    'candidate_artifact_ref_count',
    'candidate_verification_ref_count',
    'artifact_record_count',
    'tool_execution_record_count',
    'failed_tool_execution_count',
  ] as const;
  if (keys.some((key) => !nonNegativeInteger(summary[key]))) return null;
  return {
    candidateArtifactRefCount: summary.candidate_artifact_ref_count as number,
    candidateVerificationRefCount: summary.candidate_verification_ref_count as number,
    artifactRecordCount: summary.artifact_record_count as number,
    toolExecutionRecordCount: summary.tool_execution_record_count as number,
    failedToolExecutionCount: summary.failed_tool_execution_count as number,
  };
}

function readCloudCapabilities(
  value: unknown,
  pendingHitl: DesktopApprovalRequest[],
): SessionProjectionCapabilities | null {
  const capabilities = recordValue(value);
  if (!capabilities) return null;
  const booleanKeys = [
    'can_send_message',
    'can_respond_to_hitl',
    'can_approve_plan',
    'can_control_execution',
    'can_review_artifacts',
    'can_deliver_artifacts',
  ] as const;
  if (booleanKeys.some((key) => typeof capabilities[key] !== 'boolean')) return null;
  const allowed = readEnumArray(
    capabilities.allowed_actions,
    new Set<SessionAllowedAction>(['send_message', 'respond_to_hitl']),
  );
  if (!allowed) return null;
  const expected = [
    ...(capabilities.can_send_message ? (['send_message'] as const) : []),
    ...(capabilities.can_respond_to_hitl ? (['respond_to_hitl'] as const) : []),
  ];
  if (
    capabilities.can_approve_plan ||
    capabilities.can_control_execution ||
    capabilities.can_review_artifacts ||
    capabilities.can_deliver_artifacts ||
    (pendingHitl.length > 0 && capabilities.can_send_message) ||
    capabilities.can_respond_to_hitl !== (pendingHitl.length > 0) ||
    !sameStringSets(allowed, expected)
  ) {
    return null;
  }
  return {
    canSendMessage: capabilities.can_send_message as boolean,
    canApprovePlan: false,
    canRespondToHitl: capabilities.can_respond_to_hitl as boolean,
    canSteerNow: false,
    canQueueNext: false,
    canReviewArtifacts: false,
    canDeliverArtifacts: false,
    runActions: [],
    allowedActions: allowed,
  };
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

function sameStringSets(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value) => right.includes(value));
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

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => nonEmptyString(item) !== null);
}

function nonNegativeInteger(value: unknown): boolean {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}
