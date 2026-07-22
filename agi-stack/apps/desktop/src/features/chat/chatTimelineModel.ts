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

export type AssistantTextStreamChunk = {
  kind: 'start' | 'delta' | 'complete';
  messageId: string;
  content: string;
  eventTimeUs: number;
  eventCounter: number;
  payload?: Record<string, unknown>;
};

export type AssistantCompletionChunk = {
  messageId: string;
  content: string;
  eventTimeUs: number;
  eventCounter: number;
  payload?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  artifacts?: unknown[];
};

export type AgentExecutionSummary = {
  stepCount: number;
  artifactCount: number;
  callCount: number;
  totalCost: number;
  totalCostFormatted: string;
  totalTokens: number;
  tasks: { total: number; completed: number; remaining: number } | null;
};

export type ToolStreamEventKind = 'delta' | 'act' | 'observe';

/**
 * Return follow-up suggestions for the latest Agent turn. A new user message
 * starts a new turn and therefore invalidates every earlier suggestion event.
 */
export function latestAgentSuggestions(items: AgentTimelineItem[]): string[] {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item.role === 'user' || item.type === 'user_message') return [];
    if (item.type !== 'suggestions') continue;
    const payload = isRecord(item.payload) ? item.payload : null;
    const source = Array.isArray(item.suggestions)
      ? item.suggestions
      : payload && Array.isArray(payload.suggestions)
        ? payload.suggestions
        : [];
    return source.filter(
      (suggestion): suggestion is string =>
        typeof suggestion === 'string' && suggestion.trim().length > 0,
    );
  }
  return [];
}

/** Suggestion events drive UI affordances and are not conversation log rows. */
export function timelineItemsForDisplay(items: AgentTimelineItem[]): AgentTimelineItem[] {
  return items.filter((item) => item.type !== 'suggestions');
}

/**
 * Apply artifact lifecycle updates to one stable timeline row. The Web client
 * treats ready/error as updates to artifact_created; preserving that identity
 * avoids duplicate rows while an upload settles.
 */
export function mergeArtifactStreamItem(
  existing: AgentTimelineItem[],
  incoming: AgentTimelineItem,
): AgentTimelineItem[] {
  const normalizedIncoming = normalizeArtifactStreamItem(incoming);
  if (incoming.type === 'artifact_ready' || incoming.type === 'artifact_error') {
    const artifactId = artifactStreamString(normalizedIncoming, ['artifactId', 'artifact_id']);
    const targetIndex = artifactId
      ? findLastArtifactCreatedIndex(existing, artifactId)
      : -1;
    if (targetIndex >= 0) {
      const incomingPayload = isRecord(normalizedIncoming.payload)
        ? normalizedIncoming.payload
        : {};
      return sortTimelineItems(
        existing.map((item, index) => {
          if (index !== targetIndex) return item;
          const currentPayload = isRecord(item.payload) ? item.payload : {};
          return {
            ...item,
            ...(normalizedIncoming.artifactId
              ? { artifactId: normalizedIncoming.artifactId }
              : {}),
            ...(normalizedIncoming.filename ? { filename: normalizedIncoming.filename } : {}),
            ...(normalizedIncoming.error ? { error: normalizedIncoming.error } : {}),
            ...(incoming.type === 'artifact_error' ? { isError: true } : {}),
            payload: { ...currentPayload, ...incomingPayload },
          };
        }),
      );
    }
  }
  return sortTimelineItems([...existing, normalizedIncoming]);
}

function normalizeArtifactStreamItem(item: AgentTimelineItem): AgentTimelineItem {
  const artifactId = artifactStreamString(item, ['artifactId', 'artifact_id']);
  const filename = artifactStreamString(item, ['filename']);
  const sourceTool = artifactStreamString(item, ['sourceTool', 'source_tool']);
  const error = artifactStreamString(item, ['error']);
  return {
    ...item,
    ...(artifactId ? { artifactId } : {}),
    ...(filename ? { filename } : {}),
    ...(sourceTool ? { sourceTool } : {}),
    ...(error ? { error } : {}),
    ...(item.type === 'artifact_error' ? { isError: true } : {}),
  };
}

function findLastArtifactCreatedIndex(items: AgentTimelineItem[], artifactId: string): number {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (
      item.type === 'artifact_created' &&
      artifactStreamString(item, ['artifactId', 'artifact_id']) === artifactId
    ) {
      return index;
    }
  }
  return -1;
}

function artifactStreamString(item: AgentTimelineItem, keys: string[]): string | null {
  const payload = isRecord(item.payload) ? item.payload : null;
  for (const source of [item, payload]) {
    if (!source) continue;
    for (const key of keys) {
      const value = source[key];
      if (typeof value === 'string' && value) return value;
    }
  }
  return null;
}

/**
 * Merge the three phases of a streamed tool call without creating one card
 * per argument delta. The backend gives deltas a `call_id`, then adds a
 * `tool_execution_id` on act/observe, so matching accepts either identifier.
 */
export function mergeToolStreamItem(
  existing: AgentTimelineItem[],
  incoming: AgentTimelineItem,
  kind: ToolStreamEventKind,
): AgentTimelineItem[] {
  if (kind === 'observe') {
    const activeIndex = findMatchingActiveToolIndex(existing, incoming);
    const settled =
      activeIndex < 0
        ? existing
        : existing.map((item, index) =>
            index === activeIndex
              ? { ...item, metadata: { ...(item.metadata ?? {}), streaming: false } }
              : item,
          );
    return sortTimelineItems([
      ...settled,
      { ...incoming, metadata: { ...(incoming.metadata ?? {}), streaming: false } },
    ]);
  }

  const activeIndex = findMatchingActiveToolIndex(existing, incoming);
  if (activeIndex >= 0) {
    const updated = existing.map((item, index) => {
      if (index !== activeIndex) return item;
      return {
        ...item,
        ...incoming,
        // Keep the skeleton identity and start time stable while arguments stream.
        id: item.id,
        eventTimeUs: item.eventTimeUs,
        eventCounter: item.eventCounter,
        timestamp: item.timestamp,
        metadata: { ...(item.metadata ?? {}), ...(incoming.metadata ?? {}), streaming: true },
      };
    });
    return sortTimelineItems(updated);
  }

  return sortTimelineItems([
    ...existing,
    { ...incoming, metadata: { ...(incoming.metadata ?? {}), streaming: true } },
  ]);
}

export function mergeAssistantTextStreamChunk(
  existing: AgentTimelineItem[],
  chunk: AssistantTextStreamChunk,
): AgentTimelineItem[] {
  const activeIndex = findActiveAssistantTextIndex(existing, chunk.messageId);
  const settledIndex =
    activeIndex < 0 && chunk.kind === 'complete'
      ? findLastAssistantTextIndex(existing, chunk.messageId)
      : -1;
  const targetIndex = activeIndex >= 0 ? activeIndex : settledIndex;
  if (targetIndex >= 0) {
    const updated = existing.map((item, index) => {
      if (index !== targetIndex) return item;
      const content =
        chunk.kind === 'delta'
          ? `${item.content ?? ''}${chunk.content}`
          : chunk.content || item.content;
      return {
        ...item,
        eventTimeUs: chunk.eventTimeUs,
        eventCounter: chunk.eventCounter,
        timestamp: Math.floor(chunk.eventTimeUs / 1000),
        content,
        payload: chunk.payload ?? item.payload,
        metadata: { ...(item.metadata ?? {}), streaming: chunk.kind !== 'complete' },
      };
    });
    return sortTimelineItems(updated);
  }

  if (chunk.kind === 'complete' && !chunk.content) return existing;
  return sortTimelineItems([
    ...existing,
    {
      id: `streaming-assistant-${chunk.messageId}`,
      type: 'assistant_message',
      eventTimeUs: chunk.eventTimeUs,
      eventCounter: chunk.eventCounter,
      timestamp: Math.floor(chunk.eventTimeUs / 1000),
      message_id: chunk.messageId,
      role: 'assistant',
      content: chunk.content,
      payload: chunk.payload,
      metadata: { streaming: chunk.kind !== 'complete' },
    },
  ]);
}

/**
 * Apply the authoritative `complete` event to the latest assistant response
 * in the current turn. Completion message IDs are not guaranteed to match
 * preceding text stream IDs, so the user-message boundary is the stable key.
 */
export function mergeAssistantCompletionEvent(
  existing: AgentTimelineItem[],
  chunk: AssistantCompletionChunk,
): AgentTimelineItem[] {
  const targetIndex = findCurrentTurnAssistantIndex(existing);
  if (targetIndex >= 0) {
    const updated = existing.map((item, index) => {
      if (index !== targetIndex) return item;
      return {
        ...item,
        content: chunk.content || item.content,
        payload: chunk.payload ?? item.payload,
        metadata: {
          ...(item.metadata ?? {}),
          ...(chunk.metadata ?? {}),
          streaming: false,
        },
        ...(chunk.artifacts ? { artifacts: chunk.artifacts } : {}),
      };
    });
    return sortTimelineItems(updated);
  }

  const hasMetadata = Boolean(chunk.metadata && Object.keys(chunk.metadata).length > 0);
  if (!chunk.content && !hasMetadata && !chunk.artifacts?.length) return existing;
  return sortTimelineItems([
    ...existing,
    {
      id: `completed-assistant-${chunk.messageId}`,
      type: 'assistant_message',
      eventTimeUs: chunk.eventTimeUs,
      eventCounter: chunk.eventCounter,
      timestamp: Math.floor(chunk.eventTimeUs / 1000),
      message_id: chunk.messageId,
      role: 'assistant',
      content: chunk.content,
      payload: chunk.payload,
      metadata: { ...(chunk.metadata ?? {}), streaming: false },
      ...(chunk.artifacts ? { artifacts: chunk.artifacts } : {}),
    },
  ]);
}

/**
 * Fold a live cost event into the current assistant response. Cost events are
 * response metadata, not standalone narrative rows, and may arrive in either
 * the websocket aggregate shape or the domain event token-map shape.
 */
export function mergeCostUpdateEvent(
  existing: AgentTimelineItem[],
  data: Record<string, unknown>,
): AgentTimelineItem[] {
  const targetIndex = findCurrentTurnAssistantIndex(existing);
  if (targetIndex < 0) return existing;

  const tokens = isRecord(data.tokens) ? data.tokens : null;
  const inputTokens =
    optionalFiniteNumber(data.inputTokens ?? data.input_tokens) ??
    optionalFiniteNumber(tokens?.input) ??
    0;
  const outputTokens =
    optionalFiniteNumber(data.outputTokens ?? data.output_tokens) ??
    optionalFiniteNumber(tokens?.output) ??
    0;
  const totalTokens =
    optionalFiniteNumber(data.cumulativeTokens ?? data.cumulative_tokens) ??
    optionalFiniteNumber(data.totalTokens ?? data.total_tokens) ??
    optionalFiniteNumber(tokens?.total) ??
    inputTokens + outputTokens;
  const costUsd =
    optionalFiniteNumber(data.cumulativeCostUsd ?? data.cumulative_cost_usd) ??
    optionalFiniteNumber(data.costUsd ?? data.cost_usd) ??
    optionalFiniteNumber(data.cost) ??
    0;
  const model = typeof data.model === 'string' ? data.model : '';

  return existing.map((item, index) => {
    if (index !== targetIndex) return item;
    const metadata = isRecord(item.metadata) ? item.metadata : {};
    const rawSummary = isRecord(metadata.executionSummary)
      ? metadata.executionSummary
      : isRecord(metadata.execution_summary)
        ? metadata.execution_summary
        : {};
    const rawTotalTokens = isRecord(rawSummary.totalTokens)
      ? rawSummary.totalTokens
      : isRecord(rawSummary.total_tokens)
        ? rawSummary.total_tokens
        : {};
    return {
      ...item,
      metadata: {
        ...metadata,
        executionSummary: {
          ...rawSummary,
          totalCost: costUsd,
          totalCostFormatted: `$${costUsd.toFixed(6)}`,
          totalTokens: { ...rawTotalTokens, total: totalTokens },
        },
        costTracking: {
          inputTokens,
          outputTokens,
          totalTokens,
          costUsd,
          model,
        },
      },
    };
  });
}

export function assistantExecutionSummary(
  item: AgentTimelineItem,
): AgentExecutionSummary | null {
  const metadata = isRecord(item.metadata) ? item.metadata : null;
  const raw = metadata?.executionSummary ?? metadata?.execution_summary;
  if (!isRecord(raw)) return null;
  const tasks = isRecord(raw.tasks)
    ? {
        total: finiteNumber(raw.tasks.total),
        completed: finiteNumber(raw.tasks.completed),
        remaining: finiteNumber(raw.tasks.remaining),
      }
    : null;
  const tokens = isRecord(raw.totalTokens)
    ? raw.totalTokens
    : isRecord(raw.total_tokens)
      ? raw.total_tokens
      : null;
  const summary = {
    stepCount: recordNumber(raw, 'stepCount', 'step_count'),
    artifactCount: recordNumber(raw, 'artifactCount', 'artifact_count'),
    callCount: recordNumber(raw, 'callCount', 'call_count'),
    totalCost: recordNumber(raw, 'totalCost', 'total_cost'),
    totalCostFormatted:
      recordString(raw, 'totalCostFormatted', 'total_cost_formatted') ?? '$0.000000',
    totalTokens: tokens ? finiteNumber(tokens.total) : 0,
    tasks,
  };
  const visible =
    summary.stepCount > 0 ||
    summary.artifactCount > 0 ||
    summary.callCount > 0 ||
    summary.totalCost > 0 ||
    summary.totalTokens > 0 ||
    Boolean(summary.tasks && summary.tasks.total > 0);
  return visible ? summary : null;
}

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

function findActiveAssistantTextIndex(items: AgentTimelineItem[], messageId: string): number {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (
      item.role === 'assistant' &&
      item.message_id === messageId &&
      item.metadata?.streaming === true
    ) {
      return index;
    }
  }
  return -1;
}

function findLastAssistantTextIndex(items: AgentTimelineItem[], messageId: string): number {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item.role === 'assistant' && item.message_id === messageId) return index;
  }
  return -1;
}

function findCurrentTurnAssistantIndex(items: AgentTimelineItem[]): number {
  let turnStartIndex = -1;
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item.role === 'user' || item.type === 'user_message') {
      turnStartIndex = index;
      break;
    }
  }
  for (let index = items.length - 1; index > turnStartIndex; index -= 1) {
    const item = items[index];
    if (item.role === 'assistant' || item.type === 'assistant_message') return index;
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
  const pendingPairIndexes: number[] = [];
  for (const item of items) {
    if (item.type === 'act') {
      pairs.push({ call: item, result: null });
      pendingPairIndexes.push(pairs.length - 1);
      continue;
    }
    if (item.type === 'observe') {
      const pendingOffset = findMatchingPendingPairOffset(pairs, pendingPairIndexes, item);
      if (pendingOffset >= 0) {
        const pairIndex = pendingPairIndexes[pendingOffset];
        pairs[pairIndex] = { ...pairs[pairIndex], result: item };
        pendingPairIndexes.splice(pendingOffset, 1);
      } else {
        pairs.push({ call: item, result: null });
      }
      continue;
    }
    pairs.push({ call: item, result: null });
  }
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
  if (last.type === 'agent_conversation_finished') return false;
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

function findMatchingActiveToolIndex(
  items: AgentTimelineItem[],
  incoming: AgentTimelineItem,
): number {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const candidate = items[index];
    if (
      candidate.type === 'act' &&
      candidate.metadata?.streaming === true &&
      toolItemsReferToSameCall(candidate, incoming)
    ) {
      return index;
    }
  }
  return -1;
}

function findMatchingPendingPairOffset(
  pairs: ToolCallPair[],
  pendingPairIndexes: number[],
  result: AgentTimelineItem,
): number {
  for (let offset = pendingPairIndexes.length - 1; offset >= 0; offset -= 1) {
    if (toolItemsReferToSameCall(pairs[pendingPairIndexes[offset]].call, result)) return offset;
  }
  return -1;
}

function toolItemsReferToSameCall(
  call: AgentTimelineItem,
  result: AgentTimelineItem,
): boolean {
  const callIdentifiers = toolCallIdentifiers(call);
  const resultIdentifiers = toolCallIdentifiers(result);
  if (callIdentifiers.length > 0 && resultIdentifiers.length > 0) {
    return callIdentifiers.some((identifier) => resultIdentifiers.includes(identifier));
  }
  if (
    call.message_id &&
    result.message_id &&
    call.message_id !== result.message_id
  ) {
    return false;
  }
  return toolCallNamesMatch(call, result);
}

function toolCallIdentifiers(item: AgentTimelineItem): string[] {
  const payload = isRecord(item.payload) ? item.payload : null;
  const identifiers = [
    item.tool_execution_id,
    item.execution_id,
    item.call_id,
    payload?.tool_execution_id,
    payload?.execution_id,
    payload?.call_id,
    payload?.tool_call_id,
  ];
  return identifiers.filter(
    (identifier): identifier is string => typeof identifier === 'string' && identifier.length > 0,
  );
}

function startOfDay(timeMs: number): number {
  const date = new Date(timeMs);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

function nonNegativeInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null;
}

function finiteNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function optionalFiniteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

function recordNumber(
  record: Record<string, unknown>,
  camelKey: string,
  snakeKey: string,
): number {
  return finiteNumber(record[camelKey] ?? record[snakeKey]);
}

function recordString(
  record: Record<string, unknown>,
  camelKey: string,
  snakeKey: string,
): string | null {
  const value = record[camelKey] ?? record[snakeKey];
  return typeof value === 'string' && value ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}
