import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const getStats = vi.fn();

vi.mock('@/services/projectStatsService', () => ({
  projectStatsService: {
    getStats: (...args: unknown[]) => getStats(...args),
  },
}));

import { ProjectContextCard } from '@/components/agent/chat/ProjectContextCard';

describe('ProjectContextCard', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    getStats.mockReset();
  });

  it('renders project stats when available', async () => {
    getStats.mockResolvedValue({
      active_nodes: 2,
      conversation_count: 4,
      member_count: 3,
      memory_count: 5,
      node_count: 6,
      storage_limit: 100,
      storage_used: 12,
    });

    render(<ProjectContextCard projectId="project-1" />);

    await waitFor(() => {
      expect(screen.getByText('Conversations')).toBeInTheDocument();
    });
    expect(getStats).toHaveBeenCalledWith('project-1');
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('6')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('surfaces project stats load failures instead of silently disappearing', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    getStats.mockRejectedValue(new Error('stats unavailable'));

    render(<ProjectContextCard projectId="project-1" />);

    await waitFor(() => {
      expect(screen.getByText('stats unavailable')).toBeInTheDocument();
    });
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      'ProjectContextCard: fetch failed',
      expect.any(Error)
    );
  });
});
