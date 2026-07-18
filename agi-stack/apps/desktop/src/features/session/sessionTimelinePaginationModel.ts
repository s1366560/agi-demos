import type { ConversationTimelineState } from '../../types';

export type SessionTimelineCursor = NonNullable<ConversationTimelineState['firstCursor']>;

export type EarlierTimelinePageResolution =
  | Readonly<{
      kind: 'accepted';
      firstCursor: SessionTimelineCursor;
      hasMore: boolean;
    }>
  | Readonly<{
      kind: 'stalled';
      reason: 'no_new_items' | 'cursor_not_earlier';
      hasMore: false;
    }>;

export function compareSessionTimelineCursors(
  left: SessionTimelineCursor,
  right: SessionTimelineCursor,
): number {
  if (left.timeUs !== right.timeUs) return left.timeUs - right.timeUs;
  return left.counter - right.counter;
}

export function resolveEarlierTimelinePage(input: {
  requestedCursor: SessionTimelineCursor;
  previousItemCount: number;
  nextItemCount: number;
  nextFirstCursor: SessionTimelineCursor | null;
  responseHasMore: boolean;
}): EarlierTimelinePageResolution {
  if (input.nextItemCount <= input.previousItemCount) {
    return { kind: 'stalled', reason: 'no_new_items', hasMore: false };
  }
  if (
    !input.nextFirstCursor ||
    compareSessionTimelineCursors(input.nextFirstCursor, input.requestedCursor) >= 0
  ) {
    return { kind: 'stalled', reason: 'cursor_not_earlier', hasMore: false };
  }
  return {
    kind: 'accepted',
    firstCursor: input.nextFirstCursor,
    hasMore: input.responseHasMore,
  };
}

export function failEarlierTimelinePage(
  current: ConversationTimelineState,
  error: string,
): ConversationTimelineState {
  return {
    ...current,
    loadingEarlier: false,
    error,
    hasMore: false,
  };
}
