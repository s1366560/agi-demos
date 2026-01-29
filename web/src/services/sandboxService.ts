/**
 * Sandbox Service - Sandbox container management API
 *
 * Provides methods for managing sandbox containers including:
 * - Creating and deleting sandboxes
 * - Starting/stopping desktop (noVNC) and terminal (ttyd) services
 * - Querying sandbox status
 *
 * @packageDocumentation
 */

import { httpClient } from "./client/httpClient";
import { logger } from "../utils/logger";

/**
 * Sandbox container status
 */
export type SandboxStatus = "creating" | "running" | "stopped" | "error";

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
    cpu?: string;      // e.g., "0.5" for 50% of one CPU
    memory?: string;   // e.g., "512m" for 512MB
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
   * @returns Promise that resolves when stopped
   * @throws {ApiError} If stop fails
   */
  stopTerminal(sandboxId: string): Promise<void>;

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
    return this.api.post<CreateSandboxResponse>("/sandbox", request);
  }

  async getSandbox(sandboxId: string): Promise<Sandbox> {
    logger.debug(`[SandboxService] Getting sandbox: ${sandboxId}`);
    return this.api.get<Sandbox>(`/sandbox/${sandboxId}`);
  }

  async listSandboxes(projectId: string): Promise<ListSandboxesResponse> {
    logger.debug(`[SandboxService] Listing sandboxes for project: ${projectId}`);
    return this.api.get<ListSandboxesResponse>("/sandbox", {
      params: { project_id: projectId },
    });
  }

  async deleteSandbox(sandboxId: string): Promise<void> {
    logger.debug(`[SandboxService] Deleting sandbox: ${sandboxId}`);
    await this.api.delete(`/sandbox/${sandboxId}`);
  }

  async startDesktop(sandboxId: string, resolution = "1280x720"): Promise<DesktopStatus> {
    logger.debug(`[SandboxService] Starting desktop for sandbox: ${sandboxId}`);
    return this.api.post<DesktopStatus>(`/sandbox/${sandboxId}/desktop`, {
      resolution,
    });
  }

  async stopDesktop(sandboxId: string): Promise<void> {
    logger.debug(`[SandboxService] Stopping desktop for sandbox: ${sandboxId}`);
    await this.api.delete(`/sandbox/${sandboxId}/desktop`);
  }

  async startTerminal(sandboxId: string): Promise<TerminalStatus> {
    logger.debug(`[SandboxService] Starting terminal for sandbox: ${sandboxId}`);
    return this.api.post<TerminalStatus>(`/sandbox/${sandboxId}/terminal`);
  }

  async stopTerminal(sandboxId: string): Promise<void> {
    logger.debug(`[SandboxService] Stopping terminal for sandbox: ${sandboxId}`);
    await this.api.delete(`/sandbox/${sandboxId}/terminal`);
  }

  async getDesktopStatus(sandboxId: string): Promise<DesktopStatus> {
    logger.debug(`[SandboxService] Getting desktop status for sandbox: ${sandboxId}`);
    return this.api.get<DesktopStatus>(`/sandbox/${sandboxId}/desktop`);
  }

  async getTerminalStatus(sandboxId: string): Promise<TerminalStatus> {
    logger.debug(`[SandboxService] Getting terminal status for sandbox: ${sandboxId}`);
    return this.api.get<TerminalStatus>(`/sandbox/${sandboxId}/terminal`);
  }
}

// Export singleton instance
export const sandboxService = new SandboxServiceImpl();

// Export interface for convenience
export type { SandboxService as SandboxServiceInterface };
