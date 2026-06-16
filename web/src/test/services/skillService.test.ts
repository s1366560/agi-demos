import { beforeEach, describe, expect, it, vi } from 'vitest';

import { httpClient } from '../../services/client/httpClient';
import { tenantSkillConfigAPI } from '../../services/skillService';

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    delete: vi.fn(),
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    upload: vi.fn(),
  },
}));

describe('tenantSkillConfigAPI', () => {
  const mockHttpClient = httpClient as unknown as {
    delete: ReturnType<typeof vi.fn>;
    get: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('encodes system skill names used as path parameters', async () => {
    const skillName = 'research/plan skill';
    mockHttpClient.get.mockResolvedValueOnce({ id: 'config-1' });
    mockHttpClient.get.mockResolvedValueOnce({ enabled: true });
    mockHttpClient.delete.mockResolvedValueOnce(undefined);

    await tenantSkillConfigAPI.get(skillName);
    await tenantSkillConfigAPI.getStatus(skillName);
    await tenantSkillConfigAPI.delete(skillName);

    const encodedName = 'research%2Fplan%20skill';
    expect(mockHttpClient.get).toHaveBeenNthCalledWith(1, `/tenant/skills/config/${encodedName}`);
    expect(mockHttpClient.get).toHaveBeenNthCalledWith(
      2,
      `/tenant/skills/config/status/${encodedName}`
    );
    expect(mockHttpClient.delete).toHaveBeenCalledWith(`/tenant/skills/config/${encodedName}`);
  });
});
