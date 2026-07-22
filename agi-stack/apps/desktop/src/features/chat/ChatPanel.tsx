import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Badge, Button, Flex, Heading, ScrollArea, Text, TextArea } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  ArrowTopRightIcon,
  ArrowUpIcon,
  ChevronDownIcon,
  CodeIcon,
  Cross2Icon,
  MixerHorizontalIcon,
  ReloadIcon,
  RocketIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import { sessionActivitySummary } from '../session/sessionNarrativeModel';
import type {
  SessionActivityPresence,
  SessionActivityStructuredEvidence,
} from '../session/sessionNarrativeModel';
import {
  classifySessionTimelineWindowChange,
  isSessionTimelinePinnedToLatest,
  shouldFollowSessionTimeline,
} from '../session/sessionTimelineScrollModel';
import type { SessionTimelineWindow } from '../session/sessionTimelineScrollModel';
import type {
  AgentTimelineItem,
  AgentConversation,
  ComposerContextItem,
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
import { ComposerPlusMenu, type ComposerCatalogClient } from './ComposerPlusMenu';
import type { ComposerModelOption } from './ComposerControls';
import { AgentTimeline, TIMELINE_RENDER_STEP } from './ChatTimeline';
import {
  isImportantTimelineItem,
  isTimelineItemInitiallyExpanded,
} from './chatTimelinePresentation';
import { SessionEmptyState, WorkspaceTranscriptMessage } from './ChatTranscript';
import { ChatWorkflowStrip } from './ChatWorkflowStrip';
import type { ChatWorkflowTarget } from './ChatWorkflowStrip';
import {
  appendComposerContextItem,
  chatComposerPresentation,
  composerHasSendableAttachment,
} from './chatComposerModel';
import type { ChatComposerVariant } from './chatComposerModel';
import { latestAgentSuggestions } from './chatTimelineModel';
import './ChatPanel.css';
import './ComposerMenus.css';

export type { ChatWorkflowTarget } from './ChatWorkflowStrip';

type ChatAuthorityNotice = {
  tone: 'loading' | 'warning' | 'error';
  title: string;
  description: string;
  actionLabel?: string;
} | null;

type ChatPanelProps = {
  api: ComposerCatalogClient;
  conversations: readonly AgentConversation[];
  selectedConversationId?: string | null;
  messages: WorkspaceMessage[];
  timelineState: ConversationTimelineState | null;
  agentTaskSignals: AgentTaskSignal[];
  workflowCounts?: Partial<Record<ChatWorkflowTarget, number | string>>;
  sessionTitle: string;
  scopeLabel: string;
  activityPresence: SessionActivityPresence;
  activityStructuredEvidence: SessionActivityStructuredEvidence | null;
  composerVariant?: ChatComposerVariant;
  composerResetKey: string;
  initialInput?: string;
  sending: boolean;
  disabledReason: string | null;
  activeWorkflowTarget: ChatWorkflowTarget;
  modelLabel?: string;
  modelOptions?: readonly ComposerModelOption[];
  selectedModelValue?: string | null;
  modelSwitching?: boolean;
  modelError?: string | null;
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
  onRunInputDeliveryChange: (delivery: RunInputDelivery) => void;
  onPromoteRunInput: (input: DesktopRunInput) => void;
  onRemoveReference: (reference: CodeRangeReference) => void;
  onSend: (
    content: string,
    contextItems: ComposerContextItem[],
    onWorkspaceMessageSaved?: () => void,
  ) => void;
  onRefresh: () => void;
  onLoadEarlier: () => void;
  onRespondToHitl: (submission: HitlResponseSubmission) => Promise<void>;
  respondableHitlRequestIds: readonly string[];
  authorityNotice?: ChatAuthorityNotice;
  onAuthorityAction?: () => void;
  onWorkflowSelect: (target: ChatWorkflowTarget) => void;
  onRuntimeTargetChange?: (value: string) => void;
  onModelChange?: (value: string) => Promise<void>;
  onModelReset?: () => Promise<void>;
  onOpenMCPAppResult?: (item: AgentTimelineItem) => void;
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

type EarlierTimelineScrollAnchor = {
  conversationId: string;
  anchorId: string | null;
  anchorMemberId: string | null;
  anchorOffset: number;
  top: number;
};

function timelineAnchorMemberIds(anchor: HTMLElement): string[] {
  const serialized = anchor.dataset.timelineAnchorMembers;
  if (!serialized) return [];
  try {
    const parsed: unknown = JSON.parse(serialized);
    return Array.isArray(parsed) && parsed.every((value) => typeof value === 'string')
      ? parsed
      : [];
  } catch {
    return [];
  }
}

export const ChatPanel = memo(function ChatPanel({
  api,
  conversations,
  selectedConversationId,
  messages,
  timelineState,
  agentTaskSignals,
  workflowCounts,
  sessionTitle,
  scopeLabel,
  activityPresence,
  activityStructuredEvidence,
  composerVariant = 'workspace',
  composerResetKey,
  initialInput,
  sending,
  disabledReason,
  activeWorkflowTarget,
  modelLabel,
  modelOptions,
  selectedModelValue,
  modelSwitching,
  modelError,
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
  onModelChange,
  onModelReset,
  onOpenMCPAppResult,
  onOpenCommands,
}: ChatPanelProps) {
  const { t } = useI18n();
  const disabled = Boolean(disabledReason);
  const composerPresentation = chatComposerPresentation(composerVariant);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const scrollAnchorRef = useRef<HTMLDivElement>(null);
  const timelineWindowRef = useRef<SessionTimelineWindow | null>(null);
  const workspaceTailKeyRef = useRef<string | null>(null);
  const pinnedToLatestRef = useRef(true);
  const earlierScrollRef = useRef<EarlierTimelineScrollAnchor | null>(null);
  const [expandedTimelineItems, setExpandedTimelineItems] = useState<Record<string, boolean>>({});
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  const signalStateKey = useMemo(
    () => agentTaskSignals.map((signal) => `${signal.id}:${signal.status}`).join('|'),
    [agentTaskSignals],
  );
  const timelineItemCount = timelineState?.items.length ?? 0;
  const timelineConversationId = timelineState?.conversationId ?? '';
  const timelineFirstId = timelineState?.items[0]?.id ?? '';
  const agentSuggestions = useMemo(
    () => latestAgentSuggestions(timelineState?.items ?? []),
    [timelineState?.items],
  );
  const timelineTailItem = timelineState?.items[timelineItemCount - 1];
  const timelineLastId = timelineTailItem?.id ?? '';
  const timelineTailRevision =
    timelineTailItem?.content ?? timelineTailItem?.display?.summary ?? timelineTailItem?.error ?? '';
  const timelineHasMore = timelineState?.hasMore ?? false;
  const timelineLoading = timelineState?.loading ?? false;
  const timelineLoadingEarlier = timelineState?.loadingEarlier ?? false;
  const [earlierTimelineRender, setEarlierTimelineRender] = useState({
    conversationId: '',
    allowance: 0,
  });
  const timelineEarlierAllowance =
    earlierTimelineRender.conversationId === timelineConversationId
      ? earlierTimelineRender.allowance
      : 0;
  const timelineError = timelineState?.error ?? null;
  const timelineItems = timelineState?.items ?? null;
  const hasTimelineState = timelineState !== null;
  const workspaceFirstMessageId = messages[0]?.id ?? '';
  const workspaceLastMessageId = messages[messages.length - 1]?.id ?? '';
  const activitySummary = useMemo(() => {
    if (!timelineItems?.length) return null;
    return sessionActivitySummary({
      items: timelineItems,
      structuredEvidence: activityStructuredEvidence,
    });
  }, [activityStructuredEvidence, timelineItems]);
  const activityEvidence = useMemo(() => {
    if (!activitySummary) return '';
    if (activitySummary.evidence.kind === 'structured') {
      const { artifactCount, checkCount, toolActivityCount } = activitySummary.evidence;
      if (checkCount === null) {
        return t('session.structuredActivityEvidenceCount', {
          artifactCount,
          toolActivityCount,
        });
      }
      return t('session.structuredEvidenceCount', {
        artifactCount,
        checkCount,
        toolActivityCount,
      });
    }
    if (activitySummary.evidence.kind === 'agent_reported') {
      return t('session.agentReportedEvidence', { evidence: activitySummary.evidence.text });
    }
    return t('session.notAvailable');
  }, [activitySummary, t]);
  const scrollToLatest = useCallback(() => {
    scrollAnchorRef.current?.scrollIntoView({ block: 'end' });
  }, []);
  const scrollViewport = useCallback(() => {
    return (
      scrollAreaRef.current?.querySelector<HTMLElement>('[data-radix-scroll-area-viewport]') ??
      scrollAreaRef.current
    );
  }, []);
  const captureEarlierScrollAnchor = useCallback((): EarlierTimelineScrollAnchor | null => {
    const viewport = scrollViewport();
    if (!viewport) return null;
    const viewportTop = viewport.getBoundingClientRect().top;
    const anchors = viewport.querySelectorAll<HTMLElement>('[data-timeline-anchor-id]');
    let visibleAnchor: HTMLElement | null = null;
    let intersectingAnchor: HTMLElement | null = null;
    for (const anchor of anchors) {
      const bounds = anchor.getBoundingClientRect();
      if (bounds.bottom <= viewportTop + 1) continue;
      if (bounds.top >= viewportTop - 1) {
        visibleAnchor = anchor;
        break;
      }
      intersectingAnchor = anchor;
    }
    visibleAnchor ??= intersectingAnchor;
    return {
      conversationId: timelineConversationId,
      anchorId: visibleAnchor?.dataset.timelineAnchorId ?? null,
      anchorMemberId: visibleAnchor ? (timelineAnchorMemberIds(visibleAnchor)[0] ?? null) : null,
      anchorOffset: visibleAnchor ? visibleAnchor.getBoundingClientRect().top - viewportTop : 0,
      top: viewport.scrollTop,
    };
  }, [scrollViewport, timelineConversationId]);
  const followLatest = useCallback(() => {
    pinnedToLatestRef.current = true;
    setShowJumpToLatest(false);
    scrollToLatest();
  }, [scrollToLatest]);

  useEffect(() => {
    if (hasTimelineState) {
      workspaceTailKeyRef.current = null;
      const current: SessionTimelineWindow = {
        conversationId: timelineConversationId,
        firstId: timelineFirstId,
        lastId: timelineLastId,
        tailRevision: timelineTailRevision,
        count: timelineItemCount,
      };
      const change = classifySessionTimelineWindowChange(timelineWindowRef.current, current);
      timelineWindowRef.current = current;
      if (shouldFollowSessionTimeline(change, pinnedToLatestRef.current)) {
        pinnedToLatestRef.current = true;
        setShowJumpToLatest(false);
        window.requestAnimationFrame(scrollToLatest);
      } else if (change === 'appended' || change === 'updated') {
        setShowJumpToLatest(true);
      }
      return;
    } else if (timelineWindowRef.current) {
      timelineWindowRef.current = null;
      pinnedToLatestRef.current = true;
      setShowJumpToLatest(false);
    }

    const workspaceTailKey = [
      sessionTitle,
      workspaceFirstMessageId,
      workspaceLastMessageId,
      messages.length,
      signalStateKey,
    ].join(':');
    const workspaceTailChanged = workspaceTailKeyRef.current !== workspaceTailKey;
    workspaceTailKeyRef.current = workspaceTailKey;
    if (workspaceTailChanged && pinnedToLatestRef.current) {
      window.requestAnimationFrame(scrollToLatest);
    } else if (workspaceTailChanged) {
      setShowJumpToLatest(true);
    }
  }, [
    messages.length,
    scrollToLatest,
    sessionTitle,
    signalStateKey,
    timelineConversationId,
    timelineFirstId,
    timelineItemCount,
    timelineLastId,
    timelineTailRevision,
    hasTimelineState,
    workspaceFirstMessageId,
    workspaceLastMessageId,
  ]);

  useLayoutEffect(() => {
    if (timelineLoadingEarlier) return;
    const snapshot = earlierScrollRef.current;
    if (!snapshot) return;
    earlierScrollRef.current = null;
    if (snapshot.conversationId !== timelineConversationId) return;
    const viewport = scrollViewport();
    if (!viewport) return;
    const candidates = Array.from(
      viewport.querySelectorAll<HTMLElement>('[data-timeline-anchor-id]'),
    );
    const exactAnchor = snapshot.anchorId
      ? candidates.find(
          (candidate) =>
            candidate.dataset.timelineAnchorId === snapshot.anchorId &&
            candidate.getClientRects().length > 0,
        )
      : null;
    const anchor =
      exactAnchor ??
      (snapshot.anchorMemberId
        ? candidates.find(
            (candidate) =>
              candidate.getClientRects().length > 0 &&
              timelineAnchorMemberIds(candidate).includes(snapshot.anchorMemberId ?? ''),
          )
        : null);
    if (!anchor || !snapshot.anchorId) {
      viewport.scrollTop = snapshot.top;
      return;
    }
    const restoreAnchorOffset = () => {
      if (!anchor.isConnected || timelineWindowRef.current?.conversationId !== snapshot.conversationId) {
        return;
      }
      const nextOffset = anchor.getBoundingClientRect().top - viewport.getBoundingClientRect().top;
      viewport.scrollTop += nextOffset - snapshot.anchorOffset;
    };
    restoreAnchorOffset();
    window.requestAnimationFrame(() => {
      restoreAnchorOffset();
      window.requestAnimationFrame(restoreAnchorOffset);
    });
  }, [scrollViewport, timelineConversationId, timelineItemCount, timelineLoadingEarlier, timelineEarlierAllowance]);

  const requestEarlierTimeline = useCallback(() => {
    if (timelineLoading || timelineLoadingEarlier || earlierScrollRef.current) return;
    earlierScrollRef.current = captureEarlierScrollAnchor() ?? {
      conversationId: timelineConversationId,
      anchorId: null,
      anchorMemberId: null,
      anchorOffset: 0,
      top: 0,
    };
    onLoadEarlier();
  }, [
    captureEarlierScrollAnchor,
    onLoadEarlier,
    timelineConversationId,
    timelineLoading,
    timelineLoadingEarlier,
  ]);

  const showEarlierTimelineItems = useCallback(() => {
    earlierScrollRef.current = captureEarlierScrollAnchor() ?? {
      conversationId: timelineConversationId,
      anchorId: null,
      anchorMemberId: null,
      anchorOffset: 0,
      top: 0,
    };
    setEarlierTimelineRender((current) => ({
      conversationId: timelineConversationId,
      allowance:
        (current.conversationId === timelineConversationId ? current.allowance : 0) +
        TIMELINE_RENDER_STEP,
    }));
  }, [captureEarlierScrollAnchor, timelineConversationId]);

  useEffect(() => {
    const viewport = scrollViewport();
    if (!viewport) return undefined;
    const handleScroll = () => {
      const pinnedToLatest = isSessionTimelinePinnedToLatest(viewport);
      pinnedToLatestRef.current = pinnedToLatest;
      setShowJumpToLatest(!pinnedToLatest && viewport.scrollHeight > viewport.clientHeight);

      if (timelineLoadingEarlier && earlierScrollRef.current) {
        const nextAnchor = captureEarlierScrollAnchor();
        if (nextAnchor) earlierScrollRef.current = nextAnchor;
      }

      if (!hasTimelineState || timelineError) return;
      if (!timelineHasMore || timelineLoading || timelineLoadingEarlier) return;
      if (viewport.scrollTop <= 96) requestEarlierTimeline();
    };
    viewport.addEventListener('scroll', handleScroll, { passive: true });
    return () => viewport.removeEventListener('scroll', handleScroll);
  }, [
    captureEarlierScrollAnchor,
    requestEarlierTimeline,
    scrollViewport,
    timelineError,
    timelineHasMore,
    timelineLoading,
    timelineLoadingEarlier,
    hasTimelineState,
  ]);

  useEffect(() => {
    const handleResize = () => {
      if (pinnedToLatestRef.current) window.requestAnimationFrame(scrollToLatest);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [scrollToLatest]);

  const handleComposerSend = useCallback(
    (
      content: string,
      contextItems: ComposerContextItem[],
      onWorkspaceMessageSaved?: () => void,
    ) => {
      pinnedToLatestRef.current = true;
      setShowJumpToLatest(false);
      onSend(content, contextItems, onWorkspaceMessageSaved);
      window.requestAnimationFrame(scrollToLatest);
    },
    [onSend, scrollToLatest],
  );
  const handleSuggestionSelect = useCallback(
    (suggestion: string) => handleComposerSend(suggestion, []),
    [handleComposerSend],
  );
  const toggleTimelineItem = useCallback((item: AgentTimelineItem) => {
    setExpandedTimelineItems((current) => {
      const currentValue = current[item.id] ?? isTimelineItemInitiallyExpanded(item);
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
      <ScrollArea
        className="message-scroll"
        ref={scrollAreaRef}
        aria-label={t('session.timelineScrollRegion')}
        aria-busy={timelineLoading || timelineLoadingEarlier}
        tabIndex={0}
      >
        <div className="message-stack">
          {timelineState ? (
            <>
              {activitySummary ? (
                <section className="session-current-activity" aria-label={t('session.currentActivity')}>
                  <div className="session-current-activity-primary">
                    <span className="session-current-activity-icon" aria-hidden="true">
                      <ActivityLogIcon />
                    </span>
                    <span className="session-current-activity-copy">
                      <small>
                        {t(
                          activityPresence === 'live'
                            ? 'session.currentActivity'
                            : 'session.latestActivity',
                        )}
                      </small>
                      <strong>
                        {activitySummary.titleKey
                          ? t(activitySummary.titleKey)
                          : activitySummary.title || t('session.waitingForActivity')}
                      </strong>
                    </span>
                    <Badge color={activityPresence === 'live' ? 'cyan' : 'gray'} variant="soft">
                      {t(activityPresence === 'live' ? 'session.live' : 'session.recorded')}
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
                onLoadEarlier={requestEarlierTimeline}
                onShowEarlier={showEarlierTimelineItems}
                earlierRenderAllowance={timelineEarlierAllowance}
                onRetry={onRefresh}
                onRespondToHitl={onRespondToHitl}
                respondableHitlRequestIds={respondableHitlRequestIds}
                activityPresence={activityPresence}
                onOpenMCPAppResult={onOpenMCPAppResult}
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
          {agentSuggestions.length > 0 &&
          activityPresence === 'recorded' &&
          !sending &&
          !disabled ? (
            <AgentSuggestionChips
              suggestions={agentSuggestions}
              onSelect={handleSuggestionSelect}
            />
          ) : null}
          <div ref={scrollAnchorRef} aria-hidden="true" />
        </div>
      </ScrollArea>
      {showJumpToLatest ? (
        <Button
          type="button"
          size="1"
          variant="surface"
          className="session-jump-latest"
          onClick={followLatest}
        >
          <ChevronDownIcon aria-hidden="true" />
          {t('session.jumpToLatest')}
        </Button>
      ) : null}
      <ChatComposer
        api={api}
        conversations={conversations}
        selectedConversationId={selectedConversationId}
        key={composerResetKey}
        composerVariant={composerVariant}
        initialInput={initialInput}
        sending={sending}
        disabledReason={disabledReason}
        activeWorkflowTarget={activeWorkflowTarget}
        workflowCounts={workflowCounts}
        runInputDelivery={runInputDelivery}
        runInputDeliveryOptions={runInputDeliveryOptions}
        runInputs={runInputs}
        runInputsLoading={runInputsLoading}
        runInputsError={runInputsError}
        promotingRunInputId={promotingRunInputId}
        runInputAuthorityRunId={runInputAuthorityRunId}
        references={references}
        modelLabel={modelLabel}
        modelOptions={modelOptions}
        selectedModelValue={selectedModelValue}
        modelSwitching={modelSwitching}
        modelError={modelError}
        runtimeTargetLabel={runtimeTargetLabel}
        runtimeTargetOptions={runtimeTargetOptions}
        authorityNotice={authorityNotice}
        onAuthorityAction={onAuthorityAction}
        onRunInputDeliveryChange={onRunInputDeliveryChange}
        onPromoteRunInput={onPromoteRunInput}
        onRemoveReference={onRemoveReference}
        onWorkflowSelect={onWorkflowSelect}
        onRuntimeTargetChange={onRuntimeTargetChange}
        onModelChange={onModelChange}
        onModelReset={onModelReset}
        onOpenCommands={onOpenCommands}
        onSend={handleComposerSend}
      />
    </section>
  );
});

const AgentSuggestionChips = memo(function AgentSuggestionChips({
  suggestions,
  onSelect,
}: {
  suggestions: string[];
  onSelect: (suggestion: string) => void;
}) {
  const { t } = useI18n();
  return (
    <section className="agent-suggestion-list" aria-label={t('chat.suggestedFollowUps')}>
      <p>{t('chat.suggestedFollowUps')}</p>
      <div>
        {suggestions.map((suggestion, index) => (
          <button
            type="button"
            className="agent-suggestion-chip"
            aria-label={t('chat.sendSuggestion', { suggestion })}
            onClick={() => onSelect(suggestion)}
            key={`${index}:${suggestion}`}
          >
            <span>{suggestion}</span>
            <ArrowTopRightIcon aria-hidden="true" />
          </button>
        ))}
      </div>
    </section>
  );
});

type ChatComposerProps = {
  api: ComposerCatalogClient;
  conversations: readonly AgentConversation[];
  selectedConversationId?: string | null;
  composerVariant: ChatComposerVariant;
  initialInput?: string;
  sending: boolean;
  disabledReason: string | null;
  activeWorkflowTarget: ChatWorkflowTarget;
  workflowCounts?: Partial<Record<ChatWorkflowTarget, number | string>>;
  runInputDelivery: RunInputDelivery | null;
  runInputDeliveryOptions: RunInputDelivery[];
  runInputs: DesktopRunInput[];
  runInputsLoading: boolean;
  runInputsError: string | null;
  promotingRunInputId: string | null;
  runInputAuthorityRunId: string | null;
  references: CodeRangeReference[];
  modelLabel?: string;
  modelOptions?: readonly ComposerModelOption[];
  selectedModelValue?: string | null;
  modelSwitching?: boolean;
  modelError?: string | null;
  runtimeTargetLabel?: string;
  runtimeTargetOptions?: string[];
  authorityNotice?: ChatAuthorityNotice;
  onAuthorityAction?: () => void;
  onRunInputDeliveryChange: (delivery: RunInputDelivery) => void;
  onPromoteRunInput: (input: DesktopRunInput) => void;
  onRemoveReference: (reference: CodeRangeReference) => void;
  onWorkflowSelect: (target: ChatWorkflowTarget) => void;
  onRuntimeTargetChange?: (value: string) => void;
  onModelChange?: (value: string) => Promise<void>;
  onModelReset?: () => Promise<void>;
  onOpenCommands: (trigger?: HTMLElement | null) => void;
  onSend: (
    content: string,
    contextItems: ComposerContextItem[],
    onWorkspaceMessageSaved?: () => void,
  ) => void;
};

function ChatComposer({
  api,
  conversations,
  selectedConversationId,
  composerVariant,
  initialInput = '',
  sending,
  disabledReason,
  activeWorkflowTarget,
  workflowCounts,
  runInputDelivery,
  runInputDeliveryOptions,
  runInputs,
  runInputsLoading,
  runInputsError,
  promotingRunInputId,
  runInputAuthorityRunId,
  references,
  modelLabel,
  modelOptions,
  selectedModelValue,
  modelSwitching,
  modelError,
  runtimeTargetLabel,
  runtimeTargetOptions,
  authorityNotice,
  onAuthorityAction,
  onRunInputDeliveryChange,
  onPromoteRunInput,
  onRemoveReference,
  onWorkflowSelect,
  onRuntimeTargetChange,
  onModelChange,
  onModelReset,
  onOpenCommands,
  onSend,
}: ChatComposerProps) {
  const { t } = useI18n();
  const [input, setInput] = useState(initialInput);
  const [contextItems, setContextItems] = useState<ComposerContextItem[]>([]);
  const [uploadingAttachments, setUploadingAttachments] = useState(false);
  const disabled = Boolean(disabledReason);
  const canSend =
    !disabled &&
    !sending &&
    !uploadingAttachments &&
    (Boolean(input.trim()) || composerHasSendableAttachment(contextItems));
  const composerPresentation = chatComposerPresentation(composerVariant);
  const queuedRunInputs = useMemo(() => visibleQueuedRunInputs(runInputs), [runInputs]);
  const handleSend = useCallback(() => {
    if (!canSend) return;
    const content =
      input.trim() ||
      t('composer.attachmentOnlyMessage', {
        filenames: contextItems
          .filter((item) => item.kind === 'attachment')
          .map((item) => item.label)
          .join(', '),
      });
    onSend(content, contextItems, () => {
      setInput('');
      setContextItems([]);
    });
  }, [canSend, contextItems, input, onSend, t]);
  const addContextItem = useCallback((item: ComposerContextItem) => {
    setContextItems((current) => appendComposerContextItem(current, item));
  }, []);

  return (
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
        {contextItems.length ? (
          <div className="composer-context-chips" aria-label={t('composer.addedContext')}>
            {contextItems.map((item) => (
              <button
                type="button"
                key={`${item.kind}:${item.resource_id}`}
                aria-label={t('composer.removeContext', { context: item.label })}
                onClick={() =>
                  setContextItems((current) => current.filter((candidate) => candidate !== item))
                }
              >
                {item.label}
                <Cross2Icon aria-hidden="true" />
              </button>
            ))}
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
          onChange={(event) => setInput(event.target.value)}
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
            <ComposerPlusMenu
              api={api}
              conversations={conversations}
              excludedConversationId={selectedConversationId}
              compact
              onAdd={addContextItem}
              onUploadingChange={setUploadingAttachments}
            />
            <button
              type="button"
              onClick={(event) => onOpenCommands(event.currentTarget)}
            >
              <MixerHorizontalIcon aria-hidden="true" />
              {t('session.context')}
            </button>
            {modelLabel && modelOptions?.length && onModelChange ? (
              <ComposerControls
                modelLabel={modelLabel}
                modelOptions={modelOptions}
                modelValue={selectedModelValue}
                modelPending={modelSwitching}
                modelError={modelError}
                onModelChange={onModelChange}
                onModelReset={onModelReset}
              />
            ) : null}
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
            modelOptions={modelOptions}
            modelValue={selectedModelValue}
            modelPending={modelSwitching}
            modelError={modelError}
            runtimeTargetLabel={runtimeTargetLabel}
            runtimeTargetOptions={runtimeTargetOptions}
            onModelChange={onModelChange}
            onModelReset={onModelReset}
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
