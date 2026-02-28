/**
 * MCP App Types
 *
 * Type definitions for MCP Apps - interactive HTML interfaces
 * declared by MCP tools via the _meta.ui.resourceUri extension.
 */

export type MCPAppDisplayMode = 'inline' | 'fullscreen' | 'pip';

export interface MCPAppUIPermissions {
  camera?: Record<string, never> | undefined;
  microphone?: Record<string, never> | undefined;
  geolocation?: Record<string, never> | undefined;
  clipboardWrite?: Record<string, never> | undefined;
}

export interface MCPAppUIMetadata {
  resourceUri: string;
  permissions?: MCPAppUIPermissions | undefined;
  csp?:
    | {
        connectDomains?: string[] | undefined;
        resourceDomains?: string[] | undefined;
        frameDomains?: string[] | undefined;
        baseUriDomains?: string[] | undefined;
      }
    | undefined;
  title?: string | undefined;
  visibility?: Array<'model' | 'app'> | undefined;
  prefersBorder?: boolean | undefined;
  domain?: string | undefined;
  /** Display mode preference (SEP-1865): inline (default), fullscreen, or pip */
  displayMode?: MCPAppDisplayMode | undefined;
}

export type MCPAppSource = 'user_added' | 'agent_developed';

export type MCPAppStatus = 'discovered' | 'loading' | 'ready' | 'error' | 'disabled';

export interface MCPApp {
  id: string;
  project_id: string;
  tenant_id: string;
  server_id: string | null;
  server_name: string;
  tool_name: string;
  ui_metadata: MCPAppUIMetadata;
  source: MCPAppSource;
  status: MCPAppStatus;
  lifecycle_metadata?: Record<string, unknown> | undefined;
  error_message?: string | undefined;
  has_resource: boolean;
  resource_size_bytes?: number | undefined;
  created_at?: string | undefined;
  updated_at?: string | undefined;
}

export interface MCPAppResource {
  app_id: string;
  resource_uri: string;
  html_content: string;
  mime_type: string;
  size_bytes: number;
  ui_metadata: MCPAppUIMetadata;
}

export interface MCPAppToolCallRequest {
  tool_name: string;
  arguments: Record<string, unknown>;
}

/** Direct tool-call request for auto-discovered apps (no DB record). */
export interface MCPAppDirectToolCallRequest {
  project_id: string;
  server_name: string;
  tool_name: string;
  arguments: Record<string, unknown>;
}

export interface MCPAppToolCallResponse {
  content: Array<{ type: string; text?: string | undefined }>;
  is_error: boolean;
  error_message?: string | undefined;
}

/** SSE event data for mcp_app_result */
export interface MCPAppResultEventData {
  app_id: string;
  tool_name: string;
  tool_result: unknown;
  resource_html: string;
  resource_uri: string;
  ui_metadata: Record<string, unknown>;
  tool_execution_id?: string | undefined;
}

/** SSE event data for mcp_app_registered */
export interface MCPAppRegisteredEventData {
  app_id: string;
  server_name: string;
  tool_name: string;
  source: MCPAppSource;
  resource_uri: string;
  title?: string | undefined;
}
