import { useI18n } from '../../i18n';
import type { SessionCanvasTabId } from './sessionCanvasModel';
import type { SessionDetailViewModel, SessionRunAction, SessionStage } from './sessionViewModel';
import { executionModeLabel, statusLabel } from './SessionWorkspace';
import './SessionContextRail.css';

type SessionContextRailProps = {
  viewModel: SessionDetailViewModel;
  runActionPending: SessionRunAction | null;
  onRunAction: (action: SessionRunAction, feedback?: string) => void;
  onOpenCanvas: (tab?: SessionCanvasTabId) => void;
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
