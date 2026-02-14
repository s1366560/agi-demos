/**
 * memstack-agent-ui - ExecutionTimeline Component
 *
 * Displays agent execution timeline with tool calls, thoughts, and status.
 *
 * @packageDocumentation
 */

import { memo, useState } from 'react';
import type { TimelineEvent } from '@memstack-agent-ui/core';

/**
 * Timeline step interface
 */
export interface TimelineStep {
  id: string;
  toolName: string;
  status: 'running' | 'success' | 'error';
  input?: Record<string, unknown>;
  output?: string | Record<string, unknown>;
  isError?: boolean;
  duration?: number;
  timestamp?: number;
}

/**
 * ExecutionTimeline component props
 */
export interface ExecutionTimelineProps {
  timeline: TimelineEvent[];
  isStreaming?: boolean;
  conversationId?: string;
  onUndoRequest?: (stepId: string, toolName: string) => void;
}

/**
 * Get tool icon based on tool name
 */
function getToolIcon(toolName: string): string {
  const name = toolName.toLowerCase();
  if (name.includes('terminal') || name.includes('shell') || name.includes('command')) {
    return '⌨';
  }
  if (name.includes('search') || name.includes('grep') || name.includes('find')) {
    return '🔍';
  }
  if (name.includes('read') || name.includes('write') || name.includes('file') || name.includes('edit')) {
    return '📄';
  }
  if (name.includes('web') || name.includes('browse') || name.includes('scrape')) {
    return '🌐';
  }
  if (name.includes('think') || name.includes('plan') || name.includes('reason')) {
    return '🧠';
  }
  return '🔧';
}

/**
 * Get tool label from tool name
 */
function getToolLabel(toolName: string): string {
  return toolName
    .replace(/_/g, ' ')
    .replace(/([A-Z])/g, ' $1')
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Format duration for display
 */
function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

/**
 * Individual timeline step component
 */
const TimelineStepItem = memo<{
  step: TimelineStep;
  isLast: boolean;
  defaultExpanded?: boolean;
  onUndoRequest?: (stepId: string, toolName: string) => void;
}>(({ step, isLast, defaultExpanded = false, onUndoRequest }) => {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const statusColor =
    step.status === 'running'
      ? 'text-blue-500'
      : step.status === 'success'
        ? 'text-emerald-500'
        : 'text-red-500';

  const statusBg =
    step.status === 'running'
      ? 'bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800/40'
      : step.status === 'success'
        ? 'bg-emerald-50 dark:bg-emerald-950 border border-emerald-200/60 dark:border-emerald-800/30'
        : 'bg-red-50 dark:bg-red-950 border border-red-200/60 dark:border-red-800/30';

  const statusIcon =
    step.status === 'running'
      ? '⟳'
      : step.status === 'success'
        ? '✓'
        : '✗';

  return (
    <div className="relative flex gap-2">
      {/* Timeline line + dot */}
      <div className="flex flex-col items-center flex-shrink-0">
        <div
          className={`w-6 h-6 rounded-full flex items-center justify-center border-2 ${
            step.status === 'running'
              ? 'border-blue-400 bg-blue-50 dark:bg-blue-950/50'
              : step.status === 'success'
                ? 'border-emerald-400 bg-emerald-50 dark:bg-emerald-950/50'
                : 'border-red-400 bg-red-50 dark:bg-red-950/50'
          }`}
        >
          {step.status === 'running' ? (
            <span className={`text-sm ${statusColor} animate-pulse`}>⟳</span>
          ) : (
            <span className="text-sm">{getToolIcon(step.toolName)}</span>
          )}
        </div>
        {!isLast && (
          <div className="w-px flex-1 min-h-[8px] bg-slate-200 dark:bg-slate-700" />
        )}
      </div>

      {/* Content */}
      <div className="flex-1 pb-1.5 min-w-0">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className={`w-full text-left rounded-md border px-2.5 py-1.5 transition-colors ${statusBg} hover:shadow-sm cursor-pointer`}
        >
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-slate-700 dark:text-slate-300 flex-1 truncate">
              {getToolLabel(step.toolName)}
            </span>
            {step.duration != null && (
              <span className="flex items-center gap-1 text-[10px] text-slate-400">
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3-3m0 0 0 0 6 6-6 6 0 0-0zm0 0 1.5a1.5 1.5 0 1 0 0 0 0 3 3 0 0 0 0 0 0 0 3z" />
                </svg>
                {formatDuration(step.duration)}
              </span>
            )}
            <span className={statusColor}>{statusIcon}</span>
            {onUndoRequest && step.status === 'success' && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onUndoRequest(step.id, step.toolName);
                }}
                className="ml-1 p-0.5 rounded hover:bg-slate-200 dark:hover:bg-slate-600 text-slate-400 hover:text-amber-500 transition-colors"
                title="Undo this action"
              >
                ↶
              </button>
            )}
          </div>
        </button>

        {expanded && step.input && Object.keys(step.input).length > 0 && (
          <div className="mt-1.5 bg-slate-50 dark:bg-slate-800/50 rounded-md p-2 border border-slate-200/60 dark:border-slate-700/40">
            <div className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">
              Input
            </div>
            <pre className="text-sm text-slate-600 dark:text-slate-300 font-mono whitespace-pre-wrap break-words overflow-x-auto max-h-[200px] overflow-y-auto">
              {JSON.stringify(step.input, null, 2)}
            </pre>
          </div>
        )}

        {expanded && step.output && (
          <div
            className={`rounded-md p-2 border ${
              step.isError
                ? 'bg-red-50 dark:bg-red-950/30 border border-red-200/60 dark:border-red-800/30'
                : 'bg-slate-50 dark:bg-slate-800/50 border border-slate-200/60 dark:border-slate-700/40'
            }`}
          >
            <div className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">
              Output
            </div>
            <pre
              className={`font-mono whitespace-pre-wrap break-words overflow-x-auto max-h-[200px] overflow-y-auto ${
                step.isError ? 'text-red-600 dark:text-red-400' : 'text-slate-600 dark:text-slate-300'
              }`}
            >
              {typeof step.output === 'string' ? step.output : JSON.stringify(step.output, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
});
TimelineStepItem.displayName = 'TimelineStepItem';

/**
 * ExecutionTimeline component
 */
export const ExecutionTimeline = memo<ExecutionTimelineProps>(
  ({ timeline, isStreaming, onUndoRequest }) => {
    const [collapsed, setCollapsed] = useState(false);

    // Convert timeline events to timeline steps
    const steps: TimelineStep[] = timeline.map((event) => ({
      id: event.id,
      toolName: event.type || 'unknown',
      status: 'success',
      input: event.data as Record<string, unknown>,
      output: event.data as string | Record<string, unknown>,
    }));

    if (steps.length === 0) return null;

    return (
      <div className="mb-2 rounded-md">
        {/* Summary header */}
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          className="flex items-center gap-2 w-full text-left mb-1.5 group cursor-pointer"
        >
          {collapsed ? (
            <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          ) : (
            <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          )}
          <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
            {steps.length} steps
          </span>
          {isStreaming && (
            <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 text-xs">
              Running
            </span>
          )}
        </button>

        {/* Timeline steps */}
        {!collapsed && (
          <div className="pl-1">
            {steps.map((step, i) => (
              <TimelineStepItem
                key={step.id}
                step={step}
                isLast={i === steps.length - 1}
                defaultExpanded={step.status === 'error'}
                onUndoRequest={onUndoRequest}
              />
            ))}
          </div>
        )}
      </div>
    );
  }
);
ExecutionTimeline.displayName = 'ExecutionTimeline';
