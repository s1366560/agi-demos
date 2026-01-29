/**
 * Sandbox SSE Service - Subscribe to sandbox events.
 *
 * Provides Server-Sent Events subscription for sandbox lifecycle
 * and service status events (desktop, terminal).
 *
 * Events are streamed from: GET /api/v1/sandbox/events/{project_id}
 */

import { logger } from "../utils/logger";
import { getAuthToken } from "../utils/tokenResolver";
import { createApiUrl } from "./client/urlUtils";

/**
 * Sandbox event types from backend
 */
export type SandboxEventType =
  | "sandbox_created"
  | "sandbox_terminated"
  | "sandbox_status"
  | "desktop_started"
  | "desktop_stopped"
  | "desktop_status"
  | "terminal_started"
  | "terminal_stopped"
  | "terminal_status";

/**
 * Sandbox SSE event format (from backend)
 */
export interface BaseSandboxSSEEvent {
  type: SandboxEventType;
  data: unknown;
  timestamp: string;
}

/**
 * Event handler for sandbox events
 */
export interface SandboxEventHandler {
  onSandboxCreated?: (event: BaseSandboxSSEEvent) => void;
  onSandboxTerminated?: (event: BaseSandboxSSEEvent) => void;
  onDesktopStarted?: (event: BaseSandboxSSEEvent) => void;
  onDesktopStopped?: (event: BaseSandboxSSEEvent) => void;
  onTerminalStarted?: (event: BaseSandboxSSEEvent) => void;
  onTerminalStopped?: (event: BaseSandboxSSEEvent) => void;
  onStatusUpdate?: (event: BaseSandboxSSEEvent) => void;
  onError?: (error: Error) => void;
}

/**
 * SSE connection status
 */
export type SSEStatus = "connecting" | "connected" | "disconnected" | "error";

/**
 * Sandbox SSE Service implementation
 *
 * Manages SSE connection to sandbox events endpoint.
 * Supports reconnection with exponential backoff.
 */
class SandboxSSEService {
  private eventSource: EventSource | null = null;
  private status: SSEStatus = "disconnected";
  private projectId: string | null = null;
  private handlers: Set<SandboxEventHandler> = new Set();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private lastEventId: string = "0";

  /**
   * Subscribe to sandbox events for a project.
   *
   * @param projectId - Project ID to subscribe to
   * @param handler - Event handler callback
   * @returns Unsubscribe function
   */
  subscribe(projectId: string, handler: SandboxEventHandler): () => void {
    this.projectId = projectId;
    this.handlers.add(handler);

    // Start connection if not already connected
    if (!this.eventSource || this.status === "disconnected") {
      this.connect();
    }

    // Return unsubscribe function
    return () => {
      this.handlers.delete(handler);
      if (this.handlers.size === 0) {
        this.disconnect();
      }
    };
  }

  /**
   * Establish SSE connection
   */
  private connect(): void {
    if (!this.projectId) {
      logger.warn("[SandboxSSE] No project_id set");
      return;
    }

    this.status = "connecting";
    const token = getAuthToken();

    // Build SSE URL
    const url = createApiUrl(`/sandbox/events/${this.projectId}`);
    let urlWithParams: string;

    try {
      const urlObj = new URL(url, window.location.origin);
      urlObj.searchParams.set("last_id", this.lastEventId);
      if (token) {
        urlObj.searchParams.set("token", token);
      }
      urlWithParams = urlObj.toString();
    } catch {
      // Fallback for environments without URL support (e.g., some test environments)
      const params = new URLSearchParams();
      params.set("last_id", this.lastEventId);
      if (token) {
        params.set("token", token);
      }
      const separator = url.includes("?") ? "&" : "?";
      urlWithParams = `${url}${separator}${params.toString()}`;
    }

    try {
      logger.debug(`[SandboxSSE] Connecting to ${urlWithParams}`);

      this.eventSource = new EventSource(urlWithParams);

      // Connection opened
      this.eventSource.onopen = () => {
        logger.debug(`[SandboxSSE] Connected to project ${this.projectId}`);
        this.status = "connected";
        this.reconnectAttempts = 0;
        this.reconnectDelay = 1000;
      };

      // Message received - route to appropriate handler
      this.eventSource.addEventListener("sandbox", (event) => {
        const message = event as MessageEvent;
        try {
          const data: BaseSandboxSSEEvent = JSON.parse(message.data);
          this.lastEventId = (event as any).lastEventId || this.lastEventId;
          this.routeEvent(data);
        } catch (err) {
          logger.error("[SandboxSSE] Failed to parse event:", err);
        }
      });

      // Error handling
      this.eventSource.onerror = (error) => {
        logger.error("[SandboxSSE] Connection error:", error);
        this.status = "error";

        // Close the EventSource before reconnecting
        if (this.eventSource) {
          this.eventSource.close();
        }

        // Schedule reconnection
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
          this.scheduleReconnect();
        } else {
          this.notifyHandlers(
            "onError",
            new Error("Max reconnection attempts reached")
          );
        }
      };

    } catch (err) {
      logger.error("[SandboxSSE] Failed to create EventSource:", err);
      this.status = "error";
      this.notifyHandlers("onError", err as Error);
    }
  }

  /**
   * Route event to appropriate handler based on event type.
   * Exposed as public for testing purposes.
   */
  routeEvent(event: BaseSandboxSSEEvent): void {
    const { type } = event;

    switch (type) {
      case "sandbox_created":
        this.notifyHandlers("onSandboxCreated", event);
        break;
      case "sandbox_terminated":
        this.notifyHandlers("onSandboxTerminated", event);
        break;
      case "desktop_started":
        this.notifyHandlers("onDesktopStarted", event);
        break;
      case "desktop_stopped":
        this.notifyHandlers("onDesktopStopped", event);
        break;
      case "terminal_started":
        this.notifyHandlers("onTerminalStarted", event);
        break;
      case "terminal_stopped":
        this.notifyHandlers("onTerminalStopped", event);
        break;
      case "sandbox_status":
      case "desktop_status":
      case "terminal_status":
        this.notifyHandlers("onStatusUpdate", event);
        break;
      default:
        logger.debug(`[SandboxSSE] Unknown event type: ${type}`);
    }
  }

  /**
   * Notify all handlers of an event
   */
  private notifyHandlers<K extends keyof SandboxEventHandler>(
    handlerKey: K,
    ...args: Parameters<NonNullable<SandboxEventHandler[K]>>
  ): void {
    this.handlers.forEach((handler) => {
      try {
        const fn = handler[handlerKey];
        if (typeof fn === "function") {
          (fn as any)(...args);
        }
      } catch (err) {
        logger.error(`[SandboxSSE] Handler error for ${handlerKey}:`, err);
      }
    });
  }

  /**
   * Schedule reconnection with exponential backoff
   */
  private scheduleReconnect(): void {
    if (this.reconnectTimeout) {
      return; // Already scheduled
    }

    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

    logger.debug(
      `[SandboxSSE] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`
    );

    this.reconnectTimeout = setTimeout(() => {
      this.reconnectTimeout = null;
      this.connect();
    }, delay);
  }

  /**
   * Disconnect from SSE stream
   */
  disconnect(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }

    this.status = "disconnected";
  }

  /**
   * Get current connection status
   */
  getStatus(): SSEStatus {
    return this.status;
  }
}

// Export singleton instance
export const sandboxSSEService = new SandboxSSEService();
