/**
 * SSE Event Emitter
 *
 * Global event emitter for Server-Sent Events (SSE).
 * Used by hooks and components to listen to SSE events.
 *
 * @module services/sse
 */

import { EventEmitter } from 'events';
import type { AgentEvent } from '../types/agent';

/**
 * SSE Event Emitter singleton
 *
 * Emits events received from SSE connections.
 * Components can register listeners for specific event types.
 */
class SSEEmitter extends EventEmitter {
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
