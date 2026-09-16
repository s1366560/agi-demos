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

  it('installs with the exact signed protocol-v2 request contract', async () => {
    mockHttpClient.post.mockResolvedValue({
      plugin_id: 'demo',
      version: '2.0.0',
      status: 'approved',
      reason: 'protocol v2 Bundle verified and desired',
    });
    const request = {
      plugin_id: 'demo',
      version: '2.0.0',
      publisher: 'memstack',
      tenant_id: 'tenant-1',
      artifact: {
        registry: 'https://registry.memstack.test',
        repository: 'plugins/demo',
        manifest_sha256: 'b'.repeat(64),
      },
      artifact_sha256: 'a'.repeat(64),
      manifest: { schema_version: 2 },
      signature: { algorithm: 'Ed25519', public_key_pem: 'pem', signature_base64: 'c2ln' },
      provenance: {
        predicate_type: 'https://slsa.dev/provenance/v1',
        builder_id: 'builder',
        subject_name: 'demo',
      },
      approved_permissions: ['tools.execute'],
      tenant_admin_approved: true,
      security_scan_passed: true,
    };

    const outcome = await pluginMarketplaceService.installPackage('demo', request);

    expect(mockHttpClient.post).toHaveBeenCalledWith(
      '/plugin-marketplace/packages/demo/install',
      request
    );
    expect(outcome.status).toBe('approved');
  });

  it('approves scoped permission subsets for a tenant', async () => {
    mockHttpClient.post.mockResolvedValue({
      plugin_id: 'demo',
      version: '2.0.0',
      status: 'approved',
      granted_permissions: ['tools.execute'],
    });

    await pluginMarketplaceService.approvePackage('demo', {
      version: '2.0.0',
      tenant_id: 'tenant-1',
      approved_permissions: ['tools.execute'],
    });

    expect(mockHttpClient.post).toHaveBeenCalledWith(
      '/plugin-marketplace/packages/demo/approve',
      { version: '2.0.0', tenant_id: 'tenant-1', approved_permissions: ['tools.execute'] }
    );
  });

  it('revokes package versions with a required reason', async () => {
    mockHttpClient.post.mockResolvedValue({
      plugin_id: 'demo',
      revoked_versions: ['2.0.0'],
      revoked_permissions: 1,
    });

    await pluginMarketplaceService.revokePackage('demo', { reason: 'publisher compromised' });

    expect(mockHttpClient.post).toHaveBeenCalledWith(
      '/plugin-marketplace/packages/demo/revoke',
      { reason: 'publisher compromised' }
    );
  });
});
