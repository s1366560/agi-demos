/**
 * Pure, deterministic skeleton placeholder geometry.
 *
 * Components stay thin: they map these specs onto <Skeleton> primitives, so
 * the placeholder shapes can be unit-tested without rendering.
 */

export type MessageSkeletonRow = {
  id: string;
  barWidths: string[];
};

/** Bar width patterns for one fake message row (avatar circle + text bars). */
const MESSAGE_ROW_BAR_WIDTHS: readonly (readonly string[])[] = [
  ['72%', '48%'],
  ['58%', '81%', '36%'],
  ['66%', '44%'],
];

export function messageSkeletonRows(count = 3): MessageSkeletonRow[] {
  return Array.from({ length: Math.max(0, count) }, (_, index) => ({
    id: `skeleton-message-${index}`,
    barWidths: [...MESSAGE_ROW_BAR_WIDTHS[index % MESSAGE_ROW_BAR_WIDTHS.length]],
  }));
}

export type TreeSkeletonRow = {
  id: string;
  depth: number;
  width: string;
};

/** Width/indent pattern matching workspace/conversation tree rows. */
const TREE_ROW_WIDTHS: readonly string[] = ['84%', '68%', '76%', '60%'];

export function treeSkeletonRows(count = 4): TreeSkeletonRow[] {
  return Array.from({ length: Math.max(0, count) }, (_, index) => ({
    id: `skeleton-tree-${index}`,
    depth: index === 0 ? 0 : 1,
    width: TREE_ROW_WIDTHS[index % TREE_ROW_WIDTHS.length],
  }));
}
