import { describe, it, expect, vi, beforeEach } from 'vitest';

import { Route, Routes } from 'react-router-dom';

import { useTenantStore } from '@/stores/tenant';

import { channelService } from '@/services/channelService';

import { PluginDetail } from '../../../pages/tenant/PluginDetail';
import { render, screen, waitFor } from '../../utils';

vi.mock('@/stores/tenant');
vi.mock('@/services/channelService', () => ({
  channelService: {
    listTenantPlugins: vi.fn(),
    getTenantPluginConfigSchema: vi.fn(),
  },
}));

describe('PluginDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(useTenantStore).mockImplementation((selector: any) =>
      selector({ currentTenant: { id: 'tenant-1' } })
    );

    vi.mocked(channelService.listTenantPlugins).mockResolvedValue({
      items: [
        {
          name: 'github-plugin',
          source: 'local',
          package: 'memstack-plugin-github',
          version: '0.2.0',
          kind: 'tool',
          manifest_id: 'github',
          manifest_path: '.memstack/plugins/github/memstack.plugin.json',
          enabled: true,
          discovered: true,
          channel_types: [],
          providers: ['github'],
          skills: ['github'],
          channels: ['github'],
          contracts: {
            tools: ['github_request'],
            commands: ['github'],
            hooks: ['before_tool_execution'],
          },
          activation: { triggers: ['github'] },
          command_aliases: [{ name: 'github', kind: 'runtime-slash' }],
          skill_definitions: [
            {
              name: 'github',
              path: '.memstack/plugins/github/github/SKILL.md',
              content: '# GitHub Plugin\n\nUse GitHub REST operations from MemStack.',
            },
          ],
          tool_definitions: [
            {
              name: 'github_request',
              description: 'Call selected GitHub REST API operations.',
              parameters: {
                type: 'object',
                properties: {
                  operation: { type: 'string' },
                },
              },
            },
          ],
          tool_metadata: {
            github_request: { side_effects: ['network'] },
          },
          hook_metadata: {
            before_tool_execution: { priority: 10 },
          },
          config_schema: {
            type: 'object',
            properties: {
              github_token: { type: 'string', title: 'GitHub Token' },
            },
          },
          config_ui_hints: {
            github_token: { label: 'GitHub Token', sensitive: true },
          },
          env_vars: {
            required: ['GITHUB_TOKEN'],
          },
          schema_supported: true,
        },
      ],
      diagnostics: [
        {
          plugin_name: 'github-plugin',
          code: 'config_missing',
          message: 'Token is not configured',
          level: 'warning',
        },
      ],
    });

    vi.mocked(channelService.getTenantPluginConfigSchema).mockResolvedValue({
      plugin_name: 'github-plugin',
      source: 'local',
      package: 'memstack-plugin-github',
      version: '0.2.0',
      kind: 'tool',
      manifest_id: 'github',
      providers: ['github'],
      skills: ['github'],
      enabled: true,
      discovered: true,
      schema_supported: true,
      config_schema: {
        type: 'object',
        properties: {
          github_token: { type: 'string', title: 'GitHub Token' },
          confirm_write: { type: 'boolean', title: 'Confirm Write' },
        },
        required: ['github_token'],
      },
      config_ui_hints: {
        github_token: { label: 'GitHub Token', sensitive: true },
      },
      defaults: { confirm_write: false },
      secret_paths: ['github_token'],
    });
  });

  const renderPluginDetail = (route: string) =>
    render(
      <Routes>
        <Route path="/tenant/:tenantId/plugins/:pluginName" element={<PluginDetail />} />
      </Routes>,
      { route }
    );

  it('renders full runtime and schema details for a plugin', async () => {
    renderPluginDetail('/tenant/tenant-1/plugins/github-plugin?projectId=project-1');

    await waitFor(() => {
      expect(channelService.listTenantPlugins).toHaveBeenCalledWith('tenant-1');
      expect(channelService.getTenantPluginConfigSchema).toHaveBeenCalledWith(
        'tenant-1',
        'github-plugin'
      );
    });

    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getByText('Declared Capabilities')).toBeInTheDocument();
    expect(screen.getByText('Contracts')).toBeInTheDocument();
    expect(screen.getByText('Built-in Skills')).toBeInTheDocument();
    expect(screen.getByText('Tool Definitions')).toBeInTheDocument();
    expect(screen.getByText('Configuration')).toBeInTheDocument();
    expect(screen.getByText('Metadata')).toBeInTheDocument();
    expect(screen.getByText('Raw Runtime Record')).toBeInTheDocument();
    expect(screen.getAllByText('github-plugin').length).toBeGreaterThan(0);
    expect(screen.getByText('memstack-plugin-github')).toBeInTheDocument();
    expect(screen.getAllByText(/Use GitHub REST operations/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Call selected GitHub REST API operations/).length).toBeGreaterThan(
      0
    );
    expect(screen.getAllByText('github_request').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/github_token/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/GITHUB_TOKEN/).length).toBeGreaterThan(0);
    expect(screen.getByText(/config_missing/)).toBeInTheDocument();
  });

  it('shows an empty state when the plugin is missing', async () => {
    vi.mocked(channelService.listTenantPlugins).mockResolvedValue({
      items: [],
      diagnostics: [],
    });

    renderPluginDetail('/tenant/tenant-1/plugins/missing-plugin');

    expect(await screen.findByText('Plugin not found')).toBeInTheDocument();
    expect(channelService.getTenantPluginConfigSchema).not.toHaveBeenCalled();
  });
});
