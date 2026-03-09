import type { ServerMessage } from './types';
import type { LifecycleState, LifecycleStateData, SandboxStateData } from '../../types/agent';

/**
 * Parse lifecycle state data from WebSocket message
 */
export function parseLifecycleStateData(message: ServerMessage): LifecycleStateData {
  const data = (message as { data?: Record<string, unknown> | undefined }).data || {};
  return {
    lifecycleState: data.lifecycle_state as LifecycleState | null,
    isInitialized: Boolean(data.is_initialized),
    isActive: Boolean(data.is_active),
    toolCount: typeof data.tool_count === 'number' ? data.tool_count : undefined,
    builtinToolCount:
      typeof data.builtin_tool_count === 'number' ? data.builtin_tool_count : undefined,
    mcpToolCount: typeof data.mcp_tool_count === 'number' ? data.mcp_tool_count : undefined,
    skillCount: typeof data.skill_count === 'number' ? data.skill_count : undefined,
    totalSkillCount:
      typeof data.total_skill_count === 'number' ? data.total_skill_count : undefined,
    loadedSkillCount:
      typeof data.loaded_skill_count === 'number' ? data.loaded_skill_count : undefined,
    subagentCount: typeof data.subagent_count === 'number' ? data.subagent_count : undefined,
    conversationId: typeof data.conversation_id === 'string' ? data.conversation_id : undefined,
    errorMessage: typeof data.error_message === 'string' ? data.error_message : undefined,
  };
}

/**
 * Parse sandbox state data from WebSocket message
 *
 * Handles two message formats:
 * 1. sandbox_state_change (from broadcast_sandbox_state): { type, project_id, data: { event_type, ... } }
 * 2. sandbox_event (from Redis stream): { type, project_id, data: { type, data: { ... }, timestamp } }
 */
export function parseSandboxStateData(message: ServerMessage): SandboxStateData {
  const messageType = (message as { type?: string | undefined }).type;
  let data: Record<string, unknown>;
  let eventType: string;

  if (messageType === 'sandbox_event') {
    // Redis stream format: data contains { type, data, timestamp }
    const outerData = (message as { data?: Record<string, unknown> | undefined }).data || {};
    eventType = typeof outerData.type === 'string' ? outerData.type : 'unknown';
    data = (outerData.data as Record<string, unknown>) || {};
  } else {
    // broadcast_sandbox_state format: data contains event fields directly
    data = (message as { data?: Record<string, unknown> | undefined }).data || {};
    eventType = typeof data.event_type === 'string' ? data.event_type : 'unknown';
  }

  return {
    eventType,
    sandboxId: typeof data.sandbox_id === 'string' ? data.sandbox_id : null,
    status: (data.status as SandboxStateData['status']) || null,
    endpoint: typeof data.endpoint === 'string' ? data.endpoint : undefined,
    websocketUrl: typeof data.websocket_url === 'string' ? data.websocket_url : undefined,
    mcpPort: typeof data.mcp_port === 'number' ? data.mcp_port : undefined,
    desktopPort: typeof data.desktop_port === 'number' ? data.desktop_port : undefined,
    terminalPort: typeof data.terminal_port === 'number' ? data.terminal_port : undefined,
    desktopUrl: typeof data.desktop_url === 'string' ? data.desktop_url : undefined,
    terminalUrl: typeof data.terminal_url === 'string' ? data.terminal_url : undefined,
    isHealthy: Boolean(data.is_healthy),
    errorMessage: typeof data.error_message === 'string' ? data.error_message : undefined,
    serviceId: typeof data.service_id === 'string' ? data.service_id : undefined,
    serviceName: typeof data.service_name === 'string' ? data.service_name : undefined,
    sourceType:
      data.source_type === 'sandbox_internal' || data.source_type === 'external_url'
        ? data.source_type
        : undefined,
    serviceUrl: typeof data.service_url === 'string' ? data.service_url : undefined,
    previewUrl: typeof data.preview_url === 'string' ? data.preview_url : undefined,
    wsPreviewUrl: typeof data.ws_preview_url === 'string' ? data.ws_preview_url : undefined,
    autoOpen: typeof data.auto_open === 'boolean' ? data.auto_open : undefined,
    restartToken: typeof data.restart_token === 'string' ? data.restart_token : undefined,
    updatedAt: typeof data.updated_at === 'string' ? data.updated_at : undefined,
  };
}
