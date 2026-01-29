/**
 * usePlanExecution Hook
 *
 * Custom hook that monitors execution plan SSE events and maintains execution state.
 * Provides progress information and step status tracking for plan execution.
 *
 * Features:
 * - Subscribe to execution plan state from agentV3 store
 * - Calculate progress (completed/total steps)
 * - Categorize steps by status (completed, pending, in progress, failed)
 * - Track current executing step
 * - Check for step adjustments from reflection
 *
 * @module hooks/usePlanExecution
 */

import { useMemo } from "react";
import { useAgentV3Store } from "../stores/agentV3";
import type { ExecutionPlan, ExecutionStep } from "../types/agent";

/**
 * Progress information for plan execution
 */
export interface ExecutionProgress {
  total: number;
  completed: number;
  percentage: number;
}

/**
 * Return type for usePlanExecution hook
 */
export interface UsePlanExecutionReturn {
  // Current execution plan
  executionPlan: ExecutionPlan | null;

  // Status flags
  isExecuting: boolean;
  isCompleted: boolean;
  isFailed: boolean;

  // Progress
  progress: ExecutionProgress;

  // Steps categorized by status
  completedSteps: ExecutionStep[];
  pendingSteps: ExecutionStep[];
  inProgressSteps: ExecutionStep[];
  failedSteps: ExecutionStep[];

  // Current step
  currentStep: ExecutionStep | null;

  // Adjustments
  hasStepAdjustments: boolean;
}

/**
 * Calculate execution progress from steps
 */
function calculateProgress(steps: ExecutionStep[]): ExecutionProgress {
  const total = steps.length;
  const completed = steps.filter(
    (step) => step.status === "completed"
  ).length;
  const percentage = total > 0 ? Math.round((completed / total) * 100) : 0;

  return { total, completed, percentage };
}

/**
 * Categorize steps by status
 */
function categorizeSteps(steps: ExecutionStep[]) {
  return {
    completedSteps: steps.filter((step) => step.status === "completed"),
    pendingSteps: steps.filter((step) => step.status === "pending"),
    inProgressSteps: steps.filter((step) => step.status === "in_progress"),
    failedSteps: steps.filter((step) => step.status === "failed"),
  };
}

/**
 * Get current step based on current_step_index
 */
function getCurrentStep(
  steps: ExecutionStep[],
  currentIndex?: number
): ExecutionStep | null {
  if (currentIndex === undefined || currentIndex < 0 || currentIndex >= steps.length) {
    return null;
  }
  return steps[currentIndex] ?? null;
}

/**
 * Custom hook for monitoring plan execution
 *
 * Provides derived state and progress information for execution plans.
 * Automatically updates when the execution plan changes in the agentV3 store.
 *
 * @example
 * ```tsx
 * const { isExecuting, progress, currentStep } = usePlanExecution();
 *
 * return (
 *   <div>
 *     {isExecuting && (
 *       <Progress percent={progress.percentage} />
 *     )}
 *     {currentStep && <div>Executing: {currentStep.description}</div>}
 *   </div>
 * );
 * ```
 */
export function usePlanExecution(): UsePlanExecutionReturn {
  // Select execution plan from agentV3 store
  const executionPlan = useAgentV3Store((state) => state.executionPlan);

  // Memoized calculations
  const progress = useMemo(
    () => calculateProgress(executionPlan?.steps ?? []),
    [executionPlan?.steps]
  );

  const stepCategories = useMemo(
    () => categorizeSteps(executionPlan?.steps ?? []),
    [executionPlan?.steps]
  );

  const currentStep = useMemo(
    () => getCurrentStep(executionPlan?.steps ?? [], executionPlan?.current_step_index),
    [executionPlan?.steps, executionPlan?.current_step_index]
  );

  // Status flags
  const isExecuting = useMemo(
    () => executionPlan?.status === "in_progress",
    [executionPlan?.status]
  );

  const isCompleted = useMemo(
    () => executionPlan?.status === "completed",
    [executionPlan?.status]
  );

  const isFailed = useMemo(
    () => executionPlan?.status === "failed",
    [executionPlan?.status]
  );

  // Check for step adjustments
  const hasStepAdjustments = useMemo(
    () =>
      executionPlan?.step_adjustments != null &&
      executionPlan.step_adjustments.length > 0,
    [executionPlan?.step_adjustments]
  );

  return {
    // Current execution plan
    executionPlan,

    // Status flags
    isExecuting,
    isCompleted,
    isFailed,

    // Progress
    progress,

    // Steps categorized by status
    completedSteps: stepCategories.completedSteps,
    pendingSteps: stepCategories.pendingSteps,
    inProgressSteps: stepCategories.inProgressSteps,
    failedSteps: stepCategories.failedSteps,

    // Current step
    currentStep,

    // Adjustments
    hasStepAdjustments,
  };
}

export default usePlanExecution;
