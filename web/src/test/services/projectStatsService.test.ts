import { afterEach, describe, expect, it, vi } from 'vitest';

import { apiFetch } from '@/services/client/urlUtils';
import { clearProjectStatsSummaryCache, projectStatsService } from '@/services/projectStatsService';

vi.mock('@/services/client/urlUtils', () => ({
  apiFetch: {
    get: vi.fn(),
  },
}));

function jsonResponse(data: unknown): Response {
  return {
    json: vi.fn().mockResolvedValue(data),
  } as unknown as Response;
}

const projectStatsPayload = {
  active_nodes: 2,
  conversation_count: 4,
  member_count: 3,
  memory_count: 5,
  node_count: 6,
  storage_limit: 100,
  storage_used: 12,
};

describe('projectStatsService', () => {
  afterEach(() => {
    clearProjectStatsSummaryCache();
    vi.mocked(apiFetch.get).mockReset();
  });

  it('shares concurrent stats requests for the same project', async () => {
    vi.mocked(apiFetch.get).mockResolvedValueOnce(jsonResponse(projectStatsPayload));

    const [first, second] = await Promise.all([
      projectStatsService.getStats('project-1'),
      projectStatsService.getStats('project-1'),
    ]);

    expect(first).toEqual(projectStatsPayload);
    expect(second).toEqual(projectStatsPayload);
    expect(apiFetch.get).toHaveBeenCalledTimes(1);
    expect(apiFetch.get).toHaveBeenCalledWith('/projects/project-1/stats');
  });

  it('keeps a short settled cache for immediate remounts', async () => {
    vi.mocked(apiFetch.get).mockResolvedValueOnce(jsonResponse(projectStatsPayload));

    await projectStatsService.getStats('project-1');
    await projectStatsService.getStats('project-1');

    expect(apiFetch.get).toHaveBeenCalledTimes(1);
  });

  it('keeps project summary keys isolated by project, resource, and limit', async () => {
    vi.mocked(apiFetch.get)
      .mockResolvedValueOnce(jsonResponse({ entities: [{ name: 'A', mention_count: 1 }] }))
      .mockResolvedValueOnce(jsonResponse({ entities: [{ name: 'B', mention_count: 2 }] }))
      .mockResolvedValueOnce(jsonResponse({ skills: [{ name: 'code', last_used: 'now' }] }));

    const [trendingEight, trendingTen, recentSkills] = await Promise.all([
      projectStatsService.getTrending('project-1', 8),
      projectStatsService.getTrending('project-1', 10),
      projectStatsService.getRecentSkills('project-1'),
    ]);

    expect(trendingEight).toEqual([{ name: 'A', mention_count: 1 }]);
    expect(trendingTen).toEqual([{ name: 'B', mention_count: 2 }]);
    expect(recentSkills).toEqual([{ name: 'code', last_used: 'now' }]);
    expect(apiFetch.get).toHaveBeenCalledTimes(3);
    expect(apiFetch.get).toHaveBeenNthCalledWith(1, '/projects/project-1/trending?limit=8');
    expect(apiFetch.get).toHaveBeenNthCalledWith(2, '/projects/project-1/trending?limit=10');
    expect(apiFetch.get).toHaveBeenNthCalledWith(3, '/projects/project-1/recent-skills?limit=5');
  });

  it('does not cache failures so the next request can retry', async () => {
    vi.mocked(apiFetch.get)
      .mockRejectedValueOnce(new Error('temporary stats failure'))
      .mockResolvedValueOnce(jsonResponse(projectStatsPayload));

    await expect(projectStatsService.getStats('project-1')).rejects.toThrow(
      'temporary stats failure'
    );
    await expect(projectStatsService.getStats('project-1')).resolves.toEqual(projectStatsPayload);

    expect(apiFetch.get).toHaveBeenCalledTimes(2);
  });
});
