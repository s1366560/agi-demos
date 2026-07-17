import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Badge, Button, Flex, Heading, ScrollArea, Text, TextArea } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  ArrowUpIcon,
  CodeIcon,
  Cross2Icon,
  Link2Icon,
  MixerHorizontalIcon,
  ReloadIcon,
  RocketIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import { sessionActivitySummary } from '../session/sessionNarrativeModel';
import type {
  AgentTimelineItem,
  ConversationTimelineState,
  HitlResponseSubmission,
  CodeRangeReference,
  DesktopRunInput,
  RunInputDelivery,
  WorkspaceMessage,
} from '../../types';
import { runInputReferenceLabel } from '../session/sessionChangesModel';
import {
  queuedRunInputHandoffState,
  visibleQueuedRunInputs,
} from '../session/sessionRunInputModel';
import { ComposerControls } from './ComposerControls';
import { AgentTimeline } from './ChatTimeline';
import { isImportantTimelineItem } from './chatTimelinePresentation';
import { SessionEmptyState, WorkspaceTranscriptMessage } from './ChatTranscript';
import { ChatWorkflowStrip } from './ChatWorkflowStrip';
import type { ChatWorkflowTarget } from './ChatWorkflowStrip';
import { chatComposerPresentation } from './chatComposerModel';
import type { ChatComposerVariant } from './chatComposerModel';
import './ChatPanel.css';

export type { ChatWorkflowTarget } from './ChatWorkflowStrip';

type ChatPanelProps = {
  messages: WorkspaceMessage[];
  timelineState: ConversationTimelineState | null;
  agentTaskSignals: AgentTaskSignal[];
  workflowCounts?: Partial<Record<ChatWorkflowTarget, number | string>>;
  sessionTitle: string;
  scopeLabel: string;
  composerVariant?: ChatComposerVariant;
  input: string;
  sending: boolean;
  disabledReason: string | null;
  activeWorkflowTarget: ChatWorkflowTarget;
  modelLabel?: string;
  runtimeTargetLabel?: string;
  runtimeTargetOptions?: string[];
  runInputDelivery: RunInputDelivery | null;
  runInputDeliveryOptions: RunInputDelivery[];
  runInputs: DesktopRunInput[];
  runInputsLoading: boolean;
  runInputsError: string | null;
  promotingRunInputId: string | null;
  runInputAuthorityRunId: string | null;
  references: CodeRangeReference[];
  onInputChange: (value: string) => void;
  onRunInputDeliveryChange: (delivery: RunInputDelivery) => void;
  onPromoteRunInput: (input: DesktopRunInput) => void;
  onRemoveReference: (reference: CodeRangeReference) => void;
  onSend: () => void;
  onRefresh: () => void;
  onLoadEarlier: () => void;
  onRespondToHitl: (submission: HitlResponseSubmission) => Promise<void>;
  respondableHitlRequestIds: readonly string[];
  authorityNotice?: {
    tone: 'loading' | 'warning' | 'error';
    title: string;
    description: string;
    actionLabel?: string;
  } | null;
  onAuthorityAction?: () => void;
  onWorkflowSelect: (target: ChatWorkflowTarget) => void;
  onRuntimeTargetChange?: (value: string) => void;
  onOpenCommands: (trigger?: HTMLElement | null) => void;
};

export type AgentTaskSignalStatus = 'saving' | 'queued' | 'acknowledged' | 'failed';

export type AgentTaskSignal = {
  id: string;
  content: string;
  status: AgentTaskSignalStatus;
  detail: string;
  createdAt: string;
  conversationId?: string;
  messageId?: string;
  eventType?: string;
};

export function ChatPanel({
  messages,
  timelineState,
  agentTaskSignals,
  workflowCounts,
  sessionTitle,
  scopeLabel,
  composerVariant = 'workspace',
  input,
  sending,
  disabledReason,
  activeWorkflowTarget,
  modelLabel,
  runtimeTargetLabel,
  runtimeTargetOptions,
  runInputDelivery,
  runInputDeliveryOptions,
  runInputs,
  runInputsLoading,
  runInputsError,
  promotingRunInputId,
  runInputAuthorityRunId,
  references,
  onInputChange,
  onRunInputDeliveryChange,
  onPromoteRunInput,
  onRemoveReference,
  onSend,
  onRefresh,
  onLoadEarlier,
  onRespondToHitl,
  respondableHitlRequestIds,
  authorityNotice,
  onAuthorityAction,
  onWorkflowSelect,
  onRuntimeTargetChange,
  onOpenCommands,
}: ChatPanelProps) {
  const { t } = useI18n();
  const disabled = Boolean(disabledReason);
  const canSend = !disabled && !sending && Boolean(input.trim());
  const composerPresentation = chatComposerPresentation(composerVariant);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const scrollAnchorRef = useRef<HTMLDivElement>(null);
  const timelineWindowRef = useRef<{ firstId: string; lastId: string; count: number } | null>(null);
  const earlierScrollRef = useRef<{ height: number; top: number } | null>(null);
  const [expandedTimelineItems, setExpandedTimelineItems] = useState<Record<string, boolean>>({});
  const queuedRunInputs = useMemo(() => visibleQueuedRunInputs(runInputs), [runInputs]);
  const signalStateKey = useMemo(
    () => agentTaskSignals.map((signal) => `${signal.id}:${signal.status}`).join('|'),
    [agentTaskSignals],
  );
  const timelineItemCount = timelineState?.items.length ?? 0;
  const timelineFirstId = timelineState?.items[0]?.id ?? '';
  const timelineLastId = timelineState?.items[timelineItemCount - 1]?.id ?? '';
  const activitySummary = useMemo(() => {
    if (!timelineState?.items.length) return null;
    const artifactCount = timelineState.items.filter((item) =>
      item.type.startsWith('artifact_'),
    ).length;
    const taskCount =
      timelineState.items.filter((item) => item.type.startsWith('task_')).length +
      agentTaskSignals.length;
    return sessionActivitySummary({
      items: timelineState.items,
      artifactCount,
      taskCount,
    });
  }, [agentTaskSignals.length, timelineState]);
  const activityEvidence = useMemo(() => {
    if (!timelineState) return '';
    const artifactCount = timelineState.items.filter((item) =>
      item.type.startsWith('artifact_'),
    ).length;
    const taskCount =
      timelineState.items.filter((item) => item.type.startsWith('task_')).length +
      agentTaskSignals.length;
    return t('session.evidenceCount', { artifactCount, taskCount });
  }, [agentTaskSignals.length, t, timelineState]);
  const scrollToLatest = useCallback(() => {
    scrollAnchorRef.current?.scrollIntoView({ block: 'end' });
  }, []);
  const scrollViewport = useCallback(() => {
    return (
      scrollAreaRef.current?.querySelector<HTMLElement>('[data-radix-scroll-area-viewport]') ??
      scrollAreaRef.current
    );
  }, []);

  useEffect(() => {
    if (timelineState) {
      const previous = timelineWindowRef.current;
      const current = {
        firstId: timelineFirstId,
        lastId: timelineLastId,
        count: timelineItemCount,
      };
      timelineWindowRef.current = current;
      const prependedEarlier =
        previous &&
        current.count > previous.count &&
        current.lastId === previous.lastId &&
        current.firstId !== previous.firstId;
      if (prependedEarlier) return;
    } else {
      timelineWindowRef.current = null;
    }
    scrollToLatest();
  }, [
    messages.length,
    scrollToLatest,
    signalStateKey,
    timelineFirstId,
    timelineItemCount,
    timelineLastId,
    timelineState,
  ]);

  useEffect(() => {
    if (timelineState?.loadingEarlier) return;
    const snapshot = earlierScrollRef.current;
    if (!snapshot) return;
    earlierScrollRef.current = null;
    window.requestAnimationFrame(() => {
      const viewport = scrollViewport();
      if (!viewport) return;
      const delta = viewport.scrollHeight - snapshot.height;
      viewport.scrollTop = snapshot.top + delta;
    });
  }, [scrollViewport, timelineItemCount, timelineState?.loadingEarlier]);

  useEffect(() => {
    const viewport = scrollViewport();
    if (!viewport || !timelineState) return undefined;
    const handleScroll = () => {
      if (!timelineState.hasMore || timelineState.loading || timelineState.loadingEarlier) return;
      if (earlierScrollRef.current) return;
      if (viewport.scrollTop > 96) return;
      earlierScrollRef.current = {
        height: viewport.scrollHeight,
        top: viewport.scrollTop,
      };
      onLoadEarlier();
    };
    viewport.addEventListener('scroll', handleScroll, { passive: true });
    handleScroll();
    return () => viewport.removeEventListener('scroll', handleScroll);
  }, [
    onLoadEarlier,
    scrollViewport,
    timelineState,
    timelineState?.hasMore,
    timelineState?.loading,
    timelineState?.loadingEarlier,
  ]);

  useEffect(() => {
    const handleResize = () => {
      window.requestAnimationFrame(scrollToLatest);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [scrollToLatest]);

  const handleSend = useCallback(() => {
    if (!canSend) return;
    onSend();
  }, [canSend, onSend]);
  const toggleTimelineItem = useCallback((item: AgentTimelineItem) => {
    setExpandedTimelineItems((current) => {
      const currentValue = current[item.id] ?? isImportantTimelineItem(item);
      return { ...current, [item.id]: !currentValue };
    });
  }, []);

  return (
    <section
      className={`pane-shell chat-shell ${
        composerVariant === 'session' ? 'session-chat-narrative' : 'workspace-chat-panel'
      }`}
    >
      {composerPresentation.showPaneHeader ? (
        <header className="pane-head">
          <div>
            <Heading as="h2" size="3">
              {sessionTitle}
            </Heading>
            <Text size="1" color="gray">
              {scopeLabel}
            </Text>
          </div>
          <Button
            size="2"
            variant="surface"
            aria-label={t('chat.refreshMessages')}
            onClick={onRefresh}
            disabled={disabled}
          >
            <ReloadIcon /> {t('common.refresh')}
          </Button>
        </header>
      ) : null}
      <ScrollArea className="message-scroll" ref={scrollAreaRef}>
        <div className="message-stack">
          {timelineState ? (
            <>
              {timelineState.items.length ? (
                <div className="session-chat-day" aria-label={t('session.today')}>
                  <span>{t('session.today')}</span>
                </div>
              ) : null}
              {activitySummary ? (
                <section className="session-current-activity" aria-label={t('session.currentActivity')}>
                  <div className="session-current-activity-primary">
                    <span className="session-current-activity-icon" aria-hidden="true">
                      <ActivityLogIcon />
                    </span>
                    <span className="session-current-activity-copy">
                      <small>{t('session.currentActivity')}</small>
                      <strong>
                        {activitySummary.titleKey
                          ? t(activitySummary.titleKey)
                          : activitySummary.title || t('session.waitingForActivity')}
                      </strong>
                    </span>
                    <Badge color="cyan" variant="soft">
                      {t('session.live')}
                    </Badge>
                  </div>
                  {activitySummary.detail ? <p>{activitySummary.detail}</p> : null}
                  <dl>
                    <div>
                      <dt>{t('session.latestCheckpoint')}</dt>
                      <dd>
                        {activitySummary.checkpointKey
                          ? t(activitySummary.checkpointKey)
                          : activitySummary.checkpoint || t('session.notAvailable')}
                      </dd>
                    </div>
                    <div>
                      <dt>{t('session.sessionEvidence')}</dt>
                      <dd>{activityEvidence}</dd>
                    </div>
                  </dl>
                </section>
              ) : null}
              <AgentTimeline
                state={timelineState}
                expandedItems={expandedTimelineItems}
                onToggleItem={toggleTimelineItem}
                onRespondToHitl={onRespondToHitl}
                respondableHitlRequestIds={respondableHitlRequestIds}
              />
            </>
          ) : messages.length === 0 ? (
            <SessionEmptyState />
          ) : (
            messages.map((message) => <WorkspaceTranscriptMessage message={message} key={message.id} />)
          )}
          {agentTaskSignals.length ? (
            <div className="agent-run-stack" aria-label={t('chat.agentTaskStatus')}>
              {agentTaskSignals.map((signal) => (
                <article className={`message agent-run ${signal.status}`} key={signal.id}>
                  <Flex align="center" justify="between" gap="2" mb="2">
                    <Flex align="center" gap="2" className="agent-run-title">
                      <RocketIcon />
                      <Text size="2" weight="bold">
                        {t('chat.agentTask')}
                      </Text>
                      <Badge color={agentSignalColor(signal.status)} variant="soft">
                        {t(agentSignalLabelKey(signal.status))}
                      </Badge>
                    </Flex>
                    <Text size="1" color="gray">
                      {formatTime(signal.createdAt)}
                    </Text>
                  </Flex>
                  <Text as="p" size="2" className="agent-run-content">
                    {signal.content}
                  </Text>
                  <div className="agent-run-meta">
                    <span>{signal.detail}</span>
                    {signal.conversationId ? (
                      <span title={signal.conversationId}>
                        {t('chat.conversationReference', {
                          conversationId: shortId(signal.conversationId),
                        })}
                      </span>
                    ) : null}
                    {signal.eventType ? <span>{signal.eventType}</span> : null}
                  </div>
                </article>
              ))}
            </div>
          ) : null}
          <div ref={scrollAnchorRef} aria-hidden="true" />
        </div>
      </ScrollArea>
      <form
        className="composer chat-composer"
        onSubmit={(event) => {
          event.preventDefault();
          handleSend();
        }}
      >
        {composerPresentation.showWorkflowStrip ? (
          <ChatWorkflowStrip
            activeTarget={activeWorkflowTarget}
            workflowCounts={workflowCounts}
            onSelect={onWorkflowSelect}
          />
        ) : null}
        {composerPresentation.showQueueHandoff &&
        (runInputsLoading || runInputsError || queuedRunInputs.length) ? (
          <section className="run-input-queue" aria-label={t('session.queueHandoffRegion')}>
            <div className="run-input-queue-header">
              <span>
                <strong>{t('session.queueHandoffTitle')}</strong>
                {queuedRunInputs.length ? (
                  <small>
                    {t('session.queueHandoffCount', { count: queuedRunInputs.length })}
                  </small>
                ) : null}
              </span>
              {runInputsLoading ? <small>{t('session.queueLoading')}</small> : null}
            </div>
            {runInputsError ? (
              <p className="run-input-queue-error">{t('session.queueLoadError')}</p>
            ) : null}
            {queuedRunInputs.map((queuedInput) => {
              const handoffState = queuedRunInputHandoffState(queuedInput);
              if (!handoffState) return null;
              const statusLabel =
                handoffState === 'waiting'
                  ? t('session.queueHandoffWaiting')
                  : handoffState === 'ready'
                    ? t('session.queueHandoffReady')
                    : handoffState === 'blocked'
                      ? t('session.queueHandoffBlocked')
                      : t('session.queueHandoffPromoted');
              const statusBody =
                handoffState === 'waiting'
                  ? t('session.queueHandoffWaitingBody')
                  : handoffState === 'ready'
                    ? t('session.queueHandoffReadyBody')
                    : handoffState === 'blocked'
                      ? t('session.queueHandoffBlockedBody')
                      : t('session.queueHandoffPromotedBody');
              return (
                <article
                  className={`run-input-queue-item is-${handoffState}`}
                  key={queuedInput.id}
                >
                  <div className="run-input-queue-copy">
                    <div>
                      <Badge color={handoffState === 'ready' ? 'cyan' : 'gray'}>
                        {statusLabel}
                      </Badge>
                      <small>
                        {t('session.queuePosition', {
                          position: queuedInput.queue_position ?? '—',
                        })}
                      </small>
                    </div>
                    <strong>{queuedInput.content}</strong>
                    <p>{statusBody}</p>
                  </div>
                  {handoffState === 'ready' ? (
                    <Button
                      type="button"
                      size="1"
                      color="cyan"
                      loading={promotingRunInputId === queuedInput.id}
                      disabled={
                        Boolean(promotingRunInputId) ||
                        queuedInput.run_id !== runInputAuthorityRunId
                      }
                      title={
                        queuedInput.run_id === runInputAuthorityRunId
                          ? undefined
                          : t('session.authorityActionUnavailable')
                      }
                      onClick={() => onPromoteRunInput(queuedInput)}
                    >
                      <RocketIcon />
                      {promotingRunInputId === queuedInput.id
                        ? t('session.startingPlanTurn')
                        : t('session.startPlanTurn')}
                    </Button>
                  ) : null}
                </article>
              );
            })}
          </section>
        ) : null}
        {authorityNotice ? (
          <div
            className={`session-authority-notice tone-${authorityNotice.tone}`}
            role={authorityNotice.tone === 'error' ? 'alert' : 'status'}
            aria-live="polite"
          >
            <ReloadIcon aria-hidden="true" />
            <span>
              <strong>{authorityNotice.title}</strong>
              <small>{authorityNotice.description}</small>
            </span>
            {authorityNotice.actionLabel && onAuthorityAction ? (
              <Button type="button" size="1" variant="soft" onClick={onAuthorityAction}>
                {authorityNotice.actionLabel}
              </Button>
            ) : null}
          </div>
        ) : null}
        <div className="session-composer-editor">
          {references.length ? (
            <div className="composer-reference-chips" aria-label={t('session.attachedReferences')}>
              {references.map((reference) => (
                <span key={`${reference.snapshot_id}:${runInputReferenceLabel(reference)}`}>
                  <CodeIcon aria-hidden="true" />
                  <strong>{runInputReferenceLabel(reference)}</strong>
                  <button
                    type="button"
                    aria-label={t('session.removeReference', {
                      reference: runInputReferenceLabel(reference),
                    })}
                    onClick={() => onRemoveReference(reference)}
                  >
                    <Cross2Icon />
                  </button>
                </span>
              ))}
            </div>
          ) : null}
          <TextArea
            className="chat-composer-input"
            value={input}
            disabled={disabled}
            onChange={(event) => onInputChange(event.target.value)}
            placeholder={
              disabledReason ??
              (composerPresentation.placeholderKey
                ? t(composerPresentation.placeholderKey)
                : t('chat.taskComposerPlaceholder'))
            }
            onKeyDown={(event) => {
              if (
                event.key === 'Enter' &&
                !event.shiftKey &&
                (runInputDeliveryOptions.length === 0 || event.metaKey || event.ctrlKey)
              ) {
                event.preventDefault();
                handleSend();
              }
            }}
          />
          <Flex
            align="center"
            justify="between"
            className="chat-composer-footer"
          >
          {composerVariant === 'session' ? (
            <div className="session-composer-context-actions">
              <button
                type="button"
                onClick={(event) => onOpenCommands(event.currentTarget)}
              >
                <Link2Icon aria-hidden="true" />
                {t('session.attach')}
              </button>
              <button
                type="button"
                onClick={(event) => onOpenCommands(event.currentTarget)}
              >
                <MixerHorizontalIcon aria-hidden="true" />
                {t('session.context')}
              </button>
            </div>
          ) : null}
          {composerPresentation.showCommands ? (
            <button
              className="composer-slash-button"
              type="button"
              aria-label={t('chat.slashCommands')}
              title={t('chat.slashCommands')}
              onClick={(event) => onOpenCommands(event.currentTarget)}
            >
              /
            </button>
          ) : null}
          {runInputDeliveryOptions.length ? (
            <div className="composer-delivery-switch" aria-label={t('session.deliveryMode')}>
              {runInputDeliveryOptions.map((delivery) => (
                <button
                  type="button"
                  className={runInputDelivery === delivery ? 'is-active' : ''}
                  aria-pressed={runInputDelivery === delivery}
                  onClick={() => onRunInputDeliveryChange(delivery)}
                  key={delivery}
                >
                  {delivery === 'steer_now'
                    ? t('session.steerNow')
                    : t('session.queueNext')}
                </button>
              ))}
            </div>
          ) : null}
          {composerPresentation.showRuntimeControls &&
          runtimeTargetLabel &&
          runtimeTargetOptions?.length &&
          onRuntimeTargetChange ? (
            <ComposerControls
              disabledHint={disabledReason}
              modelLabel={modelLabel}
              runtimeTargetLabel={runtimeTargetLabel}
              runtimeTargetOptions={runtimeTargetOptions}
              onRuntimeTargetChange={onRuntimeTargetChange}
            />
          ) : null}
          <Flex align="center" gap="2" className="composer-right-actions">
            {composerPresentation.showRuntimeStatus ? (
              <span
                className={`composer-status-button composer-status-dot ${
                  disabledReason ? 'is-blocked' : 'is-connected'
                }`}
                aria-label={disabledReason ?? t('session.runtimeAvailable')}
                title={disabledReason ?? t('session.runtimeAvailable')}
              />
            ) : null}
            <Button
              size="2"
              color="green"
              className="send-pill"
              type="submit"
              aria-label={
                runInputDelivery === 'steer_now'
                  ? t('session.sendSteering')
                  : runInputDelivery === 'queue_next'
                    ? t('session.sendQueuedInput')
                    : t('session.sendMessage')
              }
              title={runInputDeliveryOptions.length ? t('session.sendShortcut') : undefined}
              loading={sending}
              disabled={!canSend}
            >
              <ArrowUpIcon />
            </Button>
          </Flex>
          </Flex>
        </div>
      </form>
    </section>
  );
}

function agentSignalLabelKey(status: AgentTaskSignalStatus): string {
  if (status === 'saving') return 'chat.status.saving';
  if (status === 'queued') return 'chat.status.sent';
  if (status === 'acknowledged') return 'chat.status.accepted';
  return 'chat.status.needsAttention';
}

function agentSignalColor(status: AgentTaskSignalStatus): 'gray' | 'cyan' | 'green' | 'red' {
  if (status === 'saving') return 'gray';
  if (status === 'queued') return 'cyan';
  if (status === 'acknowledged') return 'green';
  return 'red';
}

function shortId(value: string): string {
  return value.length > 8 ? value.slice(0, 8) : value;
}

function formatTime(value: string | undefined): string {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
