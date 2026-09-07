import { beforeEach, describe, expect, it, vi } from 'vitest';

import { httpClient } from '../../services/client/httpClient';
import { pluginMarketplaceService } from '../../services/pluginMarketplaceService';

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

describe('pluginMarketplaceService', () => {
  const mockHttpClient = httpClient as unknown as {
    get: ReturnType<typeof vi.fn>;
    post: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('lists protocol-v2 packages without exposing a V1 endpoint', async () => {
    mockHttpClient.get.mockResolvedValue([]);

    await pluginMarketplaceService.listPackages({ includeRevoked: true });

    expect(mockHttpClient.get).toHaveBeenCalledWith('/plugin-marketplace/packages', {
      params: { include_revoked: true },
    });
  });

  it('loads one encoded package detail from the V2 marketplace', async () => {
    mockHttpClient.get.mockResolvedValue({ plugin_id: 'vendor/tool', versions: [] });

    await pluginMarketplaceService.getPackage('vendor/tool');

    expect(mockHttpClient.get).toHaveBeenCalledWith('/plugin-marketplace/packages/vendor%2Ftool', {
      params: { include_revoked: false },
    });
  });

  it('uninstalls by mutating the desired bundle set', async () => {
    mockHttpClient.post.mockResolvedValue({
      plugin_id: 'demo',
      version: '2.0.0',
      status: 'uninstalled',
      desired_removed: true,
      revoked_permissions: 1,
    });

    await pluginMarketplaceService.uninstallPackage('demo', {
      tenant_id: 'tenant-1',
      version: '2.0.0',
    });

    expect(mockHttpClient.post).toHaveBeenCalledWith(
      '/plugin-marketplace/packages/demo/uninstall',
      { tenant_id: 'tenant-1', version: '2.0.0' }
    );
  });
});
