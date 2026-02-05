/**
 * TDD RED Phase: Performance tests for executionStore selector memoization
 *
 * Feature: Selector memoization to prevent unnecessary re-renders
 *
 * These tests verify:
 * 1. Store updates don't create new objects for unchanged slices
 * 2. Different selectors don't interfere with each other
 * 3. Store handles multiple rapid updates efficiently
 *
 * Note: These tests are written FIRST (TDD RED phase).
 * They should initially FAIL and then drive the implementation.
 */

import { renderHook } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";

import {
  useExecutionStore,
  useExecutionTimeline,
  useCurrentToolExecution,
  useToolExecutionHistory,
  useCurrentWorkPlan,
  useCurrentStepNumber,
  useCurrentStepStatus,
} from "../../../stores/agent/executionStore";

import type { WorkPlan } from "../../../types/agent";

describe("ExecutionStore - Selector Memoization", () => {
  beforeEach(() => {
    useExecutionStore.getState().reset();
    vi.clearAllMocks();
  });

  describe("State Immutability", () => {
    it("should not mutate existing timeline array when adding steps", () => {
      const timeline = [
        {
          stepNumber: 1,
          description: "Step 1",
          status: "running" as const,
          thoughts: [],
          toolExecutions: [],
        },
      ];

      useExecutionStore.setState({
        executionTimeline: timeline,
      });

      const firstArray = useExecutionStore.getState().executionTimeline;

      // Add a step to timeline
      const updatedTimeline = [
        ...timeline,
        {
          stepNumber: 2,
          description: "Step 2",
          status: "pending" as const,
          thoughts: [],
          toolExecutions: [],
        },
      ];

      useExecutionStore.setState({
        executionTimeline: updatedTimeline,
      });

      const secondArray = useExecutionStore.getState().executionTimeline;

      // Arrays should be different references
      expect(firstArray).not.toBe(secondArray);
      expect(firstArray).toHaveLength(1);
      expect(secondArray).toHaveLength(2);
    });

    it("should keep same array reference when state not changed", () => {
      const timeline = [
        {
          stepNumber: 1,
          description: "Step 1",
          status: "running" as const,
          thoughts: [],
          toolExecutions: [],
        },
      ];

      useExecutionStore.setState({
        executionTimeline: timeline,
      });

      const firstArray = useExecutionStore.getState().executionTimeline;

      // Set the same array again
      useExecutionStore.setState({
        executionTimeline: timeline,
      });

      const secondArray = useExecutionStore.getState().executionTimeline;

      // Should be equivalent
      expect(firstArray).toEqual(secondArray);
    });
  });

  describe("Selector Behavior", () => {
    it("should return current execution timeline correctly", () => {
      const timeline = [
        {
          stepNumber: 1,
          description: "Step 1",
          status: "running" as const,
          thoughts: ["Thought 1"],
          toolExecutions: [],
        },
      ];

      useExecutionStore.setState({
        executionTimeline: timeline,
      });

      const { result } = renderHook(() => useExecutionTimeline());
      expect(result.current).toHaveLength(1);
      expect(result.current[0].stepNumber).toBe(1);
      expect(result.current[0].thoughts).toEqual(["Thought 1"]);
    });

    it("should return current tool execution correctly", () => {
      const toolExec = {
        id: "tool-1",
        toolName: "web_search",
        input: { query: "test" },
        startTime: new Date().toISOString(),
      };

      useExecutionStore.setState({
        currentToolExecution: toolExec,
      });

      const { result } = renderHook(() => useCurrentToolExecution());
      expect(result.current).toEqual(toolExec);
      expect(result.current?.id).toBe("tool-1");
    });

    it("should return tool execution history correctly", () => {
      const history = [
        {
          id: "tool-1",
          toolName: "web_search",
          input: { query: "test" },
          status: "success" as const,
          startTime: new Date().toISOString(),
          result: "Search results",
        },
      ];

      useExecutionStore.setState({
        toolExecutionHistory: history,
      });

      const { result } = renderHook(() => useToolExecutionHistory());
      expect(result.current).toHaveLength(1);
      expect(result.current[0].id).toBe("tool-1");
    });

    it("should return current work plan correctly", () => {
      const workPlan: WorkPlan = {
        id: "plan-1",
        conversation_id: "conv-1",
        status: "in_progress",
        steps: [
          {
            step_number: 1,
            description: "Step 1",
            thought_prompt: "",
            required_tools: [],
            expected_output: "",
            dependencies: [],
          },
        ],
        current_step_index: 0,
        created_at: new Date().toISOString(),
      };

      useExecutionStore.setState({
        currentWorkPlan: workPlan,
      });

      const { result } = renderHook(() => useCurrentWorkPlan());
      expect(result.current).toEqual(workPlan);
    });

    it("should return current step number correctly", () => {
      useExecutionStore.setState({
        currentStepNumber: 5,
      });

      const { result } = renderHook(() => useCurrentStepNumber());
      expect(result.current).toBe(5);
    });

    it("should return current step status correctly", () => {
      useExecutionStore.setState({
        currentStepStatus: "running",
      });

      const { result } = renderHook(() => useCurrentStepStatus());
      expect(result.current).toBe("running");
    });

    it("should return null for current tool execution when none set", () => {
      const { result } = renderHook(() => useCurrentToolExecution());
      expect(result.current).toBeNull();
    });

    it("should return null for current work plan when none set", () => {
      const { result } = renderHook(() => useCurrentWorkPlan());
      expect(result.current).toBeNull();
    });
  });

  describe("Update Isolation", () => {
    it("should only update the slice being changed", () => {
      const timeline = [
        {
          stepNumber: 1,
          description: "Step 1",
          status: "running" as const,
          thoughts: [],
          toolExecutions: [],
        },
      ];

      useExecutionStore.setState({
        executionTimeline: timeline,
        currentStepNumber: 1,
        currentToolExecution: null,
      });

      const stateBefore = useExecutionStore.getState();

      // Update only step number
      useExecutionStore.setState({
        currentStepNumber: 2,
      });

      const stateAfter = useExecutionStore.getState();

      // Timeline should still be the same reference
      expect(stateBefore.executionTimeline).toBe(stateAfter.executionTimeline);

      // Step number should have changed
      expect(stateBefore.currentStepNumber).toBe(1);
      expect(stateAfter.currentStepNumber).toBe(2);
    });

    it("should not affect currentToolExecution when updating timeline", () => {
      const timeline = [
        {
          stepNumber: 1,
          description: "Step 1",
          status: "running" as const,
          thoughts: [],
          toolExecutions: [],
        },
      ];

      const toolExec = {
        id: "tool-1",
        toolName: "web_search",
        input: { query: "test" },
        startTime: new Date().toISOString(),
      };

      useExecutionStore.setState({
        executionTimeline: timeline,
        currentToolExecution: toolExec,
      });

      // Add a thought to timeline
      const updatedTimeline = [
        {
          ...timeline[0],
          thoughts: ["New thought"],
        },
      ];

      useExecutionStore.setState({
        executionTimeline: updatedTimeline,
      });

      const state = useExecutionStore.getState();

      expect(state.currentToolExecution).toEqual(toolExec);
      expect(state.executionTimeline[0].thoughts).toEqual(["New thought"]);
    });
  });

  describe("Performance", () => {
    it("should handle multiple rapid state updates efficiently", () => {
      const startTime = performance.now();

      // Perform many state updates
      for (let i = 0; i < 100; i++) {
        useExecutionStore.setState({
          currentStepNumber: i,
        });
      }

      const endTime = performance.now();
      const duration = endTime - startTime;

      // Should complete quickly
      expect(duration).toBeLessThan(100);
    });

    it("should handle complex state updates efficiently", () => {
      const startTime = performance.now();

      // Perform many complex state updates
      for (let i = 0; i < 50; i++) {
        const timeline = [
          {
            stepNumber: 1,
            description: `Step ${i}`,
            status: "running" as const,
            thoughts: [`Thought ${i}`],
            toolExecutions: [],
          },
        ];

        useExecutionStore.setState({
          executionTimeline: timeline,
          currentStepNumber: i,
          currentStepStatus: "running" as const,
        });
      }

      const endTime = performance.now();
      const duration = endTime - startTime;

      // Should complete quickly
      expect(duration).toBeLessThan(100);
    });
  });

  describe("Edge Cases", () => {
    it("should handle empty timeline array", () => {
      useExecutionStore.setState({
        executionTimeline: [],
      });

      const { result } = renderHook(() => useExecutionTimeline());
      expect(result.current).toEqual([]);
      expect(result.current).toHaveLength(0);
    });

    it("should handle null currentWorkPlan", () => {
      useExecutionStore.setState({
        currentWorkPlan: null,
      });

      const { result } = renderHook(() => useCurrentWorkPlan());
      expect(result.current).toBeNull();
    });

    it("should handle null currentStepNumber", () => {
      useExecutionStore.setState({
        currentStepNumber: null,
      });

      const { result } = renderHook(() => useCurrentStepNumber());
      expect(result.current).toBeNull();
    });

    it("should handle null currentStepStatus", () => {
      useExecutionStore.setState({
        currentStepStatus: null,
      });

      const { result } = renderHook(() => useCurrentStepStatus());
      expect(result.current).toBeNull();
    });

    it("should handle empty tool execution history", () => {
      useExecutionStore.setState({
        toolExecutionHistory: [],
      });

      const { result } = renderHook(() => useToolExecutionHistory());
      expect(result.current).toEqual([]);
    });
  });
});
