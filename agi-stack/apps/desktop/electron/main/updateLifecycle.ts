export const UPDATE_LIFECYCLE_SCHEMA_VERSION = 2 as const;

export type UpdateLifecyclePhase =
  | 'disabled'
  | 'idle'
  | 'checking'
  | 'available'
  | 'not_available'
  | 'downloading'
  | 'downloaded'
  | 'applying'
  | 'verifying'
  | 'recovered'
  | 'failed';

export type UpdateLifecycleAction = 'check' | 'restart_to_apply';

export type UpdateLifecycleState = Readonly<{
  schemaVersion: typeof UPDATE_LIFECYCLE_SCHEMA_VERSION;
  phase: UpdateLifecyclePhase;
  currentVersion: string;
  candidateVersion: string | null;
  recoveryVersion: string | null;
  progress: number | null;
  reasonCode: string | null;
  retryable: boolean;
  allowedActions: readonly UpdateLifecycleAction[];
}>;

const phases = new Set<UpdateLifecyclePhase>([
  'disabled',
  'idle',
  'checking',
  'available',
  'not_available',
  'downloading',
  'downloaded',
  'applying',
  'verifying',
  'recovered',
  'failed',
]);
const actions = new Set<UpdateLifecycleAction>(['check', 'restart_to_apply']);
const stateKeys = Object.freeze([
  'schemaVersion',
  'phase',
  'currentVersion',
  'candidateVersion',
  'recoveryVersion',
  'progress',
  'reasonCode',
  'retryable',
  'allowedActions',
]);
const versionPattern = /^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/u;
const reasonCodePattern = /^[a-z][a-z0-9_]{2,127}$/u;

export function validUpdateVersion(value: unknown): value is string {
  return typeof value === 'string' && value.length <= 128 && versionPattern.test(value);
}

export function validUpdateReasonCode(value: unknown): value is string {
  return typeof value === 'string' && reasonCodePattern.test(value);
}

export function validUpdateAction(value: unknown): value is UpdateLifecycleAction {
  return actions.has(value as UpdateLifecycleAction);
}

export function createUpdateLifecycleState(
  input: Omit<UpdateLifecycleState, 'schemaVersion'>,
): UpdateLifecycleState {
  return parseUpdateLifecycleState({
    schemaVersion: UPDATE_LIFECYCLE_SCHEMA_VERSION,
    ...input,
  });
}

export function parseUpdateLifecycleState(value: unknown): UpdateLifecycleState {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('update lifecycle state is invalid');
  }
  const record = value as Record<string, unknown>;
  const allowedActions = record.allowedActions;
  if (
    Object.keys(record).length !== stateKeys.length ||
    Object.keys(record).some((key) => !stateKeys.includes(key)) ||
    record.schemaVersion !== UPDATE_LIFECYCLE_SCHEMA_VERSION ||
    !phases.has(record.phase as UpdateLifecyclePhase) ||
    !validUpdateVersion(record.currentVersion) ||
    !(record.candidateVersion === null || validUpdateVersion(record.candidateVersion)) ||
    !(record.recoveryVersion === null || validUpdateVersion(record.recoveryVersion)) ||
    !(
      record.progress === null ||
      (typeof record.progress === 'number' &&
        Number.isFinite(record.progress) &&
        record.progress >= 0 &&
        record.progress <= 100)
    ) ||
    !(record.reasonCode === null || validUpdateReasonCode(record.reasonCode)) ||
    typeof record.retryable !== 'boolean' ||
    !Array.isArray(allowedActions) ||
    allowedActions.length > actions.size ||
    allowedActions.some((action) => !validUpdateAction(action)) ||
    new Set(allowedActions).size !== allowedActions.length
  ) {
    throw new Error('update lifecycle state is invalid');
  }
  return Object.freeze({
    schemaVersion: UPDATE_LIFECYCLE_SCHEMA_VERSION,
    phase: record.phase as UpdateLifecyclePhase,
    currentVersion: record.currentVersion,
    candidateVersion: record.candidateVersion as string | null,
    recoveryVersion: record.recoveryVersion as string | null,
    progress: record.progress as number | null,
    reasonCode: record.reasonCode as string | null,
    retryable: record.retryable,
    allowedActions: Object.freeze([...(allowedActions as UpdateLifecycleAction[])]),
  });
}
