import type { ExecutionDagEdge, ExecutionDagModel, ExecutionDagNodeLayout } from './types';

export const NODE_WIDTH = 224;
export const NODE_HEIGHT = 116;

const COLUMN_GAP = 56;
const LEVEL_GAP = 118;
const PADDING_X = 36;
const PADDING_Y = 32;

export interface GraphLayout {
  nodes: ExecutionDagNodeLayout[];
  edges: ExecutionDagEdge[];
  width: number;
  height: number;
  byId: Map<string, ExecutionDagNodeLayout>;
}

export interface GraphViewport {
  left: number;
  top: number;
  width: number;
  height: number;
  scale: number;
}

export function edgeKey(edge: ExecutionDagEdge): string {
  return `${edge.kind}:${edge.sourceId}:${edge.targetId}:${edge.label ?? ''}`;
}

export function buildLayout(model: ExecutionDagModel): GraphLayout {
  const nodes = model.nodes;
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = model.edges.filter(
    (edge) => nodeIds.has(edge.sourceId) && nodeIds.has(edge.targetId)
  );
  const incoming = new Map<string, number>();
  const adjacency = new Map<string, string[]>();

  for (const node of nodes) {
    incoming.set(node.id, 0);
    adjacency.set(node.id, []);
  }
  for (const edge of edges) {
    incoming.set(edge.targetId, (incoming.get(edge.targetId) ?? 0) + 1);
    adjacency.get(edge.sourceId)?.push(edge.targetId);
  }

  const nodeOrder = new Map(nodes.map((node, index) => [node.id, index]));
  const levels = new Map<string, number>();
  const queue = nodes
    .filter((node) => (incoming.get(node.id) ?? 0) === 0)
    .sort((left, right) => (nodeOrder.get(left.id) ?? 0) - (nodeOrder.get(right.id) ?? 0));

  if (queue.length === 0 && nodes[0]) {
    queue.push(nodes[0]);
  }

  const mutableIncoming = new Map(incoming);
  while (queue.length > 0) {
    const node = queue.shift();
    if (!node) {
      continue;
    }
    const currentLevel = levels.get(node.id) ?? 0;
    const neighbors = adjacency.get(node.id) ?? [];
    for (const neighborId of neighbors) {
      levels.set(neighborId, Math.max(levels.get(neighborId) ?? 0, currentLevel + 1));
      const remaining = (mutableIncoming.get(neighborId) ?? 0) - 1;
      mutableIncoming.set(neighborId, remaining);
      if (remaining <= 0) {
        const neighbor = nodes.find((item) => item.id === neighborId);
        if (neighbor) {
          queue.push(neighbor);
        }
      }
    }
  }

  let fallbackLevel = Math.max(0, ...Array.from(levels.values()));
  for (const node of nodes) {
    if (!levels.has(node.id)) {
      fallbackLevel += 1;
      levels.set(node.id, fallbackLevel);
    }
  }

  const levelsByNumber = new Map<number, typeof nodes>();
  for (const node of nodes) {
    const level = levels.get(node.id) ?? 0;
    const existing = levelsByNumber.get(level) ?? [];
    existing.push(node);
    levelsByNumber.set(level, existing);
  }

  const maxColumns = Math.max(
    1,
    ...Array.from(levelsByNumber.values()).map((items) => items.length)
  );
  const maxLevel = Math.max(0, ...Array.from(levelsByNumber.keys()));
  const width = PADDING_X * 2 + maxColumns * NODE_WIDTH + (maxColumns - 1) * COLUMN_GAP;
  const height = PADDING_Y * 2 + (maxLevel + 1) * NODE_HEIGHT + maxLevel * LEVEL_GAP;
  const laidOut: ExecutionDagNodeLayout[] = [];

  for (const [level, levelNodes] of levelsByNumber.entries()) {
    const sorted = [...levelNodes].sort(
      (left, right) => (nodeOrder.get(left.id) ?? 0) - (nodeOrder.get(right.id) ?? 0)
    );
    const rowWidth = sorted.length * NODE_WIDTH + (sorted.length - 1) * COLUMN_GAP;
    const startX = (width - rowWidth) / 2;
    sorted.forEach((node, order) => {
      laidOut.push({
        ...node,
        x: startX + order * (NODE_WIDTH + COLUMN_GAP),
        y: PADDING_Y + level * (NODE_HEIGHT + LEVEL_GAP),
        level,
        order,
      });
    });
  }

  const byId = new Map(laidOut.map((node) => [node.id, node]));
  return { nodes: laidOut, edges, width, height, byId };
}

export function edgePath(source: ExecutionDagNodeLayout, target: ExecutionDagNodeLayout): string {
  const startX = source.x + NODE_WIDTH / 2;
  const startY = source.y + NODE_HEIGHT;
  const endX = target.x + NODE_WIDTH / 2;
  const endY = target.y;
  const midY = startY + Math.max(34, (endY - startY) / 2);
  return `M ${startX.toFixed(1)} ${startY.toFixed(1)} C ${startX.toFixed(1)} ${midY.toFixed(
    1
  )}, ${endX.toFixed(1)} ${(midY - 10).toFixed(1)}, ${endX.toFixed(1)} ${endY.toFixed(1)}`;
}

export function centerScrollOffsetScaled(
  graphStart: number,
  graphSize: number,
  viewportSize: number,
  scale: number
): number {
  return Math.max(0, graphStart * scale + (graphSize * scale) / 2 - viewportSize / 2);
}
