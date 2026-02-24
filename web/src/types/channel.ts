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
  app_id?: string | undefined;
  webhook_url?: string | undefined;
  webhook_port?: number | undefined;
  webhook_path?: string | undefined;
  domain?: string | undefined;
  extra_settings?: Record<string, any> | undefined;
  dm_policy: DmPolicy;
  group_policy: GroupPolicy;
  allow_from?: string[] | undefined;
  group_allow_from?: string[] | undefined;
  rate_limit_per_minute: number;
  status: 'connected' | 'disconnected' | 'error' | 'circuit_open';
  last_error?: string | undefined;
  description?: string | undefined;
  created_at: string;
  updated_at?: string | undefined;
}

export interface CreateChannelConfig {
  channel_type: string;
  name: string;
  enabled?: boolean | undefined;
  connection_mode?: 'websocket' | 'webhook' | undefined;
  app_id?: string | undefined;
  app_secret?: string | undefined;
  encrypt_key?: string | undefined;
  verification_token?: string | undefined;
  webhook_url?: string | undefined;
  webhook_port?: number | undefined;
  webhook_path?: string | undefined;
  domain?: string | undefined;
  extra_settings?: Record<string, any> | undefined;
  description?: string | undefined;
  dm_policy?: DmPolicy | undefined;
  group_policy?: GroupPolicy | undefined;
  allow_from?: string[] | undefined;
  group_allow_from?: string[] | undefined;
  rate_limit_per_minute?: number | undefined;
}

export interface UpdateChannelConfig {
  name?: string | undefined;
  enabled?: boolean | undefined;
  connection_mode?: 'websocket' | 'webhook' | undefined;
  app_id?: string | undefined;
  app_secret?: string | undefined;
  encrypt_key?: string | undefined;
  verification_token?: string | undefined;
  webhook_url?: string | undefined;
  webhook_port?: number | undefined;
  webhook_path?: string | undefined;
  domain?: string | undefined;
  extra_settings?: Record<string, any> | undefined;
  description?: string | undefined;
  dm_policy?: DmPolicy | undefined;
  group_policy?: GroupPolicy | undefined;
  allow_from?: string[] | undefined;
  group_allow_from?: string[] | undefined;
  rate_limit_per_minute?: number | undefined;
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
  package?: string | undefined;
  version?: string | undefined;
  enabled: boolean;
  discovered: boolean;
  channel_types: string[];
}

export interface RuntimePluginList {
  items: RuntimePlugin[];
  diagnostics: PluginDiagnostic[];
}

export interface PluginCapabilityCounts {
  channel_types: number;
  tool_factories: number;
  hooks: number;
  commands: number;
  services: number;
  providers: number;
}

export interface PluginControlPlaneTrace {
  trace_id: string;
  action: string;
  plugin_name?: string | null | undefined;
  requirement?: string | null | undefined;
  tenant_id?: string | null | undefined;
  timestamp: string;
  capability_counts: PluginCapabilityCounts;
}

export interface PluginActionDetails {
  diagnostics?: PluginDiagnostic[] | undefined;
  control_plane_trace?: PluginControlPlaneTrace | undefined;
  channel_reload_plan?: Record<string, number> | undefined;
  [key: string]: unknown;
}

export interface PluginActionResponse {
  success: boolean;
  message: string;
  details?: PluginActionDetails | undefined;
}

export interface ChannelPluginCatalogItem {
  channel_type: string;
  plugin_name: string;
  source: string;
  package?: string | undefined;
  version?: string | undefined;
  enabled: boolean;
  discovered: boolean;
  schema_supported: boolean;
}

export interface ChannelPluginCatalog {
  items: ChannelPluginCatalogItem[];
}

export interface ChannelPluginSchemaProperty {
  type?: string | undefined;
  title?: string | undefined;
  description?: string | undefined;
  enum?: Array<string | number | boolean> | undefined;
  minimum?: number | undefined;
  maximum?: number | undefined;
}

export interface ChannelPluginConfigSchema {
  channel_type: string;
  plugin_name: string;
  source: string;
  package?: string | undefined;
  version?: string | undefined;
  schema_supported: boolean;
  config_schema?: {
    type?: string | undefined;
    properties?: Record<string, ChannelPluginSchemaProperty> | undefined;
    required?: string[] | undefined;
  } | undefined;
  config_ui_hints?: Record<
    string,
    {
      label?: string | undefined;
      help?: string | undefined;
      placeholder?: string | undefined;
      sensitive?: boolean | undefined;
      advanced?: boolean | undefined;
    }
  > | undefined;
  defaults?: Record<string, unknown> | undefined;
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
  last_heartbeat?: string | undefined;
  last_error?: string | undefined;
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
  sender_name?: string | undefined;
  message_type: string;
  content_text?: string | undefined;
  content_data?: Record<string, any> | undefined;
  reply_to?: string | undefined;
  mentions?: string[] | undefined;
  direction: 'inbound' | 'outbound';
  created_at: string;
}
