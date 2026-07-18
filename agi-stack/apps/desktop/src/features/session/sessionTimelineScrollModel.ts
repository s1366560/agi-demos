export type SessionTimelineWindow = Readonly<{
  conversationId: string;
  firstId: string;
  lastId: string;
  tailRevision: string;
  count: number;
}>;

export type SessionTimelineWindowChange =
  | 'initial'
  | 'replaced'
  | 'prepended'
  | 'appended'
  | 'updated'
  | 'stable';

type SessionTimelineViewport = Readonly<{
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}>;

const DEFAULT_LATEST_TOLERANCE_PX = 72;

export function classifySessionTimelineWindowChange(
  previous: SessionTimelineWindow | null,
  current: SessionTimelineWindow,
): SessionTimelineWindowChange {
  if (!previous) return 'initial';
  if (previous.conversationId !== current.conversationId) return 'replaced';

  const grew = current.count > previous.count;
  const preservedTail = current.lastId === previous.lastId;
  if (grew && preservedTail && current.firstId !== previous.firstId) return 'prepended';
  if (current.lastId !== previous.lastId || (grew && !preservedTail)) return 'appended';
  if (current.tailRevision !== previous.tailRevision) return 'updated';
  return 'stable';
}

export function shouldFollowSessionTimeline(
  change: SessionTimelineWindowChange,
  pinnedToLatest: boolean,
): boolean {
  if (change === 'initial' || change === 'replaced') return true;
  return (change === 'appended' || change === 'updated') && pinnedToLatest;
}

export function isSessionTimelinePinnedToLatest(
  viewport: SessionTimelineViewport,
  tolerancePx = DEFAULT_LATEST_TOLERANCE_PX,
): boolean {
  const remaining = viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop;
  return remaining <= tolerancePx;
}
