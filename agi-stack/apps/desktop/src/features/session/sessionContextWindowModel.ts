import type { AgentTimelineItem } from '../../types';

export type SessionContextTokenDistribution = {
  system: number;
  user: number;
  assistant: number;
  tool: number;
  summary: number;
  total: number;
};

export type SessionContextCompressionRecord = {
  id: string;
  timestamp: string;
  level: string;
  tokensBefore: number;
  tokensAfter: number;
  tokensSaved: number;
  compressionRatio: number;
  savingsPct: number;
  messagesBefore: number;
  messagesAfter: number;
  durationMs: number;
};

export type SessionContextCompressionHistory = {
  totalCompressions: number;
  totalTokensSaved: number;
  averageCompressionRatio: number;
  averageSavingsPct: number;
  recentRecords: SessionContextCompressionRecord[];
};

export type SessionContextWindowStatus = {
  currentTokens: number;
  tokenBudget: number;
  occupancyPct: number;
  compressionLevel: string;
  tokenDistribution: SessionContextTokenDistribution;
  compressionHistory: SessionContextCompressionHistory;
  fromCache: boolean;
  messagesInSummary: number;
  updatedAtUs: number;
};

export type SessionContextCompressionEvent = {
  id: string;
  eventTimeUs: number;
  wasCompressed: boolean;
  strategy: 'none' | 'truncate' | 'summarize';
  compressionLevel: string;
  originalMessageCount: number;
  finalMessageCount: number;
  estimatedTokens: number;
  tokenBudget: number;
  budgetUtilizationPct: number;
  summarizedMessageCount: number;
  tokensSaved: number;
  compressionRatio: number;
  prunedToolOutputs: number;
  durationMs: number;
};

export type SessionContextWindowModel = {
  current: SessionContextWindowStatus | null;
  compressions: SessionContextCompressionEvent[];
  summary: {
    updates: number;
    compressions: number;
    totalTokensSaved: number;
  };
};

const contextWindowEventTypes = new Set(['context_status', 'context_compressed']);
const compressionStrategies = new Set(['none', 'truncate', 'summarize']);

const emptyDistribution: SessionContextTokenDistribution = {
  system: 0,
  user: 0,
  assistant: 0,
  tool: 0,
  summary: 0,
  total: 0,
};

const emptyHistory: SessionContextCompressionHistory = {
  totalCompressions: 0,
  totalTokensSaved: 0,
  averageCompressionRatio: 0,
  averageSavingsPct: 0,
  recentRecords: [],
};

export function isSessionContextWindowEvent(value: unknown): boolean {
  const root = recordValue(value);
  const type = stringValue(root?.type ?? root?.event_type);
  return Boolean(type && contextWindowEventTypes.has(type));
}

export function buildSessionContextWindow(
  items: readonly AgentTimelineItem[],
): SessionContextWindowModel {
  let current: SessionContextWindowStatus | null = null;
  const compressions: SessionContextCompressionEvent[] = [];
  const seenEventIds = new Set<string>();
  let updates = 0;

  for (const item of [...items].sort(compareTimelineItems)) {
    if (!isSessionContextWindowEvent(item) || seenEventIds.has(item.id)) continue;
    seenEventIds.add(item.id);
    const type = eventType(item);
    if (type === 'context_status') {
      const next = readContextStatus(item, current);
      if (!next) continue;
      current = next;
      updates += 1;
      continue;
    }

    const compression = readCompressionEvent(item);
    if (!compression) continue;
    compressions.push(compression);
    current = applyCompressionEvent(item, compression, current);
    updates += 1;
  }

  const compressedEvents = compressions.filter((event) => event.wasCompressed);
  return {
    current,
    compressions,
    summary: {
      updates,
      compressions: compressedEvents.length,
      totalTokensSaved:
        current?.compressionHistory.totalTokensSaved ??
        compressedEvents.reduce((total, event) => total + event.tokensSaved, 0),
    },
  };
}

function readContextStatus(
  item: AgentTimelineItem,
  previous: SessionContextWindowStatus | null,
): SessionContextWindowStatus | null {
  const currentTokens = fieldNonNegativeNumber(item, 'current_tokens', 'currentTokens');
  const tokenBudget = fieldNonNegativeNumber(item, 'token_budget', 'tokenBudget');
  const occupancyPct = fieldNonNegativeNumber(item, 'occupancy_pct', 'occupancyPct');
  const compressionLevel = fieldString(item, 'compression_level', 'compressionLevel');
  if (
    currentTokens === null ||
    tokenBudget === null ||
    occupancyPct === null ||
    !compressionLevel
  ) {
    return null;
  }

  return {
    currentTokens,
    tokenBudget,
    occupancyPct,
    compressionLevel,
    tokenDistribution:
      readTokenDistribution(fieldValue(item, 'token_distribution', 'tokenDistribution')) ??
      previous?.tokenDistribution ??
      emptyDistribution,
    compressionHistory:
      readCompressionHistory(
        fieldValue(item, 'compression_history_summary', 'compressionHistorySummary'),
      ) ??
      previous?.compressionHistory ??
      emptyHistory,
    fromCache: fieldBoolean(item, 'from_cache', 'fromCache') ?? false,
    messagesInSummary:
      fieldNonNegativeNumber(item, 'messages_in_summary', 'messagesInSummary') ?? 0,
    updatedAtUs: timelineTimeUs(item),
  };
}

function applyCompressionEvent(
  item: AgentTimelineItem,
  event: SessionContextCompressionEvent,
  previous: SessionContextWindowStatus | null,
): SessionContextWindowStatus {
  return {
    currentTokens: event.estimatedTokens,
    tokenBudget: event.tokenBudget,
    occupancyPct: event.budgetUtilizationPct,
    compressionLevel: event.compressionLevel,
    tokenDistribution:
      readTokenDistribution(fieldValue(item, 'token_distribution', 'tokenDistribution')) ??
      previous?.tokenDistribution ??
      emptyDistribution,
    compressionHistory:
      readCompressionHistory(
        fieldValue(item, 'compression_history_summary', 'compressionHistorySummary'),
      ) ??
      previous?.compressionHistory ??
      emptyHistory,
    fromCache: previous?.fromCache ?? false,
    messagesInSummary: previous?.messagesInSummary ?? 0,
    updatedAtUs: event.eventTimeUs,
  };
}

function readCompressionEvent(
  item: AgentTimelineItem,
): SessionContextCompressionEvent | null {
  const wasCompressed = fieldBoolean(item, 'was_compressed', 'wasCompressed');
  const strategy = fieldString(item, 'compression_strategy', 'compressionStrategy');
  const compressionLevel = fieldString(item, 'compression_level', 'compressionLevel');
  const originalMessageCount = fieldNonNegativeNumber(
    item,
    'original_message_count',
    'originalMessageCount',
  );
  const finalMessageCount = fieldNonNegativeNumber(
    item,
    'final_message_count',
    'finalMessageCount',
  );
  const estimatedTokens = fieldNonNegativeNumber(item, 'estimated_tokens', 'estimatedTokens');
  const tokenBudget = fieldNonNegativeNumber(item, 'token_budget', 'tokenBudget');
  const budgetUtilizationPct = fieldNonNegativeNumber(
    item,
    'budget_utilization_pct',
    'budgetUtilizationPct',
  );
  const summarizedMessageCount = fieldNonNegativeNumber(
    item,
    'summarized_message_count',
    'summarizedMessageCount',
  );
  const tokensSaved = fieldNonNegativeNumber(item, 'tokens_saved', 'tokensSaved');
  const compressionRatio = fieldNonNegativeNumber(
    item,
    'compression_ratio',
    'compressionRatio',
  );
  const prunedToolOutputs = fieldNonNegativeNumber(
    item,
    'pruned_tool_outputs',
    'prunedToolOutputs',
  );
  const durationMs = fieldNonNegativeNumber(item, 'duration_ms', 'durationMs');
  if (
    wasCompressed === null ||
    !strategy ||
    !compressionStrategies.has(strategy) ||
    !compressionLevel ||
    originalMessageCount === null ||
    finalMessageCount === null ||
    estimatedTokens === null ||
    tokenBudget === null ||
    budgetUtilizationPct === null ||
    summarizedMessageCount === null ||
    tokensSaved === null ||
    compressionRatio === null ||
    prunedToolOutputs === null ||
    durationMs === null
  ) {
    return null;
  }

  return {
    id: item.id,
    eventTimeUs: timelineTimeUs(item),
    wasCompressed,
    strategy: strategy as SessionContextCompressionEvent['strategy'],
    compressionLevel,
    originalMessageCount,
    finalMessageCount,
    estimatedTokens,
    tokenBudget,
    budgetUtilizationPct,
    summarizedMessageCount,
    tokensSaved,
    compressionRatio,
    prunedToolOutputs,
    durationMs,
  };
}

function readTokenDistribution(value: unknown): SessionContextTokenDistribution | null {
  const source = recordValue(value);
  if (!source || Object.keys(source).length === 0) return null;
  const system = nonNegativeNumberValue(source.system);
  const user = nonNegativeNumberValue(source.user);
  const assistant = nonNegativeNumberValue(source.assistant);
  const tool = nonNegativeNumberValue(source.tool);
  const summary = nonNegativeNumberValue(source.summary);
  if (system === null || user === null || assistant === null || tool === null || summary === null) {
    return null;
  }
  return {
    system,
    user,
    assistant,
    tool,
    summary,
    total: system + user + assistant + tool + summary,
  };
}

function readCompressionHistory(value: unknown): SessionContextCompressionHistory | null {
  const source = recordValue(value);
  const totalCompressions = nonNegativeNumberValue(source?.total_compressions);
  if (!source || totalCompressions === null || totalCompressions === 0) return null;
  const totalTokensSaved = nonNegativeNumberValue(source.total_tokens_saved);
  const averageCompressionRatio = nonNegativeNumberValue(source.average_compression_ratio);
  const averageSavingsPct = nonNegativeNumberValue(source.average_savings_pct);
  if (
    totalTokensSaved === null ||
    averageCompressionRatio === null ||
    averageSavingsPct === null ||
    !Array.isArray(source.recent_records)
  ) {
    return null;
  }
  const recentRecords: SessionContextCompressionRecord[] = [];
  for (const [index, value] of source.recent_records.entries()) {
    const record = readCompressionRecord(value, index);
    if (!record) return null;
    recentRecords.push(record);
  }
  return {
    totalCompressions,
    totalTokensSaved,
    averageCompressionRatio,
    averageSavingsPct,
    recentRecords,
  };
}

function readCompressionRecord(
  value: unknown,
  index: number,
): SessionContextCompressionRecord | null {
  const source = recordValue(value);
  const timestamp = stringValue(source?.timestamp);
  const level = stringValue(source?.level);
  const tokensBefore = nonNegativeNumberValue(source?.tokens_before);
  const tokensAfter = nonNegativeNumberValue(source?.tokens_after);
  const tokensSaved = nonNegativeNumberValue(source?.tokens_saved);
  const compressionRatio = nonNegativeNumberValue(source?.compression_ratio);
  const savingsPct = nonNegativeNumberValue(source?.savings_pct);
  const messagesBefore = nonNegativeNumberValue(source?.messages_before);
  const messagesAfter = nonNegativeNumberValue(source?.messages_after);
  const durationMs = nonNegativeNumberValue(source?.duration_ms);
  if (
    !timestamp ||
    !level ||
    tokensBefore === null ||
    tokensAfter === null ||
    tokensSaved === null ||
    compressionRatio === null ||
    savingsPct === null ||
    messagesBefore === null ||
    messagesAfter === null ||
    durationMs === null
  ) {
    return null;
  }
  return {
    id: `${timestamp}:${index}`,
    timestamp,
    level,
    tokensBefore,
    tokensAfter,
    tokensSaved,
    compressionRatio,
    savingsPct,
    messagesBefore,
    messagesAfter,
    durationMs,
  };
}

function eventType(item: AgentTimelineItem): string {
  return stringValue(item.type) ?? '';
}

function fieldValue(item: AgentTimelineItem, ...keys: string[]): unknown {
  const itemRecord = item as unknown as Record<string, unknown>;
  const payload = recordValue(itemRecord.payload) ?? recordValue(itemRecord.data);
  for (const key of keys) {
    if (payload && key in payload) return payload[key];
    if (key in itemRecord) return itemRecord[key];
  }
  return undefined;
}

function fieldString(item: AgentTimelineItem, ...keys: string[]): string | null {
  return stringValue(fieldValue(item, ...keys));
}

function fieldNonNegativeNumber(item: AgentTimelineItem, ...keys: string[]): number | null {
  return nonNegativeNumberValue(fieldValue(item, ...keys));
}

function fieldBoolean(item: AgentTimelineItem, ...keys: string[]): boolean | null {
  const value = fieldValue(item, ...keys);
  return typeof value === 'boolean' ? value : null;
}

function timelineTimeUs(item: AgentTimelineItem): number {
  const record = item as unknown as Record<string, unknown>;
  return (
    numberValue(record.eventTimeUs ?? record.event_time_us) ??
    (numberValue(item.timestamp) ?? 0) * 1000
  );
}

function compareTimelineItems(left: AgentTimelineItem, right: AgentTimelineItem): number {
  const timeDifference = timelineTimeUs(left) - timelineTimeUs(right);
  if (timeDifference) return timeDifference;
  const leftRecord = left as unknown as Record<string, unknown>;
  const rightRecord = right as unknown as Record<string, unknown>;
  const counterDifference =
    (numberValue(leftRecord.eventCounter ?? leftRecord.event_counter) ?? 0) -
    (numberValue(rightRecord.eventCounter ?? rightRecord.event_counter) ?? 0);
  return counterDifference || left.id.localeCompare(right.id);
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function nonNegativeNumberValue(value: unknown): number | null {
  const number = numberValue(value);
  return number !== null && number >= 0 ? number : null;
}
