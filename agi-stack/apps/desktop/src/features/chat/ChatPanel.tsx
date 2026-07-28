import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react';
import { Badge, Button, Flex, Heading, ScrollArea, Text, TextArea } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  ArrowTopRightIcon,
  ArrowUpIcon,
  ChevronDownIcon,
  ClockIcon,
  CodeIcon,
  ColumnsIcon,
  Cross2Icon,
  MixerHorizontalIcon,
  ReloadIcon,
  RocketIcon,
  StopIcon,
  UploadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import { socketEventsSince } from '../../hooks/useAgentSocket';
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
  AgentWsEvent,
  ComposerContextItem,
  ConversationTimelineState,
  HitlResponseSubmission,
  CodeRangeReference,
  DesktopRunInput,
  DesktopRuntimeConfig,
  RunInputDelivery,
  RuntimeMode,
  WorkspaceMessage,
} from '../../types';
import { runInputReferenceLabel } from '../session/sessionChangesModel';
import {
  queuedRunInputHandoffState,
  visibleQueuedRunInputs,
} from '../session/sessionRunInputModel';
import { ComposerControls } from './ComposerControls';
import { ComposerPlusMenu } from './ComposerPlusMenu';
import type { ComposerModelOption } from './ComposerControls';
import type { ComposerCatalogClient } from './composerCatalogModel';
import { ConversationComparison, ConversationComparisonPicker } from './ConversationComparison';
import type { ConversationComparisonClient } from './ConversationComparison';
import { ConversationSearch } from './ConversationSearch';
import { ConversationExportMenu } from './ConversationExportMenu';
import { ConversationSummaryCard } from './ConversationSummaryCard';
import { PinnedMessages } from './PinnedMessages';
import { PromptTemplateLibrary } from './PromptTemplateLibrary';
import {
  SavePromptTemplateDialog,
  type SavePromptTemplateTarget,
} from './SavePromptTemplateDialog';
import {
  MessageDeleteDialog,
  type MessageDeleteDialogTarget,
} from './MessageDeleteDialog';
import { AgentTimeline, TIMELINE_RENDER_STEP } from './ChatTimeline';
import {
  isImportantTimelineItem,
  isTimelineItemInitiallyExpanded,
  timelineKind,
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
import {
  composeAheadContextSnapshot,
  composeAheadConversationScope,
  composeAheadEligibility,
  composeAheadQueueStore,
  conversationResponseIsStreaming,
  EMPTY_COMPOSE_AHEAD_QUEUE,
} from './composeAheadModel';
import type { ComposeAheadPrompt } from './composeAheadModel';
import {
  canConfirmMessageDeletion,
  filterHiddenMessages,
  findRetryMessageContent,
  hideMessageInScope,
  messageDeletionFocusNeighborId,
  quoteMessageForComposer,
  resolveRetryDispatch,
} from './chatMessageActionModel';
import type {
  LocalMessageVisibilityState,
  VisibleMessageForRetry,
  VisibleMessageKind,
} from './chatMessageActionModel';
import {
  pinnedMessagesInTimelineOrder,
  reconcilePinnedMessageIds,
  togglePinnedMessageId,
} from './pinnedMessageModel';
import { latestAgentSuggestions, timelineItemsForDisplay } from './chatTimelineModel';
import { createConversationExportSnapshot } from './conversationExportModel';
import {
  conversationComparisonAvailable,
  conversationComparisonScope,
} from './conversationComparisonModel';
import {
  computeTimelineTurns,
  timelineTurnForMember,
} from './timelineTurnCollapseModel';
import { useComposerFileDrop } from './useComposerFileDrop';
import { useComposerFileUpload } from './useComposerFileUpload';
import { useTimelineTurnCollapse } from './useTimelineTurnCollapse';
import { useVoiceCall } from './useVoiceCall';
import { useVoiceTranscription } from './useVoiceTranscription';
import { VoiceCallPanel } from './VoiceCallPanel';
import {
  resolveVoiceCallConnection,
  type VoiceCallConnection,
} from './voiceCallModel';
import type { VoiceCallRuntime } from './voiceCallRuntime';
import {
  applyVoiceTranscriptMessage,
  initialVoiceTranscriptDraft,
  resolveVoiceTranscriptionConnection,
  voiceTranscriptDraftValue,
  voiceTranscriptionFailureKey,
  type VoiceTranscriptionConnection,
} from './voiceTranscriptionModel';
import type { VoiceTranscriptionRuntime } from './voiceTranscriptionRuntime';
import type {
  AgentTaskSignal,
  AgentTaskSignalStatus,
} from './agentTaskSignalModel';
import {
  agentStopRequestSettlesStreaming,
  applyAgentStopEvent,
  beginAgentStopRequest,
  EMPTY_AGENT_STOP_REQUEST,
  reconcileAgentStopScope,
  type AgentStopErrorCode,
  type AgentStopRequestState,
} from './agentStopResponseModel';
import './ChatPanel.css';
import './ComposerMenus.css';

export type { ChatWorkflowTarget } from './ChatWorkflowStrip';
export type { AgentTaskSignal, AgentTaskSignalStatus } from './agentTaskSignalModel';

type ChatAuthorityNotice = {
  tone: 'loading' | 'warning' | 'error';
  title: string;
  description: string;
  actionLabel?: string;
} | null;

const DEFAULT_TURN_COLLAPSE_RUNTIME = {
  mode: 'local',
  apiBaseUrl: 'http://desktop.invalid',
  tenantId: '',
  projectId: '',
} as const;
const EMPTY_AGENT_CONTROL_EVENTS: readonly AgentWsEvent[] = [];

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
  turnCollapseRuntime?: {
    mode: RuntimeMode;
    apiBaseUrl: string;
    tenantId: string;
    projectId: string;
  };
  voiceTranscriptionConfig?: DesktopRuntimeConfig;
  voiceTranscriptionRuntime?: VoiceTranscriptionRuntime;
  voiceCallRuntime?: VoiceCallRuntime;
  activityPresence: SessionActivityPresence;
  activityStructuredEvidence: SessionActivityStructuredEvidence | null;
  composerVariant?: ChatComposerVariant;
  composerResetKey: string;
  initialInput?: string;
  sending: boolean;
  disabledReason: string | null;
  agentControlEvents?: readonly AgentWsEvent[];
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
  onRegenerateConversationSummary?: (conversationId: string) => Promise<void>;
  onStopResponse?: (conversationId: string) => boolean;
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

type EarlierTimelineScrollAnchor = {
  conversationId: string;
  anchorId: string | null;
  anchorMemberId: string | null;
  anchorOffset: number;
  top: number;
};

type ComposerDraftRequest = {
  id: number;
  conversationId: string;
  content: string;
};

type MessageDeleteRequest = MessageDeleteDialogTarget & {
  scopeKey: string;
  returnFocus: HTMLElement;
  focusNeighborId: string | null;
};

function timelineVisibleMessage(
  item: AgentTimelineItem,
  conversationId: string,
): VisibleMessageForRetry | null {
  const kind = timelineKind(item);
  if (kind !== 'user' && kind !== 'agent') return null;
  return {
    id: item.id,
    conversationId,
    kind,
    content: item.content ?? '',
  };
}

function workspaceVisibleMessage(
  message: WorkspaceMessage,
  conversationId: string,
): VisibleMessageForRetry {
  const sender = (message.sender_type ?? '').toLowerCase();
  const kind: VisibleMessageKind =
    sender === 'human' || sender === 'user'
      ? 'user'
      : sender === 'runtime' || sender === 'system'
        ? 'runtime'
        : 'agent';
  return {
    id: message.id,
    conversationId,
    kind,
    content: message.content,
  };
}

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

function equalStringArrays(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
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
  turnCollapseRuntime = DEFAULT_TURN_COLLAPSE_RUNTIME,
  voiceTranscriptionConfig,
  voiceTranscriptionRuntime,
  voiceCallRuntime,
  activityPresence,
  activityStructuredEvidence,
  composerVariant = 'workspace',
  composerResetKey,
  initialInput,
  sending,
  disabledReason,
  agentControlEvents = EMPTY_AGENT_CONTROL_EVENTS,
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
  onRegenerateConversationSummary,
  onStopResponse,
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
  const [composerDraftRequest, setComposerDraftRequest] =
    useState<ComposerDraftRequest | null>(null);
  const [messageActionNotice, setMessageActionNotice] = useState<string | null>(null);
  const [saveTemplateRequest, setSaveTemplateRequest] =
    useState<SavePromptTemplateTarget | null>(null);
  const [messageDeleteRequest, setMessageDeleteRequest] =
    useState<MessageDeleteRequest | null>(null);
  const [localMessageVisibility, setLocalMessageVisibility] =
    useState<LocalMessageVisibilityState | null>(null);
  const [promptTemplateRefreshToken, setPromptTemplateRefreshToken] = useState(0);
  const [retryingMessageId, setRetryingMessageId] = useState<string | null>(null);
  const [conversationSearchVisible, setConversationSearchVisible] = useState(false);
  const [conversationComparisonVisible, setConversationComparisonVisible] = useState(false);
  const [conversationComparisonPickerOpen, setConversationComparisonPickerOpen] = useState(false);
  const [comparisonConversation, setComparisonConversation] = useState<AgentConversation | null>(
    null,
  );
  const [pinnedMessageIds, setPinnedMessageIds] = useState<string[]>([]);
  const [pinnedMessagesCollapsed, setPinnedMessagesCollapsed] = useState(false);
  const [stopRequest, setStopRequest] =
    useState<AgentStopRequestState>(EMPTY_AGENT_STOP_REQUEST);
  const composerDraftSequenceRef = useRef(0);
  const retryDispatchLockRef = useRef<string | null>(null);
  const retryDispatchSawSendingRef = useRef(false);
  const retryUnlockTimerRef = useRef<number | null>(null);
  const pinnedJumpTimerRef = useRef<number | null>(null);
  const pinnedJumpFrameRef = useRef<number | null>(null);
  const pinnedJumpTargetRef = useRef<HTMLElement | null>(null);
  const comparisonTriggerRef = useRef<HTMLButtonElement>(null);
  const stopEventHeadRef = useRef<AgentWsEvent | null>(null);
  const agentControlEventsRef = useRef(agentControlEvents);
  agentControlEventsRef.current = agentControlEvents;
  const sendingRef = useRef(sending);
  sendingRef.current = sending;
  const visibleAgentTaskSignals = useMemo(() => {
    const timelineFailureIds = new Set(
      (timelineState?.items ?? []).flatMap((item) => {
        if (item.type !== 'error' && item.isError !== true) return [];
        return [item.executionMessageId, item.message_id].filter(
          (value): value is string => typeof value === 'string' && value.length > 0,
        );
      }),
    );
    return agentTaskSignals.filter(
      (signal) =>
        signal.status === 'failed' &&
        (!signal.messageId || !timelineFailureIds.has(signal.messageId)),
    );
  }, [agentTaskSignals, timelineState?.items]);
  const signalStateKey = useMemo(
    () => visibleAgentTaskSignals.map((signal) => `${signal.id}:${signal.status}`).join('|'),
    [visibleAgentTaskSignals],
  );
  const timelineItemCount = timelineState?.items.length ?? 0;
  const timelineConversationId = timelineState?.conversationId ?? '';
  const timelineFirstId = timelineState?.items[0]?.id ?? '';
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
  const messageActionConversationId =
    timelineConversationId || selectedConversationId || messages[0]?.workspace_id || '';
  const messageActionConversation =
    conversations.find((conversation) => conversation.id === messageActionConversationId) ?? null;
  const messageActionScopeKey = `${messageActionConversation?.tenant_id ?? ''}:${
    messageActionConversation?.project_id ?? ''
  }:${messageActionConversationId}`;
  const visibleTimelineItems = useMemo(
    () =>
      filterHiddenMessages(
        timelineItems ?? [],
        localMessageVisibility,
        messageActionScopeKey,
      ),
    [localMessageVisibility, messageActionScopeKey, timelineItems],
  );
  const visibleWorkspaceMessages = useMemo(
    () => filterHiddenMessages(messages, localMessageVisibility, messageActionScopeKey),
    [localMessageVisibility, messageActionScopeKey, messages],
  );
  const visibleTimelineState = useMemo(
    () =>
      timelineState
        ? {
            ...timelineState,
            items: visibleTimelineItems,
          }
        : null,
    [timelineState, visibleTimelineItems],
  );
  const agentSuggestions = useMemo(
    () => latestAgentSuggestions(visibleTimelineItems),
    [visibleTimelineItems],
  );
  const turnCollapseScope = useMemo(
    () => ({
      ...turnCollapseRuntime,
      tenantId: messageActionConversation?.tenant_id || turnCollapseRuntime.tenantId,
      projectId: messageActionConversation?.project_id || turnCollapseRuntime.projectId,
      conversationId: messageActionConversationId,
    }),
    [messageActionConversation, messageActionConversationId, turnCollapseRuntime],
  );
  const timelineDisplayItems = useMemo(
    () => timelineItemsForDisplay(visibleTimelineItems),
    [visibleTimelineItems],
  );
  const timelineTurns = useMemo(
    () => computeTimelineTurns(timelineDisplayItems),
    [timelineDisplayItems],
  );
  const {
    collapsedTurnIds,
    toggleTurn: toggleTimelineTurn,
    expandTurn: expandTimelineTurn,
  } = useTimelineTurnCollapse(turnCollapseScope);
  const revealTimelineMember = useCallback(
    (memberId: string): boolean => {
      const turn = timelineTurnForMember(timelineTurns, memberId);
      return turn ? expandTimelineTurn(turn.id) : false;
    },
    [expandTimelineTurn, timelineTurns],
  );
  const conversationExportSnapshot = useMemo(
    () =>
      visibleTimelineState && messageActionConversationId
        ? createConversationExportSnapshot({
            conversationId: messageActionConversationId,
            title: sessionTitle,
            items: visibleTimelineState.items,
          })
        : null,
    [messageActionConversationId, sessionTitle, visibleTimelineState],
  );
  const conversationSearchScopeId = timelineConversationId || selectedConversationId || '';
  const composeAheadConversation = useMemo(
    () =>
      selectedConversationId
        ? conversations.find((conversation) => conversation.id === selectedConversationId) ?? null
        : null,
    [conversations, selectedConversationId],
  );
  const comparisonClient = useMemo<ConversationComparisonClient | null>(() => {
    const listConversations = api.listConversations?.bind(api);
    const getConversationMessages = api.getConversationMessages?.bind(api);
    return listConversations && getConversationMessages
      ? { listConversations, getConversationMessages }
      : null;
  }, [api]);
  const comparisonAvailable = conversationComparisonAvailable(
    composeAheadConversation,
    Boolean(comparisonClient),
  );
  const composeAheadScope = useMemo(
    () => composeAheadConversationScope(composeAheadConversation),
    [composeAheadConversation],
  );
  const composeAheadEnabled =
    Boolean(composeAheadScope) && runInputDeliveryOptions.length === 0;
  const rawResponseStreaming = conversationResponseIsStreaming({
    activeConversationId: selectedConversationId ?? '',
    sending,
    activityPresence,
    signals: agentTaskSignals,
    timelineItems: timelineState?.items ?? [],
  });
  const responseStreaming =
    rawResponseStreaming &&
    !agentStopRequestSettlesStreaming(stopRequest, selectedConversationId ?? '');
  useEffect(() => {
    stopEventHeadRef.current = agentControlEventsRef.current[0] ?? null;
    setStopRequest((current) =>
      reconcileAgentStopScope(current, selectedConversationId),
    );
  }, [selectedConversationId]);
  useEffect(() => {
    if (stopRequest.status !== 'stopping') return;
    const events = socketEventsSince(agentControlEvents, stopEventHeadRef.current);
    stopEventHeadRef.current = agentControlEvents[0] ?? null;
    if (!events.length) return;
    setStopRequest((current) =>
      events.reduce(
        (next, event) => applyAgentStopEvent(next, event),
        current,
      ),
    );
  }, [agentControlEvents, stopRequest.status]);
  useEffect(() => {
    if (rawResponseStreaming || stopRequest.status === 'idle') return;
    setStopRequest(EMPTY_AGENT_STOP_REQUEST);
  }, [rawResponseStreaming, stopRequest.status]);
  const stopResponse = useCallback(() => {
    const conversationId = selectedConversationId?.trim() ?? '';
    if (
      !conversationId ||
      !responseStreaming ||
      stopRequest.status === 'stopping' ||
      !onStopResponse
    ) {
      return;
    }
    stopEventHeadRef.current = agentControlEvents[0] ?? null;
    setStopRequest(
      beginAgentStopRequest(conversationId, onStopResponse(conversationId)),
    );
  }, [
    agentControlEvents,
    onStopResponse,
    responseStreaming,
    selectedConversationId,
    stopRequest.status,
  ]);
  const stopResponseError =
    stopRequest.status === 'error' && stopRequest.errorCode
      ? t(agentStopErrorTranslationKey(stopRequest.errorCode))
      : null;
  const visibleActionMessages = useMemo<VisibleMessageForRetry[]>(
    () =>
      visibleTimelineState
        ? visibleTimelineState.items.flatMap((item) => {
            const message = timelineVisibleMessage(item, timelineConversationId);
            return message ? [message] : [];
          })
        : visibleWorkspaceMessages.map((message) =>
            workspaceVisibleMessage(message, messageActionConversationId),
          ),
    [
      messageActionConversationId,
      timelineConversationId,
      visibleTimelineState,
      visibleWorkspaceMessages,
    ],
  );
  const deletionFocusMessages = useMemo<VisibleMessageForRetry[]>(
    () =>
      visibleTimelineState
        ? visibleTimelineState.items.map((item) => {
            const kind = timelineKind(item);
            return {
              id: item.id,
              conversationId: timelineConversationId,
              kind: kind === 'user' || kind === 'agent' ? kind : 'runtime',
              content: item.content ?? '',
            };
          })
        : visibleWorkspaceMessages.map((message) =>
            workspaceVisibleMessage(message, messageActionConversationId),
          ),
    [
      messageActionConversationId,
      timelineConversationId,
      visibleTimelineState,
      visibleWorkspaceMessages,
    ],
  );
  const pinnedMessages = useMemo(
    () => pinnedMessagesInTimelineOrder(visibleActionMessages, pinnedMessageIds),
    [pinnedMessageIds, visibleActionMessages],
  );
  const workspaceFirstMessageId = visibleWorkspaceMessages[0]?.id ?? '';
  const workspaceLastMessageId =
    visibleWorkspaceMessages[visibleWorkspaceMessages.length - 1]?.id ?? '';
  const activitySummary = useMemo(() => {
    if (!visibleTimelineItems.length) return null;
    return sessionActivitySummary({
      items: visibleTimelineItems,
      structuredEvidence: activityStructuredEvidence,
    });
  }, [activityStructuredEvidence, visibleTimelineItems]);
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
  const clearPinnedJumpTarget = useCallback(() => {
    if (pinnedJumpFrameRef.current !== null) {
      window.cancelAnimationFrame(pinnedJumpFrameRef.current);
      pinnedJumpFrameRef.current = null;
    }
    pinnedJumpTargetRef.current?.classList.remove('chat-pinned-jump-target');
    pinnedJumpTargetRef.current = null;
    if (pinnedJumpTimerRef.current !== null) {
      window.clearTimeout(pinnedJumpTimerRef.current);
      pinnedJumpTimerRef.current = null;
    }
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
  const clearRetryDispatch = useCallback(() => {
    retryDispatchLockRef.current = null;
    retryDispatchSawSendingRef.current = false;
    setRetryingMessageId(null);
    if (retryUnlockTimerRef.current !== null) {
      window.clearTimeout(retryUnlockTimerRef.current);
      retryUnlockTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    setComposerDraftRequest(null);
    setMessageActionNotice(null);
    setSaveTemplateRequest(null);
    setMessageDeleteRequest(null);
    setLocalMessageVisibility(null);
    setConversationSearchVisible(false);
    setConversationComparisonVisible(false);
    setConversationComparisonPickerOpen(false);
    setComparisonConversation(null);
    setPinnedMessageIds([]);
    setPinnedMessagesCollapsed(false);
    clearPinnedJumpTarget();
    clearRetryDispatch();
  }, [clearPinnedJumpTarget, clearRetryDispatch, messageActionScopeKey]);

  useEffect(() => {
    setPinnedMessageIds((current) => {
      const reconciled = reconcilePinnedMessageIds(current, visibleActionMessages);
      return equalStringArrays(current, reconciled) ? current : reconciled;
    });
  }, [visibleActionMessages]);

  useEffect(() => {
    const handleConversationSearchShortcut = (event: KeyboardEvent) => {
      if (
        conversationSearchScopeId &&
        (event.metaKey || event.ctrlKey) &&
        event.key.toLowerCase() === 'f'
      ) {
        event.preventDefault();
        setConversationSearchVisible((visible) => !visible);
      }
    };
    window.addEventListener('keydown', handleConversationSearchShortcut);
    return () => window.removeEventListener('keydown', handleConversationSearchShortcut);
  }, [conversationSearchScopeId]);

  useEffect(() => {
    if (!retryDispatchLockRef.current) return;
    if (sending) {
      retryDispatchSawSendingRef.current = true;
      return;
    }
    if (retryDispatchSawSendingRef.current) clearRetryDispatch();
  }, [clearRetryDispatch, sending]);

  useEffect(
    () => () => {
      if (retryUnlockTimerRef.current !== null) {
        window.clearTimeout(retryUnlockTimerRef.current);
      }
      clearPinnedJumpTarget();
    },
    [clearPinnedJumpTarget],
  );

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
      visibleWorkspaceMessages.length,
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
    visibleWorkspaceMessages.length,
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
      setStopRequest((current) =>
        current.status === 'stopped' ? EMPTY_AGENT_STOP_REQUEST : current,
      );
      onSend(content, contextItems, onWorkspaceMessageSaved);
      window.requestAnimationFrame(scrollToLatest);
    },
    [onSend, scrollToLatest],
  );
  const handleSuggestionSelect = useCallback(
    (suggestion: string) => handleComposerSend(suggestion, []),
    [handleComposerSend],
  );
  const requestComposerDraft = useCallback(
    (content: string) => {
      if (!messageActionConversationId || !content) return;
      composerDraftSequenceRef.current += 1;
      setComposerDraftRequest({
        id: composerDraftSequenceRef.current,
        conversationId: messageActionConversationId,
        content,
      });
      setMessageActionNotice(null);
    },
    [messageActionConversationId],
  );
  const replyToVisibleMessage = useCallback(
    (message: VisibleMessageForRetry) => {
      const draft = quoteMessageForComposer(message.content);
      if (draft) requestComposerDraft(draft);
    },
    [requestComposerDraft],
  );
  const editVisibleMessage = useCallback(
    (message: VisibleMessageForRetry) => {
      if (message.kind === 'user' && message.content.trim()) {
        requestComposerDraft(message.content);
      }
    },
    [requestComposerDraft],
  );
  const requestVisibleMessageDeletion = useCallback(
    (message: VisibleMessageForRetry, returnFocus: HTMLElement) => {
      const target = {
        scopeKey: messageActionScopeKey,
        messageId: message.id,
      };
      if (
        message.conversationId !== messageActionConversationId ||
        !canConfirmMessageDeletion(target, messageActionScopeKey, visibleActionMessages)
      ) {
        return;
      }
      setMessageActionNotice(null);
      setMessageDeleteRequest({
        ...target,
        content: message.content,
        returnFocus,
        focusNeighborId: messageDeletionFocusNeighborId(
          deletionFocusMessages,
          message.id,
        ),
      });
    },
    [
      deletionFocusMessages,
      messageActionConversationId,
      messageActionScopeKey,
      visibleActionMessages,
    ],
  );
  const cancelMessageDeletion = useCallback(() => {
    const returnFocus = messageDeleteRequest?.returnFocus ?? null;
    setMessageDeleteRequest(null);
    if (returnFocus) {
      window.requestAnimationFrame(() => {
        if (returnFocus.isConnected) returnFocus.focus();
      });
    }
  }, [messageDeleteRequest]);
  const confirmMessageDeletion = useCallback(() => {
    const request = messageDeleteRequest;
    if (
      !request ||
      !canConfirmMessageDeletion(
        request,
        messageActionScopeKey,
        visibleActionMessages,
      )
    ) {
      setMessageDeleteRequest(null);
      return;
    }

    setLocalMessageVisibility((current) =>
      hideMessageInScope(current, request.scopeKey, request.messageId),
    );
    setPinnedMessageIds((current) =>
      current.includes(request.messageId)
        ? current.filter((candidate) => candidate !== request.messageId)
        : current,
    );
    setMessageActionNotice(t('chat.messageRemoved'));
    setMessageDeleteRequest(null);

    const focusNeighborId = request.focusNeighborId;
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        const viewport = scrollViewport();
        const anchors = viewport
          ? Array.from(
              viewport.querySelectorAll<HTMLElement>('[data-timeline-anchor-id]'),
            )
          : [];
        const anchor = focusNeighborId
          ? anchors.find(
              (candidate) =>
                candidate.dataset.timelineAnchorId === focusNeighborId ||
                timelineAnchorMemberIds(candidate).includes(focusNeighborId),
            )
          : null;
        const focusTarget =
          anchor instanceof HTMLDetailsElement
            ? anchor.querySelector<HTMLElement>('summary')
            : anchor;
        (focusTarget ?? scrollAreaRef.current)?.focus();
      });
    });
  }, [
    messageActionScopeKey,
    messageDeleteRequest,
    scrollViewport,
    t,
    visibleActionMessages,
  ]);
  const retryVisibleMessage = useCallback(
    (message: VisibleMessageForRetry) => {
      const retryContent = findRetryMessageContent(
        visibleActionMessages,
        message.id,
        messageActionConversationId,
      );
      if (!retryContent) {
        setMessageActionNotice(t('chat.retryNoUserMessage'));
        return;
      }
      const resolution = resolveRetryDispatch(
        retryDispatchLockRef.current,
        message.id,
        disabled || sending,
      );
      retryDispatchLockRef.current = resolution.lock;
      if (!resolution.accepted) return;

      retryDispatchSawSendingRef.current = false;
      setRetryingMessageId(message.id);
      setMessageActionNotice(null);
      handleComposerSend(retryContent, []);
      if (retryUnlockTimerRef.current !== null) {
        window.clearTimeout(retryUnlockTimerRef.current);
      }
      retryUnlockTimerRef.current = window.setTimeout(() => {
        if (!sendingRef.current) clearRetryDispatch();
      }, 1_500);
    },
    [
      clearRetryDispatch,
      disabled,
      handleComposerSend,
      messageActionConversationId,
      sending,
      t,
      visibleActionMessages,
    ],
  );
  const replyToTimelineMessage = useCallback(
    (item: AgentTimelineItem) => {
      const message = timelineVisibleMessage(item, messageActionConversationId);
      if (message) replyToVisibleMessage(message);
    },
    [messageActionConversationId, replyToVisibleMessage],
  );
  const editTimelineMessage = useCallback(
    (item: AgentTimelineItem) => {
      const message = timelineVisibleMessage(item, messageActionConversationId);
      if (message) editVisibleMessage(message);
    },
    [editVisibleMessage, messageActionConversationId],
  );
  const requestTimelineMessageDeletion = useCallback(
    (item: AgentTimelineItem, returnFocus: HTMLElement) => {
      const message = timelineVisibleMessage(item, messageActionConversationId);
      if (message) requestVisibleMessageDeletion(message, returnFocus);
    },
    [messageActionConversationId, requestVisibleMessageDeletion],
  );
  const retryTimelineMessage = useCallback(
    (item: AgentTimelineItem) => {
      const message = timelineVisibleMessage(item, messageActionConversationId);
      if (message) retryVisibleMessage(message);
    },
    [messageActionConversationId, retryVisibleMessage],
  );
  const saveVisibleMessageAsTemplate = useCallback(
    (message: VisibleMessageForRetry, returnFocus: HTMLElement) => {
      if (
        message.kind !== 'agent' ||
        !message.content.trim() ||
        message.conversationId !== messageActionConversationId ||
        !messageActionConversation?.tenant_id ||
        !messageActionConversation.project_id
      ) {
        return;
      }
      setMessageActionNotice(null);
      setSaveTemplateRequest({
        messageId: message.id,
        tenantId: messageActionConversation.tenant_id,
        projectId: messageActionConversation.project_id,
        conversationId: messageActionConversation.id,
        content: message.content,
        returnFocus,
      });
    },
    [messageActionConversation, messageActionConversationId],
  );
  const saveTimelineMessageAsTemplate = useCallback(
    (item: AgentTimelineItem, returnFocus: HTMLElement) => {
      const message = timelineVisibleMessage(item, messageActionConversationId);
      if (message) saveVisibleMessageAsTemplate(message, returnFocus);
    },
    [messageActionConversationId, saveVisibleMessageAsTemplate],
  );
  const closeSaveTemplateDialog = useCallback(() => {
    const returnFocus = saveTemplateRequest?.returnFocus ?? null;
    setSaveTemplateRequest(null);
    if (returnFocus) {
      window.requestAnimationFrame(() => {
        if (returnFocus.isConnected) returnFocus.focus();
      });
    }
  }, [saveTemplateRequest]);
  const completeSaveTemplate = useCallback(() => {
    setPromptTemplateRefreshToken((current) => current + 1);
    setMessageActionNotice(t('chat.templates.saved'));
  }, [t]);
  const togglePinnedVisibleMessage = useCallback(
    (message: VisibleMessageForRetry) => {
      if (
        message.kind !== 'agent' ||
        message.conversationId !== messageActionConversationId
      ) {
        return;
      }
      setPinnedMessageIds((current) => togglePinnedMessageId(current, message.id));
    },
    [messageActionConversationId],
  );
  const unpinVisibleMessage = useCallback((message: VisibleMessageForRetry) => {
    setPinnedMessageIds((current) =>
      current.includes(message.id)
        ? current.filter((candidate) => candidate !== message.id)
        : current,
    );
  }, []);
  const togglePinnedTimelineMessage = useCallback(
    (item: AgentTimelineItem) => {
      const message = timelineVisibleMessage(item, messageActionConversationId);
      if (message) togglePinnedVisibleMessage(message);
    },
    [messageActionConversationId, togglePinnedVisibleMessage],
  );
  const jumpToPinnedMessage = useCallback(
    (message: VisibleMessageForRetry) => {
      if (message.conversationId !== messageActionConversationId) return;
      clearPinnedJumpTarget();
      const scrollToMessage = () => {
        const viewport = scrollViewport();
        if (!viewport) return;
        const candidates = Array.from(
          viewport.querySelectorAll<HTMLElement>('[data-timeline-anchor-id]'),
        );
        const target =
          candidates.find(
            (candidate) => candidate.dataset.timelineAnchorId === message.id,
          ) ??
          candidates.find((candidate) =>
            timelineAnchorMemberIds(candidate).includes(message.id),
          );
        if (!target) return;

        pinnedToLatestRef.current = false;
        setShowJumpToLatest(viewport.scrollHeight > viewport.clientHeight);
        target.scrollIntoView({
          behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
            ? 'auto'
            : 'smooth',
          block: 'center',
        });
        target.classList.add('chat-pinned-jump-target');
        target.focus({ preventScroll: true });
        pinnedJumpTargetRef.current = target;
        pinnedJumpTimerRef.current = window.setTimeout(clearPinnedJumpTarget, 1_800);
      };
      if (revealTimelineMember(message.id)) {
        pinnedJumpFrameRef.current = window.requestAnimationFrame(() => {
          pinnedJumpFrameRef.current = window.requestAnimationFrame(() => {
            pinnedJumpFrameRef.current = null;
            scrollToMessage();
          });
        });
        return;
      }
      scrollToMessage();
    },
    [
      clearPinnedJumpTarget,
      messageActionConversationId,
      revealTimelineMember,
      scrollViewport,
    ],
  );
  const toggleTimelineItem = useCallback((item: AgentTimelineItem) => {
    setExpandedTimelineItems((current) => {
      const currentValue = current[item.id] ?? isTimelineItemInitiallyExpanded(item);
      return { ...current, [item.id]: !currentValue };
    });
  }, []);
  const openConversationComparison = useCallback(() => {
    if (!comparisonAvailable) return;
    setConversationComparisonVisible(true);
    setConversationComparisonPickerOpen(true);
  }, [comparisonAvailable]);
  const closeConversationComparison = useCallback(() => {
    setConversationComparisonVisible(false);
    setConversationComparisonPickerOpen(false);
    setComparisonConversation(null);
    window.requestAnimationFrame(() => comparisonTriggerRef.current?.focus());
  }, []);
  const selectComparisonConversation = useCallback(
    (conversation: AgentConversation) => {
      if (
        !composeAheadConversation ||
        !conversationComparisonScope(composeAheadConversation, conversation)
      ) {
        return;
      }
      setComparisonConversation(conversation);
    },
    [composeAheadConversation],
  );

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
      {comparisonAvailable || conversationExportSnapshot?.events.length ? (
        <div className="chat-conversation-actions">
          {comparisonAvailable ? (
            <button
              ref={comparisonTriggerRef}
              type="button"
              className="chat-conversation-compare-trigger"
              aria-label={t('chat.comparison.compare')}
              title={t('chat.comparison.compare')}
              aria-pressed={conversationComparisonVisible}
              onClick={openConversationComparison}
            >
              <ColumnsIcon aria-hidden="true" />
              <span>{t('chat.comparison.compare')}</span>
            </button>
          ) : null}
          {conversationExportSnapshot?.events.length ? (
            <ConversationExportMenu snapshot={conversationExportSnapshot} />
          ) : null}
        </div>
      ) : null}
      {conversationComparisonVisible && comparisonClient && composeAheadConversation ? (
        <ConversationComparison
          client={comparisonClient}
          currentConversation={composeAheadConversation}
          comparisonConversation={comparisonConversation}
          onChooseConversation={() => setConversationComparisonPickerOpen(true)}
          onClose={closeConversationComparison}
        />
      ) : (
        <>
      <ScrollArea
        className="message-scroll"
        ref={scrollAreaRef}
        aria-label={t('session.timelineScrollRegion')}
        aria-busy={timelineLoading || timelineLoadingEarlier}
        tabIndex={0}
      >
        <PinnedMessages
          messages={pinnedMessages}
          collapsed={pinnedMessagesCollapsed}
          onCollapsedChange={setPinnedMessagesCollapsed}
          onJump={jumpToPinnedMessage}
          onUnpin={unpinVisibleMessage}
        />
        {composeAheadConversation ? (
          <ConversationSummaryCard
            key={composeAheadConversation.id}
            conversationId={composeAheadConversation.id}
            summary={composeAheadConversation?.summary ?? null}
            regenerationAvailable={turnCollapseRuntime.mode === 'cloud'}
            onRegenerate={onRegenerateConversationSummary}
          />
        ) : null}
        <div className="message-stack">
          {timelineState ? (
            <>
              {activitySummary ? (
                <section
                  className="session-current-activity"
                  aria-label={t('session.currentActivity')}
                >
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
                state={visibleTimelineState ?? timelineState}
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
                onReplyMessage={replyToTimelineMessage}
                onEditMessage={editTimelineMessage}
                onDeleteMessage={requestTimelineMessageDeletion}
                onRetryMessage={retryTimelineMessage}
                onSaveTemplateMessage={saveTimelineMessageAsTemplate}
                pinnedMessageIds={pinnedMessageIds}
                onPinMessage={togglePinnedTimelineMessage}
                retryDisabled={disabled || sending || Boolean(retryingMessageId)}
                turns={timelineTurns}
                collapsedTurnIds={collapsedTurnIds}
                onToggleTurn={toggleTimelineTurn}
              />
            </>
          ) : visibleWorkspaceMessages.length === 0 ? (
            <SessionEmptyState />
          ) : (
            visibleWorkspaceMessages.map((message) => {
              const visibleMessage = workspaceVisibleMessage(
                message,
                messageActionConversationId,
              );
              return (
                <WorkspaceTranscriptMessage
                  message={message}
                  key={message.id}
                  onReply={
                    visibleMessage.kind === 'runtime'
                      ? undefined
                      : () => replyToVisibleMessage(visibleMessage)
                  }
                  onEdit={
                    visibleMessage.kind === 'user'
                      ? () => editVisibleMessage(visibleMessage)
                      : undefined
                  }
                  onDelete={
                    visibleMessage.kind === 'user'
                      ? (returnFocus) =>
                          requestVisibleMessageDeletion(visibleMessage, returnFocus)
                      : undefined
                  }
                  onRetry={
                    visibleMessage.kind === 'agent'
                      ? () => retryVisibleMessage(visibleMessage)
                      : undefined
                  }
                  isPinned={
                    visibleMessage.kind === 'agent' &&
                    pinnedMessageIds.includes(visibleMessage.id)
                  }
                  onPin={
                    visibleMessage.kind === 'agent'
                      ? () => togglePinnedVisibleMessage(visibleMessage)
                      : undefined
                  }
                  onSaveTemplate={
                    visibleMessage.kind === 'agent'
                      ? (returnFocus) =>
                          saveVisibleMessageAsTemplate(visibleMessage, returnFocus)
                      : undefined
                  }
                  retryDisabled={disabled || sending || Boolean(retryingMessageId)}
                />
              );
            })
          )}
          {visibleAgentTaskSignals.length ? (
            <div className="agent-run-stack" aria-label={t('chat.agentTaskStatus')}>
              {visibleAgentTaskSignals.map((signal) => (
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
      <ConversationSearch
        items={visibleTimelineItems}
        visible={conversationSearchVisible}
        getViewport={scrollViewport}
        onRevealItem={revealTimelineMember}
        onClose={() => setConversationSearchVisible(false)}
      />
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
      {messageActionNotice ? (
        <div className="session-message-action-notice" role="status" aria-live="polite">
          {messageActionNotice}
        </div>
      ) : null}
      {stopResponseError ? (
        <div className="session-stop-response-error" role="alert">
          {stopResponseError}
        </div>
      ) : null}
      <ChatComposer
        key={composerResetKey}
        api={api}
        conversations={conversations}
        selectedConversationId={selectedConversationId}
        activeConversationId={messageActionConversationId}
        promptTemplateRefreshToken={promptTemplateRefreshToken}
        draftRequest={composerDraftRequest}
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
        onStopResponse={stopResponse}
        composeAheadScope={composeAheadScope}
        composeAheadEnabled={composeAheadEnabled}
        responseStreaming={responseStreaming}
        stopResponseAvailable={Boolean(onStopResponse)}
        stopResponseStatus={stopRequest.status}
        voiceTranscriptionConfig={voiceTranscriptionConfig}
        voiceTranscriptionRuntime={voiceTranscriptionRuntime}
        voiceCallRuntime={voiceCallRuntime}
      />
      {messageDeleteRequest ? (
        <MessageDeleteDialog
          target={messageDeleteRequest}
          onCancel={cancelMessageDeletion}
          onConfirm={confirmMessageDeletion}
        />
      ) : null}
      {saveTemplateRequest ? (
        <SavePromptTemplateDialog
          api={api}
          target={saveTemplateRequest}
          onClose={closeSaveTemplateDialog}
          onSaved={completeSaveTemplate}
        />
      ) : null}
        </>
      )}
      {conversationComparisonVisible && comparisonClient && composeAheadConversation ? (
        <ConversationComparisonPicker
          open={conversationComparisonPickerOpen}
          client={comparisonClient}
          currentConversation={composeAheadConversation}
          onSelect={selectComparisonConversation}
          onClose={() => setConversationComparisonPickerOpen(false)}
        />
      ) : null}
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
  activeConversationId: string;
  promptTemplateRefreshToken: number;
  draftRequest: ComposerDraftRequest | null;
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
  onStopResponse: () => void;
  composeAheadScope: string | null;
  composeAheadEnabled: boolean;
  responseStreaming: boolean;
  stopResponseAvailable: boolean;
  stopResponseStatus: AgentStopRequestState['status'];
  voiceTranscriptionConfig?: DesktopRuntimeConfig;
  voiceTranscriptionRuntime?: VoiceTranscriptionRuntime;
  voiceCallRuntime?: VoiceCallRuntime;
};

function ChatComposer({
  api,
  conversations,
  selectedConversationId,
  activeConversationId,
  promptTemplateRefreshToken,
  draftRequest,
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
  onStopResponse,
  composeAheadScope,
  composeAheadEnabled,
  responseStreaming,
  stopResponseAvailable,
  stopResponseStatus,
  voiceTranscriptionConfig,
  voiceTranscriptionRuntime,
  voiceCallRuntime,
}: ChatComposerProps) {
  const { t } = useI18n();
  const [input, setInput] = useState(initialInput);
  const [contextItems, setContextItems] = useState<ComposerContextItem[]>([]);
  const composerInputRef = useRef<HTMLTextAreaElement>(null);
  const sendingRef = useRef(sending);
  const responseStreamingRef = useRef(responseStreaming);
  const dispatchMonitorRef = useRef<{
    timerId: number;
    scope: string;
    promptId: string;
  } | null>(null);
  sendingRef.current = sending;
  responseStreamingRef.current = responseStreaming;
  const disabled = Boolean(disabledReason);
  const promptTemplateConversation =
    conversations.find((conversation) => conversation.id === activeConversationId) ?? null;
  const voiceConnection = useMemo<VoiceTranscriptionConnection>(
    () =>
      voiceTranscriptionConfig
        ? resolveVoiceTranscriptionConnection(
            voiceTranscriptionConfig,
            promptTemplateConversation?.project_id ?? voiceTranscriptionConfig.projectId,
            promptTemplateConversation?.id ?? activeConversationId,
          )
        : { availability: 'local_runtime' },
    [activeConversationId, promptTemplateConversation, voiceTranscriptionConfig],
  );
  const voiceCallConnection = useMemo<VoiceCallConnection>(
    () =>
      voiceTranscriptionConfig
        ? resolveVoiceCallConnection(
            voiceTranscriptionConfig,
            promptTemplateConversation?.project_id ?? voiceTranscriptionConfig.projectId,
            promptTemplateConversation?.id ?? activeConversationId,
          )
        : { availability: 'local_runtime' },
    [activeConversationId, promptTemplateConversation, voiceTranscriptionConfig],
  );
  const voiceDraftRef = useRef(initialVoiceTranscriptDraft(''));
  const applyVoiceMessage = useCallback(
    (message: Parameters<typeof applyVoiceTranscriptMessage>[1]) => {
      const nextDraft = applyVoiceTranscriptMessage(voiceDraftRef.current, message);
      voiceDraftRef.current = nextDraft;
      setInput(voiceTranscriptDraftValue(nextDraft));
    },
    [],
  );
  const voice = useVoiceTranscription({
    connection: voiceConnection,
    runtime: voiceTranscriptionRuntime,
    onInterim: (text) => applyVoiceMessage({ kind: 'interim', text }),
    onFinal: (text) => applyVoiceMessage({ kind: 'final', text }),
  });
  const voiceCall = useVoiceCall({
    connection: voiceCallConnection,
    runtime: voiceCallRuntime,
  });
  const voiceActive = voice.state === 'connecting' || voice.state === 'listening';
  const voiceCallActive =
    voiceCall.status === 'connecting' ||
    voiceCall.status === 'connected' ||
    voiceCall.status === 'error';
  const voiceDisabledReason =
    voiceConnection.availability === 'available'
      ? null
      : t(`composer.voice.unavailable.${voiceConnection.availability}`);
  const voiceCallDisabledReason =
    voiceCallConnection.availability === 'available'
      ? null
      : t(`composer.voiceCall.unavailable.${voiceCallConnection.availability}`);
  const toggleVoice = useCallback(async () => {
    if (voiceCallActive) return;
    if (!voiceActive) voiceDraftRef.current = initialVoiceTranscriptDraft(input);
    await voice.toggle();
  }, [input, voice.toggle, voiceActive, voiceCallActive]);
  const toggleVoiceCall = useCallback(async () => {
    if (voiceCallActive) {
      voiceCall.end();
      return;
    }
    voice.stop();
    await voiceCall.start();
  }, [voice.stop, voiceCall, voiceCallActive]);
  const insertPromptTemplate = useCallback(
    (prompt: string) => {
      voice.stop();
      setInput(prompt);
      window.requestAnimationFrame(() => composerInputRef.current?.focus());
    },
    [voice.stop],
  );
  const addContextItem = useCallback((item: ComposerContextItem) => {
    setContextItems((current) => appendComposerContextItem(current, item));
  }, []);
  const {
    supportsFileUpload,
    uploadingFileCount,
    uploadingAttachments,
    fileUploadErrors,
    uploadFiles,
    rejectFileDrop,
  } = useComposerFileUpload({ api, onAdd: addContextItem });
  const composeAheadSnapshot = composeAheadContextSnapshot(contextItems);
  const composeAheadQueueEligibility = composeAheadEligibility({
    content: input,
    streaming: composeAheadEnabled && responseStreaming,
    disabled,
    uploading: uploadingAttachments,
    contextItems,
    referenceCount: references.length,
  });
  const canSendNow =
    !disabled &&
    !sending &&
    !(composeAheadEnabled && responseStreaming) &&
    !uploadingAttachments &&
    (Boolean(input.trim()) || composerHasSendableAttachment(contextItems));
  const canSubmit = canSendNow || composeAheadQueueEligibility.canQueue;
  const composerPresentation = chatComposerPresentation(composerVariant);
  const queuedRunInputs = useMemo(() => visibleQueuedRunInputs(runInputs), [runInputs]);
  const getComposeAheadSnapshot = useCallback(
    () =>
      composeAheadScope
        ? composeAheadQueueStore.getSnapshot(composeAheadScope)
        : EMPTY_COMPOSE_AHEAD_QUEUE,
    [composeAheadScope],
  );
  const queuedPrompts = useSyncExternalStore(
    composeAheadQueueStore.subscribe,
    getComposeAheadSnapshot,
    getComposeAheadSnapshot,
  );
  useEffect(() => {
    if (!draftRequest || draftRequest.conversationId !== activeConversationId) return;
    setInput(draftRequest.content);
    window.requestAnimationFrame(() => composerInputRef.current?.focus());
  }, [activeConversationId, draftRequest]);
  const handleSend = useCallback(() => {
    voice.stop();
    if (composeAheadQueueEligibility.canQueue && composeAheadScope) {
      composeAheadQueueStore.enqueue(composeAheadScope, {
        text: input,
        contextItems: composeAheadSnapshot.contextItems,
      });
      setInput('');
      setContextItems([]);
      return;
    }
    if (!canSendNow) return;
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
  }, [
    canSendNow,
    composeAheadQueueEligibility.canQueue,
    composeAheadScope,
    composeAheadSnapshot.contextItems,
    contextItems,
    input,
    onSend,
    t,
    voice.stop,
  ]);
  useEffect(() => {
    return () => {
      if (dispatchMonitorRef.current) {
        window.clearTimeout(dispatchMonitorRef.current.timerId);
        dispatchMonitorRef.current = null;
      }
    };
  }, []);
  useEffect(() => {
    if (!composeAheadScope) return;
    const scheduleDispatchMonitor = (prompt: ComposeAheadPrompt) => {
      const activeMonitor = dispatchMonitorRef.current;
      if (
        activeMonitor?.scope === composeAheadScope &&
        activeMonitor.promptId === prompt.id
      ) {
        return;
      }
      if (activeMonitor) {
        window.clearTimeout(activeMonitor.timerId);
        composeAheadQueueStore.fail(activeMonitor.scope, activeMonitor.promptId);
      }
      const monitorDispatch = () => {
        const currentMonitor = dispatchMonitorRef.current;
        if (
          currentMonitor?.scope !== composeAheadScope ||
          currentMonitor.promptId !== prompt.id
        ) {
          return;
        }
        dispatchMonitorRef.current = null;
        const current = composeAheadQueueStore
          .getSnapshot(composeAheadScope)
          .find((candidate) => candidate.id === prompt.id);
        if (!current || current.status !== 'dispatching') return;
        if (sendingRef.current || responseStreamingRef.current) {
          scheduleDispatchMonitor(prompt);
          return;
        }
        composeAheadQueueStore.fail(composeAheadScope, prompt.id);
      };
      dispatchMonitorRef.current = {
        timerId: window.setTimeout(monitorDispatch, 750),
        scope: composeAheadScope,
        promptId: prompt.id,
      };
    };
    const head = queuedPrompts[0];
    if (head?.status === 'dispatching') {
      scheduleDispatchMonitor(head);
      return;
    }
    if (
      !composeAheadEnabled ||
      responseStreaming ||
      sending ||
      disabled
    ) {
      return;
    }
    const claimed = composeAheadQueueStore.claimHead(composeAheadScope);
    if (!claimed) return;
    scheduleDispatchMonitor(claimed);
    try {
      onSend(claimed.text, [...claimed.contextItems], () => {
        const activeMonitor = dispatchMonitorRef.current;
        if (
          activeMonitor?.scope === composeAheadScope &&
          activeMonitor.promptId === claimed.id
        ) {
          window.clearTimeout(activeMonitor.timerId);
          dispatchMonitorRef.current = null;
        }
        composeAheadQueueStore.accept(composeAheadScope, claimed.id);
      });
    } catch {
      const activeMonitor = dispatchMonitorRef.current;
      if (
        activeMonitor?.scope === composeAheadScope &&
        activeMonitor.promptId === claimed.id
      ) {
        window.clearTimeout(activeMonitor.timerId);
        dispatchMonitorRef.current = null;
      }
      composeAheadQueueStore.fail(composeAheadScope, claimed.id);
    }
  }, [
    composeAheadEnabled,
    composeAheadScope,
    disabled,
    onSend,
    queuedPrompts,
    responseStreaming,
    sending,
  ]);
  const {
    isFileDragging,
    handleFileDragEnter,
    handleFileDragOver,
    handleFileDragLeave,
    handleFileDrop,
  } = useComposerFileDrop({
    disabled: disabled || uploadingAttachments,
    supportsUpload: supportsFileUpload,
    onUploadFiles: uploadFiles,
    onUnsupported: rejectFileDrop,
  });

  return (
    <form
      className="composer chat-composer"
      aria-busy={uploadingAttachments}
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
      {composeAheadEnabled && queuedPrompts.length ? (
        <ComposeAheadQueue
          prompts={queuedPrompts}
          scope={composeAheadScope}
        />
      ) : null}
      <div
        className={`session-composer-editor${isFileDragging ? ' is-file-dragging' : ''}`}
        data-file-drop-target
        onDragEnter={handleFileDragEnter}
        onDragOver={handleFileDragOver}
        onDragLeave={handleFileDragLeave}
        onDrop={handleFileDrop}
      >
        {isFileDragging ? (
          <div className="composer-file-drop-overlay" role="status" aria-live="polite">
            <UploadIcon aria-hidden="true" />
            <strong>{t('composer.dropFilesToUpload')}</strong>
          </div>
        ) : null}
        {uploadingFileCount ? (
          <div className="composer-file-upload-status" role="status" aria-live="polite">
            {t('composer.uploadingFiles', { count: uploadingFileCount })}
          </div>
        ) : null}
        {fileUploadErrors.length ? (
          <div className="composer-file-upload-errors" role="alert">
            {fileUploadErrors.map((error, index) => (
              <span key={`${index}:${error}`}>{error}</span>
            ))}
          </div>
        ) : null}
        {voice.errorCode ? (
          <div className="composer-voice-error" role="alert">
            {t(voiceTranscriptionFailureKey(voice.errorCode))}
          </div>
        ) : null}
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
          ref={composerInputRef}
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
              !event.nativeEvent.isComposing &&
              canSubmit &&
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
              onUploadFiles={uploadFiles}
              uploadingFileCount={uploadingFileCount}
            />
            <PromptTemplateLibrary
              api={api}
              tenantId={promptTemplateConversation?.tenant_id ?? ''}
              projectId={promptTemplateConversation?.project_id ?? ''}
              conversationId={promptTemplateConversation?.id ?? ''}
              refreshToken={promptTemplateRefreshToken}
              disabled={disabled}
              onInsert={insertPromptTemplate}
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
        {composerVariant !== 'session' ? (
          <PromptTemplateLibrary
            api={api}
            tenantId={promptTemplateConversation?.tenant_id ?? ''}
            projectId={promptTemplateConversation?.project_id ?? ''}
            conversationId={promptTemplateConversation?.id ?? ''}
            refreshToken={promptTemplateRefreshToken}
            disabled={disabled}
            onInsert={insertPromptTemplate}
          />
        ) : null}
        <Flex align="center" gap="2" className="composer-right-actions">
          {voiceTranscriptionConfig ? (
            <button
              className={`composer-voice-button is-${voice.state}`}
              type="button"
              aria-label={t(voiceActive ? 'composer.voice.stop' : 'composer.voice.start')}
              aria-pressed={voiceActive}
              title={
                voiceDisabledReason ??
                t(voiceActive ? 'composer.voice.stop' : 'composer.voice.start')
              }
              disabled={
                disabled ||
                sending ||
                uploadingAttachments ||
                voiceCallActive ||
                voiceConnection.availability !== 'available'
              }
              onClick={() => void toggleVoice()}
            >
              <VoiceMicrophoneIcon active={voiceActive} />
              {voiceActive ? (
                <span className="composer-voice-wave" aria-hidden="true">
                  <i />
                  <i />
                  <i />
                </span>
              ) : null}
            </button>
          ) : null}
          {voiceTranscriptionConfig ? (
            <button
              className={`composer-voice-button composer-call-button is-${voiceCall.status}`}
              type="button"
              aria-label={t(
                voiceCallActive ? 'composer.voiceCall.end' : 'composer.voiceCall.start',
              )}
              aria-pressed={voiceCallActive}
              title={
                voiceCallActive
                  ? t('composer.voiceCall.end')
                  : voiceCallDisabledReason ?? t('composer.voiceCall.start')
              }
              disabled={
                !voiceCallActive &&
                (disabled ||
                  sending ||
                  responseStreaming ||
                  uploadingAttachments ||
                  voiceActive ||
                  voiceCallConnection.availability !== 'available')
              }
              onClick={() => void toggleVoiceCall()}
            >
              <VoiceCallIcon active={voiceCallActive} />
            </button>
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
          {composerPresentation.showRuntimeStatus ? (
            <span
              className={`composer-status-button composer-status-dot ${
                disabledReason ? 'is-blocked' : 'is-connected'
              }`}
              aria-label={disabledReason ?? t('session.runtimeAvailable')}
              title={disabledReason ?? t('session.runtimeAvailable')}
            />
          ) : null}
          {responseStreaming && stopResponseAvailable && stopResponseStatus !== 'stopped' ? (
            <Button
              size="2"
              color="red"
              variant="soft"
              className="stop-response-pill"
              type="button"
              aria-label={
                stopResponseStatus === 'stopping'
                  ? t('session.stoppingResponse')
                  : t('session.stopResponse')
              }
              title={
                stopResponseStatus === 'stopping'
                  ? t('session.stoppingResponse')
                  : t('session.stopResponse')
              }
              loading={stopResponseStatus === 'stopping'}
              disabled={stopResponseStatus === 'stopping'}
              onClick={onStopResponse}
            >
              <StopIcon />
            </Button>
          ) : null}
          <Button
            size="2"
            color="green"
            className="send-pill"
            type="submit"
            aria-label={
              composeAheadQueueEligibility.canQueue
                ? t('chat.composeAhead.queueMessage')
                : runInputDelivery === 'steer_now'
                ? t('session.sendSteering')
                : runInputDelivery === 'queue_next'
                  ? t('session.sendQueuedInput')
                  : t('session.sendMessage')
            }
            title={
              composeAheadEnabled &&
              responseStreaming &&
              composeAheadQueueEligibility.reason &&
              composeAheadQueueEligibility.reason !== 'empty'
                ? t('chat.composeAhead.unsupportedContext')
                : runInputDeliveryOptions.length
                  ? t('session.sendShortcut')
                  : undefined
            }
            loading={sending}
            disabled={!canSubmit}
          >
            {composeAheadQueueEligibility.canQueue ? <ClockIcon /> : <ArrowUpIcon />}
          </Button>
        </Flex>
        </Flex>
      </div>
      {voiceCallActive ? (
        <VoiceCallPanel
          status={voiceCall.status}
          transcript={voiceCall.transcript}
          errorCode={voiceCall.errorCode}
          isMuted={voiceCall.isMuted}
          isSpeaking={voiceCall.isSpeaking}
          startedAt={voiceCall.startedAt}
          onToggleMute={() => void voiceCall.toggleMute()}
          onEnd={voiceCall.end}
        />
      ) : null}
    </form>
  );
}

function agentStopErrorTranslationKey(errorCode: AgentStopErrorCode): string {
  switch (errorCode) {
    case 'SESSION_NOT_RUNNING':
      return 'session.stopResponseNotRunning';
    case 'STOP_SESSION_FAILED':
      return 'session.stopResponseFailed';
    case 'socket_unavailable':
      return 'session.stopResponseDisconnected';
  }
}

function VoiceCallIcon({ active }: { active: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 20 20"
      width="18"
      height="18"
      fill="none"
    >
      <path
        d="M5.2 4.1 7.6 3l2.1 4.2-1.5 1.2a10.8 10.8 0 0 0 3.4 3.4l1.2-1.5 4.2 2.1-1.1 2.4c-.4.8-1.3 1.3-2.2 1.1A12.9 12.9 0 0 1 4.1 6.3c-.2-.9.3-1.8 1.1-2.2Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      {active ? (
        <path d="m4 4 12 12" stroke="currentColor" strokeWidth="1.5" />
      ) : null}
    </svg>
  );
}

function VoiceMicrophoneIcon({ active }: { active: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 20 20"
      width="18"
      height="18"
      fill="none"
    >
      <rect
        x="7"
        y="2.5"
        width="6"
        height="9"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M4.8 9.5a5.2 5.2 0 0 0 10.4 0M10 14.7v2.8M7.5 17.5h5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      {active ? (
        <path d="M3 4.5 17 15.5" stroke="currentColor" strokeWidth="1.6" />
      ) : null}
    </svg>
  );
}

const ComposeAheadQueue = memo(function ComposeAheadQueue({
  prompts,
  scope,
}: {
  prompts: readonly ComposeAheadPrompt[];
  scope: string | null;
}) {
  const { t } = useI18n();
  if (!scope) return null;
  return (
    <section
      className="compose-ahead-queue"
      aria-label={t('chat.composeAhead.region')}
      aria-live="polite"
    >
      <strong>{t('chat.composeAhead.count', { count: prompts.length })}</strong>
      <div>
        {prompts.map((prompt, index) => {
          const skill = prompt.contextItems.find(
            (item) => item.metadata?.execution_slot === 'skill',
          );
          const subagent = prompt.contextItems.find(
            (item) => item.metadata?.execution_slot === 'subagent',
          );
          return (
            <span
              className={`compose-ahead-prompt is-${prompt.status}`}
              title={prompt.text}
              key={prompt.id}
            >
              <ClockIcon aria-hidden="true" />
              <span>{composeAheadPreview(prompt.text)}</span>
              {skill ? <em>/{skill.label}</em> : null}
              {subagent ? <em>@{subagent.label}</em> : null}
              {index === 0 ? (
                <small>{t(`chat.composeAhead.status.${prompt.status}`)}</small>
              ) : null}
              {prompt.status === 'failed' ? (
                <button
                  type="button"
                  onClick={() => composeAheadQueueStore.retry(scope, prompt.id)}
                >
                  {t('chat.composeAhead.retry')}
                </button>
              ) : null}
              <button
                type="button"
                aria-label={t('chat.composeAhead.remove', { prompt: prompt.text })}
                onClick={() => composeAheadQueueStore.remove(scope, prompt.id)}
              >
                <Cross2Icon aria-hidden="true" />
              </button>
            </span>
          );
        })}
      </div>
    </section>
  );
});

function composeAheadPreview(text: string): string {
  const normalized = text.trim();
  return normalized.length > 60 ? `${normalized.slice(0, 60).trim()}…` : normalized;
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
