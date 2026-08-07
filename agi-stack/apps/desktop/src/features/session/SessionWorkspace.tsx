import { useEffect, useRef, useState, type ReactNode } from 'react';
import { AlertDialog, Badge, Button } from '@radix-ui/themes';
import {
  ActivityLogIcon,
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
  Pencil1Icon,
  Pencil2Icon,
  PersonIcon,
  PlayIcon,
  ReaderIcon,
  ReloadIcon,
  StopIcon,
  TrashIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import {
  ConversationLifecycleDialogs,
  type ConversationLifecycleMode,
} from '../workspace/ConversationLifecycleDialogs';
import type { SessionCanvasTabId } from './sessionCanvasModel';
import {
  sessionLiveIndicator,
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
  onOpenCanvas: (tab?: SessionCanvasTabId) => void;
  runActionPending: SessionRunAction | null;
  liveConnected: boolean;
  liveError: string | null;
  onRunAction: (action: SessionRunAction, feedback?: string) => void;
  onOpenTask?: () => void;
  onRenameConversation?: (title: string) => Promise<void>;
  onDeleteConversation?: () => Promise<void>;
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
  onOpenCanvas,
  runActionPending,
  liveConnected,
  liveError,
  onRunAction,
  onOpenTask,
  onRenameConversation,
  onDeleteConversation,
}: SessionWorkspaceProps) {
  const { t } = useI18n();
  const [reviewFeedbackOpen, setReviewFeedbackOpen] = useState(false);
  const [reviewFeedback, setReviewFeedback] = useState('');
  const [recoveryConfirmOpen, setRecoveryConfirmOpen] = useState(false);
  const [lifecycleMode, setLifecycleMode] = useState<ConversationLifecycleMode>(null);
  const moreActionsRef = useRef<HTMLDetailsElement>(null);
  const moreActionsSummaryRef = useRef<HTMLElement>(null);
  const [moreActionsOpen, setMoreActionsOpen] = useState(false);
  const statusPresentation = sessionStatusPresentation(viewModel.status);
  const liveIndicator = sessionLiveIndicator(viewModel.status, liveConnected);
  const runActions = viewModel.runActions;
  const reattachPresentation = sessionRecoveryPresentation('reconnect');
  const forkPresentation = sessionRecoveryPresentation('fork');
  const actionDisabled = runActionPending !== null || viewModel.runRevision === null;

  // The context rail lives in the right sidebar now, so the banner is the
  // only attention surface inside the thread column and must always show.
  const showStatusBanner = statusPresentation !== null;
  const conversationModePresentation = conversationModeLabel(viewModel.conversationMode, t);

  const closeMoreActions = (restoreFocus = false) => {
    moreActionsRef.current?.removeAttribute('open');
    setMoreActionsOpen(false);
    if (restoreFocus) {
      window.requestAnimationFrame(() => moreActionsSummaryRef.current?.focus());
    }
  };

  useEffect(() => {
    if (!moreActionsOpen) return;
    const closeIfOutside = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && !moreActionsRef.current?.contains(target)) closeMoreActions();
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      closeMoreActions(true);
    };
    document.addEventListener('pointerdown', closeIfOutside, true);
    document.addEventListener('keydown', closeOnEscape, true);
    return () => {
      document.removeEventListener('pointerdown', closeIfOutside, true);
      document.removeEventListener('keydown', closeOnEscape, true);
    };
  }, [moreActionsOpen]);

  useEffect(() => {
    if (viewModel.status !== 'ready_review') {
      setReviewFeedbackOpen(false);
      setReviewFeedback('');
    }
  }, [viewModel.status]);

  const closeLifecycleDialog = () => {
    setLifecycleMode(null);
    if (typeof window === 'undefined') return;
    window.requestAnimationFrame(() => moreActionsSummaryRef.current?.focus());
  };

  return (
    <section
      className={`session-workspace-shell ${showStatusBanner ? 'has-status-banner' : ''}`}
      aria-label={t('session.detail')}
    >
      <header className="session-workspace-header">
        <div className="session-workspace-identity">
          <span>
            {viewModel.workspaceLabel ? (
              <>
                {viewModel.workspaceLabel} <ChevronRightIcon />{' '}
              </>
            ) : null}
            {t('session.session')}
          </span>
          <div>
            <h1>{viewModel.title || t('session.untitled')}</h1>
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
          <details
            className="session-workspace-more"
            ref={moreActionsRef}
            onToggle={(event) => setMoreActionsOpen(event.currentTarget.open)}
          >
            <summary
              ref={moreActionsSummaryRef}
              aria-label={t('session.moreActions')}
              title={t('session.moreActions')}
            >
              <DotsHorizontalIcon />
            </summary>
            <div>
              <button
                type="button"
                onClick={() => {
                  closeMoreActions();
                  onOpenCanvas('overview');
                }}
              >
                <ReaderIcon /> {t('session.canvasOverview')}
              </button>
              {onRenameConversation ? (
                <button
                  type="button"
                  onClick={() => {
                    closeMoreActions();
                    setLifecycleMode('rename');
                  }}
                >
                  <Pencil1Icon /> {t('workspaceTree.renameConversation')}
                </button>
              ) : null}
              {onDeleteConversation ? (
                <button
                  type="button"
                  className="danger"
                  onClick={() => {
                    closeMoreActions();
                    setLifecycleMode('delete');
                  }}
                >
                  <TrashIcon /> {t('workspaceTree.deleteConversation')}
                </button>
              ) : null}
              {runActions.includes('cancel') ? (
                <button
                  type="button"
                  className="danger"
                  disabled={actionDisabled}
                  title={t('session.stopRunHint')}
                  onClick={() => {
                    closeMoreActions();
                    onRunAction('cancel');
                  }}
                >
                  <StopIcon />
                  {runActionPending === 'cancel' ? t('session.stopping') : t('session.stopRun')}
                </button>
              ) : null}
            </div>
          </details>
        </div>
      </header>
      <ConversationLifecycleDialogs
        mode={lifecycleMode}
        target={{ id: viewModel.id, title: viewModel.title }}
        onClose={closeLifecycleDialog}
        onRename={async (title) => {
          if (onRenameConversation) await onRenameConversation(title);
        }}
        onDelete={async () => {
          if (onDeleteConversation) await onDeleteConversation();
        }}
      />

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

      <div className="session-workspace-body">
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
              <em title={liveError ?? undefined} data-live-tone={liveIndicator.tone}>
                {t(liveIndicator.labelKey)}
              </em>
              <button
                type="button"
                data-session-canvas-trigger="default"
                aria-label={t('session.openCanvas')}
                title={t('session.openCanvas')}
                onClick={() => onOpenCanvas()}
              >
                {t('session.openCanvas')} <ReaderIcon />
              </button>
            </div>
            {thread}
          </section>
      </div>
    </section>
  );
}

export function executionModeLabel(
  mode: Exclude<SessionDetailViewModel['executionMode'], 'unavailable'>,
  t: (key: string) => string,
) {
  if (mode === 'plan') return t('session.planMode');
  if (mode === 'explore') return t('session.exploreMode');
  return t('session.buildMode');
}

function conversationModeLabel(mode: string | null, t: (key: string) => string): string | null {
  if (mode === 'single_agent' || mode === 'multi_agent_isolated') {
    return t('session.privateConversation');
  }
  if (mode === 'multi_agent_shared') return t('session.sharedConversation');
  if (mode === 'autonomous') return t('session.autonomousConversation');
  return null;
}

export function statusLabel(status: string, t: (key: string) => string): string {
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
