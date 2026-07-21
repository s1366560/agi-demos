import type { ExecutionDagEdge } from './types';

/**
 * Drop duplicate edges (same kind + source + target) and self-loops.
 * Shared by the chat and workspace DAG model builders.
 */
export function uniqueEdges(edges: ExecutionDagEdge[]): ExecutionDagEdge[] {
  const seen = new Set<string>();
  const result: ExecutionDagEdge[] = [];
  for (const edge of edges) {
    const key = `${edge.kind}:${edge.sourceId}:${edge.targetId}`;
    if (seen.has(key) || edge.sourceId === edge.targetId) {
      continue;
    }
    seen.add(key);
    result.push(edge);
  }
  return result;
}
