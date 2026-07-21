/**
 * MessageStream - Chat message stream component
 *
 * Displays user messages, agent reasoning, tool execution, and final responses.
 * Matches the design from docs/statics/project workbench/agent/
 */

import { ReactNode, memo, useState, useMemo, useRef, useEffect } from 'react';
import type { ComponentType } from 'react';

import { useTranslation } from 'react-i18next';

import {
  Brain,
  Wrench,
  Sparkles,
  Bot,
  ChevronRight,
  AlertCircle,
  ChevronUp,
  ChevronDown,
  TerminalSquare,
  Loader2,
  Check,
  X,
  FileEdit,
  FileInput,
  Image as ImageIcon,
  Film,
  AudioLines,
  FileText,
  Table as TableIcon,
  Presentation,
  FileArchive,
  Code as CodeIcon,
  File as FileIcon,
} from 'lucide-react';

import { foldTextWithMetadata } from '../../../utils/toolResultUtils';

import { MarkdownContent } from './MarkdownContent';

type AgentIconName = 'psychology' | 'construction' | 'auto_awesome' | 'smart_toy';

const AGENT_ICON_COMPONENTS: Record<
  AgentIconName,
  ComponentType<{ size?: number; className?: string }>
> = {
  psychology: Brain,
  construction: Wrench,
  auto_awesome: Sparkles,
  smart_toy: Bot,
};

export interface MessageStreamProps {
  /** Messages to display */
  children?: ReactNode | undefined;
  /** Padding for content area */
  className?: string | undefined;
}

/**
 * MessageStream component
 *
 * @example
 * <MessageStream>
 *   <UserMessage content="What are the trends?" />
 *   <ReasoningLog steps={reasoningSteps} />
 *   <ToolExecutionCard toolName="Memory Search" status="running" />
 *   <FinalResponse content="# Analysis Report..." />
 * </MessageStream>
 */

export const MessageStream = memo(function MessageStream({
  children,
  className = '',
}: MessageStreamProps) {
  return (
    <div className={`w-full max-w-3xl lg:max-w-5xl xl:max-w-7xl mx-auto space-y-10 ${className}`}>
      {children}
    </div>
  );
});

/**
 * UserMessage - User's message bubble (right-aligned, primary color)
 */
export interface UserMessageFileMetadata {
  filename: string;
  sandbox_path?: string | undefined;
  mime_type: string;
  size_bytes: number;
}

export interface UserMessageProps {
  /** Message content */
  content: string;
  /** Skill name if triggered via /skill */
  forcedSkillName?: string | undefined;
  /** Attached files metadata */
  fileMetadata?: UserMessageFileMetadata[] | undefined;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes.toString()} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const getFileIconComponent = (mimeType: string) => {
  if (mimeType.startsWith('image/')) return ImageIcon;
  if (mimeType.startsWith('video/')) return Film;
  if (mimeType.startsWith('audio/')) return AudioLines;
  if (mimeType === 'application/pdf') return FileText;
  if (mimeType.includes('spreadsheet') || mimeType.includes('excel')) return TableIcon;
  if (mimeType.includes('presentation') || mimeType.includes('powerpoint')) return Presentation;
  if (mimeType.includes('zip') || mimeType.includes('tar') || mimeType.includes('compress'))
    return FileArchive;
  if (
    mimeType.startsWith('text/') ||
    mimeType.includes('json') ||
    mimeType.includes('xml') ||
    mimeType.includes('javascript') ||
    mimeType.includes('typescript')
  )
    return CodeIcon;
  return FileIcon;
};

export function UserMessage({ content, forcedSkillName, fileMetadata }: UserMessageProps) {
  return (
    <div className="flex items-start gap-3 justify-end">
      <div className="flex flex-col items-end gap-1.5 max-w-[80%]">
        <div
          className={
            forcedSkillName
              ? 'relative rounded-lg rounded-tr-none border border-primary/30 bg-primary/10'
              : ''
          }
        >
          {forcedSkillName && (
            <div className="absolute left-0 top-1/2 -translate-x-1/2 -translate-y-1/2 w-4 h-4 rounded-full bg-primary flex items-center justify-center ring-2 ring-white dark:ring-slate-900 z-10">
              <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 16 16" fill="currentColor">
                <path d="M9.5 0L4 9h4l-1.5 7L13 7H9l.5-7z" />
              </svg>
            </div>
          )}
          <div
            className={
              forcedSkillName
                ? 'bg-white dark:bg-slate-900 rounded-lg rounded-tr-none px-5 py-4.5'
                : 'bg-primary text-white rounded-lg rounded-tr-none px-5 py-4.5 shadow-md'
            }
          >
            <p
              className={
                forcedSkillName
                  ? 'text-sm leading-relaxed text-slate-800 dark:text-slate-100 break-words'
                  : 'text-sm leading-relaxed break-words'
              }
            >
              {content}
            </p>
          </div>
          {forcedSkillName && (
            <div className="absolute bottom-0 right-4 translate-y-1/2 px-1.5 bg-white dark:bg-slate-900 text-2xs text-primary/70 font-medium leading-none tracking-wide">
              {forcedSkillName}
            </div>
          )}
        </div>
        {fileMetadata && fileMetadata.length > 0 && (
          <div className={`flex flex-col gap-1 ${forcedSkillName ? 'mt-2' : 'mt-0.5'}`}>
            {fileMetadata.map((file, idx) => (
              <div
                key={idx.toString()}
                className="inline-flex items-center gap-2 px-3 py-1.5 bg-slate-100 dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-lg"
              >
                {(() => {
                  const Icon = getFileIconComponent(file.mime_type);
                  return <Icon size={16} className="text-slate-500 dark:text-slate-400" />;
                })()}
                <span className="text-xs text-slate-700 dark:text-slate-300 truncate max-w-50">
                  {file.filename}
                </span>
                <span className="text-2xs text-slate-400 dark:text-slate-500 whitespace-nowrap">
                  {formatFileSize(file.size_bytes)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * AgentSection - Wrapper for agent messages (left-aligned with avatar)
 */
export interface AgentSectionProps {
  /** Icon type */
  icon?: AgentIconName | undefined;
  /** Icon background color */
  iconBg?: string | undefined;
  /** Icon color */
  iconColor?: string | undefined;
  /** Opacity for completed state */
  opacity?: boolean | undefined;
  children: ReactNode;
}

export function AgentSection({
  icon = 'psychology',
  iconBg = 'bg-slate-200 dark:bg-border-dark',
  iconColor = 'text-primary',
  opacity = false,
  children,
}: AgentSectionProps) {
  const AgentIcon = AGENT_ICON_COMPONENTS[icon];

  return (
    <div className={`flex items-start gap-4 ${opacity ? 'opacity-70' : ''}`}>
      <div className={`w-8 h-8 rounded-full ${iconBg} flex items-center justify-center shrink-0`}>
        <AgentIcon size={18} className={iconColor} />
      </div>
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  );
}

/**
 * ReasoningLogCard - Expandable reasoning log card
 */
export interface ReasoningLogCardProps {
  /** Reasoning steps */
  steps: string[];
  /** Summary text */
  summary: string;
  /** Whether completed */
  completed?: boolean | undefined;
  /** Whether expanded by default */
  expanded?: boolean | undefined;
}

export function ReasoningLogCard({
  steps,
  summary,
  completed = false,
  expanded = true,
}: ReasoningLogCardProps) {
  const { t } = useTranslation();

  return (
    <div className="bg-slate-50 dark:bg-surface-dark/50 border border-slate-200 dark:border-border-dark rounded-md rounded-tl-none p-4">
      <details className="group/reasoning" open={expanded}>
        <summary className="text-sm text-slate-600 dark:text-slate-300 cursor-pointer list-none flex items-center justify-between select-none">
          <div className="flex items-center gap-2">
            <ChevronRight
              size={14}
              className="group-open/reasoning:rotate-90 transition-transform"
            />
            <span className="font-semibold uppercase text-2xs text-primary">
              {t('components.messageStream.reasoningLog', { defaultValue: 'Reasoning Log' })}
            </span>
            <span className="text-xs">{summary}</span>
          </div>
          {completed && (
            <span className="text-2xs font-bold text-emerald-500">
              {t('components.messageStream.complete', { defaultValue: 'COMPLETE' })}
            </span>
          )}
        </summary>
        <div className="mt-3 space-y-2 border-l border-slate-200 pl-4 text-sm leading-relaxed text-slate-500 dark:border-border-dark dark:text-text-muted">
          {steps.map((step, index) => (
            <p key={index}>{step}</p>
          ))}
        </div>
      </details>
    </div>
  );
}

/**
 * Format tool result to string for display
 * Handles objects, arrays, and primitives
 */

// eslint-disable-next-line react-refresh/only-export-components
export function formatToolResult(result: unknown): string {
  if (result === null || result === undefined) {
    return '';
  }
  if (typeof result === 'string') {
    return result;
  }
  // Convert objects, arrays, numbers, booleans to JSON string
  return JSON.stringify(result, null, 2);
}

/**
 * ToolResultDisplay - Tool result with collapsible long text support
 *
 * When the result text exceeds 10 lines (5 + 5), it will:
 * - Show first 5 lines and last 5 lines by default
 * - Display a "Show Full" button to expand the full content
 * - Display a "Show Less" button when expanded to collapse it back
 */
interface ToolResultDisplayProps {
  /** Result text to display */
  result: string;
  /** Whether this is an error result */
  isError: boolean;
}

function ToolResultDisplay({ result, isError }: ToolResultDisplayProps) {
  const { t } = useTranslation();
  const [isExpanded, setIsExpanded] = useState(false);

  // Memoize the folded result calculation
  const { foldedText, isFolded, totalLines } = useMemo(() => {
    const { text, folded } = foldTextWithMetadata(result, 5);
    const lines = result.split('\n').length;
    return { foldedText: text, isFolded: folded, totalLines: lines };
  }, [result]);

  const displayText = isExpanded ? result : foldedText;

  if (isError) {
    return (
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-2xs uppercase font-bold text-red-600 flex items-center gap-1">
            <AlertCircle size={12} />
            {t('components.messageStream.error', { defaultValue: 'Error' })}
          </span>
          {isFolded && (
            <button
              type="button"
              onClick={() => {
                setIsExpanded(!isExpanded);
              }}
              className="text-2xs text-red-500 hover:text-red-600 font-medium flex items-center gap-1"
            >
              {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              {isExpanded
                ? t('components.messageStream.showLess', { defaultValue: 'Show Less' })
                : t('components.messageStream.showFullLines', {
                    defaultValue: 'Show Full ({{count}} lines)',
                    count: totalLines,
                  })}
            </button>
          )}
        </div>
        <div className="px-3 py-2 bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 rounded-md text-xs font-mono text-red-700 dark:text-red-300 overflow-x-auto max-h-48 overflow-y-auto">
          <pre className="whitespace-pre-wrap break-words">{displayText}</pre>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-2xs uppercase font-bold text-emerald-600 flex items-center gap-1">
          <TerminalSquare size={12} />
          {t('components.messageStream.output', { defaultValue: 'Output' })}
        </span>
        {isFolded && (
          <button
            type="button"
            onClick={() => {
              setIsExpanded(!isExpanded);
            }}
            className="text-2xs text-emerald-600 hover:text-emerald-700 font-medium flex items-center gap-1"
          >
            {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {isExpanded
              ? t('components.messageStream.showLess', { defaultValue: 'Show Less' })
              : t('components.messageStream.showFullLines', {
                  defaultValue: 'Show Full ({{count}} lines)',
                  count: totalLines,
                })}
          </button>
        )}
      </div>
      <div
        className={`px-3 py-2 bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/20 rounded-md text-xs text-slate-700 dark:text-slate-300 overflow-x-auto ${isExpanded ? 'max-h-96' : 'max-h-48'} overflow-y-auto`}
      >
        <MarkdownContent
          content={displayText}
          className="prose-p:my-0 prose-headings:my-1 prose-ul:my-0 prose-ol:my-0"
          prose={true}
        />
      </div>
    </div>
  );
}

/**
 * ToolExecutionCardDisplay - Tool execution with live status
 */
export interface ToolExecutionCardDisplayProps {
  /** Tool name */
  toolName: string;
  /** Execution status */
  status: 'preparing' | 'running' | 'success' | 'error';
  /** Query parameters (input) */
  parameters?: Record<string, unknown> | undefined;
  /** Partial arguments string (streaming) */
  partialArguments?: string | undefined;
  /** Execution mode */
  executionMode?: string | undefined;
  /** Execution duration in milliseconds */
  duration?: number | undefined;
  /** Execution result - can be string or object */
  result?: unknown;
  /** Error message */
  error?: string | undefined;
  /** Whether to show details expanded by default */
  defaultExpanded?: boolean | undefined;
}

type ToolPurposeKind = 'read' | 'write' | 'command' | 'search' | 'open' | 'tool';

const SUMMARY_LIST_SEPARATOR = ', ';
const SUMMARY_DETAIL_SEPARATOR = ': ';

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

function truncateMiddle(value: string, maxLength = 120): string {
  if (value.length <= maxLength) return value;
  const headLength = Math.ceil((maxLength - 3) * 0.62);
  const tailLength = Math.floor((maxLength - 3) * 0.38);
  return `${value.slice(0, headLength)}...${value.slice(value.length - tailLength)}`;
}

function normalizePreviewText(value: string): string {
  return (
    value
      .split('\n')
      .map((line) => line.trim())
      .find((line) => line.length > 0) ?? ''
  );
}

function getPreviewFromUnknown(value: unknown): string | null {
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
}

function getRecordFromUnknown(value: unknown): Record<string, unknown> | null {
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
}

function getTodosFromRecord(record: Record<string, unknown> | null): Record<string, unknown>[] {
  const todos = record?.todos;
  return Array.isArray(todos)
    ? todos.filter((todo): todo is Record<string, unknown> =>
        Boolean(todo && typeof todo === 'object')
      )
    : [];
}

function getTodoTitle(todo: Record<string, unknown>): string | null {
  const title = todo.content ?? todo.title ?? todo.task ?? todo.description ?? todo.name;
  return typeof title === 'string' && title.trim() ? truncateMiddle(title.trim(), 48) : null;
}

function getTodoStatusText(
  status: string,
  count: number,
  t: ReturnType<typeof useTranslation>['t']
): string {
  const key = status.toLowerCase();
  const label =
    key === 'completed' || key === 'done'
      ? t('components.messageStream.todoStatus.completed', { defaultValue: 'completed' })
      : key === 'in_progress' || key === 'running'
        ? t('components.messageStream.todoStatus.inProgress', { defaultValue: 'in progress' })
        : key === 'blocked'
          ? t('components.messageStream.todoStatus.blocked', { defaultValue: 'blocked' })
          : key === 'cancelled' || key === 'canceled'
            ? t('components.messageStream.todoStatus.cancelled', { defaultValue: 'cancelled' })
            : t('components.messageStream.todoStatus.pending', { defaultValue: 'pending' });
  return t('components.messageStream.todoStatus.count', {
    defaultValue: '{{count}} {{status}}',
    count,
    status: label,
  });
}

function summarizeTodoTool(
  toolName: string,
  t: ReturnType<typeof useTranslation>['t'],
  parameters?: Record<string, unknown>,
  result?: string
): string {
  const primaryRecord = getRecordFromUnknown(parameters);
  const fallbackRecord = getRecordFromUnknown(result);
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
  const titleText = visibleTitles
    ? `${visibleTitles}${hiddenTitleCount > 0 ? t('components.messageStream.todo.moreItems', { defaultValue: ' and {{count}} more', count: hiddenTitleCount }) : ''}`
    : '';
  const summary = [statusText, titleText].filter(Boolean).join(SUMMARY_DETAIL_SEPARATOR);
  const total = source.length;

  if (toolName.toLowerCase().includes('read')) {
    return total > 0
      ? t('components.messageStream.todo.readMany', {
          defaultValue: 'Read {{count}} todos: {{summary}}',
          count: total,
          summary,
        })
      : t('components.messageStream.todo.read', { defaultValue: 'Read todos' });
  }

  const verb =
    action === 'add'
      ? t('components.messageStream.todo.addVerb', { defaultValue: 'Add' })
      : action === 'update'
        ? t('components.messageStream.todo.updateVerb', { defaultValue: 'Update' })
        : action === 'replace'
          ? t('components.messageStream.todo.replaceVerb', { defaultValue: 'Replace' })
          : t('components.messageStream.todo.writeVerb', { defaultValue: 'Update' });

  if (total > 0) {
    return t('components.messageStream.todo.writeMany', {
      defaultValue: '{{verb}} {{count}} todos: {{summary}}',
      verb,
      count: total,
      summary,
    });
  }

  if (todoId) {
    return t('components.messageStream.todo.writeOne', {
      defaultValue: '{{verb}} todo {{id}}',
      verb,
      id: todoId,
    });
  }

  return t('components.messageStream.todo.write', {
    defaultValue: '{{verb}} todos',
    verb,
  });
}

function inferToolPurpose(toolName: string, parameters?: Record<string, unknown>): ToolPurposeKind {
  const name = toolName.toLowerCase();
  if (
    typeof parameters?.command === 'string' ||
    typeof parameters?.cmd === 'string' ||
    name.includes('terminal') ||
    name.includes('shell') ||
    name.includes('command')
  ) {
    return 'command';
  }
  if (name.includes('write') || name.includes('edit') || name.includes('patch')) {
    return 'write';
  }
  if (name.includes('read')) {
    return 'read';
  }
  if (
    name.includes('glob') ||
    name.includes('grep') ||
    name.includes('search') ||
    name.includes('find') ||
    typeof parameters?.pattern === 'string' ||
    typeof parameters?.query === 'string'
  ) {
    return 'search';
  }
  if (
    name.includes('web') ||
    name.includes('browse') ||
    name.includes('scrape') ||
    typeof parameters?.url === 'string'
  ) {
    return 'open';
  }
  return 'tool';
}

function getToolExecutionSummary(
  toolName: string,
  purposeKind: ToolPurposeKind,
  t: ReturnType<typeof useTranslation>['t'],
  parameters?: Record<string, unknown>,
  partialArguments?: string,
  result?: string,
  error?: string
): string {
  if (toolName.toLowerCase().includes('todo')) {
    return summarizeTodoTool(toolName, t, parameters, result);
  }

  const argumentPreview =
    getPreviewFromUnknown(parameters) ?? getPreviewFromUnknown(partialArguments);
  const resultPreview = getPreviewFromUnknown(result);
  const errorPreview = getPreviewFromUnknown(error);
  const detail = errorPreview ?? argumentPreview ?? resultPreview ?? toolName;

  if (errorPreview) {
    return t('components.messageStream.preview.error', {
      defaultValue: 'Error: {{detail}}',
      detail,
    });
  }

  switch (purposeKind) {
    case 'read':
      return t('components.messageStream.preview.read', {
        defaultValue: 'Read: {{detail}}',
        detail,
      });
    case 'write':
      return t('components.messageStream.preview.write', {
        defaultValue: 'Changed: {{detail}}',
        detail,
      });
    case 'command':
      return t('components.messageStream.preview.command', {
        defaultValue: 'Command: {{detail}}',
        detail,
      });
    case 'search':
      return t('components.messageStream.preview.search', {
        defaultValue: 'Search: {{detail}}',
        detail,
      });
    case 'open':
      return t('components.messageStream.preview.open', {
        defaultValue: 'Open: {{detail}}',
        detail,
      });
    case 'tool':
      if (toolName.toLowerCase().includes('report') && (argumentPreview || resultPreview)) {
        return t('components.messageStream.preview.report', {
          defaultValue: 'Report: {{detail}}',
          detail,
        });
      }
      return argumentPreview || resultPreview
        ? t('components.messageStream.preview.toolWithDetail', {
            defaultValue: 'Content: {{detail}}',
            detail,
          })
        : t('components.messageStream.preview.tool', {
            defaultValue: 'Call: {{detail}}',
            detail,
          });
  }
}

export function ToolExecutionCardDisplay({
  toolName,
  status,
  parameters,
  partialArguments,
  executionMode,
  duration,
  result,
  error,
  defaultExpanded = false,
}: ToolExecutionCardDisplayProps) {
  const { t } = useTranslation();
  const streamingArgsRef = useRef<HTMLDivElement>(null);

  // Auto-scroll streaming arguments to bottom
  useEffect(() => {
    if (streamingArgsRef.current && status === 'preparing') {
      streamingArgsRef.current.scrollTop = streamingArgsRef.current.scrollHeight;
    }
  }, [partialArguments, status]);

  const formatDuration = (ms: number) => {
    if (ms < 1000) return `${ms.toString()}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  };

  // Format result to ensure it's always a string
  const formattedResult = formatToolResult(result);
  const purposeKind = inferToolPurpose(toolName, parameters);
  const executionSummary = getToolExecutionSummary(
    toolName,
    purposeKind,
    t,
    parameters,
    partialArguments,
    formattedResult,
    error
  );

  const getStatusBadge = () => {
    switch (status) {
      case 'preparing':
        return (
          <div className="flex items-center gap-2 px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-500/10 text-blue-600 text-2xs font-bold uppercase tracking-wider">
            <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse motion-reduce:animate-none" />
            {t('components.messageStream.status.preparing', { defaultValue: 'Preparing' })}
          </div>
        );
      case 'running':
        return (
          <div className="flex items-center gap-2 px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-500/10 text-blue-600 text-2xs font-bold uppercase tracking-wider">
            <Loader2 size={12} className="animate-spin" />
            {t('components.messageStream.status.running', { defaultValue: 'Running' })}
          </div>
        );
      case 'success':
        return (
          <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-500/10 text-emerald-600 text-2xs font-bold uppercase tracking-wider">
            <Check size={12} />
            {t('components.messageStream.status.success', { defaultValue: 'Success' })}
            {duration !== undefined && (
              <span className="ml-1 text-emerald-500/70">({formatDuration(duration)})</span>
            )}
          </div>
        );
      case 'error':
        return (
          <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-100 dark:bg-red-500/10 text-red-600 text-2xs font-bold uppercase tracking-wider">
            <X size={12} />
            {t('components.messageStream.status.failed', { defaultValue: 'Failed' })}
            {duration !== undefined && (
              <span className="ml-1 text-red-500/70">({formatDuration(duration)})</span>
            )}
          </div>
        );
    }
  };

  const hasDetails = parameters || partialArguments || executionMode || formattedResult || error;

  return (
    <div className="overflow-hidden rounded-md rounded-tl-none border border-slate-200 bg-white shadow-sm dark:border-border-dark dark:bg-surface-dark">
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-slate-100 text-primary dark:bg-slate-800">
            <Wrench size={18} />
          </div>
          <div className="min-w-0 truncate">
            <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {t('components.messageStream.toolTitle', {
                defaultValue: 'Tool: {{tool}}',
                tool: toolName,
              })}
            </span>
            {status !== 'preparing' && (
              <span className="ml-2 text-xs text-slate-500 dark:text-slate-400">
                {executionSummary}
              </span>
            )}
          </div>
        </div>
        {getStatusBadge()}
      </div>

      {hasDetails && (
        <details
          className="group"
          open={defaultExpanded || status === 'running' || status === 'preparing'}
        >
          <summary className="border-t border-slate-200 px-4 py-2 text-xs text-slate-500 cursor-pointer hover:bg-slate-50 dark:border-border-dark dark:hover:bg-white/5 flex items-center gap-1 select-none">
            <ChevronRight size={14} className="group-open:rotate-90 transition-transform" />
            <span>{t('components.messageStream.details', { defaultValue: 'Details' })}</span>
          </summary>
          <div className="p-4 pt-0 space-y-4">
            {/* Preparing State - streaming arguments */}
            {status === 'preparing' && partialArguments && (
              <div className="space-y-1">
                <span className="text-2xs uppercase font-bold text-text-muted flex items-center gap-1">
                  <FileEdit size={12} />
                  {t('components.messageStream.buildingArguments', {
                    defaultValue: 'Building Arguments',
                  })}
                </span>
                <div
                  ref={streamingArgsRef}
                  className="px-3 py-2 bg-blue-50 dark:bg-blue-500/5 border border-blue-200 dark:border-blue-500/20 rounded-md text-xs font-mono text-slate-600 dark:text-text-muted overflow-x-auto max-h-32 overflow-y-auto"
                >
                  <pre className="whitespace-pre-wrap break-words">
                    {partialArguments}
                    <span className="inline-block w-1.5 h-3.5 bg-blue-500 animate-pulse motion-reduce:animate-none ml-0.5 align-middle" />
                  </pre>
                </div>
              </div>
            )}

            {/* Preparing State - no arguments yet */}
            {status === 'preparing' && !partialArguments && (
              <div className="space-y-2">
                <div className="border border-dashed border-blue-200 dark:border-blue-500/20 rounded-md p-4 flex items-center justify-center gap-2 text-center bg-blue-50/50 dark:bg-blue-500/5">
                  <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse motion-reduce:animate-none" />
                  <p className="text-xs text-blue-600 dark:text-blue-400 italic">
                    {t('components.messageStream.preparingToolCall', {
                      defaultValue: 'Preparing tool call…',
                    })}
                  </p>
                </div>
              </div>
            )}

            {/* Input Parameters */}
            {parameters && status !== 'preparing' && (
              <div className="space-y-1">
                <span className="text-2xs uppercase font-bold text-text-muted flex items-center gap-1">
                  <FileInput size={12} />
                  {t('components.messageStream.input', { defaultValue: 'Input' })}
                </span>
                <div className="px-3 py-2 bg-slate-100 dark:bg-background-dark/50 rounded-md text-xs font-mono text-slate-600 dark:text-text-muted overflow-x-auto max-h-32 overflow-y-auto">
                  <pre className="whitespace-pre-wrap break-words">
                    {JSON.stringify(parameters, null, 2)}
                  </pre>
                </div>
              </div>
            )}

            {/* Execution Mode */}
            {executionMode && (
              <div className="space-y-1">
                <span className="text-2xs uppercase font-bold text-text-muted">
                  {t('components.messageStream.executionMode', {
                    defaultValue: 'Execution Mode',
                  })}
                </span>
                <div className="px-3 py-2 bg-slate-100 dark:bg-background-dark/50 rounded-md text-xs font-mono text-slate-600 dark:text-text-muted">
                  {executionMode}
                </div>
              </div>
            )}

            {/* Running State */}
            {status === 'running' && (
              <div className="space-y-2">
                <span className="text-2xs uppercase font-bold text-text-muted">
                  {t('components.messageStream.liveResults', { defaultValue: 'Live Results' })}
                </span>
                <div className="border border-dashed border-slate-200 dark:border-border-dark rounded-md p-6 flex flex-col items-center justify-center gap-2 text-center bg-slate-50/50 dark:bg-background-dark/20">
                  <Loader2
                    size={30}
                    className="text-slate-300 dark:text-border-dark animate-spin"
                  />
                  <p className="text-xs text-text-muted italic">
                    {t('components.messageStream.executing', { defaultValue: 'Executing…' })}
                  </p>
                </div>
              </div>
            )}

            {/* Success Result */}
            {status === 'success' && formattedResult && (
              <ToolResultDisplay result={formattedResult} isError={false} />
            )}

            {/* Error Result */}
            {status === 'error' && error && <ToolResultDisplay result={error} isError={true} />}
          </div>
        </details>
      )}
    </div>
  );
}

export default MessageStream;
