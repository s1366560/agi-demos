/**
 * Execution Store - Split from monolithic agent store.
 *
 * This store manages execution state for agent WorkPlan execution.
 * It handles the multi-level thinking execution timeline, step progress,
 * and tool execution tracking.
 *
 * State managed:
 * - currentWorkPlan: Current WorkPlan being executed
 * - currentStepNumber: Currently executing step number
 * - currentStepStatus: Status of current step (pending/running/completed/failed)
 * - executionTimeline: Timeline of steps being executed
 * - currentToolExecution: Currently running tool execution
 * - toolExecutionHistory: History of all tool executions
 * - matchedPattern: Pattern match result (T079)
 *
 * This store was split from agent.ts to improve maintainability
 * and follow single-responsibility principle.
 *
 * Uses Zustand for state management, consistent with the main agent store.
 *
 * @module stores/agent/executionStore
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

import type { WorkPlan, TimelineStep, ToolExecution } from '../../types/agent';

/**
 * Step status type
 */
export type StepStatus = 'pending' | 'running' | 'completed' | 'failed';

/**
 * Matched pattern type (T079)
 */
export interface MatchedPattern {
  id: string;
  similarity: number;
  query: string;
}

/**
 * Current tool execution type
 */
export interface CurrentToolExecution {
  id: string;
  toolName: string;
  input: Record<string, unknown>;
  stepNumber?: number | undefined;
  startTime: string;
}

/**
 * Execution Store State
 */
export interface ExecutionState {
  // Work plan state
  currentWorkPlan: WorkPlan | null;
  currentStepNumber: number | null;
  currentStepStatus: StepStatus | null;

  // Execution timeline
  executionTimeline: TimelineStep[];

  // Tool execution state
  currentToolExecution: CurrentToolExecution | null;
  toolExecutionHistory: ToolExecution[];

  // Pattern matching state (T079)
  matchedPattern: MatchedPattern | null;

  // Actions
  setWorkPlan: (workPlan: WorkPlan) => void;
  startStep: (stepNumber: number, description: string) => void;
  completeStep: (stepNumber: number, success: boolean, nextStepIndex: number) => void;
  addThought: (thought: string, stepNumber?: number) => void;
  startTool: (
    toolName: string,
    input: Record<string, unknown>,
    stepNumber?: number,
    callId?: string,
    startTime?: string
  ) => void;
  completeTool: (callId: string | undefined, observation: string, isError?: boolean) => void;
  setMatchedPattern: (pattern: MatchedPattern | null) => void;
  clearExecution: () => void;
  reset: () => void;
}

/**
 * Initial state for Execution store
 */
export const initialState = {
  currentWorkPlan: null,
  currentStepNumber: null,
  currentStepStatus: null,
  executionTimeline: [],
  currentToolExecution: null,
  toolExecutionHistory: [],
  matchedPattern: null,
};

/**
 * Generate a unique tool ID
 */
function generateToolId(): string {
  return `tool-${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
}

/**
 * Check if an observation is an error
 * Note: This is a fallback check for legacy data.
 * New observe events have an explicit 'isError' field from the server.
 * We only check for 'failed' in the content as a very weak heuristic.
 */
function isObservationError(observation: string): boolean {
  // Only consider it an error if it explicitly contains 'failed'
  // (not just starts with 'error:' which could be valid output)
  const lowerObs = observation?.toLowerCase() || '';
  return lowerObs.includes('execution failed') || lowerObs.includes('tool failed');
}

/**
 * Execution Store
 *
 * Zustand store for managing execution state.
 */
export const useExecutionStore = create<ExecutionState>()(
  devtools(
    (set) => ({
      ...initialState,

      /**
       * Set work plan and build execution timeline
       *
       * @param workPlan - The work plan to set
       */
      setWorkPlan: (workPlan: WorkPlan) => {
        // Build execution timeline skeleton from work plan
        const timelineSteps: TimelineStep[] = workPlan.steps.map((step) => ({
          stepNumber: step.step_number,
          description: step.description,
          status: 'pending' as const,
          thoughts: [],
          toolExecutions: [],
        }));

        set({
          currentWorkPlan: workPlan,
          executionTimeline: timelineSteps,
          toolExecutionHistory: [],
        });
      },

      /**
       * Start executing a step
       *
       * Updates the step status to running and sets the current step.
       *
       * @param stepNumber - The step number to start
       * @param description - The step description (for logging)
       */
      startStep: (stepNumber: number, _description: string) => {
        const startTime = new Date().toISOString();

        set((state) => {
          // Update execution timeline step status
          const updatedTimeline = state.executionTimeline.map((step) =>
            step.stepNumber === stepNumber
              ? {
                  ...step,
                  status: 'running' as const,
                  startTime,
                }
              : step
          );

          return {
            currentStepNumber: stepNumber,
            currentStepStatus: 'running' as const,
            executionTimeline: updatedTimeline,
          };
        });
      },

      /**
       * Complete a step with success or failure
       *
       * Updates the step status and optionally marks running tool executions
       * as complete/failed to match the step status.
       *
       * @param stepNumber - The step number to complete
       * @param success - Whether the step completed successfully
       * @param nextStepIndex - The next step index to update in the work plan
       */
      completeStep: (stepNumber: number, success: boolean, nextStepIndex: number) => {
        const endTime = new Date().toISOString();

        set((state) => {
          const updatedTimeline = state.executionTimeline.map((step) => {
            if (step.stepNumber === stepNumber) {
              const startTimeMs = step.startTime ? new Date(step.startTime).getTime() : 0;
              const endTimeMs = new Date(endTime).getTime();
              const duration = startTimeMs ? endTimeMs - startTimeMs : undefined;

              // Also update any "running" tool executions to match step status
              const updatedToolExecutions = step.toolExecutions.map((exec) =>
                exec.status === 'running'
                  ? {
                      ...exec,
                      status: success ? ('success' as const) : ('failed' as const),
                      endTime,
                    }
                  : exec
              );

              return {
                ...step,
                status: success ? ('completed' as const) : ('failed' as const),
                endTime,
                duration,
                toolExecutions: updatedToolExecutions,
              };
            }
            return step;
          });

          // Also update tool execution history for consistency
          const toolIdsInStep =
            state.executionTimeline
              .find((s) => s.stepNumber === stepNumber)
              ?.toolExecutions.map((t) => t.id) ?? [];

          const updatedHistory = state.toolExecutionHistory.map((exec) =>
            toolIdsInStep.includes(exec.id) && exec.status === 'running'
              ? {
                  ...exec,
                  status: success ? ('success' as const) : ('failed' as const),
                  endTime,
                }
              : exec
          );

          return {
            currentStepStatus: success ? ('completed' as const) : ('failed' as const),
            currentWorkPlan: state.currentWorkPlan
              ? {
                  ...state.currentWorkPlan,
                  current_step_index: nextStepIndex,
                }
              : null,
            executionTimeline: updatedTimeline,
            toolExecutionHistory: updatedHistory,
          };
        });
      },

      /**
       * Add thought to a step
       *
       * @param thought - The thought to add
       * @param stepNumber - Optional step number (uses current if not provided)
       */
      addThought: (thought: string, stepNumber?: number) => {
        set((state) => {
          const targetStepNumber = stepNumber ?? state.currentStepNumber;

          // Only update if we have a valid step number
          if (targetStepNumber === null || targetStepNumber === undefined) {
            return {};
          }

          const updatedTimeline = state.executionTimeline.map((step) =>
            step.stepNumber === targetStepNumber
              ? { ...step, thoughts: [...step.thoughts, thought] }
              : step
          );

          return { executionTimeline: updatedTimeline };
        });
      },

      /**
       * Start a tool execution
       *
       * Creates a new tool execution record and adds it to history and timeline.
       *
       * @param toolName - The name of the tool being executed
       * @param input - The tool input parameters
       * @param stepNumber - Optional step number for the tool
       * @param callId - Optional call ID (generates one if not provided)
       * @param startTime - Optional start time (uses current time if not provided)
       */
      startTool: (
        toolName: string,
        input: Record<string, unknown>,
        stepNumber?: number,
        callId?: string,
        startTime?: string
      ) => {
        const effectiveStartTime = startTime || new Date().toISOString();
        const toolId = callId || generateToolId();

        set((state) => {
          const existingTool = state.toolExecutionHistory.find((exec) => exec.id === toolId);
          // Convert null to undefined for stepNumber to match ToolExecution type
          const targetStepNumber = stepNumber ?? state.currentStepNumber ?? undefined;

          let updatedHistory = state.toolExecutionHistory;
          let updatedTimeline = state.executionTimeline;

          if (existingTool) {
            // Update existing tool
            updatedHistory = state.toolExecutionHistory.map((exec) =>
              exec.id === toolId ? { ...exec, input, status: 'running' as const } : exec
            );
          } else {
            // Create new tool execution record
            const toolExecution: ToolExecution = {
              id: toolId,
              toolName,
              input,
              status: 'running',
              startTime: effectiveStartTime,
              stepNumber: targetStepNumber,
            };
            updatedHistory = [...state.toolExecutionHistory, toolExecution];

            // Add to timeline if we have a step number
            if (targetStepNumber !== undefined) {
              updatedTimeline = state.executionTimeline.map((step) =>
                step.stepNumber === targetStepNumber
                  ? {
                      ...step,
                      toolExecutions: [...step.toolExecutions, toolExecution],
                    }
                  : step
              );
            }
          }

          return {
            currentToolExecution: {
              id: toolId,
              toolName,
              input,
              startTime: effectiveStartTime,
              stepNumber: targetStepNumber,
            },
            executionTimeline: updatedTimeline,
            toolExecutionHistory: updatedHistory,
          };
        });
      },

      /**
       * Complete a tool execution with result
       *
       * Updates the tool execution status and result. Falls back to currentToolExecution
       * if callId is not provided.
       *
       * @param callId - The call ID of the tool to complete (optional)
       * @param observation - The tool output or error message
       * @param isError - Whether this is an error result (optional, defaults to heuristic check)
       */
      completeTool: (callId: string | undefined, observation: string, isError?: boolean) => {
        const endTime = new Date().toISOString();

        set((state) => {
          const targetToolId = callId || state.currentToolExecution?.id;

          if (!targetToolId) {
            return {};
          }

          const targetExecution = state.toolExecutionHistory.find(
            (exec) => exec.id === targetToolId
          );

          const startTimeMs = targetExecution?.startTime
            ? new Date(targetExecution.startTime).getTime()
            : state.currentToolExecution
              ? new Date(state.currentToolExecution.startTime).getTime()
              : 0;

          const endTimeMs = new Date(endTime).getTime();
          const duration = startTimeMs ? endTimeMs - startTimeMs : undefined;

          // Use explicit isError if provided, otherwise fall back to heuristic
          const hasError = isError !== undefined ? isError : isObservationError(observation);

          // Update tool execution in history
          const updatedHistory = state.toolExecutionHistory.map((exec) =>
            exec.id === targetToolId
              ? {
                  ...exec,
                  status: hasError ? ('failed' as const) : ('success' as const),
                  result: hasError ? undefined : observation,
                  error: hasError ? observation : undefined,
                  endTime,
                  duration,
                }
              : exec
          );

          // Update tool execution in timeline
          const targetStepNumber =
            targetExecution?.stepNumber ?? state.currentToolExecution?.stepNumber;

          let updatedTimeline = state.executionTimeline;
          if (targetStepNumber !== null && targetStepNumber !== undefined) {
            updatedTimeline = state.executionTimeline.map((step) =>
              step.stepNumber === targetStepNumber
                ? {
                    ...step,
                    toolExecutions: step.toolExecutions.map((exec) =>
                      exec.id === targetToolId
                        ? {
                            ...exec,
                            status: hasError ? ('failed' as const) : ('success' as const),
                            result: hasError ? undefined : observation,
                            error: hasError ? observation : undefined,
                            endTime,
                            duration,
                          }
                        : exec
                    ),
                  }
                : step
            );
          }

          return {
            // Only clear currentToolExecution if we were called with an explicit callId
            // If callId was undefined, we used currentToolExecution but keep it for observation display
            currentToolExecution: callId ? null : state.currentToolExecution,
            executionTimeline: updatedTimeline,
            toolExecutionHistory: updatedHistory,
          };
        });
      },

      /**
       * Set matched pattern
       *
       * @param pattern - The matched pattern or null to clear
       */
      setMatchedPattern: (pattern: MatchedPattern | null) => {
        set({ matchedPattern: pattern });
      },

      /**
       * Clear all execution state
       *
       * Clears work plan, timeline, tool executions, and pattern.
       */
      clearExecution: () => {
        set({
          currentWorkPlan: null,
          currentStepNumber: null,
          currentStepStatus: null,
          executionTimeline: [],
          currentToolExecution: null,
          toolExecutionHistory: [],
          matchedPattern: null,
        });
      },

      /**
       * Reset store to initial state
       *
       * Completely resets all state in this store.
       */
      reset: () => {
        set(initialState);
      },
    }),
    {
      name: 'ExecutionStore',
      enabled: import.meta.env.DEV,
    }
  )
);

/**
 * Derived selector: Get current work plan
 */
export const useCurrentWorkPlan = () => useExecutionStore((state) => state.currentWorkPlan);

/**
 * Derived selector: Get current step number
 */
export const useCurrentStepNumber = () => useExecutionStore((state) => state.currentStepNumber);

/**
 * Derived selector: Get current step status
 */
export const useCurrentStepStatus = () => useExecutionStore((state) => state.currentStepStatus);

/**
 * Derived selector: Get execution timeline
 */
export const useExecutionTimeline = () => useExecutionStore((state) => state.executionTimeline);

/**
 * Derived selector: Get current tool execution
 */
export const useCurrentToolExecution = () =>
  useExecutionStore((state) => state.currentToolExecution);

/**
 * Derived selector: Get tool execution history
 */
export const useToolExecutionHistory = () =>
  useExecutionStore((state) => state.toolExecutionHistory);

/**
 * Derived selector: Get matched pattern
 */
export const useMatchedPattern = () => useExecutionStore((state) => state.matchedPattern);

/**
 * Type export for store (used in tests)
 */
export type ExecutionStore = ReturnType<typeof useExecutionStore.getState>;
