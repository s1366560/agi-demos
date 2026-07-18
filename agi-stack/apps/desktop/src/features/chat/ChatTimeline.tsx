import { useMemo, useState } from 'react';
import { Button, Text } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CodeIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  AgentTimelineItem,
  ConversationTimelineState,
  DesktopApprovalRequest,
  HitlResponseSubmission,
} from '../../types';
import { buildSessionNarrative } from '../session/sessionNarrativeModel';
import type { SessionNarrativeNode } from '../session/sessionNarrativeModel';
import { resolveA2UIActionView } from './a2uiAction';
import type { A2UIActionView } from './a2uiAction';
import {
  formatTimelineTime,
  formatTimelineValue,
  isImportantTimelineItem,
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
import { HitlResponseCard } from './HitlResponseCard';
import {
  MarkdownContent,
  NarrativeMessageFrame,
  SessionEmptyState,
} from './ChatTranscript';

type TimelineActivityGroupNode = {
  kind: 'activity_group';
  id: string;
  items: AgentTimelineItem[];
};

type TimelinePresentationNode = SessionNarrativeNode | TimelineActivityGroupNode;

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
  onRetry,
  onRespondToHitl,
  respondableHitlRequestIds,
}: {
  state: ConversationTimelineState;
  expandedItems: Record<string, boolean>;
  onToggleItem: (item: AgentTimelineItem) => void;
  onLoadEarlier: () => void;
  onRetry: () => void;
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
  const narrative = useMemo(
    () => annotateTimelineGroups(groupNarrativeActivity(buildSessionNarrative(state.items))),
    [state.items],
  );
  const [expandedGroupItems, setExpandedGroupItems] = useState<Record<string, boolean>>({});
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
        <Text size="2" color="gray">
          {t('session.loadingHistory')}
        </Text>
      </div>
    );
  }

  return (
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
      {state.items.length === 0 && !state.error ? (
        <SessionEmptyState />
      ) : (
        narrative.map((node, index) => {
          if (node.kind === 'activity_group') {
            const groupId = timelineGroupIdentity(narrative, index);
            const open = node.items.some((item) => expandedGroupItems[item.id]);
            return (
              <details
                className="timeline-debug-group"
                data-timeline-anchor-id={groupId}
                data-timeline-anchor-members={node.membersJson}
                key={groupId}
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
            );
          }
          if (node.kind === 'tool_group') {
            const groupId = timelineGroupIdentity(narrative, index);
            const open = node.items.some((item) => expandedGroupItems[item.id]);
            return (
              <details
                className={`timeline-tool-group status-${node.status}`}
                data-timeline-anchor-id={groupId}
                data-timeline-anchor-members={node.membersJson}
                key={groupId}
                open={open}
                onToggle={(event) => setGroupOpen(node.items, event.currentTarget.open)}
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
  const { t } = useI18n();
  const kind = timelineKind(item);
  const lineCount = useMemo(() => timelineDetailLineCount(item, kind), [item, kind]);
  const summary = useMemo(() => timelineSummary(item, kind, t), [item, kind, t]);
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
            <span>{t('chat.displayDetails')}</span>
            <pre>{formatTimelineValue(display.details)}</pre>
          </div>
        ) : null}
        {item.toolInput !== undefined ? (
          <div className="timeline-detail-block">
            <span>{t('chat.input')}</span>
            <pre>{formatTimelineValue(item.toolInput)}</pre>
          </div>
        ) : null}
        {item.toolOutput !== undefined ? (
          <div className="timeline-detail-block">
            <span>{t('chat.output')}</span>
            <pre>{formatTimelineValue(item.toolOutput)}</pre>
          </div>
        ) : null}
        {item.payload !== undefined ? (
          <div className="timeline-detail-block">
            <span>{t('chat.payload')}</span>
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
          {item.filename || item.artifactId || t('chat.artifact')}
        </Text>
        {item.error ? (
          <Text size="1" color="red">
            {item.error}
          </Text>
        ) : null}
        {item.payload !== undefined ? (
          <div className="timeline-detail-block">
            <span>{t('chat.payload')}</span>
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
        <div className="timeline-detail-block">
          <span>{t('chat.payload')}</span>
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

function groupNarrativeActivity(narrative: SessionNarrativeNode[]): TimelinePresentationNode[] {
  const grouped: TimelinePresentationNode[] = [];
  let activityItems: AgentTimelineItem[] = [];

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

function isCollapsibleRuntimeItem(item: AgentTimelineItem): boolean {
  return timelineKind(item) === 'runtime' && !isImportantTimelineItem(item);
}
