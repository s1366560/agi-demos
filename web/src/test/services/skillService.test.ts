import { beforeEach, describe, expect, it, vi } from 'vitest';

import { httpClient } from '../../services/client/httpClient';
import { skillAPI, tenantSkillConfigAPI } from '../../services/skillService';

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
    upload: ReturnType<typeof vi.fn>;
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
    expect(mockHttpClient.get).toHaveBeenNthCalledWith(
      1,
      `/tenant/skills/config/${encodedName}`,
      undefined
    );
    expect(mockHttpClient.get).toHaveBeenNthCalledWith(
      2,
      `/tenant/skills/config/status/${encodedName}`,
      undefined
    );
    expect(mockHttpClient.delete).toHaveBeenCalledWith(
      `/tenant/skills/config/${encodedName}`,
      undefined
    );
  });

  it('passes explicit tenant scope as query params', async () => {
    mockHttpClient.get.mockResolvedValueOnce({ id: 'skill-1' });
    mockHttpClient.get.mockResolvedValueOnce({ id: 'config-1' });

    await skillAPI.get('skill-1', { tenant_id: 'tenant-2' });
    await tenantSkillConfigAPI.get('system-skill', { tenant_id: 'tenant-2' });

    expect(mockHttpClient.get).toHaveBeenNthCalledWith(1, '/skills/skill-1', {
      params: { tenant_id: 'tenant-2' },
    });
    expect(mockHttpClient.get).toHaveBeenNthCalledWith(2, '/tenant/skills/config/system-skill', {
      params: { tenant_id: 'tenant-2' },
    });
  });

  it('adds tenant scope to zip import upload URLs', async () => {
    mockHttpClient.upload.mockResolvedValueOnce({ action: 'created' });

    await skillAPI.importZip(new File(['zip'], 'skill.zip'), {}, { tenant_id: 'tenant-2' });

    expect(mockHttpClient.upload).toHaveBeenCalledWith(
      '/skills/import/zip?tenant_id=tenant-2',
      expect.any(FormData)
    );
  });
});
