/**
 * Channel configuration types
 */

export interface ChannelConfig {
  id: string;
  project_id: string;
  channel_type: 'feishu' | 'dingtalk' | 'wecom' | 'slack';
  name: string;
  enabled: boolean;
  connection_mode: 'websocket' | 'webhook';
  app_id?: string;
  webhook_url?: string;
  webhook_port?: number;
  webhook_path?: string;
  domain?: string;
  extra_settings?: Record<string, any>;
  status: 'connected' | 'disconnected' | 'error';
  last_error?: string;
  description?: string;
  created_at: string;
  updated_at?: string;
}

export interface CreateChannelConfig {
  channel_type: 'feishu' | 'dingtalk' | 'wecom' | 'slack';
  name: string;
  enabled?: boolean;
  connection_mode?: 'websocket' | 'webhook';
  app_id?: string;
  app_secret?: string;
  encrypt_key?: string;
  verification_token?: string;
  webhook_url?: string;
  webhook_port?: number;
  webhook_path?: string;
  domain?: string;
  extra_settings?: Record<string, any>;
  description?: string;
}

export interface UpdateChannelConfig {
  name?: string;
  enabled?: boolean;
  connection_mode?: 'websocket' | 'webhook';
  app_id?: string;
  app_secret?: string;
  encrypt_key?: string;
  verification_token?: string;
  webhook_url?: string;
  webhook_port?: number;
  webhook_path?: string;
  domain?: string;
  extra_settings?: Record<string, any>;
  description?: string;
}

export interface ChannelConfigList {
  items: ChannelConfig[];
  total: number;
}

export interface ChannelMessage {
  id: string;
  channel_config_id: string;
  project_id: string;
  channel_message_id: string;
  chat_id: string;
  chat_type: 'p2p' | 'group';
  sender_id: string;
  sender_name?: string;
  message_type: string;
  content_text?: string;
  content_data?: Record<string, any>;
  reply_to?: string;
  mentions?: string[];
  direction: 'inbound' | 'outbound';
  created_at: string;
}
