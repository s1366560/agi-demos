type WindowItem = Readonly<{ id: string; renderId?: string }>;
type WindowNode = Readonly<{ item: WindowItem }> | Readonly<{ items: readonly WindowItem[] }>;

const WINDOW_THRESHOLD = 150;
const WINDOW_SIZE = 100;

export type TimelineWindowBoundary = Readonly<{ memberId: string; allowance: number }>;

export function timelineWindowMember(node: WindowNode | undefined): string | undefined {
  const item = node && ('item' in node ? node.item : node.items[0]);
  return item?.renderId ?? item?.id;
}

/** Keep the previously mounted prefix available while the reader is detached.
 * Match a member across regrouping and count whole groups when revealing history. */
export function resolveTimelineRenderWindow(
  nodes: readonly WindowNode[],
  itemCount: number,
  allowance: number,
  retained: TimelineWindowBoundary | null,
): { startIndex: number; hiddenCount: number } {
  const budget = WINDOW_SIZE + allowance;
  if (itemCount <= WINDOW_THRESHOLD || budget >= itemCount) return { startIndex: 0, hiddenCount: 0 };
  let startIndex = nodes.length;
  let covered = 0;
  const includePrevious = () => {
    const node = nodes[--startIndex];
    covered += 'items' in node ? node.items.length : 1;
  };
  while (startIndex > 0 && covered < budget) includePrevious();
  if (retained) {
    const boundary = nodes.findIndex(node => 'item' in node
      ? (node.item.renderId ?? node.item.id) === retained.memberId
      : node.items.some(item => (item.renderId ?? item.id) === retained.memberId));
    if (boundary >= 0) {
      let desiredStart = boundary;
      let extra = allowance - retained.allowance;
      while (desiredStart > 0 && extra > 0) {
        const node = nodes[--desiredStart];
        extra -= 'items' in node ? node.items.length : 1;
      }
      while (startIndex > desiredStart) includePrevious();
    }
  }
  return { startIndex, hiddenCount: Math.max(0, itemCount - covered) };
}
