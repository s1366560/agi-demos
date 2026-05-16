import { beforeEach, describe, expect, it, vi } from 'vitest';

import { httpClient } from '../../services/client/httpClient';
import { clusterService } from '../../services/clusterService';

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    delete: vi.fn(),
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

describe('clusterService', () => {
  const mockHttpClient = httpClient as unknown as {
    get: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches cluster health from the health endpoint', async () => {
    mockHttpClient.get.mockResolvedValue({
      status: 'healthy',
      node_count: 3,
      cpu_usage: 25,
      memory_usage: 50,
      checked_at: null,
    });

    const result = await clusterService.getHealth('cluster-1');

    expect(mockHttpClient.get).toHaveBeenCalledWith('/clusters/cluster-1/health');
    expect(result.status).toBe('healthy');
    expect(result.checked_at).toBeNull();
  });
});
