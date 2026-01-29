/**
 * usePlanMode Hook
 *
 * Custom hook that encapsulates planModeStore operations with convenient methods.
 * Provides a simplified interface for working with Plan Mode functionality.
 *
 * Features:
 * - Enter/exit plan mode
 * - Update plan content
 * - Get plan mode status
 * - Submit plan for review
 * - Derived state (isInPlanMode, currentMode, loading, error)
 *
 * @module hooks/usePlanMode
 */

import { useMemo } from "react";
import { usePlanModeStore } from "../stores/agent/planModeStore";
import type {
  EnterPlanModeRequest,
  ExitPlanModeRequest,
  PlanDocument,
  PlanModeStatus,
  UpdatePlanRequest,
} from "../types/agent";

/**
 * Return type for usePlanMode hook
 */
export interface UsePlanModeReturn {
  // State
  currentPlan: PlanDocument | null;
  isInPlanMode: boolean;
  currentMode: "build" | "plan" | "explore" | null;
  isLoading: boolean;
  error: string | null;

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
  updatePlan: (
    planId: string,
    request: UpdatePlanRequest
  ) => Promise<PlanDocument>;
  getPlanModeStatus: (conversationId: string) => Promise<PlanModeStatus>;
  submitPlanForReview: (planId: string) => Promise<PlanDocument>;

  // Utility methods
  clearPlanState: () => void;
  resetStore: () => void;
}

/**
 * Custom hook for working with Plan Mode
 *
 * Provides a simplified interface to planModeStore with automatic
 * state derivation and error handling.
 *
 * @example
 * ```tsx
 * const { enterPlanMode, exitPlanMode, isInPlanMode, currentPlan } = usePlanMode();
 *
 * const handleEnterPlanMode = async () => {
 *   try {
 *     await enterPlanMode(conversationId, "My Plan", "Description");
 *   } catch (error) {
 *     console.error("Failed to enter plan mode", error);
 *   }
 * };
 * ```
 */
export function usePlanMode(): UsePlanModeReturn {
  // Select individual store slices to avoid unnecessary re-renders
  const currentPlan = usePlanModeStore((state) => state.currentPlan);
  const planModeStatus = usePlanModeStore((state) => state.planModeStatus);
  const planLoading = usePlanModeStore((state) => state.planLoading);
  const planError = usePlanModeStore((state) => state.planError);

  // Actions from store
  const enterPlanMode = usePlanModeStore((state) => state.enterPlanMode);
  const exitPlanMode = usePlanModeStore((state) => state.exitPlanMode);
  const getPlan = usePlanModeStore((state) => state.getPlan);
  const updatePlan = usePlanModeStore((state) => state.updatePlan);
  const getPlanModeStatus = usePlanModeStore(
    (state) => state.getPlanModeStatus
  );
  const submitPlanForReview = usePlanModeStore(
    (state) => state.submitPlanForReview
  );
  const clearPlanState = usePlanModeStore((state) => state.clearPlanState);
  const reset = usePlanModeStore((state) => state.reset);

  // Derived state
  const isInPlanMode = useMemo(
    () => planModeStatus?.is_in_plan_mode ?? false,
    [planModeStatus?.is_in_plan_mode]
  );

  const currentMode = useMemo(
    () => planModeStatus?.current_mode ?? null,
    [planModeStatus?.current_mode]
  );

  return {
    // State
    currentPlan,
    isInPlanMode,
    currentMode,
    isLoading: planLoading,
    error: planError,

    // Actions
    enterPlanMode,
    exitPlanMode,
    updatePlan,
    getPlanModeStatus,
    submitPlanForReview,

    // Utility methods
    clearPlanState,
    resetStore: reset,
  };
}

export default usePlanMode;
