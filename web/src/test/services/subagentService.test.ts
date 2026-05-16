import { beforeEach, describe, expect, it, vi } from 'vitest';

import { httpClient } from '../../services/client/httpClient';
import { subagentAPI } from '../../services/subagentService';

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    delete: vi.fn(),
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

describe('subagentAPI', () => {
  const mockHttpClient = httpClient as unknown as {
    post: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('installs templates through the backend install route', async () => {
    mockHttpClient.post.mockResolvedValue({ id: 'subagent-1' });

    await subagentAPI.createFromTemplate('template-1');

    expect(mockHttpClient.post).toHaveBeenCalledWith('/subagents/templates/template-1/install');
  });
});
