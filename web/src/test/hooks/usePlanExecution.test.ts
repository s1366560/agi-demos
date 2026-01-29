/**
 * Unit tests for usePlanExecution hook.
 *
 * TDD RED Phase: Tests written first for usePlanExecution hook.
 *
 * Feature: Monitor execution plan SSE events and maintain execution state.
 *
 * Tests cover:
 * - Subscribing to SSE events
 * - Updating execution state on events
 * - Providing progress information
 * - Handling execution completion
 * - Error handling
 * - Cleanup on unmount
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { usePlanExecution } from "../../hooks/usePlanExecution";
import * as agentV3 from "../../stores/agentV3";

// Mock agentV3 store
vi.mock("../../stores/agentV3", () => ({
  useAgentV3Store: vi.fn(),
}));

describe("usePlanExecution", () => {
  const mockExecutionPlan = {
    plan_id: "plan-123",
    user_query: "Test query",
    steps: [
      {
        step_id: "step-1",
        description: "First step",
        status: "pending" as const,
        tool_name: "read_file",
      },
      {
        step_id: "step-2",
        description: "Second step",
        status: "pending" as const,
        tool_name: "write_file",
      },
    ],
    status: "in_progress" as const,
    current_step_index: 0,
    created_at: "2024-01-01T00:00:00Z",
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe("Initial state", () => {
    it("should provide initial state with no execution plan", () => {
      vi.mocked(agentV3.useAgentV3Store).mockImplementation((selector) => {
        const state = {
          executionPlan: null,
          isStreaming: false,
        } as any;
        return selector ? selector(state) : state;
      });

      const { result } = renderHook(() => usePlanExecution());

      expect(result.current.executionPlan).toBeNull();
      expect(result.current.isExecuting).toBe(false);
      expect(result.current.progress).toEqual({
        total: 0,
        completed: 0,
        percentage: 0,
      });
    });

    it("should provide execution plan when available", () => {
      vi.mocked(agentV3.useAgentV3Store).mockImplementation((selector) => {
        const state = {
          executionPlan: mockExecutionPlan,
          isStreaming: true,
        } as any;
        return selector ? selector(state) : state;
      });

      const { result } = renderHook(() => usePlanExecution());

      expect(result.current.executionPlan).toEqual(mockExecutionPlan);
      expect(result.current.isExecuting).toBe(true);
    });
  });

  describe("Progress calculation", () => {
    it("should calculate progress correctly for pending steps", () => {
      vi.mocked(agentV3.useAgentV3Store).mockImplementation((selector) => {
        const state = {
          executionPlan: {
            ...mockExecutionPlan,
            steps: [
              { ...mockExecutionPlan.steps[0], status: "completed" as const },
              { ...mockExecutionPlan.steps[1], status: "pending" as const },
            ],
          },
        } as any;
        return selector ? selector(state) : state;
      });

      const { result } = renderHook(() => usePlanExecution());

      expect(result.current.progress).toEqual({
        total: 2,
        completed: 1,
        percentage: 50,
      });
    });

    it("should calculate 100% progress when all steps completed", () => {
      vi.mocked(agentV3.useAgentV3Store).mockImplementation((selector) => {
        const state = {
          executionPlan: {
            ...mockExecutionPlan,
            status: "completed" as const,
            steps: [
              { ...mockExecutionPlan.steps[0], status: "completed" as const },
              { ...mockExecutionPlan.steps[1], status: "completed" as const },
            ],
          },
        } as any;
        return selector ? selector(state) : state;
      });

      const { result } = renderHook(() => usePlanExecution());

      expect(result.current.progress).toEqual({
        total: 2,
        completed: 2,
        percentage: 100,
      });
    });

    it("should handle zero steps gracefully", () => {
      vi.mocked(agentV3.useAgentV3Store).mockImplementation((selector) => {
        const state = {
          executionPlan: {
            ...mockExecutionPlan,
            steps: [],
          },
        } as any;
        return selector ? selector(state) : state;
      });

      const { result } = renderHook(() => usePlanExecution());

      expect(result.current.progress).toEqual({
        total: 0,
        completed: 0,
        percentage: 0,
      });
    });
  });

  describe("Step status", () => {
    it("should provide current step", () => {
      vi.mocked(agentV3.useAgentV3Store).mockImplementation((selector) => {
        const state = {
          executionPlan: {
            ...mockExecutionPlan,
            current_step_index: 1,
            steps: [
              { ...mockExecutionPlan.steps[0], status: "completed" as const },
              { ...mockExecutionPlan.steps[1], status: "in_progress" as const },
            ],
          },
        } as any;
        return selector ? selector(state) : state;
      });

      const { result } = renderHook(() => usePlanExecution());

      expect(result.current.currentStep).toEqual({
        step_id: "step-2",
        description: "Second step",
        status: "in_progress",
        tool_name: "write_file",
      });
    });

    it("should return null for current step when not executing", () => {
      vi.mocked(agentV3.useAgentV3Store).mockImplementation((selector) => {
        const state = {
          executionPlan: null,
        } as any;
        return selector ? selector(state) : state;
      });

      const { result } = renderHook(() => usePlanExecution());

      expect(result.current.currentStep).toBeNull();
    });

    it("should categorize steps by status", () => {
      vi.mocked(agentV3.useAgentV3Store).mockImplementation((selector) => {
        const state = {
          executionPlan: {
            ...mockExecutionPlan,
            steps: [
              { ...mockExecutionPlan.steps[0], status: "completed" as const },
              { ...mockExecutionPlan.steps[1], status: "in_progress" as const },
              {
                step_id: "step-3",
                description: "Third step",
                status: "pending" as const,
                tool_name: "bash",
              },
              {
                step_id: "step-4",
                description: "Fourth step",
                status: "failed" as const,
                tool_name: "search",
              },
            ],
          },
        } as any;
        return selector ? selector(state) : state;
      });

      const { result } = renderHook(() => usePlanExecution());

      expect(result.current.completedSteps).toHaveLength(1);
      expect(result.current.completedSteps[0].step_id).toBe("step-1");

      expect(result.current.pendingSteps).toHaveLength(1);
      expect(result.current.pendingSteps[0].step_id).toBe("step-3");

      expect(result.current.failedSteps).toHaveLength(1);
      expect(result.current.failedSteps[0].step_id).toBe("step-4");

      expect(result.current.inProgressSteps).toHaveLength(1);
      expect(result.current.inProgressSteps[0].step_id).toBe("step-2");
    });
  });

  describe("Execution status", () => {
    it("should identify execution as in progress", () => {
      vi.mocked(agentV3.useAgentV3Store).mockImplementation((selector) => {
        const state = {
          executionPlan: {
            ...mockExecutionPlan,
            status: "in_progress" as const,
          },
        } as any;
        return selector ? selector(state) : state;
      });

      const { result } = renderHook(() => usePlanExecution());

      expect(result.current.isExecuting).toBe(true);
      expect(result.current.isCompleted).toBe(false);
      expect(result.current.isFailed).toBe(false);
    });

    it("should identify execution as completed", () => {
      vi.mocked(agentV3.useAgentV3Store).mockImplementation((selector) => {
        const state = {
          executionPlan: {
            ...mockExecutionPlan,
            status: "completed" as const,
          },
        } as any;
        return selector ? selector(state) : state;
      });

      const { result } = renderHook(() => usePlanExecution());

      expect(result.current.isExecuting).toBe(false);
      expect(result.current.isCompleted).toBe(true);
      expect(result.current.isFailed).toBe(false);
    });

    it("should identify execution as failed", () => {
      vi.mocked(agentV3.useAgentV3Store).mockImplementation((selector) => {
        const state = {
          executionPlan: {
            ...mockExecutionPlan,
            status: "failed" as const,
          },
        } as any;
        return selector ? selector(state) : state;
      });

      const { result } = renderHook(() => usePlanExecution());

      expect(result.current.isExecuting).toBe(false);
      expect(result.current.isCompleted).toBe(false);
      expect(result.current.isFailed).toBe(true);
    });
  });

  describe("hasStepAdjustments", () => {
    it("should return true when adjustments are available", () => {
      vi.mocked(agentV3.useAgentV3Store).mockImplementation((selector) => {
        const state = {
          executionPlan: {
            ...mockExecutionPlan,
            step_adjustments: [
              {
                step_id: "step-1",
                adjustment_type: "modify" as const,
                reason: "Needs correction",
              },
            ],
          },
        } as any;
        return selector ? selector(state) : state;
      });

      const { result } = renderHook(() => usePlanExecution());

      expect(result.current.hasStepAdjustments).toBe(true);
    });

    it("should return false when no adjustments", () => {
      vi.mocked(agentV3.useAgentV3Store).mockImplementation((selector) => {
        const state = {
          executionPlan: mockExecutionPlan,
        } as any;
        return selector ? selector(state) : state;
      });

      const { result } = renderHook(() => usePlanExecution());

      expect(result.current.hasStepAdjustments).toBe(false);
    });
  });
});
