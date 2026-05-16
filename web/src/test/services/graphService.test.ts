import { beforeEach, describe, expect, it, vi } from 'vitest';

import { httpClient } from '../../services/client/httpClient';
import { graphService } from '../../services/graphService';

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    delete: vi.fn(),
    get: vi.fn(),
    post: vi.fn(),
  },
}));

describe('graphService', () => {
  const mockHttpClient = httpClient as unknown as {
    delete: ReturnType<typeof vi.fn>;
    get: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('loads episodes through the backend by-name route', async () => {
    mockHttpClient.get.mockResolvedValue({ name: 'Launch Notes' });

    await graphService.getEpisode('Launch Notes');

    expect(mockHttpClient.get).toHaveBeenCalledWith('/episodes/by-name/Launch%20Notes');
  });

  it('deletes episodes through the backend by-name route', async () => {
    mockHttpClient.delete.mockResolvedValue({ deleted: true });

    await graphService.deleteEpisode('Launch Notes');

    expect(mockHttpClient.delete).toHaveBeenCalledWith('/episodes/by-name/Launch%20Notes');
  });
});
