import { beforeEach, describe, expect, it, vi } from 'vitest';

import { httpClient } from '../../services/client/httpClient';
import { projectSandboxService } from '../../services/projectSandboxService';

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    delete: vi.fn(),
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

describe('projectSandboxService', () => {
  const mockHttpClient = httpClient as unknown as {
    get: ReturnType<typeof vi.fn>;
    post: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('lists tenant-scoped project sandboxes', async () => {
    mockHttpClient.get.mockResolvedValue({
      sandboxes: [
        {
          sandbox_id: 'sandbox-1',
          project_id: 'project-1',
          tenant_id: 'tenant-1',
          status: 'running',
          is_healthy: true,
        },
      ],
      total: 1,
    });

    const result = await projectSandboxService.listProjectSandboxes({
      limit: 100,
      status: 'running',
    });

    expect(mockHttpClient.get).toHaveBeenCalledWith('/projects/sandboxes', {
      params: { limit: 100, status: 'running' },
    });
    expect(result.sandboxes).toHaveLength(1);
    expect(result.sandboxes[0].sandbox_id).toBe('sandbox-1');
  });

  it('seeds sandbox proxy auth cookie through an authenticated API request', async () => {
    mockHttpClient.post.mockResolvedValue({ success: true, expires_in_seconds: 3600 });

    await projectSandboxService.ensureProxyAuthCookie('project-1');

    expect(mockHttpClient.post).toHaveBeenCalledWith(
      '/projects/project-1/sandbox/proxy-auth-cookie',
      {}
    );
  });

  it('starts desktop without putting the API token in proxy URLs', async () => {
    mockHttpClient.post
      .mockResolvedValueOnce({
        success: true,
        running: true,
        display: ':1',
        resolution: '1920x1080',
        port: 6080,
      })
      .mockResolvedValueOnce({ success: true, expires_in_seconds: 3600 });

    const result = await projectSandboxService.startDesktop('project-1');

    expect(mockHttpClient.post).toHaveBeenNthCalledWith(
      1,
      '/projects/project-1/sandbox/desktop?resolution=1920x1080',
      undefined,
      { timeout: 30000 }
    );
    expect(mockHttpClient.post).toHaveBeenNthCalledWith(
      2,
      '/projects/project-1/sandbox/proxy-auth-cookie',
      {}
    );
    expect(result.url).toBe('/api/v1/projects/project-1/sandbox/desktop/proxy/');
    expect(result.wsUrl).toBe(
      'ws://localhost:3000/api/v1/projects/project-1/sandbox/desktop/proxy/websockify'
    );
  });
});
