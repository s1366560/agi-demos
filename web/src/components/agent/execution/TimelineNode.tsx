/**
 * TimelineNode - Single node in the execution timeline
 *
 * Displays a step in the execution timeline with:
 * - Status indicator (pending/running/completed/failed)
 * - Step description
 * - Expandable details (thoughts and tool executions)
 * - Duration information
 */

import { useState } from 'react';
import type { TimelineStep } from '../../../types/agent';
import { MaterialIcon } from '../shared';
import { ToolExecutionDetail } from './ToolExecutionDetail';

export interface TimelineNodeProps {
  /** Step data */
  step: TimelineStep;
  /** Whether the node is expanded */
  isExpanded: boolean;
  /** Whether this is the current running step */
  isCurrent: boolean;
  /** Whether this is the last node */
  isLast: boolean;
  /** Toggle expand/collapse */
  onToggle: () => void;
}

/**
 * Format duration in human-readable format
 */
function formatDuration(ms: number | undefined): string {
  if (!ms) return '';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/**
 * Get status icon and styles
 */
function getStatusConfig(status: TimelineStep['status']) {
  switch (status) {
    case 'completed':
      return {
        icon: 'check',
        bgColor: 'bg-emerald-500',
        textColor: 'text-white',
        borderColor: 'border-emerald-500',
        pulse: false,
      };
    case 'running':
      return {
        icon: 'hourglass_empty',
        bgColor: 'bg-blue-500',
        textColor: 'text-white',
        borderColor: 'border-blue-500',
        pulse: true,
      };
    case 'failed':
      return {
        icon: 'close',
        bgColor: 'bg-red-500',
        textColor: 'text-white',
        borderColor: 'border-red-500',
        pulse: false,
      };
    default:
      return {
        icon: 'circle',
        bgColor: 'bg-slate-200 dark:bg-slate-700',
        textColor: 'text-slate-400',
        borderColor: 'border-slate-300 dark:border-slate-600',
        pulse: false,
      };
  }
}

/**
 * TimelineNode component
 */
export function TimelineNode({
  step,
  isExpanded,
  isCurrent,
  isLast: _isLast,
  onToggle,
}: TimelineNodeProps) {
  const [showAllThoughts, setShowAllThoughts] = useState(false);
  const statusConfig = getStatusConfig(step.status);
  
  const hasContent = step.thoughts.length > 0 || step.toolExecutions.length > 0;
  const displayThoughts = showAllThoughts ? step.thoughts : step.thoughts.slice(-3);

  return (
    <div
      className="relative pl-14 pb-6"
      data-step-number={step.stepNumber}
    >
      {/* Status Circle */}
      <div
        className={`absolute left-4 w-5 h-5 rounded-full flex items-center justify-center
          ${statusConfig.bgColor} ${statusConfig.textColor}
          ${statusConfig.pulse ? 'animate-pulse' : ''}
          ring-4 ring-white dark:ring-slate-900`}
      >
        {step.status === 'pending' ? (
          <span className="text-xs font-medium">{step.stepNumber + 1}</span>
        ) : (
          <MaterialIcon name={statusConfig.icon as any} size={12} />
        )}
      </div>

      {/* Node Content Card */}
      <div
        className={`bg-white dark:bg-surface-dark border rounded-xl overflow-hidden
          ${isCurrent ? 'border-blue-300 dark:border-blue-700 shadow-md' : 'border-slate-200 dark:border-border-dark'}
        `}
      >
        {/* Header - Clickable to expand/collapse */}
        <button
          onClick={onToggle}
          className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
        >
          <div className="flex items-center gap-3">
            <div>
              <h4 className="text-sm font-semibold text-slate-900 dark:text-white text-left">
                Step {step.stepNumber + 1}: {step.description}
              </h4>
              <div className="flex items-center gap-2 mt-0.5">
                {/* Status Badge */}
                <span
                  className={`text-xs font-medium ${
                    step.status === 'completed'
                      ? 'text-emerald-600 dark:text-emerald-400'
                      : step.status === 'running'
                      ? 'text-blue-600 dark:text-blue-400'
                      : step.status === 'failed'
                      ? 'text-red-600 dark:text-red-400'
                      : 'text-slate-400'
                  }`}
                >
                  {step.status === 'completed' && 'Completed'}
                  {step.status === 'running' && 'Running'}
                  {step.status === 'failed' && 'Failed'}
                  {step.status === 'pending' && 'Pending'}
                </span>
                
                {/* Duration */}
                {step.duration && (
                  <>
                    <span className="text-slate-300 dark:text-slate-600">•</span>
                    <span className="text-xs text-slate-500">
                      {formatDuration(step.duration)}
                    </span>
                  </>
                )}
                
                {/* Tool Count */}
                {step.toolExecutions.length > 0 && (
                  <>
                    <span className="text-slate-300 dark:text-slate-600">•</span>
                    <span className="text-xs text-slate-500">
                      {step.toolExecutions.length} tool{step.toolExecutions.length > 1 ? 's' : ''}
                    </span>
                  </>
                )}
              </div>
            </div>
          </div>

          {/* Expand/Collapse Icon */}
          {hasContent && (
            <MaterialIcon
              name={isExpanded ? 'expand_less' : 'expand_more'}
              size={20}
              className="text-slate-400"
            />
          )}
        </button>

        {/* Expanded Content */}
        {isExpanded && hasContent && (
          <div className="px-4 pb-4 space-y-4 border-t border-slate-100 dark:border-slate-800">
            {/* Thoughts Section */}
            {step.thoughts.length > 0 && (
              <div className="pt-4">
                <div className="flex items-center justify-between mb-2">
                  <h5 className="text-xs font-semibold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
                    <MaterialIcon name="psychology" size={14} />
                    Thinking Process
                  </h5>
                  {step.thoughts.length > 3 && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setShowAllThoughts(!showAllThoughts);
                      }}
                      className="text-xs text-primary hover:underline"
                    >
                      {showAllThoughts ? 'Show Less' : `Show All (${step.thoughts.length})`}
                    </button>
                  )}
                </div>
                <div className="space-y-2">
                  {displayThoughts.map((thought, idx) => (
                    <div
                      key={idx}
                      className="flex items-start gap-2 text-sm text-slate-600 dark:text-slate-400"
                    >
                      <MaterialIcon
                        name="chevron_right"
                        size={16}
                        className="text-slate-400 mt-0.5 flex-shrink-0"
                      />
                      <span className="break-words">{thought}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Tool Executions Section */}
            {step.toolExecutions.length > 0 && (
              <div className="pt-2">
                <h5 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                  <MaterialIcon name="build" size={14} />
                  Tool Executions
                </h5>
                <div className="space-y-3">
                  {step.toolExecutions.map((execution) => (
                    <ToolExecutionDetail
                      key={execution.id}
                      execution={execution}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default TimelineNode;
