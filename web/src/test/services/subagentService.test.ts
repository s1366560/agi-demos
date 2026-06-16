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
    get: ReturnType<typeof vi.fn>;
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

  it('normalizes legacy skip pagination to backend offset', async () => {
    mockHttpClient.get.mockResolvedValue({ subagents: [], total: 0 });

    await subagentAPI.list({ skip: 20, limit: 10, enabled_only: true, tenant_id: 'tenant-2' });

    expect(mockHttpClient.get).toHaveBeenCalledWith('/subagents/', {
      params: {
        enabled_only: true,
        limit: 10,
        offset: 20,
        tenant_id: 'tenant-2',
      },
    });
  });

  it('prefers explicit offset over legacy skip when both are provided', async () => {
    mockHttpClient.get.mockResolvedValue({ subagents: [], total: 0 });

    await subagentAPI.list({ skip: 20, offset: 40, limit: 10 });

    expect(mockHttpClient.get).toHaveBeenCalledWith('/subagents/', {
      params: {
        limit: 10,
        offset: 40,
      },
    });
  });

  it('passes selected tenant when installing a template', async () => {
    mockHttpClient.post.mockResolvedValue({ id: 'subagent-1' });

    await subagentAPI.createFromTemplate('template-1', { tenant_id: 'tenant-2' });

    expect(mockHttpClient.post).toHaveBeenCalledWith(
      '/subagents/templates/template-1/install',
      undefined,
      {
        params: {
          tenant_id: 'tenant-2',
        },
      }
    );
  });

  it('passes selected tenant and project when importing filesystem agents', async () => {
    mockHttpClient.post.mockResolvedValue({ id: 'subagent-1' });

    await subagentAPI.importFilesystem('test-agent', 'project-1', { tenant_id: 'tenant-2' });

    expect(mockHttpClient.post).toHaveBeenCalledWith(
      '/subagents/filesystem/test-agent/import',
      null,
      {
        params: {
          project_id: 'project-1',
          tenant_id: 'tenant-2',
        },
      }
    );
  });
});
