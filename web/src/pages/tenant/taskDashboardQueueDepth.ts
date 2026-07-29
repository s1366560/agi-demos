import type { QueueDepth } from '@/types/memory';

export interface QueueDepthProjection {
  current: QueueDepth | null;
  history: { time: string; count: number }[];
}

export function projectQueueDepth(points: readonly QueueDepth[]): QueueDepthProjection {
  return {
    current: points.length > 0 ? (points[points.length - 1] ?? null) : null,
    history: points.map((point) => ({
      time: point.timestamp,
      count: point.depth,
    })),
  };
}
