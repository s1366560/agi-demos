import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  DesktopRun,
  DesktopRuntimeConfig,
  ForkRecoveryOutcome,
  ReviewRunRequest,
  RunControlOutcome,
} from '../types';
import { cloneRuntimeConfigV2, isPlainRecordV2 } from './desktopNewTaskFlowContractV2';

export type DesktopSessionRunControlIdentityV2 = Readonly<{
  tenant_id: string;
  project_id: string;
  session_id: string;
}>;

export type DesktopRunTransitionKindV2 = 'pause' | 'resume' | 'cancel';

export type DesktopRunTransitionCommandV2 =
  | Readonly<{
      kind: 'pause';
      runId: string;
      expectedRevision: number;
    }>
  | Readonly<{
      kind: 'resume';
      runId: string;
      expectedRevision: number;
    }>
  | Readonly<{
      kind: 'cancel';
      runId: string;
      expectedRevision: number;
    }>;

export type DesktopRunForkCommandV2 = Readonly<{
  kind: 'fork';
  runId: string;
  expectedRevision: number;
  idempotencyKey: string;
}>;

export type DesktopRunReviewCommandV2 = Readonly<{
  kind: 'review';
  runId: string;
  input: ReviewRunRequest;
}>;

export type DesktopRunControlCommandV2 =
  | DesktopRunTransitionCommandV2
  | DesktopRunForkCommandV2
  | DesktopRunReviewCommandV2;

const RUN_STATUSES_V2 = new Set([
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
const REVIEW_INPUT_KEYS_V2 = new Set(['action', 'expectedRevision', 'feedback']);
const MAX_JSON_DEPTH_V2 = 32;

export function cloneSessionRunControlRuntimeConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  try {
    return cloneRuntimeConfigV2(config);
  } catch {
    throw sessionRunControlInputInvalidV2();
  }
}

export function cloneSessionRunControlIdentityV2(
  value: unknown,
): DesktopSessionRunControlIdentityV2 {
  if (
    !isPlainRecordV2(value) ||
    hasUnexpectedKeysV2(value, new Set(['tenant_id', 'project_id', 'session_id'])) ||
    !isCanonicalIdentifierV2(value.tenant_id) ||
    !isCanonicalIdentifierV2(value.project_id) ||
    !isCanonicalIdentifierV2(value.session_id)
  ) {
    throw sessionRunControlInputInvalidV2();
  }
  return Object.freeze({
    tenant_id: value.tenant_id,
    project_id: value.project_id,
    session_id: value.session_id,
  });
}

export function assertSessionRunControlScopeV2(
  config: DesktopRuntimeConfig,
  identity: DesktopSessionRunControlIdentityV2,
): void {
  if (config.tenantId !== identity.tenant_id || config.projectId !== identity.project_id) {
    throw new RuntimeV2Error(
      'desktop_session_run_control_scope_mismatch',
      'desktop session run-control operation differs from its configured scope',
    );
  }
}

export function cloneRunTransitionCommandV2(
  kind: unknown,
  runId: unknown,
  expectedRevision: unknown,
): DesktopRunTransitionCommandV2 {
  if (
    (kind !== 'pause' && kind !== 'resume' && kind !== 'cancel') ||
    !isCanonicalIdentifierV2(runId) ||
    !isRevisionV2(expectedRevision)
  ) {
    throw sessionRunControlInputInvalidV2();
  }
  return Object.freeze({ kind, runId, expectedRevision });
}

export function cloneRunForkCommandV2(
  runId: unknown,
  expectedRevision: unknown,
  idempotencyKey: unknown,
): DesktopRunForkCommandV2 {
  if (
    !isCanonicalIdentifierV2(runId) ||
    !isRevisionV2(expectedRevision) ||
    !isIdempotencyKeyV2(idempotencyKey)
  ) {
    throw sessionRunControlInputInvalidV2();
  }
  return Object.freeze({
    kind: 'fork',
    runId,
    expectedRevision,
    idempotencyKey,
  });
}

export function cloneRunReviewCommandV2(
  runId: unknown,
  input: unknown,
): DesktopRunReviewCommandV2 {
  if (
    !isCanonicalIdentifierV2(runId) ||
    !isPlainRecordV2(input) ||
    hasUnexpectedKeysV2(input, REVIEW_INPUT_KEYS_V2) ||
    !isRevisionV2(input.expectedRevision) ||
    (input.action !== 'approve' && input.action !== 'request_changes')
  ) {
    throw sessionRunControlInputInvalidV2();
  }
  if (input.action === 'approve') {
    if (input.feedback !== undefined) throw sessionRunControlInputInvalidV2();
    return Object.freeze({
      kind: 'review',
      runId,
      input: Object.freeze({
        action: 'approve',
        expectedRevision: input.expectedRevision,
      }),
    });
  }
  if (!isCanonicalTextV2(input.feedback, 4_000)) {
    throw sessionRunControlInputInvalidV2();
  }
  return Object.freeze({
    kind: 'review',
    runId,
    input: Object.freeze({
      action: 'request_changes',
      expectedRevision: input.expectedRevision,
      feedback: input.feedback,
    }),
  });
}

export function assertRunControlOutcomeV2(
  value: unknown,
  config: DesktopRuntimeConfig,
  identity: DesktopSessionRunControlIdentityV2,
  command: DesktopRunTransitionCommandV2 | DesktopRunReviewCommandV2,
): RunControlOutcome {
  if (!isPlainRecordV2(value) || value.accepted !== true || typeof value.status !== 'string') {
    throw sessionRunControlResponseInvalidV2();
  }
  const run = cloneRunV2(value.run);
  assertRunIdentityV2(run, config, identity, command.runId);
  if (!matchesRunControlOutcomeV2(command, value.status, run)) {
    throw sessionRunControlResponseInvalidV2();
  }
  return deepFreezeV2({
    accepted: true,
    status: value.status,
    run,
  }) as RunControlOutcome;
}

export function assertForkRecoveryOutcomeV2(
  value: unknown,
  config: DesktopRuntimeConfig,
  identity: DesktopSessionRunControlIdentityV2,
  command: DesktopRunForkCommandV2,
): ForkRecoveryOutcome {
  if (
    !isPlainRecordV2(value) ||
    value.accepted !== true ||
    typeof value.created !== 'boolean' ||
    !RUN_STATUSES_V2.has(String(value.status))
  ) {
    throw sessionRunControlResponseInvalidV2();
  }
  const sourceRun = cloneRunV2(value.source_run);
  const run = cloneRunV2(value.run);
  assertRunIdentityV2(sourceRun, config, identity, command.runId);
  if (
    (sourceRun.status !== 'disconnected' && sourceRun.status !== 'interrupted') ||
    sourceRun.revision !== command.expectedRevision ||
    run.id === sourceRun.id ||
    run.conversation_id !== identity.session_id ||
    run.project_id !== config.projectId ||
    run.idempotency_key !== command.idempotencyKey ||
    run.status !== value.status
  ) {
    throw sessionRunControlResponseInvalidV2();
  }
  return deepFreezeV2({
    accepted: true,
    created: value.created,
    status: value.status,
    source_run: sourceRun,
    run,
  }) as ForkRecoveryOutcome;
}

export function sessionRunControlInputInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_session_run_control_input_invalid',
    'desktop session run-control authority received invalid input',
  );
}

function sessionRunControlResponseInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_session_run_control_response_invalid',
    'desktop session run-control authority returned an invalid response',
  );
}

function matchesRunControlOutcomeV2(
  command: DesktopRunTransitionCommandV2 | DesktopRunReviewCommandV2,
  status: string,
  run: DesktopRun,
): boolean {
  if (command.kind === 'pause') {
    return (
      status === 'pause_requested' &&
      run.status === 'running' &&
      run.revision === command.expectedRevision
    );
  }
  if (command.kind === 'resume') {
    return (
      (status === 'running' &&
        run.status === 'running' &&
        run.revision === command.expectedRevision + 1) ||
      (status === 'restart_requested' &&
        run.status === 'interrupted' &&
        run.revision === command.expectedRevision)
    );
  }
  if (command.kind === 'cancel') {
    return (
      (status === 'cancel_requested' &&
        run.status === 'running' &&
        run.revision === command.expectedRevision) ||
      (status === 'cancelled' &&
        run.status === 'cancelled' &&
        run.revision === command.expectedRevision + 1)
    );
  }
  const expectedStatus = command.input.action === 'approve' ? 'completed' : 'running';
  return (
    status === expectedStatus &&
    run.status === expectedStatus &&
    run.revision === command.input.expectedRevision + 1
  );
}

function cloneRunV2(value: unknown): DesktopRun {
  if (
    !isPlainRecordV2(value) ||
    !isCanonicalIdentifierV2(value.id) ||
    !isCanonicalIdentifierV2(value.conversation_id) ||
    !isCanonicalIdentifierV2(value.project_id) ||
    !isOptionalIdentifierV2(value.plan_version_id) ||
    !isCanonicalTextV2(value.idempotency_key, 256) ||
    !isCanonicalIdentifierV2(value.message_id) ||
    typeof value.request_message !== 'string' ||
    !RUN_STATUSES_V2.has(String(value.status)) ||
    !isRevisionV2(value.revision) ||
    !isCanonicalTextV2(value.created_at, 256) ||
    !isCanonicalTextV2(value.updated_at, 256) ||
    !isPlainRecordV2(value.authorization_snapshot) ||
    !isOptionalTextV2(value.started_at) ||
    !isOptionalTextV2(value.completed_at) ||
    !isOptionalTextV2(value.last_heartbeat_at) ||
    !isOptionalTextV2(value.error)
  ) {
    throw sessionRunControlResponseInvalidV2();
  }
  return deepFreezeV2(cloneJsonValueV2(value, new Set<object>(), 0)) as DesktopRun;
}

function assertRunIdentityV2(
  run: DesktopRun,
  config: DesktopRuntimeConfig,
  identity: DesktopSessionRunControlIdentityV2,
  runId: string,
): void {
  if (
    run.id !== runId ||
    run.conversation_id !== identity.session_id ||
    run.project_id !== config.projectId
  ) {
    throw sessionRunControlResponseInvalidV2();
  }
}

function cloneJsonValueV2(value: unknown, ancestors: Set<object>, depth: number): unknown {
  if (depth > MAX_JSON_DEPTH_V2) throw sessionRunControlResponseInvalidV2();
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw sessionRunControlResponseInvalidV2();
    return value;
  }
  if (
    typeof value !== 'object' ||
    value === null ||
    ancestors.has(value) ||
    (!Array.isArray(value) && !isPlainRecordV2(value))
  ) {
    throw sessionRunControlResponseInvalidV2();
  }
  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      return value.map((item) => cloneJsonValueV2(item, ancestors, depth + 1));
    }
    const copy: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) {
      if (item === undefined) throw sessionRunControlResponseInvalidV2();
      copy[key] = cloneJsonValueV2(item, ancestors, depth + 1);
    }
    return copy;
  } finally {
    ancestors.delete(value);
  }
}

function deepFreezeV2<T>(value: T): T {
  if (Array.isArray(value)) {
    for (const item of value) deepFreezeV2(item);
    return Object.freeze(value);
  }
  if (isPlainRecordV2(value)) {
    for (const item of Object.values(value)) deepFreezeV2(item);
    return Object.freeze(value) as T;
  }
  return value;
}

function hasUnexpectedKeysV2(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
): boolean {
  return Object.keys(value).some((key) => !allowed.has(key));
}

function isRevisionV2(value: unknown): value is number {
  return (
    Number.isSafeInteger(value) &&
    Number(value) >= 0 &&
    Number(value) < Number.MAX_SAFE_INTEGER
  );
}

function isCanonicalIdentifierV2(value: unknown): value is string {
  return (
    typeof value === 'string' && value.length > 0 && value.length <= 256 && value === value.trim()
  );
}

function isCanonicalTextV2(value: unknown, maximumLength: number): value is string {
  return (
    typeof value === 'string' &&
    value.length > 0 &&
    value.length <= maximumLength &&
    value === value.trim()
  );
}

function isOptionalIdentifierV2(value: unknown): boolean {
  return value === null || isCanonicalIdentifierV2(value);
}

function isOptionalTextV2(value: unknown): boolean {
  return value === undefined || value === null || isCanonicalTextV2(value, 4_000);
}

function isIdempotencyKeyV2(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length >= 8 &&
    value.length <= 256 &&
    value === value.trim() &&
    [...value].every((character) => {
      const code = character.charCodeAt(0);
      return code >= 33 && code <= 126;
    })
  );
}
