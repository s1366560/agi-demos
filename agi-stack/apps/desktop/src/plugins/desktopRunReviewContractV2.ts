import { DesktopApiError } from '../api/client';
import type { ChangeSnapshot, DesktopRuntimeConfig, RunSummary } from '../types';
import {
  parseRunChanges,
  parseRunSummary,
} from '../features/agent-authority/agentAuthorityContract';
import { desktopChangeSnapshotFromCloud } from '../features/agent-authority/agentAuthorityProjection';
export type DesktopRunReviewIdentityV2 = Readonly<{
  id: string;
  tenant_id: string;
  project_id: string;
  workspace_id: string | null;
}>;
export type DesktopRunChangesScopeV2 = Readonly<{
  scope?: 'turn' | 'run' | 'session';
  turnId?: string;
}>;
export function runReviewErrorV2(code: string, status = 422): DesktopApiError {
  return new DesktopApiError(code, status, { code, reason_code: code });
}
export function checkRunReviewAbortV2(signal: AbortSignal): void {
  if (!(signal instanceof AbortSignal)) throw runReviewErrorV2('desktop_run_review_signal_invalid');
  signal.throwIfAborted();
}
export function prepareRunReviewRequestV2(
  config: DesktopRuntimeConfig,
  identity: DesktopRunReviewIdentityV2,
  runId: string,
  signal: AbortSignal,
): void {
  checkRunReviewAbortV2(signal);
  if (
    !record(identity) ||
    ![identity.id, identity.tenant_id, identity.project_id, runId].every(identifier)
  )
    throw runReviewErrorV2('desktop_run_review_identity_invalid');
  if (
    config.projectId !== identity.project_id ||
    config.tenantId !== identity.tenant_id ||
    (config.workspaceId.trim() || null) !== identity.workspace_id
  )
    throw runReviewErrorV2('desktop_run_review_scope_mismatch', 409);
}
export function prepareRunChangesScopeV2(
  config: DesktopRuntimeConfig,
  revision: number,
  options: DesktopRunChangesScopeV2 = {},
): Readonly<{ scope: 'turn' | 'run' | 'session'; turnId?: string }> {
  const scope = options.scope ?? 'run';
  if (
    !record(options) ||
    !['turn', 'run', 'session'].includes(scope) ||
    !Number.isSafeInteger(revision) ||
    revision < (config.mode === 'cloud' ? 1 : 0) ||
    (options.turnId !== undefined && !identifier(options.turnId)) ||
    (scope === 'turn' && !identifier(options.turnId)) ||
    (scope !== 'turn' && options.turnId !== undefined)
  )
    throw runReviewErrorV2('desktop_run_changes_request_invalid');
  return Object.freeze({
    scope,
    ...(options.turnId === undefined ? {} : { turnId: options.turnId }),
  });
}
export function requireRunReviewSummaryV2(
  raw: unknown,
  identity: DesktopRunReviewIdentityV2,
  runId: string,
): RunSummary {
  const summary = parseRunSummary(
    raw,
    {
      authority: 'cloud',
      principalId: '',
      tenantId: identity.tenant_id,
      projectId: identity.project_id,
    },
    runId,
  );
  if (summary.conversation_id !== identity.id)
    throw runReviewErrorV2('desktop_run_summary_conversation_mismatch', 409);
  return freezeRunReviewJsonV2(summary);
}
export function requireRunReviewChangesV2(
  raw: unknown,
  config: DesktopRuntimeConfig,
  identity: DesktopRunReviewIdentityV2,
  runId: string,
  revision: number,
  options: DesktopRunChangesScopeV2 = {},
): ChangeSnapshot {
  if (
    !record(raw) ||
    raw.run_id !== runId ||
    raw.conversation_id !== identity.id ||
    raw.run_revision !== revision
  )
    throw runReviewErrorV2('desktop_run_changes_identity_mismatch', 409);
  const scope = prepareRunChangesScopeV2(config, revision, options);
  if (config.mode === 'cloud')
    return freezeRunReviewJsonV2(
      desktopChangeSnapshotFromCloud(
        parseRunChanges(raw, runId, {
          scope: scope.scope,
          expected_revision: revision,
          ...(scope.turnId === undefined ? {} : { turn_id: scope.turnId }),
        }),
      ),
    );
  if (
    !identifier(raw.id) ||
    !['ready', 'unavailable', 'failed', 'unattributed'].includes(String(raw.status)) ||
    !['additions', 'deletions', 'files_changed'].every((key) => nonnegative(raw[key])) ||
    typeof raw.truncated !== 'boolean' ||
    typeof raw.captured_at !== 'string' ||
    !Number.isFinite(Date.parse(raw.captured_at)) ||
    !Array.isArray(raw.files) ||
    raw.files.length !== raw.files_changed
  )
    throw runReviewErrorV2('desktop_local_run_changes_contract_invalid', 502);
  for (const key of [
    'environment_id',
    'repository_root',
    'workspace_path',
    'branch',
    'base_revision',
    'head_revision',
    'reason',
  ])
    if (raw[key] !== null && raw[key] !== undefined && typeof raw[key] !== 'string')
      throw runReviewErrorV2('desktop_local_run_changes_contract_invalid', 502);
  for (const file of raw.files) validateLocalFile(file);
  return freezeRunReviewJsonV2(raw) as ChangeSnapshot;
}
function validateLocalFile(value: unknown): void {
  if (
    !record(value) ||
    !identifier(value.path) ||
    !(value.old_path === null || typeof value.old_path === 'string') ||
    !identifier(value.status) ||
    !nonnegative(value.additions) ||
    !nonnegative(value.deletions) ||
    typeof value.binary !== 'boolean' ||
    typeof value.untracked !== 'boolean' ||
    !identifier(value.patch_digest) ||
    !Array.isArray(value.hunks)
  )
    throw runReviewErrorV2('desktop_local_run_changes_contract_invalid', 502);
  for (const hunk of value.hunks) {
    if (
      !record(hunk) ||
      typeof hunk.header !== 'string' ||
      !nonnegative(hunk.old_start) ||
      !nonnegative(hunk.new_start) ||
      !Array.isArray(hunk.lines)
    )
      throw runReviewErrorV2('desktop_local_run_changes_contract_invalid', 502);
    for (const line of hunk.lines)
      if (
        !record(line) ||
        !['context', 'addition', 'deletion'].includes(String(line.kind)) ||
        !(line.old_line === null || nonnegative(line.old_line)) ||
        !(line.new_line === null || nonnegative(line.new_line)) ||
        typeof line.text !== 'string'
      )
        throw runReviewErrorV2('desktop_local_run_changes_contract_invalid', 502);
  }
}
export function freezeRunReviewJsonV2<T>(value: T): T {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean' ||
    (typeof value === 'number' && Number.isFinite(value))
  )
    return value;
  if (Array.isArray(value))
    return Object.freeze(value.map((item) => freezeRunReviewJsonV2(item))) as T;
  if (record(value))
    return Object.freeze(
      Object.fromEntries(
        Object.entries(value).map(([key, item]) => [key, freezeRunReviewJsonV2(item)]),
      ),
    ) as T;
  throw runReviewErrorV2('desktop_run_review_json_invalid', 502);
}
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function identifier(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}
function nonnegative(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}
// The operations boundary checks the normalized snapshot, independently of its transport provider.
export function requireRunReviewSnapshotIdentityV2(
  value: unknown,
  config: DesktopRuntimeConfig,
  identity: DesktopRunReviewIdentityV2,
  runId: string,
  revision: number,
  options: DesktopRunChangesScopeV2 = {},
): ChangeSnapshot {
  if (
    !record(value) ||
    !identifier(value.id) ||
    value.run_id !== runId ||
    value.conversation_id !== identity.id ||
    value.run_revision !== revision
  )
    throw runReviewErrorV2('desktop_run_changes_identity_mismatch', 409);
  const request = prepareRunChangesScopeV2(config, revision, options);
  if (
    config.mode === 'cloud' &&
    (value.scope !== request.scope ||
      value.turn_id !== (request.turnId ?? null) ||
      !identifier(value.snapshot_revision))
  )
    throw runReviewErrorV2('desktop_run_changes_scope_mismatch', 409);
  return freezeRunReviewJsonV2(value) as ChangeSnapshot;
}
