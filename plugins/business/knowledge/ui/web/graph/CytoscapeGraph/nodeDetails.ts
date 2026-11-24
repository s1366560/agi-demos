import type { NodeData } from './types';

const CONNECTION_COUNT_KEYS = ['connection_count', 'connections', 'degree'] as const;

export function getNodeConnectionCount(node: NodeData): number | null {
  for (const key of CONNECTION_COUNT_KEYS) {
    const rawValue = node[key];
    const value = typeof rawValue === 'number' ? rawValue : Number(rawValue);

    if (Number.isFinite(value) && value >= 0) {
      return Math.round(value);
    }
  }

  return null;
}
