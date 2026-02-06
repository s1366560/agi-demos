/**
 * Sandbox WebSocket URL Utilities
 *
 * Provides dynamic WebSocket URL generation for sandbox services,
 * supporting both development and production environments.
 */

import { logger } from '../utils/logger';

/**
 * WebSocket service types
 */
export type WebSocketServiceType = 'terminal' | 'desktop' | 'mcp';

/**
 * Get the base WebSocket URL protocol based on current page protocol
 */
export function getWebSocketProtocol(): string {
  return window.location.protocol === 'https:' ? 'wss:' : 'ws:';
}

/**
 * Get the API host from environment or current location
 */
export function getApiHost(): string {
  // In production, use the same host as the page
  // In development, this can be overridden via env variable
  return import.meta.env.VITE_API_HOST || window.location.host;
}

/**
 * Get the API base path
 */
export function getApiBasePath(): string {
  return import.meta.env.VITE_API_BASE_PATH || '/api/v1';
}

/**
 * Build a WebSocket URL for a specific service
 *
 * @param service - Service type (terminal, desktop, mcp)
 * @param sandboxId - Sandbox identifier
 * @param params - Additional query parameters
 * @returns Complete WebSocket URL
 *
 * @example
 * ```typescript
 * const wsUrl = buildWebSocketUrl("terminal", "sandbox-123", {
 *   session_id: "sess-456"
 * });
 * // Returns: "ws://localhost:8000/api/v1/terminal/sandbox-123/ws?session_id=sess-456"
 * ```
 */
export function buildWebSocketUrl(
  service: WebSocketServiceType,
  sandboxId: string,
  params?: Record<string, string>
): string {
  const protocol = getWebSocketProtocol();
  const host = getApiHost();
  const basePath = getApiBasePath();

  let path: string;
  switch (service) {
    case 'terminal':
      path = `${basePath}/terminal/${sandboxId}/ws`;
      break;
    case 'desktop':
      // Desktop (noVNC) uses HTTP, not WebSocket directly
      throw new Error('Desktop service uses HTTP, not WebSocket. Use buildDesktopUrl instead.');
    case 'mcp':
      path = `${basePath}/sandbox/${sandboxId}/mcp`;
      break;
    default:
      throw new Error(`Unknown service type: ${service}`);
  }

  const url = new URL(path, `${protocol}//${host}`);

  // Add query parameters
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, value);
      }
    });
  }

  const result = url.toString();
  logger.debug(`[WebSocketUtils] Built URL for ${service}: ${result}`);
  return result;
}

/**
 * Build HTTP URL for desktop (noVNC) service
 *
 * @param sandboxId - Sandbox identifier
 * @param path - Optional path after the base URL (e.g., "vnc.html")
 * @returns Complete HTTP URL for desktop access
 */
export function buildDesktopUrl(sandboxId: string, path?: string): string {
  const protocol = window.location.protocol;
  const host = getApiHost();
  const basePath = getApiBasePath();

  const urlPath = path
    ? `${basePath}/sandbox/${sandboxId}/desktop/proxy/${path}`
    : `${basePath}/sandbox/${sandboxId}/desktop/proxy`;

  const url = new URL(urlPath, `${protocol}//${host}`);
  return url.toString();
}

/**
 * Build direct desktop URL (when direct port access is available)
 *
 * @param host - Hostname or IP
 * @param port - Port number
 * @param path - Optional path
 * @returns Direct desktop URL
 */
export function buildDirectDesktopUrl(host: string, port: number, path = 'vnc.html'): string {
  const protocol = window.location.protocol;
  return `${protocol}//${host}:${port}/${path}`;
}

/**
 * Build terminal WebSocket URL with session ID
 *
 * @param sandboxId - Sandbox identifier
 * @param sessionId - Terminal session ID
 * @returns WebSocket URL for terminal
 */
export function buildTerminalWebSocketUrl(sandboxId: string, sessionId: string): string {
  return buildWebSocketUrl('terminal', sandboxId, { session_id: sessionId });
}

/**
 * Detect if running in development mode
 */
export function isDevelopment(): boolean {
  return import.meta.env.DEV === true;
}

/**
 * Detect if running in production mode
 */
export function isProduction(): boolean {
  return import.meta.env.PROD === true;
}

/**
 * Get environment-specific configuration
 */
export function getWebSocketConfig(): {
  reconnectAttempts: number;
  reconnectDelay: number;
  heartbeatInterval: number;
  timeout: number;
} {
  if (isDevelopment()) {
    return {
      reconnectAttempts: 5,
      reconnectDelay: 1000,
      heartbeatInterval: 30000,
      timeout: 30000,
    };
  }

  // Production settings
  return {
    reconnectAttempts: 10,
    reconnectDelay: 2000,
    heartbeatInterval: 30000,
    timeout: 60000,
  };
}

/**
 * Validate WebSocket URL
 *
 * @param url - URL to validate
 * @returns True if valid WebSocket URL
 */
export function isValidWebSocketUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'ws:' || parsed.protocol === 'wss:';
  } catch {
    return false;
  }
}

/**
 * Parse sandbox connection info from various sources
 *
 * @param sandbox - Sandbox object from API
 * @returns Normalized connection info
 */
export function parseSandboxConnection(sandbox: {
  id: string;
  desktop_port?: number;
  terminal_port?: number;
  desktop_url?: string;
  terminal_url?: string;
}): {
  desktopUrl: string | null;
  terminalWsUrl: string | null;
} {
  // Priority 1: Use provided URLs
  if (sandbox.desktop_url) {
    return {
      desktopUrl: sandbox.desktop_url,
      terminalWsUrl: sandbox.terminal_url ? buildWebSocketUrlFromHttp(sandbox.terminal_url) : null,
    };
  }

  // Priority 2: Build from ports (direct access)
  if (sandbox.desktop_port) {
    const host = getApiHost().split(':')[0]; // Remove port if present
    return {
      desktopUrl: buildDirectDesktopUrl(host, sandbox.desktop_port),
      terminalWsUrl: sandbox.terminal_port ? buildWebSocketUrl('terminal', sandbox.id) : null,
    };
  }

  // Fallback: Use API proxy
  return {
    desktopUrl: buildDesktopUrl(sandbox.id),
    terminalWsUrl: buildWebSocketUrl('terminal', sandbox.id),
  };
}

/**
 * Convert HTTP URL to WebSocket URL
 */
function buildWebSocketUrlFromHttp(httpUrl: string): string {
  try {
    const url = new URL(httpUrl);
    const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${url.host}${url.pathname}`;
  } catch {
    return '';
  }
}
