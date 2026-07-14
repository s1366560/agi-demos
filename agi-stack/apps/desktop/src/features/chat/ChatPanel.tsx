import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Badge, Button, Flex, Heading, ScrollArea, Text, TextArea } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  ArchiveIcon,
  ArrowUpIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CodeIcon,
  Cross2Icon,
  DotsHorizontalIcon,
  ReaderIcon,
  ReloadIcon,
  RocketIcon,
} from '@radix-ui/react-icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { useI18n } from '../../i18n';
import {
  approvalResponseSubmission,
  validateApprovalRequest,
} from '../session/sessionDecisionModel';
import {
  buildSessionNarrative,
  sessionActivitySummary,
} from '../session/sessionNarrativeModel';
import type {
  AgentTimelineItem,
  ConversationTimelineState,
  DesktopApprovalRequest,
  HitlResponseSubmission,
  HitlType,
  ToolDisplayData,
  ToolFileMetadata,
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
import { resolveA2UIActionView } from './a2uiAction';
import type { A2UIActionView } from './a2uiAction';
import { chatComposerPresentation } from './chatComposerModel';
import type { ChatComposerVariant } from './chatComposerModel';

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

export type ChatWorkflowTarget = 'changes' | 'pull' | 'plan' | 'background' | 'artifacts';
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

type TimelineKind = 'user' | 'agent' | 'runtime' | 'tool' | 'artifact';
type TimelineStatus = { kind: 'ok' | 'error' | 'waiting'; label: string };

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
    return sessionActivitySummary({
      items: timelineState.items,
      artifactCount: timelineState.items.filter((item) => item.type.startsWith('artifact_')).length,
      taskCount:
        timelineState.items.filter((item) => item.type.startsWith('task_')).length +
        agentTaskSignals.length,
    });
  }, [agentTaskSignals.length, timelineState]);
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
    <section className="pane-shell chat-shell">
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
            aria-label="Refresh workspace messages"
            onClick={onRefresh}
            disabled={disabled}
          >
            <ReloadIcon /> Refresh
          </Button>
        </header>
      ) : null}
      <ScrollArea className="message-scroll" ref={scrollAreaRef}>
        <div className="message-stack">
          {timelineState ? (
            <>
              {activitySummary ? (
                <section className="session-current-activity" aria-label={t('session.currentActivity')}>
                  <div className="session-current-activity-head">
                    <span>{t('session.currentActivity')}</span>
                    <Badge color="cyan" variant="soft">
                      {t('session.live')}
                    </Badge>
                  </div>
                  <strong>
                    {activitySummary.titleKey
                      ? t(activitySummary.titleKey)
                      : activitySummary.title || t('session.waitingForActivity')}
                  </strong>
                  {activitySummary.detail ? <p>{activitySummary.detail}</p> : null}
                  <dl>
                    <div>
                      <dt>{t('session.latestCheckpoint')}</dt>
                      <dd>{activitySummary.checkpoint || t('session.notAvailable')}</dd>
                    </div>
                    <div>
                      <dt>{t('session.sessionEvidence')}</dt>
                      <dd>{activitySummary.evidence}</dd>
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
            <div className="agent-run-stack" aria-label="Agent task status">
              {agentTaskSignals.map((signal) => (
                <article className={`message agent-run ${signal.status}`} key={signal.id}>
                  <Flex align="center" justify="between" gap="2" mb="2">
                    <Flex align="center" gap="2" className="agent-run-title">
                      <RocketIcon />
                      <Text size="2" weight="bold">
                        Agent task
                      </Text>
                      <Badge color={agentSignalColor(signal.status)} variant="soft">
                        {agentSignalLabel(signal.status)}
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
                        Conversation {shortId(signal.conversationId)}
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
              : 'Describe a task to run autonomously. Type / for commands, @ for files, or # for issues...')
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
          justify={
            composerVariant === 'session' && runInputDeliveryOptions.length === 0
              ? 'end'
              : 'between'
          }
          className="chat-composer-footer"
        >
          {composerPresentation.showCommands ? (
            <button
              className="composer-slash-button"
              type="button"
              aria-label="Slash commands"
              title="Slash commands"
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
      </form>
    </section>
  );
}

function AgentTimeline({
  state,
  expandedItems,
  onToggleItem,
  onRespondToHitl,
  respondableHitlRequestIds,
}: {
  state: ConversationTimelineState;
  expandedItems: Record<string, boolean>;
  onToggleItem: (item: AgentTimelineItem) => void;
  onRespondToHitl: (submission: HitlResponseSubmission) => Promise<void>;
  respondableHitlRequestIds: readonly string[];
}) {
  const { t } = useI18n();
  const respondableHitlRequestIdSet = useMemo(
    () => new Set(respondableHitlRequestIds),
    [respondableHitlRequestIds],
  );
  const a2uiActionViews = useMemo(
    () =>
      new Map(
        state.items
          .filter((item) => timelineHitlType(item) === 'a2ui_action')
          .map((item) => [item.id, resolveA2UIActionView(item, state.items)] as const),
      ),
    [state.items],
  );
  const narrative = useMemo(() => buildSessionNarrative(state.items), [state.items]);

  if (state.loading) {
    return (
      <div className="chat-empty-state timeline-loading" role="status" aria-label={t('session.loadingHistory')}>
        <Text size="2" color="gray">
          {t('session.loadingHistory')}
        </Text>
      </div>
    );
  }

  return (
    <div className="agent-timeline" aria-label={t('session.conversationTimeline')}>
      {state.error ? (
        <div className="timeline-error" role="status">
          <Text size="2" color="red">
            {state.error}
          </Text>
        </div>
      ) : null}
      {state.hasMore || state.loadingEarlier ? (
        <div className="timeline-load-earlier" role="status" aria-live="polite">
          {state.loadingEarlier ? 'Loading earlier...' : 'Scroll up for earlier history'}
        </div>
      ) : null}
      {state.items.length === 0 && !state.error ? (
        <SessionEmptyState />
      ) : (
        narrative.map((node) => {
          if (node.kind === 'tool_group') {
            return (
              <details
                className={`timeline-tool-group status-${node.status}`}
                open={node.status !== 'complete' ? true : undefined}
                key={node.id}
              >
                <summary>
                  <span className="timeline-tool-group-icon" aria-hidden>
                    <CodeIcon />
                  </span>
                  <span>
                    <strong>{t('session.toolActivity')}</strong>
                    <small>{t('session.toolActivityCount', { count: node.toolCount })}</small>
                  </span>
                  <em>{t(`session.toolStatus.${node.status}`)}</em>
                  <ChevronRightIcon className="timeline-tool-group-chevron" aria-hidden />
                </summary>
                <div className="timeline-tool-group-items">
                  {node.items.map((item) => {
                    const requestId = timelineHitlRequestId(item);
                    return (
                      <TimelineItemView
                        item={item}
                        expanded={expandedItems[item.id] ?? false}
                        onToggle={() => onToggleItem(item)}
                        onRespondToHitl={onRespondToHitl}
                        canRespondToHitl={Boolean(
                          requestId && respondableHitlRequestIdSet.has(requestId),
                        )}
                        a2uiActionView={a2uiActionViews.get(item.id)}
                        approvalRequest={state.approvalRequests.find(
                          (request) => request.id === requestId,
                        )}
                        key={item.id}
                      />
                    );
                  })}
                </div>
              </details>
            );
          }
          const item = node.item;
          const requestId = timelineHitlRequestId(item);
          return (
            <TimelineItemView
              item={item}
              expanded={expandedItems[item.id] ?? isImportantTimelineItem(item)}
              onToggle={() => onToggleItem(item)}
              onRespondToHitl={onRespondToHitl}
              canRespondToHitl={Boolean(
                requestId && respondableHitlRequestIdSet.has(requestId),
              )}
              a2uiActionView={a2uiActionViews.get(item.id)}
              approvalRequest={state.approvalRequests.find(
                (request) => request.id === requestId,
              )}
              key={node.id}
            />
          );
        })
      )}
    </div>
  );
}

function SessionEmptyState() {
  const { t } = useI18n();
  return (
    <div className="chat-empty-state session-conversation-empty" role="status">
      <span aria-hidden="true">
        <ActivityLogIcon />
      </span>
      <strong>{t('session.emptyTitle')}</strong>
      <p>{t('session.emptyDescription')}</p>
    </div>
  );
}

function WorkspaceTranscriptMessage({ message }: { message: WorkspaceMessage }) {
  const kind = messageKind(message);
  return (
    <article className={`message transcript-message workspace-message ${kind}`}>
      <div className="transcript-meta">
        <div className="transcript-author">
          <Text size="2" weight="bold">
            {messageSenderLabel(message)}
          </Text>
          {message.mentions?.length ? (
            <Badge color="cyan" variant="soft">
              {message.mentions.length} mentions
            </Badge>
          ) : null}
        </div>
        <Text size="1" color="gray">
          {formatTime(message.created_at)}
        </Text>
      </div>
      <MarkdownContent content={message.content} className="transcript-content" />
    </article>
  );
}

function TimelineItemView({
  item,
  expanded,
  onToggle,
  onRespondToHitl,
  canRespondToHitl,
  a2uiActionView,
  approvalRequest,
}: {
  item: AgentTimelineItem;
  expanded: boolean;
  onToggle: () => void;
  onRespondToHitl: (submission: HitlResponseSubmission) => Promise<void>;
  canRespondToHitl: boolean;
  a2uiActionView?: A2UIActionView;
  approvalRequest?: DesktopApprovalRequest;
}) {
  const kind = timelineKind(item);
  if (kind === 'user' || kind === 'agent') {
    return (
      <article className={`message transcript-message timeline-item ${kind}`}>
        <div className="transcript-meta">
          <Text size="2" weight="bold">
            {timelineTitle(item)}
          </Text>
          <Text size="1" color="gray">
            {formatTimelineTime(item)}
          </Text>
        </div>
        <TimelineItemBody
          item={item}
          kind={kind}
          onRespondToHitl={onRespondToHitl}
          canRespondToHitl={canRespondToHitl}
          a2uiActionView={a2uiActionView}
          approvalRequest={approvalRequest}
        />
      </article>
    );
  }

  const hasDetails = timelineHasDetails(item, kind);
  const status = timelineStatus(item);
  const lineCount = timelineDetailLineCount(item, kind);
  return (
    <article
      className={`message timeline-row timeline-item ${kind} ${expanded ? 'is-expanded' : ''} ${
        approvalRequest ? 'has-approval-evidence' : ''
      }`}
    >
      {hasDetails ? (
        <button
          type="button"
          className="timeline-row-toggle"
          aria-label={`${expanded ? 'Collapse' : 'Expand'} ${timelineTitle(item)}`}
          aria-expanded={expanded}
          onClick={onToggle}
        >
          {expanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
        </button>
      ) : (
        <span className="timeline-row-spacer" aria-hidden="true" />
      )}
      <div className="timeline-row-main">
        <div className="timeline-row-line">
          <span className="timeline-row-icon" aria-hidden="true">
            {timelineIcon(kind, item)}
          </span>
          <span className="timeline-row-title">{timelineTitle(item)}</span>
          <span className="timeline-row-summary">{timelineSummary(item, kind)}</span>
        </div>
        {expanded && hasDetails ? (
          <TimelineItemBody
            item={item}
            kind={kind}
            onRespondToHitl={onRespondToHitl}
            canRespondToHitl={canRespondToHitl}
            a2uiActionView={a2uiActionView}
            approvalRequest={approvalRequest}
          />
        ) : null}
      </div>
      <div className="timeline-row-meta">
        {status ? <span className={`timeline-status ${status.kind}`}>{status.label}</span> : null}
        {lineCount > 1 ? <span>{lineCount} lines</span> : null}
        <span>{formatTimelineTime(item)}</span>
      </div>
    </article>
  );
}

function TimelineItemBody({
  item,
  kind,
  onRespondToHitl,
  canRespondToHitl,
  a2uiActionView,
  approvalRequest,
}: {
  item: AgentTimelineItem;
  kind: TimelineKind;
  onRespondToHitl: (submission: HitlResponseSubmission) => Promise<void>;
  canRespondToHitl: boolean;
  a2uiActionView?: A2UIActionView;
  approvalRequest?: DesktopApprovalRequest;
}) {
  const hitlType = timelineHitlType(item);
  if (hitlType) {
    return (
      <HitlResponseCard
        item={item}
        hitlType={hitlType}
        onRespond={onRespondToHitl}
        canRespond={canRespondToHitl}
        a2uiActionView={a2uiActionView}
        approvalRequest={approvalRequest}
      />
    );
  }

  if (kind === 'tool') {
    const display = timelineToolDisplay(item);
    const fileMetadata = timelineFileMetadata(item);
    return (
      <div className="timeline-details">
        {display?.summary ? (
          <Text as="p" size="2" className="timeline-detail-summary">
            {display.summary}
          </Text>
        ) : null}
        {fileMetadata ? <ToolFileMetadataView metadata={fileMetadata} /> : null}
        {display?.details !== undefined ? (
          <div className="timeline-detail-block">
            <span>Display details</span>
            <pre>{formatTimelineValue(display.details)}</pre>
          </div>
        ) : null}
        {item.toolInput !== undefined ? (
          <div className="timeline-detail-block">
            <span>Input</span>
            <pre>{formatTimelineValue(item.toolInput)}</pre>
          </div>
        ) : null}
        {item.toolOutput !== undefined ? (
          <div className="timeline-detail-block">
            <span>Output</span>
            <pre>{formatTimelineValue(item.toolOutput)}</pre>
          </div>
        ) : null}
        {item.payload !== undefined ? (
          <div className="timeline-detail-block">
            <span>Payload</span>
            <pre>{formatTimelineValue(item.payload)}</pre>
          </div>
        ) : null}
      </div>
    );
  }

  if (kind === 'artifact') {
    return (
      <div className="timeline-details">
        <Text as="p" size="2" className="timeline-detail-summary">
          {item.filename || item.artifactId || 'Artifact'}
        </Text>
        {item.error ? (
          <Text size="1" color="red">
            {item.error}
          </Text>
        ) : null}
        {item.payload !== undefined ? (
          <div className="timeline-detail-block">
            <span>Payload</span>
            <pre>{formatTimelineValue(item.payload)}</pre>
          </div>
        ) : null}
      </div>
    );
  }

  if (item.question) {
    return (
      <div className="timeline-details">
        <Text as="p" size="2" className="timeline-detail-summary">
          {item.question}
        </Text>
        <div className="agent-run-meta">
          <span>{item.answered ? 'Answered' : 'Waiting for input'}</span>
          {item.requestId ? <span>{item.requestId}</span> : null}
        </div>
      </div>
    );
  }

  if (kind === 'runtime' && item.payload !== undefined) {
    return (
      <div className="timeline-details">
        {item.content ? (
          <Text as="p" size="2" className="timeline-detail-summary" color="gray">
            {item.content}
          </Text>
        ) : null}
        <div className="timeline-detail-block">
          <span>Payload</span>
          <pre>{formatTimelineValue(item.payload)}</pre>
        </div>
      </div>
    );
  }

  const content = item.content || timelinePayloadPreview(item);
  if (kind === 'user' || kind === 'agent') {
    return <MarkdownContent content={content} className="transcript-content" />;
  }
  return (
    <Text
      as="p"
      size="2"
      className="timeline-detail-summary"
      color={kind === 'runtime' ? 'gray' : undefined}
    >
      {content}
    </Text>
  );
}

function HitlResponseCard({
  item,
  hitlType,
  onRespond,
  canRespond,
  a2uiActionView,
  approvalRequest,
}: {
  item: AgentTimelineItem;
  hitlType: HitlType;
  onRespond: (submission: HitlResponseSubmission) => Promise<void>;
  canRespond: boolean;
  a2uiActionView?: A2UIActionView;
  approvalRequest?: DesktopApprovalRequest;
}) {
  const { t } = useI18n();
  const [answer, setAnswer] = useState('');
  const [envValues, setEnvValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const requestId = timelineHitlRequestId(item);
  const options = timelineHitlOptions(item);
  const fields = timelineHitlFields(item);
  const answered = Boolean(item.answered) || submitted;
  const authorityDisabled = !answered && !canRespond;
  const allowCustom =
    item.allowCustom ?? booleanPayloadField(item, 'allow_custom') ?? options.length === 0;
  const question = timelineHitlQuestion(item);
  const approvalValidation = approvalRequest
    ? validateApprovalRequest(approvalRequest)
    : null;

  const submit = async (responseData: Record<string, unknown>) => {
    if (!requestId || answered || busy || authorityDisabled) return;
    setBusy(true);
    setSubmitError(null);
    try {
      const expectedRevision = approvalRequest?.run_revision;
      await onRespond({
        requestId,
        hitlType,
        responseData,
        ...(typeof expectedRevision === 'number' ? { expectedRevision } : {}),
        idempotencyKey: [requestId, expectedRevision ?? 'unversioned', hitlType].join(':'),
      });
      setSubmitted(true);
    } catch (caught) {
      setSubmitError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const submitApproval = async (action: 'approve' | 'request_changes') => {
    if (!approvalRequest || answered || busy || authorityDisabled) return;
    setBusy(true);
    setSubmitError(null);
    try {
      await onRespond(approvalResponseSubmission(approvalRequest, action));
      setSubmitted(true);
    } catch (caught) {
      setSubmitError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="timeline-details">
      <Text as="p" size="2" className="timeline-detail-summary">
        {question}
      </Text>
      <div className="agent-run-meta">
        <span>{answered ? 'Answered' : 'Waiting for input'}</span>
        {requestId ? <span>{requestId}</span> : <span>Missing request id</span>}
      </div>

      {authorityDisabled ? (
        <Text size="1" color="amber">
          {t('session.authorityActionUnavailable')}
        </Text>
      ) : null}

      {approvalRequest?.decision ? (
        <div className="timeline-approval-evidence">
          <div>
            <span>{t('approval.action')}</span>
            <strong>{approvalRequest.decision.action.label}</strong>
          </div>
          <div>
            <span>{t('approval.target')}</span>
            <strong>
              {approvalRequest.decision.target.kind} · {approvalRequest.decision.target.id}
            </strong>
          </div>
          <div>
            <span>{t('approval.agentRisk')}</span>
            <strong>{approvalRequest.decision.risk.level}</strong>
          </div>
          <div>
            <span>{t('approval.scope')}</span>
            <strong>
              {approvalRequest.decision.scope.kind} ·{' '}
              {approvalRequest.decision.scope.ids.join(', ')}
            </strong>
          </div>
          <p>{approvalRequest.decision.reason}</p>
          <small>
            {t('approval.requestIdentity', {
              requestId: approvalRequest.id,
              revision: approvalRequest.run_revision ?? '—',
            })}
          </small>
        </div>
      ) : !answered && (hitlType === 'permission' || hitlType === 'decision') ? (
        <Text size="1" color="red">
          {t('approval.incomplete', {
            fields: 'action, target, data, reason, risk, reversibility, scope, evidence',
          })}
        </Text>
      ) : null}

      {!answered && hitlType === 'permission' ? (
        <Flex gap="2" wrap="wrap">
          <Button
            size="1"
            color="green"
            disabled={authorityDisabled || !requestId || busy || !approvalValidation?.canApprove}
            loading={busy}
            onClick={() => void submitApproval('approve')}
          >
            Allow once
          </Button>
          <Button
            size="1"
            color="red"
            variant="soft"
            disabled={authorityDisabled || !requestId || busy}
            onClick={() =>
              void (approvalRequest
                ? submitApproval('request_changes')
                : submit({ granted: false, action: 'deny' }))
            }
          >
            Deny
          </Button>
        </Flex>
      ) : null}

      {!answered && hitlType === 'env_var' ? (
        <div className="timeline-detail-block">
          <span>Environment values</span>
          {fields.map((field) => (
            <label key={field.name}>
              <span>{field.label}</span>
              <input
                type="password"
                autoComplete="off"
                disabled={authorityDisabled || busy}
                required={field.required}
                value={envValues[field.name] ?? ''}
                onChange={(event) =>
                  setEnvValues((current) => ({
                    ...current,
                    [field.name]: event.currentTarget.value,
                  }))
                }
              />
            </label>
          ))}
          <Button
            size="1"
            disabled={
              !requestId ||
              authorityDisabled ||
              busy ||
              fields.length === 0 ||
              fields.some((field) => field.required && !envValues[field.name]?.trim())
            }
            loading={busy}
            onClick={() => void submit({ values: envValues })}
          >
            Submit securely
          </Button>
        </div>
      ) : null}

      {!answered && (hitlType === 'clarification' || hitlType === 'decision') ? (
        <div className="timeline-detail-block">
          {options.length ? (
            <Flex gap="2" wrap="wrap">
              {options.map((option) => (
                <Button
                  size="1"
                  variant="soft"
                  disabled={authorityDisabled || !requestId || busy}
                  title={option.description}
                  key={option.value}
                  onClick={() =>
                    void submit(
                      hitlType === 'clarification'
                        ? { answer: option.value }
                        : { decision: option.value },
                    )
                  }
                >
                  {option.label}
                </Button>
              ))}
            </Flex>
          ) : null}
          {allowCustom ? (
            <>
              <TextArea
                size="1"
                value={answer}
                disabled={authorityDisabled || busy}
                placeholder={hitlType === 'decision' ? 'Enter a decision' : 'Enter your answer'}
                onChange={(event) => setAnswer(event.currentTarget.value)}
              />
              <Button
                size="1"
                disabled={authorityDisabled || !requestId || busy || !answer.trim()}
                loading={busy}
                onClick={() =>
                  void submit(
                    hitlType === 'clarification'
                      ? { answer: answer.trim() }
                      : { decision: answer.trim() },
                  )
                }
              >
                Submit response
              </Button>
            </>
          ) : null}
        </div>
      ) : null}

      {!answered && hitlType === 'a2ui_action' ? (
        a2uiActionView?.actions.length ? (
          <Flex gap="2" wrap="wrap">
            {a2uiActionView.actions.map((action) => (
              <Button
                size="1"
                variant="soft"
                disabled={authorityDisabled || !requestId || busy}
                loading={busy}
                key={`${action.sourceComponentId}:${action.actionName}`}
                onClick={() =>
                  void submit({
                    action_name: action.actionName,
                    source_component_id: action.sourceComponentId,
                    context: {},
                  })
                }
              >
                {action.label}
              </Button>
            ))}
          </Flex>
        ) : (
          <Text size="1" color="amber">
            {a2uiActionView?.reason ??
              'This interactive A2UI request requires its original surface.'}{' '}
            Open the Web client to respond.
          </Text>
        )
      ) : null}

      {submitError ? (
        <Text size="1" color="red" role="alert">
          {submitError}
        </Text>
      ) : null}
    </div>
  );
}

function timelineHitlType(item: AgentTimelineItem): HitlType | null {
  if (item.type === 'clarification_asked') return 'clarification';
  if (item.type === 'decision_asked') return 'decision';
  if (item.type === 'env_var_requested') return 'env_var';
  if (item.type === 'permission_asked' || item.type === 'permission_requested') {
    return 'permission';
  }
  if (item.type === 'a2ui_action_asked') return 'a2ui_action';
  return null;
}

function timelineHitlRequestId(item: AgentTimelineItem): string {
  if (item.requestId) return item.requestId;
  const direct = item.request_id;
  if (typeof direct === 'string') return direct;
  return stringPayloadField(item, 'request_id') ?? '';
}

function timelineHitlQuestion(item: AgentTimelineItem): string {
  if (item.question) return item.question;
  return (
    stringPayloadField(item, 'question') ??
    stringPayloadField(item, 'message') ??
    item.reason ??
    stringPayloadField(item, 'reason') ??
    item.description ??
    stringPayloadField(item, 'description') ??
    'The Agent is waiting for human input.'
  );
}

function timelineHitlOptions(
  item: AgentTimelineItem,
): Array<{ value: string; label: string; description?: string }> {
  const payload = isRecord(item.payload) ? item.payload : {};
  const source = Array.isArray(item.options)
    ? item.options
    : Array.isArray(payload.options)
      ? payload.options
      : [];
  return source.flatMap((option) => {
    if (typeof option === 'string') return [{ value: option, label: option }];
    if (!isRecord(option)) return [];
    const value = firstString(option, ['id', 'value', 'option_id', 'label']);
    if (!value) return [];
    return [
      {
        value,
        label: firstString(option, ['label', 'title', 'name']) ?? value,
        description: firstString(option, ['description', 'detail']) ?? undefined,
      },
    ];
  });
}

function timelineHitlFields(
  item: AgentTimelineItem,
): Array<{ name: string; label: string; required: boolean }> {
  const payload = isRecord(item.payload) ? item.payload : {};
  const source = Array.isArray(item.fields)
    ? item.fields
    : Array.isArray(payload.fields)
      ? payload.fields
      : [];
  return source.flatMap((field) => {
    if (typeof field === 'string') return [{ name: field, label: field, required: true }];
    if (!isRecord(field)) return [];
    const name = firstString(field, ['name', 'key', 'variable']);
    if (!name) return [];
    return [
      {
        name,
        label: firstString(field, ['label', 'description']) ?? name,
        required: field.required !== false,
      },
    ];
  });
}

function stringPayloadField(item: AgentTimelineItem, key: string): string | null {
  if (!isRecord(item.payload)) return null;
  const value = item.payload[key];
  return typeof value === 'string' && value ? value : null;
}

function booleanPayloadField(item: AgentTimelineItem, key: string): boolean | null {
  if (!isRecord(item.payload)) return null;
  const value = item.payload[key];
  return typeof value === 'boolean' ? value : null;
}

function firstString(record: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value) return value;
  }
  return null;
}

function MarkdownContent({ content, className }: { content: string; className: string }) {
  return (
    <div className={`markdown-content ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}

function ToolFileMetadataView({ metadata }: { metadata: ToolFileMetadata }) {
  const paths = Array.isArray(metadata.paths) ? metadata.paths : [];
  const matches = Array.isArray(metadata.matches) ? metadata.matches : [];
  return (
    <div className="tool-file-metadata">
      <div className="tool-file-metadata-head">
        <span>{metadata.operation || 'file'}</span>
        {typeof metadata.matchCount === 'number' ? <em>{metadata.matchCount} matches</em> : null}
        {metadata.truncated ? <em>truncated</em> : null}
      </div>
      {metadata.diffStat ? (
        <div className="tool-file-diffstat">
          <span>{metadata.diffStat.filesChanged ?? 0} files</span>
          <span>+{metadata.diffStat.additions ?? 0}</span>
          <span>-{metadata.diffStat.deletions ?? 0}</span>
        </div>
      ) : null}
      {paths.length ? (
        <div className="tool-file-list">
          {paths.slice(0, 8).map((path, index) => (
            <div className="tool-file-row" key={`${path.path ?? path.relativePath ?? index}`}>
              <CodeIcon />
              <span>{path.relativePath || path.path || 'file'}</span>
              <em>{filePathMetaLabel(path)}</em>
            </div>
          ))}
        </div>
      ) : null}
      {matches.length ? (
        <div className="tool-file-matches">
          {matches.slice(0, 6).map((match, index) => (
            <div className="tool-match-row" key={`${match.path ?? 'match'}:${match.lineNumber ?? index}`}>
              <span>
                {match.path}
                {typeof match.lineNumber === 'number' ? `:${match.lineNumber}` : ''}
              </span>
              {match.preview ? <em>{match.preview}</em> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ChatWorkflowStrip({
  activeTarget,
  workflowCounts,
  onSelect,
}: {
  activeTarget: ChatWorkflowTarget;
  workflowCounts?: Partial<Record<ChatWorkflowTarget, number | string>>;
  onSelect: (target: ChatWorkflowTarget) => void;
}) {
  const items: Array<[ChatWorkflowTarget, string, string, ReactNode]> = [
    ['changes', 'Changes', '+0 -0', <CodeIcon key="changes" />],
    ['pull', 'PR', 'idle', <ReaderIcon key="pull" />],
    ['plan', 'Plan', 'idle', <ActivityLogIcon key="plan" />],
    ['background', 'Background', '0', <DotsHorizontalIcon key="background" />],
    ['artifacts', 'Artifacts', '0', <ArchiveIcon key="artifacts" />],
  ];

  return (
    <div className="composer-workflows chat-composer-workflows" aria-label="chat workflow shortcuts">
      {items.map(([target, label, value, icon]) => (
        <button
          className={activeTarget === target ? 'selected' : ''}
          type="button"
          aria-label={`${label} ${workflowCounts?.[target] ?? value}`}
          key={target}
          onClick={() => onSelect(target)}
        >
          <span>{icon}</span>
          <strong>{label}</strong>
          <em>{workflowCounts?.[target] ?? value}</em>
        </button>
      ))}
    </div>
  );
}

function messageSenderLabel(message: WorkspaceMessage): string {
  const sender = (message.sender_type ?? '').toLowerCase();
  if (sender === 'human' || sender === 'user') return 'You';
  if (sender === 'runtime' || sender === 'system') return 'System';
  return message.sender_type ?? 'Agent';
}

function messageKind(message: WorkspaceMessage): 'user' | 'agent' | 'runtime' {
  const sender = (message.sender_type ?? '').toLowerCase();
  if (sender === 'human' || sender === 'user') return 'user';
  if (sender === 'runtime' || sender === 'system') return 'runtime';
  return 'agent';
}

function timelineKind(item: AgentTimelineItem): TimelineKind {
  if (item.role === 'user' || item.type === 'user_message') return 'user';
  if (item.role === 'assistant' || item.type === 'assistant_message') return 'agent';
  if (item.type === 'act' || item.type === 'observe') return 'tool';
  if (item.type.startsWith('artifact_')) return 'artifact';
  return 'runtime';
}

function timelineToolDisplay(item: AgentTimelineItem): ToolDisplayData | null {
  if (isRecord(item.display)) return item.display as ToolDisplayData;
  const output = isRecord(item.toolOutput) ? item.toolOutput : null;
  const display = output?.display;
  return isRecord(display) ? (display as ToolDisplayData) : null;
}

function timelineFileMetadata(item: AgentTimelineItem): ToolFileMetadata | null {
  if (isRecord(item.fileMetadata)) return item.fileMetadata as ToolFileMetadata;
  const output = isRecord(item.toolOutput) ? item.toolOutput : null;
  const metadata = output?.fileMetadata ?? output?.file_metadata;
  return isRecord(metadata) ? (metadata as ToolFileMetadata) : null;
}

function timelineTitle(item: AgentTimelineItem): string {
  if (item.role === 'user' || item.type === 'user_message') return 'You';
  if (item.role === 'assistant' || item.type === 'assistant_message') return 'Agent';
  const display = timelineToolDisplay(item);
  if (display?.title) return display.title;
  if (item.type === 'thought') return 'Thought';
  if (item.type === 'act') return 'Tool call';
  if (item.type === 'observe') return 'Tool result';
  if (item.type === 'work_plan') return 'Work plan';
  if (item.type.startsWith('task_')) return 'Task';
  if (item.type.startsWith('artifact_')) return 'Artifact';
  if (timelineHitlType(item)) return 'Human input';
  if (item.type.startsWith('subagent_')) return 'Subagent';
  if (item.type.startsWith('chain_')) return 'Chain';
  if (item.type.startsWith('agent_')) return 'Agent event';
  return 'Event';
}

function timelineIcon(kind: TimelineKind, item: AgentTimelineItem): ReactNode {
  if (item.isError || item.error) return <DotsHorizontalIcon />;
  if (kind === 'tool') return <CodeIcon />;
  if (kind === 'artifact') return <ArchiveIcon />;
  if (item.type === 'thought' || item.type === 'work_plan') return <ActivityLogIcon />;
  return <DotsHorizontalIcon />;
}

function isImportantTimelineItem(item: AgentTimelineItem): boolean {
  const kind = timelineKind(item);
  if (kind === 'user' || kind === 'agent') return true;
  if (item.isError || item.error) return true;
  if (timelineHitlType(item) && !item.answered) return true;
  if (item.type === 'work_plan') return true;
  if (item.type.startsWith('task_')) return true;
  if (item.type === 'artifact_error') return true;
  return false;
}

function timelineHasDetails(item: AgentTimelineItem, kind: TimelineKind): boolean {
  if (kind === 'user' || kind === 'agent') return false;
  if (timelineToolDisplay(item) || timelineFileMetadata(item)) return true;
  if (timelineHitlType(item) || item.question || item.error || item.content) return true;
  if (item.toolInput !== undefined || item.toolOutput !== undefined) return true;
  if (item.payload !== undefined) return true;
  if (item.filename || item.artifactId) return true;
  return false;
}

function timelineSummary(item: AgentTimelineItem, kind: TimelineKind): string {
  if (item.error) return item.error;
  if (timelineHitlType(item)) return timelineHitlQuestion(item);
  if (kind === 'artifact') return item.filename || item.artifactId || item.type;
  if (kind === 'tool') {
    const display = timelineToolDisplay(item);
    if (display?.summary) return display.summary;
    const fileSummary = timelineFileMetadataSummary(timelineFileMetadata(item));
    if (fileSummary) {
      return item.toolName ? `${item.toolName} ${fileSummary}` : fileSummary;
    }
    const source = item.toolOutput ?? item.toolInput ?? item.payload ?? item.content;
    const summary = compactTimelineValue(source);
    return item.toolName ? `${item.toolName}${summary ? ` ${summary}` : ''}` : summary || item.type;
  }
  if (item.content) return compactTimelineValue(item.content);
  if (item.payload !== undefined) return compactTimelineValue(item.payload);
  return item.type;
}

function timelineStatus(item: AgentTimelineItem): TimelineStatus | null {
  if (item.isError || item.error) return { kind: 'error', label: 'error' };
  const displayStatus = timelineToolDisplay(item)?.status;
  if (displayStatus) return { kind: item.type === 'act' ? 'waiting' : 'ok', label: displayStatus };
  if (timelineHitlType(item)) {
    return item.answered
      ? { kind: 'ok', label: 'answered' }
      : { kind: 'waiting', label: 'waiting' };
  }
  if (item.type === 'act') return { kind: 'waiting', label: 'call' };
  if (item.type === 'observe') return { kind: 'ok', label: 'result' };
  if (item.type === 'artifact_ready') return { kind: 'ok', label: 'ready' };
  return null;
}

function timelineDetailLineCount(item: AgentTimelineItem, kind: TimelineKind): number {
  const values: string[] = [];
  if (item.content) values.push(item.content);
  if (timelineToolDisplay(item)?.summary) values.push(timelineToolDisplay(item)?.summary ?? '');
  if (timelineFileMetadata(item)) values.push(formatTimelineValue(timelineFileMetadata(item)));
  if (item.toolInput !== undefined) values.push(formatTimelineValue(item.toolInput));
  if (item.toolOutput !== undefined) values.push(formatTimelineValue(item.toolOutput));
  if (item.payload !== undefined) values.push(formatTimelineValue(item.payload));
  if (item.question) values.push(item.question);
  if (item.error) values.push(item.error);
  if (kind === 'artifact') values.push(item.filename || item.artifactId || '');
  return values
    .join('\n')
    .split('\n')
    .filter((line) => line.trim().length > 0).length;
}

function timelineFileMetadataSummary(metadata: ToolFileMetadata | null): string {
  if (!metadata) return '';
  const paths = Array.isArray(metadata.paths) ? metadata.paths : [];
  const pathLabel =
    paths.length === 1
      ? paths[0].relativePath || paths[0].path
      : paths.length > 1
        ? `${paths.length} files`
        : '';
  const matchLabel =
    typeof metadata.matchCount === 'number' ? `${metadata.matchCount} matches` : '';
  const truncated = metadata.truncated ? 'truncated' : '';
  return [metadata.operation, pathLabel, matchLabel, truncated].filter(Boolean).join(' · ');
}

function filePathMetaLabel(path: NonNullable<ToolFileMetadata['paths']>[number]): string {
  const parts: string[] = [];
  if (typeof path.lineStart === 'number' && typeof path.lineEnd === 'number') {
    parts.push(path.lineStart === path.lineEnd ? `L${path.lineStart}` : `L${path.lineStart}-${path.lineEnd}`);
  } else if (typeof path.lineCount === 'number') {
    parts.push(`${path.lineCount} lines`);
  }
  if (typeof path.bytesWritten === 'number') parts.push(`${path.bytesWritten} B written`);
  if (typeof path.bytesRead === 'number') parts.push(`${path.bytesRead} B read`);
  if (path.created) parts.push('created');
  if (path.changed) parts.push('changed');
  if (path.deleted) parts.push('deleted');
  return parts.join(' · ');
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function formatTimelineTime(item: AgentTimelineItem): string {
  const value =
    typeof item.timestamp === 'number'
      ? item.timestamp
      : typeof item.eventTimeUs === 'number'
        ? Math.floor(item.eventTimeUs / 1000)
        : null;
  if (!value) return '';
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function timelinePayloadPreview(item: AgentTimelineItem): string {
  if (item.payload === undefined || item.payload === null) return timelineTitle(item);
  return formatTimelineValue(item.payload);
}

function compactTimelineValue(value: unknown, maxLength = 180): string {
  if (value === undefined || value === null) return '';
  const rendered = typeof value === 'string' ? value : formatTimelineValue(value);
  const compacted = rendered.replace(/\s+/g, ' ').trim();
  if (compacted.length <= maxLength) return compacted;
  return `${compacted.slice(0, maxLength - 1)}…`;
}

function formatTimelineValue(value: unknown): string {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function agentSignalLabel(status: AgentTaskSignalStatus): string {
  if (status === 'saving') return 'Saving';
  if (status === 'queued') return 'Sent';
  if (status === 'acknowledged') return 'Accepted';
  return 'Needs attention';
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
