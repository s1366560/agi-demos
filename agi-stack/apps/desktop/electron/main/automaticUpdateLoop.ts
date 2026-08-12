import type { AppUpdater } from 'electron-updater';

import {
  createUpdateLifecycleState,
  type UpdateLifecycleAction,
  type UpdateLifecycleState,
  validUpdateVersion,
} from './updateLifecycle';
import {
  createUpdateRecoveryCoordinator,
  type UpdateRecoveryCoordinator,
} from './updateRecoveryCoordinator';
import type {
  UpdateRecoveryJournal,
  UpdateRecoveryPayload,
  UpdateRecoveryRecord,
  UpdateRecoverySnapshot,
} from './updateRecoveryJournal';

const DEFAULT_UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1_000;

type UpdateEvent =
  | 'checking-for-update'
  | 'update-available'
  | 'update-not-available'
  | 'download-progress'
  | 'update-downloaded'
  | 'error';

type UpdateClient = Pick<
  AppUpdater,
  | 'autoDownload'
  | 'autoInstallOnAppQuit'
  | 'checkForUpdatesAndNotify'
  | 'quitAndInstall'
  | 'on'
  | 'removeListener'
>;

type IntervalHandle = ReturnType<typeof setInterval>;

type AutomaticUpdateLoopOptions = {
  currentVersion: string;
  journal?: UpdateRecoveryJournal;
  intervalMs?: number;
  now?: () => Date;
  randomNonce?: () => string;
  candidateProcessId?: () => number;
  recoveryWindowMs?: number;
  launchRecoveryHelper?: (record: UpdateRecoveryRecord) => void;
  prepareRecoverySnapshot?: (input: Readonly<{
    currentVersion: string;
    candidateVersion: string;
  }>) => UpdateRecoverySnapshot | Promise<UpdateRecoverySnapshot>;
  clearRecoverySnapshot?: () => void;
  schedule?: (callback: () => void, intervalMs: number) => IntervalHandle;
  cancel?: (handle: IntervalHandle) => void;
  report?: (message: string) => void;
};

export type AutomaticUpdateController = Readonly<{
  getState(): UpdateLifecycleState;
  check(): Promise<void>;
  restartToApply(): void;
  confirmHealthy(): void;
  subscribe(listener: (state: UpdateLifecycleState) => void): () => void;
  stop(): void;
}>;

function candidateVersion(input: unknown): string | null {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return null;
  const version = (input as Record<string, unknown>).version;
  return validUpdateVersion(version) ? version : null;
}

function progress(input: unknown): number | null {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return null;
  const percent = (input as Record<string, unknown>).percent;
  if (typeof percent !== 'number' || !Number.isFinite(percent)) return null;
  return Math.min(100, Math.max(0, percent));
}

function recoveryPayloads(input: unknown): readonly UpdateRecoveryPayload[] | null {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return null;
  const files = (input as Record<string, unknown>).files;
  if (!Array.isArray(files) || files.length === 0 || files.length > 8) return null;
  const payloads: UpdateRecoveryPayload[] = [];
  for (const candidate of files) {
    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) return null;
    const record = candidate as Record<string, unknown>;
    const size = record.size;
    if (typeof record.sha512 !== 'string' || typeof size !== 'number' || !Number.isSafeInteger(size) || size <= 0) {
      return null;
    }
    const digest = Buffer.from(record.sha512, 'base64');
    if (digest.byteLength !== 64 || digest.toString('base64') !== record.sha512) return null;
    payloads.push(Object.freeze({ sha512: record.sha512, size }));
  }
  if (new Set(payloads.map(({ sha512 }) => sha512)).size !== payloads.length) return null;
  return Object.freeze(payloads);
}

function recoveryState(
  record: UpdateRecoveryRecord,
  actualCurrentVersion: string,
): UpdateLifecycleState {
  return createUpdateLifecycleState({
    phase: record.phase,
    currentVersion: actualCurrentVersion,
    candidateVersion: record.candidateVersion,
    recoveryVersion: record.recoveryVersion,
    progress: record.phase === 'downloaded' ? 100 : null,
    reasonCode: record.reasonCode,
    retryable: record.retryable,
    allowedActions: record.allowedActions,
  });
}

export function startAutomaticUpdateLoop(
  updateClient: UpdateClient,
  options: AutomaticUpdateLoopOptions,
): AutomaticUpdateController {
  const report =
    options.report ??
    ((message: string) => {
      process.stderr.write(`${message}\n`);
    });
  const now = options.now ?? (() => new Date());
  const listeners = new Set<(state: UpdateLifecycleState) => void>();
  const ownedUpdateListeners = new Map<UpdateEvent, (...args: unknown[]) => void>();
  const recovery: UpdateRecoveryCoordinator | null = options.journal
    ? createUpdateRecoveryCoordinator(options.journal, {
        now,
        randomNonce: options.randomNonce,
        candidateProcessId: options.candidateProcessId,
        recoveryWindowMs: options.recoveryWindowMs,
        launchRecoveryHelper: options.launchRecoveryHelper,
      })
    : null;
  let recoveryRecord: UpdateRecoveryRecord | null = null;
  let recoveryInvalid = false;
  try {
    recoveryRecord = recovery?.loadForStartup(options.currentVersion) ?? null;
  } catch {
    recoveryInvalid = true;
  }
  let state = recoveryRecord
    ? recoveryState(recoveryRecord, options.currentVersion)
    : createUpdateLifecycleState({
        phase: recoveryInvalid ? 'failed' : 'idle',
        currentVersion: options.currentVersion,
        candidateVersion: null,
        recoveryVersion: null,
        progress: null,
        reasonCode: recoveryInvalid ? 'update_recovery_journal_invalid' : null,
        retryable: recoveryInvalid,
        allowedActions: recoveryInvalid ? ['check'] : ['check'],
      });
  let stopped = false;

  const transition = (
    patch: Partial<Omit<UpdateLifecycleState, 'schemaVersion' | 'currentVersion'>>,
  ): void => {
    if (stopped) return;
    state = createUpdateLifecycleState({
      phase: patch.phase ?? state.phase,
      currentVersion: state.currentVersion,
      candidateVersion:
        patch.candidateVersion === undefined ? state.candidateVersion : patch.candidateVersion,
      recoveryVersion:
        patch.recoveryVersion === undefined ? state.recoveryVersion : patch.recoveryVersion,
      progress: patch.progress === undefined ? state.progress : patch.progress,
      reasonCode: patch.reasonCode === undefined ? state.reasonCode : patch.reasonCode,
      retryable: patch.retryable ?? state.retryable,
      allowedActions: patch.allowedActions ?? state.allowedActions,
    });
    for (const listener of listeners) listener(state);
  };
  const fail = (
    reasonCode: string,
    retryable = true,
    allowedActions: readonly UpdateLifecycleAction[] = retryable ? ['check'] : [],
  ): void => {
    transition({ phase: 'failed', reasonCode, retryable, allowedActions, progress: null });
  };

  const handlers: Readonly<Record<UpdateEvent, (...args: unknown[]) => void>> = {
    'checking-for-update': () =>
      transition({
        phase: 'checking',
        progress: null,
        reasonCode: null,
        retryable: false,
        allowedActions: [],
      }),
    'update-available': (input) => {
      const version = candidateVersion(input);
      if (!version) {
        fail('update_available_contract_invalid', false);
        return;
      }
      transition({
        phase: 'available',
        candidateVersion: version,
        recoveryVersion: state.currentVersion,
        progress: 0,
        reasonCode: null,
        retryable: false,
        allowedActions: [],
      });
    },
    'update-not-available': () => {
      try {
        recovery?.clear();
        transition({
          phase: 'not_available',
          candidateVersion: null,
          recoveryVersion: null,
          progress: null,
          reasonCode: null,
          retryable: false,
          allowedActions: ['check'],
        });
      } catch {
        fail('update_recovery_journal_clear_failed', true);
      }
    },
    'download-progress': (input) => {
      const percent = progress(input);
      if (percent === null) {
        fail('update_download_progress_contract_invalid', false);
        return;
      }
      transition({
        phase: 'downloading',
        progress: percent,
        reasonCode: null,
        retryable: false,
        allowedActions: [],
      });
    },
    'update-downloaded': (input) => {
      const version = candidateVersion(input) ?? state.candidateVersion;
      const payloads = recoveryPayloads(input);
      if (!version || !payloads) {
        fail('update_downloaded_contract_invalid', false);
        return;
      }
      if (!recovery) {
        fail('update_recovery_unavailable', false);
        return;
      }
      const prepareRecoverySnapshot = options.prepareRecoverySnapshot;
      if (!prepareRecoverySnapshot) {
        fail('update_recovery_unavailable', false);
        return;
      }
      transition({
        phase: 'verifying',
        progress: 100,
        reasonCode: null,
        retryable: false,
        allowedActions: [],
      });
      void Promise.resolve(
        prepareRecoverySnapshot({ currentVersion: state.currentVersion, candidateVersion: version }),
      )
        .then((snapshot) => {
          if (stopped || state.candidateVersion !== version) return;
          recoveryRecord = recovery.recordDownloaded({
            currentVersion: state.currentVersion,
            candidateVersion: version,
            payloads,
            snapshot,
          });
          state = recoveryState(recoveryRecord, state.currentVersion);
          for (const listener of listeners) listener(state);
        })
        .catch(() => fail('update_recovery_snapshot_failed', false));
    },
    error: () => {
      report('automatic update operation failed');
      fail('update_operation_failed', true);
    },
  };
  for (const [event, listener] of Object.entries(handlers) as [
    UpdateEvent,
    (...args: unknown[]) => void,
  ][]) {
    ownedUpdateListeners.set(event, listener);
    updateClient.on(event, listener);
  }

  const controller: AutomaticUpdateController = Object.freeze({
    getState: () => state,
    async check(): Promise<void> {
      if (stopped) throw new Error('automatic update controller is stopped');
      if (!state.allowedActions.includes('check')) {
        throw new Error('update check is not allowed in the current state');
      }
      try {
        recovery?.clear();
      } catch {
        fail('update_recovery_journal_clear_failed', true);
        return;
      }
      transition({
        phase: 'checking',
        candidateVersion: null,
        recoveryVersion: null,
        progress: null,
        reasonCode: null,
        retryable: false,
        allowedActions: [],
      });
      try {
        await updateClient.checkForUpdatesAndNotify();
      } catch {
        report('automatic update check failed');
        fail('update_check_failed', true);
      }
    },
    restartToApply(): void {
      if (stopped) throw new Error('automatic update controller is stopped');
      if (!state.allowedActions.includes('restart_to_apply') || !recovery) {
        throw new Error('update is not ready to apply');
      }
      const applying = recovery.restartToApply();
      state = recoveryState(applying, state.currentVersion);
      for (const listener of listeners) listener(state);
      try {
        updateClient.quitAndInstall(false, true);
      } catch {
        const failed = recovery.markFailed('update_install_start_failed', true);
        state = recoveryState(failed, state.currentVersion);
        for (const listener of listeners) listener(state);
        throw new Error('update install could not start');
      }
    },
    confirmHealthy(): void {
      if (stopped) throw new Error('automatic update controller is stopped');
      if (state.phase !== 'verifying' || !recoveryRecord || !recovery) return;
      const recovered = recovery.confirmHealthy({
        currentVersion: state.currentVersion,
        nonce: recoveryRecord.nonce,
      });
      recoveryRecord = recovered;
      state = recoveryState(recovered, state.currentVersion);
      for (const listener of listeners) listener(state);
      try {
        options.clearRecoverySnapshot?.();
      } catch {
        report('automatic update recovery snapshot cleanup failed');
      }
    },
    subscribe(listener: (nextState: UpdateLifecycleState) => void): () => void {
      if (typeof listener !== 'function') throw new Error('update state listener is invalid');
      listeners.add(listener);
      listener(state);
      return () => listeners.delete(listener);
    },
    stop(): void {
      if (stopped) return;
      stopped = true;
      (options.cancel ?? clearInterval)(interval);
      for (const [event, listener] of ownedUpdateListeners) {
        updateClient.removeListener(event, listener);
      }
      ownedUpdateListeners.clear();
      listeners.clear();
    },
  });

  updateClient.autoDownload = true;
  updateClient.autoInstallOnAppQuit = false;
  const schedule = options.schedule ?? setInterval;
  const interval = schedule(
    () => {
      if (controller.getState().allowedActions.includes('check')) void controller.check();
    },
    options.intervalMs ?? DEFAULT_UPDATE_CHECK_INTERVAL_MS,
  );
  interval.unref?.();
  if (!recoveryRecord && !recoveryInvalid) void controller.check();
  return controller;
}
