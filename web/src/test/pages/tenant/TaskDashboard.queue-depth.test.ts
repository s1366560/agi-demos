import { describe, expect, it } from 'vitest';

import { projectQueueDepth } from '@/pages/tenant/taskDashboardQueueDepth';

describe('projectQueueDepth', () => {
  it('uses the newest queue-depth point for the current value and preserves history', () => {
    const projection = projectQueueDepth([
      { timestamp: '09:00', depth: 2 },
      { timestamp: '12:00', depth: 5 },
      { timestamp: '15:00', depth: 3 },
    ]);

    expect(projection.current).toEqual({ timestamp: '15:00', depth: 3 });
    expect(projection.history).toEqual([
      { time: '09:00', count: 2 },
      { time: '12:00', count: 5 },
      { time: '15:00', count: 3 },
    ]);
  });

  it('returns an empty projection when the authority has no points', () => {
    expect(projectQueueDepth([])).toEqual({
      current: null,
      history: [],
    });
  });
});
