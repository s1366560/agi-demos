import { useEffect, useState, type ReactNode } from 'react';
import { AlertDialog, Badge, Button } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  CheckCircledIcon,
  ClockIcon,
  CodeIcon,
  ColumnsIcon,
  CommitIcon,
  Cross1Icon,
  DesktopIcon,
  ExclamationTriangleIcon,
  PauseIcon,
  Pencil2Icon,
  PlayIcon,
  ReaderIcon,
  ReloadIcon,
  StopIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import {
  sessionRecoveryPresentation,
  sessionStatusPresentation,
  sessionRunActions,
  type SessionDetailViewModel,
  type SessionRunAction,
  type SessionStage,
} from './sessionViewModel';
import './SessionWorkspace.css';

type SessionWorkspaceProps = {
  viewModel: SessionDetailViewModel;
  thread: ReactNode;
  canvas: ReactNode | null;
  onOpenCanvas: () => void;
  onCloseCanvas: () => void;
  runActionPending: SessionRunAction | null;
  liveConnected: boolean;
  liveError: string | null;
  onRunAction: (action: SessionRunAction, feedback?: string) => void;
};

const stageLabels: Array<{ id: Exclude<SessionStage, 'unavailable'>; label: string }> = [
  { id: 'understand', label: 'session.stageUnderstand' },
  { id: 'implement', label: 'session.stageImplement' },
  { id: 'verify', label: 'session.stageVerify' },
  { id: 'review', label: 'session.stageReview' },
];

type SessionSurface = 'thread' | 'split' | 'canvas';

export function SessionWorkspace({
  viewModel,
  thread,
  canvas,
  onOpenCanvas,
  onCloseCanvas,
  runActionPending,
  liveConnected,
  liveError,
  onRunAction,
}: SessionWorkspaceProps) {
  const { t } = useI18n();
  const hasCanvas = Boolean(canvas);
  const [surface, setSurface] = useState<SessionSurface>('thread');
  const [reviewFeedbackOpen, setReviewFeedbackOpen] = useState(false);
  const [reviewFeedback, setReviewFeedback] = useState('');
  const [recoveryConfirmOpen, setRecoveryConfirmOpen] = useState(false);
  const statusPresentation = sessionStatusPresentation(viewModel.status);
  const runActions = sessionRunActions(viewModel.status);
  const reattachPresentation = sessionRecoveryPresentation('reconnect');
  const forkPresentation = sessionRecoveryPresentation('fork');
  const actionDisabled = runActionPending !== null || viewModel.runRevision === null;

  useEffect(() => {
    setSurface('thread');
  }, [hasCanvas]);

  useEffect(() => {
    if (viewModel.status !== 'ready_review') {
      setReviewFeedbackOpen(false);
      setReviewFeedback('');
    }
  }, [viewModel.status]);

  return (
    <section
      className={`session-workspace-shell ${statusPresentation ? 'has-status-banner' : ''}`}
      aria-label={t('session.detail')}
    >
      <header className="session-workspace-header">
        <div className="session-workspace-identity">
          <span>{viewModel.workspaceLabel} / {t('session.session')}</span>
          <div>
            <h1>{viewModel.title}</h1>
            <Badge color={statusColor(viewModel.status)} variant="soft">
              {statusLabel(viewModel.status, t)}
            </Badge>
            {viewModel.capabilityMode !== 'unavailable' ? (
              <Badge color={viewModel.capabilityMode === 'code' ? 'cyan' : 'gray'} variant="soft">
                {viewModel.capabilityMode === 'code' ? t('session.code') : t('session.work')}
              </Badge>
            ) : null}
            {viewModel.executionMode !== 'unavailable' ? (
              <Badge color={viewModel.executionMode === 'plan' ? 'amber' : 'green'} variant="soft">
                {viewModel.executionMode === 'plan'
                  ? t('session.planMode')
                  : t('session.buildMode')}
              </Badge>
            ) : null}
          </div>
        </div>

        {viewModel.stage !== 'unavailable' ? (
          <div className="session-workspace-stages" aria-label={t('session.progress')}>
            {stageLabels.map((stage, index) => {
              const state = stageState(viewModel.stage, stage.id);
              return (
                <div className={state} key={stage.id}>
                  {state === 'complete' ? <CheckCircledIcon /> : <ClockIcon />}
                  <span>
                    <small>0{index + 1}</small>
                    <strong>{t(stage.label)}</strong>
                  </span>
                </div>
              );
            })}
          </div>
        ) : null}

        <div className="session-workspace-actions">
          {runActions.includes('pause') ? (
            <Button
              size="2"
              variant="surface"
              disabled={actionDisabled}
              onClick={() => onRunAction('pause')}
            >
              <PauseIcon />
              {runActionPending === 'pause' ? t('session.pausing') : t('session.pauseRun')}
            </Button>
          ) : null}
          {runActions.includes('resume') ? (
            <Button
              size="2"
              color="green"
              variant="surface"
              disabled={actionDisabled}
              onClick={() => onRunAction('resume')}
            >
              <PlayIcon />
              {runActionPending === 'resume' ? t('session.resuming') : t('session.resumeRun')}
            </Button>
          ) : null}
          {runActions.includes('reconnect') ? (
            <Button
              size="2"
              color="green"
              variant="solid"
              disabled={actionDisabled}
              title={t(reattachPresentation.descriptionKey)}
              onClick={() => onRunAction('reconnect')}
            >
              <ReloadIcon />
              {runActionPending === 'reconnect'
                ? t('session.reconnecting')
                : t(reattachPresentation.labelKey)}
            </Button>
          ) : null}
          {runActions.includes('fork') ? (
            <AlertDialog.Root open={recoveryConfirmOpen} onOpenChange={setRecoveryConfirmOpen}>
              <AlertDialog.Trigger>
                <Button
                  className="session-fork-recovery-trigger"
                  size="2"
                  color="amber"
                  variant="surface"
                  disabled={actionDisabled}
                  title={t(forkPresentation.descriptionKey)}
                >
                  <CommitIcon />
                  {runActionPending === 'fork'
                    ? t('session.forkingRecovery')
                    : t(forkPresentation.labelKey)}
                </Button>
              </AlertDialog.Trigger>
              <AlertDialog.Content className="session-recovery-dialog" maxWidth="500px">
                <div className="session-recovery-dialog-icon" aria-hidden>
                  <CommitIcon />
                </div>
                <AlertDialog.Title>{t(forkPresentation.titleKey)}</AlertDialog.Title>
                <AlertDialog.Description>
                  {t(forkPresentation.descriptionKey)}
                </AlertDialog.Description>

                <ul className="session-recovery-warning-list">
                  {forkPresentation.warnings?.map((warningKey, index) => (
                    <li className={index === 2 ? 'is-warning' : ''} key={warningKey}>
                      {index === 2 ? <ExclamationTriangleIcon /> : <CheckCircledIcon />}
                      <span>{t(warningKey)}</span>
                    </li>
                  ))}
                </ul>

                <section
                  className="session-recovery-context"
                  aria-label={t('session.recoveryContext')}
                >
                  <h3>{t('session.recoveryContext')}</h3>
                  <dl>
                    <div>
                      <dt>{t('session.sourceRun')}</dt>
                      <dd title={viewModel.runId ?? undefined}>{viewModel.runId ?? '—'}</dd>
                    </div>
                    <div>
                      <dt>{t('session.sourceEnvironment')}</dt>
                      <dd title={viewModel.environmentLabel}>{viewModel.environmentLabel}</dd>
                    </div>
                    {viewModel.branchLabel ? (
                      <div>
                        <dt>{t('session.sourceBranch')}</dt>
                        <dd title={viewModel.branchLabel}>{viewModel.branchLabel}</dd>
                      </div>
                    ) : null}
                  </dl>
                </section>

                <div className="session-recovery-dialog-actions">
                  <AlertDialog.Cancel>
                    <Button size="2" variant="soft" color="gray">
                      {t('session.cancelRecovery')}
                    </Button>
                  </AlertDialog.Cancel>
                  <AlertDialog.Action>
                    <Button
                      size="2"
                      color="amber"
                      onClick={() => onRunAction('fork')}
                    >
                      <CommitIcon /> {t('session.confirmForkRecovery')}
                    </Button>
                  </AlertDialog.Action>
                </div>
              </AlertDialog.Content>
            </AlertDialog.Root>
          ) : null}
          {runActions.includes('cancel') ? (
            <Button
              size="2"
              color="red"
              variant="soft"
              disabled={actionDisabled}
              onClick={() => onRunAction('cancel')}
            >
              <StopIcon />
              {runActionPending === 'cancel' ? t('session.stopping') : t('session.stopRun')}
            </Button>
          ) : null}
          {!canvas ? (
            <Button size="2" variant="surface" onClick={onOpenCanvas}>
              <ReaderIcon /> {t('session.openCanvas')}
            </Button>
          ) : null}
        </div>
      </header>

      <div className="session-workspace-context" aria-label={t('session.runContext')}>
        <span title={viewModel.environmentLabel}>
          <DesktopIcon /> {viewModel.environmentLabel}
        </span>
        {viewModel.branchLabel ? (
          <span title={viewModel.branchLabel}>
            <CodeIcon /> {viewModel.branchLabel}
          </span>
        ) : null}
        {viewModel.permissionLabel !== 'Permission policy unavailable' ? (
          <span title={viewModel.permissionLabel}>{viewModel.permissionLabel}</span>
        ) : null}
        {viewModel.modelLabel !== 'Model unavailable' ? (
          <span title={viewModel.modelLabel}>{viewModel.modelLabel}</span>
        ) : null}
        {viewModel.elapsedLabel !== 'Elapsed unavailable' ? <span>{viewModel.elapsedLabel}</span> : null}
        {viewModel.usageLabel !== 'Usage unavailable' ? <span>{viewModel.usageLabel}</span> : null}
        {viewModel.taskCount ? (
          <span>{t('session.taskCount', { count: viewModel.taskCount })}</span>
        ) : null}
        {viewModel.eventCount ? (
          <span>{t('session.eventCount', { count: viewModel.eventCount })}</span>
        ) : null}
        <span
          className={liveConnected ? 'session-live-connected' : 'session-live-reconnecting'}
          title={liveError ?? undefined}
        >
          <i aria-hidden />
          {liveConnected ? t('session.liveConnected') : t('session.liveReconnecting')}
        </span>
        {hasCanvas ? (
          <div className="session-surface-switcher" role="group" aria-label={t('session.layout')}>
            <button
              type="button"
              className={surface === 'thread' ? 'active' : ''}
              aria-pressed={surface === 'thread'}
              onClick={() => setSurface('thread')}
            >
              <ActivityLogIcon /> {t('session.conversation')}
            </button>
            <button
              type="button"
              className={surface === 'split' ? 'active' : ''}
              aria-pressed={surface === 'split'}
              onClick={() => setSurface('split')}
            >
              <ColumnsIcon /> {t('session.splitView')}
            </button>
            <button
              type="button"
              className={surface === 'canvas' ? 'active' : ''}
              aria-pressed={surface === 'canvas'}
              onClick={() => setSurface('canvas')}
            >
              <ReaderIcon /> {t('session.inspector')}
            </button>
          </div>
        ) : null}
      </div>

      {statusPresentation ? (
        <div
          className={`session-workspace-status-banner tone-${statusPresentation.tone}`}
          role={statusPresentation.tone === 'danger' ? 'alert' : 'status'}
        >
          {statusPresentation.tone === 'success' ? (
            <CheckCircledIcon />
          ) : (
            <ExclamationTriangleIcon />
          )}
          <span>
            <strong>{t(statusPresentation.titleKey)}</strong>
            <small>
              {statusPresentation.tone === 'danger' && viewModel.error
                ? viewModel.error
                : t(statusPresentation.descriptionKey)}
            </small>
          </span>
          {runActions.includes('approve') ? (
            <div className="session-status-actions">
              <Button
                size="2"
                variant="surface"
                disabled={actionDisabled}
                onClick={() => setReviewFeedbackOpen(true)}
              >
                <Pencil2Icon /> {t('session.requestChanges')}
              </Button>
              <Button
                size="2"
                color="green"
                disabled={actionDisabled}
                onClick={() => onRunAction('approve')}
              >
                <CheckCircledIcon />
                {runActionPending === 'approve'
                  ? t('session.approvingRun')
                  : t('session.approveRun')}
              </Button>
            </div>
          ) : null}
          {reviewFeedbackOpen && runActions.includes('request_changes') ? (
            <form
              className="session-review-feedback"
              onSubmit={(event) => {
                event.preventDefault();
                const feedback = reviewFeedback.trim();
                if (!feedback) return;
                onRunAction('request_changes', feedback);
              }}
            >
              <label htmlFor="session-review-feedback">{t('session.changeRequestLabel')}</label>
              <textarea
                id="session-review-feedback"
                value={reviewFeedback}
                placeholder={t('session.changeRequestPlaceholder')}
                onChange={(event) => setReviewFeedback(event.target.value)}
              />
              <Button
                size="2"
                type="button"
                variant="ghost"
                disabled={runActionPending !== null}
                onClick={() => setReviewFeedbackOpen(false)}
              >
                {t('session.cancelAction')}
              </Button>
              <Button
                size="2"
                type="submit"
                disabled={!reviewFeedback.trim() || runActionPending !== null}
              >
                {runActionPending === 'request_changes'
                  ? t('session.sendingChanges')
                  : t('session.sendChanges')}
              </Button>
            </form>
          ) : null}
        </div>
      ) : null}

      <div className={`session-workspace-body surface-${surface} ${canvas ? '' : 'canvas-closed'}`}>
        <section className="session-workspace-thread" aria-label={t('session.thread')}>
          <div className="session-pane-label">
            <span><ActivityLogIcon /> {t('session.thread')}</span>
            <small>{t('session.threadDescription')}</small>
          </div>
          {thread}
        </section>
        {canvas ? (
          <aside className="session-workspace-canvas" aria-label={t('session.canvas')}>
            <div className="session-pane-label">
              <span><ReaderIcon /> {t('session.inspector')}</span>
              <small>{t('session.canvasDescription')}</small>
              <button
                type="button"
                aria-label={t('session.closeInspector')}
                title={t('session.closeInspector')}
                onClick={onCloseCanvas}
              >
                <Cross1Icon />
              </button>
            </div>
            {canvas}
          </aside>
        ) : null}
      </div>
    </section>
  );
}

function statusLabel(status: string, t: (key: string) => string): string {
  const normalized = status.trim().toLowerCase();
  const labels: Record<string, string> = {
    active: 'session.statusActive',
    queued: 'session.statusQueued',
    running: 'session.statusRunning',
    completed: 'session.statusCompleted',
    blocked: 'session.statusBlocked',
    needs_input: 'session.statusNeedsInput',
    needs_approval: 'session.statusNeedsApproval',
    paused: 'session.statusPaused',
    ready_review: 'session.statusReadyReview',
    failed: 'session.statusFailed',
    interrupted: 'session.statusInterrupted',
    disconnected: 'session.statusDisconnected',
    cancelled: 'session.statusCancelled',
  };
  return labels[normalized] ? t(labels[normalized]) : status;
}

function statusColor(status: string): 'green' | 'amber' | 'gray' | 'red' {
  if (status === 'active' || status === 'running') return 'green';
  if (status === 'blocked' || status === 'needs_input' || status === 'needs_approval') return 'amber';
  if (status === 'paused') return 'amber';
  if (status === 'ready_review') return 'green';
  if (status === 'failed' || status === 'error' || status === 'disconnected') return 'red';
  return 'gray';
}

function stageState(
  activeStage: SessionStage,
  stage: Exclude<SessionStage, 'unavailable'>,
): 'complete' | 'active' | 'queued' | 'unavailable' {
  if (activeStage === 'unavailable') return 'unavailable';
  const activeIndex = stageLabels.findIndex((item) => item.id === activeStage);
  const stageIndex = stageLabels.findIndex((item) => item.id === stage);
  if (stageIndex < activeIndex) return 'complete';
  if (stageIndex === activeIndex) return 'active';
  return 'queued';
}
