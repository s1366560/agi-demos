import { DesktopApiError } from '../../api/client';
import type {
  ActivityReadEntry,
  ActivityReadState,
  ActivityAuthorityScope,
  CloudRunInputAck,
  CloudRunInputContextItem,
  CloudRunInputListResponse,
  CloudRunInputReceipt,
  CloudRunInputReference,
  CloudAgentAuthorityScope,
  CreateCloudRunInputRequest,
  GetRunChangesOptions,
  ProjectMyWorkResponse,
  ProjectWorkItem,
  RunChangeAttribution,
  RunChangeFile,
  RunChangeHunk,
  RunChangeLine,
  RunChanges,
  RunSummary,
  PromoteCloudRunInputRequest,
  PromoteCloudRunInputResponse,
  UpdateActivityReadStateRequest,
} from './agentAuthorityTypes';

const AUTHORITY_KINDS = new Set([
  'desktop_run',
  'agent_run',
  'workspace_attempt',
  'hitl_request',
]);
const WORK_GROUPS = new Set([
  'needs_input',
  'needs_approval',
  'running',
  'ready_review',
]);
const WORK_STATUSES = new Set([
  'running',
  'ready_review',
  'failed',
  'needs_input',
  'needs_approval',
]);
const REQUIRED_ACTIONS = new Set([
  'provide_input',
  'review_approval',
  'observe',
  'inspect_failure',
]);
const PERMISSION_PROFILES = new Set([
  'read_only',
  'workspace_write',
  'full_access',
]);
const CHANGE_SCOPES = new Set(['turn', 'run', 'session']);
const CHANGE_STATUSES = new Set([
  'ready',
  'unattributed',
  'unavailable',
  'failed',
]);
const RUN_INPUT_DELIVERIES = new Set(['steer_now', 'queue_next']);
const RUN_INPUT_STATUSES = new Set([
  'pending_boundary',
  'queued',
  'applied',
  'ready',
  'blocked',
  'promoted_to_plan',
]);
const RUN_INPUT_DISPATCH_STATUSES = new Set([
  'not_required',
  'dispatching',
  'dispatched',
  'failed',
]);
const RUN_INPUT_CONTEXT_KINDS = new Set([
  'attachment',
  'agent',
  'skill',
  'plugin',
  'command',
  'thread',
]);

export function parseProjectMyWorkResponse(
  payload: unknown,
  scope: CloudAgentAuthorityScope,
): ProjectMyWorkResponse {
  if (
    !isRecord(payload) ||
    payload.project_id !== scope.projectId ||
    !Array.isArray(payload.items)
  ) {
    throw contractError('cloud_my_work_contract_invalid');
  }
  if (
    !isNonnegativeInteger(payload.total) ||
    payload.total !== payload.items.length
  ) {
    throw contractError('cloud_my_work_contract_invalid');
  }
  const items = payload.items.map((item) => parseProjectWorkItem(item, scope));
  return { project_id: scope.projectId, items, total: payload.total };
}

export function parseActivityReadState(
  payload: unknown,
  scope: Pick<ActivityAuthorityScope, 'projectId'>,
  reasonCode = 'cloud_activity_read_state_contract_invalid',
): ActivityReadState {
  if (
    !isRecord(payload) ||
    payload.project_id !== scope.projectId ||
    !isNonnegativeInteger(payload.authority_revision) ||
    !Array.isArray(payload.entries) ||
    payload.entries.length > 500
  ) {
    throw contractError(reasonCode);
  }
  const entries = payload.entries.map(parseActivityReadEntry);
  if (new Set(entries.map((entry) => entry.entry_id)).size !== entries.length) {
    throw contractError(reasonCode);
  }
  return {
    project_id: scope.projectId,
    authority_revision: payload.authority_revision,
    entries,
  };
}

export function requireActivityReadUpdateRequest(
  request: UpdateActivityReadStateRequest,
  reasonCode = 'cloud_activity_read_state_request_invalid',
): UpdateActivityReadStateRequest {
  if (
    !isRecord(request) ||
    !isNonnegativeInteger(request.expected_authority_revision) ||
    !Array.isArray(request.entries) ||
    request.entries.length > 500
  ) {
    throw contractError(reasonCode);
  }
  const entries = request.entries.map(parseActivityReadEntry);
  if (new Set(entries.map((entry) => entry.entry_id)).size !== entries.length) {
    throw contractError(reasonCode);
  }
  return {
    expected_authority_revision: request.expected_authority_revision,
    entries,
  };
}

export function parseRunSummary(
  payload: unknown,
  scope: CloudAgentAuthorityScope,
  runId: string,
): RunSummary {
  if (
    !isRecord(payload) ||
    payload.run_id !== runId ||
    payload.tenant_id !== scope.tenantId ||
    payload.project_id !== scope.projectId ||
    !isIdentifier(payload.conversation_id) ||
    !isIdentifier(payload.status) ||
    !isNonnegativeInteger(payload.revision) ||
    (payload.summary_state !== 'recorded' &&
      payload.summary_state !== 'partial') ||
    !isNullableString(payload.reason_code) ||
    !isNullableTimestamp(payload.started_at) ||
    !isNullableTimestamp(payload.completed_at) ||
    !isNullableNonnegativeInteger(payload.duration_ms) ||
    !isNullableNonnegativeInteger(payload.input_tokens) ||
    !isNullableNonnegativeInteger(payload.output_tokens) ||
    !isNullableNonnegativeNumber(payload.cost_usd) ||
    !isRecordArray(payload.model_breakdown) ||
    !isNullableString(payload.completion_summary) ||
    !isNullableNonnegativeInteger(payload.artifact_count) ||
    !isNullableNonnegativeInteger(payload.checks_passed) ||
    !isNullableNonnegativeInteger(payload.checks_failed) ||
    !isNullableNonnegativeInteger(payload.files_changed) ||
    !isNullableNonnegativeInteger(payload.lines_added) ||
    !isNullableNonnegativeInteger(payload.lines_deleted) ||
    !isRecordArray(payload.evidence_references)
  ) {
    throw contractError('cloud_run_summary_contract_invalid');
  }
  return {
    run_id: runId,
    tenant_id: scope.tenantId,
    project_id: scope.projectId,
    conversation_id: payload.conversation_id,
    status: payload.status,
    revision: payload.revision,
    summary_state: payload.summary_state,
    reason_code: payload.reason_code,
    started_at: payload.started_at,
    completed_at: payload.completed_at,
    duration_ms: payload.duration_ms,
    input_tokens: payload.input_tokens,
    output_tokens: payload.output_tokens,
    cost_usd: payload.cost_usd,
    model_breakdown: payload.model_breakdown.map((item) => ({ ...item })),
    completion_summary: payload.completion_summary,
    artifact_count: payload.artifact_count,
    checks_passed: payload.checks_passed,
    checks_failed: payload.checks_failed,
    files_changed: payload.files_changed,
    lines_added: payload.lines_added,
    lines_deleted: payload.lines_deleted,
    evidence_references: payload.evidence_references.map((item) => ({
      ...item,
    })),
  };
}

export function parseRunChanges(
  payload: unknown,
  runId: string,
  request: GetRunChangesOptions,
): RunChanges {
  if (
    !isRecord(payload) ||
    !isIdentifier(payload.id) ||
    payload.run_id !== runId ||
    !isIdentifier(payload.conversation_id) ||
    payload.run_revision !== request.expected_revision ||
    payload.scope !== request.scope ||
    (request.scope === 'turn'
      ? payload.turn_id !== request.turn_id
      : payload.turn_id !== null) ||
    !isIdentifier(payload.snapshot_revision) ||
    !CHANGE_STATUSES.has(String(payload.status)) ||
    !isNullableString(payload.environment_id) ||
    !isNullableString(payload.repository_root) ||
    !isNullableString(payload.workspace_path) ||
    !isNullableString(payload.branch) ||
    !isNullableString(payload.base_revision) ||
    !isNullableString(payload.head_revision) ||
    !isNullableString(payload.reason) ||
    !isNonnegativeInteger(payload.additions) ||
    !isNonnegativeInteger(payload.deletions) ||
    !isNonnegativeInteger(payload.files_changed) ||
    typeof payload.truncated !== 'boolean' ||
    !isTimestamp(payload.captured_at) ||
    !Array.isArray(payload.files) ||
    !Array.isArray(payload.attribution)
  ) {
    throw contractError('cloud_run_changes_contract_invalid');
  }
  const files = payload.files.map(parseChangeFile);
  const attribution = payload.attribution.map(parseChangeAttribution);
  if (payload.files_changed !== files.length) {
    throw contractError('cloud_run_changes_contract_invalid');
  }
  return {
    id: payload.id,
    run_id: runId,
    conversation_id: payload.conversation_id,
    run_revision: payload.run_revision,
    environment_id: payload.environment_id,
    repository_root: payload.repository_root,
    workspace_path: payload.workspace_path,
    branch: payload.branch,
    base_revision: payload.base_revision,
    head_revision: payload.head_revision,
    status: payload.status as RunChanges['status'],
    reason: payload.reason,
    additions: payload.additions,
    deletions: payload.deletions,
    files_changed: payload.files_changed,
    truncated: payload.truncated,
    captured_at: payload.captured_at,
    files,
    scope: request.scope,
    turn_id: payload.turn_id as string | null,
    snapshot_revision: payload.snapshot_revision,
    attribution,
  };
}

export function requireCreateRunInputRequest(
  request: CreateCloudRunInputRequest,
): CreateCloudRunInputRequest {
  if (
    !isRecord(request) ||
    !isPositiveInteger(request.expected_run_revision) ||
    !isNonemptyString(request.message) ||
    !isIdentifier(request.message_id) ||
    !isIdentifier(request.idempotency_key) ||
    !RUN_INPUT_DELIVERIES.has(String(request.delivery)) ||
    !Array.isArray(request.references) ||
    request.references.length > 32 ||
    !Array.isArray(request.context_items) ||
    request.context_items.length > 32
  ) {
    throw contractError('cloud_run_input_request_invalid');
  }
  const references = request.references.map(parseRunInputReference);
  const contextItems = request.context_items.map(parseRunInputContextItem);
  if (
    new Set(references.map(runInputReferenceKey)).size !== references.length ||
    new Set(contextItems.map((item) => `${item.kind}:${item.resource_id}`))
      .size !== contextItems.length
  ) {
    throw contractError('cloud_run_input_request_invalid');
  }
  return {
    expected_run_revision: request.expected_run_revision,
    message: request.message,
    message_id: request.message_id,
    idempotency_key: request.idempotency_key,
    delivery: request.delivery as CreateCloudRunInputRequest['delivery'],
    references,
    context_items: contextItems,
  };
}

export function requirePromoteRunInputRequest(
  request: PromoteCloudRunInputRequest,
): PromoteCloudRunInputRequest {
  if (
    !isRecord(request) ||
    !isPositiveInteger(request.expected_source_run_revision) ||
    !isIdentifier(request.idempotency_key)
  ) {
    throw contractError('cloud_run_input_promotion_request_invalid');
  }
  return {
    expected_source_run_revision: request.expected_source_run_revision,
    idempotency_key: request.idempotency_key,
  };
}

export function parseRunInputAck(
  payload: unknown,
  runId: string,
  request: CreateCloudRunInputRequest,
): CloudRunInputAck {
  if (
    !isRecord(payload) ||
    payload.accepted !== true ||
    typeof payload.created !== 'boolean' ||
    payload.action !== 'send_message' ||
    !isIdentifier(payload.conversation_id) ||
    payload.message_id !== request.message_id ||
    payload.delivery_mode !== request.delivery ||
    payload.run_id !== runId ||
    payload.run_revision !== request.expected_run_revision ||
    !isNullablePositiveInteger(payload.queue_position)
  ) {
    throw contractError('cloud_run_input_contract_invalid');
  }
  const input = parseRunInputReceipt(payload.input, runId);
  if (
    input.conversation_id !== payload.conversation_id ||
    input.message_id !== request.message_id ||
    input.idempotency_key !== request.idempotency_key ||
    input.delivery !== request.delivery ||
    input.expected_run_revision !== request.expected_run_revision
  ) {
    throw contractError('cloud_run_input_contract_invalid');
  }
  return {
    accepted: true,
    created: payload.created,
    action: 'send_message',
    conversation_id: payload.conversation_id,
    message_id: payload.message_id,
    delivery_mode: payload.delivery_mode as CloudRunInputAck['delivery_mode'],
    run_id: runId,
    run_revision: payload.run_revision,
    queue_position: payload.queue_position,
    input,
  };
}

export function parseRunInputListResponse(
  payload: unknown,
  runId: string,
): CloudRunInputListResponse {
  if (
    !isRecord(payload) ||
    payload.run_id !== runId ||
    !isPositiveInteger(payload.run_revision) ||
    !Array.isArray(payload.inputs) ||
    !isNonnegativeInteger(payload.total_count) ||
    payload.total_count !== payload.inputs.length
  ) {
    throw contractError('cloud_run_input_contract_invalid');
  }
  return {
    run_id: runId,
    run_revision: payload.run_revision,
    inputs: payload.inputs.map((input) => parseRunInputReceipt(input, runId)),
    total_count: payload.total_count,
  };
}

export function parsePromoteRunInputResponse(
  payload: unknown,
  scope: CloudAgentAuthorityScope,
  runId: string,
  request: PromoteCloudRunInputRequest,
): PromoteCloudRunInputResponse {
  if (
    !isRecord(payload) ||
    payload.accepted !== true ||
    typeof payload.created !== 'boolean' ||
    payload.action !== 'start_plan_turn' ||
    !isRecord(payload.conversation) ||
    !isRecord(payload.source_run)
  ) {
    throw contractError('cloud_run_input_promotion_contract_invalid');
  }
  const input = parseRunInputReceipt(payload.input, runId);
  if (
    payload.conversation.id !== input.conversation_id ||
    payload.conversation.tenant_id !== scope.tenantId ||
    payload.conversation.project_id !== scope.projectId ||
    payload.source_run.id !== runId ||
    payload.source_run.conversation_id !== input.conversation_id ||
    payload.source_run.project_id !== scope.projectId ||
    payload.source_run.revision !== request.expected_source_run_revision
  ) {
    throw contractError('cloud_run_input_promotion_contract_invalid');
  }
  return {
    accepted: true,
    created: payload.created,
    action: 'start_plan_turn',
    input,
    conversation: { ...payload.conversation },
    source_run: {
      ...payload.source_run,
      revision: payload.source_run.revision,
    },
  };
}

export function requireCloudAuthorityScope(
  scope: ActivityAuthorityScope,
): CloudAgentAuthorityScope {
  if (
    !isRecord(scope) ||
    scope.authority !== 'cloud' ||
    !isIdentifier(scope.principalId) ||
    !isIdentifier(scope.tenantId) ||
    !isIdentifier(scope.projectId)
  ) {
    throw contractError('cloud_agent_authority_scope_invalid');
  }
  return scope;
}

export function requireRunChangesOptions(
  options: GetRunChangesOptions,
): GetRunChangesOptions {
  if (
    !isRecord(options) ||
    !CHANGE_SCOPES.has(String(options.scope)) ||
    !isPositiveInteger(options.expected_revision) ||
    (options.turn_id !== undefined && !isIdentifier(options.turn_id)) ||
    (options.scope === 'turn' && !isIdentifier(options.turn_id))
  ) {
    throw contractError(
      options?.scope === 'turn' && !options.turn_id
        ? 'cloud_run_changes_turn_id_required'
        : 'cloud_run_changes_request_invalid',
    );
  }
  return options;
}

function parseProjectWorkItem(
  value: unknown,
  scope: CloudAgentAuthorityScope,
): ProjectWorkItem {
  if (
    !isRecord(value) ||
    !isIdentifier(value.id) ||
    !AUTHORITY_KINDS.has(String(value.authority_kind)) ||
    !isIdentifier(value.authority_id) ||
    !isNullableIdentifier(value.run_id) ||
    !isIdentifier(value.conversation_id) ||
    !isNullableIdentifier(value.workspace_id) ||
    value.project_id !== scope.projectId ||
    !isNonemptyString(value.title) ||
    !isNullableEnum(value.capability_mode, new Set(['work', 'code'])) ||
    !WORK_GROUPS.has(String(value.group)) ||
    !WORK_STATUSES.has(String(value.status)) ||
    !REQUIRED_ACTIONS.has(String(value.required_action)) ||
    !isNullableNonnegativeInteger(value.revision) ||
    !isNullableEnum(value.permission_profile, PERMISSION_PROFILES) ||
    !isNullableString(value.environment) ||
    !isNullableString(value.error) ||
    !isNullableNonnegativeInteger(value.attempt_number) ||
    !isTimestamp(value.created_at) ||
    !isTimestamp(value.updated_at) ||
    !isNullableTimestamp(value.last_heartbeat_at) ||
    !isNullableString(value.workspace_name) ||
    !isNullableString(value.summary) ||
    !isNullableString(value.phase) ||
    !isNullableNonnegativeInteger(value.progress)
  ) {
    throw contractError('cloud_my_work_contract_invalid');
  }
  let runSummary: RunSummary | null = null;
  if (value.run_summary !== null && value.run_summary !== undefined) {
    try {
      runSummary = parseRunSummary(
        value.run_summary,
        scope,
        String(value.run_id ?? value.authority_id),
      );
    } catch {
      throw contractError('cloud_my_work_contract_invalid');
    }
  }
  if (value.authority_kind === 'agent_run') {
    if (
      !isIdentifier(value.run_id) ||
      value.authority_id !== value.run_id ||
      runSummary === null
    ) {
      throw contractError('cloud_my_work_contract_invalid');
    }
    if (runSummary && runSummary.conversation_id !== value.conversation_id) {
      throw contractError('cloud_my_work_contract_invalid');
    }
  }
  return {
    id: value.id,
    authority_kind: value.authority_kind as ProjectWorkItem['authority_kind'],
    authority_id: value.authority_id,
    run_id: value.run_id,
    conversation_id: value.conversation_id,
    workspace_id: value.workspace_id,
    project_id: scope.projectId,
    title: value.title,
    capability_mode:
      value.capability_mode as ProjectWorkItem['capability_mode'],
    group: value.group as ProjectWorkItem['group'],
    status: value.status as ProjectWorkItem['status'],
    required_action:
      value.required_action as ProjectWorkItem['required_action'],
    revision: value.revision,
    permission_profile:
      value.permission_profile as ProjectWorkItem['permission_profile'],
    environment: value.environment,
    error: value.error,
    attempt_number: value.attempt_number,
    created_at: value.created_at,
    updated_at: value.updated_at,
    last_heartbeat_at: value.last_heartbeat_at,
    workspace_name: value.workspace_name,
    summary: value.summary,
    phase: value.phase,
    progress: value.progress,
    run_summary: runSummary,
  } as ProjectWorkItem;
}

function parseRunInputReceipt(
  value: unknown,
  runId: string,
): CloudRunInputReceipt {
  if (
    !isRecord(value) ||
    !isIdentifier(value.id) ||
    !isIdentifier(value.conversation_id) ||
    value.run_id !== runId ||
    !isPositiveInteger(value.expected_run_revision) ||
    !isIdentifier(value.message_id) ||
    !isIdentifier(value.idempotency_key) ||
    !RUN_INPUT_DELIVERIES.has(String(value.delivery)) ||
    !RUN_INPUT_STATUSES.has(String(value.status)) ||
    !isPositiveInteger(value.sequence) ||
    !isNullablePositiveInteger(value.queue_position) ||
    typeof value.content !== 'string' ||
    !Array.isArray(value.references) ||
    !Array.isArray(value.context_items) ||
    !isNullableNonnegativeInteger(value.applied_round) ||
    !isNullableTimestamp(value.applied_at) ||
    !isNullableString(value.injected_via) ||
    !RUN_INPUT_DISPATCH_STATUSES.has(String(value.dispatch_status)) ||
    !isNonnegativeInteger(value.dispatch_attempts) ||
    !isNullableTimestamp(value.dispatch_lease_expires_at) ||
    !isNullableString(value.dispatch_error_code) ||
    !isNullableString(value.promotion_idempotency_key) ||
    !isNullableTimestamp(value.promoted_at) ||
    !isTimestamp(value.created_at) ||
    !isTimestamp(value.updated_at)
  ) {
    throw contractError('cloud_run_input_contract_invalid');
  }
  return {
    id: value.id,
    conversation_id: value.conversation_id,
    run_id: runId,
    expected_run_revision: value.expected_run_revision,
    message_id: value.message_id,
    idempotency_key: value.idempotency_key,
    delivery: value.delivery as CloudRunInputReceipt['delivery'],
    status: value.status as CloudRunInputReceipt['status'],
    sequence: value.sequence,
    queue_position: value.queue_position,
    content: value.content,
    references: value.references.map(parseRunInputReference),
    context_items: value.context_items.map(parseRunInputContextItem),
    applied_round: value.applied_round,
    applied_at: value.applied_at,
    injected_via: value.injected_via,
    dispatch_status:
      value.dispatch_status as CloudRunInputReceipt['dispatch_status'],
    dispatch_attempts: value.dispatch_attempts,
    dispatch_lease_expires_at: value.dispatch_lease_expires_at,
    dispatch_error_code: value.dispatch_error_code,
    promotion_idempotency_key: value.promotion_idempotency_key,
    promoted_at: value.promoted_at,
    created_at: value.created_at,
    updated_at: value.updated_at,
  };
}

function parseRunInputReference(value: unknown): CloudRunInputReference {
  if (
    !isRecord(value) ||
    value.type !== 'code_range' ||
    !isIdentifier(value.snapshot_id) ||
    !isIdentifier(value.environment_id) ||
    !isIdentifier(value.path) ||
    !isPositiveInteger(value.start_line) ||
    !isPositiveInteger(value.end_line) ||
    value.end_line < value.start_line ||
    (value.side !== 'old' && value.side !== 'new') ||
    !isIdentifier(value.patch_digest)
  ) {
    throw contractError('cloud_run_input_contract_invalid');
  }
  return {
    type: 'code_range',
    snapshot_id: value.snapshot_id,
    environment_id: value.environment_id,
    path: value.path,
    start_line: value.start_line,
    end_line: value.end_line,
    side: value.side,
    patch_digest: value.patch_digest,
  };
}

function parseRunInputContextItem(value: unknown): CloudRunInputContextItem {
  if (
    !isRecord(value) ||
    !RUN_INPUT_CONTEXT_KINDS.has(String(value.kind)) ||
    !isIdentifier(value.resource_id) ||
    !isIdentifier(value.label) ||
    !isNullablePrimitiveRecord(value.metadata)
  ) {
    throw contractError('cloud_run_input_contract_invalid');
  }
  return {
    kind: value.kind as CloudRunInputContextItem['kind'],
    resource_id: value.resource_id,
    label: value.label,
    metadata: value.metadata === null ? null : { ...value.metadata },
  };
}

function runInputReferenceKey(value: CloudRunInputReference): string {
  return [
    value.snapshot_id,
    value.environment_id,
    value.path,
    value.start_line,
    value.end_line,
    value.side,
    value.patch_digest,
  ].join('\u0000');
}

function parseActivityReadEntry(value: unknown): ActivityReadEntry {
  if (
    !isRecord(value) ||
    !isIdentifier(value.entry_id) ||
    !isNonnegativeInteger(value.entry_revision) ||
    !isTimestamp(value.read_at)
  ) {
    throw contractError('cloud_activity_read_state_contract_invalid');
  }
  return {
    entry_id: value.entry_id,
    entry_revision: value.entry_revision,
    read_at: value.read_at,
  };
}

function parseChangeFile(value: unknown): RunChangeFile {
  if (
    !isRecord(value) ||
    !isIdentifier(value.path) ||
    !isNullableString(value.old_path) ||
    !isIdentifier(value.status) ||
    !isNonnegativeInteger(value.additions) ||
    !isNonnegativeInteger(value.deletions) ||
    typeof value.binary !== 'boolean' ||
    typeof value.untracked !== 'boolean' ||
    !isIdentifier(value.patch_digest) ||
    !Array.isArray(value.hunks)
  ) {
    throw contractError('cloud_run_changes_contract_invalid');
  }
  return {
    path: value.path,
    old_path: value.old_path,
    status: value.status,
    additions: value.additions,
    deletions: value.deletions,
    binary: value.binary,
    untracked: value.untracked,
    patch_digest: value.patch_digest,
    hunks: value.hunks.map(parseChangeHunk),
  };
}

function parseChangeHunk(value: unknown): RunChangeHunk {
  if (
    !isRecord(value) ||
    typeof value.header !== 'string' ||
    !isNonnegativeInteger(value.old_start) ||
    !isNonnegativeInteger(value.new_start) ||
    !Array.isArray(value.lines)
  ) {
    throw contractError('cloud_run_changes_contract_invalid');
  }
  return {
    header: value.header,
    old_start: value.old_start,
    new_start: value.new_start,
    lines: value.lines.map(parseChangeLine),
  };
}

function parseChangeLine(value: unknown): RunChangeLine {
  if (
    !isRecord(value) ||
    (value.kind !== 'context' &&
      value.kind !== 'addition' &&
      value.kind !== 'deletion') ||
    !isNullableNonnegativeInteger(value.old_line) ||
    !isNullableNonnegativeInteger(value.new_line) ||
    typeof value.text !== 'string'
  ) {
    throw contractError('cloud_run_changes_contract_invalid');
  }
  return {
    kind: value.kind,
    old_line: value.old_line,
    new_line: value.new_line,
    text: value.text,
  };
}

function parseChangeAttribution(value: unknown): RunChangeAttribution {
  if (
    !isRecord(value) ||
    !isNullableString(value.file_path) ||
    !isNullableString(value.hunk_id) ||
    (value.attribution !== 'attributed' &&
      value.attribution !== 'unattributed') ||
    !isNullableString(value.turn_id) ||
    !isIdentifier(value.event_id) ||
    !isIdentifier(value.event_revision) ||
    !isRecord(value.payload)
  ) {
    throw contractError('cloud_run_changes_contract_invalid');
  }
  return {
    file_path: value.file_path,
    hunk_id: value.hunk_id,
    attribution: value.attribution,
    turn_id: value.turn_id,
    event_id: value.event_id,
    event_revision: value.event_revision,
    payload: { ...value.payload },
  };
}

function contractError(reasonCode: string): DesktopApiError {
  return new DesktopApiError(reasonCode, 0, { reason_code: reasonCode });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isRecordArray(value: unknown): value is Record<string, unknown>[] {
  return Array.isArray(value) && value.every(isRecord);
}

function isNullablePrimitiveRecord(
  value: unknown,
): value is Record<string, string | number | boolean | null> | null {
  return (
    value === null ||
    (isRecord(value) &&
      Object.values(value).every(
        (item) =>
          item === null ||
          typeof item === 'string' ||
          (typeof item === 'number' && Number.isFinite(item)) ||
          typeof item === 'boolean',
      ))
  );
}

function isIdentifier(value: unknown): value is string {
  return (
    typeof value === 'string' && value.length > 0 && value === value.trim()
  );
}

function isNonemptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

function isNullableIdentifier(value: unknown): value is string | null {
  return value === null || isIdentifier(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length > 0 &&
    Number.isFinite(Date.parse(value))
  );
}

function isNullableTimestamp(value: unknown): value is string | null {
  return value === null || isTimestamp(value);
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 1;
}

function isNullablePositiveInteger(value: unknown): value is number | null {
  return value === null || isPositiveInteger(value);
}

function isNullableNonnegativeInteger(value: unknown): value is number | null {
  return value === null || isNonnegativeInteger(value);
}

function isNullableNonnegativeNumber(value: unknown): value is number | null {
  return (
    value === null ||
    (typeof value === 'number' && Number.isFinite(value) && value >= 0)
  );
}

function isNullableEnum(value: unknown, allowed: ReadonlySet<string>): boolean {
  return value === null || (typeof value === 'string' && allowed.has(value));
}
