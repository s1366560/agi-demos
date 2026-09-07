import { DesktopApiError } from '../../api/client';
import type {
  ActivityReadEntry,
  ActivityReadState,
  ActivityAuthorityScope,
  CloudAgentAuthorityScope,
  GetRunChangesOptions,
  ProjectMyWorkResponse,
  ProjectWorkItem,
  RunChangeAttribution,
  RunChangeFile,
  RunChangeHunk,
  RunChangeLine,
  RunChanges,
  RunSummary,
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
