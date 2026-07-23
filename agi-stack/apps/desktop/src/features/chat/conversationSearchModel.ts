import type { AgentTimelineItem } from '../../types';

export type ConversationSearchMatch = {
  eventId: string;
  eventIndex: number;
  anchorId: string;
};

export type ConversationSearchDirection = 'next' | 'previous';

export function conversationSearchMatches(
  items: readonly AgentTimelineItem[],
  rawQuery: string,
): ConversationSearchMatch[] {
  const query = rawQuery.trim().toLocaleLowerCase();
  if (!query) return [];

  return items.flatMap((item, eventIndex) => {
    const text = conversationSearchText(item).toLocaleLowerCase();
    if (!text.includes(query)) return [];
    return [{ eventId: item.id, eventIndex, anchorId: item.id }];
  });
}

export function moveConversationSearchIndex(
  currentIndex: number,
  matchCount: number,
  direction: ConversationSearchDirection,
): number {
  if (matchCount <= 0) return 0;
  const normalizedIndex =
    Number.isInteger(currentIndex) && currentIndex >= 0
      ? currentIndex % matchCount
      : 0;
  return direction === 'previous'
    ? (normalizedIndex - 1 + matchCount) % matchCount
    : (normalizedIndex + 1) % matchCount;
}

export function resolveConversationSearchIndex(
  matches: readonly ConversationSearchMatch[],
  selectedAnchorId: string | null,
  fallbackIndex: number,
): number {
  if (!matches.length) return 0;
  if (selectedAnchorId) {
    const stableIndex = matches.findIndex((match) => match.anchorId === selectedAnchorId);
    if (stableIndex >= 0) return stableIndex;
  }
  return Math.min(Math.max(Math.trunc(fallbackIndex), 0), matches.length - 1);
}

function conversationSearchText(item: AgentTimelineItem): string {
  if (
    item.type === 'user_message' ||
    item.type === 'assistant_message' ||
    item.type === 'thought'
  ) {
    return item.content ?? '';
  }
  if (item.type === 'act') {
    return [item.toolName ?? '', searchableValue(item.toolInput)].filter(Boolean).join(' ');
  }
  if (item.type === 'observe') {
    return searchableValue(item.toolOutput);
  }
  return '';
}

function searchableValue(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === null || value === undefined) return '';
  try {
    const serialized = JSON.stringify(value);
    return typeof serialized === 'string' ? serialized : '';
  } catch {
    return '';
  }
}
