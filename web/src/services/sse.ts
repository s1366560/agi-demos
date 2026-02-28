/**
 * SSE Event Emitter
 *
 * **DEPRECATED**: This module is deprecated. Plan mode events should be handled
 * directly through agentService WebSocket handlers instead of this global emitter.
 *
 * Migration:
 * - Instead of sseEmitter.onPlanEvent(), use agentService.subscribe() with
 *   plan mode callbacks (onPlanModeEnter, onPlanCreated, etc.)
 *
 * This emitter is kept for backward compatibility but will be removed in a future version.
 *
 * @deprecated Use agentService WebSocket handlers instead
 * @module services/sse
 */

import type { AgentEvent } from '../types/agent';

/**
 * Browser-compatible EventEmitter implementation
 * @deprecated
 */
class BrowserEventEmitter {
  private listeners: Map<string, Set<(...args: unknown[]) => void>> = new Map();
  private maxListeners: number = 10;

  setMaxListeners(n: number): void {
    this.maxListeners = n;
  }

  on(event: string, listener: (...args: unknown[]) => void): this {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    const eventListeners = this.listeners.get(event)!;

    if (eventListeners.size >= this.maxListeners) {
      console.warn(
        `MaxListenersExceededWarning: Possible memory leak. ${eventListeners.size + 1} listeners added for event "${event}". Use setMaxListeners() to increase limit.`
      );
    }

    eventListeners.add(listener);
    return this;
  }

  off(event: string, listener: (...args: unknown[]) => void): this {
    const eventListeners = this.listeners.get(event);
    if (eventListeners) {
      eventListeners.delete(listener);
    }
    return this;
  }

  emit(event: string, ...args: unknown[]): boolean {
    const eventListeners = this.listeners.get(event);
    if (!eventListeners || eventListeners.size === 0) {
      return false;
    }

    eventListeners.forEach((listener) => {
      try {
        listener(...args);
      } catch (error) {
        console.error('Error in event listener:', error);
      }
    });
    return true;
  }

  removeAllListeners(event?: string): this {
    if (event) {
      this.listeners.delete(event);
    } else {
      this.listeners.clear();
    }
    return this;
  }
}

/**
 * SSE Event Emitter singleton
 *
 * @deprecated Use agentService WebSocket handlers instead of this emitter.
 * Plan mode events (plan_mode_enter, plan_created, etc.) are now delivered
 * directly through the WebSocket connection.
 */
class SSEEmitter extends BrowserEventEmitter {
  constructor() {
    super();
    // Increase max listeners to support multiple components
    this.setMaxListeners(100);
    console.warn(
      '[SSEEmitter] DEPRECATED: sseEmitter is deprecated. Use agentService WebSocket handlers.'
    );
  }

  /**
   * Emit a plan mode event
   * @deprecated
   */
  emitPlanEvent(event: AgentEvent<unknown>): void {
    this.emit('plan_event', event);
  }

  /**
   * Register a listener for plan events
   * @deprecated Use agentService.subscribe() with plan mode handlers instead
   */
  onPlanEvent(listener: (event: AgentEvent<unknown>) => void): () => void {
    this.on('plan_event', listener as (...args: unknown[]) => void);

    // Return cleanup function
    return () => {
      this.off('plan_event', listener as (...args: unknown[]) => void);
    };
  }

  /**
   * Remove all listeners (useful for cleanup)
   * @deprecated
   */
  removeAllPlanListeners(): void {
    this.removeAllListeners('plan_event');
  }
}

/**
 * Global SSE emitter instance
 * @deprecated Use agentService WebSocket handlers instead
 */
export const sseEmitter = new SSEEmitter();

/**
 * Type for plan mode event handlers
 * @deprecated Use AgentStreamHandler from types/agent instead
 */
export interface PlanModeEventHandlers {
  onPlanModeEntered?:
    | ((data: { conversation_id: string; plan_id: string; plan_title: string }) => void)
    | undefined;
  onPlanGenerated?: ((data: { plan: unknown }) => void) | undefined;
  onStepUpdated?: ((data: { step_id: string; step: unknown }) => void) | undefined;
  onReflectionComplete?: ((data: { reflection: unknown }) => void) | undefined;
  onPlanAdjusted?: ((data: { adjustments: unknown[] }) => void) | undefined;
  onPlanCompleted?: ((data: { plan_id: string; status: string }) => void) | undefined;
}

// Export AgentEvent for use in tests
export type { AgentEvent } from '../types/agent';
