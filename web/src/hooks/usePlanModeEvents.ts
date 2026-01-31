/**
 * usePlanModeEvents Hook
 *
 * Handles Plan Mode SSE events for ExecutionPlanViewer.
 *
 * Manages:
 * - Reflection results from plan execution
 * - Plan adjustments applied during execution
 * - Real-time updates from SSE events
 *
 * @module hooks/usePlanModeEvents
 */

import { useEffect, useRef } from "react";
import type { AgentEvent } from "../types/agent";
import { sseEmitter, type PlanModeEventHandlers } from "../services/sse";

/**
 * Reflection result from plan execution
 */
export interface ReflectionResult {
  id: string;
  timestamp: string;
  cycle_number: number;
  summary: string;
  suggested_changes: string[];
  issues_found?: string[];
  confidence?: number;
}

/**
 * Plan adjustment applied during execution
 */
export interface PlanAdjustment {
  id: string;
  timestamp: string;
  type: "step_added" | "step_removed" | "step_modified" | "step_reordered";
  description: string;
  step_id?: string;
  previous_state?: unknown;
  new_state?: unknown;
}

/**
 * Hook for handling Plan Mode SSE events
 *
 * This hook connects to the SSE emitter and listens for plan mode events.
 * It calls the appropriate handlers when events are received.
 *
 * @param handlers - Event handlers for plan mode events
 *
 * @example
 * usePlanModeEvents({
 *   onPlanModeEntered: (data) => console.log('Plan mode entered', data),
 *   onPlanGenerated: (data) => console.log('Plan generated', data.plan),
 *   onStepUpdated: (data) => console.log('Step updated', data.step),
 *   onReflectionComplete: (data) => console.log('Reflection complete', data.reflection),
 *   onPlanAdjusted: (data) => console.log('Plan adjusted', data.adjustments),
 *   onPlanCompleted: (data) => console.log('Plan completed', data.status),
 * });
 */
export function usePlanModeEvents(handlers: PlanModeEventHandlers): void {
  // Use ref to store the latest handlers without causing re-renders
  const handlersRef = useRef(handlers);

  useEffect(() => {
    // Update ref inside effect to avoid accessing during render
    handlersRef.current = handlers;
    /**
     * Handle incoming plan mode events from SSE
     *
     * Routes events to the appropriate handler based on event type.
     */
    const handlePlanEvent = (event: AgentEvent<unknown>): void => {
      const currentHandlers = handlersRef.current;

      try {
        switch (event.type) {
          case "plan_mode_enter": {
            const data = event.data as {
              conversation_id: string;
              plan_id: string;
              plan_title: string;
            };
            currentHandlers.onPlanModeEntered?.(data);
            break;
          }

          case "plan_created": {
            const data = event.data as any;
            currentHandlers.onPlanGenerated?.({ plan: data });
            break;
          }

          case "plan_step_complete": {
            const data = event.data as {
              plan_id: string;
              step_id: string;
              status: string;
              result?: string;
              error?: string;
            };
            currentHandlers.onStepUpdated?.({
              step_id: data.step_id,
              step: {
                step_id: data.step_id,
                status: data.status,
                result: data.result,
                error: data.error,
              },
            });
            break;
          }

          case "reflection_complete": {
            const data = event.data as any;
            currentHandlers.onReflectionComplete?.({ reflection: data });
            break;
          }

          case "adjustment_applied": {
            const data = event.data as {
              plan_id: string;
              adjustment_count: number;
              adjustments: any[];
            };
            currentHandlers.onPlanAdjusted?.({ adjustments: data.adjustments });
            break;
          }

          case "plan_execution_complete": {
            const data = event.data as {
              plan_id: string;
              status: string;
              completed_steps: number;
              failed_steps: number;
            };
            currentHandlers.onPlanCompleted?.({
              plan_id: data.plan_id,
              status: data.status,
            });
            break;
          }

          default:
            // Ignore unknown event types
            break;
        }
      } catch (error) {
        // Log error but don't crash the hook
        console.error("[usePlanModeEvents] Error handling event:", error);
      }
    };

    // Register the event listener
    const cleanup = sseEmitter.onPlanEvent(handlePlanEvent);

    // Cleanup function: remove listener on unmount
    return () => {
      cleanup();
    };
  }, []); // Empty deps - only run on mount
}
