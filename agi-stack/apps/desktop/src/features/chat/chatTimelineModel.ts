import type { AgentTimelineItem } from '../../types';

// Pure presentation logic for the agent conversation timeline. Kept free of
// React/JSX so the node:test harness can compile and exercise it directly
// (see tests/chat-timeline-model.test.mjs).

/**
 * One rendered tool-call row: an `act` item paired with the `observe` item
 * that answers it. A lone trailing `act` is a call still in flight; a lone
 * `observe` (e.g. resumed history without its call) renders as a completed
 * call on its own.
 */
export type ToolCallPair = {
  call: AgentTimelineItem;
  result: AgentTimelineItem | null;
};

export type ToolActivityRow =
  | { kind: 'thought'; item: AgentTimelineItem }
  | { kind: 'tool_call'; pair: ToolCallPair };

export type ToolCallPairStatus = 'running' | 'complete' | 'failed';

export type ToolCallPresentationKind =
  | 'search'
  | 'read'
  | 'command'
  | 'edit'
  | 'check'
  | 'tool';

export type ToolCallDiffStat = {
  filesChanged: number;
  additions: number;
  deletions: number;
};

export type ThoughtStreamChunk = {
  kind: 'start' | 'delta' | 'complete';
  messageId: string;
  content: string;
  eventTimeUs: number;
  eventCounter: number;
  payload?: Record<string, unknown>;
};

export function mergeThoughtStreamChunk(
  existing: AgentTimelineItem[],
  chunk: ThoughtStreamChunk,
): AgentTimelineItem[] {
  const activeIndex = findActiveThoughtIndex(existing, chunk.messageId);
  if (chunk.kind !== 'start' && activeIndex >= 0) {
    const updated = existing.map((item, index) => {
      if (index !== activeIndex) return item;
      return {
        ...item,
        eventTimeUs: chunk.eventTimeUs,
        eventCounter: chunk.eventCounter,
        timestamp: Math.floor(chunk.eventTimeUs / 1000),
        content:
          chunk.kind === 'delta'
            ? `${item.content ?? ''}${chunk.content}`
            : chunk.content || item.content,
        payload: chunk.payload ?? item.payload,
        metadata: { ...(item.metadata ?? {}), streaming: chunk.kind !== 'complete' },
      };
    });
    return sortTimelineItems(updated);
  }

  return sortTimelineItems([
    ...existing,
    {
      id: `streaming-thought-${chunk.messageId}-${chunk.eventTimeUs}-${chunk.eventCounter}`,
      type: 'thought',
      eventTimeUs: chunk.eventTimeUs,
      eventCounter: chunk.eventCounter,
      timestamp: Math.floor(chunk.eventTimeUs / 1000),
      message_id: chunk.messageId,
      content: chunk.content,
      payload: chunk.payload,
      metadata: { streaming: chunk.kind !== 'complete' },
    },
  ]);
}

function findActiveThoughtIndex(items: AgentTimelineItem[], messageId: string): number {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (
      item.type === 'thought' &&
      item.message_id === messageId &&
      item.metadata?.streaming === true
    ) {
      return index;
    }
  }
  return -1;
}

function sortTimelineItems(items: AgentTimelineItem[]): AgentTimelineItem[] {
  return items.sort((left, right) => {
    if (left.eventTimeUs !== right.eventTimeUs) return left.eventTimeUs - right.eventTimeUs;
    return left.eventCounter - right.eventCounter;
  });
}

export function pairToolCallItems(items: AgentTimelineItem[]): ToolCallPair[] {
  const pairs: ToolCallPair[] = [];
  let pendingCall: AgentTimelineItem | null = null;
  for (const item of items) {
    if (item.type === 'act') {
      if (pendingCall) pairs.push({ call: pendingCall, result: null });
      pendingCall = item;
      continue;
    }
    if (item.type === 'observe') {
      if (pendingCall && toolCallNamesMatch(pendingCall, item)) {
        pairs.push({ call: pendingCall, result: item });
        pendingCall = null;
      } else {
        pairs.push({ call: item, result: null });
      }
      continue;
    }
    pairs.push({ call: item, result: null });
  }
  if (pendingCall) pairs.push({ call: pendingCall, result: null });
  return pairs;
}

export function toolActivityRows(items: AgentTimelineItem[]): ToolActivityRow[] {
  const rows: ToolActivityRow[] = [];
  let toolItems: AgentTimelineItem[] = [];
  const flushTools = () => {
    rows.push(
      ...pairToolCallItems(toolItems).map(
        (pair): ToolActivityRow => ({ kind: 'tool_call', pair }),
      ),
    );
    toolItems = [];
  };

  for (const item of items) {
    if (item.type === 'thought') {
      flushTools();
      rows.push({ kind: 'thought', item });
    } else {
      toolItems.push(item);
    }
  }
  flushTools();
  return rows;
}

export function toolCallPairStatus(pair: ToolCallPair): ToolCallPairStatus {
  if (pair.result) {
    return pair.result.isError || pair.result.error ? 'failed' : 'complete';
  }
  if (pair.call.isError || pair.call.error) return 'failed';
  return pair.call.type === 'observe' ? 'complete' : 'running';
}

export function toolCallPairDurationMs(pair: ToolCallPair): number | null {
  if (!pair.result) return null;
  const deltaUs = pair.result.eventTimeUs - pair.call.eventTimeUs;
  return deltaUs > 0 ? deltaUs / 1000 : null;
}

export function formatToolCallDuration(durationMs: number): string {
  if (!Number.isFinite(durationMs) || durationMs < 0) return '';
  if (durationMs < 1000) return `${Math.round(durationMs)}ms`;
  if (durationMs < 10_000) return `${(durationMs / 1000).toFixed(1)}s`;
  if (durationMs < 60_000) return `${Math.round(durationMs / 1000)}s`;
  const minutes = Math.floor(durationMs / 60_000);
  const seconds = Math.round((durationMs % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

export function toolCallPresentationKind(pair: ToolCallPair): ToolCallPresentationKind {
  for (const item of [pair.result, pair.call]) {
    const kind = item && isRecord(item.display) ? item.display.kind : null;
    if (
      kind === 'search' ||
      kind === 'read' ||
      kind === 'command' ||
      kind === 'edit' ||
      kind === 'check'
    ) {
      return kind;
    }
  }
  return 'tool';
}

export function toolCallDiffStat(pair: ToolCallPair): ToolCallDiffStat | null {
  for (const item of [pair.result, pair.call]) {
    if (!item) continue;
    const metadata = isRecord(item.fileMetadata)
      ? item.fileMetadata
      : isRecord(item.toolOutput) && isRecord(item.toolOutput.fileMetadata)
        ? item.toolOutput.fileMetadata
        : null;
    const diffStat = metadata && isRecord(metadata.diffStat) ? metadata.diffStat : null;
    if (!diffStat) continue;
    const filesChanged = nonNegativeInteger(diffStat.filesChanged);
    const additions = nonNegativeInteger(diffStat.additions);
    const deletions = nonNegativeInteger(diffStat.deletions);
    if (filesChanged === null && additions === null && deletions === null) continue;
    return {
      filesChanged: filesChanged ?? 0,
      additions: additions ?? 0,
      deletions: deletions ?? 0,
    };
  }
  return null;
}

export function timelineWorkingStartedAtUs(items: AgentTimelineItem[]): number | null {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (
      item.type === 'run_status' &&
      isRecord(item.payload) &&
      item.payload.status === 'running'
    ) {
      return item.eventTimeUs;
    }
  }
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item.role === 'user' || item.type === 'user_message') return item.eventTimeUs;
  }
  return null;
}

export type TimelineDayLabel =
  | { kind: 'today' }
  | { kind: 'yesterday' }
  | { kind: 'date'; date: string };

/** Calendar-day bucket key (local timezone) used to place day dividers. */
export function timelineDayKey(eventTimeUs: number | undefined): string {
  if (!eventTimeUs) return '';
  const date = new Date(Math.floor(eventTimeUs / 1000));
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

export function timelineDayLabel(eventTimeUs: number, nowMs = Date.now()): TimelineDayLabel {
  const itemMs = Math.floor(eventTimeUs / 1000);
  const diffDays = Math.round((startOfDay(nowMs) - startOfDay(itemMs)) / 86_400_000);
  if (diffDays <= 0) return { kind: 'today' };
  if (diffDays === 1) return { kind: 'yesterday' };
  const date = new Date(itemMs);
  const sameYear = date.getFullYear() === new Date(nowMs).getFullYear();
  const formatter = new Intl.DateTimeFormat(
    undefined,
    sameYear
      ? { month: 'short', day: 'numeric' }
      : { year: 'numeric', month: 'short', day: 'numeric' },
  );
  return { kind: 'date', date: formatter.format(date) };
}

/**
 * Whether the timeline tail should show the pulsing "agent is working"
 * indicator: the run is live, no HITL card is blocking, and the last event
 * is not already an in-flight assistant stream or a finished answer.
 */
export function shouldShowAgentWorkingIndicator(args: {
  items: AgentTimelineItem[];
  presence: 'live' | 'recorded';
  awaitingHitl: boolean;
}): boolean {
  const { items, presence, awaitingHitl } = args;
  if (presence !== 'live' || awaitingHitl || items.length === 0) return false;
  const last = items[items.length - 1];
  if (last.metadata?.streaming) return false;
  if (last.role === 'assistant' || last.type === 'assistant_message') return false;
  return true;
}

export type PayloadCode = {
  code: string;
  language: 'json' | 'text';
};

/**
 * Render a tool payload/input/output value for display: objects and
 * JSON-looking strings become pretty-printed `json` blocks, everything else
 * stays plain text (terminal output, prose, logs).
 */
export function detectPayloadLanguage(value: unknown): PayloadCode {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (trimmed.length > 1 && (trimmed.startsWith('{') || trimmed.startsWith('['))) {
      try {
        return { code: JSON.stringify(JSON.parse(trimmed), null, 2), language: 'json' };
      } catch {
        // Not actually JSON — fall through to plain text.
      }
    }
    return { code: value, language: 'text' };
  }
  try {
    return { code: JSON.stringify(value, null, 2), language: 'json' };
  } catch {
    return { code: String(value), language: 'text' };
  }
}

function toolCallNamesMatch(call: AgentTimelineItem, result: AgentTimelineItem): boolean {
  const callName = call.toolName ?? '';
  const resultName = result.toolName ?? '';
  return !callName || !resultName || callName === resultName;
}

function startOfDay(timeMs: number): number {
  const date = new Date(timeMs);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

function nonNegativeInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}
