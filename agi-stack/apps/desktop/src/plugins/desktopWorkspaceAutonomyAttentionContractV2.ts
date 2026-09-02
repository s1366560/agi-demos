import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  DesktopRuntimeConfig,
  WorkspaceAutonomyAttention,
  WorkspaceAutonomyAttentionResolveResponse,
  WorkspaceAutonomyAttentionRetryResponse,
  WorkspaceAutonomyAttentionSourceKind,
} from '../types';

const ATTENTION_KEYS_V2 = new Set([
  'attention_id',
  'created_at_ms',
  'reason',
  'root_task_id',
  'source_id',
  'source_kind',
  'status',
]);
const ATTENTION_SOURCE_KINDS_V2 = new Set<WorkspaceAutonomyAttentionSourceKind>([
  'judge_block',
  'judge_escalate',
  'progression_dead_letter',
  'bootstrap_dead_letter',
  'task_dispatch_dead_letter',
]);
const RETRY_RESPONSE_KEYS_V2 = new Set(['attention_id', 'status']);
const RESOLVE_RESPONSE_KEYS_V2 = new Set([
  'attention_id',
  'committed_revision',
  'replayed',
  'status',
]);

export function cloneWorkspaceAutonomyAttentionRuntimeConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw workspaceAutonomyAttentionInputInvalidV2();
  const copy: DesktopRuntimeConfig = {
    apiBaseUrl: config.apiBaseUrl,
    deviceAuthorizationBaseUrl: config.deviceAuthorizationBaseUrl,
    apiKey: config.apiKey,
    localApiToken: config.localApiToken,
    tenantId: config.tenantId,
    projectId: config.projectId,
    workspaceId: config.workspaceId,
    mode: config.mode,
    workspaceRoot: config.workspaceRoot,
  };
  if (
    Object.values(copy).some((value) => typeof value !== 'string') ||
    (copy.mode !== 'cloud' && copy.mode !== 'local') ||
    !isCanonicalIdentifierV2(copy.apiBaseUrl) ||
    !isCanonicalIdentifierV2(copy.tenantId) ||
    !isCanonicalIdentifierV2(copy.projectId) ||
    !isCanonicalIdentifierV2(copy.workspaceId)
  ) {
    throw workspaceAutonomyAttentionInputInvalidV2();
  }
  return Object.freeze(copy);
}

export function cloneWorkspaceAutonomyAttentionWorkspaceIdV2(
  config: DesktopRuntimeConfig,
  workspaceId: unknown,
): string {
  if (!isCanonicalIdentifierV2(workspaceId) || workspaceId !== config.workspaceId) {
    throw workspaceAutonomyAttentionInputInvalidV2();
  }
  return workspaceId;
}

export function cloneWorkspaceAutonomyAttentionActorIdV2(actorId: unknown): string {
  if (!isCanonicalIdentifierV2(actorId)) throw workspaceAutonomyAttentionInputInvalidV2();
  return actorId;
}

export function cloneWorkspaceAutonomyAttentionIdV2(attentionId: unknown): string {
  if (!isCanonicalIdentifierV2(attentionId)) {
    throw workspaceAutonomyAttentionInputInvalidV2();
  }
  return attentionId;
}

export function cloneWorkspaceAutonomyAttentionExpectedRevisionV2(
  value: unknown,
): number | null {
  if (value === null) return null;
  if (!isUnsignedSafeIntegerV2(value)) throw workspaceAutonomyAttentionInputInvalidV2();
  return value;
}

export function cloneWorkspaceAutonomyAttentionIdempotencyKeyV2(value: unknown): string {
  if (
    !isCanonicalIdentifierV2(value) ||
    value.length < 16 ||
    value.length > 256
  ) {
    throw workspaceAutonomyAttentionInputInvalidV2();
  }
  return value;
}

export function cloneWorkspaceAutonomyAttentionSignalV2(
  value: unknown,
): AbortSignal | undefined {
  if (value === undefined) return undefined;
  if (typeof AbortSignal === 'undefined' || !(value instanceof AbortSignal)) {
    throw workspaceAutonomyAttentionInputInvalidV2();
  }
  return value;
}

export function assertWorkspaceAutonomyAttentionSignalV2(
  expected: AbortSignal | undefined,
  actual: AbortSignal | undefined,
): void {
  if (actual !== expected) throw workspaceAutonomyAttentionInputInvalidV2();
}

export function cloneWorkspaceAutonomyAttentionsV2(
  value: unknown,
): WorkspaceAutonomyAttention[] {
  if (!Array.isArray(value)) throw workspaceAutonomyAttentionResponseInvalidV2();
  const seenIds = new Set<string>();
  const attentions = value.map((candidate) => {
    if (
      !isPlainRecordV2(candidate) ||
      !hasExactKeysV2(candidate, ATTENTION_KEYS_V2) ||
      !isCanonicalIdentifierV2(candidate.attention_id) ||
      seenIds.has(candidate.attention_id) ||
      (candidate.root_task_id !== null &&
        !isCanonicalIdentifierV2(candidate.root_task_id)) ||
      typeof candidate.source_kind !== 'string' ||
      !ATTENTION_SOURCE_KINDS_V2.has(
        candidate.source_kind as WorkspaceAutonomyAttentionSourceKind,
      ) ||
      !isCanonicalIdentifierV2(candidate.source_id) ||
      !isCanonicalIdentifierV2(candidate.reason) ||
      candidate.status !== 'open' ||
      !isUnsignedSafeIntegerV2(candidate.created_at_ms)
    ) {
      throw workspaceAutonomyAttentionResponseInvalidV2();
    }
    seenIds.add(candidate.attention_id);
    return Object.freeze({
      attention_id: candidate.attention_id,
      root_task_id: candidate.root_task_id,
      source_kind: candidate.source_kind as WorkspaceAutonomyAttentionSourceKind,
      source_id: candidate.source_id,
      reason: candidate.reason,
      status: 'open' as const,
      created_at_ms: candidate.created_at_ms,
    });
  });
  return Object.freeze(attentions) as unknown as WorkspaceAutonomyAttention[];
}

export function cloneWorkspaceAutonomyAttentionRevisionV2(value: unknown): number {
  if (!isUnsignedSafeIntegerV2(value)) {
    throw workspaceAutonomyAttentionResponseInvalidV2();
  }
  return value;
}

export function cloneWorkspaceAutonomyAttentionRetryResponseV2(
  value: unknown,
  attentionId: string,
): WorkspaceAutonomyAttentionRetryResponse {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, RETRY_RESPONSE_KEYS_V2) ||
    value.attention_id !== attentionId ||
    value.status !== 'retry_queued'
  ) {
    throw workspaceAutonomyAttentionResponseInvalidV2();
  }
  return Object.freeze({ attention_id: attentionId, status: 'retry_queued' as const });
}

export function cloneWorkspaceAutonomyAttentionResolveResponseV2(
  value: unknown,
  attentionId: string,
): WorkspaceAutonomyAttentionResolveResponse {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, RESOLVE_RESPONSE_KEYS_V2) ||
    value.attention_id !== attentionId ||
    value.status !== 'resolved' ||
    !isUnsignedSafeIntegerV2(value.committed_revision) ||
    typeof value.replayed !== 'boolean'
  ) {
    throw workspaceAutonomyAttentionResponseInvalidV2();
  }
  return Object.freeze({
    attention_id: attentionId,
    status: 'resolved' as const,
    committed_revision: value.committed_revision,
    replayed: value.replayed,
  });
}

export function workspaceAutonomyAttentionInputInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_autonomy_attention_input_invalid',
    'desktop workspace autonomy-attention operation input is invalid',
  );
}

export function workspaceAutonomyAttentionResponseInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_autonomy_attention_response_invalid',
    'desktop workspace autonomy-attention response is invalid',
  );
}

export function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

export function hasExactOptionalKeysV2(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
}

function hasExactKeysV2(
  value: Record<string, unknown>,
  expected: ReadonlySet<string>,
): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function isCanonicalIdentifierV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isUnsignedSafeIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}
