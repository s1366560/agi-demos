import { httpClient } from '@/services/client/httpClient';

import type {
  ChannelConfig,
  CreateChannelConfig,
  UpdateChannelConfig,
  ChannelConfigList,
  ChannelConnectionStatus,
  ChannelObservabilitySummary,
} from '@/types/channel';

const BASE_URL = '/channels';

export const channelService = {
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
  async createConfig(
    projectId: string,
    data: CreateChannelConfig
  ): Promise<ChannelConfig> {
    return httpClient.post<ChannelConfig>(
      `${BASE_URL}/projects/${projectId}/configs`,
      data
    );
  },

  /**
   * Update a channel configuration
   */
  async updateConfig(
    configId: string,
    data: UpdateChannelConfig
  ): Promise<ChannelConfig> {
    return httpClient.put<ChannelConfig>(
      `${BASE_URL}/configs/${configId}`,
      data
    );
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
  async testConfig(
    configId: string
  ): Promise<{ success: boolean; message: string }> {
    return httpClient.post<{ success: boolean; message: string }>(
      `${BASE_URL}/configs/${configId}/test`
    );
  },

  /**
   * Get connection status for a specific channel config
   */
  async getConnectionStatus(configId: string): Promise<ChannelConnectionStatus> {
    return httpClient.get<ChannelConnectionStatus>(
      `${BASE_URL}/configs/${configId}/status`
    );
  },

  /**
   * Get observability summary for a project
   */
  async getObservabilitySummary(
    projectId: string
  ): Promise<ChannelObservabilitySummary> {
    return httpClient.get<ChannelObservabilitySummary>(
      `${BASE_URL}/projects/${projectId}/observability/summary`
    );
  },
};
