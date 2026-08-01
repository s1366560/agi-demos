import { beforeEach, describe, expect, it, vi } from 'vitest';

import { httpClient } from '../../services/client/httpClient';
import { poolService } from '../../services/poolService';

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

describe('poolService authority binding', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('binds tenant scope to every admin pool request', async () => {
    vi.mocked(httpClient.get).mockResolvedValue({});
    vi.mocked(httpClient.post).mockResolvedValue({});
    vi.mocked(httpClient.delete).mockResolvedValue({});
    const scope = { scope: 'tenant', tenant_id: 'tenant-1' } as const;

    await poolService.getStatus(scope);
    await poolService.listInstances({ page: 2 }, scope);
    await poolService.pauseInstance('instance-1', scope);
    await poolService.resumeInstance('instance-1', scope);
    await poolService.terminateInstance('instance-1', false, scope);
    await poolService.getMetrics(scope);

    expect(httpClient.get).toHaveBeenNthCalledWith(1, '/admin/pool/status', {
      params: scope,
    });
    expect(httpClient.get).toHaveBeenNthCalledWith(2, '/admin/pool/instances', {
      params: { page: 2, ...scope },
    });
    expect(httpClient.post).toHaveBeenNthCalledWith(
      1,
      '/admin/pool/instances/instance-1/pause',
      undefined,
      { params: scope }
    );
    expect(httpClient.post).toHaveBeenNthCalledWith(
      2,
      '/admin/pool/instances/instance-1/resume',
      undefined,
      { params: scope }
    );
    expect(httpClient.delete).toHaveBeenCalledWith('/admin/pool/instances/instance-1', {
      params: { graceful: false, ...scope },
    });
    expect(httpClient.get).toHaveBeenNthCalledWith(3, '/admin/pool/metrics', {
      params: scope,
    });
  });

  it('uses the exact tenant project and mode compatibility path', async () => {
    vi.mocked(httpClient.get).mockResolvedValue({});
    vi.mocked(httpClient.post).mockResolvedValue({});
    vi.mocked(httpClient.delete).mockResolvedValue({});

    await poolService.getProjectInstance('tenant one', 'project/one', 'chat');
    await poolService.pauseProjectInstance('tenant one', 'project/one', 'chat');
    await poolService.resumeProjectInstance('tenant one', 'project/one', 'chat');
    await poolService.terminateProjectInstance('tenant one', 'project/one', 'chat');

    const path = '/tenants/tenant%20one/projects/project%2Fone/pool/instances/chat';
    expect(httpClient.get).toHaveBeenCalledWith(path);
    expect(httpClient.post).toHaveBeenNthCalledWith(1, `${path}/pause`);
    expect(httpClient.post).toHaveBeenNthCalledWith(2, `${path}/resume`);
    expect(httpClient.delete).toHaveBeenCalledWith(path);
  });
});
