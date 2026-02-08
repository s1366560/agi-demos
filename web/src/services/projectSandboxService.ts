/**
 * Project Sandbox Service - Project-dedicated sandbox lifecycle management API
 *
 * Provides methods for managing persistent sandboxes per project:
 * - Each project has exactly one persistent sandbox
 * - Lazy creation on first use
 * - Health monitoring and auto-recovery
 *
 * This service replaces the old sandbox ID-based management with project-scoped operations.
 *
 * @packageDocumentation
 */

import { logger } from '../utils/logger';
import { getAuthToken } from '../utils/tokenResolver';

import { httpClient } from './client/httpClient';
import { buildDesktopWebSocketUrl, buildTerminalWebSocketUrl } from './sandboxWebSocketUtils';

/**
 * Project sandbox status
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
 * Project sandbox information
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
  endpoint?: string;
  /** WebSocket URL */
  websocket_url?: string;
  /** MCP server port */
  mcp_port?: number;
  /** Desktop (noVNC) port */
  desktop_port?: number;
  /** Terminal (ttyd) port */
  terminal_port?: number;
  /** Desktop access URL */
  desktop_url?: string;
  /** Terminal access URL */
  terminal_url?: string;
  /** Creation timestamp */
  created_at?: string;
  /** Last access timestamp */
  last_accessed_at?: string;
  /** Whether sandbox is healthy */
  is_healthy: boolean;
  /** Error message if in error state */
  error_message?: string;
}

/**
 * Request to ensure project's sandbox exists
 */
export interface EnsureSandboxRequest {
  /** Optional profile: lite, standard, or full */
  profile?: string;
  /** Whether to auto-create if doesn't exist */
  auto_create?: boolean;
}

/**
 * Tool execution request
 */
export interface ExecuteToolRequest {
  /** MCP tool name (bash, read, write, etc.) */
  tool_name: string;
  /** Tool arguments */
  arguments: Record<string, unknown>;
  /** Execution timeout in seconds */
  timeout?: number;
}

/**
 * Tool execution response
 */
export interface ExecuteToolResponse {
  /** Whether execution succeeded */
  success: boolean;
  /** Tool output content */
  content: Array<{ type: string; text?: string }>;
  /** Whether tool returned an error */
  is_error: boolean;
  /** Execution time in milliseconds */
  execution_time_ms?: number;
}

/**
 * Health check response
 */
export interface HealthCheckResponse {
  project_id: string;
  sandbox_id: string;
  healthy: boolean;
  status: string;
  checked_at: string;
}

/**
 * Sandbox action response (restart, terminate)
 */
export interface SandboxActionResponse {
  success: boolean;
  message: string;
  sandbox?: ProjectSandbox;
}

/**
 * Sandbox resource statistics
 */
export interface SandboxStats {
  project_id: string;
  sandbox_id: string;
  status: string;
  cpu_percent: number;
  memory_usage: number;
  memory_limit: number;
  memory_percent: number;
  disk_usage?: number;
  disk_limit?: number;
  disk_percent?: number;
  network_rx_bytes?: number;
  network_tx_bytes?: number;
  pids: number;
  uptime_seconds?: number;
  created_at?: string;
  collected_at: string;
}

/**
 * Desktop status
 */
export interface DesktopStatus {
  running: boolean;
  url: string | null;
  /** WebSocket URL for KasmVNC connection */
  wsUrl?: string | null;
  display: string;
  resolution: string;
  port: number;
  /** Whether audio streaming is enabled */
  audioEnabled?: boolean;
  /** Whether dynamic resize is supported */
  dynamicResize?: boolean;
  /** Image encoding format (webp/jpeg/qoi) */
  encoding?: string;
}

/**
 * Terminal status
 */
export interface TerminalStatus {
  running: boolean;
  url: string | null;
  port: number;
  sessionId: string | null;
  pid: number | null;
}

/**
 * Project sandbox service interface
 */
export interface ProjectSandboxService {
  /**
   * Get project's sandbox info
   * @param projectId - Project ID
   * @returns Promise resolving to sandbox info or null if not exists
   */
  getProjectSandbox(projectId: string): Promise<ProjectSandbox | null>;

  /**
   * Ensure project's sandbox exists and is running
   * @param projectId - Project ID
   * @param request - Optional configuration
   * @returns Promise resolving to sandbox info
   */
  ensureSandbox(projectId: string, request?: EnsureSandboxRequest): Promise<ProjectSandbox>;

  /**
   * Check sandbox health
   * @param projectId - Project ID
   * @returns Promise resolving to health check result
   */
  healthCheck(projectId: string): Promise<HealthCheckResponse>;

  /**
   * Get sandbox resource statistics
   * @param projectId - Project ID
   * @returns Promise resolving to resource stats
   */
  getStats(projectId: string): Promise<SandboxStats>;

  /**
   * Execute a tool in project's sandbox
   * @param projectId - Project ID
   * @param request - Tool execution request
   * @returns Promise resolving to execution result
   */
  executeTool(projectId: string, request: ExecuteToolRequest): Promise<ExecuteToolResponse>;

  /**
   * Restart project's sandbox
   * @param projectId - Project ID
   * @returns Promise resolving to action result
   */
  restartSandbox(projectId: string): Promise<SandboxActionResponse>;

  /**
   * Terminate project's sandbox
   * @param projectId - Project ID
   * @returns Promise resolving to action result
   */
  terminateSandbox(projectId: string): Promise<SandboxActionResponse>;

  /**
   * Sync sandbox status with database
   * @param projectId - Project ID
   * @returns Promise resolving to updated sandbox info
   */
  syncSandboxStatus(projectId: string): Promise<ProjectSandbox>;

  /**
   * Start desktop service for project
   * @param projectId - Project ID
   * @param resolution - Screen resolution (default: "1280x720")
   * @returns Promise resolving to desktop status
   */
  startDesktop(projectId: string, resolution?: string): Promise<DesktopStatus>;

  /**
   * Stop desktop service for project
   * @param projectId - Project ID
   * @returns Promise that resolves when stopped
   */
  stopDesktop(projectId: string): Promise<void>;

  /**
   * Start terminal service for project
   * @param projectId - Project ID
   * @returns Promise resolving to terminal status
   */
  startTerminal(projectId: string): Promise<TerminalStatus>;

  /**
   * Stop terminal service for project
   * @param projectId - Project ID
   * @returns Promise that resolves when stopped
   */
  stopTerminal(projectId: string): Promise<void>;
}

/**
 * Project sandbox service implementation
 *
 * Features:
 * - Request deduplication: concurrent requests for the same project share one API call
 * - Automatic retry on failure
 * - Logging for debugging
 */
class ProjectSandboxServiceImpl implements ProjectSandboxService {
  private readonly api = httpClient;

  /**
   * Pending ensureSandbox requests by project ID.
   * Used to deduplicate concurrent requests for the same project.
   */
  private pendingEnsureRequests: Map<string, Promise<ProjectSandbox>> = new Map();

  async getProjectSandbox(projectId: string): Promise<ProjectSandbox | null> {
    logger.debug(`[ProjectSandboxService] Getting sandbox for project: ${projectId}`);
    try {
      const response = await this.api.get<ProjectSandbox>(`/projects/${projectId}/sandbox`);
      return response;
    } catch (error: any) {
      if (error.status === 404) {
        return null;
      }
      throw error;
    }
  }

  async ensureSandbox(
    projectId: string,
    request: EnsureSandboxRequest = {}
  ): Promise<ProjectSandbox> {
    logger.debug(`[ProjectSandboxService] Ensuring sandbox for project: ${projectId}`);

    // Check if there's already a pending request for this project
    const pendingRequest = this.pendingEnsureRequests.get(projectId);
    if (pendingRequest) {
      logger.debug(`[ProjectSandboxService] Reusing pending request for project: ${projectId}`);
      return pendingRequest;
    }

    // Create new request and track it
    const requestPromise = this._doEnsureSandbox(projectId, request);
    this.pendingEnsureRequests.set(projectId, requestPromise);

    try {
      return await requestPromise;
    } finally {
      // Clean up after request completes (success or failure)
      this.pendingEnsureRequests.delete(projectId);
    }
  }

  /**
   * Internal method to actually call the API
   *
   * Uses extended timeout (60s) because sandbox creation can take a while
   * when Docker containers need to be started.
   */
  private async _doEnsureSandbox(
    projectId: string,
    request: EnsureSandboxRequest
  ): Promise<ProjectSandbox> {
    const response = await this.api.post<ProjectSandbox>(
      `/projects/${projectId}/sandbox`,
      {
        profile: request.profile,
        auto_create: request.auto_create ?? true,
      },
      {
        timeout: 60000, // 60 seconds for sandbox creation
      }
    );
    return response;
  }

  async healthCheck(projectId: string): Promise<HealthCheckResponse> {
    logger.debug(`[ProjectSandboxService] Health check for project: ${projectId}`);
    const response = await this.api.get<HealthCheckResponse>(
      `/projects/${projectId}/sandbox/health`
    );
    return response;
  }

  async getStats(projectId: string): Promise<SandboxStats> {
    logger.debug(`[ProjectSandboxService] Getting sandbox stats for project: ${projectId}`);
    const response = await this.api.get<SandboxStats>(`/projects/${projectId}/sandbox/stats`);
    return response;
  }

  async executeTool(projectId: string, request: ExecuteToolRequest): Promise<ExecuteToolResponse> {
    logger.debug(
      `[ProjectSandboxService] Executing tool ${request.tool_name} for project: ${projectId}`
    );
    const response = await this.api.post<ExecuteToolResponse>(
      `/projects/${projectId}/sandbox/execute`,
      {
        tool_name: request.tool_name,
        arguments: request.arguments,
        timeout: request.timeout ?? 30,
      }
    );
    return response;
  }

  async restartSandbox(projectId: string): Promise<SandboxActionResponse> {
    logger.debug(`[ProjectSandboxService] Restarting sandbox for project: ${projectId}`);
    const response = await this.api.post<SandboxActionResponse>(
      `/projects/${projectId}/sandbox/restart`
    );
    return response;
  }

  async terminateSandbox(projectId: string): Promise<SandboxActionResponse> {
    logger.debug(`[ProjectSandboxService] Terminating sandbox for project: ${projectId}`);
    const response = await this.api.delete<SandboxActionResponse>(`/projects/${projectId}/sandbox`);
    return response;
  }

  async syncSandboxStatus(projectId: string): Promise<ProjectSandbox> {
    logger.debug(`[ProjectSandboxService] Syncing sandbox status for project: ${projectId}`);
    const response = await this.api.get<ProjectSandbox>(`/projects/${projectId}/sandbox/sync`);
    return response;
  }

  async startDesktop(projectId: string, resolution = '1920x1080'): Promise<DesktopStatus> {
    logger.debug(`[ProjectSandboxService] Starting desktop for project: ${projectId}`);
    const response = await this.api.post<any>(
      `/projects/${projectId}/sandbox/desktop?resolution=${encodeURIComponent(resolution)}`,
      undefined,
      { timeout: 30000 } // 30 seconds for desktop service startup
    );

    // Build proxy URL with token for authentication
    // KasmVNC serves its own web client; proxy through API server
    const token = getAuthToken();
    const isRunning = response.success || response.running;
    const proxyUrl = isRunning
      ? `/api/v1/projects/${projectId}/sandbox/desktop/proxy/${token ? `?token=${encodeURIComponent(token)}` : ''}`
      : null;
    const wsUrl = isRunning ? buildDesktopWebSocketUrl(projectId, token || undefined) : null;

    return {
      running: response.success ?? response.running,
      url: proxyUrl,
      wsUrl,
      display: response.display || ':1',
      resolution: response.resolution || resolution,
      port: response.port || 0,
      audioEnabled: response.audio_enabled ?? false,
      dynamicResize: response.dynamic_resize ?? true,
      encoding: response.encoding ?? 'webp',
    };
  }

  async stopDesktop(projectId: string): Promise<void> {
    logger.debug(`[ProjectSandboxService] Stopping desktop for project: ${projectId}`);
    await this.api.delete(`/projects/${projectId}/sandbox/desktop`);
  }

  async startTerminal(projectId: string): Promise<TerminalStatus> {
    logger.debug(`[ProjectSandboxService] Starting terminal for project: ${projectId}`);
    const response = await this.api.post<any>(
      `/projects/${projectId}/sandbox/terminal`,
      undefined,
      { timeout: 30000 } // 30 seconds for terminal service startup
    );

    // Build WebSocket URL if session_id is provided
    let wsUrl = response.url;
    if (response.session_id && !wsUrl) {
      wsUrl = buildTerminalWebSocketUrl(response.sandbox_id, response.session_id);
    }

    return {
      running: response.success ?? response.running,
      url: wsUrl || null,
      port: response.port || 7681,
      sessionId: response.session_id || null,
      pid: response.pid || null,
    };
  }

  async stopTerminal(projectId: string): Promise<void> {
    logger.debug(`[ProjectSandboxService] Stopping terminal for project: ${projectId}`);
    await this.api.delete(`/projects/${projectId}/sandbox/terminal`);
  }
}

// Export singleton instance
export const projectSandboxService = new ProjectSandboxServiceImpl();

// Export interface for convenience
export type { ProjectSandboxService as ProjectSandboxServiceInterface };
