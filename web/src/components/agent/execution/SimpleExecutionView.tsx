/**
 * SimpleExecutionView - Simplified tool execution display
 *
 * Used when there's no work plan but tool executions exist.
 * Shows a simple vertical list of tool executions.
 */

import type { ToolExecution } from '../../../types/agent';
import { MaterialIcon } from '../shared';
import { ToolExecutionDetail } from './ToolExecutionDetail';

export interface SimpleExecutionViewProps {
  /** Tool executions to display */
  toolExecutions: ToolExecution[];
  /** Whether streaming is in progress */
  isStreaming: boolean;
}

/**
 * SimpleExecutionView component
 *
 * @example
 * <SimpleExecutionView
 *   toolExecutions={toolExecutionHistory}
 *   isStreaming={isStreaming}
 * />
 */
export function SimpleExecutionView({
  toolExecutions,
  isStreaming,
}: SimpleExecutionViewProps) {
  if (toolExecutions.length === 0) {
    return null;
  }

  const completedCount = toolExecutions.filter((t) => t.status === 'success').length;
  const runningCount = toolExecutions.filter((t) => t.status === 'running').length;
  const failedCount = toolExecutions.filter((t) => t.status === 'failed').length;

  return (
    <div className="w-full mb-4">
      {/* Header Card */}
      <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl p-4 mb-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
              <MaterialIcon name="build" size={20} className="text-primary" />
            </div>
            <div>
              <h3 className="font-semibold text-slate-900 dark:text-white">
                Tool Executions
              </h3>
              <p className="text-sm text-slate-500">
                {toolExecutions.length} tool{toolExecutions.length > 1 ? 's' : ''} used
              </p>
            </div>
          </div>

          {/* Status Summary */}
          <div className="flex items-center gap-2">
            {completedCount > 0 && (
              <span className="px-2 py-1 rounded-full text-xs font-medium bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400">
                {completedCount} completed
              </span>
            )}
            {runningCount > 0 && (
              <span className="px-2 py-1 rounded-full text-xs font-medium bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
                {runningCount} running
              </span>
            )}
            {failedCount > 0 && (
              <span className="px-2 py-1 rounded-full text-xs font-medium bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400">
                {failedCount} failed
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Tool Execution List */}
      <div className="space-y-3">
        {toolExecutions.map((execution) => (
          <ToolExecutionDetail
            key={execution.id}
            execution={execution}
          />
        ))}
      </div>

      {/* Streaming Indicator */}
      {isStreaming && runningCount === 0 && (
        <div className="mt-4 flex items-center justify-center py-4 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl">
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <span className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            Processing...
          </div>
        </div>
      )}
    </div>
  );
}

export default SimpleExecutionView;
