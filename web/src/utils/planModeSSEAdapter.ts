/**
 * Plan Mode SSE Adapter
 *
 * Converts Plan Mode SSE events into standardized UI actions.
 *
 * This adapter transforms raw SSE events from the backend into
 * consistent action objects that can be consumed by stores and components.
 *
 * Events handled:
 * - plan_mode_enter: User entered plan mode
 * - plan_mode_exit: User exited plan mode
 * - plan_created: New plan document created
 * - plan_updated: Plan document updated
 * - plan_execution_start: Execution plan started
 * - plan_step_complete: Execution step completed
 * - reflection_complete: Reflection completed
 */

import type { AgentEvent } from '../types/agent';

/**
 * Plan Mode UI action types
 */
export type PlanModeAction =
  | { type: 'ENTER_PLAN_MODE'; payload: EnterPlanModePayload }
  | { type: 'EXIT_PLAN_MODE'; payload: ExitPlanModePayload }
  | { type: 'LOAD_PLAN'; payload: LoadPlanPayload }
  | { type: 'UPDATE_PLAN'; payload: UpdatePlanPayload }
  | { type: 'EXECUTION_START'; payload: ExecutionStartPayload }
  | { type: 'STEP_COMPLETE'; payload: StepCompletePayload }
  | { type: 'REFLECTION_COMPLETE'; payload: ReflectionCompletePayload }
  | { type: 'UNKNOWN'; payload: null };

/**
 * Enter plan mode payload
 */
export interface EnterPlanModePayload {
  conversationId: string;
  planId: string;
  planTitle?: string;
}

/**
 * Exit plan mode payload
 */
export interface ExitPlanModePayload {
  conversationId: string;
  planId: string;
  planStatus?: 'draft' | 'reviewing' | 'approved' | 'archived';
  approved?: boolean;
}

/**
 * Load plan payload
 */
export interface LoadPlanPayload {
  planId: string;
}

/**
 * Update plan payload
 */
export interface UpdatePlanPayload {
  planId: string;
  content?: string;
  version?: number;
  title?: string;
  exploredFiles?: string[];
  criticalFiles?: CriticalFile[];
}

/**
 * Critical file in plan
 */
export interface CriticalFile {
  path: string;
  type: 'create' | 'modify' | 'delete';
}

/**
 * Execution start payload
 */
export interface ExecutionStartPayload {
  planId: string;
  totalSteps: number;
  userQuery: string;
}

/**
 * Step complete payload
 */
export interface StepCompletePayload {
  planId: string;
  stepId: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'cancelled';
  result?: string;
  error?: string;
}

/**
 * Reflection complete payload
 */
export interface ReflectionCompletePayload {
  planId: string;
  assessment: 'on_track' | 'needs_adjustment' | 'off_track' | 'complete' | 'failed';
  reasoning: string;
  hasAdjustments: boolean;
  adjustmentCount: number;
}

/**
 * Convert Plan Mode SSE event to UI action
 *
 * @param event - Raw SSE event from backend
 * @returns Standardized UI action or null for unknown events
 */
export function planModeSSEAdapter(event: AgentEvent): PlanModeAction | null {
  if (!event) {
    return null;
  }

  switch (event.type) {
    case 'plan_mode_enter': {
      const data = (event.data || {}) as {
        conversation_id?: string;
        plan_id?: string;
        plan_title?: string;
      };
      return {
        type: 'ENTER_PLAN_MODE',
        payload: {
          conversationId: data.conversation_id || '',
          planId: data.plan_id || '',
          planTitle: data.plan_title,
        },
      };
    }

    case 'plan_mode_exit': {
      const data = (event.data || {}) as {
        conversation_id?: string;
        plan_id?: string;
        plan_status?: 'draft' | 'reviewing' | 'approved' | 'archived';
        approved?: boolean;
      };
      return {
        type: 'EXIT_PLAN_MODE',
        payload: {
          conversationId: data.conversation_id || '',
          planId: data.plan_id || '',
          planStatus: data.plan_status,
          approved: data.approved,
        },
      };
    }

    case 'plan_created': {
      const data = (event.data || {}) as {
        plan_id?: string;
        title?: string;
        conversation_id?: string;
      };
      return {
        type: 'LOAD_PLAN',
        payload: {
          planId: data.plan_id || '',
        },
      };
    }

    case 'plan_updated': {
      const data = (event.data || {}) as {
        plan_id?: string;
        content?: string;
        version?: number;
        title?: string;
      };
      return {
        type: 'UPDATE_PLAN',
        payload: {
          planId: data.plan_id || '',
          content: data.content,
          version: data.version,
          title: data.title,
        },
      };
    }

    case 'plan_execution_start': {
      const data = (event.data || {}) as {
        plan_id?: string;
        total_steps?: number;
        user_query?: string;
      };
      return {
        type: 'EXECUTION_START',
        payload: {
          planId: data.plan_id || '',
          totalSteps: data.total_steps || 0,
          userQuery: data.user_query || '',
        },
      };
    }

    case 'plan_step_complete': {
      const data = (event.data || {}) as {
        plan_id?: string;
        step_id?: string;
        status?: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'cancelled';
        result?: string;
        error?: string;
      };
      return {
        type: 'STEP_COMPLETE',
        payload: {
          planId: data.plan_id || '',
          stepId: data.step_id || '',
          status: data.status || 'pending',
          result: data.result,
          error: data.error,
        },
      };
    }

    case 'reflection_complete': {
      const data = (event.data || {}) as {
        plan_id?: string;
        assessment?: 'on_track' | 'needs_adjustment' | 'off_track' | 'complete' | 'failed';
        reasoning?: string;
        has_adjustments?: boolean;
        adjustment_count?: number;
      };
      return {
        type: 'REFLECTION_COMPLETE',
        payload: {
          planId: data.plan_id || '',
          assessment: data.assessment || 'on_track',
          reasoning: data.reasoning || '',
          hasAdjustments: data.has_adjustments || false,
          adjustmentCount: data.adjustment_count || 0,
        },
      };
    }

    default:
      return null;
  }
}

/**
 * Append Plan Mode SSE event to timeline
 *
 * This is a convenience function that combines the adapter with
 * timeline event creation for consistent event handling.
 *
 * @param timeline - Current timeline array
 * @param event - Raw SSE event
 * @returns Updated timeline with new event appended
 */
export function appendPlanModeEventToTimeline<
  T extends { type: string; timestamp?: number | string; eventTimeUs?: number; eventCounter?: number },
>(timeline: T[], event: AgentEvent): T[] {
  // Use current timestamp since AgentEvent doesn't include timestamp
  const timestamp = Date.now();
  const eventTimeUs = timestamp * 1000;
  const eventCounter = 0;

  // Create timeline event
  const timelineEvent = {
    id: `plan-${event.type}-${Date.now()}`,
    type: event.type as T extends { type: string } ? never : string,
    eventTimeUs,
    eventCounter,
    timestamp,
    ...event.data,
  };

  return [...timeline, timelineEvent] as T[];
}
