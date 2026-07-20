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

export type ToolCallPairStatus = 'running' | 'complete' | 'failed';

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
