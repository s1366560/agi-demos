import { useEffect, useRef, useState, type ReactNode } from 'react';
import { AlertDialog, Badge, Button } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  ArchiveIcon,
  CheckCircledIcon,
  ChevronRightIcon,
  ClockIcon,
  CodeIcon,
  CommitIcon,
  DesktopIcon,
  DotsHorizontalIcon,
  ExclamationTriangleIcon,
  LockClosedIcon,
  PauseIcon,
  Pencil2Icon,
  PersonIcon,
  PlayIcon,
  ReaderIcon,
  ReloadIcon,
  StopIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import {
  defaultSessionCanvasTab,
  type SessionCanvasTabId,
} from './sessionCanvasModel';
import {
  sessionSurfaceForSession,
  sessionSurfacePanes,
  transitionSessionSurface,
  type SessionSurfaceAction,
  type SessionSurfaceState,
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
  onOpenCanvas: (tab?: SessionCanvasTabId) => void;
  onCloseCanvas: () => void;
  runActionPending: SessionRunAction | null;
  liveConnected: boolean;
  liveError: string | null;
  onRunAction: (action: SessionRunAction, feedback?: string) => void;
  onOpenTask?: () => void;
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
  onOpenCanvas,
  onCloseCanvas,
  runActionPending,
  liveConnected,
  liveError,
  onRunAction,
  onOpenTask,
}: SessionWorkspaceProps) {
  const { t } = useI18n();
  const hasCanvas = Boolean(canvas);
  const [surfaceState, setSurfaceState] = useState<SessionSurfaceState>(() => ({
    sessionId: viewModel.id,
    surface: 'conversation',
  }));
  const surface = sessionSurfaceForSession(surfaceState, viewModel.id);
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
  const showStatusBanner = statusPresentation !== null && surface !== 'conversation';
  const conversationModePresentation = conversationModeLabel(viewModel.conversationMode, t);
  const evidenceSurface = viewModel.capabilityMode === 'code' ? 'checks' : 'verification';

  const transitionSurface = (action: SessionSurfaceAction) => {
    setSurfaceState((current) => transitionSessionSurface(current, viewModel.id, action));
  };

  useEffect(() => {
    if (!hasCanvas) {
      transitionSurface('close_canvas');
    }
  }, [hasCanvas, viewModel.id]);

  useEffect(() => {
    if (viewModel.status !== 'ready_review') {
      setReviewFeedbackOpen(false);
      setReviewFeedback('');
    }
  }, [viewModel.status]);

  const revealCanvas = () => {
    if (typeof document !== 'undefined' && document.activeElement instanceof HTMLElement) {
      canvasTriggerRef.current =
        document.activeElement.dataset.sessionCanvasTrigger ?? canvasTriggerRef.current;
    }
    transitionSurface('open_canvas');
  };

  const openCanvas = (tab?: SessionCanvasTabId) => {
    revealCanvas();
    onOpenCanvas(tab ?? defaultSessionCanvasTab(viewModel.status, viewModel.capabilityMode));
  };

  const closeCanvas = () => {
    const triggerId = canvasTriggerRef.current;
    transitionSurface('close_canvas');
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
      transitionSurface(layout === 'focus' ? 'focus_canvas' : 'show_split');
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
            {viewModel.workspaceLabel ?? t('session.notAvailable')} <ChevronRightIcon />{' '}
            {t('session.session')}
          </span>
          <div>
            <h1>{viewModel.title}</h1>
            <Badge color={statusColor(viewModel.status)} variant="soft">
              {statusLabel(viewModel.status, t)}
            </Badge>
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
          {viewModel.linkedTaskId && onOpenTask ? (
            <Button size="2" variant="ghost" onClick={onOpenTask}>
              {t('session.openTask')}
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
          <details className="session-workspace-more">
            <summary aria-label={t('session.moreActions')} title={t('session.moreActions')}>
              <DotsHorizontalIcon />
            </summary>
            <div>
              <button type="button" onClick={() => openCanvas('overview')}>
                <ReaderIcon /> {t('session.canvasOverview')}
              </button>
              {runActions.includes('cancel') ? (
                <button
                  type="button"
                  className="danger"
                  disabled={actionDisabled}
                  onClick={() => onRunAction('cancel')}
                >
                  <StopIcon />
                  {runActionPending === 'cancel' ? t('session.stopping') : t('session.stopRun')}
                </button>
              ) : null}
            </div>
          </details>
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
                <ActivityLogIcon /> {t('session.sessionLog')}
              </span>
              {conversationModePresentation ? (
                <small className="session-pane-privacy">
                  <LockClosedIcon /> {conversationModePresentation}
                </small>
              ) : null}
              {viewModel.participantCount !== null ? (
                <small>
                  <PersonIcon />
                  {t('session.participantCount', { count: viewModel.participantCount })}
                </small>
              ) : null}
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
                  {t('session.openCanvas')} <ReaderIcon />
                </button>
              ) : null}
            </div>
            {thread}
          </section>
        ) : null}
        {panes.contextRail ? (
          <aside className="session-context-rail" aria-label={t('session.runContext')}>
            {statusPresentation ? (
              <section className={`session-context-attention tone-${statusPresentation.tone}`}>
                <header>
                  <ExclamationTriangleIcon />
                  <strong>{t(statusPresentation.titleKey)}</strong>
                </header>
                <p>
                  {statusPresentation.tone === 'danger' && viewModel.error
                    ? viewModel.error
                    : t(statusPresentation.descriptionKey)}
                </p>
                <div className="session-context-attention-actions">
                  {runActions.includes('request_changes') ? (
                    <Button
                      size="1"
                      variant="surface"
                      disabled={actionDisabled}
                      onClick={() => setReviewFeedbackOpen(true)}
                    >
                      <Pencil2Icon /> {t('session.requestChanges')}
                    </Button>
                  ) : null}
                  {runActions.includes('approve') ? (
                    <Button
                      size="1"
                      color="green"
                      disabled={actionDisabled}
                      onClick={() => onRunAction('approve')}
                    >
                      <CheckCircledIcon />
                      {runActionPending === 'approve'
                        ? t('session.approvingRun')
                        : t('session.approveRun')}
                    </Button>
                  ) : null}
                  {!runActions.includes('approve') && !runActions.includes('request_changes') ? (
                    <Button size="1" variant="surface" onClick={() => openCanvas('plan')}>
                      {t('session.reviewCanvas')}
                    </Button>
                  ) : null}
                </div>
                {reviewFeedbackOpen && runActions.includes('request_changes') ? (
                  <form
                    className="session-context-feedback"
                    onSubmit={(event) => {
                      event.preventDefault();
                      const feedback = reviewFeedback.trim();
                      if (!feedback) return;
                      onRunAction('request_changes', feedback);
                    }}
                  >
                    <label htmlFor="session-context-review-feedback">
                      {t('session.changeRequestLabel')}
                    </label>
                    <textarea
                      id="session-context-review-feedback"
                      value={reviewFeedback}
                      placeholder={t('session.changeRequestPlaceholder')}
                      onChange={(event) => setReviewFeedback(event.target.value)}
                    />
                    <div>
                      <Button
                        size="1"
                        type="button"
                        variant="ghost"
                        onClick={() => setReviewFeedbackOpen(false)}
                      >
                        {t('session.cancelAction')}
                      </Button>
                      <Button
                        size="1"
                        type="submit"
                        disabled={!reviewFeedback.trim() || runActionPending !== null}
                      >
                        {runActionPending === 'request_changes'
                          ? t('session.sendingChanges')
                          : t('session.sendChanges')}
                      </Button>
                    </div>
                  </form>
                ) : null}
              </section>
            ) : null}

            <section className="session-context-section">
              <h2>{t('session.runSnapshot')}</h2>
              <dl>
                <div>
                  <dt>{t('session.overviewStatus')}</dt>
                  <dd>{statusLabel(viewModel.status, t)}</dd>
                </div>
                <div>
                  <dt>{t('session.conversation')}</dt>
                  <dd>
                    {viewModel.capabilityMode === 'unavailable'
                      ? t('session.notAvailable')
                      : viewModel.capabilityMode === 'code'
                        ? t('session.code')
                        : t('session.work')}
                  </dd>
                </div>
                <div>
                  <dt>{t('session.currentStage')}</dt>
                  <dd>
                    {viewModel.executionMode === 'unavailable'
                      ? t('session.notAvailable')
                      : executionModeLabel(viewModel.executionMode, t)}
                  </dd>
                </div>
                <div>
                  <dt>{t('session.elapsed')}</dt>
                  <dd>{viewModel.elapsedLabel ?? t('session.notAvailable')}</dd>
                </div>
                {viewModel.environmentLabel ? (
                  <div className="wide">
                    <dt>{t('session.overviewEnvironment')}</dt>
                    <dd title={viewModel.environmentLabel}>{viewModel.environmentLabel}</dd>
                  </div>
                ) : null}
              </dl>
            </section>

            <section className="session-context-section session-context-surfaces">
              <h2>{t('session.workSurfaces')}</h2>
              <button
                type="button"
                data-session-canvas-trigger="plan"
                onClick={() => openCanvas('plan')}
              >
                <ActivityLogIcon />
                <span>
                  <strong>{t('session.canvasPlan')}</strong>
                  <small>{viewModel.hasPlan ? t('session.planReady') : t('session.noPlanShort')}</small>
                </span>
                <ChevronRightIcon />
              </button>
              <button
                type="button"
                data-session-canvas-trigger="output"
                onClick={() =>
                  openCanvas(viewModel.capabilityMode === 'code' ? 'changes' : 'artifacts')
                }
              >
                {viewModel.capabilityMode === 'code' ? <CodeIcon /> : <ArchiveIcon />}
                <span>
                  <strong>
                    {viewModel.capabilityMode === 'code'
                      ? t('session.canvasChanges')
                      : t('session.canvasArtifacts')}
                  </strong>
                  <small>
                    {viewModel.artifactCount === null
                      ? t('session.notAvailable')
                      : t('session.evidence.recordCount', { count: viewModel.artifactCount })}
                  </small>
                </span>
                <ChevronRightIcon />
              </button>
              <button
                type="button"
                data-session-canvas-trigger="evidence"
                onClick={() => openCanvas(evidenceSurface)}
              >
                <CheckCircledIcon />
                <span>
                  <strong>
                    {evidenceSurface === 'checks'
                      ? t('session.canvasChecks')
                      : t('session.canvasVerification')}
                  </strong>
                  <small>
                    {viewModel.verificationCount === null
                      ? t('session.notAvailable')
                      : t('session.evidence.recordCount', {
                          count: viewModel.verificationCount,
                        })}
                  </small>
                </span>
                <ChevronRightIcon />
              </button>
            </section>

            <section className="session-context-section session-context-evidence">
              <h2>{t('session.latestEvidence')}</h2>
              <dl>
                <div>
                  <dt>{t('session.toolActivity')}</dt>
                  <dd>
                    {viewModel.toolActivityCount === null
                      ? t('session.notAvailable')
                      : viewModel.toolActivityCount}
                  </dd>
                </div>
                <div>
                  <dt>{t('session.failedShort')}</dt>
                  <dd>
                    {viewModel.failedToolActivityCount === null
                      ? t('session.notAvailable')
                      : viewModel.failedToolActivityCount}
                  </dd>
                </div>
                <div>
                  <dt>{t('session.canvasSources')}</dt>
                  <dd>
                    {viewModel.sourceCount === null ? t('session.notAvailable') : viewModel.sourceCount}
                  </dd>
                </div>
              </dl>
            </section>
          </aside>
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

function executionModeLabel(
  mode: Exclude<SessionDetailViewModel['executionMode'], 'unavailable'>,
  t: (key: string) => string,
) {
  if (mode === 'plan') return t('session.planMode');
  if (mode === 'explore') return t('session.exploreMode');
  return t('session.buildMode');
}

function conversationModeLabel(
  mode: string | null,
  t: (key: string) => string,
): string | null {
  if (mode === 'single_agent' || mode === 'multi_agent_isolated') {
    return t('session.privateConversation');
  }
  if (mode === 'multi_agent_shared') return t('session.sharedConversation');
  if (mode === 'autonomous') return t('session.autonomousConversation');
  return null;
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

function statusColor(status: string): 'green' | 'amber' | 'gray' | 'red' {
  if (status === 'active' || status === 'running' || status === 'accepted') return 'green';
  if (
    status === 'blocked' ||
    status === 'needs_input' ||
    status === 'needs_approval' ||
    status === 'awaiting_leader_adjudication'
  ) {
    return 'amber';
  }
  if (status === 'paused') return 'amber';
  if (status === 'ready_review') return 'green';
  if (
    status === 'failed' ||
    status === 'error' ||
    status === 'disconnected' ||
    status === 'rejected'
  ) {
    return 'red';
  }
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
