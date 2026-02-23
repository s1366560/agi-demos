/**
 * RightPanel - Side panel with Tasks
 *
 * Features:
 * - Agent-managed task checklist (DB-persistent, SSE-streamed)
 * - Draggable resize support
 */

import { useCallback, memo } from 'react';

import { X, ListTodo, Route, Filter } from 'lucide-react';

import { LazyButton } from '@/components/ui/lazyAntd';

import { ResizeHandle } from './RightPanelComponents';
import { TaskList } from './TaskList';

import type {
  AgentTask,
  ExecutionPathDecidedEventData,
  SelectionTraceEventData,
  PolicyFilteredEventData,
} from '../../types/agent';

export interface RightPanelProps {
  tasks?: AgentTask[];
  executionPathDecision?: ExecutionPathDecidedEventData | null;
  selectionTrace?: SelectionTraceEventData | null;
  policyFiltered?: PolicyFilteredEventData | null;
  sandboxId?: string | null;
  onClose?: () => void;
  onFileClick?: (filePath: string) => void;
  collapsed?: boolean;
  width?: number;
  onWidthChange?: (width: number) => void;
  minWidth?: number;
  maxWidth?: number;
}

export const RightPanel = memo<RightPanelProps>(
  ({
    tasks = [],
    executionPathDecision = null,
    selectionTrace = null,
    policyFiltered = null,
    onClose,
    collapsed,
    width = 360,
    onWidthChange,
    minWidth = 280,
    maxWidth = 600,
  }) => {
    const handleResize = useCallback(
      (delta: number) => {
        if (!onWidthChange) return;
        const newWidth = Math.max(minWidth, Math.min(maxWidth, width - delta));
        onWidthChange(newWidth);
      },
      [width, onWidthChange, minWidth, maxWidth]
    );

    if (collapsed) {
      return null;
    }

    const domainLane =
      (executionPathDecision?.metadata?.domain_lane as string | undefined) ??
      selectionTrace?.domain_lane ??
      policyFiltered?.domain_lane ??
      null;
    const hasInsights = Boolean(executionPathDecision || selectionTrace || policyFiltered);

    return (
      <div
        className="h-full w-full flex bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm relative"
        data-testid="right-panel"
      >
        {onWidthChange ? (
          <ResizeHandle onResize={handleResize} direction="horizontal" position="left" />
        ) : null}

        <div className="flex-1 flex flex-col min-w-0">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200/60 dark:border-slate-700/50">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-100 to-violet-100 dark:from-purple-900/30 dark:to-violet-900/20 flex items-center justify-center">
                <ListTodo size={16} className="text-purple-600 dark:text-purple-400" />
              </div>
              <h2 className="font-semibold text-slate-900 dark:text-slate-100">Tasks</h2>
            </div>
            <div className="flex items-center gap-1">
              {onClose ? (
                <LazyButton
                  type="text"
                  size="small"
                  icon={<X size={18} />}
                  onClick={onClose}
                  className="text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-all"
                  data-testid="close-button"
                />
              ) : null}
            </div>
          </div>

          {hasInsights ? (
            <div
              className="px-4 py-3 border-b border-slate-200/60 dark:border-slate-700/50 space-y-2"
              data-testid="execution-insights"
            >
              <div className="text-xs font-semibold text-slate-700 dark:text-slate-200">
                Execution Insights
              </div>
              {executionPathDecision ? (
                <div className="flex items-start gap-2 text-xs text-slate-600 dark:text-slate-300">
                  <Route
                    size={14}
                    className="mt-0.5 text-blue-500 dark:text-blue-400 flex-shrink-0"
                  />
                  <div>
                    <span className="font-medium">Path:</span>{' '}
                    {executionPathDecision.path.replace(/_/g, ' ')} (
                    {executionPathDecision.confidence.toFixed(2)})
                    {domainLane ? (
                      <span className="ml-1 text-slate-500">· lane {domainLane}</span>
                    ) : null}
                  </div>
                </div>
              ) : null}
              {selectionTrace ? (
                <div className="text-xs text-slate-600 dark:text-slate-300">
                  <span className="font-medium">Selection:</span> {selectionTrace.final_count}/
                  {selectionTrace.initial_count} tools kept across {selectionTrace.stages.length}{' '}
                  stages
                </div>
              ) : null}
              {policyFiltered && policyFiltered.removed_total > 0 ? (
                <div className="flex items-start gap-2 text-xs text-slate-600 dark:text-slate-300">
                  <Filter
                    size={14}
                    className="mt-0.5 text-amber-500 dark:text-amber-400 flex-shrink-0"
                  />
                  <div>
                    <span className="font-medium">Policy:</span> filtered{' '}
                    {policyFiltered.removed_total} tools
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}

          {/* Task List */}
          <div className="flex-1 overflow-y-auto">
            <TaskList tasks={tasks} />
          </div>
        </div>
      </div>
    );
  }
);

RightPanel.displayName = 'RightPanel';

export default RightPanel;
