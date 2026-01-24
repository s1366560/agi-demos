/**
 * WorkPlanProgress - 3-step progress bar visualization
 *
 * Displays the agent's work plan progress with step indicators:
 * - Analyzing Request
 * - Searching Memory
 * - Synthesizing Report
 */

import { MaterialIcon } from "../shared";

export type StepStatus = "pending" | "running" | "completed" | "failed";

export interface WorkPlanStep {
  number: number;
  title: string;
  status: StepStatus;
}

export interface WorkPlanProgressProps {
  /** Current step being executed */
  currentStep: number;
  /** Total number of steps (default: 3) */
  totalSteps?: number;
  /** Custom step labels */
  stepLabels?: string[];
  /** Overall progress percentage (0-100) */
  progress?: number;
  /** Status message */
  statusMessage?: string;
  /** Whether to show compact version */
  compact?: boolean;
}

const DEFAULT_STEP_LABELS = [
  "Analyzing Request",
  "Searching Memory",
  "Synthesizing Report",
];

/**
 * WorkPlanProgress component
 *
 * @example
 * <WorkPlanProgress
 *   currentStep={1}
 *   progress={33}
 *   statusMessage="Processing your request..."
 * />
 */
export function WorkPlanProgress({
  currentStep,
  totalSteps = 3,
  stepLabels = DEFAULT_STEP_LABELS,
  progress,
  statusMessage,
  compact = false,
}: WorkPlanProgressProps) {
  // Calculate progress if not provided
  const calculatedProgress =
    progress ?? Math.round((currentStep / totalSteps) * 100);

  const getStepStatus = (stepNumber: number): StepStatus => {
    if (stepNumber < currentStep) return "completed";
    if (stepNumber === currentStep) return "running";
    return "pending";
  };

  const getStatusStyles = (status: StepStatus) => {
    switch (status) {
      case "completed":
        return "bg-primary text-white";
      case "running":
        return "bg-primary text-white animate-[pulse-ring_2s_ease-in-out_infinite]";
      case "failed":
        return "bg-red-500 text-white";
      default:
        return "bg-slate-200 dark:bg-slate-700 text-slate-400 dark:text-slate-600";
    }
  };

  const getLineColor = (stepNumber: number) => {
    if (stepNumber < currentStep) return "bg-primary";
    return "bg-slate-200 dark:bg-slate-700";
  };

  if (compact) {
    return (
      <div className="w-full">
        {/* Progress Bar */}
        <div className="h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-primary transition-all duration-500 ease-out"
            style={{ width: `${calculatedProgress}%` }}
          />
        </div>

        {/* Step Labels */}
        <div className="flex justify-between mt-2">
          {stepLabels.slice(0, totalSteps).map((label, index) => {
            const stepNum = index + 1;
            const status = getStepStatus(stepNum);
            return (
              <span
                key={index}
                className={`text-xs font-medium ${
                  status === "completed" || status === "running"
                    ? "text-primary"
                    : "text-slate-400"
                }`}
              >
                {label}
              </span>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="w-full bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl p-4 mb-4">
      {/* Header with Status */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <MaterialIcon
              name="psychology"
              size={20}
              className="text-primary"
            />
            <h3 className="font-semibold text-slate-900 dark:text-white">
              Work Plan
            </h3>
          </div>
          {statusMessage && (
            <span className="text-sm text-slate-500">{statusMessage}</span>
          )}
        </div>

        {/* Overall Status Badge */}
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">
            Step {currentStep} of {totalSteps}
          </span>
          <span
            className={`px-2 py-1 rounded-full text-xs font-semibold ${
              currentStep === totalSteps
                ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400"
                : "bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400"
            }`}
          >
            {currentStep === totalSteps ? "Completed" : "In Progress"}
          </span>
        </div>
      </div>

      {/* Progress Steps */}
      <div className="flex items-center justify-between">
        {stepLabels.slice(0, totalSteps).map((label, index) => {
          const stepNum = index + 1;
          const status = getStepStatus(stepNum);
          const isLast = index === totalSteps - 1;

          return (
            <div key={index} className="flex-1 flex items-center">
              {/* Step Circle */}
              <div
                className={`w-12 h-12 rounded-full flex items-center justify-center text-sm font-semibold transition-all duration-300 ${getStatusStyles(
                  status
                )}`}
              >
                {status === "completed" ? (
                  <MaterialIcon name="check" size={18} />
                ) : status === "running" ? (
                  <MaterialIcon name="hourglass_empty" size={18} />
                ) : (
                  stepNum
                )}
              </div>

              {/* Step Label */}
              <div className="ml-3">
                <p
                  className={`text-sm font-medium ${
                    status === "completed" || status === "running"
                      ? "text-slate-900 dark:text-white"
                      : "text-slate-400"
                  }`}
                >
                  {label}
                </p>
              </div>

              {/* Connecting Line (not for last step) */}
              {!isLast && (
                <div
                  className={`flex-1 h-1.5 mx-4 rounded-full transition-all duration-300 ${getLineColor(
                    stepNum
                  )}`}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* Progress Bar */}
      <div className="mt-4 h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
        <div
          className="h-full bg-primary transition-all duration-500 ease-out"
          style={{ width: `${calculatedProgress}%` }}
        />
      </div>
    </div>
  );
}

export default WorkPlanProgress;
