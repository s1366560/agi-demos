import type { SessionRunAction } from '../session/sessionViewModel';

export type RunControlState = 'planning' | 'running' | 'paused' | 'stopped';
export type RunDotTone = RunControlState | 'completed' | 'failed' | 'idle';
export const runControlLabels: Record<RunControlState, string> = {
  planning: 'Planning',
  running: 'Running',
  paused: 'Paused',
  stopped: 'Stopped',
};
const runControlStates = new Set<RunControlState>([
  'planning',
  'running',
  'paused',
  'stopped',
]);
export function isRunControlState(value: string): value is RunControlState {
  return runControlStates.has(value as RunControlState);
}

export function runToneFromStatus(status: string): RunDotTone {
  const normalized = status.trim().toLowerCase();
  if (isRunControlState(normalized)) return normalized;
  if (
    normalized === 'completed' ||
    normalized === 'complete' ||
    normalized === 'done'
  ) {
    return 'completed';
  }
  if (normalized === 'failed' || normalized === 'error') return 'failed';
  if (normalized === 'active') return 'running';
  return 'idle';
}

export function runLabelFromStatus(status: string): string {
  const normalized = status.trim().toLowerCase();
  if (isRunControlState(normalized)) return runControlLabels[normalized];
  if (normalized === 'active') return 'Running';
  if (
    normalized === 'completed' ||
    normalized === 'complete' ||
    normalized === 'done'
  ) {
    return 'Completed';
  }
  if (normalized === 'failed' || normalized === 'error') return 'Failed';
  return status;
}

export function runStatusLabel(
  state: RunControlState | undefined,
  fallback: string,
): string {
  return state ? runControlLabels[state] : runLabelFromStatus(fallback);
}

export function titlebarRunStateFromStatus(status: string): RunControlState {
  const normalized = status.trim().toLowerCase();
  if (normalized === 'queued') return 'planning';
  if (normalized === 'running' || normalized === 'active') return 'running';
  if (
    normalized === 'needs_input' ||
    normalized === 'needs_approval' ||
    normalized === 'paused' ||
    normalized === 'interrupted'
  ) {
    return 'paused';
  }
  if (normalized === 'ready_review' || normalized === 'completed')
    return 'stopped';
  if (
    normalized === 'failed' ||
    normalized === 'disconnected' ||
    normalized === 'cancelled'
  ) {
    return 'stopped';
  }
  return 'stopped';
}

export function titlebarRunLabelFromStatus(
  status: string,
  translate: (key: string) => string,
): string {
  const normalized = status.trim().toLowerCase();
  const labels: Record<string, string> = {
    active: 'session.statusActive',
    queued: 'session.statusQueued',
    running: 'session.statusRunning',
    needs_input: 'session.statusNeedsInput',
    needs_approval: 'session.statusNeedsApproval',
    paused: 'session.statusPaused',
    ready_review: 'session.statusReadyReview',
    completed: 'session.statusCompleted',
    failed: 'session.statusFailed',
    interrupted: 'session.statusInterrupted',
    disconnected: 'session.statusDisconnected',
    cancelled: 'session.statusCancelled',
  };
  return labels[normalized]
    ? translate(labels[normalized])
    : runLabelFromStatus(status);
}

export type RuntimeTarget = 'local' | 'staging';
export const runtimeTargetLabels: Record<RuntimeTarget, string> = {
  local: 'Local Rust Core',
  staging: 'Staging Runtime',
};
export const titlebarRuntimeTargetLabels: Record<RuntimeTarget, string> = {
  local: 'Local Rust Core',
  staging: 'Remote staging',
};
export const runtimeTargetComposerOptions = Object.values(runtimeTargetLabels);
export type RuntimeHealthState =
  | 'healthy'
  | 'starting'
  | 'waiting'
  | 'offline'
  | 'error';
export const runtimeHealthLabels: Record<RuntimeHealthState, string> = {
  healthy: 'Healthy',
  starting: 'Starting',
  waiting: 'Waiting',
  offline: 'Offline',
  error: 'Error',
};
export const runtimeHealthBadgeColors: Record<
  RuntimeHealthState,
  'gray' | 'blue' | 'green' | 'red'
> = {
  healthy: 'green',
  starting: 'blue',
  waiting: 'gray',
  offline: 'gray',
  error: 'red',
};

export const SESSION_RUN_ACTION_LABEL_KEY: Readonly<
  Record<SessionRunAction, string>
> = {
  pause: 'session.pauseRun',
  resume: 'session.resumeRun',
  cancel: 'session.cancelAction',
  reconnect: 'session.reconnectRun',
  fork: 'session.forkRecovery',
  request_changes: 'session.requestChanges',
  approve: 'session.approveRun',
};
