/**
 * Unit tests for usePlanMode hook.
 *
 * TDD RED Phase: Tests written first for usePlanMode hook.
 *
 * Feature: Encapsulate planModeStore operations with convenient methods.
 *
 * Tests cover:
 * - Entering plan mode
 * - Exiting plan mode
 * - Updating plan
 * - Getting plan mode status
 * - Submitting plan for review
 * - Error handling
 * - Loading states
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { usePlanMode } from "../../hooks/usePlanMode";
import { usePlanModeStore } from "../../stores/agent/planModeStore";
import * as planService from "../../services/planService";

// Mock planService
vi.mock("../../services/planService", () => ({
  planService: {
    enterPlanMode: vi.fn(),
    exitPlanMode: vi.fn(),
    getPlan: vi.fn(),
    updatePlan: vi.fn(),
    getPlanModeStatus: vi.fn(),
    submitPlanForReview: vi.fn(),
  },
}));

describe("usePlanMode", () => {
  const mockConversationId = "conv-123";
  const mockPlanId = "plan-123";

  const mockPlanDocument = {
    id: mockPlanId,
    conversation_id: mockConversationId,
    title: "Test Plan",
    content: "Plan content",
    status: "draft" as const,
    version: 1,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    metadata: {},
  };

  const mockPlanModeStatus = {
    is_in_plan_mode: true,
    current_mode: "plan" as const,
    current_plan_id: mockPlanId,
    plan: mockPlanDocument,
  };

  beforeEach(() => {
    // Reset store state before each test
    usePlanModeStore.getState().reset();
    vi.clearAllMocks();
  });

  describe("enterPlanMode", () => {
    it("should enter plan mode successfully", async () => {
      vi.mocked(planService.planService.enterPlanMode).mockResolvedValue(
        mockPlanDocument
      );

      const { result } = renderHook(() => usePlanMode());

      await act(async () => {
        const plan = await result.current.enterPlanMode(
          mockConversationId,
          "Test Plan",
          "Test description"
        );

        expect(plan).toEqual(mockPlanDocument);
        expect(planService.planService.enterPlanMode).toHaveBeenCalledWith({
          conversation_id: mockConversationId,
          title: "Test Plan",
          description: "Test description",
        });
      });

      // Verify store state is updated
      const state = usePlanModeStore.getState();
      expect(state.currentPlan).toEqual(mockPlanDocument);
      expect(state.planModeStatus?.is_in_plan_mode).toBe(true);
    });

    it("should handle enterPlanMode errors gracefully", async () => {
      const mockError = new Error("Failed to enter plan mode");
      vi.mocked(planService.planService.enterPlanMode).mockRejectedValue(
        mockError
      );

      const { result } = renderHook(() => usePlanMode());

      await act(async () => {
        await expect(
          result.current.enterPlanMode(mockConversationId, "Test Plan")
        ).rejects.toThrow("Failed to enter plan mode");
      });

      // Verify error state
      const state = usePlanModeStore.getState();
      expect(state.planError).toBe("Failed to enter Plan Mode");
      expect(state.planLoading).toBe(false);
    });
  });

  describe("exitPlanMode", () => {
    it("should exit plan mode with approval", async () => {
      const approvedPlan = {
        ...mockPlanDocument,
        status: "approved" as const,
      };
      vi.mocked(planService.planService.exitPlanMode).mockResolvedValue(
        approvedPlan
      );

      const { result } = renderHook(() => usePlanMode());

      await act(async () => {
        const plan = await result.current.exitPlanMode(
          mockConversationId,
          mockPlanId,
          true,
          "Summary"
        );

        expect(plan).toEqual(approvedPlan);
        expect(planService.planService.exitPlanMode).toHaveBeenCalledWith({
          conversation_id: mockConversationId,
          plan_id: mockPlanId,
          approve: true,
          summary: "Summary",
        });
      });

      // Verify store state is updated
      const state = usePlanModeStore.getState();
      expect(state.planModeStatus?.is_in_plan_mode).toBe(false);
    });

    it("should exit plan mode without approval", async () => {
      const reviewingPlan = {
        ...mockPlanDocument,
        status: "reviewing" as const,
      };
      vi.mocked(planService.planService.exitPlanMode).mockResolvedValue(
        reviewingPlan
      );

      const { result } = renderHook(() => usePlanMode());

      await act(async () => {
        const plan = await result.current.exitPlanMode(
          mockConversationId,
          mockPlanId,
          false
        );

        expect(plan).toEqual(reviewingPlan);
        expect(planService.planService.exitPlanMode).toHaveBeenCalledWith({
          conversation_id: mockConversationId,
          plan_id: mockPlanId,
          approve: false,
        });
      });
    });
  });

  describe("updatePlan", () => {
    it("should update plan content", async () => {
      const updatedPlan = {
        ...mockPlanDocument,
        content: "Updated content",
        version: 2,
      };
      vi.mocked(planService.planService.updatePlan).mockResolvedValue(
        updatedPlan
      );

      const { result } = renderHook(() => usePlanMode());

      await act(async () => {
        const plan = await result.current.updatePlan(mockPlanId, {
          content: "Updated content",
        });

        expect(plan).toEqual(updatedPlan);
        expect(planService.planService.updatePlan).toHaveBeenCalledWith(
          mockPlanId,
          { content: "Updated content" }
        );
      });

      // Verify store state is updated
      const state = usePlanModeStore.getState();
      expect(state.currentPlan?.content).toBe("Updated content");
    });
  });

  describe("getPlanModeStatus", () => {
    it("should get plan mode status", async () => {
      vi.mocked(
        planService.planService.getPlanModeStatus
      ).mockResolvedValue(mockPlanModeStatus);

      const { result } = renderHook(() => usePlanMode());

      await act(async () => {
        const status = await result.current.getPlanModeStatus(
          mockConversationId
        );

        expect(status).toEqual(mockPlanModeStatus);
        expect(
          planService.planService.getPlanModeStatus
        ).toHaveBeenCalledWith(mockConversationId);
      });

      // Verify store state is updated
      const state = usePlanModeStore.getState();
      expect(state.planModeStatus).toEqual(mockPlanModeStatus);
    });
  });

  describe("submitPlanForReview", () => {
    it("should submit plan for review", async () => {
      const reviewingPlan = {
        ...mockPlanDocument,
        status: "reviewing" as const,
      };
      vi.mocked(
        planService.planService.submitPlanForReview
      ).mockResolvedValue(reviewingPlan);

      const { result } = renderHook(() => usePlanMode());

      await act(async () => {
        const plan = await result.current.submitPlanForReview(mockPlanId);

        expect(plan).toEqual(reviewingPlan);
        expect(
          planService.planService.submitPlanForReview
        ).toHaveBeenCalledWith(mockPlanId);
      });

      // Verify store state is updated
      const state = usePlanModeStore.getState();
      expect(state.currentPlan?.status).toBe("reviewing");
    });
  });

  describe("Derived state", () => {
    it("should provide isInPlanMode derived state", () => {
      const { result } = renderHook(() => usePlanMode());

      expect(result.current.isInPlanMode).toBe(false);

      act(() => {
        usePlanModeStore.setState({
          planModeStatus: { is_in_plan_mode: true, current_mode: "plan" },
        });
      });

      expect(result.current.isInPlanMode).toBe(true);
    });

    it("should provide currentMode derived state", () => {
      const { result } = renderHook(() => usePlanMode());

      expect(result.current.currentMode).toBeNull();

      act(() => {
        usePlanModeStore.setState({
          planModeStatus: { is_in_plan_mode: true, current_mode: "explore" },
        });
      });

      expect(result.current.currentMode).toBe("explore");
    });

    it("should provide loading state", () => {
      const { result } = renderHook(() => usePlanMode());

      expect(result.current.isLoading).toBe(false);

      act(() => {
        usePlanModeStore.setState({ planLoading: true });
      });

      expect(result.current.isLoading).toBe(true);
    });

    it("should provide error state", () => {
      const { result } = renderHook(() => usePlanMode());

      expect(result.current.error).toBeNull();

      act(() => {
        usePlanModeStore.setState({ planError: "Test error" });
      });

      expect(result.current.error).toBe("Test error");
    });

    it("should provide currentPlan derived state", () => {
      const { result } = renderHook(() => usePlanMode());

      expect(result.current.currentPlan).toBeNull();

      act(() => {
        usePlanModeStore.setState({ currentPlan: mockPlanDocument });
      });

      expect(result.current.currentPlan).toEqual(mockPlanDocument);
    });
  });

  describe("Utility methods", () => {
    it("should clear plan state", () => {
      const { result } = renderHook(() => usePlanMode());

      act(() => {
        usePlanModeStore.setState({
          currentPlan: mockPlanDocument,
          planModeStatus: mockPlanModeStatus,
        });
      });

      expect(result.current.currentPlan).toEqual(mockPlanDocument);

      act(() => {
        result.current.clearPlanState();
      });

      const state = usePlanModeStore.getState();
      expect(state.currentPlan).toBeNull();
      expect(state.planModeStatus).toBeNull();
    });

    it("should reset store", () => {
      const { result } = renderHook(() => usePlanMode());

      act(() => {
        usePlanModeStore.setState({
          currentPlan: mockPlanDocument,
          planModeStatus: mockPlanModeStatus,
          planError: "Error",
          planLoading: true,
        });
      });

      act(() => {
        result.current.resetStore();
      });

      const state = usePlanModeStore.getState();
      expect(state.currentPlan).toBeNull();
      expect(state.planModeStatus).toBeNull();
      expect(state.planError).toBeNull();
      expect(state.planLoading).toBe(false);
    });
  });
});
