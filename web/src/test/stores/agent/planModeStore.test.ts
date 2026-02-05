/**
 * Unit tests for planModeStore.
 *
 * TDD RED Phase: Tests written first for Plan Mode store split.
 *
 * Feature: Split Plan Mode state from monolithic agent store.
 *
 * Plan Mode state includes:
 * - currentPlan: The active plan document
 * - planModeStatus: Current mode status (build/plan/explore)
 * - planLoading: Loading state for plan operations
 * - planError: Error state for plan operations
 *
 * Actions:
 * - enterPlanMode: Enter plan mode for a conversation
 * - exitPlanMode: Exit plan mode with optional approval
 * - getPlan: Fetch a plan by ID
 * - updatePlan: Update plan content
 * - getPlanModeStatus: Get current plan mode status
 * - clearPlanState: Clear all plan mode state
 * - reset: Reset to initial state
 *
 * These tests verify that the planModeStore maintains the same behavior
 * as the original monolithic agent store's Plan Mode functionality.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';

import { usePlanModeStore, initialState } from '../../../stores/agent/planModeStore';

import type { PlanDocument, PlanModeStatus } from '../../../types/agent';

// Mock planService
vi.mock('../../../services/planService', () => ({
  planService: {
    enterPlanMode: vi.fn(),
    exitPlanMode: vi.fn(),
    getPlan: vi.fn(),
    updatePlan: vi.fn(),
    getPlanModeStatus: vi.fn(),
  },
}));

import { planService } from '../../../services/planService';

describe('PlanModeStore', () => {
  beforeEach(() => {
    // Reset store before each test
    usePlanModeStore.getState().reset();
    vi.clearAllMocks();
  });

  describe('Initial State', () => {
    it('should have correct initial state', () => {
      const state = usePlanModeStore.getState();
      expect(state.currentPlan).toBe(initialState.currentPlan);
      expect(state.planModeStatus).toBe(initialState.planModeStatus);
      expect(state.planLoading).toBe(initialState.planLoading);
      expect(state.planError).toBe(initialState.planError);
    });

    it('should have null currentPlan initially', () => {
      const { currentPlan } = usePlanModeStore.getState();
      expect(currentPlan).toBeNull();
    });

    it('should have null planModeStatus initially', () => {
      const { planModeStatus } = usePlanModeStore.getState();
      expect(planModeStatus).toBeNull();
    });

    it('should have planLoading as false initially', () => {
      const { planLoading } = usePlanModeStore.getState();
      expect(planLoading).toBe(false);
    });

    it('should have planError as null initially', () => {
      const { planError } = usePlanModeStore.getState();
      expect(planError).toBeNull();
    });
  });

  describe('reset', () => {
    it('should reset state to initial values', async () => {
      const mockPlan: PlanDocument = {
        id: 'plan-1',
        conversation_id: 'conv-1',
        title: 'Test Plan',
        content: 'Test content',
        status: 'draft',
        version: 1,
        metadata: {},
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      } as PlanDocument;

      // Set some state via enterPlanMode
      vi.mocked(planService.enterPlanMode).mockResolvedValue(mockPlan);
      await usePlanModeStore.getState().enterPlanMode('conv-1', 'Test Plan', 'Test content');

      // Verify state is set
      expect(usePlanModeStore.getState().currentPlan).toEqual(mockPlan);

      // Reset
      usePlanModeStore.getState().reset();

      // Verify initial state restored
      const { currentPlan, planModeStatus, planLoading, planError } = usePlanModeStore.getState();
      expect(currentPlan).toBeNull();
      expect(planModeStatus).toBeNull();
      expect(planLoading).toBe(false);
      expect(planError).toBeNull();
    });
  });

  describe('clearPlanState', () => {
    it('should clear all plan-related state', async () => {
      const mockPlan: PlanDocument = {
        id: 'plan-1',
        conversation_id: 'conv-1',
        title: 'Test Plan',
        content: 'Test content',
        status: 'draft',
        version: 1,
        metadata: {},
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      } as PlanDocument;

      // Set some state
      vi.mocked(planService.enterPlanMode).mockResolvedValue(mockPlan);
      await usePlanModeStore.getState().enterPlanMode('conv-1', 'Test Plan', 'Test content');

      // Verify state is set
      expect(usePlanModeStore.getState().currentPlan).toBeDefined();

      // Clear state
      usePlanModeStore.getState().clearPlanState();

      // Verify cleared
      const { currentPlan, planModeStatus, planLoading, planError } = usePlanModeStore.getState();
      expect(currentPlan).toBeNull();
      expect(planModeStatus).toBeNull();
      expect(planLoading).toBe(false);
      expect(planError).toBeNull();
    });
  });

  describe('enterPlanMode', () => {
    const mockConversationId = 'conv-123';
    const mockTitle = 'Test Plan Title';
    const mockDescription = 'Test plan description';

    const mockPlan: PlanDocument = {
      id: 'plan-abc',
      conversation_id: mockConversationId,
      title: mockTitle,
      content: mockDescription,
      status: 'draft',
      version: 1,
      metadata: {},
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    };

    const expectedPlanModeStatus: PlanModeStatus = {
      is_in_plan_mode: true,
      current_mode: 'plan',
      current_plan_id: mockPlan.id,
      plan: mockPlan,
    };

    it('should enter plan mode successfully', async () => {
      vi.mocked(planService.enterPlanMode).mockResolvedValue(mockPlan);

      await usePlanModeStore.getState().enterPlanMode(
        mockConversationId,
        mockTitle,
        mockDescription
      );

      expect(planService.enterPlanMode).toHaveBeenCalledWith({
        conversation_id: mockConversationId,
        title: mockTitle,
        description: mockDescription,
      });

      const { currentPlan, planModeStatus, planLoading, planError } =
        usePlanModeStore.getState();
      expect(currentPlan).toEqual(mockPlan);
      expect(planModeStatus).toEqual(expectedPlanModeStatus);
      expect(planLoading).toBe(false);
      expect(planError).toBeNull();
    });

    it('should set loading to true before API call', async () => {
      let resolveApiCall: (value: PlanDocument) => void;
      const pendingPromise = new Promise<PlanDocument>((resolve) => {
        resolveApiCall = resolve;
      });
      vi.mocked(planService.enterPlanMode).mockReturnValue(pendingPromise);

      // Start the call (don't await)
      const callPromise = usePlanModeStore.getState().enterPlanMode(
        mockConversationId,
        mockTitle,
        mockDescription
      );

      // Check loading state
      expect(usePlanModeStore.getState().planLoading).toBe(true);

      // Resolve and finish
      resolveApiCall!(mockPlan);
      await callPromise;
    });

    it('should handle API errors gracefully', async () => {
      const mockError = {
        response: {
          data: {
            detail: 'Failed to enter plan mode',
          },
        },
      };
      vi.mocked(planService.enterPlanMode).mockRejectedValue(mockError);

      await expect(
        usePlanModeStore.getState().enterPlanMode(
          mockConversationId,
          mockTitle,
          mockDescription
        )
      ).rejects.toEqual(mockError);

      const { planLoading, planError, currentPlan, planModeStatus } =
        usePlanModeStore.getState();
      expect(planLoading).toBe(false);
      expect(planError).toBe('Failed to enter plan mode');
      expect(currentPlan).toBeNull();
      expect(planModeStatus).toBeNull();
    });

    it('should handle errors without response data', async () => {
      const mockError = new Error('Network error');
      vi.mocked(planService.enterPlanMode).mockRejectedValue(mockError);

      await expect(
        usePlanModeStore.getState().enterPlanMode(
          mockConversationId,
          mockTitle,
          mockDescription
        )
      ).rejects.toThrow();

      const { planError, planLoading } = usePlanModeStore.getState();
      expect(planLoading).toBe(false);
      expect(planError).toBe('Failed to enter Plan Mode');
    });

    it('should work without description parameter', async () => {
      vi.mocked(planService.enterPlanMode).mockResolvedValue(mockPlan);

      await usePlanModeStore.getState().enterPlanMode(
        mockConversationId,
        mockTitle
      );

      expect(planService.enterPlanMode).toHaveBeenCalledWith({
        conversation_id: mockConversationId,
        title: mockTitle,
        description: undefined,
      });
    });
  });

  describe('exitPlanMode', () => {
    const mockConversationId = 'conv-123';
    const mockPlanId = 'plan-abc';
    const mockApprove = true;
    const mockSummary = 'Plan summary';

    const mockPlan: PlanDocument = {
      id: mockPlanId,
      conversation_id: mockConversationId,
      title: 'Updated Plan',
      content: 'Updated content',
      status: 'approved',
      version: 2,
      metadata: {},
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T01:00:00Z',
    };

    const expectedPlanModeStatus: PlanModeStatus = {
      is_in_plan_mode: false,
      current_mode: 'build',
      current_plan_id: null,
      plan: null,
    };

    it('should exit plan mode successfully', async () => {
      vi.mocked(planService.exitPlanMode).mockResolvedValue(mockPlan);

      const result = await usePlanModeStore.getState().exitPlanMode(
        mockConversationId,
        mockPlanId,
        mockApprove,
        mockSummary
      );

      expect(planService.exitPlanMode).toHaveBeenCalledWith({
        conversation_id: mockConversationId,
        plan_id: mockPlanId,
        approve: mockApprove,
        summary: mockSummary,
      });
      expect(result).toEqual(mockPlan);

      const { currentPlan, planModeStatus, planLoading, planError } =
        usePlanModeStore.getState();
      expect(currentPlan).toEqual(mockPlan);
      expect(planModeStatus).toEqual(expectedPlanModeStatus);
      expect(planLoading).toBe(false);
      expect(planError).toBeNull();
    });

    it('should handle API errors when exiting plan mode', async () => {
      const mockError = {
        response: {
          data: {
            detail: 'Failed to exit plan mode',
          },
        },
      };
      vi.mocked(planService.exitPlanMode).mockRejectedValue(mockError);

      await expect(
        usePlanModeStore.getState().exitPlanMode(
          mockConversationId,
          mockPlanId,
          true
        )
      ).rejects.toEqual(mockError);

      const { planLoading, planError } = usePlanModeStore.getState();
      expect(planLoading).toBe(false);
      expect(planError).toBe('Failed to exit plan mode');
    });

    it('should use default approve=true when not specified', async () => {
      vi.mocked(planService.exitPlanMode).mockResolvedValue(mockPlan);

      await usePlanModeStore.getState().exitPlanMode(
        mockConversationId,
        mockPlanId
      );

      expect(planService.exitPlanMode).toHaveBeenCalledWith({
        conversation_id: mockConversationId,
        plan_id: mockPlanId,
        approve: true,
        summary: undefined,
      });
    });

    it('should work without summary parameter', async () => {
      vi.mocked(planService.exitPlanMode).mockResolvedValue(mockPlan);

      await usePlanModeStore.getState().exitPlanMode(
        mockConversationId,
        mockPlanId,
        true
      );

      expect(planService.exitPlanMode).toHaveBeenCalledWith({
        conversation_id: mockConversationId,
        plan_id: mockPlanId,
        approve: true,
        summary: undefined,
      });
    });
  });

  describe('getPlan', () => {
    const mockPlanId = 'plan-abc';

    const mockPlan: PlanDocument = {
      id: mockPlanId,
      conversation_id: 'conv-123',
      title: 'Existing Plan',
      content: 'Plan content',
      status: 'reviewing',
      version: 1,
      metadata: {},
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    };

    it('should fetch plan successfully', async () => {
      vi.mocked(planService.getPlan).mockResolvedValue(mockPlan);

      const result = await usePlanModeStore.getState().getPlan(mockPlanId);

      expect(planService.getPlan).toHaveBeenCalledWith(mockPlanId);
      expect(result).toEqual(mockPlan);

      const { currentPlan, planLoading, planError } = usePlanModeStore.getState();
      expect(currentPlan).toEqual(mockPlan);
      expect(planLoading).toBe(false);
      expect(planError).toBeNull();
    });

    it('should handle API errors when fetching plan', async () => {
      const mockError = {
        response: {
          data: {
            detail: 'Plan not found',
          },
        },
      };
      vi.mocked(planService.getPlan).mockRejectedValue(mockError);

      await expect(usePlanModeStore.getState().getPlan(mockPlanId)).rejects.toEqual(
        mockError
      );

      const { planLoading, planError } = usePlanModeStore.getState();
      expect(planLoading).toBe(false);
      expect(planError).toBe('Plan not found');
    });
  });

  describe('updatePlan', () => {
    const mockPlanId = 'plan-abc';
    const mockUpdateRequest = {
      content: 'Updated plan content',
      title: 'Updated Title',
    };

    const mockUpdatedPlan: PlanDocument = {
      id: mockPlanId,
      conversation_id: 'conv-123',
      title: 'Updated Title',
      content: 'Updated plan content',
      status: 'reviewing',
      version: 2,
      metadata: {},
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T01:00:00Z',
    };

    it('should update plan successfully', async () => {
      vi.mocked(planService.updatePlan).mockResolvedValue(mockUpdatedPlan);

      const result = await usePlanModeStore.getState().updatePlan(
        mockPlanId,
        mockUpdateRequest
      );

      expect(planService.updatePlan).toHaveBeenCalledWith(
        mockPlanId,
        mockUpdateRequest
      );
      expect(result).toEqual(mockUpdatedPlan);

      const { currentPlan, planLoading, planError } = usePlanModeStore.getState();
      expect(currentPlan).toEqual(mockUpdatedPlan);
      expect(planLoading).toBe(false);
      expect(planError).toBeNull();
    });

    it('should handle API errors when updating plan', async () => {
      const mockError = {
        response: {
          data: {
            detail: 'Failed to update plan',
          },
        },
      };
      vi.mocked(planService.updatePlan).mockRejectedValue(mockError);

      await expect(
        usePlanModeStore.getState().updatePlan(mockPlanId, mockUpdateRequest)
      ).rejects.toEqual(mockError);

      const { planLoading, planError } = usePlanModeStore.getState();
      expect(planLoading).toBe(false);
      expect(planError).toBe('Failed to update plan');
    });
  });

  describe('getPlanModeStatus', () => {
    const mockConversationId = 'conv-123';

    const mockStatus: PlanModeStatus = {
      is_in_plan_mode: true,
      current_mode: 'plan',
      current_plan_id: 'plan-abc',
      plan: null,
    };

    it('should fetch plan mode status successfully', async () => {
      vi.mocked(planService.getPlanModeStatus).mockResolvedValue(mockStatus);

      const result = await usePlanModeStore.getState().getPlanModeStatus(
        mockConversationId
      );

      expect(planService.getPlanModeStatus).toHaveBeenCalledWith(
        mockConversationId
      );
      expect(result).toEqual(mockStatus);

      const { planModeStatus, currentPlan, planLoading, planError } =
        usePlanModeStore.getState();
      expect(planModeStatus).toEqual(mockStatus);
      expect(currentPlan).toEqual(mockStatus.plan);
      expect(planLoading).toBe(false);
      expect(planError).toBeNull();
    });

    it('should handle API errors when fetching status', async () => {
      const mockError = {
        response: {
          data: {
            detail: 'Failed to get status',
          },
        },
      };
      vi.mocked(planService.getPlanModeStatus).mockRejectedValue(mockError);

      await expect(
        usePlanModeStore.getState().getPlanModeStatus(mockConversationId)
      ).rejects.toEqual(mockError);

      const { planLoading, planError } = usePlanModeStore.getState();
      expect(planLoading).toBe(false);
      expect(planError).toBe('Failed to get status');
    });
  });

  describe('Computed State', () => {
    it('should derive isInPlanMode from planModeStatus', () => {
      const state = usePlanModeStore.getState();

      // Not in plan mode initially
      expect(state.planModeStatus?.is_in_plan_mode ?? false).toBe(false);
    });
  });

  describe('State Isolation', () => {
    it('should maintain state isolation between store instances', () => {
      // Since usePlanModeStore is a singleton Zustand store,
      // we verify that reset properly clears state
      const { reset } = usePlanModeStore.getState();

      // Reset should return to initial state
      reset();

      const { currentPlan, planModeStatus, planLoading, planError } =
        usePlanModeStore.getState();
      expect(currentPlan).toBeNull();
      expect(planModeStatus).toBeNull();
      expect(planLoading).toBe(false);
      expect(planError).toBeNull();
    });
  });
});
