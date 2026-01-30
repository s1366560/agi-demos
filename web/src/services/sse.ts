/**
 * SSE Event Emitter
 *
 * Global event emitter for Server-Sent Events (SSE).
 * Used by hooks and components to listen to SSE events.
 *
 * @module services/sse
 */

import type { AgentEvent } from '../types/agent';

/**
 * Browser-compatible EventEmitter implementation
 */
class BrowserEventEmitter {
  private listeners: Map<string, Set<(...args: any[]) => void>> = new Map();
  private maxListeners: number = 10;

  setMaxListeners(n: number): void {
    this.maxListeners = n;
  }

  on(event: string, listener: (...args: any[]) => void): this {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    const eventListeners = this.listeners.get(event)!;
    
    if (eventListeners.size >= this.maxListeners) {
      console.warn(`MaxListenersExceededWarning: Possible memory leak. ${eventListeners.size + 1} listeners added for event "${event}". Use setMaxListeners() to increase limit.`);
    }
    
    eventListeners.add(listener);
    return this;
  }

  off(event: string, listener: (...args: any[]) => void): this {
    const eventListeners = this.listeners.get(event);
    if (eventListeners) {
      eventListeners.delete(listener);
    }
    return this;
  }

  emit(event: string, ...args: any[]): boolean {
    const eventListeners = this.listeners.get(event);
    if (!eventListeners || eventListeners.size === 0) {
      return false;
    }
    
    eventListeners.forEach(listener => {
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
 * Emits events received from SSE connections.
 * Components can register listeners for specific event types.
 */
class SSEEmitter extends BrowserEventEmitter {
  constructor() {
    super();
    // Increase max listeners to support multiple components
    this.setMaxListeners(100);
  }

  /**
   * Emit a plan mode event
   *
   * @param event - The SSE event to emit
   */
  emitPlanEvent(event: AgentEvent<unknown>): void {
    this.emit('plan_event', event);
  }

  /**
   * Register a listener for plan events
   *
   * @param listener - Callback function for plan events
   * @returns Function to remove the listener
   */
  onPlanEvent(listener: (event: AgentEvent<unknown>) => void): () => void {
    this.on('plan_event', listener);

    // Return cleanup function
    return () => {
      this.off('plan_event', listener);
    };
  }

  /**
   * Remove all listeners (useful for cleanup)
   */
  removeAllPlanListeners(): void {
    this.removeAllListeners('plan_event');
  }
}

/**
 * Global SSE emitter instance
 */
export const sseEmitter = new SSEEmitter();

/**
 * Type for plan mode event handlers
 */
export interface PlanModeEventHandlers {
  onPlanModeEntered?: (data: {
    conversation_id: string;
    plan_id: string;
    plan_title: string;
  }) => void;
  onPlanGenerated?: (data: {
    plan: any;
  }) => void;
  onStepUpdated?: (data: {
    step_id: string;
    step: any;
  }) => void;
  onReflectionComplete?: (data: {
    reflection: any;
  }) => void;
  onPlanAdjusted?: (data: {
    adjustments: any[];
  }) => void;
  onPlanCompleted?: (data: {
    plan_id: string;
    status: string;
  }) => void;
}

// Export AgentEvent for use in tests
export type { AgentEvent } from '../types/agent';
