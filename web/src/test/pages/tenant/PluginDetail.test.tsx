import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Route, Routes } from 'react-router-dom';

import { useTenantStore } from '@/stores/tenant';

import { pluginMarketplaceService } from '@/services/pluginMarketplaceService';

import { PluginDetail } from '../../../pages/tenant/PluginDetail';
import { render, screen, waitFor } from '../../utils';

vi.mock('@/stores/tenant');
vi.mock('@/services/pluginMarketplaceService', () => ({
  pluginMarketplaceService: {
    getPackage: vi.fn(),
    uninstallPackage: vi.fn(),
  },
}));

const marketplacePackage = {
  plugin_id: 'github-plugin',
  version: '2.0.0',
  publisher: 'memstack',
  artifact_digest: 'a'.repeat(64),
  artifact_registry: 'https://registry.memstack.test',
  artifact_repository: 'plugins/github',
  oci_manifest_digest: 'b'.repeat(64),
  install_status: 'approved',
  manifest: {
    schema_version: 2,
    bundle_id: 'github-plugin',
    targets: ['python', 'web'],
  },
  signature: { algorithm: 'Ed25519', signature_sha256: 'c'.repeat(64) },
  provenance: { predicateType: 'https://slsa.dev/provenance/v1' },
  security_scan_status: 'passed',
  revoked: false,
  revocation_reason: null,
};

describe('PluginDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useTenantStore).mockImplementation((selector: any) =>
      selector({ currentTenant: { id: 'tenant-1' } })
    );
    vi.mocked(pluginMarketplaceService.getPackage).mockResolvedValue({
      plugin_id: marketplacePackage.plugin_id,
      versions: [marketplacePackage],
    });
    vi.mocked(pluginMarketplaceService.uninstallPackage).mockResolvedValue({
      plugin_id: marketplacePackage.plugin_id,
      version: marketplacePackage.version,
      status: 'uninstalled',
      desired_removed: true,
      revoked_permissions: 0,
    });
  });

  const renderPluginDetail = (route: string) =>
    render(
      <Routes>
        <Route path="/tenant/:tenantId/plugins/:pluginName" element={<PluginDetail />} />
      </Routes>,
      { route }
    );

  it('renders protocol-v2 marketplace metadata without a V1 runtime record', async () => {
    renderPluginDetail('/tenant/tenant-1/plugins/github-plugin');

    await waitFor(() => {
      expect(pluginMarketplaceService.getPackage).toHaveBeenCalledWith('github-plugin', {
        includeRevoked: true,
      });
    });

    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getAllByText('2.0.0').length).toBeGreaterThan(0);
    expect(screen.getAllByText('memstack').length).toBeGreaterThan(0);
    expect(screen.getAllByText('passed').length).toBeGreaterThan(0);
    expect(screen.getByText(/"schema_version": 2/)).toBeInTheDocument();
    expect(screen.queryByText('Raw Runtime Record')).not.toBeInTheDocument();
  });

  it('shows an empty state when the package is missing', async () => {
    vi.mocked(pluginMarketplaceService.getPackage).mockResolvedValue({
      plugin_id: 'missing-plugin',
      versions: [],
    });

    renderPluginDetail('/tenant/tenant-1/plugins/missing-plugin');

    expect(await screen.findByText('Plugin not found')).toBeInTheDocument();
  });
});
