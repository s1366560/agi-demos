import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useProjectStore } from '@/stores/project';
import { useTenantStore } from '@/stores/tenant';

import { channelService } from '@/services/channelService';
import { pluginMarketplaceService } from '@/services/pluginMarketplaceService';

import { PluginHub } from '../../../pages/tenant/PluginHub';
import { fireEvent, render, screen, waitFor } from '../../utils';

const messageMock = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd');
  return {
    ...actual,
    App: {
      ...actual.App,
      useApp: () => ({ message: messageMock }),
    },
  };
});

vi.mock('@/stores/project');
vi.mock('@/stores/tenant');
vi.mock('@/services/pluginMarketplaceService', () => ({
  pluginMarketplaceService: {
    listPackages: vi.fn(),
    uninstallPackage: vi.fn(),
  },
}));
vi.mock('@/services/channelService', () => ({
  channelService: {
    listTenantChannelPluginCatalog: vi.fn(),
    getTenantChannelPluginSchema: vi.fn(),
    listConfigs: vi.fn(),
    createConfig: vi.fn(),
    updateConfig: vi.fn(),
    deleteConfig: vi.fn(),
    testConfig: vi.fn(),
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
  manifest: { schema_version: 2, targets: ['python', 'web'] },
  signature: { algorithm: 'Ed25519' },
  provenance: { predicateType: 'https://slsa.dev/provenance/v1' },
  security_scan_status: 'passed',
  revoked: false,
  revocation_reason: null,
};

const channelConfig = {
  id: 'cfg-1',
  project_id: 'project-1',
  channel_type: 'feishu',
  name: 'Support Channel',
  enabled: true,
  connection_mode: 'websocket' as const,
  dm_policy: 'open' as const,
  group_policy: 'open' as const,
  rate_limit_per_minute: 60,
  status: 'disconnected' as const,
  created_at: '2026-01-01T00:00:00Z',
};

describe('PluginHub', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useTenantStore).mockImplementation((selector: any) =>
      selector({ currentTenant: { id: 'tenant-1' } })
    );
    vi.mocked(useProjectStore).mockImplementation((selector: any) =>
      selector({
        projects: [{ id: 'project-1', name: 'Project One', tenant_id: 'tenant-1' }],
        isLoading: false,
        listProjects: vi.fn().mockResolvedValue(undefined),
      })
    );
    vi.mocked(pluginMarketplaceService.listPackages).mockResolvedValue([marketplacePackage]);
    vi.mocked(pluginMarketplaceService.uninstallPackage).mockResolvedValue({
      plugin_id: marketplacePackage.plugin_id,
      version: marketplacePackage.version,
      status: 'uninstalled',
      desired_removed: true,
      revoked_permissions: 0,
    });
    vi.mocked(channelService.listTenantChannelPluginCatalog).mockResolvedValue({
      items: [
        {
          channel_type: 'feishu',
          plugin_name: 'builtin://memstack/channel/feishu',
          source: 'v2-generation',
          enabled: true,
          discovered: true,
          schema_supported: true,
        },
      ],
    });
    vi.mocked(channelService.listConfigs).mockResolvedValue([channelConfig]);
    vi.mocked(channelService.getTenantChannelPluginSchema).mockResolvedValue({
      channel_type: 'feishu',
      plugin_name: 'builtin://memstack/channel/feishu',
      source: 'v2-generation',
      schema_supported: true,
      config_schema: {
        type: 'object',
        properties: {
          app_id: { type: 'string', title: 'App ID' },
          app_secret: { type: 'string', title: 'App Secret' },
        },
        required: ['app_id', 'app_secret'],
      },
      config_ui_hints: {
        app_id: { label: 'App ID' },
        app_secret: { label: 'App Secret', sensitive: true },
      },
      defaults: {},
      secret_paths: ['app_secret'],
    });
  });

  it('loads V2 marketplace packages and generation-backed channel data', async () => {
    render(<PluginHub />, { route: '/tenant/tenant-1/plugins?projectId=project-1' });

    await waitFor(() => {
      expect(pluginMarketplaceService.listPackages).toHaveBeenCalledWith({
        includeRevoked: true,
      });
      expect(channelService.listTenantChannelPluginCatalog).toHaveBeenCalledWith('tenant-1');
      expect(channelService.listConfigs).toHaveBeenCalledWith('project-1');
    });

    expect(screen.getByText('github-plugin')).toBeInTheDocument();
    expect(screen.getByText('memstack')).toBeInTheDocument();
    expect(screen.getByText('Support Channel')).toBeInTheDocument();
    expect(screen.getByText(/builtin:\/\/memstack\/channel\/feishu/)).toBeInTheDocument();
  });

  it('loads a generation-owned schema when opening the channel form', async () => {
    render(<PluginHub />, { route: '/tenant/tenant-1/plugins?projectId=project-1' });

    const addButton = await screen.findByRole('button', {
      name: 'tenant.pluginHub.channelsList.addChannel',
    });
    fireEvent.click(addButton);

    await waitFor(() => {
      expect(channelService.getTenantChannelPluginSchema).toHaveBeenCalledWith(
        'tenant-1',
        'feishu'
      );
    });
    expect(await screen.findByText('App ID')).toBeInTheDocument();
  });
});
