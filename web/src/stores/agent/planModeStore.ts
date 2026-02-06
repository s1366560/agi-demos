/**
 * Plan Mode Store - Split from monolithic agent store.
 *
 * This store manages Plan Mode state for agent conversations.
 * Plan Mode allows users to create and edit plan documents before
 * executing them with the agent.
 *
 * State managed:
 * - currentPlan: The active plan document
 * - planModeStatus: Current mode status (build/plan/explore)
 * - planLoading: Loading state for plan operations
 * - planError: Error state for plan operations
 *
 * This store was split from agent.ts to improve maintainability
 * and follow single-responsibility principle.
 *
 * Uses Zustand for state management, consistent with the main agent store.
 *
 * @module stores/agent/planModeStore
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

import { planService } from '../../services/planService';

import type {
  EnterPlanModeRequest,
  ExitPlanModeRequest,
  PlanDocument,
  PlanModeStatus,
  UpdatePlanRequest,
} from '../../types/agent';

/**
 * Plan Mode Store State
 */
interface PlanModeState {
  // State
  currentPlan: PlanDocument | null;
  planModeStatus: PlanModeStatus | null;
  planLoading: boolean;
  planError: string | null;

  // Actions
  enterPlanMode: (
    conversationId: string,
    title: string,
    description?: string
  ) => Promise<PlanDocument>;
  exitPlanMode: (
    conversationId: string,
    planId: string,
    approve?: boolean,
    summary?: string
  ) => Promise<PlanDocument>;
  getPlan: (planId: string) => Promise<PlanDocument>;
  updatePlan: (planId: string, request: UpdatePlanRequest) => Promise<PlanDocument>;
  getPlanModeStatus: (conversationId: string) => Promise<PlanModeStatus>;
  submitPlanForReview: (planId: string) => Promise<PlanDocument>;
  clearPlanState: () => void;
  reset: () => void;
}

/**
 * Initial state for Plan Mode store
 */
export const initialState = {
  currentPlan: null,
  planModeStatus: null,
  planLoading: false,
  planError: null,
};

/**
 * Plan Mode Store
 *
 * Zustand store for managing Plan Mode state.
 */
export const usePlanModeStore = create<PlanModeState>()(
  devtools(
    (set) => ({
      ...initialState,

      /**
       * Enter Plan Mode for a conversation
       *
       * Creates a new plan document and enters plan mode.
       *
       * @param conversationId - The conversation ID
       * @param title - Plan title
       * @param description - Optional plan description
       * @returns The created plan document
       */
      enterPlanMode: async (
        conversationId: string,
        title: string,
        description?: string
      ): Promise<PlanDocument> => {
        set({ planLoading: true, planError: null });

        try {
          const request: EnterPlanModeRequest = {
            conversation_id: conversationId,
            title,
            description,
          };
          const plan = await planService.enterPlanMode(request);

          set({
            currentPlan: plan,
            planModeStatus: {
              is_in_plan_mode: true,
              current_mode: 'plan',
              current_plan_id: plan.id,
              plan: plan,
            },
            planLoading: false,
          });

          return plan;
        } catch (error: unknown) {
          const err = error as { response?: { data?: { detail?: string } }; message?: string };
          set({
            planError: err?.response?.data?.detail || 'Failed to enter Plan Mode',
            planLoading: false,
          });
          throw error;
        }
      },

      /**
       * Exit Plan Mode
       *
       * Exits plan mode, optionally approving the plan.
       *
       * @param conversationId - The conversation ID
       * @param planId - The plan ID
       * @param approve - Whether to approve the plan (default: true)
       * @param summary - Optional summary
       * @returns The updated plan document
       */
      exitPlanMode: async (
        conversationId: string,
        planId: string,
        approve = true,
        summary?: string
      ): Promise<PlanDocument> => {
        set({ planLoading: true, planError: null });

        try {
          const request: ExitPlanModeRequest = {
            conversation_id: conversationId,
            plan_id: planId,
            approve,
            summary,
          };
          const plan = await planService.exitPlanMode(request);

          set({
            currentPlan: plan,
            planModeStatus: {
              is_in_plan_mode: false,
              current_mode: 'build',
              current_plan_id: null,
              plan: null,
            },
            planLoading: false,
          });

          return plan;
        } catch (error: unknown) {
          const err = error as { response?: { data?: { detail?: string } }; message?: string };
          set({
            planError: err?.response?.data?.detail || 'Failed to exit Plan Mode',
            planLoading: false,
          });
          throw error;
        }
      },

      /**
       * Get a plan by ID
       *
       * @param planId - The plan ID
       * @returns The plan document
       */
      getPlan: async (planId: string): Promise<PlanDocument> => {
        set({ planLoading: true, planError: null });

        try {
          const plan = await planService.getPlan(planId);
          set({ currentPlan: plan, planLoading: false });
          return plan;
        } catch (error: unknown) {
          const err = error as { response?: { data?: { detail?: string } }; message?: string };
          set({
            planError: err?.response?.data?.detail || 'Failed to get plan',
            planLoading: false,
          });
          throw error;
        }
      },

      /**
       * Update a plan
       *
       * @param planId - The plan ID
       * @param request - Update request
       * @returns The updated plan document
       */
      updatePlan: async (planId: string, request: UpdatePlanRequest): Promise<PlanDocument> => {
        set({ planLoading: true, planError: null });

        try {
          const plan = await planService.updatePlan(planId, request);
          set({ currentPlan: plan, planLoading: false });
          return plan;
        } catch (error: unknown) {
          const err = error as { response?: { data?: { detail?: string } }; message?: string };
          set({
            planError: err?.response?.data?.detail || 'Failed to update plan',
            planLoading: false,
          });
          throw error;
        }
      },

      /**
       * Get Plan Mode status for a conversation
       *
       * @param conversationId - The conversation ID
       * @returns The plan mode status
       */
      getPlanModeStatus: async (conversationId: string): Promise<PlanModeStatus> => {
        set({ planLoading: true, planError: null });

        try {
          const status = await planService.getPlanModeStatus(conversationId);
          set({
            planModeStatus: status,
            currentPlan: status.plan,
            planLoading: false,
          });
          return status;
        } catch (error: unknown) {
          const err = error as { response?: { data?: { detail?: string } }; message?: string };
          set({
            planError: err?.response?.data?.detail || 'Failed to get Plan Mode status',
            planLoading: false,
          });
          throw error;
        }
      },

      /**
       * Submit a plan for review
       *
       * Changes plan status from 'draft' to 'reviewing'.
       *
       * @param planId - The plan ID
       * @returns The updated plan document
       */
      submitPlanForReview: async (planId: string): Promise<PlanDocument> => {
        set({ planLoading: true, planError: null });

        try {
          const plan = await planService.submitPlanForReview(planId);
          set({ currentPlan: plan, planLoading: false });
          return plan;
        } catch (error: unknown) {
          const err = error as { response?: { data?: { detail?: string } }; message?: string };
          set({
            planError: err?.response?.data?.detail || 'Failed to submit plan for review',
            planLoading: false,
          });
          throw error;
        }
      },

      /**
       * Clear all Plan Mode state
       *
       * Resets plan-related state to initial values.
       */
      clearPlanState: (): void => {
        set({
          currentPlan: null,
          planModeStatus: null,
          planLoading: false,
          planError: null,
        });
      },

      /**
       * Reset store to initial state
       *
       * Completely resets all state in this store.
       */
      reset: (): void => {
        set(initialState);
      },
    }),
    {
      name: 'PlanModeStore',
      enabled: import.meta.env.DEV,
    }
  )
);

/**
 * Derived selector: Check if currently in plan mode
 *
 * @returns Boolean indicating if in plan mode
 */
export const useIsInPlanMode = () =>
  usePlanModeStore((state) => state.planModeStatus?.is_in_plan_mode ?? false);

/**
 * Type export for store (used in tests)
 */
export type PlanModeStore = ReturnType<typeof usePlanModeStore.getState>;
