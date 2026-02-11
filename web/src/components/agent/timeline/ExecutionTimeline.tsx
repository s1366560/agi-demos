/**
 * ExecutionTimeline - Visual vertical timeline for agent execution steps
 *
 * Groups consecutive act/observe events into a collapsible timeline view.
 * Shows status indicators, durations, and contextual progress messages.
 *
 * Inspired by Devin/Windsurf Cascade action timelines.
 */

import { memo, useState, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import {
  Brain,
  Terminal,
  Search,
  FileText,
  Globe,
  CheckCircle2,
  XCircle,
  Loader2,
  ChevronDown,
  ChevronRight,
  Clock,
  Wrench,
  Undo2,
} from 'lucide-react';

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

interface ExecutionTimelineProps {
  steps: TimelineStep[];
  isStreaming?: boolean;
  conversationId?: string;
  onUndoRequest?: (stepId: string, toolName: string) => void;
}

const getToolIcon = (toolName: string, size = 13, className = '') => {
  const name = toolName.toLowerCase();
  if (name.includes('terminal') || name.includes('shell') || name.includes('command')) {
    return <Terminal size={size} className={className} />;
  }
  if (name.includes('search') || name.includes('grep') || name.includes('find')) {
    return <Search size={size} className={className} />;
  }
  if (name.includes('read') || name.includes('write') || name.includes('file') || name.includes('edit')) {
    return <FileText size={size} className={className} />;
  }
  if (name.includes('web') || name.includes('browse') || name.includes('scrape')) {
    return <Globe size={size} className={className} />;
  }
  if (name.includes('think') || name.includes('plan') || name.includes('reason')) {
    return <Brain size={size} className={className} />;
  }
  return <Wrench size={size} className={className} />;
};

const getToolLabel = (toolName: string): string => {
  return toolName
    .replace(/_/g, ' ')
    .replace(/([A-Z])/g, ' $1')
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
};

const formatDuration = (ms: number): string => {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
};

const getInputPreview = (input?: Record<string, unknown>): string | null => {
  if (!input) return null;
  if (input.command && typeof input.command === 'string') {
    return input.command.length > 60 ? input.command.slice(0, 57) + '...' : input.command;
  }
  if (input.path && typeof input.path === 'string') {
    return input.path;
  }
  if (input.query && typeof input.query === 'string') {
    return input.query.length > 60 ? input.query.slice(0, 57) + '...' : input.query;
  }
  return null;
};

// Individual timeline step
const TimelineStepItem = memo<{
  step: TimelineStep;
  isLast: boolean;
  defaultExpanded?: boolean;
  onUndoRequest?: (stepId: string, toolName: string) => void;
}>(({ step, isLast, defaultExpanded = false, onUndoRequest }) => {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const { t } = useTranslation();
  const preview = getInputPreview(step.input);

  const statusColor =
    step.status === 'running'
      ? 'text-blue-500'
      : step.status === 'success'
        ? 'text-emerald-500'
        : 'text-red-500';

  const statusBg =
    step.status === 'running'
      ? 'bg-blue-50 dark:bg-blue-950/30 border-blue-200 dark:border-blue-800/40'
      : step.status === 'success'
        ? 'bg-emerald-50/50 dark:bg-emerald-950/20 border-emerald-200/60 dark:border-emerald-800/30'
        : 'bg-red-50/50 dark:bg-red-950/20 border-red-200/60 dark:border-red-800/30';

  const statusIcon =
    step.status === 'running'
      ? <Loader2 size={14} className={`${statusColor} animate-spin`} />
      : step.status === 'success'
        ? <CheckCircle2 size={14} className={statusColor} />
        : <XCircle size={14} className={statusColor} />;

  return (
    <div className="relative flex gap-3">
      {/* Timeline line + dot */}
      <div className="flex flex-col items-center flex-shrink-0">
        <div
          className={`
            w-7 h-7 rounded-full flex items-center justify-center border-2
            ${step.status === 'running'
              ? 'border-blue-400 bg-blue-50 dark:bg-blue-950/50'
              : step.status === 'success'
                ? 'border-emerald-400 bg-emerald-50 dark:bg-emerald-950/50'
                : 'border-red-400 bg-red-50 dark:bg-red-950/50'
            }
          `}
        >
          {step.status === 'running' ? (
            <Loader2 size={13} className="text-blue-500 animate-spin" />
          ) : (
            getToolIcon(step.toolName, 13, statusColor)
          )}
        </div>
        {!isLast && (
          <div className="w-px flex-1 min-h-[16px] bg-slate-200 dark:bg-slate-700" />
        )}
      </div>

      {/* Content */}
      <div className="flex-1 pb-3 min-w-0">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className={`
            w-full text-left rounded-lg border px-3 py-2 transition-colors
            ${statusBg}
            hover:shadow-sm cursor-pointer
          `}
        >
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-slate-700 dark:text-slate-300 flex-1 truncate">
              {getToolLabel(step.toolName)}
            </span>
            {step.duration != null && (
              <span className="flex items-center gap-1 text-[10px] text-slate-400">
                <Clock size={10} />
                {formatDuration(step.duration)}
              </span>
            )}
            {statusIcon}
            {onUndoRequest && step.status === 'success' && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onUndoRequest(step.id, step.toolName);
                }}
                className="ml-1 p-0.5 rounded hover:bg-slate-200 dark:hover:bg-slate-600 text-slate-400 hover:text-amber-500 transition-colors"
                title={t('agent.undo.button', 'Undo this action')}
              >
                <Undo2 size={12} />
              </button>
            )}
            {(step.input || step.output) && (
              expanded
                ? <ChevronDown size={12} className="text-slate-400" />
                : <ChevronRight size={12} className="text-slate-400" />
            )}
          </div>
          {!expanded && preview && (
            <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-400 font-mono truncate">
              {preview}
            </div>
          )}
        </button>

        {expanded && (
          <div className="mt-2 space-y-2 text-xs">
            {step.input && Object.keys(step.input).length > 0 && (
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded-md p-2.5 border border-slate-200/60 dark:border-slate-700/40">
                <div className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">
                  {t('agent.timeline.input', 'Input')}
                </div>
                <pre className="text-slate-600 dark:text-slate-300 font-mono whitespace-pre-wrap break-words overflow-x-auto max-h-[200px] overflow-y-auto">
                  {JSON.stringify(step.input, null, 2)}
                </pre>
              </div>
            )}
            {step.output && (
              <div
                className={`rounded-md p-2.5 border ${
                  step.isError
                    ? 'bg-red-50 dark:bg-red-950/30 border-red-200/60 dark:border-red-800/30'
                    : 'bg-slate-50 dark:bg-slate-800/50 border-slate-200/60 dark:border-slate-700/40'
                }`}
              >
                <div className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">
                  {t('agent.timeline.output', 'Output')}
                </div>
                <pre
                  className={`font-mono whitespace-pre-wrap break-words overflow-x-auto max-h-[200px] overflow-y-auto ${
                    step.isError
                      ? 'text-red-600 dark:text-red-400'
                      : 'text-slate-600 dark:text-slate-300'
                  }`}
                >
                  {typeof step.output === 'string'
                    ? step.output
                    : JSON.stringify(step.output, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
});
TimelineStepItem.displayName = 'TimelineStepItem';

// Main timeline component
export const ExecutionTimeline = memo<ExecutionTimelineProps>(
  ({ steps, isStreaming, onUndoRequest }) => {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(false);

  const summary = useMemo(() => {
    const total = steps.length;
    const completed = steps.filter((s) => s.status === 'success').length;
    const failed = steps.filter((s) => s.status === 'error').length;
    const running = steps.filter((s) => s.status === 'running').length;
    return { total, completed, failed, running };
  }, [steps]);

  if (steps.length === 0) return null;

  return (
    <div className="mb-4">
      {/* Summary header */}
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        className="flex items-center gap-2 w-full text-left mb-2 group cursor-pointer"
      >
        {collapsed ? (
          <ChevronRight size={14} className="text-slate-400" />
        ) : (
          <ChevronDown size={14} className="text-slate-400" />
        )}
        <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
          {summary.running > 0
            ? t('agent.timeline.running', 'Running {{count}} tools...', {
                count: summary.running,
              })
            : t('agent.timeline.completed', '{{completed}}/{{total}} steps completed', {
                completed: summary.completed,
                total: summary.total,
              })}
        </span>
        {summary.failed > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 rounded-full">
            {summary.failed} {t('agent.timeline.failed', 'failed')}
          </span>
        )}
        {isStreaming && summary.running > 0 && (
          <Loader2 size={12} className="text-blue-500 animate-spin" />
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
});
ExecutionTimeline.displayName = 'ExecutionTimeline';
