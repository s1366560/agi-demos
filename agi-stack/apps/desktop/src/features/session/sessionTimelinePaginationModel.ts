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
  // A transient failure says nothing about whether earlier history exists, so
  // the known `hasMore` signal is preserved: clearing it would hide every
  // recovery affordance once the error banner is dismissed.
  return {
    ...current,
    loadingEarlier: false,
    error,
  };
}

export function exhaustEarlierTimelinePage(
  current: ConversationTimelineState,
): ConversationTimelineState {
  // End-of-history is a benign terminal condition, not a failure: surface it
  // neutrally by retiring the load-earlier affordance without raising an
  // error.
  return {
    ...current,
    loadingEarlier: false,
    error: null,
    hasMore: false,
  };
}
