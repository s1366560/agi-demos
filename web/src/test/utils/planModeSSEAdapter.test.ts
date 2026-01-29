/**
 * Unit tests for planModeSSEAdapter utility.
 *
 * TDD RED Phase: Tests written first for Plan Mode SSE event handling.
 *
 * Feature: Convert Plan Mode SSE events to UI state updates.
 *
 * Events to handle:
 * - plan_mode_enter: User entered plan mode
 * - plan_mode_exit: User exited plan mode
 * - plan_created: New plan document created
 * - plan_updated: Plan document updated
 * - plan_execution_start: Execution plan started
 * - plan_step_complete: Execution step completed
 */

import { describe, it, expect } from "vitest";
import { planModeSSEAdapter } from "../../utils/planModeSSEAdapter";
import type { AgentEvent } from "../../types/agent";

// Helper to create test event with timestamp (not part of AgentEvent type)
function createTestEvent<T>(type: string, data: T): AgentEvent<T> {
  return {
    type: type as any,
    data,
  } as AgentEvent<T>;
}

describe("planModeSSEAdapter", () => {
  describe("plan_mode_enter event", () => {
    it("should return enter plan mode action with plan data", () => {
      const event: AgentEvent = {
        type: "plan_mode_enter",
        data: {
          conversation_id: "conv-1",
          plan_id: "plan-123",
          plan_title: "Test Plan",
        },
        // timestamp: "2024-01-01T00:00:00Z", // Removed: not part of AgentEvent type
      };

      const action = planModeSSEAdapter(event);

      expect(action).toEqual({
        type: "ENTER_PLAN_MODE",
        payload: {
          conversationId: "conv-1",
          planId: "plan-123",
          planTitle: "Test Plan",
        },
      });
    });

    it("should handle minimal plan_mode_enter event", () => {
      const event: AgentEvent = {
        type: "plan_mode_enter",
        data: {
          conversation_id: "conv-1",
          plan_id: "plan-123",
        },
        // timestamp: "2024-01-01T00:00:00Z", // Removed: not part of AgentEvent type
      };

      const action = planModeSSEAdapter(event);

      expect(action.type).toBe("ENTER_PLAN_MODE");
      expect(action.payload.conversationId).toBe("conv-1");
    });
  });

  describe("plan_mode_exit event", () => {
    it("should return exit plan mode action with status", () => {
      const event: AgentEvent = {
        type: "plan_mode_exit",
        data: {
          conversation_id: "conv-1",
          plan_id: "plan-123",
          plan_status: "approved",
          approved: true,
        },
        // timestamp: "2024-01-01T00:00:00Z", // Removed: not part of AgentEvent type
      };

      const action = planModeSSEAdapter(event);

      expect(action).toEqual({
        type: "EXIT_PLAN_MODE",
        payload: {
          conversationId: "conv-1",
          planId: "plan-123",
          planStatus: "approved",
          approved: true,
        },
      });
    });
  });

  describe("plan_created event", () => {
    it("should return load plan action", () => {
      const event: AgentEvent = {
        type: "plan_created",
        data: {
          plan_id: "plan-123",
          title: "New Plan",
          conversation_id: "conv-1",
        },
        // timestamp: "2024-01-01T00:00:00Z", // Removed: not part of AgentEvent type
      };

      const action = planModeSSEAdapter(event);

      expect(action).toEqual({
        type: "LOAD_PLAN",
        payload: {
          planId: "plan-123",
        },
      });
    });
  });

  describe("plan_updated event", () => {
    it("should return update plan action", () => {
      const event: AgentEvent = {
        type: "plan_updated",
        data: {
          plan_id: "plan-123",
          content: "Updated content",
          version: 2,
        },
        // timestamp: "2024-01-01T00:00:00Z", // Removed: not part of AgentEvent type
      };

      const action = planModeSSEAdapter(event);

      expect(action).toEqual({
        type: "UPDATE_PLAN",
        payload: {
          planId: "plan-123",
          content: "Updated content",
          version: 2,
        },
      });
    });
  });

  describe("plan_execution_start event", () => {
    it("should return execution start action", () => {
      const event: AgentEvent = {
        type: "plan_execution_start",
        data: {
          plan_id: "plan-123",
          total_steps: 5,
          user_query: "Test query",
        },
        // timestamp: "2024-01-01T00:00:00Z", // Removed: not part of AgentEvent type
      };

      const action = planModeSSEAdapter(event);

      expect(action).toEqual({
        type: "EXECUTION_START",
        payload: {
          planId: "plan-123",
          totalSteps: 5,
          userQuery: "Test query",
        },
      });
    });
  });

  describe("plan_step_complete event", () => {
    it("should return step complete action", () => {
      const event: AgentEvent = {
        type: "plan_step_complete",
        data: {
          plan_id: "plan-123",
          step_id: "step-1",
          status: "completed",
          result: "Step successful",
        },
        // timestamp: "2024-01-01T00:00:00Z", // Removed: not part of AgentEvent type
      };

      const action = planModeSSEAdapter(event);

      expect(action).toEqual({
        type: "STEP_COMPLETE",
        payload: {
          planId: "plan-123",
          stepId: "step-1",
          status: "completed",
          result: "Step successful",
        },
      });
    });
  });

  describe("reflection_complete event", () => {
    it("should return reflection complete action", () => {
      const event: AgentEvent = {
        type: "reflection_complete",
        data: {
          plan_id: "plan-123",
          assessment: "on_track",
          reasoning: "Everything looks good",
          has_adjustments: false,
          adjustment_count: 0,
        },
        // timestamp: "2024-01-01T00:00:00Z", // Removed: not part of AgentEvent type
      };

      const action = planModeSSEAdapter(event);

      expect(action).toEqual({
        type: "REFLECTION_COMPLETE",
        payload: {
          planId: "plan-123",
          assessment: "on_track",
          reasoning: "Everything looks good",
          hasAdjustments: false,
          adjustmentCount: 0,
        },
      });
    });
  });

  describe("Unknown event", () => {
    it("should return null for unknown event types", () => {
      const event: AgentEvent = {
        type: "unknown_event" as any,
        data: {},
        // timestamp: "2024-01-01T00:00:00Z", // Removed: not part of AgentEvent type
      };

      const action = planModeSSEAdapter(event);

      expect(action).toBeNull();
    });
  });

  describe("Event payload edge cases", () => {
    it("should handle null data gracefully", () => {
      const event: AgentEvent = {
        type: "plan_mode_enter",
        data: null as any,
        // timestamp: "2024-01-01T00:00:00Z", // Removed: not part of AgentEvent type
      };

      const action = planModeSSEAdapter(event);

      // Should still return action type with null payload
      expect(action?.type).toBe("ENTER_PLAN_MODE");
    });

    it("should handle missing optional fields", () => {
      const event: AgentEvent = {
        type: "plan_mode_exit",
        data: {
          conversation_id: "conv-1",
          plan_id: "plan-123",
        },
        // timestamp: "2024-01-01T00:00:00Z", // Removed: not part of AgentEvent type
      };

      const action = planModeSSEAdapter(event);

      expect(action).toEqual({
        type: "EXIT_PLAN_MODE",
        payload: {
          conversationId: "conv-1",
          planId: "plan-123",
          planStatus: undefined,
          approved: undefined,
        },
      });
    });
  });
});
