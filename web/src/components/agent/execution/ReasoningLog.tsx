/**
 * ReasoningLog - Collapsible agent reasoning display
 *
 * Uses native HTML <details> element for accessibility and simplicity.
 * Shows agent's step-by-step reasoning process.
 */

import { MaterialIcon } from '../shared';

export interface ReasoningStep {
  number: number;
  title: string;
  description: string;
}

export interface ReasoningLogProps {
  /** Agent's reasoning content */
  reasoning?: string;
  /** Structured reasoning steps */
  steps?: ReasoningStep[];
  /** Whether the log is complete */
  complete?: boolean;
  /** Default open state */
  defaultOpen?: boolean;
  /** Title for the reasoning log */
  title?: string;
}

/**
 * ReasoningLog component
 *
 * @example
 * <ReasoningLog
 *   reasoning="Breaking down the query into sub-goals..."
 *   complete={true}
 * />
 */
export function ReasoningLog({
  reasoning,
  steps,
  complete = false,
  defaultOpen = false,
  title = 'Agent Reasoning',
}: ReasoningLogProps) {
  return (
    <details
      className="group/reasoning bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl overflow-hidden mb-4"
      open={defaultOpen}
    >
      {/* Summary (Header) */}
      <summary className="cursor-pointer list-none flex items-center justify-between px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors select-none">
        <div className="flex items-center gap-3">
          {/* Chevron Icon */}
          <MaterialIcon
            name="chevron_right"
            className="group-open/reasoning:rotate-90 transition-transform duration-200 text-slate-400"
            size={20}
          />

          {/* Title */}
          <span className="text-sm font-medium text-slate-900 dark:text-white">
            {title}
          </span>
        </div>

        {/* Status Badge */}
        {complete && (
          <span className="ml-auto text-xs bg-emerald-500 text-white px-2 py-0.5 rounded font-semibold uppercase tracking-wider">
            Complete
          </span>
        )}
      </summary>

      {/* Content */}
      <div className="px-4 pb-4">
        {/* Structured Steps */}
        {steps && steps.length > 0 && (
          <div className="mt-3 space-y-3">
            {steps.map((step, index) => (
              <div key={index} className="flex gap-3">
                {/* Step Number */}
                <div className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center text-primary text-xs font-semibold">
                  {step.number}
                </div>

                {/* Step Content */}
                <div className="flex-1">
                  <h4 className="text-sm font-semibold text-slate-900 dark:text-white mb-0.5">
                    {step.title}
                  </h4>
                  <p className="text-sm text-slate-600 dark:text-slate-400">
                    {step.description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Raw Reasoning Text */}
        {reasoning && (
          <div className="mt-3 pl-6 text-sm text-slate-600 dark:text-slate-400 whitespace-pre-wrap">
            {reasoning}
          </div>
        )}
      </div>
    </details>
  );
}

export default ReasoningLog;
