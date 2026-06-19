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
  Loader2,
  ChevronDown,
  ChevronRight,
  Wrench,
  Undo2,
  AppWindow,
} from 'lucide-react';

import { formatDuration } from '../../../utils/date';
import { MultiSourceResultsCard } from '../results/MultiSourceResultsCard';
import { AgentToolStepCard } from '../timeline-items/AgentToolCards';
import { isAgentTool } from '../timeline-items/agentToolNames';

import { getToolLabel } from './toolLabels';
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
  todoTitle?: string | undefined;
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
  onAgentSessionSelect?: ((sessionId: string) => void) | undefined;
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

const toSafeDomId = (value: string): string => value.replace(/[^A-Za-z0-9_-]/g, '-');

const getPathName = (path: string): string => {
  const segments = path.split(/[\\/]/).filter(Boolean);
  return segments.at(-1) ?? path;
};

const truncateMiddle = (value: string, maxLength = 120): string => {
  if (value.length <= maxLength) return value;
  const headLength = Math.ceil((maxLength - 3) * 0.62);
  const tailLength = Math.floor((maxLength - 3) * 0.38);
  return `${value.slice(0, headLength)}...${value.slice(value.length - tailLength)}`;
};

const TOOL_PREVIEW_KEYS = [
  'command',
  'cmd',
  'path',
  'file_path',
  'pattern',
  'query',
  'url',
  'report',
  'summary',
  'message',
  'content',
  'text',
  'title',
  'status',
  'result',
  'output',
];

const normalizePreviewText = (value: string): string => {
  return (
    value
      .split('\n')
      .map((line) => line.trim())
      .find((line) => line.length > 0) ?? ''
  );
};

const getPreviewFromUnknown = (value: unknown): string | null => {
  if (typeof value === 'string') {
    const text = normalizePreviewText(value);
    return text ? truncateMiddle(text) : null;
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      const preview = getPreviewFromUnknown(item);
      if (preview) return preview;
    }
    return null;
  }

  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    for (const key of TOOL_PREVIEW_KEYS) {
      const preview = getPreviewFromUnknown(record[key]);
      if (preview) return preview;
    }
  }

  return null;
};

type ToolActionKind = 'read' | 'write' | 'command' | 'search' | 'open' | 'todo' | 'tool';

const SUMMARY_LIST_SEPARATOR = ', ';
const SUMMARY_DETAIL_SEPARATOR = ': ';

interface ToolActionSummaryItem {
  kind: ToolActionKind;
  label: string;
}

const getRecordFromUnknown = (value: unknown): Record<string, unknown> | null => {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }

  if (typeof value === 'string') {
    const text = value.trim();
    if (!text.startsWith('{') && !text.startsWith('[')) return null;
    try {
      const parsed: unknown = JSON.parse(text);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        ? (parsed as Record<string, unknown>)
        : null;
    } catch {
      return null;
    }
  }

  return null;
};

const getTodosFromRecord = (record: Record<string, unknown> | null): Record<string, unknown>[] => {
  const todos = record?.todos;
  return Array.isArray(todos)
    ? todos.filter((todo): todo is Record<string, unknown> =>
        Boolean(todo && typeof todo === 'object')
      )
    : [];
};

const getTodoTitle = (todo: Record<string, unknown>): string | null => {
  const title = todo.content ?? todo.title ?? todo.task ?? todo.description ?? todo.name;
  return typeof title === 'string' && title.trim() ? truncateMiddle(title.trim(), 48) : null;
};

const getTodoStatusText = (
  status: string,
  count: number,
  t: ReturnType<typeof useTranslation>['t']
): string => {
  const key = status.toLowerCase();
  const label =
    key === 'completed' || key === 'done'
      ? t('agent.timeline.todoStatus.completed', 'completed')
      : key === 'in_progress' || key === 'running'
        ? t('agent.timeline.todoStatus.inProgress', 'in progress')
        : key === 'blocked'
          ? t('agent.timeline.todoStatus.blocked', 'blocked')
          : key === 'cancelled' || key === 'canceled'
            ? t('agent.timeline.todoStatus.cancelled', 'cancelled')
            : t('agent.timeline.todoStatus.pending', 'pending');
  return t('agent.timeline.todoStatus.count', '{{count}} {{status}}', { count, status: label });
};

const summarizeTodoDetails = (
  toolName: string,
  primary: unknown,
  fallback: unknown,
  t: ReturnType<typeof useTranslation>['t'],
  knownTitle?: string
): string => {
  const primaryRecord = getRecordFromUnknown(primary);
  const fallbackRecord = getRecordFromUnknown(fallback);
  const record = primaryRecord ?? fallbackRecord;
  const todos = getTodosFromRecord(record);
  const fallbackTodos = getTodosFromRecord(fallbackRecord);
  const todosHaveTitles = todos.some((todo) => Boolean(getTodoTitle(todo)));
  const source =
    todos.length > 0 && (todosHaveTitles || fallbackTodos.length === 0) ? todos : fallbackTodos;
  const action = typeof record?.action === 'string' ? record.action.toLowerCase() : '';
  const todoId = typeof record?.todo_id === 'string' ? record.todo_id : null;

  const statusCounts = new Map<string, number>();
  for (const todo of source) {
    const status = typeof todo.status === 'string' ? todo.status : 'pending';
    statusCounts.set(status, (statusCounts.get(status) ?? 0) + 1);
  }

  const statusText = Array.from(statusCounts.entries())
    .slice(0, 3)
    .map(([status, count]) => getTodoStatusText(status, count, t))
    .join(SUMMARY_LIST_SEPARATOR);
  const titles = source.map(getTodoTitle).filter((title): title is string => Boolean(title));
  const visibleTitles = titles.slice(0, 2).join(SUMMARY_LIST_SEPARATOR);
  const hiddenTitleCount = Math.max(0, titles.length - 2);
  const baseTitle = visibleTitles || knownTitle || '';
  const titleText = baseTitle
    ? `${baseTitle}${hiddenTitleCount > 0 ? t('agent.timeline.actionGroup.moreItems', ' and {{count}} more', { count: hiddenTitleCount }) : ''}`
    : '';
  const suffix = [statusText, titleText].filter(Boolean).join(SUMMARY_DETAIL_SEPARATOR);
  const total = source.length;

  if (toolName.toLowerCase().includes('read')) {
    return total > 0
      ? t('agent.timeline.todo.readMany', 'Read {{count}} todos: {{summary}}', {
          count: total,
          summary: suffix,
        })
      : t('agent.timeline.todo.read', 'Read todos');
  }

  const verb =
    action === 'add'
      ? t('agent.timeline.todo.addVerb', 'Add')
      : action === 'update'
        ? t('agent.timeline.todo.updateVerb', 'Update')
        : action === 'replace'
          ? t('agent.timeline.todo.replaceVerb', 'Replace')
          : t('agent.timeline.todo.writeVerb', 'Update');

  if (total > 0) {
    return t('agent.timeline.todo.writeMany', '{{verb}} {{count}} todos: {{summary}}', {
      verb,
      count: total,
      summary: suffix,
    });
  }

  if (todoId) {
    return t('agent.timeline.todo.writeOne', '{{verb}} todo {{id}}', { verb, id: todoId });
  }

  return t('agent.timeline.todo.write', '{{verb}} todos', { verb });
};

const getStepAction = (step: TimelineStep): ToolActionSummaryItem => {
  const toolName = step.toolName.toLowerCase();
  const input = step.input ?? {};
  const pathValue = input.path ?? input.file_path;
  const commandValue = input.command ?? input.cmd;
  const queryValue = input.query ?? input.pattern;
  const urlValue = input.url;

  if (toolName.includes('todo')) {
    return { kind: 'todo', label: getToolLabel(step.toolName) };
  }

  if (typeof commandValue === 'string' && commandValue.trim().length > 0) {
    return { kind: 'command', label: truncateMiddle(commandValue.trim()) };
  }

  if (
    typeof pathValue === 'string' &&
    pathValue.trim().length > 0 &&
    (toolName.includes('write') || toolName.includes('edit') || toolName.includes('patch'))
  ) {
    return { kind: 'write', label: getPathName(pathValue.trim()) };
  }

  if (
    typeof pathValue === 'string' &&
    pathValue.trim().length > 0 &&
    (toolName.includes('read') || toolName.includes('file'))
  ) {
    return { kind: 'read', label: getPathName(pathValue.trim()) };
  }

  if (typeof queryValue === 'string' && queryValue.trim().length > 0) {
    return { kind: 'search', label: truncateMiddle(queryValue.trim()) };
  }

  if (typeof urlValue === 'string' && urlValue.trim().length > 0) {
    return { kind: 'open', label: truncateMiddle(urlValue.trim()) };
  }

  return { kind: 'tool', label: getToolLabel(step.toolName) };
};

const getStepExecutionPreview = (
  step: TimelineStep,
  t: ReturnType<typeof useTranslation>['t']
): string => {
  const action = getStepAction(step);
  const inputPreview = getPreviewFromUnknown(step.input);
  const outputPreview = getPreviewFromUnknown(step.output);
  const detail = inputPreview ?? outputPreview ?? action.label;

  switch (action.kind) {
    case 'read':
      return t('agent.timeline.preview.read', 'Read: {{detail}}', { detail });
    case 'write':
      return t('agent.timeline.preview.write', 'Changed: {{detail}}', { detail });
    case 'command':
      return t('agent.timeline.preview.command', 'Command: {{detail}}', { detail });
    case 'search':
      return t('agent.timeline.preview.search', 'Search: {{detail}}', { detail });
    case 'open':
      return t('agent.timeline.preview.open', 'Open: {{detail}}', { detail });
    case 'todo':
      return summarizeTodoDetails(step.toolName, step.input, step.output, t, step.todoTitle);
    case 'tool':
      if (step.toolName.toLowerCase().includes('report') && (inputPreview || outputPreview)) {
        return t('agent.timeline.preview.report', 'Report: {{detail}}', { detail });
      }
      return inputPreview || outputPreview
        ? t('agent.timeline.preview.toolWithDetail', 'Content: {{detail}}', { detail })
        : t('agent.timeline.preview.tool', 'Call: {{detail}}', { detail });
  }
};

const TOOL_ACTION_KIND_ORDER: ToolActionKind[] = [
  'read',
  'write',
  'command',
  'search',
  'open',
  'todo',
  'tool',
];

const getUniqueLabels = (items: ToolActionSummaryItem[]): string[] => {
  return Array.from(new Set(items.map((item) => item.label).filter(Boolean)));
};

const getVisibleLabels = (
  labels: string[],
  t: ReturnType<typeof useTranslation>['t'],
  maxVisible = 3
): string => {
  const visible = labels.slice(0, maxVisible).join(SUMMARY_LIST_SEPARATOR);
  const hiddenCount = labels.length - maxVisible;
  if (hiddenCount <= 0) return visible;
  return `${visible}${t('agent.timeline.actionGroup.moreItems', ' and {{count}} more', {
    count: hiddenCount,
  })}`;
};

const getActionGroupText = (
  kind: ToolActionKind,
  items: ToolActionSummaryItem[],
  t: ReturnType<typeof useTranslation>['t']
): string => {
  const labels = getUniqueLabels(items);
  const names = getVisibleLabels(labels, t);
  const count = items.length;

  if (count === 1) {
    switch (kind) {
      case 'read':
        return t('agent.timeline.actionGroup.readSingle', 'Read {{names}}', { names });
      case 'write':
        return t('agent.timeline.actionGroup.writeSingle', 'Changed {{names}}', { names });
      case 'command':
        return t('agent.timeline.actionGroup.commandSingle', 'Ran {{names}}', { names });
      case 'search':
        return t('agent.timeline.actionGroup.searchSingle', 'Searched {{names}}', { names });
      case 'open':
        return t('agent.timeline.actionGroup.openSingle', 'Opened {{names}}', { names });
      case 'tool':
        return t('agent.timeline.actionGroup.toolSingle', 'Called {{names}}', { names });
    }
  }

  switch (kind) {
    case 'read':
      return t('agent.timeline.actionGroup.readMany', 'Read {{count}} files: {{names}}', {
        count,
        names,
      });
    case 'write':
      return t('agent.timeline.actionGroup.writeMany', 'Changed {{count}} files: {{names}}', {
        count,
        names,
      });
    case 'command':
      return t('agent.timeline.actionGroup.commandMany', 'Ran {{count}} commands: {{names}}', {
        count,
        names,
      });
    case 'search':
      return t('agent.timeline.actionGroup.searchMany', 'Searched {{count}} times: {{names}}', {
        count,
        names,
      });
    case 'open':
      return t('agent.timeline.actionGroup.openMany', 'Opened {{count}} links: {{names}}', {
        count,
        names,
      });
    case 'todo':
      return count === 1
        ? t('agent.timeline.actionGroup.todoSingle', '{{names}}', { names })
        : t('agent.timeline.actionGroup.todoMany', '{{count}} todo updates: {{names}}', {
            count,
            names,
          });
    case 'tool':
      return t('agent.timeline.actionGroup.toolMany', 'Called {{count}} tools: {{names}}', {
        count,
        names,
      });
  }
};

const summarizeToolActions = (
  steps: TimelineStep[],
  t: ReturnType<typeof useTranslation>['t']
): string[] => {
  const grouped = new Map<ToolActionKind, ToolActionSummaryItem[]>();
  for (const step of steps) {
    const action = getStepAction(step);
    const summaryAction =
      action.kind === 'todo'
        ? {
            ...action,
            label: summarizeTodoDetails(step.toolName, step.input, step.output, t, step.todoTitle),
          }
        : action;
    const items = grouped.get(summaryAction.kind) ?? [];
    items.push(summaryAction);
    grouped.set(summaryAction.kind, items);
  }

  return TOOL_ACTION_KIND_ORDER.flatMap((kind) => {
    const items = grouped.get(kind);
    return items && items.length > 0 ? [getActionGroupText(kind, items, t)] : [];
  });
};

// Individual timeline step
const TimelineStepItem = memo<{
  step: TimelineStep;
  isLast: boolean;
  defaultExpanded?: boolean | undefined;
  onUndoRequest?: ((stepId: string, toolName: string) => void) | undefined;
  onAgentSessionSelect?: ((sessionId: string) => void) | undefined;
}>(({ step, isLast, defaultExpanded = false, onUndoRequest, onAgentSessionSelect }) => {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const { t } = useTranslation();
  const toolPreview = getStepExecutionPreview(step, t);
  const openMCPApp = useMCPAppOpen(step);
  const stepLabel = getToolLabel(step.toolName);
  const safeStepId = useMemo(() => toSafeDomId(step.id), [step.id]);
  const detailsPanelId = `timeline-step-panel-${safeStepId}`;

  if (isAgentTool(step.toolName)) {
    return (
      <div className="relative flex gap-2 mb-0" style={{ minHeight: '24px' }}>
        <div className="flex flex-col items-center flex-shrink-0" style={{ width: '24px' }}>
          <div
            className={`
              w-6 h-6 rounded-full flex items-center justify-center border-2 flex-shrink-0 transition-colors duration-200 motion-reduce:transition-none
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
              <Loader2
                size={11}
                className="text-blue-500 animate-spin motion-reduce:animate-none"
              />
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
            <div className="w-px flex-1 min-h-4 bg-slate-200 dark:bg-slate-700 flex-shrink-0" />
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
            onAgentSessionSelect={onAgentSessionSelect}
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

  return (
    <div className="relative flex gap-2 mb-0" style={{ minHeight: '24px' }}>
      {/* Timeline line + dot */}
      <div
        className="flex flex-col items-center flex-shrink-0"
        style={{ width: step.duration != null ? '36px' : '24px' }}
      >
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
        {step.duration != null && (
          <span className="mt-0.5 max-w-10 truncate text-center text-[10px] leading-none tabular-nums text-slate-400 dark:text-slate-500">
            {formatDuration(step.duration)}
          </span>
        )}
        {!isLast && (
          <div className="mt-1 w-px flex-1 min-h-4 bg-slate-200 dark:bg-slate-700 flex-shrink-0" />
        )}
      </div>

      {/* Content */}
      <div className="flex-1 pb-1.5 min-w-0 flex flex-col">
        <div className="w-full rounded-md border border-slate-200/50 bg-white px-3 py-2 shadow-[0_1px_2px_rgba(15,23,42,0.02)] transition-[border-color,box-shadow] duration-200 hover:border-slate-300/70 hover:shadow-[0_1px_3px_rgba(15,23,42,0.045)] dark:border-slate-800/60 dark:bg-slate-950/70 dark:hover:border-slate-700/70 motion-reduce:transition-none">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setExpanded((v) => !v);
              }}
              aria-expanded={expanded}
              aria-controls={detailsPanelId}
              aria-label={
                expanded
                  ? t('agent.timeline.hideStepDetails', 'Hide details for {{tool}}', {
                      tool: stepLabel,
                    })
                  : t('agent.timeline.showStepDetails', 'Show details for {{tool}}', {
                      tool: stepLabel,
                    })
              }
              className="flex min-w-0 flex-1 items-center gap-2 text-left cursor-pointer rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
            >
              <span className="flex min-w-0 flex-1 items-baseline gap-2">
                <span className="min-w-0 truncate text-sm font-normal text-slate-800 dark:text-slate-200">
                  {toolPreview}
                </span>
                <span className="shrink-0 text-2xs font-normal text-slate-400 dark:text-slate-500">
                  {stepLabel}
                </span>
              </span>
              {(step.input || step.output) &&
                (expanded ? (
                  <ChevronDown size={12} className="text-slate-400" />
                ) : (
                  <ChevronRight size={12} className="text-slate-400" />
                ))}
            </button>
            {onUndoRequest && step.status === 'success' && (
              <button
                type="button"
                onClick={() => {
                  onUndoRequest(step.id, step.toolName);
                }}
                className="ml-1 p-1.5 rounded hover:bg-slate-200 dark:hover:bg-slate-600 active:bg-slate-300 dark:active:bg-slate-500 text-slate-400 hover:text-amber-500 transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/50 min-w-8 min-h-8 flex items-center justify-center"
                aria-label={t('agent.undo.button', 'Undo this action')}
                title={t('agent.undo.button', 'Undo this action')}
              >
                <Undo2 size={14} />
              </button>
            )}
          </div>
        </div>

        {/* MCP App "Open App" button - visible without expanding */}
        {step.toolName.startsWith('mcp__') && step.status === 'success' && !step.isError && (
          <button
            type="button"
            onClick={(e) => {
              void openMCPApp(e);
            }}
            className="flex items-center gap-1.5 px-2.5 py-1 mt-1 text-xs rounded-md bg-violet-50 dark:bg-violet-950/30 text-violet-600 dark:text-violet-400 hover:bg-violet-100 dark:hover:bg-violet-900/40 active:bg-violet-200 dark:active:bg-violet-800/40 border border-violet-200/60 dark:border-violet-800/30 transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/50 focus-visible:ring-offset-1"
          >
            <AppWindow size={12} />
            {t('agent.timeline.openApp', 'Open App')}
          </button>
        )}

        {expanded && (
          <div
            id={detailsPanelId}
            role="region"
            aria-label={t('agent.timeline.stepDetailsRegion', 'Details for {{tool}}', {
              tool: stepLabel,
            })}
            className="mt-1.5 space-y-1.5 text-xs"
          >
            {step.input && Object.keys(step.input).length > 0 && (
              <div className="bg-slate-50/75 dark:bg-slate-800/40 rounded-md p-2 border border-slate-200/40 dark:border-slate-700/35">
                <div className="text-2xs font-medium text-slate-400 uppercase tracking-wider mb-1">
                  {t('agent.timeline.input', 'Input')}
                </div>
                <pre className="text-slate-600 dark:text-slate-300 font-mono whitespace-pre-wrap break-words overflow-x-auto max-h-50 overflow-y-auto">
                  {JSON.stringify(step.input, null, 2)}
                </pre>
              </div>
            )}
            {step.output && (
              <div
                className={`rounded-md p-2 border ${
                  step.isError
                    ? 'bg-red-50/80 dark:bg-red-950/25 border-red-200/45 dark:border-red-800/25'
                    : 'bg-slate-50/75 dark:bg-slate-800/40 border-slate-200/40 dark:border-slate-700/35'
                }`}
              >
                <div className="text-2xs font-medium text-slate-400 uppercase tracking-wider mb-1">
                  {t('agent.timeline.output', 'Output')}
                </div>
                <pre
                  className={`font-mono whitespace-pre-wrap break-words overflow-x-auto max-h-50 overflow-y-auto ${
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
  ({ steps, isStreaming, defaultCollapsed, onUndoRequest, onAgentSessionSelect }) => {
    const { t } = useTranslation();
    const [collapsed, setCollapsed] = useState(defaultCollapsed ?? false);
    const timelineStepsPanelId = useMemo(
      () => `execution-timeline-steps-${toSafeDomId(steps[0]?.id ?? 'current')}`,
      [steps]
    );

    const summary = useMemo(() => {
      const total = steps.length;
      const completed = steps.filter((s) => s.status === 'success').length;
      const failed = steps.filter((s) => s.status === 'error').length;
      const running = steps.filter((s) => s.status === 'running').length;
      const actions = summarizeToolActions(steps, t);
      const title =
        actions[0] ??
        (running > 0
          ? t('agent.timeline.actionSummaryRunning', '{{count}} actions running', {
              count: running,
            })
          : t('agent.timeline.actionSummary', '{{count}} actions', {
              count: total,
            }));
      const detailActions = actions.slice(1);
      const hiddenActions = Math.max(0, detailActions.length - 7);
      return { total, completed, failed, running, title, detailActions, hiddenActions };
    }, [steps, t]);

    if (steps.length === 0) return null;

    return (
      <div className="pb-2 rounded-md">
        {/* Aggregated multi-source view (only renders when 2+ search/RAG steps detected) */}
        <MultiSourceResultsCard steps={steps} />

        {/* Summary header */}
        <button
          type="button"
          onClick={() => {
            setCollapsed((v) => !v);
          }}
          aria-expanded={!collapsed}
          aria-controls={timelineStepsPanelId}
          aria-label={
            collapsed
              ? t('agent.timeline.showTimeline', 'Show execution steps')
              : t('agent.timeline.hideTimeline', 'Hide execution steps')
          }
          className="flex items-center gap-2 w-full text-left mb-1.5 group cursor-pointer rounded min-h-9 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
        >
          {collapsed ? (
            <ChevronRight size={14} className="text-slate-400" />
          ) : (
            <ChevronDown size={14} className="text-slate-400" />
          )}
          <span className="min-w-0 flex-1 truncate text-xs font-medium text-slate-600 dark:text-slate-300">
            {summary.title}
          </span>
          <span className="hidden shrink-0 text-2xs text-slate-400 sm:inline">
            {t('agent.timeline.progress', '{{completed}}/{{total}} done', {
              completed: summary.completed,
              total: summary.total,
            })}
          </span>
          {summary.failed > 0 && (
            <span className="text-2xs px-1.5 py-0.5 bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 rounded-full">
              {summary.failed} {t('agent.timeline.failed', 'Failed')}
            </span>
          )}
          {isStreaming && summary.running > 0 && (
            <Loader2 size={12} className="text-blue-500 animate-spin motion-reduce:animate-none" />
          )}
        </button>

        {/* Timeline steps */}
        {collapsed && summary.detailActions.length > 0 && (
          <div className="mb-1.5 ml-6 space-y-1 overflow-hidden">
            {summary.detailActions.slice(0, 7).map((action, index) => (
              <div
                key={`${action}-${String(index)}`}
                className="truncate text-sm leading-6 text-slate-500 dark:text-slate-400"
              >
                {action}
              </div>
            ))}
            {summary.hiddenActions > 0 && (
              <div className="truncate text-sm leading-6 text-slate-400 dark:text-slate-500">
                {t('agent.timeline.moreActions', 'More {{count}} actions', {
                  count: summary.hiddenActions,
                })}
              </div>
            )}
          </div>
        )}

        {!collapsed && (
          <div id={timelineStepsPanelId} className="pl-1 pt-0.5" style={{ display: 'flow-root' }}>
            {steps.map((step, i) => (
              <TimelineStepItem
                key={step.id}
                step={step}
                isLast={i === steps.length - 1}
                defaultExpanded={step.status === 'error'}
                onUndoRequest={onUndoRequest}
                onAgentSessionSelect={onAgentSessionSelect}
              />
            ))}
          </div>
        )}
      </div>
    );
  }
);
ExecutionTimeline.displayName = 'ExecutionTimeline';
