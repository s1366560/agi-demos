import { httpClient } from '@/services/client/httpClient';

import type {
  ChannelConfig,
  CreateChannelConfig,
  UpdateChannelConfig,
  ChannelConfigList,
  ChannelConnectionStatus,
  ChannelObservabilitySummary,
  RuntimePluginList,
  PluginActionResponse,
  ChannelPluginCatalog,
  ChannelPluginConfigSchema,
} from '@/types/channel';

const BASE_URL = '/channels';

export const channelService = {
  async listTenantPlugins(tenantId: string): Promise<RuntimePluginList> {
    return httpClient.get<RuntimePluginList>(`${BASE_URL}/tenants/${tenantId}/plugins`);
  },

  async listTenantChannelPluginCatalog(tenantId: string): Promise<ChannelPluginCatalog> {
    return httpClient.get<ChannelPluginCatalog>(
      `${BASE_URL}/tenants/${tenantId}/plugins/channel-catalog`
    );
  },

  async getTenantChannelPluginSchema(
    tenantId: string,
    channelType: string
  ): Promise<ChannelPluginConfigSchema> {
    return httpClient.get<ChannelPluginConfigSchema>(
      `${BASE_URL}/tenants/${tenantId}/plugins/channel-catalog/${channelType}/schema`
    );
  },

  async installTenantPlugin(tenantId: string, requirement: string): Promise<PluginActionResponse> {
    return httpClient.post<PluginActionResponse>(
      `${BASE_URL}/tenants/${tenantId}/plugins/install`,
      { requirement }
    );
  },

  async enableTenantPlugin(tenantId: string, pluginName: string): Promise<PluginActionResponse> {
    return httpClient.post<PluginActionResponse>(
      `${BASE_URL}/tenants/${tenantId}/plugins/${pluginName}/enable`
    );
  },

  async disableTenantPlugin(tenantId: string, pluginName: string): Promise<PluginActionResponse> {
    return httpClient.post<PluginActionResponse>(
      `${BASE_URL}/tenants/${tenantId}/plugins/${pluginName}/disable`
    );
  },

  async uninstallTenantPlugin(tenantId: string, pluginName: string): Promise<PluginActionResponse> {
    return httpClient.post<PluginActionResponse>(
      `${BASE_URL}/tenants/${tenantId}/plugins/${pluginName}/uninstall`
    );
  },

  async reloadTenantPlugins(tenantId: string): Promise<PluginActionResponse> {
    return httpClient.post<PluginActionResponse>(`${BASE_URL}/tenants/${tenantId}/plugins/reload`);
  },

  async listPlugins(projectId: string): Promise<RuntimePluginList> {
    return httpClient.get<RuntimePluginList>(`${BASE_URL}/projects/${projectId}/plugins`);
  },

  async listChannelPluginCatalog(projectId: string): Promise<ChannelPluginCatalog> {
    return httpClient.get<ChannelPluginCatalog>(
      `${BASE_URL}/projects/${projectId}/plugins/channel-catalog`
    );
  },

  async getChannelPluginSchema(
    projectId: string,
    channelType: string
  ): Promise<ChannelPluginConfigSchema> {
    return httpClient.get<ChannelPluginConfigSchema>(
      `${BASE_URL}/projects/${projectId}/plugins/channel-catalog/${channelType}/schema`
    );
  },

  async installPlugin(projectId: string, requirement: string): Promise<PluginActionResponse> {
    return httpClient.post<PluginActionResponse>(
      `${BASE_URL}/projects/${projectId}/plugins/install`,
      { requirement }
    );
  },

  async enablePlugin(projectId: string, pluginName: string): Promise<PluginActionResponse> {
    return httpClient.post<PluginActionResponse>(
      `${BASE_URL}/projects/${projectId}/plugins/${pluginName}/enable`
    );
  },

  async disablePlugin(projectId: string, pluginName: string): Promise<PluginActionResponse> {
    return httpClient.post<PluginActionResponse>(
      `${BASE_URL}/projects/${projectId}/plugins/${pluginName}/disable`
    );
  },

  async uninstallPlugin(projectId: string, pluginName: string): Promise<PluginActionResponse> {
    return httpClient.post<PluginActionResponse>(
      `${BASE_URL}/projects/${projectId}/plugins/${pluginName}/uninstall`
    );
  },

  async reloadPlugins(projectId: string): Promise<PluginActionResponse> {
    return httpClient.post<PluginActionResponse>(
      `${BASE_URL}/projects/${projectId}/plugins/reload`
    );
  },

  /**
   * List channel configurations for a project
   */
  async listConfigs(
    projectId: string,
    params?: { channel_type?: string; enabled_only?: boolean }
  ): Promise<ChannelConfig[]> {
    const response = await httpClient.get<ChannelConfigList>(
      `${BASE_URL}/projects/${projectId}/configs`,
      { params }
    );
    return response.items;
  },

  /**
   * Get a channel configuration by ID
   */
  async getConfig(configId: string): Promise<ChannelConfig> {
    return httpClient.get<ChannelConfig>(`${BASE_URL}/configs/${configId}`);
  },

  /**
   * Create a new channel configuration
   */
  async createConfig(projectId: string, data: CreateChannelConfig): Promise<ChannelConfig> {
    return httpClient.post<ChannelConfig>(`${BASE_URL}/projects/${projectId}/configs`, data);
  },

  /**
   * Update a channel configuration
   */
  async updateConfig(configId: string, data: UpdateChannelConfig): Promise<ChannelConfig> {
    return httpClient.put<ChannelConfig>(`${BASE_URL}/configs/${configId}`, data);
  },

  /**
   * Delete a channel configuration
   */
  async deleteConfig(configId: string): Promise<void> {
    return httpClient.delete(`${BASE_URL}/configs/${configId}`);
  },

  /**
   * Test a channel configuration
   */
  async testConfig(configId: string): Promise<{ success: boolean; message: string }> {
    return httpClient.post<{ success: boolean; message: string }>(
      `${BASE_URL}/configs/${configId}/test`
    );
  },

  /**
   * Get connection status for a specific channel config
   */
  async getConnectionStatus(configId: string): Promise<ChannelConnectionStatus> {
    return httpClient.get<ChannelConnectionStatus>(`${BASE_URL}/configs/${configId}/status`);
  },

  /**
   * Get observability summary for a project
   */
  async getObservabilitySummary(projectId: string): Promise<ChannelObservabilitySummary> {
    return httpClient.get<ChannelObservabilitySummary>(
      `${BASE_URL}/projects/${projectId}/observability/summary`
    );
  },
};
