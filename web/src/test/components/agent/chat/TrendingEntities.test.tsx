import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const getTrending = vi.fn();

vi.mock('@/services/projectStatsService', () => ({
  projectStatsService: {
    getTrending: (...args: unknown[]) => getTrending(...args),
  },
}));

import { TrendingEntities } from '@/components/agent/chat/TrendingEntities';

describe('TrendingEntities', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    getTrending.mockReset();
  });

  it('renders duplicate entity names without duplicate React keys', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    getTrending.mockResolvedValue([
      {
        name: 'Project Aurora',
        mention_count: 106,
        summary: 'First entity record',
      },
      {
        name: 'Project Aurora',
        mention_count: 51,
        summary: 'Second entity record',
      },
    ]);

    render(<TrendingEntities projectId="project-1" />);

    await waitFor(() => {
      expect(screen.getAllByText('Project Aurora')).toHaveLength(2);
    });
    expect(
      consoleErrorSpy.mock.calls.some((args) =>
        String(args[0]).includes('Encountered two children with the same key')
      )
    ).toBe(false);
  });
});
