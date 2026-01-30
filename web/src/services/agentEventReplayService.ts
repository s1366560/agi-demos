/**
 * Agent Event Replay Service
 *
 * This service handles replaying SSE events from the backend for:
 * - Reconnection after network issues
 * - Switching between active conversations
 * - Loading historical conversation state
 */

import { httpClient } from "./client/httpClient";
import type { AgentEventType, AgentStreamHandler } from "../types/agent";

// Use centralized HTTP client
const api = httpClient;

/**
 * Replay event response from backend
 */
interface ReplayEvent {
  type: AgentEventType;
  data: any;
  timestamp: string | null;
}

/**
 * Replay response from backend
 */
interface ReplayResponse {
  events: ReplayEvent[];
  has_more: boolean;
}

/**
 * Execution status response
 */
interface ExecutionStatusResponse {
  is_running: boolean;
  last_sequence: number;
  current_message_id: string | null;
  conversation_id: string;
}

/**
 * Agent Event Replay Service
 */
export class AgentEventReplayService {
  /**
   * Replay events for a conversation starting from a sequence number.
   *
   * This fetches events from the backend and applies them to the handler.
   *
   * @param conversationId - The conversation ID
   * @param handler - The stream handler to apply events to
   * @param fromSequence - Starting sequence number (default: 0)
   * @returns Promise resolving when replay is complete
   */
  async replayEvents(
    conversationId: string,
    handler: AgentStreamHandler,
    fromSequence = 0
  ): Promise<void> {
    let currentSequence = fromSequence;
    let hasMore = true;
    const batchSize = 100;

    try {
      while (hasMore) {
        const response = await api.get<ReplayResponse>(
          `/agent/conversations/${conversationId}/events`,
          {
            params: {
              from_sequence: currentSequence,
              limit: batchSize,
            },
          }
        );

        const { events, has_more: hasMoreEvents } = response;

        // Apply each event to the handler
        for (const event of events) {
          await this.applyEvent(handler, event);
          currentSequence = Math.max(
            currentSequence,
            (event as any).sequence_number + 1
          );
        }

        hasMore = hasMoreEvents;

        // Small delay between batches to avoid overwhelming the UI
        if (hasMore) {
          await new Promise((resolve) => setTimeout(resolve, 10));
        }
      }
    } catch (error) {
      console.error("Failed to replay events:", error);
      throw error;
    }
  }

  /**
   * Get the execution status of a conversation.
   *
   * @param conversationId - The conversation ID
   * @returns Promise resolving to execution status
   */
  async getExecutionStatus(
    conversationId: string
  ): Promise<ExecutionStatusResponse> {
    const response = await api.get<ExecutionStatusResponse>(
      `/agent/conversations/${conversationId}/execution-status`
    );
    return response;
  }

  /**
   * Apply a replayed event to the stream handler.
   *
   * @param handler - The stream handler
   * @param event - The event to apply
   */
  private async applyEvent(
    handler: AgentStreamHandler,
    event: ReplayEvent
  ): Promise<void> {
    const { type, data: _data } = event;

    switch (type as AgentEventType) {
      case "message":
        await handler.onMessage?.(event as any);
        break;
      case "thought":
        await handler.onThought?.(event as any);
        break;
      case "thought_delta":
        // Handle thought_delta using dedicated onThoughtDelta handler
        await handler.onThoughtDelta?.(event as any);
        break;
      case "work_plan":
        await handler.onWorkPlan?.(event as any);
        break;
      case "pattern_match":
        await handler.onPatternMatch?.(event as any);
        break;
      case "step_start":
        await handler.onStepStart?.(event as any);
        break;
      case "step_end":
        await handler.onStepEnd?.(event as any);
        break;
      case "act":
        await handler.onAct?.(event as any);
        break;
      case "observe":
        await handler.onObserve?.(event as any);
        break;
      case "text_start":
        await handler.onTextStart?.();
        break;
      case "text_delta":
        await handler.onTextDelta?.(event as any);
        break;
      case "text_end":
        await handler.onTextEnd?.(event as any);
        break;
      case "clarification_asked":
        await handler.onClarificationAsked?.(event as any);
        break;
      case "clarification_answered":
        await handler.onClarificationAnswered?.(event as any);
        break;
      case "decision_asked":
        await handler.onDecisionAsked?.(event as any);
        break;
      case "decision_answered":
        await handler.onDecisionAnswered?.(event as any);
        break;
      case "doom_loop_detected":
        await handler.onDoomLoopDetected?.(event as any);
        break;
      case "doom_loop_intervened":
        await handler.onDoomLoopIntervened?.(event as any);
        break;
      case "complete":
        await handler.onComplete?.(event as any);
        break;
      case "error":
        await handler.onError?.(event as any);
        break;
      // Skill execution events (L2 layer)
      case "skill_matched":
        await handler.onSkillMatched?.(event as any);
        break;
      case "skill_execution_start":
        await handler.onSkillExecutionStart?.(event as any);
        break;
      case "skill_tool_start":
        await handler.onSkillToolStart?.(event as any);
        break;
      case "skill_tool_result":
        await handler.onSkillToolResult?.(event as any);
        break;
      case "skill_execution_complete":
        await handler.onSkillExecutionComplete?.(event as any);
        break;
      case "skill_fallback":
        await handler.onSkillFallback?.(event as any);
        break;
      // Status events (no-op during replay, just for streaming status)
      case "start":
      case "status":
      case "cost_update":
      case "step_finish":
      case "retry":
      case "compact_needed":
      case "permission_asked":
      case "permission_replied":
      case "plan_mode_enter":
      case "plan_mode_exit":
      case "plan_created":
      case "plan_updated":
      case "plan_status_changed":
      case "tool_start":
      case "tool_result":
        // These events are informational during replay, no specific handler needed
        break;
      default:
        console.warn("Unknown event type during replay:", type);
    }
  }
}

// Export singleton instance
export const agentEventReplayService = new AgentEventReplayService();
