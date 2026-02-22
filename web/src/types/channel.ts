/**
 * Channel configuration types
 */

export type DmPolicy = 'open' | 'allowlist' | 'disabled';
export type GroupPolicy = 'open' | 'allowlist' | 'disabled';

export interface ChannelConfig {
  id: string;
  project_id: string;
  channel_type: string;
  name: string;
  enabled: boolean;
  connection_mode: 'websocket' | 'webhook';
  app_id?: string;
  webhook_url?: string;
  webhook_port?: number;
  webhook_path?: string;
  domain?: string;
  extra_settings?: Record<string, any>;
  dm_policy: DmPolicy;
  group_policy: GroupPolicy;
  allow_from?: string[];
  group_allow_from?: string[];
  rate_limit_per_minute: number;
  status: 'connected' | 'disconnected' | 'error' | 'circuit_open';
  last_error?: string;
  description?: string;
  created_at: string;
  updated_at?: string;
}

export interface CreateChannelConfig {
  channel_type: string;
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
  dm_policy?: DmPolicy;
  group_policy?: GroupPolicy;
  allow_from?: string[];
  group_allow_from?: string[];
  rate_limit_per_minute?: number;
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
  dm_policy?: DmPolicy;
  group_policy?: GroupPolicy;
  allow_from?: string[];
  group_allow_from?: string[];
  rate_limit_per_minute?: number;
}

export interface PluginDiagnostic {
  plugin_name: string;
  code: string;
  message: string;
  level: string;
}

export interface RuntimePlugin {
  name: string;
  source: string;
  package?: string;
  version?: string;
  enabled: boolean;
  discovered: boolean;
  channel_types: string[];
}

export interface RuntimePluginList {
  items: RuntimePlugin[];
  diagnostics: PluginDiagnostic[];
}

export interface PluginActionResponse {
  success: boolean;
  message: string;
  details?: Record<string, unknown>;
}

export interface ChannelPluginCatalogItem {
  channel_type: string;
  plugin_name: string;
  source: string;
  package?: string;
  version?: string;
  enabled: boolean;
  discovered: boolean;
  schema_supported: boolean;
}

export interface ChannelPluginCatalog {
  items: ChannelPluginCatalogItem[];
}

export interface ChannelPluginSchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  enum?: Array<string | number | boolean>;
  minimum?: number;
  maximum?: number;
}

export interface ChannelPluginConfigSchema {
  channel_type: string;
  plugin_name: string;
  source: string;
  package?: string;
  version?: string;
  schema_supported: boolean;
  config_schema?: {
    type?: string;
    properties?: Record<string, ChannelPluginSchemaProperty>;
    required?: string[];
  };
  config_ui_hints?: Record<
    string,
    {
      label?: string;
      help?: string;
      placeholder?: string;
      sensitive?: boolean;
      advanced?: boolean;
    }
  >;
  defaults?: Record<string, unknown>;
  secret_paths: string[];
}

export interface ChannelConfigList {
  items: ChannelConfig[];
  total: number;
}

export interface ChannelConnectionStatus {
  config_id: string;
  project_id: string;
  channel_type: string;
  status: string;
  connected: boolean;
  last_heartbeat?: string;
  last_error?: string;
  reconnect_attempts: number;
}

export interface ChannelObservabilitySummary {
  bindings_total: number;
  outbox_total: number;
  outbox_by_status: Record<string, number>;
  active_connections: number;
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
