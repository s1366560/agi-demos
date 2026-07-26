import { Fragment, useEffect, useMemo, useState } from 'react';
import { Button, Text } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  CaretRightIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CodeIcon,
  ExclamationTriangleIcon,
  FileTextIcon,
  MagnifyingGlassIcon,
  Pencil1Icon,
  ReloadIcon,
  UpdateIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  AgentTimelineItem,
  ConversationTimelineState,
  DesktopApprovalRequest,
  HitlResponseSubmission,
} from '../../types';
import { buildSessionNarrative, timelineGroupOpen } from '../session/sessionNarrativeModel';
import type { SessionActivityPresence, SessionNarrativeNode } from '../session/sessionNarrativeModel';
import { resolveA2UIActionView } from './a2uiAction';
import type { A2UIActionView } from './a2uiAction';
import {
  assistantCostTracking,
  assistantDisplayDuplicateItems,
  assistantExecutionSummary,
  detectPayloadLanguage,
  formatToolCallDuration,
  shouldShowAgentWorkingIndicator,
  timelineItemsForDisplay,
  timelineWorkingStartedAtUs,
  timelineDayKey,
  timelineDayLabel,
  toolActivityRows,
  toolCallDiffStat,
  toolCallPairDurationMs,
  toolCallPairStatus,
  toolCallPresentationKind,
} from './chatTimelineModel';
import type { ToolCallPair, ToolCallPresentationKind } from './chatTimelineModel';
import { agentLifecyclePresentation } from './agentLifecyclePresentationModel';
import { groupSubAgentTimelineItems } from './subagentTimelineGroupModel';
import type { SubAgentTimelineGroup } from './subagentTimelineGroupModel';
import {
  formatTimelineTime,
  isImportantTimelineItem,
  isTimelineItemInitiallyExpanded,
  timelineDetailLineCount,
  timelineFileMetadata,
  timelineHasDetails,
  timelineHitlRequestId,
  timelineHitlType,
  timelineIcon,
  timelineKind,
  timelinePayloadPreview,
  timelineStatus,
  timelineSummary,
  timelineTitle,
  timelineToolDisplay,
  ToolFileMetadataView,
} from './chatTimelinePresentation';
import type { TimelineKind } from './chatTimelinePresentation';
import { AggregatedSourcesCard } from './AggregatedSourcesCard';
import { AssistantArtifactReferences } from './AssistantArtifactReferences';
import { ArtifactTimelineCard } from './ArtifactTimelineCard';
import { CodeBlockFrame } from './HighlightedCode';
import { HitlResponseCard } from './HitlResponseCard';
import { MCPAppTimelineCard } from './MCPAppTimelineCard';
import { MarkdownArtifactImageProvider } from './MarkdownArtifactImage';
import { MemoryTimelineEvent } from './MemoryTimelineCards';
import { MessageForcedSkillBadge } from './MessageForcedSkillBadge';
import { isMemoryTimelineEvent } from './memoryTimelineModel';
import { MessageAttachments } from './MessageAttachments';
import { groupMCPAppTimelineItems } from './mcpAppTimelineModel';
import type { MCPAppTimelineGroup } from './mcpAppTimelineModel';
import { SkillTimelineCard } from './SkillTimelineCard';
import { groupSkillTimelineItems } from './skillTimelineGroupModel';
import type { SkillTimelineGroup } from './skillTimelineGroupModel';
import { ThoughtTimelineCard } from './ThoughtTimelineCard';
import type { TimelineTurn } from './timelineTurnCollapseModel';
import { WorkPlanTimelineCard } from './WorkPlanTimelineCard';
import {
  MarkdownContent,
  NarrativeMessageFrame,
  SessionEmptyState,
} from './ChatTranscript';
import './AssistantDuplicateDisclosure.css';

const TIMELINE_RENDER_THRESHOLD = 150;
const TIMELINE_RENDER_WINDOW = 100;
export const TIMELINE_RENDER_STEP = 100;
const EMPTY_PINNED_MESSAGE_IDS: readonly string[] = [];
const EMPTY_TIMELINE_TURNS: readonly TimelineTurn[] = [];
const EMPTY_COLLAPSED_TURN_IDS: readonly string[] = [];

type TimelineActivityGroupNode = {
  kind: 'activity_group';
  id: string;
  items: AgentTimelineItem[];
};

type TimelineSubAgentGroupNode = {
  kind: 'subagent_group';
  id: string;
  items: AgentTimelineItem[];
  group: SubAgentTimelineGroup;
};

type TimelineSkillGroupNode = {
  kind: 'skill_group';
  id: string;
  items: AgentTimelineItem[];
  group: SkillTimelineGroup;
};

type TimelineMCPAppGroupNode = {
  kind: 'mcp_app_group';
  id: string;
  items: AgentTimelineItem[];
  group: MCPAppTimelineGroup;
};

type TimelinePresentationNode =
  | SessionNarrativeNode
  | TimelineActivityGroupNode
  | TimelineSubAgentGroupNode
  | TimelineSkillGroupNode
  | TimelineMCPAppGroupNode;

type TimelineGroupNode = Exclude<TimelinePresentationNode, { kind: 'item' }>;

type TimelineGroupAnnotation = {
  groupId: string;
  membersJson: string;
};

type AnnotatedTimelineNode =
  | Extract<TimelinePresentationNode, { kind: 'item' }>
  | (TimelineGroupNode & TimelineGroupAnnotation);

export function AgentTimeline({
  state,
  expandedItems,
  onToggleItem,
  onLoadEarlier,
  onShowEarlier,
  earlierRenderAllowance,
  onRetry,
  onRespondToHitl,
  respondableHitlRequestIds,
  activityPresence,
  onOpenMCPAppResult,
  onReplyMessage,
  onEditMessage,
  onDeleteMessage,
  onRetryMessage,
  onSaveTemplateMessage,
  pinnedMessageIds = EMPTY_PINNED_MESSAGE_IDS,
  onPinMessage,
  retryDisabled = false,
  turns = EMPTY_TIMELINE_TURNS,
  collapsedTurnIds = EMPTY_COLLAPSED_TURN_IDS,
  onToggleTurn = () => undefined,
}: {
  state: ConversationTimelineState;
  expandedItems: Record<string, boolean>;
  onToggleItem: (item: AgentTimelineItem) => void;
  onLoadEarlier: () => void;
  onShowEarlier: () => void;
  earlierRenderAllowance: number;
  onRetry: () => void;
  onRespondToHitl: (submission: HitlResponseSubmission) => Promise<void>;
  respondableHitlRequestIds: readonly string[];
  activityPresence: SessionActivityPresence;
  onOpenMCPAppResult?: (item: AgentTimelineItem) => void;
  onReplyMessage?: (item: AgentTimelineItem) => void;
  onEditMessage?: (item: AgentTimelineItem) => void;
  onDeleteMessage?: (item: AgentTimelineItem, returnFocus: HTMLElement) => void;
  onRetryMessage?: (item: AgentTimelineItem) => void;
  onSaveTemplateMessage?: (item: AgentTimelineItem, returnFocus: HTMLElement) => void;
  pinnedMessageIds?: readonly string[];
  onPinMessage?: (item: AgentTimelineItem) => void;
  retryDisabled?: boolean;
  turns?: readonly TimelineTurn[];
  collapsedTurnIds?: readonly string[];
  onToggleTurn?: (turnId: string) => void;
}) {
  const { t } = useI18n();
  const respondableHitlRequestIdSet = useMemo(
    () => new Set(respondableHitlRequestIds),
    [respondableHitlRequestIds],
  );
  const pinnedMessageIdSet = useMemo(() => new Set(pinnedMessageIds), [pinnedMessageIds]);
  const a2uiActionViews = useMemo(
    () =>
      new Map(
        state.items
          .filter((item) => timelineHitlType(item) === 'a2ui_action')
          .map((item) => [item.id, resolveA2UIActionView(item, state.items)] as const),
      ),
    [state.items],
  );
  const displayItems = useMemo(() => timelineItemsForDisplay(state.items), [state.items]);
  const narrative = useMemo(
    () => annotateTimelineGroups(groupNarrativeActivity(buildSessionNarrative(displayItems))),
    [displayItems],
  );
  const lastToolGroupIndex = useMemo(() => {
    for (let index = narrative.length - 1; index >= 0; index -= 1) {
      if (narrative[index].kind === 'tool_group') return index;
    }
    return -1;
  }, [narrative]);
  const renderWindow = useMemo(
    () => resolveTimelineRenderWindow(narrative, displayItems.length, earlierRenderAllowance),
    [narrative, displayItems.length, earlierRenderAllowance],
  );
  const collapsedTurnIdSet = useMemo(
    () => new Set(collapsedTurnIds),
    [collapsedTurnIds],
  );
  const turnByUserItemId = useMemo(
    () => new Map(turns.map((turn) => [turn.userItemId, turn] as const)),
    [turns],
  );
  const turnCollapsePresentation = useMemo(
    () => timelineTurnCollapsePresentation(narrative, turns, renderWindow.startIndex),
    [narrative, renderWindow.startIndex, turns],
  );
  const [expandedGroupItems, setExpandedGroupItems] = useState<Record<string, boolean>>({});
  const showWorkingIndicator = shouldShowAgentWorkingIndicator({
    items: displayItems,
    presence: activityPresence,
    awaitingHitl: respondableHitlRequestIdSet.size > 0,
  });
  const setGroupOpen = (items: AgentTimelineItem[], open: boolean) => {
    setExpandedGroupItems((current) => {
      const next = { ...current };
      let changed = false;
      items.forEach((item) => {
        if (next[item.id] === open) return;
        next[item.id] = open;
        changed = true;
      });
      return changed ? next : current;
    });
  };

  if (state.loading) {
    return (
      <div
        className="chat-empty-state timeline-loading"
        role="status"
        aria-label={t('session.loadingHistory')}
      >
        <span className="timeline-skeleton-bar is-wide" aria-hidden="true" />
        <span className="timeline-skeleton-bar" aria-hidden="true" />
        <span className="timeline-skeleton-bar is-short" aria-hidden="true" />
        <span className="sr-only">{t('session.loadingHistory')}</span>
      </div>
    );
  }

  let lastRenderedDayKey = '';

  const timeline = (
    <div className="agent-timeline" aria-label={t('session.conversationTimeline')}>
      {state.error ? (
        <div className="timeline-error" role="alert" aria-live="assertive">
          <Text size="2" color="red">
            {state.error}
          </Text>
          <Button
            type="button"
            size="1"
            variant="surface"
            className="timeline-history-action"
            onClick={state.items.length ? onLoadEarlier : onRetry}
          >
            <ReloadIcon aria-hidden="true" />
            {t(state.items.length ? 'session.retryEarlierHistory' : 'session.retryHistory')}
          </Button>
        </div>
      ) : null}
      {!state.error && (state.hasMore || state.loadingEarlier) ? (
        <div className="timeline-history-control" aria-live="polite">
          {state.loadingEarlier ? (
            <Text size="1" color="gray" role="status">
              {t('session.loadingEarlierHistory')}
            </Text>
          ) : (
            <Button
              type="button"
              size="1"
              variant="ghost"
              className="timeline-history-action"
              onClick={onLoadEarlier}
            >
              {t('session.loadEarlierHistory')}
            </Button>
          )}
        </div>
      ) : null}
      {renderWindow.hiddenCount > 0 ? (
        <div className="timeline-history-control" aria-live="polite">
          <Button
            type="button"
            size="1"
            variant="ghost"
            className="timeline-history-action"
            onClick={onShowEarlier}
          >
            {t('session.showEarlierItems', { count: renderWindow.hiddenCount })}
          </Button>
        </div>
      ) : null}
      {displayItems.length === 0 && !state.error ? (
        <SessionEmptyState />
      ) : (
        narrative.map((node, index) => {
          if (index < renderWindow.startIndex) return null;
          const responseTurnId = turnCollapsePresentation.nodeTurnIds[index];
          const responseCollapsed = Boolean(
            responseTurnId && collapsedTurnIdSet.has(responseTurnId),
          );
          if (
            responseCollapsed &&
            responseTurnId &&
            turnCollapsePresentation.firstVisibleNodeIndex.get(responseTurnId) !== index
          ) {
            return null;
          }
          const nodeTimeUs =
            node.kind === 'item' ? node.item.eventTimeUs : node.items[0]?.eventTimeUs;
          const dayKey = timelineDayKey(nodeTimeUs);
          const dayDivider =
            dayKey && dayKey !== lastRenderedDayKey && nodeTimeUs ? (
              <TimelineDayDivider key={`day-${dayKey}`} timeUs={nodeTimeUs} />
            ) : null;
          if (dayKey) lastRenderedDayKey = dayKey;
          if (responseCollapsed && responseTurnId) {
            const turn = turns.find((candidate) => candidate.id === responseTurnId);
            const regionId = timelineTurnResponseRegionId(responseTurnId);
            const controlId = timelineTurnControlId(responseTurnId);
            const count =
              turnCollapsePresentation.responsePresentationCounts.get(responseTurnId) ?? 0;
            const membersJson = JSON.stringify(turn?.responseItemIds ?? []);
            return (
              <Fragment key={`collapsed-turn:${responseTurnId}`}>
                {dayDivider}
                <div
                  id={regionId}
                  className="timeline-turn-placeholder-shell"
                  role="group"
                  aria-label={t('session.turnItemsHidden', { count })}
                >
                  <button
                    type="button"
                    className="timeline-turn-placeholder"
                    data-timeline-anchor-id={`collapsed-turn:${responseTurnId}`}
                    data-timeline-anchor-members={membersJson}
                    aria-expanded={false}
                    aria-controls={regionId}
                    aria-label={t('session.expandTurn', { count })}
                    onClick={() => {
                      onToggleTurn(responseTurnId);
                      window.requestAnimationFrame(() => {
                        window.requestAnimationFrame(() => {
                          document.getElementById(controlId)?.focus();
                        });
                      });
                    }}
                  >
                    <ChevronRightIcon aria-hidden="true" />
                    <span>{t('session.turnItemsHidden', { count })}</span>
                  </button>
                </div>
              </Fragment>
            );
          }
          const responseRegionMarker =
            responseTurnId &&
            turnCollapsePresentation.firstVisibleNodeIndex.get(responseTurnId) === index ? (
              <span
                id={timelineTurnResponseRegionId(responseTurnId)}
                className="timeline-turn-response-anchor"
                role="group"
                aria-label={t('session.turnResponseGroup')}
              />
            ) : null;
          if (node.kind === 'item' && isMemoryTimelineEvent(node.item)) {
            return (
              <Fragment key={node.id}>
                {dayDivider}
                {responseRegionMarker}
                <MemoryTimelineEvent
                  key={`${state.conversationId ?? 'unscoped'}:${node.item.id}`}
                  item={node.item}
                  conversationId={state.conversationId}
                />
              </Fragment>
            );
          }
          if (node.kind === 'subagent_group') {
            const groupId = timelineGroupIdentity(narrative, index);
            const open = timelineGroupOpen(
              node.items,
              expandedGroupItems,
              node.group.status === 'running' || node.group.status === 'steered',
            );
            return (
              <Fragment key={groupId}>
                {dayDivider}
                {responseRegionMarker}
                <SubAgentGroupView
                  group={node.group}
                  expanded={open}
                  onToggle={() => setGroupOpen(node.items, !open)}
                  anchorId={groupId}
                />
              </Fragment>
            );
          }
          if (node.kind === 'skill_group') {
            const groupId = timelineGroupIdentity(narrative, index);
            const open = timelineGroupOpen(
              node.items,
              expandedGroupItems,
              node.group.status === 'matched' || node.group.status === 'executing',
            );
            return (
              <Fragment key={groupId}>
                {dayDivider}
                {responseRegionMarker}
                <SkillTimelineCard
                  skill={node.group}
                  expanded={open}
                  onToggle={() => setGroupOpen(node.items, !open)}
                  anchorId={groupId}
                />
              </Fragment>
            );
          }
          if (node.kind === 'mcp_app_group') {
            const groupId = timelineGroupIdentity(narrative, index);
            const open = timelineGroupOpen(node.items, expandedGroupItems);
            const resultItem = node.group.resultItem;
            const openApp =
              resultItem && onOpenMCPAppResult
                ? () => onOpenMCPAppResult(resultItem)
                : undefined;
            return (
              <Fragment key={groupId}>
                {dayDivider}
                {responseRegionMarker}
                <MCPAppTimelineCard
                  app={node.group}
                  expanded={open}
                  onToggle={() => setGroupOpen(node.items, !open)}
                  onOpen={openApp}
                  anchorId={groupId}
                />
              </Fragment>
            );
          }
          if (node.kind === 'activity_group') {
            const groupId = timelineGroupIdentity(narrative, index);
            const open = node.items.some((item) => expandedGroupItems[item.id]);
            return (
              <Fragment key={groupId}>
                {dayDivider}
                {responseRegionMarker}
                <details
                  className="timeline-debug-group"
                  data-timeline-anchor-id={groupId}
                  data-timeline-anchor-members={node.membersJson}
                  open={open}
                  onToggle={(event) => setGroupOpen(node.items, event.currentTarget.open)}
                >
                  <summary>
                    <span className="timeline-debug-group-icon" aria-hidden="true">
                      <ActivityLogIcon />
                    </span>
                    <span>
                      <strong>{t('session.runActivity')}</strong>
                      <small>{t('session.runActivityCount', { count: node.items.length })}</small>
                    </span>
                    <em>{t('session.inspect')}</em>
                    <ChevronRightIcon className="timeline-debug-group-chevron" aria-hidden="true" />
                  </summary>
                  <div className="timeline-debug-group-items">
                    {node.items.map((item) => (
                      <TimelineItemView
                        item={item}
                        expanded={expandedItems[item.id] ?? false}
                        onToggle={() => onToggleItem(item)}
                        onRespondToHitl={onRespondToHitl}
                        canRespondToHitl={false}
                        key={item.id}
                      />
                    ))}
                  </div>
                </details>
              </Fragment>
            );
          }
          if (node.kind === 'tool_group') {
            const groupId = timelineGroupIdentity(narrative, index);
            const open = timelineGroupOpen(
              node.items,
              expandedGroupItems,
              index === lastToolGroupIndex,
            );
            return (
              <Fragment key={groupId}>
                {dayDivider}
                {responseRegionMarker}
                <details
                  className={`timeline-tool-group status-${node.status}`}
                  data-timeline-anchor-id={groupId}
                  data-timeline-anchor-members={node.membersJson}
                  open={open}
                >
                  <summary
                    className="timeline-tool-group-summary"
                    aria-expanded={open}
                    onClick={(event) => {
                      event.preventDefault();
                      setGroupOpen(node.items, !open);
                    }}
                  >
                    <span className="timeline-tool-group-icon" aria-hidden>
                      <ActivityLogIcon />
                    </span>
                    <span>
                      <strong>{t('session.toolActivity')}</strong>
                      <small>{t('session.toolActivityCount', { count: node.toolCount })}</small>
                    </span>
                    <em>{t(`session.toolStatus.${node.status}`)}</em>
                    <ChevronRightIcon className="timeline-tool-group-chevron" aria-hidden />
                  </summary>
                  <div className="timeline-tool-group-items">
                    <AggregatedSourcesCard items={node.items} />
                    {toolActivityRows(node.items).map((row) =>
                      row.kind === 'thought' ? (
                        <TimelineItemView
                          item={row.item}
                          expanded={expandedItems[row.item.id] ?? false}
                          onToggle={() => onToggleItem(row.item)}
                          onRespondToHitl={onRespondToHitl}
                          canRespondToHitl={false}
                          key={row.item.id}
                        />
                      ) : (
                        <ToolCallPairView
                          pair={row.pair}
                          expanded={expandedItems[row.pair.call.id] ?? false}
                          onToggle={() => onToggleItem(row.pair.call)}
                          key={row.pair.call.id}
                        />
                      ),
                    )}
                  </div>
                </details>
              </Fragment>
            );
          }
          const item = node.item;
          const requestId = timelineHitlRequestId(item);
          const turn = turnByUserItemId.get(item.id);
          const turnResponseCount = turn
            ? turnCollapsePresentation.responsePresentationCounts.get(turn.id) ?? 0
            : 0;
          const collapsed = Boolean(turn && collapsedTurnIdSet.has(turn.id));
          const regionId = turn ? timelineTurnResponseRegionId(turn.id) : '';
          return (
            <Fragment key={node.id}>
              {dayDivider}
              {responseRegionMarker}
              <TimelineItemView
                item={item}
                expanded={expandedItems[item.id] ?? isTimelineItemInitiallyExpanded(item)}
                onToggle={() => onToggleItem(item)}
                onRespondToHitl={onRespondToHitl}
                canRespondToHitl={Boolean(
                  requestId && respondableHitlRequestIdSet.has(requestId),
                )}
                a2uiActionView={a2uiActionViews.get(item.id)}
                approvalRequest={state.approvalRequests.find(
                  (request) => request.id === requestId,
                )}
                onReplyMessage={onReplyMessage}
                onEditMessage={onEditMessage}
                onDeleteMessage={onDeleteMessage}
                onRetryMessage={onRetryMessage}
                onSaveTemplateMessage={onSaveTemplateMessage}
                isPinned={pinnedMessageIdSet.has(item.id)}
                onPinMessage={onPinMessage}
                retryDisabled={retryDisabled}
              />
              {turn && turnResponseCount > 0 ? (
                <button
                  id={timelineTurnControlId(turn.id)}
                  type="button"
                  className="timeline-turn-collapse-control"
                  aria-expanded={!collapsed}
                  aria-controls={regionId}
                  aria-label={t(collapsed ? 'session.expandTurn' : 'session.collapseTurn', {
                    count: turnResponseCount,
                  })}
                  title={t(collapsed ? 'session.expandTurn' : 'session.collapseTurn', {
                    count: turnResponseCount,
                  })}
                  onClick={() => onToggleTurn(turn.id)}
                >
                  {collapsed ? (
                    <ChevronRightIcon aria-hidden="true" />
                  ) : (
                    <ChevronDownIcon aria-hidden="true" />
                  )}
                  <span>
                    {t(collapsed ? 'session.expandTurnShort' : 'session.collapseTurnShort')}
                  </span>
                </button>
              ) : null}
            </Fragment>
          );
        })
      )}
      {showWorkingIndicator ? (
        <TimelineWorkingRow items={state.items} />
      ) : null}
    </div>
  );
  return (
    <MarkdownArtifactImageProvider carriers={state.items}>
      {timeline}
    </MarkdownArtifactImageProvider>
  );
}

function TimelineDayDivider({ timeUs }: { timeUs: number }) {
  const { t } = useI18n();
  const label = timelineDayLabel(timeUs);
  return (
    <div className="timeline-day-divider" aria-hidden="true">
      <span>
        {label.kind === 'today'
          ? t('session.today')
          : label.kind === 'yesterday'
            ? t('session.yesterday')
            : label.date}
      </span>
    </div>
  );
}

function TimelineWorkingRow({ items }: { items: AgentTimelineItem[] }) {
  const { t } = useI18n();
  const startedAtUs = timelineWorkingStartedAtUs(items);
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!startedAtUs) return undefined;
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [startedAtUs]);
  const duration = startedAtUs
    ? formatToolCallDuration(Math.max(0, nowMs - Math.floor(startedAtUs / 1_000)))
    : '';
  return (
    <div
      className="timeline-working-indicator timeline-worklog-row active"
      role="status"
      aria-live="polite"
    >
      <span className="timeline-working-spinner" aria-hidden="true" />
      <span className="timeline-working-copy">
        <strong>{t('session.agentWorking')}</strong>
      </span>
      {duration ? <em>{t('session.workedFor', { duration })}</em> : null}
    </div>
  );
}

function ToolCallPairView({
  pair,
  expanded,
  onToggle,
}: {
  pair: ToolCallPair;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  const status = toolCallPairStatus(pair);
  const presentationKind = toolCallPresentationKind(pair);
  const diffStat = toolCallDiffStat(pair);
  const primary = pair.result ?? pair.call;
  const title =
    timelineToolDisplay(pair.call)?.title ||
    (presentationKind === 'tool'
      ? pair.call.toolName || t('chat.toolCall')
      : t(`session.toolKind.${presentationKind}`));
  const rawSummary = timelineSummary(primary, 'tool', t);
  const summary = stripRedundantToolPrefix(rawSummary, title, pair.call.toolName);
  const durationMs = toolCallPairDurationMs(pair);
  const hasDetails = timelineHasDetails(pair.call, 'tool') || Boolean(pair.result);
  const memberIds = pair.result ? [pair.call.id, pair.result.id] : [pair.call.id];
  return (
    <article
      className={`timeline-worklog-row kind-${presentationKind} message timeline-row timeline-item tool tool-call status-${status} ${
        expanded ? 'is-expanded' : ''
      }`}
      data-timeline-anchor-id={pair.call.id}
      data-timeline-anchor-members={JSON.stringify(memberIds)}
    >
      {hasDetails ? (
        <button
          type="button"
          className="timeline-row-toggle"
          aria-label={t(expanded ? 'chat.collapseItem' : 'chat.expandItem', { item: title })}
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
          <span className={`timeline-row-icon tool-call-icon is-${status}`} aria-hidden="true">
            <TimelineToolIcon kind={presentationKind} status={status} />
          </span>
          <span className="timeline-row-title">{title}</span>
          <span className="timeline-row-summary">{summary}</span>
        </div>
        {expanded && hasDetails ? <ToolCallPairBody pair={pair} /> : null}
      </div>
      <div className="timeline-row-meta">
        {diffStat ? (
          <span className="timeline-diff-count">
            <b>+{diffStat.additions}</b>
            <i>−{diffStat.deletions}</i>
          </span>
        ) : null}
        {status === 'running' ? (
          <span className="timeline-status waiting">{t('chat.status.running')}</span>
        ) : null}
        {status === 'failed' ? (
          <span className="timeline-status error">{t('chat.status.error')}</span>
        ) : null}
        {durationMs !== null ? (
          <span className="timeline-pair-duration">{formatToolCallDuration(durationMs)}</span>
        ) : null}
        <span>{formatTimelineTime(primary)}</span>
      </div>
    </article>
  );
}

function TimelineToolIcon({
  kind,
  status,
}: {
  kind: ToolCallPresentationKind;
  status: 'running' | 'complete' | 'failed';
}) {
  if (status === 'running') return <UpdateIcon />;
  if (status === 'failed') return <ExclamationTriangleIcon />;
  if (kind === 'search') return <MagnifyingGlassIcon />;
  if (kind === 'read') return <FileTextIcon />;
  if (kind === 'command') return <CaretRightIcon />;
  if (kind === 'edit') return <Pencil1Icon />;
  if (kind === 'check') return <CheckIcon />;
  return <CodeIcon />;
}

function stripRedundantToolPrefix(
  summary: string,
  title: string,
  toolName: string | undefined,
): string {
  for (const prefix of [title, toolName ?? '']) {
    if (prefix && summary.startsWith(`${prefix} `)) {
      return summary.slice(prefix.length + 1);
    }
  }
  return summary;
}

function ToolCallPairBody({ pair }: { pair: ToolCallPair }) {
  const { t } = useI18n();
  const display = timelineToolDisplay(pair.call) ?? timelineToolDisplay(pair.result ?? pair.call);
  const fileMetadata =
    timelineFileMetadata(pair.result ?? pair.call) ?? timelineFileMetadata(pair.call);
  const input = pair.call.toolInput;
  const output = pair.result?.toolOutput ?? pair.result?.payload;
  return (
    <div className="timeline-details">
      {display?.summary ? (
        <Text as="p" size="2" className="timeline-detail-summary">
          {display.summary}
        </Text>
      ) : null}
      {fileMetadata ? <ToolFileMetadataView metadata={fileMetadata} /> : null}
      {display?.details !== undefined ? (
        <TimelinePayloadBlock label={t('chat.displayDetails')} value={display.details} />
      ) : null}
      {input !== undefined ? (
        <TimelinePayloadBlock label={t('chat.input')} value={input} />
      ) : null}
      {output !== undefined ? (
        <TimelinePayloadBlock label={t('chat.output')} value={output} />
      ) : null}
      {pair.call.payload !== undefined ? (
        <TimelinePayloadBlock label={t('chat.payload')} value={pair.call.payload} />
      ) : null}
      {pair.result?.error ? (
        <Text size="1" color="red">
          {pair.result.error}
        </Text>
      ) : null}
    </div>
  );
}

function TimelinePayloadBlock({ label, value }: { label: string; value: unknown }) {
  const payload = detectPayloadLanguage(value);
  return (
    <div className="timeline-detail-block">
      <span>{label}</span>
      <CodeBlockFrame
        code={payload.code}
        language={payload.language}
        collapsibleAfterLines={24}
        wrap
      />
    </div>
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
  onReplyMessage,
  onEditMessage,
  onDeleteMessage,
  onRetryMessage,
  onSaveTemplateMessage,
  isPinned = false,
  onPinMessage,
  retryDisabled = false,
}: {
  item: AgentTimelineItem;
  expanded: boolean;
  onToggle: () => void;
  onRespondToHitl: (submission: HitlResponseSubmission) => Promise<void>;
  canRespondToHitl: boolean;
  a2uiActionView?: A2UIActionView;
  approvalRequest?: DesktopApprovalRequest;
  onReplyMessage?: (item: AgentTimelineItem) => void;
  onEditMessage?: (item: AgentTimelineItem) => void;
  onDeleteMessage?: (item: AgentTimelineItem, returnFocus: HTMLElement) => void;
  onRetryMessage?: (item: AgentTimelineItem) => void;
  onSaveTemplateMessage?: (item: AgentTimelineItem, returnFocus: HTMLElement) => void;
  isPinned?: boolean;
  onPinMessage?: (item: AgentTimelineItem) => void;
  retryDisabled?: boolean;
}) {
  const { t } = useI18n();
  const kind = timelineKind(item);
  const lineCount = useMemo(() => timelineDetailLineCount(item, kind), [item, kind]);
  const summary = useMemo(() => timelineSummary(item, kind, t), [item, kind, t]);
  if (kind === 'artifact') {
    return <ArtifactTimelineCard item={item} />;
  }
  if (item.type === 'thought') {
    return <ThoughtTimelineCard item={item} expanded={expanded} onToggle={onToggle} />;
  }
  if (item.type === 'work_plan' || item.type === 'task_list_updated') {
    return <WorkPlanTimelineCard item={item} expanded={expanded} onToggle={onToggle} />;
  }
  if (kind === 'user' || kind === 'agent') {
    return (
      <NarrativeMessageFrame
        kind={kind}
        label={timelineTitle(item, t)}
        time={formatTimelineTime(item)}
        content={item.content ?? ''}
        badge={kind === 'agent' ? t('session.workspaceAgent') : null}
        className="timeline-item"
        timelineItemId={item.id}
        streaming={Boolean(item.metadata?.streaming)}
        onReply={
          item.content?.trim() && onReplyMessage
            ? () => onReplyMessage(item)
            : undefined
        }
        onEdit={
          kind === 'user' && item.content?.trim() && onEditMessage
            ? () => onEditMessage(item)
            : undefined
        }
        onDelete={
          kind === 'user' && onDeleteMessage
            ? (returnFocus) => onDeleteMessage(item, returnFocus)
            : undefined
        }
        onRetry={
          kind === 'agent' && item.content?.trim() && onRetryMessage
            ? () => onRetryMessage(item)
            : undefined
        }
        isPinned={kind === 'agent' && isPinned}
        onPin={
          kind === 'agent' && item.content?.trim() && onPinMessage
            ? () => onPinMessage(item)
            : undefined
        }
        onSaveTemplate={
          kind === 'agent' &&
          !item.metadata?.streaming &&
          item.content?.trim() &&
          onSaveTemplateMessage
            ? (returnFocus) => onSaveTemplateMessage(item, returnFocus)
            : undefined
        }
        retryDisabled={retryDisabled || Boolean(item.metadata?.streaming)}
      >
        <TimelineItemBody
          item={item}
          kind={kind}
          onRespondToHitl={onRespondToHitl}
          canRespondToHitl={canRespondToHitl}
          a2uiActionView={a2uiActionView}
          approvalRequest={approvalRequest}
        />
      </NarrativeMessageFrame>
    );
  }

  const hasDetails = timelineHasDetails(item, kind);
  const status = timelineStatus(item);
  return (
    <article
      className={`message timeline-row timeline-item ${kind} ${expanded ? 'is-expanded' : ''} ${
        approvalRequest ? 'has-approval-evidence' : ''
      }`}
      data-timeline-anchor-id={item.id}
      tabIndex={-1}
    >
      {hasDetails ? (
        <button
          type="button"
          className="timeline-row-toggle"
          aria-label={t(expanded ? 'chat.collapseItem' : 'chat.expandItem', {
            item: timelineTitle(item, t),
          })}
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
          <span className="timeline-row-title">{timelineTitle(item, t)}</span>
          <span className="timeline-row-summary">{summary}</span>
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
        {status ? (
          <span className={`timeline-status ${status.kind}`}>
            {status.localized ? t(status.label) : status.label}
          </span>
        ) : null}
        {lineCount > 1 ? <span>{t('chat.lineCount', { count: lineCount })}</span> : null}
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
  const { t } = useI18n();
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

  const lifecycle = agentLifecyclePresentation(item);
  if (lifecycle?.family === 'elicitation') {
    const answered = item.type === 'elicitation_answered' || item.answered === true;
    const requestId = timelineHitlRequestId(item);
    return (
      <div className="timeline-details">
        {lifecycle.detail || lifecycle.subject ? (
          <Text as="p" size="2" className="timeline-detail-summary">
            {lifecycle.detail || lifecycle.subject}
          </Text>
        ) : null}
        <div className="agent-run-meta">
          <span>
            {t(answered ? 'chat.status.answered' : 'chat.status.waitingForInput')}
          </span>
          {requestId ? <span>{requestId}</span> : null}
        </div>
      </div>
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
          <TimelinePayloadBlock label={t('chat.displayDetails')} value={display.details} />
        ) : null}
        {item.toolInput !== undefined ? (
          <TimelinePayloadBlock label={t('chat.input')} value={item.toolInput} />
        ) : null}
        {item.toolOutput !== undefined ? (
          <TimelinePayloadBlock label={t('chat.output')} value={item.toolOutput} />
        ) : null}
        {item.payload !== undefined ? (
          <TimelinePayloadBlock label={t('chat.payload')} value={item.payload} />
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
          <span>{t(item.answered ? 'chat.status.answered' : 'chat.status.waitingForInput')}</span>
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
        <TimelinePayloadBlock label={t('chat.payload')} value={item.payload} />
      </div>
    );
  }

  const content =
    kind === 'user' || kind === 'agent'
      ? (item.content ?? '')
      : item.content || timelinePayloadPreview(item);
  if (item.type === 'thought') {
    return <MarkdownContent content={content} className="transcript-content thought-content" />;
  }
  if (kind === 'user' || kind === 'agent') {
    return (
      <>
        {kind === 'agent' ? <AssistantExecutionSummary item={item} /> : null}
        <MarkdownContent content={content} className="transcript-content" />
        {kind === 'agent' ? <AssistantDuplicateDisclosure item={item} /> : null}
        {kind === 'agent' ? (
          <AssistantArtifactReferences artifacts={item.artifacts} metadata={item.metadata} />
        ) : null}
        {kind === 'user' ? (
          <>
            <MessageForcedSkillBadge message={item} />
            <MessageAttachments item={item} />
          </>
        ) : null}
      </>
    );
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

function AssistantDuplicateDisclosure({ item }: { item: AgentTimelineItem }) {
  const { t } = useI18n();
  const originals = assistantDisplayDuplicateItems(item);
  if (originals.length < 2) return null;

  return (
    <details className="assistant-duplicate-disclosure">
      <summary>
        <span>
          <UpdateIcon aria-hidden="true" />
          <strong>{t('chat.duplicateAssistantReplies', { count: originals.length })}</strong>
        </span>
        <span>
          {t('chat.duplicateAssistantRepliesAudit')}
          <CaretRightIcon aria-hidden="true" />
        </span>
      </summary>
      <ol>
        {originals.map((original, index) => {
          const source = assistantDuplicateSourceLabel(original);
          return (
            <li key={original.id}>
              <span>{t('chat.duplicateAssistantReply', { index: index + 1 })}</span>
              <code>{original.message_id || original.id}</code>
              <time>{formatTimelineTime(original)}</time>
              {source ? <small>{source}</small> : null}
            </li>
          );
        })}
      </ol>
    </details>
  );
}

function assistantDuplicateSourceLabel(item: AgentTimelineItem): string {
  const payload = isTimelineRecord(item.payload) ? item.payload : null;
  const payloadMetadata =
    payload && isTimelineRecord(payload.metadata) ? payload.metadata : null;
  const records = [item.metadata, payload, payloadMetadata].filter(isTimelineRecord);
  const keys = [
    'agent_id',
    'agentId',
    'source_agent_id',
    'sourceAgentId',
    'sender_id',
    'senderId',
    'source',
  ];
  for (const record of records) {
    for (const key of keys) {
      const value = record[key];
      if (typeof value === 'string' && value.trim()) return value.trim();
    }
  }
  return '';
}

function isTimelineRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function AssistantExecutionSummary({ item }: { item: AgentTimelineItem }) {
  const { t } = useI18n();
  const summary = assistantExecutionSummary(item);
  if (!summary) return null;
  const costTracking = assistantCostTracking(item);
  const pills: Array<{ label: string; value: string }> = [];
  if (summary.stepCount > 0) {
    pills.push({ label: t('chat.summary.steps'), value: String(summary.stepCount) });
  }
  if (summary.tasks && summary.tasks.total > 0) {
    pills.push({
      label: t('chat.summary.tasks'),
      value: `${summary.tasks.completed}/${summary.tasks.total}`,
    });
    if (summary.tasks.remaining > 0) {
      pills.push({
        label: t('chat.summary.remaining'),
        value: String(summary.tasks.remaining),
      });
    }
  }
  if (summary.artifactCount > 0) {
    pills.push({ label: t('chat.summary.artifacts'), value: String(summary.artifactCount) });
  }
  if (summary.callCount > 0) {
    pills.push({ label: t('chat.summary.calls'), value: String(summary.callCount) });
  }
  if (summary.totalTokens > 0) {
    pills.push({ label: t('chat.summary.tokens'), value: String(summary.totalTokens) });
  }
  if (costTracking) {
    pills.push({ label: t('chat.input'), value: String(costTracking.inputTokens) });
    pills.push({ label: t('chat.output'), value: String(costTracking.outputTokens) });
    if (costTracking.reasoningTokens > 0) {
      pills.push({
        label: t('session.activityReasoning'),
        value: String(costTracking.reasoningTokens),
      });
    }
  }
  if (summary.totalCost > 0) {
    pills.push({ label: t('chat.summary.cost'), value: summary.totalCostFormatted });
  }
  return (
    <div className="assistant-execution-summary" aria-label={t('chat.executionSummary')}>
      {pills.map((pill) => (
        <span key={pill.label}>
          <small>{pill.label}</small>
          <strong>{pill.value}</strong>
        </span>
      ))}
    </div>
  );
}

function SubAgentGroupView({
  group,
  expanded,
  onToggle,
  anchorId,
}: {
  group: SubAgentTimelineGroup;
  expanded: boolean;
  onToggle: () => void;
  anchorId: string;
}) {
  const { t } = useI18n();
  const displayName = group.subagentName || group.subagentId || t('chat.subagentUnnamed');
  const title =
    group.mode === 'parallel'
      ? t('chat.parallel')
      : group.mode === 'chain'
        ? t('chat.chain')
        : t('chat.subagentExecution', { name: displayName });
  const phaseEntries = [
    ['routed', group.phases.routed],
    ['started', group.phases.started],
    ['executing', group.phases.executing],
    ['ended', group.phases.ended],
  ] as const;
  const showProgress =
    group.progress !== null &&
    group.progress >= 0 &&
    group.progress <= 100 &&
    (group.status === 'running' || group.status === 'steered');
  return (
    <article
      className={`timeline-subagent-group status-${group.status} ${expanded ? 'is-expanded' : ''}`}
      data-timeline-anchor-id={anchorId}
      data-timeline-anchor-members={JSON.stringify(group.itemIds)}
      data-subagent-id={group.subagentId || undefined}
    >
      <button
        type="button"
        className="subagent-group-header"
        aria-expanded={expanded}
        aria-label={t(expanded ? 'chat.collapseItem' : 'chat.expandItem', { item: title })}
        onClick={onToggle}
      >
        <span className="subagent-group-chevron" aria-hidden="true">
          {expanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
        </span>
        <span className="subagent-group-icon" aria-hidden="true">
          {group.status === 'success' ? (
            <CheckIcon />
          ) : group.status === 'error' || group.status === 'killed' ? (
            <ExclamationTriangleIcon />
          ) : (
            <ActivityLogIcon />
          )}
        </span>
        <span className="subagent-group-copy">
          <strong>{title}</strong>
          <small>{t('chat.subagentLifecycleCount', { count: group.items.length })}</small>
        </span>
        <span className="subagent-group-metrics">
          {group.confidence !== null ? (
            <span>{t('chat.percentCount', { count: Math.round(group.confidence * 100) })}</span>
          ) : null}
          {group.tokensUsed !== null && group.tokensUsed > 0 ? (
            <span>{t('chat.tokensCount', { count: group.tokensUsed })}</span>
          ) : null}
          {group.executionTimeMs !== null && group.executionTimeMs > 0 ? (
            <span>{formatToolCallDuration(group.executionTimeMs)}</span>
          ) : null}
          <em className={`timeline-status ${subAgentStatusTone(group.status)}`}>
            {t(`chat.subagentStatus.${group.status}`)}
          </em>
        </span>
      </button>
      {showProgress ? (
        <div
          className="subagent-progress"
          role="progressbar"
          aria-label={t('chat.subagentProgress')}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={group.progress ?? undefined}
        >
          <span className="subagent-progress-bar" style={{ width: `${group.progress}%` }} />
        </div>
      ) : null}
      {expanded ? (
        <div className="subagent-group-body">
          <div className="subagent-phase-list" aria-label={t('chat.subagentLifecycle')}>
            {phaseEntries.map(([phase, active]) => (
              <span className={active ? 'is-active' : undefined} key={phase}>
                {t(`chat.subagentPhase.${phase}`)}
              </span>
            ))}
          </div>
          {group.statusMessage ? (
            <p className="subagent-live-status">{group.statusMessage}</p>
          ) : null}
          <SubAgentDetail label={t('chat.task')} value={group.task} />
          <SubAgentDetail label={t('chat.subagentReason')} value={group.reason} />
          <SubAgentDetail label={t('chat.subagentResult')} value={group.summary} emphasis />
          <SubAgentDetail label={t('chat.subagentFailure')} value={group.error} error />
          {group.toolCallsCount !== null && group.toolCallsCount > 0 ? (
            <div className="subagent-group-facts">
              <span>{t('chat.callsCount', { count: group.toolCallsCount })}</span>
              {group.tokensUsed !== null && group.tokensUsed > 0 ? (
                <span>{t('chat.tokensCount', { count: group.tokensUsed })}</span>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function SubAgentDetail({
  label,
  value,
  emphasis = false,
  error = false,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
  error?: boolean;
}) {
  if (!value) return null;
  return (
    <div
      className={`subagent-detail${emphasis ? ' is-emphasis' : ''}${error ? ' is-error' : ''}`}
    >
      <span>{label}</span>
      <p>{value}</p>
    </div>
  );
}

function subAgentStatusTone(status: SubAgentTimelineGroup['status']): 'ok' | 'error' | 'waiting' {
  if (status === 'success') return 'ok';
  if (status === 'error' || status === 'killed' || status === 'depth_limited') return 'error';
  return 'waiting';
}

function groupNarrativeActivity(narrative: SessionNarrativeNode[]): TimelinePresentationNode[] {
  const grouped: TimelinePresentationNode[] = [];
  let activityItems: AgentTimelineItem[] = [];
  const itemNodes = narrative.flatMap((node) => (node.kind === 'item' ? [node.item] : []));
  const subagentGrouping = groupSubAgentTimelineItems(itemNodes);
  const subagentGroupsByStartItem = new Map(
    subagentGrouping.groups.map((group) => [group.startItemId, group]),
  );
  const claimedSubagentItemIds = new Set(subagentGrouping.claimedItemIds);
  const skillGrouping = groupSkillTimelineItems(itemNodes);
  const skillGroupsByStartItem = new Map(
    skillGrouping.groups.map((group) => [group.startItemId, group]),
  );
  const claimedSkillItemIds = new Set(skillGrouping.claimedItemIds);
  const mcpAppGrouping = groupMCPAppTimelineItems(itemNodes);
  const mcpAppGroupsByStartItem = new Map(
    mcpAppGrouping.groups.map((group) => [group.startItemId, group]),
  );
  const claimedMCPAppItemIds = new Set(mcpAppGrouping.claimedItemIds);

  const flushActivityItems = () => {
    if (!activityItems.length) return;
    grouped.push({
      kind: 'activity_group',
      id: `activity-group:${activityItems[0].id}:${activityItems[activityItems.length - 1].id}`,
      items: activityItems,
    });
    activityItems = [];
  };

  narrative.forEach((node) => {
    if (node.kind === 'item' && isMemoryTimelineEvent(node.item)) {
      flushActivityItems();
      grouped.push(node);
      return;
    }
    if (node.kind === 'item') {
      const mcpAppGroup = mcpAppGroupsByStartItem.get(node.item.id);
      if (mcpAppGroup) {
        flushActivityItems();
        grouped.push({
          kind: 'mcp_app_group',
          id: mcpAppGroup.id,
          items: mcpAppGroup.items,
          group: mcpAppGroup,
        });
        return;
      }
      if (claimedMCPAppItemIds.has(node.item.id)) return;
      const skillGroup = skillGroupsByStartItem.get(node.item.id);
      if (skillGroup) {
        flushActivityItems();
        grouped.push({
          kind: 'skill_group',
          id: skillGroup.id,
          items: skillGroup.items,
          group: skillGroup,
        });
        return;
      }
      if (claimedSkillItemIds.has(node.item.id)) return;
      const subagentGroup = subagentGroupsByStartItem.get(node.item.id);
      if (subagentGroup) {
        flushActivityItems();
        grouped.push({
          kind: 'subagent_group',
          id: subagentGroup.id,
          items: subagentGroup.items,
          group: subagentGroup,
        });
        return;
      }
      if (claimedSubagentItemIds.has(node.item.id)) return;
    }
    if (
      node.kind === 'item' &&
      (node.item.type === 'artifact_created' ||
        node.item.type === 'artifact_ready' ||
        node.item.type === 'artifact_error')
    ) {
      flushActivityItems();
      grouped.push(node);
      return;
    }
    // Reasoning traces stay first-class, collapsible rows instead of being
    // folded into the debug activity group.
    if (node.kind === 'item' && node.item.type === 'thought') {
      flushActivityItems();
      grouped.push(node);
      return;
    }
    if (
      node.kind === 'item' &&
      (node.item.type === 'work_plan' ||
        node.item.type === 'task_list_updated')
    ) {
      flushActivityItems();
      grouped.push(node);
      return;
    }
    if (node.kind === 'item' && isCollapsibleRuntimeItem(node.item)) {
      activityItems.push(node.item);
      return;
    }
    flushActivityItems();
    grouped.push(node);
  });
  flushActivityItems();

  return grouped;
}

function annotateTimelineGroups(nodes: TimelinePresentationNode[]): AnnotatedTimelineNode[] {
  const annotated: AnnotatedTimelineNode[] = new Array(nodes.length);
  let ordinalsAfterItem: Record<string, number> = {};
  let lastItemId: string | null = null;
  let leadingGroups: Array<{ node: TimelineGroupNode; index: number }> = [];

  const annotateGroup = (node: TimelineGroupNode, index: number, groupId: string) => {
    annotated[index] = {
      ...node,
      groupId,
      membersJson: JSON.stringify(node.items.map((item) => item.id)),
    };
  };

  const resolveLeadingGroups = (nextItemId: string | null) => {
    const ordinalsBeforeItem: Record<string, number> = {};
    for (let position = leadingGroups.length - 1; position >= 0; position -= 1) {
      const { node, index } = leadingGroups[position];
      const ordinal = ordinalsBeforeItem[node.kind] ?? 0;
      annotateGroup(
        node,
        index,
        nextItemId
          ? `${node.kind}:before:${nextItemId}:${ordinal}`
          : `${node.kind}:unbounded:${ordinal}`,
      );
      ordinalsBeforeItem[node.kind] = ordinal + 1;
    }
    leadingGroups = [];
  };

  nodes.forEach((node, index) => {
    if (node.kind === 'item') {
      if (lastItemId === null) resolveLeadingGroups(node.id);
      lastItemId = node.id;
      ordinalsAfterItem = {};
      annotated[index] = node;
      return;
    }
    if (lastItemId !== null) {
      const ordinal = ordinalsAfterItem[node.kind] ?? 0;
      annotateGroup(node, index, `${node.kind}:after:${lastItemId}:${ordinal}`);
      ordinalsAfterItem[node.kind] = ordinal + 1;
      return;
    }
    leadingGroups.push({ node, index });
  });
  if (lastItemId === null) resolveLeadingGroups(null);

  return annotated;
}

function timelineGroupIdentity(narrative: AnnotatedTimelineNode[], index: number): string {
  const node = narrative[index];
  if (!node || node.kind === 'item') return node?.id ?? `timeline-node:${index}`;
  return node.groupId;
}

function timelineTurnCollapsePresentation(
  narrative: readonly AnnotatedTimelineNode[],
  turns: readonly TimelineTurn[],
  startIndex: number,
): {
  nodeTurnIds: Array<string | null>;
  responsePresentationCounts: Map<string, number>;
  firstVisibleNodeIndex: Map<string, number>;
} {
  const responseTurnByItemId = new Map<string, string>();
  turns.forEach((turn) => {
    turn.responseItemIds.forEach((itemId) => responseTurnByItemId.set(itemId, turn.id));
  });
  const responsePresentationCounts = new Map<string, number>();
  const firstVisibleNodeIndex = new Map<string, number>();
  const nodeTurnIds = narrative.map((node, index) => {
    const memberIds = timelineNodeMemberIds(node);
    const turnId = memberIds.length ? responseTurnByItemId.get(memberIds[0]) : undefined;
    const sharedTurn =
      turnId && memberIds.every((memberId) => responseTurnByItemId.get(memberId) === turnId)
        ? turnId
        : null;
    if (!sharedTurn) return null;
    responsePresentationCounts.set(
      sharedTurn,
      (responsePresentationCounts.get(sharedTurn) ?? 0) + 1,
    );
    if (index >= startIndex && !firstVisibleNodeIndex.has(sharedTurn)) {
      firstVisibleNodeIndex.set(sharedTurn, index);
    }
    return sharedTurn;
  });
  return { nodeTurnIds, responsePresentationCounts, firstVisibleNodeIndex };
}

function timelineNodeMemberIds(node: AnnotatedTimelineNode): string[] {
  return node.kind === 'item' ? [node.item.id] : node.items.map((item) => item.id);
}

function timelineTurnResponseRegionId(turnId: string): string {
  return `timeline-turn-response-${encodeURIComponent(turnId)}`;
}

function timelineTurnControlId(turnId: string): string {
  return `timeline-turn-control-${encodeURIComponent(turnId)}`;
}

function resolveTimelineRenderWindow(
  narrative: AnnotatedTimelineNode[],
  itemCount: number,
  earlierAllowance: number,
): { startIndex: number; hiddenCount: number } {
  if (itemCount <= TIMELINE_RENDER_THRESHOLD) return { startIndex: 0, hiddenCount: 0 };
  const budget = TIMELINE_RENDER_WINDOW + earlierAllowance;
  if (budget >= itemCount) return { startIndex: 0, hiddenCount: 0 };
  let coveredItems = 0;
  let startIndex = narrative.length;
  while (startIndex > 0 && coveredItems < budget) {
    startIndex -= 1;
    const node = narrative[startIndex];
    coveredItems += node.kind === 'item' ? 1 : node.items.length;
  }
  return { startIndex, hiddenCount: itemCount - coveredItems };
}

function isCollapsibleRuntimeItem(item: AgentTimelineItem): boolean {
  return timelineKind(item) === 'runtime' && !isImportantTimelineItem(item);
}
