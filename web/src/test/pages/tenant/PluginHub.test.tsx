import { describe, it, expect, vi, beforeEach } from 'vitest';

import { MemoryRouter } from 'react-router-dom';

import { useProjectStore } from '@/stores/project';
import { useTenantStore } from '@/stores/tenant';

import { channelService } from '@/services/channelService';

import { PluginHub } from '../../../pages/tenant/PluginHub';
import { render, screen, waitFor, fireEvent, act } from '../../utils';

const createDeferred = <T,>() => {
  let resolvePromise: (value: T | PromiseLike<T>) => void = () => {};
  let rejectPromise: (reason?: unknown) => void = () => {};
  const promise = new Promise<T>((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });

  return {
    promise,
    resolve: resolvePromise,
    reject: rejectPromise,
  };
};

const createRuntimePlugin = (name: string) => ({
  name,
  source: 'local',
  package: `memstack-plugin-${name}`,
  version: '0.1.0',
  enabled: true,
  discovered: true,
  channel_types: ['feishu'],
  contracts: {
    tools: ['feishu_send'],
    skills: ['feishu'],
    commands: ['feishu'],
    hooks: ['before_tool_execution', 'after_response'],
  },
  command_aliases: [{ name: 'feishu', kind: 'runtime-slash' }],
  schema_supported: true,
});

const createChannelCatalogItem = (pluginName: string) => ({
  channel_type: 'feishu',
  plugin_name: pluginName,
  source: 'local',
  package: `memstack-plugin-${pluginName}`,
  version: '0.1.0',
  enabled: true,
  discovered: true,
  schema_supported: true,
});

const createChannelConfig = (id: string, projectId: string, name: string) =>
  ({
    id,
    project_id: projectId,
    channel_type: 'feishu',
    name,
    enabled: true,
    connection_mode: 'websocket',
    dm_policy: 'open',
    group_policy: 'open',
    rate_limit_per_minute: 60,
    status: 'disconnected',
    created_at: '2026-01-01T00:00:00Z',
  }) as any;

vi.mock('@/stores/project');
vi.mock('@/stores/tenant');
vi.mock('@/services/channelService', () => ({
  channelService: {
    listTenantPlugins: vi.fn(),
    listTenantChannelPluginCatalog: vi.fn(),
    getTenantChannelPluginSchema: vi.fn(),
    getTenantPluginConfigSchema: vi.fn(),
    getTenantPluginConfig: vi.fn(),
    updateTenantPluginConfig: vi.fn(),
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
  let currentTenantId: string;
  let projectStoreProjects: Array<{ id: string; name: string }>;

  beforeEach(() => {
    vi.clearAllMocks();
    currentTenantId = 'tenant-1';
    projectStoreProjects = [{ id: 'project-1', name: 'Project One' }];

    vi.mocked(useTenantStore).mockImplementation((selector: any) =>
      selector({ currentTenant: { id: currentTenantId } })
    );
    vi.mocked(useProjectStore).mockImplementation((selector: any) =>
      selector({
        projects: projectStoreProjects,
        isLoading: false,
        listProjects: vi.fn().mockResolvedValue(undefined),
      })
    );

    vi.mocked(channelService.listTenantPlugins).mockResolvedValue({
      items: [
        {
          ...createRuntimePlugin('feishu-channel-plugin'),
          package: 'memstack-plugin-feishu',
        },
      ],
      diagnostics: [],
    });
    vi.mocked(channelService.listTenantChannelPluginCatalog).mockResolvedValue({
      items: [
        {
          ...createChannelCatalogItem('feishu-channel-plugin'),
          package: 'memstack-plugin-feishu',
        },
      ],
    });
    vi.mocked(channelService.listConfigs).mockResolvedValue([
      createChannelConfig('cfg-1', 'project-1', 'Support Channel'),
    ]);
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
    vi.mocked(channelService.getTenantPluginConfigSchema).mockResolvedValue({
      plugin_name: 'feishu-channel-plugin',
      source: 'local',
      package: 'memstack-plugin-feishu',
      version: '0.1.0',
      enabled: true,
      discovered: true,
      schema_supported: true,
      providers: [],
      skills: [],
      config_schema: {
        type: 'object',
        properties: {
          api_key: { type: 'string', title: 'API Key' },
          enabled_feature: { type: 'boolean', title: 'Enabled Feature' },
          retries: { type: 'integer', title: 'Retries', minimum: 1, maximum: 5 },
          mode: { type: 'string', title: 'Mode', enum: ['fast', 'safe'] },
        },
        required: ['api_key'],
      },
      config_ui_hints: {
        api_key: { label: 'API Key', sensitive: true },
      },
      defaults: { enabled_feature: true, retries: 2, mode: 'safe' },
      secret_paths: ['api_key'],
    });
    vi.mocked(channelService.getTenantPluginConfig).mockResolvedValue({
      id: 'plugin-config-1',
      tenant_id: 'tenant-1',
      plugin_name: 'feishu-channel-plugin',
      config: { api_key: '__MEMSTACK_SECRET_UNCHANGED__', mode: 'fast' },
      created_at: '2026-01-01T00:00:00Z',
    });
    vi.mocked(channelService.updateTenantPluginConfig).mockResolvedValue({
      id: 'plugin-config-1',
      tenant_id: 'tenant-1',
      plugin_name: 'feishu-channel-plugin',
      config: { api_key: '__MEMSTACK_SECRET_UNCHANGED__', mode: 'safe' },
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
      expect(screen.getByText('Tools: 1')).toBeInTheDocument();
      expect(screen.getByText('Skills: 1')).toBeInTheDocument();
      expect(screen.getByText('Commands: 1')).toBeInTheDocument();
      expect(screen.getByText('Hooks: 2')).toBeInTheDocument();
      expect(screen.getByText('Support Channel')).toBeInTheDocument();
    });
  });

  it('ignores stale tenant plugin runtime responses after tenant changes', async () => {
    const tenantOnePlugins =
      createDeferred<Awaited<ReturnType<typeof channelService.listTenantPlugins>>>();
    const tenantOneCatalog =
      createDeferred<Awaited<ReturnType<typeof channelService.listTenantChannelPluginCatalog>>>();
    const tenantTwoPlugins =
      createDeferred<Awaited<ReturnType<typeof channelService.listTenantPlugins>>>();
    const tenantTwoCatalog =
      createDeferred<Awaited<ReturnType<typeof channelService.listTenantChannelPluginCatalog>>>();

    vi.mocked(channelService.listTenantPlugins).mockImplementation((tenantId: string) =>
      tenantId === 'tenant-1' ? tenantOnePlugins.promise : tenantTwoPlugins.promise
    );
    vi.mocked(channelService.listTenantChannelPluginCatalog).mockImplementation(
      (tenantId: string) =>
        tenantId === 'tenant-1' ? tenantOneCatalog.promise : tenantTwoCatalog.promise
    );

    const { rerender } = render(<PluginHub />, { route: '/tenant/plugins' });

    await waitFor(() => {
      expect(channelService.listTenantPlugins).toHaveBeenCalledWith('tenant-1');
    });

    currentTenantId = 'tenant-2';
    projectStoreProjects = [{ id: 'project-2', name: 'Project Two' }];
    rerender(
      <MemoryRouter initialEntries={['/tenant/plugins']}>
        <PluginHub />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(channelService.listTenantPlugins).toHaveBeenCalledWith('tenant-2');
    });

    await act(async () => {
      tenantTwoPlugins.resolve({
        items: [createRuntimePlugin('current-plugin')],
        diagnostics: [],
      });
      tenantTwoCatalog.resolve({
        items: [createChannelCatalogItem('current-plugin')],
      });
    });

    expect(await screen.findByText('current-plugin')).toBeInTheDocument();

    await act(async () => {
      tenantOnePlugins.resolve({
        items: [createRuntimePlugin('stale-plugin')],
        diagnostics: [],
      });
      tenantOneCatalog.resolve({
        items: [createChannelCatalogItem('stale-plugin')],
      });
    });

    await waitFor(() => {
      expect(screen.getByText('current-plugin')).toBeInTheDocument();
      expect(screen.queryByText('stale-plugin')).not.toBeInTheDocument();
    });
  });

  it('ignores stale project channel config responses after project changes', async () => {
    const projectOneConfigs =
      createDeferred<Awaited<ReturnType<typeof channelService.listConfigs>>>();
    const projectTwoConfigs =
      createDeferred<Awaited<ReturnType<typeof channelService.listConfigs>>>();

    vi.mocked(channelService.listConfigs).mockImplementation((projectId: string) =>
      projectId === 'project-1' ? projectOneConfigs.promise : projectTwoConfigs.promise
    );

    const { rerender } = render(<PluginHub />, { route: '/tenant/plugins' });

    await waitFor(() => {
      expect(channelService.listConfigs).toHaveBeenCalledWith('project-1');
    });

    projectStoreProjects = [{ id: 'project-2', name: 'Project Two' }];
    rerender(
      <MemoryRouter initialEntries={['/tenant/plugins']}>
        <PluginHub />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(channelService.listConfigs).toHaveBeenCalledWith('project-2');
    });

    await act(async () => {
      projectTwoConfigs.resolve([
        createChannelConfig('cfg-current', 'project-2', 'Current Channel'),
      ]);
    });

    expect(await screen.findByText('Current Channel')).toBeInTheDocument();

    await act(async () => {
      projectOneConfigs.resolve([createChannelConfig('cfg-stale', 'project-1', 'Stale Channel')]);
    });

    await waitFor(() => {
      expect(screen.getByText('Current Channel')).toBeInTheDocument();
      expect(screen.queryByText('Stale Channel')).not.toBeInTheDocument();
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

  it('opens generic plugin config modal and saves schema-backed config', async () => {
    render(<PluginHub />, { route: '/tenant/tenant-1/plugins?projectId=project-1' });

    const configureButton = await screen.findByRole('button', {
      name: 'tenant.pluginHub.pluginsList.configurePlugin',
    });
    fireEvent.click(configureButton);

    await waitFor(() => {
      expect(channelService.getTenantPluginConfigSchema).toHaveBeenCalledWith(
        'tenant-1',
        'feishu-channel-plugin'
      );
      expect(screen.getByText('API Key')).toBeInTheDocument();
      expect(screen.getByText('Enabled Feature')).toBeInTheDocument();
      expect(screen.getByText('Retries')).toBeInTheDocument();
      expect(screen.getByText('Mode')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('OK'));

    await waitFor(() => {
      expect(channelService.updateTenantPluginConfig).toHaveBeenCalledWith(
        'tenant-1',
        'feishu-channel-plugin',
        {
          config: expect.objectContaining({
            enabled_feature: true,
            retries: 2,
            mode: 'fast',
          }),
        }
      );
    });
  });
});
