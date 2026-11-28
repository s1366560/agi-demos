import { useI18n } from '../../../../../../agi-stack/apps/desktop/src/i18n';
import type {
  SessionDetailViewModel,
  SessionStage,
} from '../../../../../../agi-stack/apps/desktop/src/features/session/sessionViewModel';

import '../../../../../../agi-stack/apps/desktop/src/features/session/SessionContextRail.css';

type SessionContextRailProps = {
  viewModel: Pick<
    SessionDetailViewModel,
    | 'status'
    | 'stage'
    | 'environmentLabel'
    | 'elapsedLabel'
    | 'executionMode'
    | 'permissionLabel'
    | 'observedToolActivityCount'
    | 'observedFailedToolActivityCount'
    | 'error'
  >;
};

const stageLabels: Record<Exclude<SessionStage, 'unavailable'>, string> = {
  understand: 'session.stageUnderstand',
  implement: 'session.stageImplement',
  verify: 'session.stageVerify',
  review: 'session.stageReview',
};

/** Read-only run details. Actions stay in the conversation's status banner. */
export function SessionContextRail({ viewModel }: SessionContextRailProps) {
  const { t } = useI18n();
  const facts = [
    {
      label: t('myWork.runStatus'),
      value: viewModel.status === 'unavailable' ? null : statusLabel(viewModel.status, t),
    },
    {
      label: t('session.currentStage'),
      value: viewModel.stage === 'unavailable' ? null : t(stageLabels[viewModel.stage]),
    },
    {
      label: t('session.overviewEnvironment'),
      value: viewModel.environmentLabel,
    },
    { label: t('session.elapsed'), value: viewModel.elapsedLabel },
    {
      label: t('session.runMode'),
      value:
        viewModel.executionMode === 'unavailable'
          ? null
          : executionModeLabel(viewModel.executionMode, t),
    },
    { label: t('session.permission'), value: viewModel.permissionLabel },
    {
      label: t('session.loadedToolActivity'),
      value:
        (viewModel.observedToolActivityCount ?? 0) > 0
          ? String(viewModel.observedToolActivityCount)
          : null,
    },
    {
      label: t('session.loadedFailedToolActivity'),
      value:
        (viewModel.observedFailedToolActivityCount ?? 0) > 0
          ? String(viewModel.observedFailedToolActivityCount)
          : null,
    },
  ].filter((fact) => fact.value !== null && fact.value !== '');

  return (
    <aside className="session-context-rail" aria-label={t('session.runContext')}>
      {viewModel.error ? (
        <p className="session-context-error" role="alert">
          {viewModel.error}
        </p>
      ) : null}
      {facts.length > 0 ? (
        <dl className="session-context-facts">
          {facts.map(({ label, value }) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      ) : !viewModel.error ? (
        <p className="session-context-empty">{t('session.dataUnavailableTitle')}</p>
      ) : null}
    </aside>
  );
}

function executionModeLabel(
  mode: Exclude<SessionDetailViewModel['executionMode'], 'unavailable'>,
  t: (key: string) => string
) {
  if (mode === 'plan') return t('session.planMode');
  if (mode === 'explore') return t('session.exploreMode');
  return t('session.buildMode');
}

function statusLabel(status: string, t: (key: string) => string): string {
  const normalized = status.trim().toLowerCase();
  const labels: Record<string, string> = {
    unavailable: 'session.notAvailable',
    active: 'session.statusActive',
    queued: 'session.statusQueued',
    pending: 'session.statusQueued',
    running: 'session.statusRunning',
    completed: 'session.statusCompleted',
    accepted: 'session.statusCompleted',
    blocked: 'session.statusBlocked',
    needs_input: 'session.statusNeedsInput',
    needs_approval: 'session.statusNeedsApproval',
    awaiting_leader_adjudication: 'session.statusNeedsApproval',
    paused: 'session.statusPaused',
    ready_review: 'session.statusReadyReview',
    failed: 'session.statusFailed',
    rejected: 'session.statusFailed',
    interrupted: 'session.statusInterrupted',
    disconnected: 'session.statusDisconnected',
    cancelled: 'session.statusCancelled',
  };
  return t(labels[normalized] ?? 'session.notAvailable');
}
