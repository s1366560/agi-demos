import type { VisibleMessageForRetry } from './chatMessageActionModel';

export function pinnedMessagesInTimelineOrder(
  messages: readonly VisibleMessageForRetry[],
  pinnedMessageIds: readonly string[],
): VisibleMessageForRetry[] {
  const pinnedIds = new Set(pinnedMessageIds);
  const seenIds = new Set<string>();
  return messages.filter((message) => {
    if (message.kind !== 'agent' || !pinnedIds.has(message.id) || seenIds.has(message.id)) {
      return false;
    }
    seenIds.add(message.id);
    return true;
  });
}

export function reconcilePinnedMessageIds(
  pinnedMessageIds: readonly string[],
  messages: readonly VisibleMessageForRetry[],
): string[] {
  const visibleAgentIds = new Set(
    messages.filter((message) => message.kind === 'agent').map((message) => message.id),
  );
  const seenIds = new Set<string>();
  return pinnedMessageIds.filter((messageId) => {
    if (!visibleAgentIds.has(messageId) || seenIds.has(messageId)) return false;
    seenIds.add(messageId);
    return true;
  });
}

export function togglePinnedMessageId(
  pinnedMessageIds: readonly string[],
  messageId: string,
): string[] {
  return pinnedMessageIds.includes(messageId)
    ? pinnedMessageIds.filter((candidate) => candidate !== messageId)
    : [...pinnedMessageIds, messageId];
}
