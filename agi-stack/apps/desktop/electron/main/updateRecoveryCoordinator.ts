import { randomBytes } from 'node:crypto';

import type {
  UpdateRecoveryJournal,
  UpdateRecoveryPayload,
  UpdateRecoveryRecord,
  UpdateRecoverySnapshot,
} from './updateRecoveryJournal';

const DEFAULT_RECOVERY_WINDOW_MS = 5 * 60 * 1_000;
const MAX_LAUNCH_ATTEMPTS = 3;

type UpdateRecoveryCoordinatorOptions = Readonly<{
  now?: () => Date;
  randomNonce?: () => string;
  recoveryWindowMs?: number;
  launchRecoveryHelper?: (record: UpdateRecoveryRecord) => void;
}>;

export type UpdateRecoveryCoordinator = Readonly<{
  loadForStartup(currentVersion: string): UpdateRecoveryRecord | null;
  recordDownloaded(input: Readonly<{
    currentVersion: string;
    candidateVersion: string;
    payloads: readonly UpdateRecoveryPayload[];
    snapshot: UpdateRecoverySnapshot;
  }>): UpdateRecoveryRecord;
  restartToApply(): UpdateRecoveryRecord;
  confirmHealthy(input: Readonly<{
    currentVersion: string;
    nonce: string;
  }>): UpdateRecoveryRecord;
  markFailed(reasonCode: string, retryable: boolean): UpdateRecoveryRecord;
  clear(): void;
}>;

function freezeRecord(input: UpdateRecoveryRecord): UpdateRecoveryRecord {
  return Object.freeze({
    ...input,
    payloads: Object.freeze(input.payloads.map((payload) => Object.freeze({ ...payload }))),
    snapshot: Object.freeze({ ...input.snapshot }),
    allowedActions: Object.freeze([...input.allowedActions]),
  });
}

function failedRecord(
  record: UpdateRecoveryRecord,
  reasonCode: string,
  retryable: boolean,
  recordedAt: string,
): UpdateRecoveryRecord {
  return freezeRecord({
    ...record,
    phase: 'failed',
    recordedAt,
    reasonCode,
    retryable,
    allowedActions: retryable ? ['restart_to_apply'] : [],
  });
}

export function createUpdateRecoveryCoordinator(
  journal: UpdateRecoveryJournal,
  options: UpdateRecoveryCoordinatorOptions = {},
): UpdateRecoveryCoordinator {
  const now = options.now ?? (() => new Date());
  const randomNonce = options.randomNonce ?? (() => randomBytes(32).toString('hex'));
  const recoveryWindowMs = options.recoveryWindowMs ?? DEFAULT_RECOVERY_WINDOW_MS;
  if (!Number.isSafeInteger(recoveryWindowMs) || recoveryWindowMs < 10_000 || recoveryWindowMs > 3_600_000) {
    throw new Error('update recovery window is invalid');
  }

  const write = (record: UpdateRecoveryRecord): UpdateRecoveryRecord => {
    const frozen = freezeRecord(record);
    journal.write(frozen);
    return frozen;
  };
  const fail = (
    record: UpdateRecoveryRecord,
    reasonCode: string,
    retryable: boolean,
  ): UpdateRecoveryRecord => write(failedRecord(record, reasonCode, retryable, now().toISOString()));

  return Object.freeze({
    loadForStartup(currentVersion: string): UpdateRecoveryRecord | null {
      const record = journal.load();
      if (!record) return null;
      if (record.phase === 'downloaded' || record.phase === 'failed') return record;
      if (record.phase === 'recovered') {
        return currentVersion === record.currentVersion
          ? record
          : fail(record, 'update_recovered_version_mismatch', false);
      }
      if (now().getTime() > new Date(record.deadlineAt).getTime()) {
        return fail(
          record,
          'update_recovery_deadline_expired',
          record.launchAttempts < MAX_LAUNCH_ATTEMPTS,
        );
      }
      if (currentVersion === record.candidateVersion) {
        return write({
          ...record,
          phase: 'verifying',
          currentVersion,
          recordedAt: now().toISOString(),
          reasonCode: null,
          retryable: false,
          allowedActions: [],
        });
      }
      if (currentVersion === record.recoveryVersion) {
        return fail(
          record,
          'update_apply_not_observed',
          record.launchAttempts < MAX_LAUNCH_ATTEMPTS,
        );
      }
      return fail(record, 'update_recovery_version_mismatch', false);
    },
    recordDownloaded({ currentVersion, candidateVersion, payloads, snapshot }): UpdateRecoveryRecord {
      const recordedAt = now();
      return write({
        schemaVersion: 2,
        phase: 'downloaded',
        currentVersion,
        candidateVersion,
        recoveryVersion: currentVersion,
        nonce: randomNonce(),
        deadlineAt: new Date(recordedAt.getTime() + recoveryWindowMs).toISOString(),
        launchAttempts: 0,
        payloads,
        snapshot,
        recordedAt: recordedAt.toISOString(),
        reasonCode: null,
        retryable: false,
        allowedActions: ['restart_to_apply'],
      });
    },
    restartToApply(): UpdateRecoveryRecord {
      const record = journal.load();
      if (
        !record ||
        (record.phase !== 'downloaded' && !(record.phase === 'failed' && record.retryable))
      ) {
        throw new Error('update is not ready to apply');
      }
      if (record.launchAttempts >= MAX_LAUNCH_ATTEMPTS) {
        fail(record, 'update_recovery_launch_attempts_exhausted', false);
        throw new Error('update recovery launch attempts are exhausted');
      }
      const recordedAt = now();
      const applying = write({
        ...record,
        phase: 'applying',
        nonce: randomNonce(),
        deadlineAt: new Date(recordedAt.getTime() + recoveryWindowMs).toISOString(),
        launchAttempts: record.launchAttempts + 1,
        recordedAt: recordedAt.toISOString(),
        reasonCode: null,
        retryable: false,
        allowedActions: [],
      });
      try {
        options.launchRecoveryHelper?.(applying);
      } catch {
        fail(applying, 'update_recovery_helper_launch_failed', true);
        throw new Error('update recovery helper could not start');
      }
      return applying;
    },
    confirmHealthy({ currentVersion, nonce }): UpdateRecoveryRecord {
      const record = journal.load();
      if (!record || record.phase !== 'verifying') {
        throw new Error('update recovery is not awaiting health verification');
      }
      if (record.nonce !== nonce) throw new Error('update recovery health nonce mismatch');
      if (now().getTime() > new Date(record.deadlineAt).getTime()) {
        fail(
          record,
          'update_recovery_deadline_expired',
          record.launchAttempts < MAX_LAUNCH_ATTEMPTS,
        );
        throw new Error('update recovery health deadline expired');
      }
      if (currentVersion !== record.candidateVersion) {
        fail(record, 'update_recovery_health_version_mismatch', false);
        throw new Error('update recovery health version mismatch');
      }
      return write({
        ...record,
        phase: 'recovered',
        currentVersion,
        recordedAt: now().toISOString(),
        reasonCode: null,
        retryable: false,
        allowedActions: ['check'],
      });
    },
    markFailed(reasonCode: string, retryable: boolean): UpdateRecoveryRecord {
      const record = journal.load();
      if (!record) throw new Error('update recovery record is unavailable');
      return fail(record, reasonCode, retryable && record.launchAttempts < MAX_LAUNCH_ATTEMPTS);
    },
    clear(): void {
      journal.clear();
    },
  });
}
