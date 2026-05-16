import { describe, it, expect, vi, beforeEach } from 'vitest';

import { useProjectStore } from '@/stores/project';
import { useTenantStore } from '@/stores/tenant';

import { channelService } from '@/services/channelService';

import { PluginHub } from '../../../pages/tenant/PluginHub';
import { render, screen, waitFor, fireEvent } from '../../utils';

vi.mock('@/stores/project');
vi.mock('@/stores/tenant');
vi.mock('@/services/channelService', () => ({
  channelService: {
    listTenantPlugins: vi.fn(),
    listTenantChannelPluginCatalog: vi.fn(),
    getTenantChannelPluginSchema: vi.fn(),
    installTenantPlugin: vi.fn(),
    enableTenantPlugin: vi.fn(),
    disableTenantPlugin: vi.fn(),
    uninstallTenantPlugin: vi.fn(),
    reloadTenantPlugins: vi.fn(),
    listConfigs: vi.fn(),
    createConfig: vi.fn(),
    updateConfig: vi.fn(),
    deleteConfig: vi.fn(),
    testConfig: vi.fn(),
  },
}));

describe('PluginHub', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(useTenantStore).mockImplementation((selector: any) =>
      selector({ currentTenant: { id: 'tenant-1' } })
    );
    vi.mocked(useProjectStore).mockImplementation((selector: any) =>
      selector({
        projects: [{ id: 'project-1', name: 'Project One' }],
        isLoading: false,
        listProjects: vi.fn().mockResolvedValue(undefined),
      })
    );

    vi.mocked(channelService.listTenantPlugins).mockResolvedValue({
      items: [
        {
          name: 'feishu-channel-plugin',
          source: 'local',
          package: 'memstack-plugin-feishu',
          version: '0.1.0',
          enabled: true,
          discovered: true,
          channel_types: ['feishu'],
        },
      ],
      diagnostics: [],
    });
    vi.mocked(channelService.listTenantChannelPluginCatalog).mockResolvedValue({
      items: [
        {
          channel_type: 'feishu',
          plugin_name: 'feishu-channel-plugin',
          source: 'local',
          package: 'memstack-plugin-feishu',
          version: '0.1.0',
          enabled: true,
          discovered: true,
          schema_supported: true,
        },
      ],
    });
    vi.mocked(channelService.listConfigs).mockResolvedValue([
      {
        id: 'cfg-1',
        project_id: 'project-1',
        channel_type: 'feishu',
        name: 'Support Channel',
        enabled: true,
        connection_mode: 'websocket',
        dm_policy: 'open',
        group_policy: 'open',
        rate_limit_per_minute: 60,
        status: 'disconnected',
        created_at: '2026-01-01T00:00:00Z',
      },
    ] as any);
    vi.mocked(channelService.getTenantChannelPluginSchema).mockResolvedValue({
      channel_type: 'feishu',
      plugin_name: 'feishu-channel-plugin',
      source: 'local',
      package: 'memstack-plugin-feishu',
      version: '0.1.0',
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
    vi.mocked(channelService.reloadTenantPlugins).mockResolvedValue({
      success: true,
      message: 'Plugin runtime reloaded',
      details: {
        control_plane_trace: {
          trace_id: 'trace-1',
          action: 'reload',
          timestamp: '2026-04-22T00:00:00Z',
          capability_counts: {
            channel_types: 1,
            tool_factories: 2,
            registered_tool_factories: 3,
            hooks: 4,
            commands: 5,
            services: 6,
            providers: 7,
          },
        },
      },
    });
  });

  it('loads runtime plugins and channel configs', async () => {
    render(<PluginHub />, { route: '/tenant/tenant-1/plugins?projectId=project-1' });

    await waitFor(() => {
      expect(channelService.listTenantPlugins).toHaveBeenCalledWith('tenant-1');
      expect(screen.getByText('feishu-channel-plugin')).toBeInTheDocument();
      expect(screen.getByText('Support Channel')).toBeInTheDocument();
    });
  });

  it('fetches schema when opening add-channel modal', async () => {
    render(<PluginHub />, { route: '/tenant/tenant-1/plugins?projectId=project-1' });

    const addChannelLabel = await screen.findByText('tenant.pluginHub.channelsList.addChannel');
    const addButton = addChannelLabel.closest('button');
    expect(addButton).not.toBeNull();
    await waitFor(() => {
      expect(addButton).not.toBeDisabled();
    });
    fireEvent.click(addButton as HTMLButtonElement);

    await waitFor(() => {
      expect(channelService.getTenantChannelPluginSchema).toHaveBeenCalledWith(
        'tenant-1',
        'feishu'
      );
      expect(screen.getByText('App ID')).toBeInTheDocument();
    });
  });

  it('renders readable control-plane capability labels after reload', async () => {
    render(<PluginHub />, { route: '/tenant/tenant-1/plugins?projectId=project-1' });

    const reloadButton = await screen.findByRole('button', {
      name: 'tenant.pluginHub.pluginsList.reload',
    });
    fireEvent.click(reloadButton);

    await waitFor(() => {
      expect(channelService.reloadTenantPlugins).toHaveBeenCalledWith('tenant-1');
    });

    expect(await screen.findByText('active tools: 2')).toBeInTheDocument();
    expect(screen.getByText('registered tools: 3')).toBeInTheDocument();
    expect(screen.getByText('channels: 1')).toBeInTheDocument();
  });
});
