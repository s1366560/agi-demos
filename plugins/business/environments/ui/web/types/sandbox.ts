/**
 * Sandbox event types for SSE subscription.
 *
 * These types align with backend sandbox events in
 * src/domain/events/agent_events.py
 */

/**
 * All possible sandbox event types
 */
export type SandboxEventType =
  | 'sandbox_created'
  | 'sandbox_terminated'
  | 'sandbox_status'
  | 'desktop_started'
  | 'desktop_stopped'
  | 'desktop_status'
  | 'terminal_started'
  | 'terminal_stopped'
  | 'terminal_status';

/**
 * Base sandbox SSE event format
 */
export interface BaseSandboxSSEEvent {
  type: SandboxEventType;
  data: unknown;
  timestamp: string;
}

/**
 * Sandbox created event data
 */
export interface SandboxCreatedEventData {
  sandbox_id: string;
  project_id: string;
  status: string;
  endpoint?: string | undefined;
  websocket_url?: string | undefined;
}

/**
 * Sandbox created SSE event
 */
export interface SandboxCreatedSSEEvent extends BaseSandboxSSEEvent {
  type: 'sandbox_created';
  data: SandboxCreatedEventData;
}

/**
 * Sandbox terminated event data
 */
export interface SandboxTerminatedEventData {
  sandbox_id: string;
}

/**
 * Sandbox terminated SSE event
 */
export interface SandboxTerminatedSSEEvent extends BaseSandboxSSEEvent {
  type: 'sandbox_terminated';
  data: SandboxTerminatedEventData;
}

/**
 * Sandbox status event data
 */
export interface SandboxStatusEventData {
  sandbox_id: string;
  status: string;
}

/**
 * Sandbox status SSE event
 */
export interface SandboxStatusSSEEvent extends BaseSandboxSSEEvent {
  type: 'sandbox_status';
  data: SandboxStatusEventData;
}

/**
 * Desktop started event data
 */
export interface DesktopStartedEventData {
  sandbox_id: string;
  url?: string | undefined;
  display: string;
  resolution: string;
  port: number;
  audio_enabled?: boolean | undefined;
  dynamic_resize?: boolean | undefined;
  encoding?: string | undefined;
}

/**
 * Desktop started SSE event
 */
export interface DesktopStartedSSEEvent extends BaseSandboxSSEEvent {
  type: 'desktop_started';
  data: DesktopStartedEventData;
}

/**
 * Desktop stopped event data
 */
export interface DesktopStoppedEventData {
  sandbox_id: string;
}

/**
 * Desktop stopped SSE event
 */
export interface DesktopStoppedSSEEvent extends BaseSandboxSSEEvent {
  type: 'desktop_stopped';
  data: DesktopStoppedEventData;
}

/**
 * Desktop status event data
 */
export interface DesktopStatusEventData {
  sandbox_id: string;
  running: boolean;
  url?: string | undefined;
  display: string;
  resolution: string;
  port: number;
  audio_enabled?: boolean | undefined;
  dynamic_resize?: boolean | undefined;
  encoding?: string | undefined;
}

/**
 * Desktop status SSE event
 */
export interface DesktopStatusSSEEvent extends BaseSandboxSSEEvent {
  type: 'desktop_status';
  data: DesktopStatusEventData;
}

/**
 * Terminal started event data
 */
export interface TerminalStartedEventData {
  sandbox_id: string;
  url?: string | undefined;
  port: number;
  session_id?: string | undefined;
  pid?: number | undefined;
}

/**
 * Terminal started SSE event
 */
export interface TerminalStartedSSEEvent extends BaseSandboxSSEEvent {
  type: 'terminal_started';
  data: TerminalStartedEventData;
}

/**
 * Terminal stopped event data
 */
export interface TerminalStoppedEventData {
  sandbox_id: string;
  session_id?: string | undefined;
}

/**
 * Terminal stopped SSE event
 */
export interface TerminalStoppedSSEEvent extends BaseSandboxSSEEvent {
  type: 'terminal_stopped';
  data: TerminalStoppedEventData;
}

/**
 * Terminal status event data
 */
export interface TerminalStatusEventData {
  sandbox_id: string;
  running: boolean;
  url?: string | undefined;
  port: number;
  session_id?: string | undefined;
  pid?: number | undefined;
}

/**
 * Terminal status SSE event
 */
export interface TerminalStatusSSEEvent extends BaseSandboxSSEEvent {
  type: 'terminal_status';
  data: TerminalStatusEventData;
}

/**
 * Union type for all sandbox SSE events
 */
export type SandboxSSEEvent =
  | SandboxCreatedSSEEvent
  | SandboxTerminatedSSEEvent
  | SandboxStatusSSEEvent
  | DesktopStartedSSEEvent
  | DesktopStoppedSSEEvent
  | DesktopStatusSSEEvent
  | TerminalStartedSSEEvent
  | TerminalStoppedSSEEvent
  | TerminalStatusSSEEvent;

/**
 * Type guard to check if event is a specific type
 */
export function isSandboxEventType(
  event: BaseSandboxSSEEvent,
  type: SandboxEventType
): event is SandboxSSEEvent {
  return event.type === type;
}

/**
 * Type guard for sandbox_created event
 */
export function isSandboxCreatedEvent(event: SandboxSSEEvent): event is SandboxCreatedSSEEvent {
  return event.type === 'sandbox_created';
}

/**
 * Type guard for desktop_started event
 */
export function isDesktopStartedEvent(event: SandboxSSEEvent): event is DesktopStartedSSEEvent {
  return event.type === 'desktop_started';
}

/**
 * Type guard for terminal_started event
 */
export function isTerminalStartedEvent(event: SandboxSSEEvent): event is TerminalStartedSSEEvent {
  return event.type === 'terminal_started';
}

// ============================================================================
// Project Sandbox Types (v2 API)
// ============================================================================

/**
 * Project sandbox lifecycle status
 */
export type ProjectSandboxStatus =
  | 'pending'
  | 'creating'
  | 'running'
  | 'unhealthy'
  | 'stopped'
  | 'terminated'
  | 'error';

/**
 * Project sandbox information (v2 API)
 */
export interface ProjectSandbox {
  /** Unique sandbox identifier */
  sandbox_id: string;
  /** Associated project ID */
  project_id: string;
  /** Tenant ID */
  tenant_id: string;
  /** Current lifecycle status */
  status: ProjectSandboxStatus;
  /** MCP WebSocket endpoint */
  endpoint?: string | undefined;
  /** WebSocket URL */
  websocket_url?: string | undefined;
  /** MCP server port */
  mcp_port?: number | undefined;
  /** Desktop (KasmVNC) port */
  desktop_port?: number | undefined;
  /** Terminal (ttyd) port */
  terminal_port?: number | undefined;
  /** Desktop access URL */
  desktop_url?: string | undefined;
  /** Terminal access URL */
  terminal_url?: string | undefined;
  /** Creation timestamp */
  created_at?: string | undefined;
  /** Last access timestamp */
  last_accessed_at?: string | undefined;
  /** Whether sandbox is healthy */
  is_healthy: boolean;
  /** Error message if in error state */
  error_message?: string | undefined;
}

/**
 * Tool execution request (v2 API)
 */
export interface ExecuteToolRequest {
  /** MCP tool name (bash, read, write, etc.) */
  tool_name: string;
  /** Tool arguments */
  arguments: Record<string, unknown>;
  /** Execution timeout in seconds */
  timeout?: number | undefined;
}

/**
 * Tool execution response (v2 API)
 */
export interface ExecuteToolResponse {
  /** Whether execution succeeded */
  success: boolean;
  /** Tool output content */
  content: Array<{ type: string; text?: string | undefined }>;
  /** Whether tool returned an error */
  is_error: boolean;
  /** Execution time in milliseconds */
  execution_time_ms?: number | undefined;
}

/**
 * Health check response (v2 API)
 */
export interface HealthCheckResponse {
  project_id: string;
  sandbox_id: string;
  healthy: boolean;
  status: string;
  checked_at: string;
}
