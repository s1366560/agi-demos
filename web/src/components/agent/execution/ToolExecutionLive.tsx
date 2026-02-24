/**
 * ToolExecutionLive - Live tool execution display
 *
 * Shows tool execution in progress with pulsing animation and status.
 */

import { MaterialIcon } from '../shared';

export type ToolExecutionStatus = 'preparing' | 'running' | 'completed' | 'failed';

export interface ToolExecutionLiveProps {
  /** Name of the tool being executed */
  toolName: string;
  /** Current status */
  status?: ToolExecutionStatus | undefined;
  /** Tool input parameters */
  toolInput?: Record<string, unknown> | undefined;
  /** Execution mode */
  executionMode?: string | undefined;
  /** Result count (for search tools) */
  resultCount?: number | undefined;
  /** Whether to show details expanded */
  expanded?: boolean | undefined;
}

/**
 * ToolExecutionLive component
 *
 * @example
 * <ToolExecutionLive
 *   toolName="Memory Search"
 *   status="running"
 *   toolInput={{ query: "project trends", limit: 10 }}
 * />
 */
export function ToolExecutionLive({
  toolName,
  status = 'running',
  toolInput,
  executionMode = 'semantic',
  resultCount,
  expanded = true,
}: ToolExecutionLiveProps) {
  const getStatusBadge = () => {
    switch (status) {
      case 'preparing':
        return (
          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-semibold bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
            <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
            Preparing
          </span>
        );
      case 'running':
        return (
          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-semibold bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400">
            <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
            Running
          </span>
        );
      case 'completed':
        return (
          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-semibold bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400">
            <MaterialIcon name="check_circle" size={14} />
            Success
          </span>
        );
      case 'failed':
        return (
          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-semibold bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400">
            <MaterialIcon name="error" size={14} />
            Failed
          </span>
        );
    }
  };

  const getToolIcon = (name: string) => {
    const lowerName = name.toLowerCase();
    if (
      lowerName.includes('web_search') ||
      (lowerName.includes('web') && lowerName.includes('search'))
    )
      return 'language';
    if (
      lowerName.includes('web_scrape') ||
      lowerName.includes('scrape') ||
      lowerName.includes('web')
    )
      return 'public';
    if (lowerName.includes('search') || lowerName.includes('memory')) return 'search';
    if (lowerName.includes('entity')) return 'account_tree';
    if (lowerName.includes('episode')) return 'history';
    if (lowerName.includes('create')) return 'add_circle';
    if (lowerName.includes('graph') || lowerName.includes('query')) return 'hub';
    if (lowerName.includes('summary')) return 'summarize';
    return 'extension';
  };

  return (
    <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl overflow-hidden mb-4">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-center gap-3">
          {/* Tool Icon */}
          <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
            <MaterialIcon name={getToolIcon(toolName) as any} size={18} />
          </div>

          {/* Tool Name */}
          <div>
            <h4 className="text-sm font-semibold text-slate-900 dark:text-white">{toolName}</h4>
            {executionMode && <p className="text-xs text-slate-500">{executionMode}</p>}
          </div>
        </div>

        {/* Status Badge */}
        {getStatusBadge()}
      </div>

      {/* Content */}
      {expanded && (
        <div className="p-4 space-y-4">
          {/* Query Parameters */}
          {toolInput && (
            <div>
              <h5 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                Query Parameters
              </h5>
              <div className="bg-slate-900 dark:bg-slate-950 rounded-lg p-3 overflow-x-auto">
                <pre className="text-xs text-slate-300 font-mono">
                  {JSON.stringify(toolInput, null, 2)}
                </pre>
              </div>
            </div>
          )}

          {/* Execution Mode */}
          {executionMode && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-slate-600 dark:text-slate-400">Execution Mode</span>
              <span className="text-sm font-medium text-slate-900 dark:text-white">
                {executionMode}
              </span>
            </div>
          )}

          {/* Live Results (placeholder for running state) */}
          {status === 'running' && (
            <div className="border-2 border-dashed border-slate-300 dark:border-slate-700 rounded-lg p-6 text-center">
              <div className="flex flex-col items-center gap-3">
                <div className="w-12 h-12 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
                  <MaterialIcon name="search" size={24} className="text-slate-400" />
                </div>
                <div className="text-center">
                  <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
                    Scanning knowledge graph...
                  </p>
                  <p className="text-xs text-slate-500 mt-1">
                    Searching for relevant entities and relationships
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Results Summary (for completed state) */}
          {status === 'completed' && resultCount !== undefined && (
            <div className="flex items-center justify-between p-3 bg-emerald-50 dark:bg-emerald-900/20 rounded-lg">
              <div className="flex items-center gap-2">
                <MaterialIcon name="check_circle" size={18} className="text-emerald-500" />
                <span className="text-sm font-medium text-emerald-700 dark:text-emerald-400">
                  Search completed
                </span>
              </div>
              <span className="text-sm text-slate-600 dark:text-slate-400">
                {resultCount} results found
              </span>
            </div>
          )}

          {/* Error State */}
          {status === 'failed' && (
            <div className="flex items-center gap-2 p-3 bg-red-50 dark:bg-red-900/20 rounded-lg">
              <MaterialIcon name="error" size={18} className="text-red-500" />
              <span className="text-sm font-medium text-red-700 dark:text-red-400">
                Tool execution failed. Please try again.
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ToolExecutionLive;
