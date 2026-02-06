/**
 * Sandbox Service - Sandbox container management API (DEPRECATED)
 *
 * ⚠️ DEPRECATED: This service uses the old sandbox ID-based API.
 * Please use `projectSandboxService` from `./projectSandboxService` instead.
 *
 * The new API provides:
 * - Project-scoped sandbox management (one sandbox per project)
 * - Automatic health monitoring and recovery
 * - Simplified API (no need to manage sandbox IDs)
 *
 * Migration guide:
 * - Replace `sandboxService.createSandbox({project_id})` with `projectSandboxService.ensureSandbox(projectId)`
 * - Replace `sandboxService.startDesktop(sandboxId)` with `projectSandboxService.startDesktop(projectId)`
 * - Replace `sandboxService.startTerminal(sandboxId)` with `projectSandboxService.startTerminal(projectId)`
 *
 * @deprecated Use projectSandboxService instead
 * @packageDocumentation
 */

import { logger } from '../utils/logger';

import { httpClient } from './client/httpClient';
import {
  buildTerminalWebSocketUrl,
  buildDirectDesktopUrl,
  getApiHost,
} from './sandboxWebSocketUtils';

/**
 * Sandbox container status
 */
export type SandboxStatus = 'creating' | 'running' | 'stopped' | 'error';

/**
 * Sandbox container information
 */
export interface Sandbox {
  /** Unique sandbox identifier */
  id: string;
  /** Project this sandbox belongs to */
  project_id: string;
  /** Current status of the sandbox */
  status: SandboxStatus;
  /** ISO timestamp of creation */
  created_at: string;
  /** Docker container ID (if running) */
  container_id?: string;
  /** Container image used */
  image?: string;
  /** MCP WebSocket port on host */
  mcp_port?: number;
  /** Desktop (noVNC) port on host */
  desktop_port?: number;
  /** Terminal (ttyd) port on host */
  terminal_port?: number;
  /** Desktop (noVNC) URL */
  desktop_url?: string;
  /** Terminal (ttyd) URL */
  terminal_url?: string;
}

/**
 * Remote desktop status information
 */
export interface DesktopStatus {
  /** Whether desktop service is running */
  running: boolean;
  /** noVNC WebSocket URL (if running) */
  url: string | null;
  /** X11 display number (e.g., ":0") */
  display: string;
  /** Screen resolution (e.g., "1280x720") */
  resolution: string;
  /** noVNC port number */
  port: number;
}

/**
 * Terminal service status information
 */
export interface TerminalStatus {
  /** Whether terminal service is running */
  running: boolean;
  /** ttyd WebSocket URL (if running) */
  url: string | null;
  /** ttyd port number */
  port: number;
  /** Terminal session ID */
  sessionId: string | null;
  /** Process ID of ttyd */
  pid: number | null;
}

/**
 * Request to create a new sandbox
 */
export interface CreateSandboxRequest {
  /** Project ID to associate sandbox with */
  project_id: string;
  /** Optional custom image */
  image?: string;
  /** Optional resource limits */
  resources?: {
    cpu?: string; // e.g., "0.5" for 50% of one CPU
    memory?: string; // e.g., "512m" for 512MB
  };
}

/**
 * Response when creating a sandbox
 */
export interface CreateSandboxResponse {
  /** The created sandbox */
  sandbox: Sandbox;
  /** Initial access URLs (if services auto-started) */
  urls?: {
    desktop?: string;
    terminal?: string;
  };
}

/**
 * List sandboxes response
 */
export interface ListSandboxesResponse {
  /** Array of sandboxes */
  sandboxes: Sandbox[];
  /** Total count */
  total: number;
}

/**
 * Sandbox service interface
 */
export interface SandboxService {
  /**
   * Create a new sandbox for a project
   * @param request - Sandbox creation request
   * @returns Promise resolving to created sandbox
   * @throws {ApiError} If creation fails
   */
  createSandbox(request: CreateSandboxRequest): Promise<CreateSandboxResponse>;

  /**
   * Get sandbox information
   * @param sandboxId - Sandbox ID
   * @returns Promise resolving to sandbox info
   * @throws {ApiError} If sandbox not found (404) or other error
   */
  getSandbox(sandboxId: string): Promise<Sandbox>;

  /**
   * List sandboxes for a project
   * @param projectId - Project ID
   * @returns Promise resolving to list of sandboxes
   * @throws {ApiError} If request fails
   */
  listSandboxes(projectId: string): Promise<ListSandboxesResponse>;

  /**
   * Delete a sandbox
   * @param sandboxId - Sandbox ID to delete
   * @returns Promise that resolves when deleted
   * @throws {ApiError} If deletion fails
   */
  deleteSandbox(sandboxId: string): Promise<void>;

  /**
   * Start remote desktop service (noVNC)
   * @param sandboxId - Sandbox ID
   * @param resolution - Optional resolution (default: "1280x720")
   * @returns Promise resolving to desktop status
   * @throws {ApiError} If start fails
   */
  startDesktop(sandboxId: string, resolution?: string): Promise<DesktopStatus>;

  /**
   * Stop remote desktop service
   * @param sandboxId - Sandbox ID
   * @returns Promise that resolves when stopped
   * @throws {ApiError} If stop fails
   */
  stopDesktop(sandboxId: string): Promise<void>;

  /**
   * Start terminal service (ttyd)
   * @param sandboxId - Sandbox ID
   * @returns Promise resolving to terminal status
   * @throws {ApiError} If start fails
   */
  startTerminal(sandboxId: string): Promise<TerminalStatus>;

  /**
   * Stop terminal service
   * @param sandboxId - Sandbox ID
   * @param sessionId - Optional specific session ID to stop
   * @returns Promise that resolves when stopped
   * @throws {ApiError} If stop fails
   */
  stopTerminal(sandboxId: string, sessionId?: string): Promise<void>;

  /**
   * Get current desktop status
   * @param sandboxId - Sandbox ID
   * @returns Promise resolving to desktop status
   * @throws {ApiError} If request fails
   */
  getDesktopStatus(sandboxId: string): Promise<DesktopStatus>;

  /**
   * Get current terminal status
   * @param sandboxId - Sandbox ID
   * @returns Promise resolving to terminal status
   * @throws {ApiError} If request fails
   */
  getTerminalStatus(sandboxId: string): Promise<TerminalStatus>;
}

/**
 * Sandbox service implementation with HTTP client
 */
class SandboxServiceImpl implements SandboxService {
  private readonly api = httpClient;

  async createSandbox(request: CreateSandboxRequest): Promise<CreateSandboxResponse> {
    logger.debug(`[SandboxService] Creating sandbox for project: ${request.project_id}`);
    // Backend uses POST /sandbox/create
    const response = await this.api.post<any>('/sandbox/create', {
      project_path: `/tmp/memstack_${request.project_id}`,
      image: request.image,
      memory_limit: request.resources?.memory || '2g',
      cpu_limit: request.resources?.cpu || '2',
    });

    // Transform backend response to match frontend types
    return {
      sandbox: {
        id: response.id,
        project_id: request.project_id,
        status: response.status as SandboxStatus,
        created_at: response.created_at,
        container_id: response.id,
        image: response.tools?.join(','),
        mcp_port: response.mcp_port,
        desktop_port: response.desktop_port,
        terminal_port: response.terminal_port,
        desktop_url: response.desktop_url,
        terminal_url: response.terminal_url,
      },
      urls: {
        desktop: response.desktop_url || response.endpoint,
        terminal: response.terminal_url || response.websocket_url,
      },
    };
  }

  async getSandbox(sandboxId: string): Promise<Sandbox> {
    logger.debug(`[SandboxService] Getting sandbox: ${sandboxId}`);
    const response = await this.api.get<any>(`/sandbox/${sandboxId}`);

    // Extract project_id from project_path (format: /tmp/memstack_{project_id})
    const projectIdMatch = response.project_path?.match(/memstack_([a-zA-Z0-9_-]+)$/);
    const projectId = projectIdMatch ? projectIdMatch[1] : '';

    return {
      id: response.id,
      project_id: projectId,
      status: response.status as SandboxStatus,
      created_at: response.created_at,
      container_id: response.id,
      image: response.tools?.join(',') || response.image,
      mcp_port: response.mcp_port,
      desktop_port: response.desktop_port,
      terminal_port: response.terminal_port,
      desktop_url: response.desktop_url,
      terminal_url: response.terminal_url,
    };
  }

  async listSandboxes(projectId: string): Promise<ListSandboxesResponse> {
    logger.debug(`[SandboxService] Listing sandboxes for project: ${projectId}`);
    // Backend lists all sandboxes, we need to filter by project_id
    const response = await this.api.get<any>('/sandbox');

    // Filter sandboxes by project_id extracted from project_path
    const allSandboxes = response.sandboxes || [];
    const filteredSandboxes = allSandboxes.filter((sb: any) => {
      const projectIdMatch = sb.project_path?.match(/memstack_([a-zA-Z0-9_-]+)$/);
      return projectIdMatch && projectIdMatch[1] === projectId;
    });

    return {
      sandboxes: filteredSandboxes.map((sb: any) => ({
        id: sb.id,
        project_id: projectId,
        status: sb.status as SandboxStatus,
        created_at: sb.created_at,
        container_id: sb.id,
        image: sb.tools?.join(',') || sb.image,
        mcp_port: sb.mcp_port,
        desktop_port: sb.desktop_port,
        terminal_port: sb.terminal_port,
        desktop_url: sb.desktop_url,
        terminal_url: sb.terminal_url,
      })),
      total: filteredSandboxes.length,
    };
  }

  async deleteSandbox(sandboxId: string): Promise<void> {
    logger.debug(`[SandboxService] Deleting sandbox: ${sandboxId}`);
    await this.api.delete(`/sandbox/${sandboxId}`);
  }

  async startDesktop(sandboxId: string, resolution = '1280x720'): Promise<DesktopStatus> {
    logger.debug(`[SandboxService] Starting desktop for sandbox: ${sandboxId}`);
    // Backend uses POST /sandbox/{sandbox_id}/desktop
    const response = await this.api.post<any>(`/sandbox/${sandboxId}/desktop`, {
      resolution,
      display: ':1',
    });

    return {
      running: response.running,
      url: response.url,
      display: response.display,
      resolution: response.resolution,
      port: response.port,
    };
  }

  async stopDesktop(sandboxId: string): Promise<void> {
    logger.debug(`[SandboxService] Stopping desktop for sandbox: ${sandboxId}`);
    // Backend uses DELETE /sandbox/{sandbox_id}/desktop
    await this.api.delete(`/sandbox/${sandboxId}/desktop`);
  }

  async startTerminal(sandboxId: string): Promise<TerminalStatus> {
    logger.debug(`[SandboxService] Starting terminal for sandbox: ${sandboxId}`);
    // Backend uses /terminal/{sandbox_id}/create
    const response = await this.api.post<any>(`/terminal/${sandboxId}/create`, {
      shell: '/bin/bash',
      cols: 80,
      rows: 24,
    });

    // Backend returns: session_id, container_id, cols, rows, is_active
    // Construct WebSocket URL for terminal connection (dynamic)
    const wsUrl = buildTerminalWebSocketUrl(sandboxId, response.session_id);

    return {
      running: response.is_active,
      url: wsUrl,
      port: 8000, // WebSocket port is same as API
      sessionId: response.session_id,
      pid: null,
    };
  }

  async stopTerminal(sandboxId: string, sessionId?: string): Promise<void> {
    logger.debug(`[SandboxService] Stopping terminal for sandbox: ${sandboxId}`);

    if (sessionId) {
      // Close specific session
      await this.api.delete(`/terminal/${sandboxId}/sessions/${sessionId}`);
    } else {
      // Get active sessions and close them
      const sessions = await this.api.get<any>(`/terminal/${sandboxId}/sessions`);
      if (sessions && sessions.length > 0) {
        for (const session of sessions) {
          await this.api.delete(`/terminal/${sandboxId}/sessions/${session.session_id}`);
        }
      }
    }
  }

  async getDesktopStatus(sandboxId: string): Promise<DesktopStatus> {
    logger.debug(`[SandboxService] Getting desktop status for sandbox: ${sandboxId}`);
    // Backend uses GET /sandbox/{sandbox_id}/desktop
    const response = await this.api.get<any>(`/sandbox/${sandboxId}/desktop`);

    // Build direct URL if we have port info
    let desktopUrl = response.url;
    if (response.port && !desktopUrl) {
      const host = getApiHost().split(':')[0];
      desktopUrl = buildDirectDesktopUrl(host, response.port);
    }

    return {
      running: response.running,
      url: desktopUrl,
      display: response.display,
      resolution: response.resolution,
      port: response.port,
    };
  }

  async getTerminalStatus(sandboxId: string): Promise<TerminalStatus> {
    logger.debug(`[SandboxService] Getting terminal status for sandbox: ${sandboxId}`);
    // Backend returns array of sessions
    const sessions = await this.api.get<any>(`/terminal/${sandboxId}/sessions`);

    const hasActiveSession = sessions && sessions.length > 0;
    const activeSession = hasActiveSession ? sessions[0] : null;

    if (activeSession) {
      const wsUrl = buildTerminalWebSocketUrl(sandboxId, activeSession.session_id);
      return {
        running: activeSession.is_active,
        url: wsUrl,
        port: 8000,
        sessionId: activeSession.session_id,
        pid: null,
      };
    }

    return {
      running: false,
      url: null,
      port: 0,
      sessionId: null,
      pid: null,
    };
  }
}

// Export singleton instance
export const sandboxService = new SandboxServiceImpl();

// Export interface for convenience
export type { SandboxService as SandboxServiceInterface };
