import type { ServerMessage } from './types';
import type { LifecycleState, LifecycleStateData, SandboxStateData } from '../../types/agent';

function getStringField(data: Record<string, unknown>, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = data[key];
    if (typeof value === 'string') return value;
  }
  return undefined;
}

function getNumberField(data: Record<string, unknown>, ...keys: string[]): number | undefined {
  for (const key of keys) {
    const value = data[key];
    if (typeof value === 'number') return value;
  }
  return undefined;
}

function getBooleanField(data: Record<string, unknown>, ...keys: string[]): boolean | undefined {
  for (const key of keys) {
    const value = data[key];
    if (typeof value === 'boolean') return value;
  }
  return undefined;
}

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
    const outerPayload = outerData.data;
    data =
      outerPayload && typeof outerPayload === 'object' && !Array.isArray(outerPayload)
        ? (outerPayload as Record<string, unknown>)
        : {};
  } else {
    // broadcast_sandbox_state format: data contains event fields directly
    data = (message as { data?: Record<string, unknown> | undefined }).data || {};
    eventType = typeof data.event_type === 'string' ? data.event_type : 'unknown';
  }

  return {
    eventType,
    sandboxId: getStringField(data, 'sandbox_id', 'sandboxId') ?? null,
    status: (data.status as SandboxStateData['status']) || null,
    endpoint: getStringField(data, 'endpoint'),
    websocketUrl: getStringField(data, 'websocket_url', 'websocketUrl'),
    mcpPort: getNumberField(data, 'mcp_port', 'mcpPort'),
    desktopPort: getNumberField(data, 'desktop_port', 'desktopPort'),
    terminalPort: getNumberField(data, 'terminal_port', 'terminalPort'),
    desktopUrl: getStringField(data, 'desktop_url', 'desktopUrl'),
    terminalUrl: getStringField(data, 'terminal_url', 'terminalUrl'),
    isHealthy: getBooleanField(data, 'is_healthy', 'isHealthy') ?? false,
    errorMessage: getStringField(data, 'error_message', 'errorMessage'),
    running: getBooleanField(data, 'running'),
    url: getStringField(data, 'url'),
    display: getStringField(data, 'display'),
    resolution: getStringField(data, 'resolution'),
    port: getNumberField(data, 'port'),
    sessionId: getStringField(data, 'session_id', 'sessionId'),
    pid: getNumberField(data, 'pid'),
    audioEnabled: getBooleanField(data, 'audio_enabled', 'audioEnabled'),
    dynamicResize: getBooleanField(data, 'dynamic_resize', 'dynamicResize'),
    encoding: getStringField(data, 'encoding'),
    serviceId: getStringField(data, 'service_id', 'serviceId'),
    serviceName: getStringField(data, 'service_name', 'serviceName'),
    sourceType:
      data.source_type === 'sandbox_internal' || data.source_type === 'external_url'
        ? data.source_type
        : undefined,
    serviceUrl: getStringField(data, 'service_url', 'serviceUrl'),
    previewUrl: getStringField(data, 'preview_url', 'previewUrl', 'proxy_url', 'proxyUrl'),
    wsPreviewUrl: getStringField(
      data,
      'ws_preview_url',
      'wsPreviewUrl',
      'ws_proxy_url',
      'wsProxyUrl'
    ),
    autoOpen: getBooleanField(data, 'auto_open', 'autoOpen'),
    restartToken: getStringField(data, 'restart_token', 'restartToken'),
    updatedAt: getStringField(data, 'updated_at', 'updatedAt'),
  };
}
