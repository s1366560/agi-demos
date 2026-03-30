import { httpClient } from './client/httpClient';

const BASE_URL = '/instances';

type ChannelType = 'mcp' | 'webhook' | 'websocket' | 'api' | 'slack' | 'discord' | 'email';
type ChannelStatus = 'connected' | 'disconnected' | 'error' | 'pending';

interface ChannelConfig {
  id: string;
  instance_id: string;
  channel_type: ChannelType;
  name: string;
  config: Record<string, unknown>;
  status: ChannelStatus;
  last_connected_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export const instanceChannelService = {
  listChannels: (instanceId: string) =>
    httpClient.get<{ items: ChannelConfig[] }>(`${BASE_URL}/${instanceId}/channels`),

  createChannel: (
    instanceId: string,
    data: { channel_type: string; name: string; config: Record<string, unknown> }
  ) => httpClient.post<ChannelConfig>(`${BASE_URL}/${instanceId}/channels`, data),

  updateChannel: (
    instanceId: string,
    channelId: string,
    data: { name?: string; config?: Record<string, unknown> }
  ) =>
    httpClient.put<ChannelConfig>(
      `${BASE_URL}/${instanceId}/channels/${channelId}`,
      data
    ),

  deleteChannel: (instanceId: string, channelId: string) =>
    httpClient.delete(`${BASE_URL}/${instanceId}/channels/${channelId}`),

  testConnection: (instanceId: string, channelId: string) =>
    httpClient.post<{ status: string; message: string }>(
      `${BASE_URL}/${instanceId}/channels/${channelId}/test`
    ),
};
