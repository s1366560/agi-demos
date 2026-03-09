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
  endpoint?: string | undefined;
  /** WebSocket URL */
  websocket_url?: string | undefined;
  /** MCP server port */
  mcp_port?: number | undefined;
  /** Desktop (noVNC) port */
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
 * Request to ensure project's sandbox exists
 */
export interface EnsureSandboxRequest {
  /** Optional profile: lite, standard, or full */
  profile?: string | undefined;
  /** Whether to auto-create if doesn't exist */
  auto_create?: boolean | undefined;
}

export interface GetProjectSandboxOptions {
  /** Force bypass cache and request deduplication */
  force?: boolean | undefined;
  /** Abort signal for request cancellation */
  signal?: AbortSignal | undefined;
  /** Optional override for cache TTL in milliseconds */
  cacheTtlMs?: number | undefined;
}

interface PendingSandboxRequest {
  promise: Promise<ProjectSandbox | null>;
  controller: AbortController;
  consumers: number;
  settled: boolean;
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
  timeout?: number | undefined;
}

/**
 * Tool execution response
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
  sandbox?: ProjectSandbox | undefined;
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
  disk_usage?: number | undefined;
  disk_limit?: number | undefined;
  disk_percent?: number | undefined;
  network_rx_bytes?: number | undefined;
  network_tx_bytes?: number | undefined;
  pids: number;
  uptime_seconds?: number | undefined;
  created_at?: string | undefined;
  collected_at: string;
}

/**
 * Desktop status
 */
export interface DesktopStatus {
  running: boolean;
  url: string | null;
  /** WebSocket URL for KasmVNC connection */
  wsUrl?: string | null | undefined;
  display: string;
  resolution: string;
  port: number;
  /** Whether audio streaming is enabled */
  audioEnabled?: boolean | undefined;
  /** Whether dynamic resize is supported */
  dynamicResize?: boolean | undefined;
  /** Image encoding format (webp/jpeg/qoi) */
  encoding?: string | undefined;
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

export type HttpServiceSourceType = 'sandbox_internal' | 'external_url';

export interface HttpServiceInfo {
  service_id: string;
  name: string;
  source_type: HttpServiceSourceType;
  status: 'running' | 'stopped' | 'error';
  service_url: string;
  preview_url: string;
  ws_preview_url?: string | null | undefined;
  sandbox_id?: string | null | undefined;
  auto_open: boolean;
  restart_token?: string | null | undefined;
  updated_at: string;
}

export interface RegisterHttpServiceRequest {
  service_id?: string | undefined;
  name: string;
  source_type: HttpServiceSourceType;
  internal_port?: number | undefined;
  internal_scheme?: 'http' | 'https' | undefined;
  path_prefix?: string | undefined;
  external_url?: string | undefined;
  auto_open?: boolean | undefined;
}

export interface ListHttpServicesResponse {
  services: HttpServiceInfo[];
  total: number;
}

export interface HttpServiceActionResponse {
  success: boolean;
  message: string;
  service?: HttpServiceInfo | undefined;
}

/**
 * Project sandbox service interface
 */
export interface ProjectSandboxService {
  /**
   * Get project's sandbox info
   * @param projectId - Project ID
   * @param options - Optional cache/cancellation options
   * @returns Promise resolving to sandbox info or null if not exists
   */
  getProjectSandbox(
    projectId: string,
    options?: GetProjectSandboxOptions
  ): Promise<ProjectSandbox | null>;

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

  /**
   * Register or update a sandbox HTTP service preview
   */
  registerHttpService(
    projectId: string,
    request: RegisterHttpServiceRequest
  ): Promise<HttpServiceInfo>;

  /**
   * List registered sandbox HTTP preview services
   */
  listHttpServices(projectId: string): Promise<ListHttpServicesResponse>;

  /**
   * Stop/unregister a sandbox HTTP preview service
   */
  stopHttpService(projectId: string, serviceId: string): Promise<HttpServiceActionResponse>;
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
  private static readonly SANDBOX_STATUS_CACHE_TTL_MS = 3000;

  /**
   * Pending ensureSandbox requests by project ID.
   * Used to deduplicate concurrent requests for the same project.
   */
  private pendingEnsureRequests: Map<string, Promise<ProjectSandbox>> = new Map();
  private pendingGetSandboxRequests: Map<string, PendingSandboxRequest> = new Map();
  private sandboxStatusCache: Map<string, { value: ProjectSandbox | null; fetchedAt: number }> =
    new Map();

  async getProjectSandbox(
    projectId: string,
    options: GetProjectSandboxOptions = {}
  ): Promise<ProjectSandbox | null> {
    const { force = false, signal, cacheTtlMs } = options;
    const ttlMs = cacheTtlMs ?? ProjectSandboxServiceImpl.SANDBOX_STATUS_CACHE_TTL_MS;
    const now = Date.now();

    if (!force) {
      const cached = this.sandboxStatusCache.get(projectId);
      if (cached && now - cached.fetchedAt < ttlMs) {
        return cached.value;
      }
    }

    if (!force) {
      const pendingRequest = this.pendingGetSandboxRequests.get(projectId);
      if (pendingRequest) {
        logger.debug(
          `[ProjectSandboxService] Reusing pending getSandbox for project: ${projectId}`
        );
        const result = await this.consumePendingSandboxRequest(projectId, pendingRequest, signal);
        this.sandboxStatusCache.set(projectId, { value: result, fetchedAt: Date.now() });
        return result;
      }

      const controller = new AbortController();
      const nextPendingRequest: PendingSandboxRequest = {
        controller,
        consumers: 0,
        settled: false,
        promise: this._doGetProjectSandbox(projectId, controller.signal).finally(() => {
          nextPendingRequest.settled = true;
          const currentPending = this.pendingGetSandboxRequests.get(projectId);
          if (currentPending === nextPendingRequest) {
            this.pendingGetSandboxRequests.delete(projectId);
          }
        }),
      };
      this.pendingGetSandboxRequests.set(projectId, nextPendingRequest);
      const result = await this.consumePendingSandboxRequest(projectId, nextPendingRequest, signal);
      this.sandboxStatusCache.set(projectId, { value: result, fetchedAt: Date.now() });
      return result;
    }

    const result = await this._doGetProjectSandbox(projectId, signal);
    this.sandboxStatusCache.set(projectId, { value: result, fetchedAt: Date.now() });
    return result;
  }

  private consumePendingSandboxRequest(
    projectId: string,
    pendingRequest: PendingSandboxRequest,
    signal?: AbortSignal
  ): Promise<ProjectSandbox | null> {
    pendingRequest.consumers += 1;
    let released = false;
    const releaseConsumer = () => {
      if (released) {
        return;
      }
      released = true;
      pendingRequest.consumers = Math.max(0, pendingRequest.consumers - 1);
      if (pendingRequest.consumers === 0 && !pendingRequest.settled) {
        pendingRequest.controller.abort();
        const currentPending = this.pendingGetSandboxRequests.get(projectId);
        if (currentPending === pendingRequest) {
          this.pendingGetSandboxRequests.delete(projectId);
        }
      }
    };

    if (signal?.aborted) {
      releaseConsumer();
      return Promise.reject(this.createCanceledError());
    }

    return new Promise<ProjectSandbox | null>((resolve, reject) => {
      const onAbort = () => {
        cleanupAbortListener();
        releaseConsumer();
        reject(this.createCanceledError());
      };

      const cleanupAbortListener = () => {
        if (signal) {
          signal.removeEventListener('abort', onAbort);
        }
      };

      if (signal) {
        signal.addEventListener('abort', onAbort, { once: true });
      }

      pendingRequest.promise.then(
        (value) => {
          cleanupAbortListener();
          releaseConsumer();
          resolve(value);
        },
        (error) => {
          cleanupAbortListener();
          releaseConsumer();
          reject(error);
        }
      );
    });
  }

  private createCanceledError(): Error & { code: string } {
    const error = new Error('Request canceled') as Error & { code: string };
    error.name = 'CanceledError';
    error.code = 'ERR_CANCELED';
    return error;
  }

  private async _doGetProjectSandbox(
    projectId: string,
    signal?: AbortSignal
  ): Promise<ProjectSandbox | null> {
    logger.debug(`[ProjectSandboxService] Getting sandbox for project: ${projectId}`);
    try {
      const requestConfig = signal ? { signal } : undefined;
      const response = await this.api.get<ProjectSandbox>(
        `/projects/${projectId}/sandbox`,
        requestConfig
      );
      return response;
    } catch (error: unknown) {
      const typedError = error as { status?: number | undefined; statusCode?: number | undefined };
      if (typedError.status === 404 || typedError.statusCode === 404) {
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
      const sandbox = await requestPromise;
      this.sandboxStatusCache.set(projectId, { value: sandbox, fetchedAt: Date.now() });
      return sandbox;
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
    const timeoutMs = (request.timeout ?? 30) * 1000 + 10000; // tool timeout + 10s buffer
    const response = await this.api.post<ExecuteToolResponse>(
      `/projects/${projectId}/sandbox/execute`,
      {
        tool_name: request.tool_name,
        arguments: request.arguments,
        timeout: request.timeout ?? 30,
      },
      { timeout: timeoutMs }
    );
    return response;
  }

  async restartSandbox(projectId: string): Promise<SandboxActionResponse> {
    logger.debug(`[ProjectSandboxService] Restarting sandbox for project: ${projectId}`);
    const response = await this.api.post<SandboxActionResponse>(
      `/projects/${projectId}/sandbox/restart`
    );
    if (response.sandbox) {
      this.sandboxStatusCache.set(projectId, { value: response.sandbox, fetchedAt: Date.now() });
    } else {
      this.sandboxStatusCache.delete(projectId);
    }
    return response;
  }

  async terminateSandbox(projectId: string): Promise<SandboxActionResponse> {
    logger.debug(`[ProjectSandboxService] Terminating sandbox for project: ${projectId}`);
    const response = await this.api.delete<SandboxActionResponse>(`/projects/${projectId}/sandbox`);
    this.sandboxStatusCache.set(projectId, { value: null, fetchedAt: Date.now() });
    return response;
  }

  async syncSandboxStatus(projectId: string): Promise<ProjectSandbox> {
    logger.debug(`[ProjectSandboxService] Syncing sandbox status for project: ${projectId}`);
    const response = await this.api.get<ProjectSandbox>(`/projects/${projectId}/sandbox/sync`);
    this.sandboxStatusCache.set(projectId, { value: response, fetchedAt: Date.now() });
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

  async registerHttpService(
    projectId: string,
    request: RegisterHttpServiceRequest
  ): Promise<HttpServiceInfo> {
    logger.debug(
      `[ProjectSandboxService] Registering HTTP service ${request.name} for project: ${projectId}`
    );
    const response = await this.api.post<HttpServiceInfo>(
      `/projects/${projectId}/sandbox/http-services`,
      request
    );
    return response;
  }

  async listHttpServices(projectId: string): Promise<ListHttpServicesResponse> {
    logger.debug(`[ProjectSandboxService] Listing HTTP services for project: ${projectId}`);
    return this.api.get<ListHttpServicesResponse>(`/projects/${projectId}/sandbox/http-services`);
  }

  async stopHttpService(projectId: string, serviceId: string): Promise<HttpServiceActionResponse> {
    logger.debug(
      `[ProjectSandboxService] Stopping HTTP service ${serviceId} for project: ${projectId}`
    );
    return this.api.delete<HttpServiceActionResponse>(
      `/projects/${projectId}/sandbox/http-services/${encodeURIComponent(serviceId)}`
    );
  }
}

// Export singleton instance
export const projectSandboxService = new ProjectSandboxServiceImpl();

// Export interface for convenience
export type { ProjectSandboxService as ProjectSandboxServiceInterface };
