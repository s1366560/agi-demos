import { useMemo } from 'react';
import { Text } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CodeIcon,
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

type TimelinePresentationNode =
  | SessionNarrativeNode
  | {
      kind: 'activity_group';
      id: string;
      items: AgentTimelineItem[];
    };

export function AgentTimeline({
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
  const narrative = useMemo(
    () => groupNarrativeActivity(buildSessionNarrative(state.items)),
    [state.items],
  );

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
        <div className="timeline-error" role="status">
          <Text size="2" color="red">
            {state.error}
          </Text>
        </div>
      ) : null}
      {state.hasMore || state.loadingEarlier ? (
        <div className="timeline-load-earlier" role="status" aria-live="polite">
          {state.loadingEarlier
            ? t('session.loadingEarlierHistory')
            : t('session.scrollForEarlierHistory')}
        </div>
      ) : null}
      {state.items.length === 0 && !state.error ? (
        <SessionEmptyState />
      ) : (
        narrative.map((node) => {
          if (node.kind === 'activity_group') {
            return (
              <details className="timeline-debug-group" key={node.id}>
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
            return (
              <details className={`timeline-tool-group status-${node.status}`} key={node.id}>
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
  if (kind === 'user' || kind === 'agent') {
    return (
      <NarrativeMessageFrame
        kind={kind}
        label={timelineTitle(item, t)}
        time={formatTimelineTime(item)}
        content={item.content ?? ''}
        badge={kind === 'agent' ? t('session.workspaceAgent') : null}
        className="timeline-item"
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
          <span className="timeline-row-summary">{timelineSummary(item, kind, t)}</span>
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

function isCollapsibleRuntimeItem(item: AgentTimelineItem): boolean {
  return timelineKind(item) === 'runtime' && !isImportantTimelineItem(item);
}
