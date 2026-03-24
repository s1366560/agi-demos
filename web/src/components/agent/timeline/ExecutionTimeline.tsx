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
  AppWindow,
} from 'lucide-react';

import { formatDuration } from '../../../utils/date';
import { isAgentTool, AgentToolStepCard } from '../timeline-items/AgentToolCards';

import { useMCPAppOpen } from './useMCPAppOpen';

export interface TimelineStep {
  id: string;
  toolName: string;
  status: 'running' | 'success' | 'error';
  input?: Record<string, unknown> | undefined;
  output?: string | Record<string, unknown> | undefined;
  isError?: boolean | undefined;
  duration?: number | undefined;
  timestamp?: number | undefined;
  mcpUiMetadata?:
    | {
        resource_uri?: string | undefined;
        server_name?: string | undefined;
        app_id?: string | undefined;
        title?: string | undefined;
        project_id?: string | undefined;
      }
    | undefined;
}

interface ExecutionTimelineProps {
  steps: TimelineStep[];
  isStreaming?: boolean | undefined;
  conversationId?: string | undefined;
  defaultCollapsed?: boolean | undefined;
  onUndoRequest?: ((stepId: string, toolName: string) => void) | undefined;
}

const getToolIcon = (toolName: string, size = 13, className = '') => {
  const name = toolName.toLowerCase();
  if (name.includes('terminal') || name.includes('shell') || name.includes('command')) {
    return <Terminal size={size} className={className} />;
  }
  if (name.includes('search') || name.includes('grep') || name.includes('find')) {
    return <Search size={size} className={className} />;
  }
  if (
    name.includes('read') ||
    name.includes('write') ||
    name.includes('file') ||
    name.includes('edit')
  ) {
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

// eslint-disable-next-line react-refresh/only-export-components -- Utility function exported for reuse in related components
export { getToolLabel };

const getInputPreview = (input?: Record<string, unknown>, toolName?: string): string | null => {
  if (!input) return null;
  const name = (toolName ?? '').toLowerCase();

  // Write/Edit tools: show file path + line count
  if (name.includes('write') || name.includes('edit') || name.includes('patch')) {
    const filePath = (input.path ?? input.file_path ?? '') as string;
    const content = (input.content ?? input.new_content ?? input.text ?? '') as string;
    if (filePath) {
      const lineCount = content ? content.split('\n').length : 0;
      return lineCount > 0 ? `${filePath} (${String(lineCount)} lines)` : filePath;
    }
  }

  // Read tools: show file path
  if (name.includes('read')) {
    const filePath = (input.path ?? input.file_path ?? '') as string;
    if (filePath) return filePath;
  }

  // command: Bash/terminal tools
  if (input.command && typeof input.command === 'string') {
    return input.command.length > 80 ? input.command.slice(0, 77) + '...' : input.command;
  }
  // path: List/Glob tools
  if (input.path && typeof input.path === 'string') {
    return input.path;
  }
  // pattern: Glob/Grep tools
  if (input.pattern && typeof input.pattern === 'string') {
    return input.pattern.length > 80 ? input.pattern.slice(0, 77) + '...' : input.pattern;
  }
  // query: search tools
  if (input.query && typeof input.query === 'string') {
    return input.query.length > 80 ? input.query.slice(0, 77) + '...' : input.query;
  }
  // file_path: alternative path field
  if (input.file_path && typeof input.file_path === 'string') {
    return input.file_path;
  }
  // url: web tools
  if (input.url && typeof input.url === 'string') {
    return input.url.length > 80 ? input.url.slice(0, 77) + '...' : input.url;
  }
  // Fallback: show first string value from input
  for (const value of Object.values(input)) {
    if (typeof value === 'string' && value.length > 0) {
      return value.length > 80 ? value.slice(0, 77) + '...' : value;
    }
  }
  return null;
};

// Individual timeline step
const TimelineStepItem = memo<{
  step: TimelineStep;
  isLast: boolean;
  defaultExpanded?: boolean | undefined;
  onUndoRequest?: ((stepId: string, toolName: string) => void) | undefined;
}>(({ step, isLast, defaultExpanded = false, onUndoRequest }) => {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const { t } = useTranslation();
  const preview = getInputPreview(step.input, step.toolName);
  const openMCPApp = useMCPAppOpen(step);

  if (isAgentTool(step.toolName)) {
    return (
      <div className="relative flex gap-2 mb-0" style={{ minHeight: '24px' }}>
        <div className="flex flex-col items-center flex-shrink-0" style={{ width: '24px' }}>
          <div
            className={`
              w-6 h-6 rounded-full flex items-center justify-center border-2 flex-shrink-0 transition-colors duration-200
              ${
                step.status === 'running'
                  ? 'border-blue-400 bg-blue-50 dark:bg-blue-950/50'
                  : step.status === 'success'
                    ? 'border-emerald-400 bg-emerald-50 dark:bg-emerald-950/50'
                    : 'border-red-400 bg-red-50 dark:bg-red-950/50'
              }
            `}
            style={{ minWidth: '24px', minHeight: '24px' }}
          >
            {step.status === 'running' ? (
              <Loader2 size={11} className="text-blue-500 animate-spin motion-reduce:animate-none" />
            ) : (
              <span className="animate-fade-in flex items-center justify-center">
                <Brain
                  size={11}
                  className={step.status === 'success' ? 'text-emerald-500' : 'text-red-500'}
                />
              </span>
            )}
          </div>
          {!isLast && (
            <div className="w-px flex-1 min-h-[16px] bg-slate-200 dark:bg-slate-700 flex-shrink-0" />
          )}
        </div>
        <div className="flex-1 pb-1.5 min-w-0">
          <AgentToolStepCard
            toolName={step.toolName}
            {...(step.input !== undefined ? { input: step.input } : {})}
            {...(step.output !== undefined ? { output: step.output } : {})}
            status={step.status}
            {...(step.isError !== undefined ? { isError: step.isError } : {})}
            {...(step.duration !== undefined ? { duration: step.duration } : {})}
          />
        </div>
      </div>
    );
  }

  const statusColor =
    step.status === 'running'
      ? 'text-blue-500'
      : step.status === 'success'
        ? 'text-emerald-500'
        : 'text-red-500';

  const statusBg =
    step.status === 'running'
      ? 'bg-blue-50 dark:bg-blue-950 border-blue-200 dark:border-blue-800/40'
      : step.status === 'success'
        ? 'bg-emerald-50 dark:bg-emerald-950 border-emerald-200/60 dark:border-emerald-800/30'
        : 'bg-red-50 dark:bg-red-950 border-red-200/60 dark:border-red-800/30';

  const statusIcon =
    step.status === 'running' ? (
      <Loader2 size={14} className={`${statusColor} animate-spin motion-reduce:animate-none`} />
    ) : step.status === 'success' ? (
      <CheckCircle2 size={14} className={`${statusColor} animate-fade-in`} />
    ) : (
      <XCircle size={14} className={`${statusColor} animate-fade-in`} />
    );

  return (
    <div className="relative flex gap-2 mb-0" style={{ minHeight: '24px' }}>
      {/* Timeline line + dot */}
      <div className="flex flex-col items-center flex-shrink-0" style={{ width: '24px' }}>
        <div
          className={`
            w-6 h-6 rounded-full flex items-center justify-center border-2 flex-shrink-0 transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-300
            ${
              step.status === 'running'
                ? 'border-blue-400 bg-blue-50 dark:bg-blue-950/50'
                : step.status === 'success'
                  ? 'border-emerald-400 bg-emerald-50 dark:bg-emerald-950/50'
                  : 'border-red-400 bg-red-50 dark:bg-red-950/50'
            }
          `}
          style={{ minWidth: '24px', minHeight: '24px' }}
        >
          {step.status === 'running' ? (
            <Loader2 size={11} className="text-blue-500 animate-spin motion-reduce:animate-none" />
          ) : (
            <span className="animate-fade-in flex items-center justify-center">
              {getToolIcon(step.toolName, 11, statusColor)}
            </span>
          )}
        </div>
        {!isLast && (
          <div className="w-px flex-1 min-h-[16px] bg-slate-200 dark:bg-slate-700 flex-shrink-0" />
        )}
      </div>

      {/* Content */}
      <div className="flex-1 pb-1.5 min-w-0 flex flex-col">
        <button
          type="button"
          onClick={() => {
            setExpanded((v) => !v);
          }}
          className={`
            w-full text-left rounded-md border px-2.5 py-1.5 transition-colors duration-300
            focus:outline-none focus:ring-2 focus:ring-primary/50 focus:ring-offset-1
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
                className="ml-1 p-1.5 rounded hover:bg-slate-200 dark:hover:bg-slate-600 text-slate-400 hover:text-amber-500 transition-colors focus:outline-none focus:ring-2 focus:ring-amber-500/50 min-w-[28px] min-h-[28px] flex items-center justify-center"
                aria-label={t('agent.undo.button', 'Undo this action')}
                title={t('agent.undo.button', 'Undo this action')}
              >
                <Undo2 size={14} />
              </button>
            )}
            {(step.input || step.output) &&
              (expanded ? (
                <ChevronDown size={12} className="text-slate-400" />
              ) : (
                <ChevronRight size={12} className="text-slate-400" />
              ))}
          </div>
          {!expanded && preview && (
            <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-400 font-mono truncate">
              {preview}
            </div>
          )}
        </button>

        {/* MCP App "Open App" button - visible without expanding */}
        {step.toolName.startsWith('mcp__') && step.status === 'success' && !step.isError && (
          <button
            type="button"
            onClick={() => {
              void openMCPApp();
            }}
            className="flex items-center gap-1.5 px-2.5 py-1 mt-1 text-xs rounded-md bg-violet-50 dark:bg-violet-950/30 text-violet-600 dark:text-violet-400 hover:bg-violet-100 dark:hover:bg-violet-900/40 border border-violet-200/60 dark:border-violet-800/30 transition-colors focus:outline-none focus:ring-2 focus:ring-violet-500/50 focus:ring-offset-1"
          >
            <AppWindow size={12} />
            {t('agent.timeline.openApp', 'Open App')}
          </button>
        )}

        {expanded && (
          <div className="mt-1.5 space-y-1.5 text-xs">
            {step.input && Object.keys(step.input).length > 0 && (
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded-md p-2 border border-slate-200/60 dark:border-slate-700/40">
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
                className={`rounded-md p-2 border ${
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
  ({ steps, isStreaming, defaultCollapsed, onUndoRequest }) => {
    const { t } = useTranslation();
    const [collapsed, setCollapsed] = useState(defaultCollapsed ?? false);

    const summary = useMemo(() => {
      const total = steps.length;
      const completed = steps.filter((s) => s.status === 'success').length;
      const failed = steps.filter((s) => s.status === 'error').length;
      const running = steps.filter((s) => s.status === 'running').length;
      return { total, completed, failed, running };
    }, [steps]);

    if (steps.length === 0) return null;

    return (
      <div className="pb-2 rounded-md">
        {/* Summary header */}
        <button
          type="button"
          onClick={() => {
            setCollapsed((v) => !v);
          }}
          className="flex items-center gap-2 w-full text-left mb-1.5 group cursor-pointer focus:outline-none focus:ring-2 focus:ring-primary/50 focus:ring-offset-1 rounded"
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
            <Loader2 size={12} className="text-blue-500 animate-spin motion-reduce:animate-none" />
          )}
        </button>

        {/* Timeline steps */}
        {!collapsed && (
          <div className="pl-1 pt-0.5" style={{ display: 'flow-root' }}>
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
