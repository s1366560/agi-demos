/**
 * Sandbox SSE Service - Subscribe to sandbox events.
 *
 * **Migration Notice**: This service now uses WebSocket internally via
 * agentService. The SSE endpoint is deprecated. Previously used
 * unifiedEventService which created a duplicate WebSocket connection;
 * now shares the single agentService WebSocket.
 *
 * Provides subscription for sandbox lifecycle and service status events
 * (desktop, terminal).
 *
 * Events now come via WebSocket: subscribe_sandbox message type
 */

import { logger } from '../utils/logger';

import { agentService } from './agentService';

import type { SandboxStateData } from '../types/agent';

/**
 * Sandbox event types from backend
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
  onSandboxCreated?: ((event: BaseSandboxSSEEvent) => void) | undefined;
  onSandboxTerminated?: ((event: BaseSandboxSSEEvent) => void) | undefined;
  onDesktopStarted?: ((event: BaseSandboxSSEEvent) => void) | undefined;
  onDesktopStopped?: ((event: BaseSandboxSSEEvent) => void) | undefined;
  onTerminalStarted?: ((event: BaseSandboxSSEEvent) => void) | undefined;
  onTerminalStopped?: ((event: BaseSandboxSSEEvent) => void) | undefined;
  onStatusUpdate?: ((event: BaseSandboxSSEEvent) => void) | undefined;
  onError?: ((error: Error) => void) | undefined;
}

/**
 * SSE connection status
 */
export type SSEStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

/**
 * Sandbox SSE Service implementation
 *
 * **Updated**: Now uses WebSocket via agentService (shared connection).
 * The API remains the same for backward compatibility.
 */
class SandboxSSEService {
  private status: SSEStatus = 'disconnected';
  private projectId: string | null = null;
  private handlers: Set<SandboxEventHandler> = new Set();
  private unsubscribeFn: (() => void) | null = null;

  /**
   * Subscribe to sandbox events for a project.
   *
   * @param projectId - Project ID to subscribe to
   * @param handler - Event handler callback
   * @returns Unsubscribe function
   */
  subscribe(projectId: string, handler: SandboxEventHandler): () => void {
    // If switching projects, clean up old subscription first
    if (this.projectId && this.projectId !== projectId) {
      this.disconnect();
    }

    this.projectId = projectId;
    this.handlers.add(handler);

    // Start WebSocket connection if not already connected
    if (!this.unsubscribeFn) {
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
   * Establish WebSocket connection via agentService (shared connection)
   */
  private connect(): void {
    if (!this.projectId) {
      logger.warn('[SandboxWS] No project_id set');
      return;
    }

    this.status = 'connecting';
    const projectId = this.projectId;

    // Ensure agentService WebSocket is connected with timeout
    const connectPromise = agentService.isConnected() ? Promise.resolve() : agentService.connect();

    const timeoutPromise = new Promise<never>((_, reject) =>
      setTimeout(() => {
        reject(new Error('WebSocket connection timeout'));
      }, 15000)
    );

    Promise.race([connectPromise, timeoutPromise])
      .then(() => {
        // Guard: project may have changed during async connect
        if (this.projectId !== projectId) return;

        // Subscribe to sandbox events via agentService WebSocket
        agentService.subscribeSandboxState(projectId, '', (state: SandboxStateData) => {
          this.handleSandboxState(state);
        });

        // Track that we have an active subscription so we can clean up
        this.unsubscribeFn = () => {
          agentService.unsubscribeSandboxState();
        };

        this.status = 'connected';
        logger.debug(`[SandboxWS] Connected to project ${projectId} via agentService`);
      })
      .catch((err) => {
        logger.error('[SandboxWS] Failed to connect:', err);
        this.status = 'error';
        this.notifyHandlers('onError', err instanceof Error ? err : new Error(String(err)));
      });
  }

  /**
   * Handle incoming sandbox state change from agentService
   */
  private handleSandboxState(state: SandboxStateData): void {
    // Map SandboxStateData.eventType to SandboxEventType for routing
    const eventType = state.eventType as SandboxEventType;
    const sandboxEvent: BaseSandboxSSEEvent = {
      type: eventType,
      data: state,
      timestamp: new Date().toISOString(),
    };
    this.routeEvent(sandboxEvent);
  }

  /**
   * Route event to appropriate handler based on event type.
   * Exposed as public for testing purposes.
   */
  routeEvent(event: BaseSandboxSSEEvent): void {
    const { type } = event;

    switch (type) {
      case 'sandbox_created':
        this.notifyHandlers('onSandboxCreated', event);
        break;
      case 'sandbox_terminated':
        this.notifyHandlers('onSandboxTerminated', event);
        break;
      case 'desktop_started':
        this.notifyHandlers('onDesktopStarted', event);
        break;
      case 'desktop_stopped':
        this.notifyHandlers('onDesktopStopped', event);
        break;
      case 'terminal_started':
        this.notifyHandlers('onTerminalStarted', event);
        break;
      case 'terminal_stopped':
        this.notifyHandlers('onTerminalStopped', event);
        break;
      case 'sandbox_status':
      case 'desktop_status':
      case 'terminal_status':
        this.notifyHandlers('onStatusUpdate', event);
        break;
      default:
        logger.debug(`[SandboxWS] Unknown event type: ${type}`);
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
        if (typeof fn === 'function') {
          (fn as (...args: unknown[]) => void)(...args);
        }
      } catch (err) {
        logger.error(`[SandboxWS] Handler error for ${handlerKey}:`, err);
      }
    });
  }

  /**
   * Disconnect from WebSocket stream
   */
  disconnect(): void {
    if (this.unsubscribeFn) {
      this.unsubscribeFn();
      this.unsubscribeFn = null;
    }

    this.status = 'disconnected';
    this.projectId = null;
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
