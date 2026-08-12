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

export type UpdateLifecycleState = Readonly<{
  schemaVersion: 2;
  phase: UpdateLifecyclePhase;
  currentVersion: string;
  candidateVersion: string | null;
  recoveryVersion: string | null;
  progress: number | null;
  reasonCode: string | null;
  retryable: boolean;
  allowedActions: readonly ('check' | 'restart_to_apply')[];
}>;

export type UpdatePresentation = Readonly<{
  phaseKey: `settings.updatesPhase.${UpdateLifecyclePhase}`;
  reasonKey: string | null;
  progress: number | null;
  tone: 'neutral' | 'progress' | 'success' | 'danger';
}>;

const reasonKeys = new Map<string, string>([
  ['production_update_feed_disabled', 'settings.updatesReason.feedDisabled'],
  ['updates_externally_managed', 'settings.updatesReason.externallyManaged'],
  ['update_available_contract_invalid', 'settings.updatesReason.contractInvalid'],
  ['update_download_progress_contract_invalid', 'settings.updatesReason.contractInvalid'],
  ['update_downloaded_contract_invalid', 'settings.updatesReason.contractInvalid'],
  ['update_recovery_unavailable', 'settings.updatesReason.recoveryUnavailable'],
  ['update_recovery_snapshot_failed', 'settings.updatesReason.recoverySnapshotFailed'],
  ['update_recovery_restore_failed', 'settings.updatesReason.recoveryRestoreFailed'],
  ['update_recovery_journal_invalid', 'settings.updatesReason.recoveryJournalInvalid'],
  ['update_recovery_journal_write_failed', 'settings.updatesReason.recoveryJournalWriteFailed'],
  ['update_recovery_journal_clear_failed', 'settings.updatesReason.recoveryJournalWriteFailed'],
  ['update_recovery_helper_launch_failed', 'settings.updatesReason.recoveryHelperLaunchFailed'],
  ['update_recovery_deadline_expired', 'settings.updatesReason.healthDeadlineExpired'],
  ['update_recovery_launch_attempts_exhausted', 'settings.updatesReason.recoveryAttemptsExhausted'],
  ['update_recovered_version_mismatch', 'settings.updatesReason.versionMismatch'],
  ['update_recovery_version_mismatch', 'settings.updatesReason.versionMismatch'],
  ['update_recovery_health_version_mismatch', 'settings.updatesReason.versionMismatch'],
  ['update_apply_not_observed', 'settings.updatesReason.applyNotObserved'],
  ['update_install_start_failed', 'settings.updatesReason.installStartFailed'],
  ['update_operation_failed', 'settings.updatesReason.operationFailed'],
  ['update_check_failed', 'settings.updatesReason.checkFailed'],
]);

export function updateLifecyclePresentation(state: UpdateLifecycleState): UpdatePresentation {
  const progress =
    state.progress === null ? null : Math.max(0, Math.min(100, state.progress));
  const tone =
    state.phase === 'failed'
      ? 'danger'
      : state.phase === 'recovered'
        ? 'success'
        : ['checking', 'available', 'downloading', 'downloaded', 'applying', 'verifying'].includes(
              state.phase,
            )
          ? 'progress'
          : 'neutral';
  return Object.freeze({
    phaseKey: `settings.updatesPhase.${state.phase}`,
    reasonKey:
      state.reasonCode === null
        ? null
        : (reasonKeys.get(state.reasonCode) ?? 'settings.updatesReason.unknown'),
    progress,
    tone,
  });
}
