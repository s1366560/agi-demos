/**
 * ExecutionTimeline - Vertical timeline for agent execution visualization
 *
 * Displays the agent's execution process as a vertical timeline with:
 * - Work plan overview (if present)
 * - Step nodes with expandable details
 * - Tool execution details with parameters and results
 * - Adaptive display modes based on task complexity
 */

import { useState, useEffect, useRef, useCallback } from "react";
import type {
  TimelineStep,
  WorkPlan,
  ToolExecution,
} from "../../../types/agent";
import { MaterialIcon } from "../shared";
import { TimelineNode } from "./TimelineNode";
import { SimpleExecutionView } from "./SimpleExecutionView";

export type DisplayMode = "timeline" | "simple-timeline" | "direct";

export interface ExecutionTimelineProps {
  /** Work plan (if present, enables full timeline mode) */
  workPlan?: WorkPlan | null;
  /** Timeline steps with execution details */
  steps: TimelineStep[];
  /** Tool execution history (for simple-timeline mode) */
  toolExecutionHistory?: ToolExecution[];
  /** Final response content */
  finalResponse?: string;
  /** Whether streaming is in progress */
  isStreaming: boolean;
  /** Current step number being executed */
  currentStepNumber?: number | null;
  /** Matched workflow pattern info */
  matchedPattern?: { id: string; similarity: number } | null;
}

/**
 * Determine display mode based on available data
 * Returns "direct" for simple conversations to avoid showing unnecessary execution plans
 */
function getDisplayMode(
  workPlan: WorkPlan | null | undefined,
  steps: TimelineStep[],
  toolExecutionHistory: ToolExecution[]
): DisplayMode {
  // No work plan and minimal activity - use direct mode (no timeline shown)
  // This handles simple conversations like "hi" where no tools are needed
  if (!workPlan && steps.length <= 1 && toolExecutionHistory.length <= 1) {
    return "direct";
  }
  
  if (workPlan || steps.length > 0) {
    return "timeline";
  }
  if (toolExecutionHistory.length > 0) {
    return "simple-timeline";
  }
  return "direct";
}

/**
 * ExecutionTimeline component
 *
 * @example
 * <ExecutionTimeline
 *   workPlan={currentWorkPlan}
 *   steps={executionTimeline}
 *   toolExecutionHistory={toolExecutionHistory}
 *   isStreaming={isStreaming}
 *   currentStepNumber={currentStepNumber}
 * />
 */
export function ExecutionTimeline({
  workPlan,
  steps,
  toolExecutionHistory = [],
  isStreaming,
  currentStepNumber,
  matchedPattern,
}: ExecutionTimelineProps) {
  // Track manually toggled steps (user interaction)
  const [manuallyExpandedSteps, setManuallyExpandedSteps] = useState<
    Set<number>
  >(new Set());
  const [manuallyCollapsedSteps, setManuallyCollapsedSteps] = useState<
    Set<number>
  >(new Set());
  const timelineRef = useRef<HTMLDivElement>(null);

  const displayMode = getDisplayMode(workPlan, steps, toolExecutionHistory);

  // Derive expanded state: auto-expand current step unless manually collapsed
  const isStepExpanded = useCallback(
    (stepNumber: number) => {
      // If manually collapsed, don't show
      if (manuallyCollapsedSteps.has(stepNumber)) return false;
      // If manually expanded, show
      if (manuallyExpandedSteps.has(stepNumber)) return true;
      // Auto-expand current running step
      if (currentStepNumber === stepNumber) return true;
      return false;
    },
    [manuallyExpandedSteps, manuallyCollapsedSteps, currentStepNumber]
  );

  // Auto-scroll to current step
  useEffect(() => {
    if (
      currentStepNumber !== null &&
      currentStepNumber !== undefined &&
      timelineRef.current
    ) {
      const stepElement = timelineRef.current.querySelector(
        `[data-step-number="${currentStepNumber}"]`
      );
      if (stepElement) {
        stepElement.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  }, [currentStepNumber]);

  const toggleStep = (stepNumber: number) => {
    const isCurrentlyExpanded = isStepExpanded(stepNumber);
    if (isCurrentlyExpanded) {
      // Collapse: add to collapsed set, remove from expanded set
      setManuallyCollapsedSteps((prev) => new Set([...prev, stepNumber]));
      setManuallyExpandedSteps((prev) => {
        const next = new Set(prev);
        next.delete(stepNumber);
        return next;
      });
    } else {
      // Expand: add to expanded set, remove from collapsed set
      setManuallyExpandedSteps((prev) => new Set([...prev, stepNumber]));
      setManuallyCollapsedSteps((prev) => {
        const next = new Set(prev);
        next.delete(stepNumber);
        return next;
      });
    }
  };

  const expandAll = () => {
    setManuallyExpandedSteps(new Set(steps.map((s) => s.stepNumber)));
    setManuallyCollapsedSteps(new Set());
  };

  const collapseAll = () => {
    setManuallyExpandedSteps(new Set());
    setManuallyCollapsedSteps(new Set(steps.map((s) => s.stepNumber)));
  };

  // Calculate overall progress
  const completedSteps = steps.filter((s) => s.status === "completed").length;
  const totalSteps = steps.length;
  const progressPercent =
    totalSteps > 0 ? Math.round((completedSteps / totalSteps) * 100) : 0;

  // Simple timeline mode - just show tool executions with checklist header
  if (displayMode === "simple-timeline") {
    return (
      <div className="w-full mb-4">
        {/* Work Plan Checklist - Only show if workPlan exists */}
        {workPlan && workPlan.steps && workPlan.steps.length > 0 && (
          <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl p-4 mb-4">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                <MaterialIcon
                  name="checklist"
                  size={18}
                  className="text-primary"
                />
              </div>
              <h3 className="font-semibold text-slate-900 dark:text-white">
                执行计划
              </h3>
            </div>
            <div className="space-y-2">
              {workPlan.steps.map((step, idx) => {
                const isCompleted = idx < (currentStepNumber ?? 0);
                const isActive = idx === currentStepNumber;
                return (
                  <div
                    key={idx}
                    className={`flex items-center gap-3 py-2 px-3 rounded-lg transition-colors ${
                      isActive
                        ? "bg-primary/5 border border-primary/20"
                        : isCompleted
                        ? "bg-emerald-50 dark:bg-emerald-900/10"
                        : "bg-slate-50 dark:bg-slate-800/50"
                    }`}
                  >
                    <div
                      className={`w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 ${
                        isCompleted
                          ? "bg-emerald-500 text-white"
                          : isActive
                          ? "bg-primary text-white"
                          : "bg-slate-200 dark:bg-slate-700"
                      }`}
                    >
                      {isCompleted ? (
                        <MaterialIcon name="check" size={14} />
                      ) : isActive ? (
                        <span className="w-2 h-2 bg-white rounded-full animate-pulse" />
                      ) : (
                        <span className="text-xs text-slate-500">
                          {idx + 1}
                        </span>
                      )}
                    </div>
                    <span
                      className={`text-sm ${
                        isCompleted
                          ? "text-emerald-700 dark:text-emerald-400 line-through"
                          : isActive
                          ? "text-primary font-medium"
                          : "text-slate-600 dark:text-slate-400"
                      }`}
                    >
                      {step.description}
                    </span>
                    {isActive && isStreaming && (
                      <span className="ml-auto text-xs text-primary">
                        执行中...
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
        <SimpleExecutionView
          toolExecutions={toolExecutionHistory}
          isStreaming={isStreaming}
        />
      </div>
    );
  }

  // Direct mode - nothing to show here (handled by parent)
  if (displayMode === "direct") {
    return null;
  }

  // Full timeline mode
  return (
    <div className="w-full mb-4" ref={timelineRef}>
      {/* Work Plan Checklist Card */}
      {workPlan && (
        <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl p-4 mb-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                <MaterialIcon
                  name="checklist"
                  size={20}
                  className="text-primary"
                />
              </div>
              <div>
                <h3 className="font-semibold text-slate-900 dark:text-white">
                  执行计划
                </h3>
                <p className="text-sm text-slate-500">
                  {completedSteps}/{totalSteps} 步骤已完成
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {/* Pattern Match Badge */}
              {matchedPattern && (
                <span className="px-2 py-1 rounded-full text-xs font-medium bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">
                  匹配模式 ({Math.round(matchedPattern.similarity * 100)}%)
                </span>
              )}

              {/* Status Badge */}
              <span
                className={`px-2 py-1 rounded-full text-xs font-semibold ${
                  completedSteps === totalSteps
                    ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400"
                    : isStreaming
                    ? "bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400"
                    : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400"
                }`}
              >
                {completedSteps === totalSteps
                  ? "已完成"
                  : isStreaming
                  ? "执行中"
                  : "等待中"}
              </span>
            </div>
          </div>

          {/* Progress Bar */}
          <div className="h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden mb-3">
            <div
              className="h-full bg-primary transition-all duration-500 ease-out"
              style={{ width: `${progressPercent}%` }}
            />
          </div>

          {/* Checklist Items */}
          <div className="space-y-2">
            {steps.map((step, idx) => {
              const isCompleted = step.status === "completed";
              const isActive =
                step.status === "running" ||
                currentStepNumber === step.stepNumber;
              const isFailed = step.status === "failed";
              return (
                <div
                  key={step.stepNumber}
                  className={`flex items-center gap-3 py-2 px-3 rounded-lg transition-colors cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/70 ${
                    isActive
                      ? "bg-primary/5 border border-primary/20"
                      : isCompleted
                      ? "bg-emerald-50 dark:bg-emerald-900/10"
                      : isFailed
                      ? "bg-red-50 dark:bg-red-900/10"
                      : "bg-slate-50 dark:bg-slate-800/50"
                  }`}
                  onClick={() => toggleStep(step.stepNumber)}
                  data-step-number={step.stepNumber}
                >
                  <div
                    className={`w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 ${
                      isCompleted
                        ? "bg-emerald-500 text-white"
                        : isFailed
                        ? "bg-red-500 text-white"
                        : isActive
                        ? "bg-primary text-white"
                        : "bg-slate-200 dark:bg-slate-700"
                    }`}
                  >
                    {isCompleted ? (
                      <MaterialIcon name="check" size={14} />
                    ) : isFailed ? (
                      <MaterialIcon name="close" size={14} />
                    ) : isActive ? (
                      <span className="w-2 h-2 bg-white rounded-full animate-pulse" />
                    ) : (
                      <span className="text-xs text-slate-500">{idx + 1}</span>
                    )}
                  </div>
                  <span
                    className={`text-sm flex-grow ${
                      isCompleted
                        ? "text-emerald-700 dark:text-emerald-400"
                        : isFailed
                        ? "text-red-700 dark:text-red-400"
                        : isActive
                        ? "text-primary font-medium"
                        : "text-slate-600 dark:text-slate-400"
                    }`}
                  >
                    {step.description}
                  </span>
                  {step.toolExecutions && step.toolExecutions.length > 0 && (
                    <span className="text-xs text-slate-400">
                      {step.toolExecutions.length} 工具
                    </span>
                  )}
                  {isActive && isStreaming && (
                    <span className="text-xs text-primary">执行中...</span>
                  )}
                  <MaterialIcon
                    name={
                      isStepExpanded(step.stepNumber)
                        ? "expand_less"
                        : "expand_more"
                    }
                    size={18}
                    className="text-slate-400"
                  />
                </div>
              );
            })}
          </div>

          {/* Expand/Collapse Controls */}
          {steps.length > 1 && (
            <div className="flex justify-end gap-2 mt-3 pt-3 border-t border-slate-100 dark:border-slate-700">
              <button
                onClick={expandAll}
                className="text-xs text-primary hover:underline"
              >
                展开全部
              </button>
              <span className="text-slate-300">|</span>
              <button
                onClick={collapseAll}
                className="text-xs text-primary hover:underline"
              >
                收起全部
              </button>
            </div>
          )}
        </div>
      )}

      {/* Timeline Nodes */}
      <div className="relative">
        {/* Vertical Timeline Line */}
        <div className="absolute left-6 top-0 bottom-0 w-0.5 bg-slate-200 dark:bg-slate-700" />

        {/* Step Nodes */}
        {steps.map((step, index) => {
          const isExpanded = isStepExpanded(step.stepNumber);
          const isLast = index === steps.length - 1;
          const isCurrent = currentStepNumber === step.stepNumber;

          return (
            <TimelineNode
              key={step.stepNumber}
              step={step}
              isExpanded={isExpanded}
              isCurrent={isCurrent}
              isLast={isLast}
              onToggle={() => toggleStep(step.stepNumber)}
            />
          );
        })}
      </div>
    </div>
  );
}

export default ExecutionTimeline;
