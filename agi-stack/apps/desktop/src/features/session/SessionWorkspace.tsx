import { useEffect, useRef, useState, type ReactNode } from 'react';
import { AlertDialog, Badge, Button } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  CheckCircledIcon,
  ClockIcon,
  CodeIcon,
  CommitIcon,
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
  SessionInspector,
  type SessionInspectorEvidence,
} from './SessionInspector';
import {
  defaultSessionCanvasTab,
  type SessionCanvasTabId,
} from './sessionCanvasModel';
import {
  nextSessionSurface,
  sessionSurfacePanes,
  type SessionSurface,
} from './sessionLayoutModel';
import type { SessionCanvasControls } from './workspaceReviewPanelModel';
import {
  sessionRecoveryPresentation,
  sessionStatusPresentation,
  type SessionDetailViewModel,
  type SessionRunAction,
  type SessionStage,
} from './sessionViewModel';
import './SessionWorkspace.css';

type SessionWorkspaceProps = {
  viewModel: SessionDetailViewModel;
  thread: ReactNode;
  canvas: ReactNode | ((controls: SessionCanvasControls) => ReactNode) | null;
  evidence: SessionInspectorEvidence;
  onOpenCanvas: (tab?: SessionCanvasTabId) => void;
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

export function SessionWorkspace({
  viewModel,
  thread,
  canvas,
  evidence,
  onOpenCanvas,
  onCloseCanvas,
  runActionPending,
  liveConnected,
  liveError,
  onRunAction,
}: SessionWorkspaceProps) {
  const { t } = useI18n();
  const hasCanvas = Boolean(canvas);
  const [surface, setSurface] = useState<SessionSurface>('conversation');
  const [reviewFeedbackOpen, setReviewFeedbackOpen] = useState(false);
  const [reviewFeedback, setReviewFeedback] = useState('');
  const [recoveryConfirmOpen, setRecoveryConfirmOpen] = useState(false);
  const canvasTriggerRef = useRef<string | null>(null);
  const statusPresentation = sessionStatusPresentation(viewModel.status);
  const runActions = viewModel.runActions;
  const reattachPresentation = sessionRecoveryPresentation('reconnect');
  const forkPresentation = sessionRecoveryPresentation('fork');
  const actionDisabled = runActionPending !== null || viewModel.runRevision === null;

  const panes = sessionSurfacePanes(surface, hasCanvas);
  const showStatusBanner =
    statusPresentation !== null &&
    (surface !== 'conversation' || statusPresentation.tone !== 'attention');

  useEffect(() => {
    setSurface((current) => nextSessionSurface(current, 'select_session'));
  }, [viewModel.id]);

  useEffect(() => {
    if (!hasCanvas) {
      setSurface((current) => nextSessionSurface(current, 'close_canvas'));
    }
  }, [hasCanvas]);

  useEffect(() => {
    if (viewModel.status !== 'ready_review') {
      setReviewFeedbackOpen(false);
      setReviewFeedback('');
    }
  }, [viewModel.status]);

  const openCanvas = (tab?: SessionCanvasTabId) => {
    if (typeof document !== 'undefined' && document.activeElement instanceof HTMLElement) {
      canvasTriggerRef.current =
        document.activeElement.dataset.sessionCanvasTrigger ?? canvasTriggerRef.current;
    }
    setSurface((current) => nextSessionSurface(current, 'open_canvas'));
    onOpenCanvas(tab ?? defaultSessionCanvasTab(viewModel.status, viewModel.capabilityMode));
  };

  const closeCanvas = () => {
    const triggerId = canvasTriggerRef.current;
    setSurface((current) => nextSessionSurface(current, 'close_canvas'));
    onCloseCanvas();
    if (triggerId && typeof window !== 'undefined') {
      window.requestAnimationFrame(() => {
        const triggers = document.querySelectorAll<HTMLButtonElement>(
          '[data-session-canvas-trigger]',
        );
        for (const trigger of triggers) {
          if (trigger.dataset.sessionCanvasTrigger !== triggerId) continue;
          trigger.focus();
          break;
        }
      });
    }
  };

  const canvasControls: SessionCanvasControls = {
    layout: surface === 'canvas' ? 'focus' : 'split',
    onLayoutChange: (layout) => {
      setSurface((current) =>
        nextSessionSurface(current, layout === 'focus' ? 'focus_canvas' : 'show_split'),
      );
    },
    onClose: closeCanvas,
  };
  const canvasContent = typeof canvas === 'function' ? canvas(canvasControls) : canvas;

  return (
    <section
      className={`session-workspace-shell ${showStatusBanner ? 'has-status-banner' : ''}`}
      aria-label={t('session.detail')}
    >
      <header className="session-workspace-header">
        <div className="session-workspace-identity">
          <span>
            {viewModel.workspaceLabel ?? t('session.notAvailable')} / {t('session.session')}
          </span>
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
              <Badge color={executionModeColor(viewModel.executionMode)} variant="soft">
                {executionModeLabel(viewModel.executionMode, t)}
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
          <div className="session-workspace-header-runtime">
            {viewModel.environmentLabel ? (
              <span title={viewModel.environmentLabel}>
                <DesktopIcon /> {viewModel.environmentLabel}
              </span>
            ) : null}
            {viewModel.branchLabel ? (
              <span title={viewModel.branchLabel}>
                <CodeIcon /> {viewModel.branchLabel}
              </span>
            ) : null}
            {viewModel.elapsedLabel ? (
              <span>
                <ClockIcon /> {viewModel.elapsedLabel}
              </span>
            ) : null}
          </div>
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
                      <dd title={viewModel.environmentLabel ?? undefined}>
                        {viewModel.environmentLabel ?? t('session.notAvailable')}
                      </dd>
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
        </div>
      </header>

      {showStatusBanner && statusPresentation ? (
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

      <div className={`session-workspace-body surface-${surface}`}>
        {panes.thread ? (
          <section className="session-workspace-thread" aria-label={t('session.thread')}>
            <div className="session-pane-label">
              <span>
                <ActivityLogIcon /> {t('session.thread')}
              </span>
              <em title={liveError ?? undefined}>
                {liveConnected ? t('session.live') : t('session.liveReconnecting')}
              </em>
              {surface === 'conversation' ? (
                <button
                  type="button"
                  data-session-canvas-trigger="default"
                  aria-label={t('session.openCanvas')}
                  title={t('session.openCanvas')}
                  onClick={() => openCanvas()}
                >
                  <ReaderIcon />
                </button>
              ) : null}
            </div>
            {thread}
          </section>
        ) : null}
        {panes.inspector ? (
          <SessionInspector viewModel={viewModel} evidence={evidence} onOpenCanvas={openCanvas} />
        ) : null}
        {panes.canvas && canvasContent ? (
          <aside className="session-workspace-canvas" aria-label={t('session.canvas')}>
            {canvasContent}
          </aside>
        ) : null}
      </div>
    </section>
  );
}

function executionModeColor(mode: Exclude<SessionDetailViewModel['executionMode'], 'unavailable'>) {
  if (mode === 'plan') return 'amber' as const;
  if (mode === 'explore') return 'gray' as const;
  return 'green' as const;
}

function executionModeLabel(
  mode: Exclude<SessionDetailViewModel['executionMode'], 'unavailable'>,
  t: (key: string) => string,
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
