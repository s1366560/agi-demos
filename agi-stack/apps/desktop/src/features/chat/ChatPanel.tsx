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
  DotsHorizontalIcon,
  ReaderIcon,
  ReloadIcon,
  RocketIcon,
} from '@radix-ui/react-icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import type {
  AgentTimelineItem,
  ConversationTimelineState,
  ToolDisplayData,
  ToolFileMetadata,
  WorkspaceMessage,
} from '../../types';
import { ComposerControls } from './ComposerControls';

type ChatPanelProps = {
  messages: WorkspaceMessage[];
  timelineState: ConversationTimelineState | null;
  agentTaskSignals: AgentTaskSignal[];
  sessionTitle: string;
  scopeLabel: string;
  input: string;
  sending: boolean;
  disabledReason: string | null;
  activeWorkflowTarget: ChatWorkflowTarget;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onRefresh: () => void;
  onLoadEarlier: () => void;
  onWorkflowSelect: (target: ChatWorkflowTarget) => void;
  onOpenUsagePlan: () => void;
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
  sessionTitle,
  scopeLabel,
  input,
  sending,
  disabledReason,
  activeWorkflowTarget,
  onInputChange,
  onSend,
  onRefresh,
  onLoadEarlier,
  onWorkflowSelect,
  onOpenUsagePlan,
}: ChatPanelProps) {
  const disabled = Boolean(disabledReason);
  const canSend = !disabled && !sending && Boolean(input.trim());
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const scrollAnchorRef = useRef<HTMLDivElement>(null);
  const timelineWindowRef = useRef<{ firstId: string; lastId: string; count: number } | null>(null);
  const earlierScrollRef = useRef<{ height: number; top: number } | null>(null);
  const [expandedTimelineItems, setExpandedTimelineItems] = useState<Record<string, boolean>>({});
  const signalStateKey = useMemo(
    () => agentTaskSignals.map((signal) => `${signal.id}:${signal.status}`).join('|'),
    [agentTaskSignals],
  );
  const timelineItemCount = timelineState?.items.length ?? 0;
  const timelineFirstId = timelineState?.items[0]?.id ?? '';
  const timelineLastId = timelineState?.items[timelineItemCount - 1]?.id ?? '';
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
      <ScrollArea className="message-scroll" ref={scrollAreaRef}>
        <div className="message-stack">
          {timelineState ? (
            <AgentTimeline
              state={timelineState}
              expandedItems={expandedTimelineItems}
              onToggleItem={toggleTimelineItem}
            />
          ) : messages.length === 0 ? (
            <div className="chat-empty-state" role="status" aria-label="Ready for a new task" />
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
        <ChatWorkflowStrip activeTarget={activeWorkflowTarget} onSelect={onWorkflowSelect} />
        <TextArea
          className="chat-composer-input"
          value={input}
          disabled={disabled}
          onChange={(event) => onInputChange(event.target.value)}
          placeholder={
            disabledReason ??
            'Describe a task to run autonomously. Type / for commands, @ for files, or # for issues...'
          }
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              handleSend();
            }
          }}
        />
        <Flex align="center" justify="between" className="chat-composer-footer">
          <ComposerControls disabledHint={disabledReason} modelLabel="Claude Fable 5 · 1M" />
          <Flex align="center" gap="2" className="composer-right-actions">
            <button
              className={`composer-status-button composer-status-dot ${
                disabledReason ? 'is-blocked' : 'is-connected'
              }`}
              type="button"
              aria-label={disabledReason ?? 'AI credits quota: 100% used'}
              aria-haspopup="dialog"
              title={disabledReason ?? 'AI credits quota: 100% used'}
              onClick={onOpenUsagePlan}
            />
            <Button
              size="2"
              color="green"
              className="send-pill"
              type="submit"
              aria-label="Send workspace message"
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
}: {
  state: ConversationTimelineState;
  expandedItems: Record<string, boolean>;
  onToggleItem: (item: AgentTimelineItem) => void;
}) {
  if (state.loading) {
    return (
      <div className="chat-empty-state timeline-loading" role="status" aria-label="Loading session history">
        <Text size="2" color="gray">
          Loading session history...
        </Text>
      </div>
    );
  }

  return (
    <div className="agent-timeline" aria-label="Agent conversation timeline">
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
        <div className="chat-empty-state" role="status" aria-label="No session history yet" />
      ) : (
        state.items.map((item) => (
          <TimelineItemView
            item={item}
            expanded={expandedItems[item.id] ?? isImportantTimelineItem(item)}
            onToggle={() => onToggleItem(item)}
            key={item.id}
          />
        ))
      )}
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
}: {
  item: AgentTimelineItem;
  expanded: boolean;
  onToggle: () => void;
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
        <TimelineItemBody item={item} kind={kind} />
      </article>
    );
  }

  const hasDetails = timelineHasDetails(item, kind);
  const status = timelineStatus(item);
  const lineCount = timelineDetailLineCount(item, kind);
  return (
    <article className={`message timeline-row timeline-item ${kind} ${expanded ? 'is-expanded' : ''}`}>
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
        {expanded && hasDetails ? <TimelineItemBody item={item} kind={kind} /> : null}
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
}: {
  item: AgentTimelineItem;
  kind: TimelineKind;
}) {
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
  onSelect,
}: {
  activeTarget: ChatWorkflowTarget;
  onSelect: (target: ChatWorkflowTarget) => void;
}) {
  const items: Array<[ChatWorkflowTarget, string, string, ReactNode]> = [
    ['changes', 'Changes', '+0 -0', <CodeIcon key="changes" />],
    ['pull', 'PR', 'idle', <ReaderIcon key="pull" />],
    ['plan', 'Plan', 'active', <ActivityLogIcon key="plan" />],
    ['background', 'Background', '0', <DotsHorizontalIcon key="background" />],
    ['artifacts', 'Artifacts', '0', <ArchiveIcon key="artifacts" />],
  ];

  return (
    <div className="composer-workflows chat-composer-workflows" aria-label="chat workflow shortcuts">
      {items.map(([target, label, value, icon]) => (
        <button
          className={activeTarget === target ? 'selected' : ''}
          type="button"
          aria-label={`${label} ${value}`}
          key={target}
          onClick={() => onSelect(target)}
        >
          <span>{icon}</span>
          <strong>{label}</strong>
          <em>{value}</em>
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
  if (item.question) return 'Human input';
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
  if (item.question && !item.answered) return true;
  if (item.type === 'work_plan') return true;
  if (item.type.startsWith('task_')) return true;
  if (item.type === 'artifact_error') return true;
  return false;
}

function timelineHasDetails(item: AgentTimelineItem, kind: TimelineKind): boolean {
  if (kind === 'user' || kind === 'agent') return false;
  if (timelineToolDisplay(item) || timelineFileMetadata(item)) return true;
  if (item.question || item.error || item.content) return true;
  if (item.toolInput !== undefined || item.toolOutput !== undefined) return true;
  if (item.payload !== undefined) return true;
  if (item.filename || item.artifactId) return true;
  return false;
}

function timelineSummary(item: AgentTimelineItem, kind: TimelineKind): string {
  if (item.error) return item.error;
  if (item.question) return item.question;
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
  if (item.question) {
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
