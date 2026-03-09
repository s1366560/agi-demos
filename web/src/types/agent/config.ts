import type { SkillResponse } from './execution';
// ============================================
// Tenant Agent Configuration Types (T093, T102)
// ============================================

/**
 * Configuration type (T089)
 */
export type ConfigType = 'default' | 'custom';

/**
 * Tenant agent configuration (FR-021, FR-022)
 *
 * Represents tenant-level agent configuration that controls
 * agent behavior at the tenant level.
 *
 * Access Control:
 * - All authenticated users can READ config
 * - Only tenant admins can MODIFY config
 */
export interface TenantAgentConfig {
  id: string;
  tenant_id: string;
  config_type: ConfigType;
  llm_model: string;
  llm_temperature: number;
  pattern_learning_enabled: boolean;
  multi_level_thinking_enabled: boolean;
  max_work_plan_steps: number;
  tool_timeout_seconds: number;
  enabled_tools: string[];
  disabled_tools: string[];
  created_at: string;
  updated_at: string;
}

/**
 * Update tenant agent configuration request (T089)
 *
 * All fields are optional - only provided fields will be updated.
 * Validation occurs on the backend.
 */
export interface UpdateTenantAgentConfigRequest {
  llm_model?: string | undefined;
  llm_temperature?: number | undefined;
  pattern_learning_enabled?: boolean | undefined;
  multi_level_thinking_enabled?: boolean | undefined;
  max_work_plan_steps?: number | undefined;
  tool_timeout_seconds?: number | undefined;
  enabled_tools?: string[] | undefined;
  disabled_tools?: string[] | undefined;
}

/**
 * Tenant agent configuration service interface (T089, T103)
 */
export interface TenantAgentConfigService {
  /**
   * Get tenant agent configuration
   * Returns default config if no custom config exists (FR-021)
   */
  getConfig(tenantId: string): Promise<TenantAgentConfig>;

  /**
   * Update tenant agent configuration (FR-022)
   * Only accessible to tenant admins
   */
  updateConfig(
    tenantId: string,
    request: UpdateTenantAgentConfigRequest
  ): Promise<TenantAgentConfig>;

  /**
   * Check if current user can modify tenant config
   * Used to conditionally show edit UI
   */
  canModifyConfig(tenantId: string): Promise<boolean>;
}

// ============================================
// MCP (Model Context Protocol) Types
// ============================================

/**
 * MCP server transport types
 */
export type MCPServerType = 'stdio' | 'sse' | 'http' | 'websocket';

/**
 * MCP tool information discovered from server
 */
export interface MCPToolInfo {
  name: string;
  description?: string | undefined;
  input_schema?: Record<string, unknown> | undefined;
  is_error?: boolean | undefined;
}

/**
 * MCP server response from API
 */
export interface MCPServerResponse {
  id: string;
  tenant_id: string;
  project_id?: string | undefined;
  name: string;
  description?: string | undefined;
  server_type: MCPServerType;
  transport_config: Record<string, unknown>;
  enabled: boolean;
  runtime_status?: string | undefined;
  runtime_metadata?: Record<string, unknown> | undefined;
  discovered_tools: MCPToolInfo[];
  last_sync_at?: string | undefined;
  sync_error?: string | undefined;
  created_at: string;
  updated_at: string;
}

/**
 * MCP server create request
 */
export interface MCPServerCreate {
  name: string;
  description?: string | undefined;
  server_type: MCPServerType;
  transport_config: Record<string, unknown>;
  enabled?: boolean | undefined;
  project_id: string;
}

/**
 * MCP server update request
 */
export interface MCPServerUpdate {
  name?: string | undefined;
  description?: string | undefined;
  server_type?: MCPServerType | undefined;
  transport_config?: Record<string, unknown> | undefined;
  enabled?: boolean | undefined;
}

/**
 * MCP servers list response
 */
export interface MCPServersListResponse {
  servers: MCPServerResponse[];
  total: number;
}

/**
 * MCP server sync response (after discovering tools)
 */
export interface MCPServerSyncResponse {
  server: MCPServerResponse;
  tools_count: number;
  message: string;
}

/**
 * MCP server test connection response
 */
export interface MCPServerTestResponse {
  success: boolean;
  message: string;
  tools_discovered?: number | undefined;
  connection_time_ms?: number | undefined;
  latency_ms?: number | undefined; // Backward compatibility
  errors?: string[] | undefined;
}

/**
 * MCP tool call request
 */
export interface MCPToolCallRequest {
  server_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
}

/**
 * MCP tool call response
 */
export interface MCPToolCallResponse {
  success: boolean;
  result?: unknown;
  error?: string | undefined;
  execution_time_ms: number;
}

/**
 * Transport config for stdio type
 */
export interface StdioTransportConfig {
  command: string;
  args?: string[] | undefined;
  env?: Record<string, string> | undefined;
}

/**
 * Transport config for HTTP/SSE type
 */
export interface HttpTransportConfig {
  url: string;
  headers?: Record<string, string> | undefined;
}

/**
 * Transport config for WebSocket type
 */
export interface WebSocketTransportConfig {
  url: string;
}

// ============================================
// Sandbox Types (Desktop and Terminal)
// ============================================

/**
 * Desktop status for remote desktop sessions
 */
export interface DesktopStatus {
  running: boolean;
  url: string | null;
  /** WebSocket URL for KasmVNC connection */
  wsUrl?: string | null | undefined;
  display: string;
  resolution: string;
  port: number;
  /** KasmVNC process ID */
  kasmvncPid?: number | null | undefined;
  /** Whether audio streaming is enabled */
  audioEnabled?: boolean | undefined;
  /** Whether dynamic resize is supported */
  dynamicResize?: boolean | undefined;
  /** Image encoding format (webp/jpeg/qoi) */
  encoding?: string | undefined;
}

/**
 * Terminal status for web terminal sessions
 */
export interface TerminalStatus {
  running: boolean;
  url: string | null;
  port: number;
  pid?: number | null | undefined;
  sessionId?: string | null | undefined;
}

// ============================================
// Artifact Types (Rich Output Display)
// ============================================

/**
 * Artifact category for UI rendering decisions
 */
export type ArtifactCategory =
  | 'image'
  | 'video'
  | 'audio'
  | 'document'
  | 'code'
  | 'data'
  | 'archive'
  | 'other';

/**
 * Artifact status
 */
export type ArtifactStatus = 'pending' | 'uploading' | 'ready' | 'error' | 'deleted';

/**
 * Artifact information for rich output display
 */
export interface Artifact {
  id: string;
  projectId: string;
  tenantId: string;
  sandboxId?: string | undefined;
  toolExecutionId?: string | undefined;
  conversationId?: string | undefined;

  filename: string;
  mimeType: string;
  category: ArtifactCategory;
  sizeBytes: number;

  url?: string | undefined;
  previewUrl?: string | undefined;

  status: ArtifactStatus;
  errorMessage?: string | undefined;

  sourceTool?: string | undefined;
  sourcePath?: string | undefined;

  metadata?: Record<string, unknown> | undefined;
  createdAt: string;
}

// ============================================
// Lifecycle State Types (Agent Lifecycle Monitoring)
// ============================================

/**
 * Lifecycle states for ProjectReActAgent
 */
export type LifecycleState =
  | 'initializing'
  | 'ready'
  | 'executing'
  | 'paused'
  | 'shutting_down'
  | 'error';

/**
 * Lifecycle state data from WebSocket
 */
export interface LifecycleStateData {
  lifecycleState: LifecycleState | null;
  isInitialized: boolean;
  isActive: boolean;
  /** Total tool count (builtin + mcp) */
  toolCount?: number | undefined;
  /** Number of built-in tools */
  builtinToolCount?: number | undefined;
  /** Number of MCP tools */
  mcpToolCount?: number | undefined;
  /** Deprecated, use loadedSkillCount */
  skillCount?: number | undefined;
  /** Total number of skills available in registry */
  totalSkillCount?: number | undefined;
  /** Number of skills loaded into current context */
  loadedSkillCount?: number | undefined;
  subagentCount?: number | undefined;
  conversationId?: string | undefined;
  errorMessage?: string | undefined;
}

/**
 * Sandbox status types
 */
export type SandboxStatus =
  | 'pending'
  | 'creating'
  | 'running'
  | 'unhealthy'
  | 'stopped'
  | 'terminated'
  | 'error';

/**
 * Sandbox state data from WebSocket
 *
 * Pushed via WebSocket when sandbox state changes, replacing SSE-based events.
 */
export interface SandboxStateData {
  /** Event type: created, terminated, restarted, status_changed */
  eventType: string;
  /** Unique sandbox identifier */
  sandboxId: string | null;
  /** Current sandbox status */
  status: SandboxStatus | null;
  /** MCP WebSocket endpoint URL */
  endpoint?: string | undefined;
  /** WebSocket URL for MCP connection */
  websocketUrl?: string | undefined;
  /** MCP server port */
  mcpPort?: number | undefined;
  /** Desktop (noVNC) port */
  desktopPort?: number | undefined;
  /** Terminal (ttyd) port */
  terminalPort?: number | undefined;
  /** Desktop access URL */
  desktopUrl?: string | undefined;
  /** Terminal access URL */
  terminalUrl?: string | undefined;
  /** Whether sandbox is healthy */
  isHealthy: boolean;
  /** Error message if in error state */
  errorMessage?: string | undefined;
  /** HTTP service identifier for sandbox web previews */
  serviceId?: string | undefined;
  /** Human-readable service name */
  serviceName?: string | undefined;
  /** Service source type */
  sourceType?: 'sandbox_internal' | 'external_url' | undefined;
  /** Upstream service URL */
  serviceUrl?: string | undefined;
  /** Preview URL to use in Canvas */
  previewUrl?: string | undefined;
  /** WebSocket preview URL for HMR/live updates */
  wsPreviewUrl?: string | undefined;
  /** Whether frontend should auto-open this service in Canvas */
  autoOpen?: boolean | undefined;
  /** Restart/version token to force iframe refresh */
  restartToken?: string | undefined;
  /** Event timestamp for idempotency */
  updatedAt?: string | undefined;
}

/**
 * Lifecycle status for UI display
 */
export interface LifecycleStatus {
  label: string;
  color: string;
  icon: string;
  description: string;
}

// === Command Types (Slash Command System) ===

export interface CommandArgInfo {
  name: string;
  description: string;
  arg_type: string;
  required: boolean;
  choices: string[] | null;
}

export interface CommandInfo {
  name: string;
  description: string;
  category: string;
  scope: string;
  aliases: string[];
  args: CommandArgInfo[];
}

export interface CommandsListResponse {
  commands: CommandInfo[];
  total: number;
}

export type SlashItem =
  | { kind: 'command'; data: CommandInfo }
  | { kind: 'skill'; data: SkillResponse };
