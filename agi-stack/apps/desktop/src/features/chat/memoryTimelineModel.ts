import type { AgentTimelineItem } from '../../types';

export type MemoryRecallHit = {
  key: string;
  content: string;
  score: number | null;
  source: string;
  category: string;
  originalIndex: number;
};

export type MemoryRecallPresentation = {
  count: number;
  searchMs: number | null;
  memories: MemoryRecallHit[];
  sources: Array<{ source: string; count: number }>;
};

export type MemoryCapturePresentation = {
  count: number;
  categories: string[];
};

const MEMORY_PIN_STORAGE_PREFIX = 'agistack.desktop.memory-pins.v1';

export function isMemoryTimelineEvent(item: AgentTimelineItem): boolean {
  return item.type === 'memory_recalled' || item.type === 'memory_captured';
}

export function memoryRecallPresentation(
  item: AgentTimelineItem,
): MemoryRecallPresentation | null {
  if (item.type !== 'memory_recalled') return null;
  const rawMemories = eventArray(item, ['memories']);
  const memories = rawMemories.flatMap((value, originalIndex) => {
    if (!isRecord(value)) return [];
    const content = recordString(value, ['content']);
    if (!content) return [];
    const explicitKey = recordString(value, ['id', 'memory_id', 'memoryId']);
    return [
      {
        key: explicitKey || `${item.id}:${String(originalIndex)}`,
        content,
        score: recordNumber(value, ['score', 'similarity_score', 'similarityScore']),
        source: recordString(value, ['source']),
        category: recordString(value, ['category']),
        originalIndex,
      },
    ];
  });
  if (memories.length === 0) return null;

  const explicitCount = eventNumber(item, ['count']);
  const sourceCounts = new Map<string, number>();
  for (const memory of memories) {
    if (!memory.source) continue;
    sourceCounts.set(memory.source, (sourceCounts.get(memory.source) ?? 0) + 1);
  }
  return {
    count: explicitCount !== null && explicitCount > 0 ? explicitCount : memories.length,
    searchMs: eventNumber(item, ['search_ms', 'searchMs']),
    memories,
    sources: [...sourceCounts.entries()]
      .map(([source, count]) => ({ source, count }))
      .sort((left, right) => right.count - left.count || left.source.localeCompare(right.source)),
  };
}

export function memoryCapturePresentation(
  item: AgentTimelineItem,
): MemoryCapturePresentation | null {
  if (item.type !== 'memory_captured') return null;
  const count = eventNumber(item, ['captured_count', 'capturedCount']);
  if (count === null || count <= 0) return null;
  return {
    count,
    categories: eventStringArray(item, ['categories']),
  };
}

export function memoryPinStorageKey(conversationId: string | null): string {
  const scope = conversationId?.trim() ? encodeURIComponent(conversationId.trim()) : 'unscoped';
  return `${MEMORY_PIN_STORAGE_PREFIX}:${scope}`;
}

export function parseMemoryPinState(raw: string | null): Set<string> {
  if (!raw) return new Set();
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(
      parsed.flatMap((value) =>
        typeof value === 'string' && value.trim() ? [value.trim()] : [],
      ),
    );
  } catch {
    return new Set();
  }
}

export function serializeMemoryPinState(pinned: ReadonlySet<string>): string {
  return JSON.stringify([...pinned].sort());
}

function eventRecords(item: AgentTimelineItem): Record<string, unknown>[] {
  const records: Record<string, unknown>[] = [item];
  for (const value of [item.payload, item.data, item.metadata]) {
    if (isRecord(value)) records.push(value);
  }
  return records;
}

function eventArray(item: AgentTimelineItem, keys: readonly string[]): unknown[] {
  for (const record of eventRecords(item)) {
    for (const key of keys) {
      const value = record[key];
      if (Array.isArray(value)) return value;
    }
  }
  return [];
}

function eventNumber(item: AgentTimelineItem, keys: readonly string[]): number | null {
  for (const record of eventRecords(item)) {
    const value = recordNumber(record, keys);
    if (value !== null) return value;
  }
  return null;
}

function eventStringArray(item: AgentTimelineItem, keys: readonly string[]): string[] {
  return eventArray(item, keys).flatMap((value) =>
    typeof value === 'string' && value.trim() ? [value.trim()] : [],
  );
}

function recordString(record: Record<string, unknown>, keys: readonly string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function recordNumber(record: Record<string, unknown>, keys: readonly string[]): number | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
