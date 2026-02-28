/**
 * RightPanel - Side panel with Tasks
 *
 * Features:
 * - Agent-managed task checklist (DB-persistent, SSE-streamed)
 * - Execution insights (routing + selection + policy)
 * - Draggable resize support
 */

import { useCallback, memo, useState } from 'react';

import { Filter, ListTodo, Route, X } from 'lucide-react';

import { LazyButton } from '@/components/ui/lazyAntd';

import { ResizeHandle } from './RightPanelComponents';
import { TaskList } from './TaskList';

import type {
  AgentTask,
  ExecutionNarrativeEntry,
  ExecutionPathDecidedEventData,
  PolicyFilteredEventData,
  SelectionTraceEventData,
  ToolsetChangedEventData,
} from '../../types/agent';

export interface RightPanelProps {
  tasks?: AgentTask[] | undefined;
  sandboxId?: string | null | undefined;
  executionPathDecision?: ExecutionPathDecidedEventData | null | undefined;
  selectionTrace?: SelectionTraceEventData | null | undefined;
  policyFiltered?: PolicyFilteredEventData | null | undefined;
  executionNarrative?: ExecutionNarrativeEntry[] | undefined;
  latestToolsetChange?: ToolsetChangedEventData | null | undefined;
  onClose?: (() => void) | undefined;
  onFileClick?: ((filePath: string) => void) | undefined;
  collapsed?: boolean | undefined;
  width?: number | undefined;
  onWidthChange?: ((width: number) => void) | undefined;
  minWidth?: number | undefined;
  maxWidth?: number | undefined;
}

type PanelTab = 'tasks' | 'insights';

interface ExecutionInsightsProps {
  executionPathDecision?: ExecutionPathDecidedEventData | null | undefined;
  selectionTrace?: SelectionTraceEventData | null | undefined;
  policyFiltered?: PolicyFilteredEventData | null | undefined;
  executionNarrative?: ExecutionNarrativeEntry[] | undefined;
  latestToolsetChange?: ToolsetChangedEventData | null | undefined;
}

const ExecutionInsights = memo<ExecutionInsightsProps>(
  ({
    executionPathDecision,
    selectionTrace,
    policyFiltered,
    executionNarrative,
    latestToolsetChange,
  }) => {
    const metadataLane =
      executionPathDecision?.metadata &&
      typeof executionPathDecision.metadata['domain_lane'] === 'string'
        ? executionPathDecision.metadata['domain_lane']
        : null;
    const lane = metadataLane ?? selectionTrace?.domain_lane ?? policyFiltered?.domain_lane ?? null;
    const traceId =
      executionPathDecision?.trace_id ??
      selectionTrace?.trace_id ??
      policyFiltered?.trace_id ??
      null;
    const narrativeEntries = (executionNarrative ?? []).slice(-8).reverse();

    if (
      !executionPathDecision &&
      !selectionTrace &&
      !policyFiltered &&
      !latestToolsetChange &&
      narrativeEntries.length === 0
    ) {
      return (
        <div
          data-testid="execution-insights"
          className="rounded-lg border border-slate-200/60 dark:border-slate-700/50 p-4 text-sm text-slate-500 dark:text-slate-400"
        >
          Execution diagnostics will appear after the agent makes routing and tool-selection
          decisions.
        </div>
      );
    }

    return (
      <div
        data-testid="execution-insights"
        className="space-y-3 rounded-lg border border-slate-200/60 dark:border-slate-700/50 p-3"
      >
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          Execution Insights
        </h3>

        {executionPathDecision ? (
          <div className="rounded-md bg-slate-50 dark:bg-slate-800/50 p-3">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
              <Route size={13} />
              <span>Routing</span>
            </div>
            <div className="mt-1 text-sm text-slate-800 dark:text-slate-100">
              Path: <span className="font-medium">{executionPathDecision.path}</span> · Confidence:{' '}
              <span className="font-medium">{executionPathDecision.confidence.toFixed(2)}</span>
            </div>
            <div className="mt-1 text-xs text-slate-600 dark:text-slate-300">
              {executionPathDecision.reason}
            </div>
            {executionPathDecision.route_id ? (
              <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                route_id: <span className="font-mono">{executionPathDecision.route_id}</span>
              </div>
            ) : null}
            {traceId ? (
              <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                trace_id: <span className="font-mono">{traceId}</span>
              </div>
            ) : null}
            {lane ? (
              <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                domain_lane: <span className="font-medium">{lane}</span>
              </div>
            ) : null}
          </div>
        ) : null}

        {selectionTrace ? (
          <div className="rounded-md bg-slate-50 dark:bg-slate-800/50 p-3">
            <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Selection
            </div>
            <div className="mt-1 text-sm text-slate-800 dark:text-slate-100">
              {selectionTrace.final_count}/{selectionTrace.initial_count} tools kept · removed{' '}
              {selectionTrace.removed_total}
            </div>
            <div className="mt-1 text-xs text-slate-600 dark:text-slate-300">
              {selectionTrace.stages.length} stage(s) executed
            </div>
            {typeof selectionTrace.tool_budget === 'number' ? (
              <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                tool_budget: <span className="font-medium">{selectionTrace.tool_budget}</span>
              </div>
            ) : null}
          </div>
        ) : null}

        {policyFiltered ? (
          <div className="rounded-md bg-slate-50 dark:bg-slate-800/50 p-3">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
              <Filter size={13} />
              <span>Policy</span>
            </div>
            <div className="mt-1 text-sm text-slate-800 dark:text-slate-100">
              Filtered {policyFiltered.removed_total} tool(s) across {policyFiltered.stage_count}{' '}
              stage(s)
            </div>
            {policyFiltered.budget_exceeded_stages?.length ? (
              <div className="mt-1 text-[11px] text-amber-600 dark:text-amber-400">
                budget_exceeded: {policyFiltered.budget_exceeded_stages.join(', ')}
              </div>
            ) : null}
          </div>
        ) : null}

        {latestToolsetChange ? (
          <div className="rounded-md bg-slate-50 dark:bg-slate-800/50 p-3">
            <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Toolset
            </div>
            <div className="mt-1 text-sm text-slate-800 dark:text-slate-100">
              {latestToolsetChange.action || 'update'}
              {latestToolsetChange.plugin_name ? ` ${latestToolsetChange.plugin_name}` : ''}
            </div>
            <div className="mt-1 text-xs text-slate-600 dark:text-slate-300">
              refresh: {latestToolsetChange.refresh_status || 'not_applicable'}
              {typeof latestToolsetChange.refreshed_tool_count === 'number'
                ? ` (${latestToolsetChange.refreshed_tool_count} tools)`
                : ''}
            </div>
            {latestToolsetChange.trace_id ? (
              <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                trace_id: <span className="font-mono">{latestToolsetChange.trace_id}</span>
              </div>
            ) : null}
          </div>
        ) : null}

        {narrativeEntries.length ? (
          <div
            className="rounded-md bg-slate-50 dark:bg-slate-800/50 p-3"
            data-testid="execution-narrative"
          >
            <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Execution Narrative
            </div>
            <div className="mt-2 space-y-2">
              {narrativeEntries.map((entry) => (
                <div
                  key={entry.id}
                  className="rounded border border-slate-200/70 dark:border-slate-700/70 p-2"
                >
                  <div className="text-[11px] uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    {entry.stage}
                  </div>
                  <div className="text-xs text-slate-700 dark:text-slate-200">{entry.summary}</div>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    );
  }
);

ExecutionInsights.displayName = 'ExecutionInsights';

export const RightPanel = memo<RightPanelProps>(
  ({
    tasks = [],
    executionPathDecision,
    selectionTrace,
    policyFiltered,
    executionNarrative,
    latestToolsetChange,
    onClose,
    collapsed,
    width = 360,
    onWidthChange,
    minWidth = 280,
    maxWidth = 600,
  }) => {
    const hasInsights = Boolean(
      executionPathDecision ||
      selectionTrace ||
      policyFiltered ||
      latestToolsetChange ||
      (executionNarrative && executionNarrative.length > 0)
    );
    const [preferredTab, setPreferredTab] = useState<PanelTab>(
      hasInsights && tasks.length === 0 ? 'insights' : 'tasks'
    );
    const activeTab: PanelTab =
      preferredTab === 'insights' && !hasInsights ? 'tasks' : preferredTab;

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
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-100 to-violet-100 dark:from-purple-900/30 dark:to-violet-900/20 flex items-center justify-center">
                <ListTodo size={16} className="text-purple-600 dark:text-purple-400" />
              </div>
              <div className="flex flex-col min-w-0">
                <h2 className="font-semibold text-slate-900 dark:text-slate-100 leading-tight">
                  Tasks
                </h2>
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {tasks.length} item{tasks.length === 1 ? '' : 's'}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <div className="inline-flex items-center rounded-lg border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-50 dark:bg-slate-800/70">
                <button
                  type="button"
                  onClick={() => {
                    setPreferredTab('tasks');
                  }}
                  className={`px-2 py-1 text-xs rounded-md transition-colors ${
                    activeTab === 'tasks'
                      ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100'
                      : 'text-slate-500 dark:text-slate-400'
                  }`}
                >
                  Tasks
                </button>
                <button
                  type="button"
                  onClick={() => hasInsights && setPreferredTab('insights')}
                  disabled={!hasInsights}
                  className={`px-2 py-1 text-xs rounded-md transition-colors ${
                    activeTab === 'insights'
                      ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100'
                      : 'text-slate-500 dark:text-slate-400'
                  } ${!hasInsights ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  Insights
                </button>
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
          </div>

          {activeTab === 'insights' ? (
            <div className="flex-1 overflow-y-auto p-3">
              <ExecutionInsights
                executionPathDecision={executionPathDecision}
                selectionTrace={selectionTrace}
                policyFiltered={policyFiltered}
                executionNarrative={executionNarrative}
                latestToolsetChange={latestToolsetChange}
              />
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto">
              <TaskList tasks={tasks} />
            </div>
          )}
        </div>
      </div>
    );
  }
);

RightPanel.displayName = 'RightPanel';

export default RightPanel;
