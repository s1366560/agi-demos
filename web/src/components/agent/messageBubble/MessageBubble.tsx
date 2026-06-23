/**
 * MessageBubble - Modern message bubble component
 *
 * Compound Component Pattern for flexible message rendering.
 * Features quiet surfaces, smooth state changes, and focused message rendering.
 */

import type React from 'react';
import { memo, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import type { Components } from 'react-markdown';
import ReactMarkdown from 'react-markdown';

import {
  Image as ImageIcon,
  Film,
  Music,
  FileText,
  Table,
  Presentation,
  Archive,
  FileCode,
  Paperclip,
  File,
  Download,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  FileOutput,
  Lightbulb,
  Loader2,
  PanelRight,
  RefreshCw,
  User,
  Wrench,
  XCircle,
} from 'lucide-react';

import { useCanvasStore, type CanvasContentType } from '@/stores/canvasStore';
import { useLayoutModeStore } from '@/stores/layoutMode';
import { useSandboxStore } from '@/stores/sandbox';

import { artifactService, fetchArtifactResource } from '@/services/artifactService';

import { useLocaleNumberFormat } from '@/i18n/formatters';
import { formatDateTime, formatTimeOnly } from '@/utils/date';
import { normalizeExecutionSummary } from '@/utils/executionSummary';
import { isOfficeMimeType, isOfficeExtension } from '@/utils/filePreview';
import {
  findArtifactForSandboxPath,
  isSafeArtifactUrl,
  normalizeSandboxPath,
  resolveSandboxArtifactUrl,
} from '@/utils/sandboxArtifactPath';

import { CodeBlock as SharedCodeBlock } from '../chat/CodeBlock';
import { useMarkdownPlugins } from '../chat/markdownPlugins';
import { MessageActionBar } from '../chat/MessageActionBar';
import { safeMarkdownComponents } from '../chat/safeMarkdownComponents';
import { SaveTemplateModal } from '../chat/SaveTemplateModal';
import { InlineHITLCard } from '../InlineHITLCard';
import {
  ASSISTANT_AVATAR_CLASSES,
  ASSISTANT_BUBBLE_CLASSES,
  MARKDOWN_PROSE_CLASSES,
  MESSAGE_MAX_WIDTH_CLASSES,
  WIDE_MESSAGE_MAX_WIDTH_CLASSES,
} from '../styles';

import { getErrorMessage } from '@/types/common';

import type {
  ArtifactCreatedProps,
  AssistantMessageProps,
  MessageBubbleCompound,
  MessageBubbleRootProps,
  TextDeltaProps,
  TextEndProps,
  ThoughtProps,
  ToolExecutionProps,
  UserMessageProps,
  WorkPlanProps,
} from './types';
import type {
  ActEvent,
  Artifact,
  ArtifactCreatedEvent,
  ArtifactReference,
  ClarificationAskedEventData,
  DecisionAskedEventData,
  EnvVarRequestedEventData,
  ObserveEvent,
  PermissionAskedEventData,
  PermissionAskedTimelineEvent,
  PermissionRequestedTimelineEvent,
  TimelineEvent,
} from '../../../types/agent';

// ========================================
// Utilities
// ========================================

const COUNT_FORMATTER_FALLBACK = new Intl.NumberFormat('en-US');
const SUMMARY_PILL_CLASSES =
  'inline-flex items-center gap-1 rounded-full border border-slate-200/60 bg-slate-50/80 px-2.5 py-1 text-xs text-neutral-600 dark:border-slate-800/60 dark:bg-slate-800/50';

const formatCount = (
  value: number,
  formatter: Intl.NumberFormat = COUNT_FORMATTER_FALLBACK
): string => formatter.format(value);

const SummaryPill: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <span className={SUMMARY_PILL_CLASSES}>
    <span className="text-neutral-500">{label}</span>
    <span className="font-medium text-neutral-800">{value}</span>
  </span>
);

const USER_MESSAGE_MAX_WIDTH_CLASSES = 'max-w-[85%] md:max-w-[75%] lg:max-w-[70%]';
const SANDBOX_FILE_LINK_PREFIX = '#sandbox-file:';
const CANVAS_FORCE_VIEW_MODE_EVENT = 'canvas:force-view-mode';
const SANDBOX_FILE_PATH_PATTERN =
  /(^|[\s:：|])((?:\/workspace\/|~\/|(?:output|outputs|artifacts|input|inputs|tmp|workspace)\/)[^\s)\]）}>`"']*\.[A-Za-z0-9]{1,12})/g;
const TEXT_FILE_EXTENSIONS = new Set([
  'txt',
  'md',
  'markdown',
  'json',
  'jsonl',
  'yaml',
  'yml',
  'toml',
  'csv',
  'tsv',
  'xml',
  'html',
  'css',
  'scss',
  'js',
  'jsx',
  'ts',
  'tsx',
  'py',
  'go',
  'rs',
  'java',
  'kt',
  'rb',
  'php',
  'sh',
  'bash',
  'zsh',
  'sql',
  'log',
]);

const MessageTime: React.FC<{
  timestamp?: number | undefined;
  className?: string | undefined;
}> = ({ timestamp, className = '' }) => {
  if (!timestamp) {
    return null;
  }

  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return (
    <time
      dateTime={date.toISOString()}
      title={formatDateTime(timestamp)}
      className={`inline-flex flex-shrink-0 items-center gap-1 text-2xs leading-none text-slate-400 dark:text-slate-500 ${className}`}
    >
      <Clock size={11} aria-hidden="true" />
      <span>{formatTimeOnly(timestamp)}</span>
    </time>
  );
};

function getFileNameFromPath(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? path;
}

function getFileExtension(path: string): string {
  const name = getFileNameFromPath(path);
  const dotIndex = name.lastIndexOf('.');
  return dotIndex >= 0 ? name.slice(dotIndex + 1).toLowerCase() : '';
}

function getCanvasTypeForSandboxPath(path: string): CanvasContentType {
  const ext = getFileExtension(path);
  if (ext === 'md' || ext === 'markdown') return 'markdown';
  if (['json', 'jsonl', 'csv', 'tsv', 'xml', 'yaml', 'yml', 'toml'].includes(ext)) return 'data';
  if (['html', 'htm', 'svg'].includes(ext)) return 'preview';
  return 'code';
}

function getCanvasTypeForSandboxFile(path: string, mimeType?: string | null): CanvasContentType {
  const mime = (mimeType ?? '').toLowerCase();
  if (mime.includes('markdown')) return 'markdown';
  if (
    mime.includes('json') ||
    mime.includes('csv') ||
    mime.includes('xml') ||
    mime.includes('yaml') ||
    mime.includes('toml')
  ) {
    return 'data';
  }
  if (mime.includes('html') || mime.includes('svg')) return 'preview';
  return getCanvasTypeForSandboxPath(path);
}

function getMimeTypeForSandboxPath(path: string): string | undefined {
  const ext = getFileExtension(path);
  if (ext === 'md' || ext === 'markdown') return 'text/markdown';
  if (ext === 'html' || ext === 'htm') return 'text/html';
  if (ext === 'svg') return 'image/svg+xml';
  if (ext === 'json' || ext === 'jsonl') return 'application/json';
  if (ext === 'csv') return 'text/csv';
  if (ext === 'pdf') return 'application/pdf';
  if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext))
    return `image/${ext === 'jpg' ? 'jpeg' : ext}`;
  if (TEXT_FILE_EXTENSIONS.has(ext)) return 'text/plain';
  return undefined;
}

function isPdfSandboxFile(path: string, mimeType?: string | null): boolean {
  return (
    (mimeType ?? '').toLowerCase().includes('application/pdf') || getFileExtension(path) === 'pdf'
  );
}

function shouldPreviewSandboxFileByUrl(path: string, mimeType?: string | null): boolean {
  const mime = (mimeType ?? '').toLowerCase();
  return (
    isPdfSandboxFile(path, mime) ||
    mime.startsWith('image/') ||
    mime.startsWith('video/') ||
    mime.startsWith('audio/') ||
    isOfficeMimeType(mime) ||
    isOfficeExtension(path)
  );
}

function openSandboxUrlPreviewTab(params: {
  id: string;
  title: string;
  url: string;
  mimeType?: string | undefined;
  artifactId?: string | undefined;
}) {
  const mimeType = params.mimeType || getMimeTypeForSandboxPath(params.title);
  useCanvasStore.getState().openTab({
    id: params.id,
    title: params.title,
    type: 'preview',
    content: params.url,
    mimeType,
    pdfVerified: isPdfSandboxFile(params.title, mimeType) || undefined,
    artifactId: params.artifactId,
    artifactUrl: params.url,
  });
  useLayoutModeStore.getState().setMode('canvas');
  requestCanvasViewMode();
}

function requestCanvasViewMode() {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(CANVAS_FORCE_VIEW_MODE_EVENT));
  window.setTimeout(() => {
    window.dispatchEvent(new CustomEvent(CANVAS_FORCE_VIEW_MODE_EVENT));
  }, 0);
}

function escapeMarkdownLinkText(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/\]/g, '\\]');
}

function linkifySandboxPaths(content: string): string {
  const lines = content.split('\n');
  let inFence = false;
  return lines
    .map((line) => {
      if (/^\s*```/.test(line)) {
        inFence = !inFence;
        return line;
      }
      if (inFence) return line;
      return line.replace(SANDBOX_FILE_PATH_PATTERN, (_match, prefix: string, path: string) => {
        return `${prefix}[${escapeMarkdownLinkText(path)}](${SANDBOX_FILE_LINK_PREFIX}${encodeURIComponent(path)})`;
      });
    })
    .join('\n');
}

function collectNodeText(node: React.ReactNode): string {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(collectNodeText).join('');
  return '';
}

function isSandboxFilePathText(value: string): boolean {
  const trimmed = value.trim();
  const padded = ` ${trimmed}`;
  SANDBOX_FILE_PATH_PATTERN.lastIndex = 0;
  const matches = SANDBOX_FILE_PATH_PATTERN.test(padded);
  SANDBOX_FILE_PATH_PATTERN.lastIndex = 0;
  return (
    trimmed === value &&
    matches &&
    padded.replace(SANDBOX_FILE_PATH_PATTERN, '').trim().length === 0
  );
}

function getSandboxFilePathFromHref(href: string | undefined): string | null {
  if (!href) return null;

  if (href.startsWith(SANDBOX_FILE_LINK_PREFIX)) {
    return safeDecodeURIComponent(href.slice(SANDBOX_FILE_LINK_PREFIX.length));
  }

  const decodedHref = safeDecodeURIComponent(href);
  if (isSandboxFilePathText(decodedHref)) return decodedHref;

  if (typeof window === 'undefined') return null;

  try {
    const url = new URL(decodedHref, window.location.origin);
    if (url.origin === window.location.origin && isSandboxFilePathText(url.pathname)) {
      return url.pathname;
    }
  } catch {
    // Non-URL hrefs are handled above.
  }

  return null;
}

async function openArtifactUrlInCanvas(params: {
  id: string;
  title: string;
  url: string;
  artifactId?: string | undefined;
  mimeType?: string | undefined;
}): Promise<boolean> {
  const { id, title, url, artifactId } = params;
  if (!url || !isSafeArtifactUrl(url)) return false;

  const mime = (params.mimeType || getMimeTypeForSandboxPath(title) || '').toLowerCase();

  if (shouldPreviewSandboxFileByUrl(title, mime)) {
    openSandboxUrlPreviewTab({
      id,
      title,
      url,
      mimeType: mime,
      artifactId,
    });
    return true;
  }

  const response = await fetchArtifactResource(url);
  if (!response.ok) return false;
  const responseType = response.headers.get('content-type')?.toLowerCase() || '';
  if (shouldPreviewSandboxFileByUrl(title, responseType)) {
    openSandboxUrlPreviewTab({
      id,
      title,
      url,
      mimeType: responseType || mime,
      artifactId,
    });
    return true;
  }

  const content = await response.text();
  const contentType = getCanvasTypeForSandboxFile(title, responseType || mime);
  useCanvasStore.getState().openTab({
    id,
    title,
    type: contentType,
    content,
    language: getFileExtension(title) || undefined,
    mimeType: params.mimeType,
    artifactId,
    artifactUrl: url,
  });
  useLayoutModeStore.getState().setMode('canvas');
  requestCanvasViewMode();
  return true;
}

async function openArtifactInCanvas(artifact: Artifact, requestedPath: string): Promise<boolean> {
  const url = artifact.url || artifact.previewUrl;
  const title = artifact.filename || getFileNameFromPath(requestedPath);
  return await openArtifactUrlInCanvas({
    id: artifact.id,
    title,
    url: url || '',
    artifactId: artifact.id,
    mimeType: artifact.mimeType,
  });
}

async function openSandboxPathInCanvas(path: string): Promise<void> {
  const normalizedPath = normalizeSandboxPath(path);

  try {
    const artifact = await findArtifactForSandboxPath(path);
    if (artifact) {
      const opened = await openArtifactInCanvas(artifact, path);
      if (opened) return;
    }

    const resolvedArtifactUrl = await resolveSandboxArtifactUrl(path);
    if (resolvedArtifactUrl) {
      const opened = await openArtifactUrlInCanvas({
        id: `${SANDBOX_FILE_LINK_PREFIX}${normalizedPath}`,
        title: getFileNameFromPath(path),
        url: resolvedArtifactUrl,
      });
      if (opened) return;
    }
  } catch {
    // Fall back to direct sandbox read below.
  }

  const result = await useSandboxStore
    .getState()
    .executeTool('read', { file_path: normalizedPath, offset: 0, limit: 50000, raw: true }, 20);
  if (!result.success || result.isError) return;

  const title = getFileNameFromPath(path);
  const mimeType = getMimeTypeForSandboxPath(path);
  const type = getCanvasTypeForSandboxFile(path, mimeType);
  useCanvasStore.getState().openTab({
    id: `${SANDBOX_FILE_LINK_PREFIX}${normalizedPath}`,
    title,
    type,
    content: result.content,
    language: getFileExtension(path) || undefined,
    mimeType,
  });
  useLayoutModeStore.getState().setMode('canvas');
  requestCanvasViewMode();
}

const ExecutionSummaryPanel: React.FC<{
  summary: ReturnType<typeof normalizeExecutionSummary>;
}> = ({ summary }) => {
  const countFormatter = useLocaleNumberFormat();
  if (!summary) {
    return null;
  }

  const taskSummary = summary.tasks;

  return (
    <div className="mb-3 flex flex-wrap gap-2">
      <SummaryPill label="Steps" value={formatCount(summary.stepCount, countFormatter)} />
      {taskSummary ? (
        <SummaryPill
          label="Tasks"
          value={`${formatCount(taskSummary.completed, countFormatter)}/${formatCount(taskSummary.total, countFormatter)}`}
        />
      ) : null}
      {taskSummary && taskSummary.remaining > 0 ? (
        <SummaryPill label="Remaining" value={formatCount(taskSummary.remaining, countFormatter)} />
      ) : null}
      {summary.artifactCount > 0 ? (
        <SummaryPill label="Artifacts" value={formatCount(summary.artifactCount, countFormatter)} />
      ) : null}
      {summary.callCount > 0 ? (
        <SummaryPill label="LLM calls" value={formatCount(summary.callCount, countFormatter)} />
      ) : null}
      {summary.totalTokens.total > 0 ? (
        <SummaryPill
          label="Tokens"
          value={formatCount(summary.totalTokens.total, countFormatter)}
        />
      ) : null}
      {summary.totalCost > 0 ? (
        <SummaryPill label="Cost" value={summary.totalCostFormatted} />
      ) : null}
    </div>
  );
};

// ========================================
// HITL Adapters - Convert TimelineEvent to SSE format for InlineHITLCard
// ========================================
// HITL Adapters - Convert TimelineEvent to SSE format for InlineHITLCard
// ========================================

/**
 * Convert ClarificationAskedTimelineEvent to ClarificationAskedEventData (snake_case)
 */
const toClarificationData = (event: TimelineEvent): ClarificationAskedEventData | undefined => {
  if (event.type !== 'clarification_asked') return undefined;
  const e = event as TimelineEvent & {
    requestId: string;
    question: string;
    clarificationType: string;
    options: unknown[];
    allowCustom: boolean;
    context?: Record<string, unknown> | undefined;
  };
  return {
    request_id: e.requestId,
    question: e.question,
    clarification_type: e.clarificationType as ClarificationAskedEventData['clarification_type'],
    options: e.options as ClarificationAskedEventData['options'],
    allow_custom: e.allowCustom,
    context: e.context || {},
  };
};

/**
 * Convert DecisionAskedTimelineEvent to DecisionAskedEventData (snake_case)
 */
const toDecisionData = (event: TimelineEvent): DecisionAskedEventData | undefined => {
  if (event.type !== 'decision_asked') return undefined;
  const e = event as TimelineEvent & {
    requestId: string;
    question: string;
    decisionType: string;
    options: unknown[];
    allowCustom?: boolean | undefined;
    context?: Record<string, unknown> | undefined;
    defaultOption?: string | undefined;
  };
  return {
    request_id: e.requestId,
    question: e.question,
    decision_type: e.decisionType as DecisionAskedEventData['decision_type'],
    options: e.options as DecisionAskedEventData['options'],
    allow_custom: e.allowCustom || false,
    context: e.context || {},
    default_option: e.defaultOption,
  };
};

/**
 * Convert EnvVarRequestedTimelineEvent to EnvVarRequestedEventData (snake_case)
 */
const toEnvVarData = (event: TimelineEvent): EnvVarRequestedEventData | undefined => {
  if (event.type !== 'env_var_requested') return undefined;
  const e = event as TimelineEvent & {
    requestId: string;
    toolName: string;
    fields: EnvVarRequestedEventData['fields'];
    message?: string | undefined;
    context?: Record<string, unknown> | undefined;
  };
  return {
    request_id: e.requestId,
    tool_name: e.toolName,
    fields: e.fields,
    message: e.message,
    context: e.context,
  };
};

/**
 * Convert PermissionAskedTimelineEvent to PermissionAskedEventData (snake_case)
 * Supports both 'permission_asked' (SSE) and 'permission_requested' (DB) event types
 */
const toPermissionData = (event: TimelineEvent): PermissionAskedEventData | undefined => {
  if (event.type !== 'permission_asked' && event.type !== 'permission_requested') return undefined;
  const e = event;
  if (event.type === 'permission_asked') {
    const asked = e as PermissionAskedTimelineEvent;
    return {
      request_id: asked.requestId,
      tool_name: asked.toolName,
      permission_type: 'ask',
      description: asked.description,
      risk_level: asked.riskLevel,
      context: asked.context,
    };
  } else {
    const requested = e as PermissionRequestedTimelineEvent;
    return {
      request_id: requested.requestId,
      tool_name: requested.resource || 'unknown',
      permission_type: 'ask',
      description: requested.reason || requested.action || '',
      risk_level: requested.riskLevel,
      context: requested.context,
    };
  }
};

// ========================================
// Utilities
// ========================================

// Format tool output for display
const formatToolOutput = (
  output: unknown
): { type: 'text' | 'json' | 'error'; content: string } => {
  if (!output) return { type: 'text', content: 'No output' };

  if (typeof output === 'string') {
    if (output.toLowerCase().includes('error:') || output.toLowerCase().includes('failed')) {
      return { type: 'error', content: output };
    }
    return { type: 'text', content: output };
  }

  if (typeof output === 'object') {
    if ('error' in output || 'errorMessage' in output || 'error_message' in output) {
      const errorContent = (
        'errorMessage' in output
          ? output.errorMessage
          : 'error_message' in output
            ? output.error_message
            : 'error' in output
              ? output.error
              : undefined
      ) as string | undefined;
      if (typeof errorContent === 'string') {
        return { type: 'error', content: errorContent };
      }
    }

    try {
      return { type: 'json', content: JSON.stringify(output, null, 2) };
    } catch {
      return { type: 'text', content: JSON.stringify(output) };
    }
  }

  return { type: 'text', content: JSON.stringify(output) };
};

// Find matching observe event for act
const findMatchingObserve = (
  actEvent: ActEvent,
  events: TimelineEvent[]
): ObserveEvent | undefined => {
  const actIndex = events.indexOf(actEvent as unknown as TimelineEvent);
  if (actIndex === -1) return undefined;

  for (let i = actIndex + 1; i < events.length; i++) {
    const event = events[i];
    if (event && event.type === 'observe') {
      const observeEvent = event as unknown as ObserveEvent;
      if (actEvent.execution_id && observeEvent.execution_id) {
        if (actEvent.execution_id === observeEvent.execution_id) return observeEvent;
      } else if (observeEvent.toolName === actEvent.toolName) {
        return observeEvent;
      }
    }
  }
  return undefined;
};

// ========================================
// Sub-Components - Modern Design
// ========================================

function formatBytesSize(bytes: number): string {
  if (bytes < 1024) return `${String(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getFileIconForMime(
  mimeType: string
): React.ComponentType<{ size?: number; className?: string }> {
  if (mimeType.startsWith('image/')) return ImageIcon;
  if (mimeType.startsWith('video/')) return Film;
  if (mimeType.startsWith('audio/')) return Music;
  if (mimeType === 'application/pdf') return FileText;
  if (mimeType.includes('spreadsheet') || mimeType.includes('excel')) return Table;
  if (mimeType.includes('presentation') || mimeType.includes('powerpoint')) return Presentation;
  if (mimeType.includes('zip') || mimeType.includes('tar') || mimeType.includes('compress'))
    return Archive;
  if (
    mimeType.startsWith('text/') ||
    mimeType.includes('json') ||
    mimeType.includes('xml') ||
    mimeType.includes('javascript') ||
    mimeType.includes('typescript')
  )
    return FileCode;
  return FileText;
}

function getArtifactLabel(artifact: ArtifactReference): string {
  const rawValue = artifact.object_key ?? artifact.url;
  try {
    const url = new URL(rawValue, 'https://memstack.local');
    const pathParts = url.pathname.split('/').filter(Boolean);
    const fileName = pathParts[pathParts.length - 1];
    return fileName ? safeDecodeURIComponent(fileName) : rawValue;
  } catch {
    const pathParts = rawValue.split('/').filter(Boolean);
    const fileName = pathParts[pathParts.length - 1];
    return fileName ? safeDecodeURIComponent(fileName) : rawValue;
  }
}

function safeDecodeURIComponent(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

const ArtifactReferenceList: React.FC<{
  artifacts?: ArtifactReference[] | undefined;
}> = ({ artifacts }) => {
  if (!artifacts || artifacts.length === 0) {
    return null;
  }

  return (
    <div className="mt-3 flex flex-col gap-1.5">
      {artifacts.map((artifact) => {
        const mimeType = artifact.mime_type ?? 'application/octet-stream';
        const FileIcon = getFileIconForMime(mimeType);
        return (
          <a
            key={`${artifact.url}-${artifact.object_key ?? ''}`}
            href={artifact.url}
            target="_blank"
            rel="noopener noreferrer"
            download
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200/80 bg-slate-50 px-3 py-1.5 text-sm text-slate-700 transition-colors hover:bg-slate-100 dark:border-slate-700/70 dark:bg-slate-800 dark:text-slate-200"
          >
            <FileIcon size={16} className="text-slate-500 dark:text-slate-400" />
            <span className="truncate">{getArtifactLabel(artifact)}</span>
            {typeof artifact.size_bytes === 'number' ? (
              <span className="text-2xs whitespace-nowrap text-slate-400 dark:text-slate-500">
                {formatBytesSize(artifact.size_bytes)}
              </span>
            ) : null}
            <Download
              size={14}
              className="ml-auto flex-shrink-0 text-slate-400 dark:text-slate-500"
            />
          </a>
        );
      })}
    </div>
  );
};

const getSafeArtifactReferences = (
  artifacts: ArtifactReference[] | undefined
): ArtifactReference[] => {
  if (!artifacts) {
    return [];
  }
  return artifacts.filter((artifact) => isSafeArtifactUrl(artifact.url));
};

const SandboxFileButton: React.FC<{ path: string; children: React.ReactNode }> = ({
  path,
  children,
}) => {
  const [opening, setOpening] = useState(false);
  const { t } = useTranslation();

  return (
    <button
      type="button"
      disabled={opening}
      onClick={(event) => {
        event.preventDefault();
        setOpening(true);
        void openSandboxPathInCanvas(path).finally(() => {
          setOpening(false);
        });
      }}
      className="inline-flex max-w-full items-baseline gap-1 rounded px-1 text-left font-medium text-primary underline decoration-primary/30 underline-offset-2 transition-colors hover:text-primary/80 hover:decoration-primary/70 disabled:cursor-wait disabled:opacity-60"
      title={t('agent.messageBubble.openSandboxFileInCanvas', {
        defaultValue: 'Open {{path}} in Canvas',
        path,
      })}
    >
      <FileText size={12} className="relative top-0.5 shrink-0" aria-hidden="true" />
      <span className="truncate">{children}</span>
    </button>
  );
};

const SandboxFileLink: Components['a'] = ({ href, children, ...props }) => {
  const path = getSandboxFilePathFromHref(href);
  if (!path) {
    return (
      <a href={href} {...props}>
        {children}
      </a>
    );
  }

  return <SandboxFileButton path={path}>{children}</SandboxFileButton>;
};

const SandboxAwareInlineCode: Components['code'] = ({ children, className, ...props }) => {
  const text = collectNodeText(children);
  if (!className && isSandboxFilePathText(text)) {
    return <SandboxFileButton path={text}>{children}</SandboxFileButton>;
  }
  return (
    <code className={className} {...props}>
      {children}
    </code>
  );
};

// User Message Component - Modern floating style with action bar
const UserMessage: React.FC<UserMessageProps> = memo(
  ({ content, timestamp, onReply, forcedSkillName, forcedSubAgentName, fileMetadata }) => {
    const { t } = useTranslation();

    if (!content) return null;
    const hasFiles = fileMetadata && fileMetadata.length > 0;

    // Determine bubble style based on forced type
    const isSkill = !!forcedSkillName;
    const isSubAgent = !!forcedSubAgentName;
    const isForced = isSkill || isSubAgent;

    let gradientClass = '';
    if (isSubAgent) {
      gradientClass = 'bg-purple-300/70 dark:bg-purple-700/60';
    } else if (isSkill) {
      gradientClass = 'bg-primary/30';
    }

    return (
      <div className="group flex flex-col items-end gap-1 pb-1">
        {/* Main row: bubble + avatar */}
        <div className="flex items-end justify-end gap-3 w-full">
          <div className={USER_MESSAGE_MAX_WIDTH_CLASSES}>
            {timestamp ? (
              <div className="mb-1 flex justify-end pr-1">
                <MessageTime timestamp={timestamp} />
              </div>
            ) : null}
            <div
              className={
                isForced ? `relative ${gradientClass} rounded-lg rounded-br-sm p-px` : 'relative'
              }
            >
              {/* Badge Icon for Forced Execution */}
              {isForced && (
                <div
                  className={`absolute left-0 top-1/2 -translate-x-1/2 -translate-y-1/2 w-4 h-4 rounded-full flex items-center justify-center ring-2 ring-slate-50 dark:ring-slate-800 z-10 ${isSubAgent ? 'bg-purple-500' : 'bg-primary'}`}
                >
                  {isSubAgent ? (
                    <svg
                      className="w-2.5 h-2.5 text-slate-50"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="3"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <title>
                        {t('agent.messageBubble.subAgentIcon', { defaultValue: 'SubAgent Icon' })}
                      </title>
                      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
                      <line x1="8" y1="21" x2="16" y2="21" />
                      <line x1="12" y1="17" x2="12" y2="21" />
                    </svg>
                  ) : (
                    <svg
                      className="w-2.5 h-2.5 text-slate-50"
                      viewBox="0 0 16 16"
                      fill="currentColor"
                    >
                      <path d="M9.5 0L4 9h4l-1.5 7L13 7H9l.5-7z" />
                    </svg>
                  )}
                </div>
              )}

              <div
                className={
                  isForced
                    ? 'bg-slate-50/80 dark:bg-slate-800/70 rounded-lg rounded-br-sm px-4 py-2'
                    : 'bg-slate-50/80 dark:bg-slate-800/70 border border-slate-200/40 dark:border-slate-700/40 rounded-lg rounded-br-sm px-4 py-2 shadow-[0_1px_2px_rgba(15,23,42,0.02)]'
                }
              >
                <p className="text-sm leading-[1.5] whitespace-pre-wrap break-words text-slate-800 dark:text-slate-100 font-normal">
                  {content}
                </p>
              </div>
              {/* Action bar - appears on hover at top-right */}
              <div className="absolute -top-3 right-2 z-10">
                <MessageActionBar role="user" content={content} onReply={onReply} />
              </div>

              {/* Badge Label */}
              {isForced && (
                <div
                  className={`absolute bottom-0 right-4 translate-y-1/2 px-1.5 bg-white dark:bg-slate-800 text-xs-plus font-medium leading-none tracking-wide ${isSubAgent ? 'text-purple-600 dark:text-purple-400' : 'text-primary dark:text-primary-300'}`}
                >
                  {isSubAgent ? `@${forcedSubAgentName}` : forcedSkillName}
                </div>
              )}
            </div>
          </div>
          <div className="w-8 h-8 rounded-lg bg-slate-100/80 dark:bg-slate-800/70 ring-1 ring-slate-200/45 dark:ring-slate-700/45 flex items-center justify-center flex-shrink-0">
            <User size={16} className="text-slate-500 dark:text-slate-400" />
          </div>
        </div>
        {/* Attachment row: below bubble, aligned under bubble (offset by avatar width) */}
        {hasFiles && (
          <div className={`flex flex-col items-end gap-1 mr-11 ${isForced ? 'mt-2' : 'mt-0.5'}`}>
            {fileMetadata.map((file, idx) => (
              <div
                key={idx}
                className="inline-flex items-center gap-2 px-3 py-1.5 bg-slate-100/80 dark:bg-slate-800/70 border border-slate-200/40 dark:border-slate-700/40 rounded-md"
              >
                {(() => {
                  const FileIcon = getFileIconForMime(file.mime_type);
                  return <FileIcon size={16} className="text-slate-500 dark:text-slate-400" />;
                })()}
                <span className="text-xs text-slate-700 dark:text-slate-300 truncate max-w-50">
                  {file.filename}
                </span>
                <span className="text-2xs text-slate-400 dark:text-slate-500 whitespace-nowrap">
                  {formatBytesSize(file.size_bytes)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }
);
UserMessage.displayName = 'MessageBubble.User';

// Stable component references hoisted to module scope to prevent ReactMarkdown re-parsing
const ASSISTANT_COMPONENTS: Components = {
  pre: SharedCodeBlock,
  ...safeMarkdownComponents,
  a: SandboxFileLink,
  code: SandboxAwareInlineCode,
};

// Assistant Message Component - Modern card style with action bar
const AssistantMessage: React.FC<AssistantMessageProps> = memo(
  ({ content, timestamp, metadata, artifacts, isStreaming, isPinned, onPin, onReply }) => {
    const [showSaveTemplate, setShowSaveTemplate] = useState(false);
    const markdownContent = useMemo(() => linkifySandboxPaths(content), [content]);
    const { remarkPlugins, rehypePlugins } = useMarkdownPlugins(markdownContent);
    const executionSummary = normalizeExecutionSummary(metadata?.executionSummary);
    const completionArtifacts = getSafeArtifactReferences(
      artifacts ?? (metadata?.artifacts as ArtifactReference[] | undefined)
    );
    if (!content && !isStreaming && !executionSummary && completionArtifacts.length === 0)
      return null;
    return (
      <div className="group flex items-start gap-3 pb-1">
        <div className={ASSISTANT_AVATAR_CLASSES}>
          <Bot size={18} className="text-primary" />
        </div>
        <div className={`flex-1 ${MESSAGE_MAX_WIDTH_CLASSES}`}>
          {timestamp ? (
            <div className="mb-1 flex pl-1">
              <MessageTime timestamp={timestamp} />
            </div>
          ) : null}
          <div className="relative">
            <div className={ASSISTANT_BUBBLE_CLASSES}>
              <ExecutionSummaryPanel summary={executionSummary} />
              <div className={MARKDOWN_PROSE_CLASSES}>
                {content ? (
                  <ReactMarkdown
                    remarkPlugins={remarkPlugins}
                    rehypePlugins={rehypePlugins}
                    components={ASSISTANT_COMPONENTS}
                  >
                    {markdownContent}
                  </ReactMarkdown>
                ) : null}
              </div>
              <ArtifactReferenceList artifacts={completionArtifacts} />
            </div>
            {/* Action bar - appears on hover at top-right */}
            {!isStreaming && content && (
              <div className="absolute -top-3 right-2 z-10">
                <MessageActionBar
                  role="assistant"
                  content={content}
                  isPinned={isPinned}
                  onPin={onPin}
                  onReply={onReply}
                  onSaveAsTemplate={() => {
                    setShowSaveTemplate(true);
                  }}
                />
              </div>
            )}
          </div>
        </div>
        {showSaveTemplate && (
          <SaveTemplateModal
            content={content || ''}
            visible={showSaveTemplate}
            onClose={() => {
              setShowSaveTemplate(false);
            }}
            onSave={() => {
              setShowSaveTemplate(false);
            }}
          />
        )}
      </div>
    );
  }
);
AssistantMessage.displayName = 'MessageBubble.Assistant';

// Text Delta Component (for streaming content)
const TextDelta: React.FC<TextDeltaProps> = memo(({ content, timestamp }) => {
  const markdownContent = useMemo(() => linkifySandboxPaths(content), [content]);
  const { remarkPlugins, rehypePlugins } = useMarkdownPlugins(markdownContent);
  if (!content) return null;
  return (
    <div className="flex items-start gap-3 pb-1">
      <div className={ASSISTANT_AVATAR_CLASSES}>
        <Bot size={18} className="text-primary" />
      </div>
      <div className={`flex-1 ${MESSAGE_MAX_WIDTH_CLASSES}`}>
        {timestamp ? (
          <div className="mb-1 flex pl-1">
            <MessageTime timestamp={timestamp} />
          </div>
        ) : null}
        <div className={ASSISTANT_BUBBLE_CLASSES}>
          <div className={MARKDOWN_PROSE_CLASSES}>
            <ReactMarkdown
              remarkPlugins={remarkPlugins}
              rehypePlugins={rehypePlugins}
              components={ASSISTANT_COMPONENTS}
            >
              {markdownContent}
            </ReactMarkdown>
          </div>
        </div>
      </div>
    </div>
  );
});
TextDelta.displayName = 'MessageBubble.TextDelta';

// Thought/Reasoning Component - Modern pill style
const Thought: React.FC<ThoughtProps> = memo(({ content, timestamp }) => {
  const [expanded, setExpanded] = useState(true);
  const { t } = useTranslation();

  if (!content) return null;

  return (
    <div className="flex items-start gap-3 pb-1">
      <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
        <Lightbulb size={16} className="text-slate-500 dark:text-slate-400" />
      </div>
      <div className={`flex-1 ${MESSAGE_MAX_WIDTH_CLASSES}`}>
        <div className="bg-slate-50/80 dark:bg-slate-800/50 border border-slate-200/45 dark:border-slate-700/45 rounded-md overflow-hidden">
          <button
            type="button"
            onClick={() => {
              setExpanded(!expanded);
            }}
            className="w-full px-4 py-2.5 flex items-center gap-2 hover:bg-slate-100/50 dark:hover:bg-slate-700/30 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset"
          >
            <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              {t('agent.messageBubble.reasoning', 'Reasoning')}
            </span>
            <MessageTime timestamp={timestamp} className="ml-auto" />
            {expanded ? (
              <ChevronUp size={14} className="text-slate-400" />
            ) : (
              <ChevronDown size={14} className="text-slate-400" />
            )}
          </button>
          {expanded && (
            <div className="px-4 pb-3">
              <p className="text-sm text-slate-600 dark:text-slate-400 leading-relaxed whitespace-pre-wrap">
                {content}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
});
Thought.displayName = 'MessageBubble.Thought';

// Tool Execution Component - Modern collapsible card
const ToolExecution: React.FC<ToolExecutionProps> = memo(({ event, observeEvent }) => {
  const [expanded, setExpanded] = useState(!observeEvent);
  const { t } = useTranslation();

  const hasError = observeEvent?.isError;
  const duration = observeEvent ? (observeEvent.timestamp || 0) - (event.timestamp || 0) : null;

  const statusIcon = observeEvent ? (
    hasError ? (
      <XCircle size={16} className="text-red-500" />
    ) : (
      <CheckCircle2 size={16} className="text-emerald-500" />
    )
  ) : (
    <Loader2 size={16} className="text-blue-500 animate-spin motion-reduce:animate-none" />
  );

  const statusText = observeEvent
    ? hasError
      ? t('agent.messageBubble.failed', 'Failed')
      : t('agent.messageBubble.success', 'Success')
    : t('agent.messageBubble.running', 'Running');

  const statusColor = observeEvent
    ? hasError
      ? 'bg-red-50 text-red-600 border-red-200 dark:bg-red-900/20 dark:text-red-400 dark:border-red-800/50'
      : 'bg-emerald-50 text-emerald-600 border-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-400 dark:border-emerald-800/50'
    : 'bg-blue-50 text-blue-600 border-blue-200 dark:bg-blue-900/20 dark:text-blue-400 dark:border-blue-800/50';

  return (
    <div className="flex items-start gap-3 pb-1">
      <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
        <Wrench size={16} className="text-slate-500 dark:text-slate-400" />
      </div>
      <div className={`flex-1 min-w-0 ${WIDE_MESSAGE_MAX_WIDTH_CLASSES}`}>
        <div className="bg-slate-50/80 dark:bg-slate-800/55 border border-slate-200/45 dark:border-slate-700/40 rounded-md overflow-hidden shadow-[0_1px_2px_rgba(15,23,42,0.02)]">
          {/* Header */}
          <button
            type="button"
            onClick={() => {
              setExpanded(!expanded);
            }}
            className="w-full px-4 py-3 flex items-center justify-between hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset"
          >
            <div className="flex items-center gap-3 min-w-0 flex-1">
              <span className="font-medium text-sm text-slate-800 dark:text-slate-200 truncate">
                {event.toolName || 'Unknown Tool'}
              </span>
              <span
                className={`flex-shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${statusColor}`}
              >
                {statusIcon}
                {statusText}
              </span>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0 ml-2">
              {duration && duration > 0 && (
                <span className="text-xs text-slate-400 flex items-center gap-1">
                  <Clock size={12} />
                  {duration}ms
                </span>
              )}
              {expanded ? (
                <ChevronUp size={16} className="text-slate-400" />
              ) : (
                <ChevronDown size={16} className="text-slate-400" />
              )}
            </div>
          </button>

          {/* Content */}
          {expanded && (
            <div className="px-4 pb-4 border-t border-slate-200/45 dark:border-slate-700/35">
              {/* Input */}
              <div className="mt-3">
                <p className="text-2xs font-semibold text-slate-500 dark:text-slate-400 mb-2 uppercase tracking-wide">
                  {t('agent.messageBubble.input', 'Input')}
                </p>
                <div className="rounded-lg overflow-hidden border border-slate-200 dark:border-slate-700">
                  <div className="bg-slate-50 dark:bg-slate-900/50 px-3 py-1.5 text-xs text-slate-500 border-b border-slate-200 dark:border-slate-700 flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-slate-400"></span>
                    JSON
                  </div>
                  <pre className="bg-white dark:bg-slate-900 p-3 text-xs overflow-x-auto whitespace-pre-wrap break-words">
                    <code className="text-slate-700 dark:text-slate-300 font-mono">
                      {JSON.stringify(event.toolInput, null, 2)}
                    </code>
                  </pre>
                </div>
              </div>

              {/* Output */}
              {observeEvent && (
                <div className="mt-3">
                  <p className="text-2xs font-semibold text-slate-500 dark:text-slate-400 mb-2 uppercase tracking-wide">
                    {t('agent.messageBubble.output', 'Output')}
                  </p>
                  {(() => {
                    const formatted = formatToolOutput(observeEvent.toolOutput);
                    if (formatted.type === 'error') {
                      return (
                        <div className="rounded-lg p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/50">
                          <div className="flex items-start gap-2">
                            <XCircle size={14} className="text-red-500 mt-0.5 flex-shrink-0" />
                            <pre className="text-xs text-red-700 dark:text-red-300 overflow-x-auto whitespace-pre-wrap break-words font-mono">
                              <code>{formatted.content}</code>
                            </pre>
                          </div>
                        </div>
                      );
                    }
                    if (formatted.type === 'json') {
                      return (
                        <div className="rounded-lg overflow-hidden border border-slate-200 dark:border-slate-700">
                          <div className="bg-slate-50 dark:bg-slate-900/50 px-3 py-1.5 text-xs text-slate-500 border-b border-slate-200 dark:border-slate-700 flex items-center gap-2">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                            JSON
                          </div>
                          <pre className="bg-white dark:bg-slate-900 p-3 text-xs overflow-x-auto whitespace-pre-wrap break-words">
                            <code className="text-slate-700 dark:text-slate-300 font-mono">
                              {formatted.content}
                            </code>
                          </pre>
                        </div>
                      );
                    }
                    return (
                      <pre className="rounded-lg p-3 text-xs overflow-x-auto whitespace-pre-wrap break-words bg-slate-50 dark:bg-slate-900/50 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 font-mono">
                        <code>{formatted.content}</code>
                      </pre>
                    );
                  })()}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
});
ToolExecution.displayName = 'MessageBubble.ToolExecution';

// Work Plan Component - Modern timeline style
const WorkPlan: React.FC<WorkPlanProps> = memo(({ event }) => {
  const [expanded, setExpanded] = useState(true);
  const { t } = useTranslation();
  const steps = event.steps;

  if (!steps.length) return null;

  return (
    <div className="flex items-start gap-3 pb-2">
      <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
        <Bot size={16} className="text-primary" />
      </div>
      <div className={`flex-1 ${MESSAGE_MAX_WIDTH_CLASSES}`}>
        <div className="bg-slate-50/80 dark:bg-slate-800/50 border border-slate-200/45 dark:border-slate-700/45 rounded-md overflow-hidden">
          <button
            type="button"
            onClick={() => {
              setExpanded(!expanded);
            }}
            className="w-full px-4 py-3 flex items-center justify-between hover:bg-slate-100/50 dark:hover:bg-slate-700/30 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset"
          >
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm text-slate-800 dark:text-slate-200">
                {t('agent.messageBubble.workPlan', 'Work Plan')}
              </span>
              <span className="text-xs text-primary bg-primary/10 px-2 py-0.5 rounded-full">
                {t('agent.messageBubble.steps', '{{count}} steps', {
                  count: steps.length,
                })}
              </span>
            </div>
            {expanded ? (
              <ChevronUp size={16} className="text-slate-400" />
            ) : (
              <ChevronDown size={16} className="text-slate-400" />
            )}
          </button>
          {expanded && (
            <div className="px-4 pb-4">
              <div className="space-y-2 mt-2">
                {steps.map((step: { description?: string }, index: number) => (
                  <div
                    key={index}
                    className="flex items-start gap-3 p-3 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200/70 dark:border-slate-700/60"
                  >
                    <span className="w-6 h-6 rounded-full bg-primary text-xs font-semibold flex items-center justify-center text-slate-50 flex-shrink-0 shadow-sm">
                      {index + 1}
                    </span>
                    <span className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
                      {step.description || t('agent.messageBubble.noDescription', 'No description')}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
});
WorkPlan.displayName = 'MessageBubble.WorkPlan';

// Text End Component with action bar
const TextEnd: React.FC<TextEndProps> = memo(({ event, isPinned, onPin, onReply }) => {
  const [showSaveTemplate, setShowSaveTemplate] = useState(false);
  const fullText = 'fullText' in event ? (event.fullText as string) : '';
  const markdownContent = useMemo(() => linkifySandboxPaths(fullText), [fullText]);
  const { remarkPlugins, rehypePlugins } = useMarkdownPlugins(markdownContent);
  const executionSummary = normalizeExecutionSummary(event.metadata?.executionSummary);
  const completionArtifacts = getSafeArtifactReferences(
    event.artifacts ?? (event.metadata?.artifacts as ArtifactReference[] | undefined)
  );
  if ((!fullText || !fullText.trim()) && !executionSummary && completionArtifacts.length === 0) {
    return null;
  }

  return (
    <div className="group flex items-start gap-3 pb-2">
      <div className={ASSISTANT_AVATAR_CLASSES}>
        <Bot size={18} className="text-primary" />
      </div>
      <div className={`flex-1 ${MESSAGE_MAX_WIDTH_CLASSES}`}>
        {event.timestamp ? (
          <div className="mb-1 flex pl-1">
            <MessageTime timestamp={event.timestamp} />
          </div>
        ) : null}
        <div className="relative">
          <div className={ASSISTANT_BUBBLE_CLASSES}>
            <ExecutionSummaryPanel summary={executionSummary} />
            <div className={MARKDOWN_PROSE_CLASSES}>
              {fullText ? (
                <ReactMarkdown
                  remarkPlugins={remarkPlugins}
                  rehypePlugins={rehypePlugins}
                  components={ASSISTANT_COMPONENTS}
                >
                  {markdownContent}
                </ReactMarkdown>
              ) : null}
            </div>
            <ArtifactReferenceList artifacts={completionArtifacts} />
          </div>
          {/* Action bar - appears on hover at top-right */}
          {fullText ? (
            <div className="absolute -top-3 right-2 z-10">
              <MessageActionBar
                role="assistant"
                content={fullText}
                isPinned={isPinned}
                onPin={onPin}
                onReply={onReply}
                onSaveAsTemplate={() => {
                  setShowSaveTemplate(true);
                }}
              />
            </div>
          ) : null}
        </div>
        {showSaveTemplate && fullText ? (
          <SaveTemplateModal
            content={fullText}
            visible={showSaveTemplate}
            onClose={() => {
              setShowSaveTemplate(false);
            }}
            onSave={() => {
              setShowSaveTemplate(false);
            }}
          />
        ) : null}
      </div>
    </div>
  );
});
TextEnd.displayName = 'MessageBubble.TextEnd';

// Artifact Created Component - Modern card style
const ArtifactCreated: React.FC<ArtifactCreatedProps> = memo(({ event }) => {
  const [imageError, setImageError] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [refreshingUrl, setRefreshingUrl] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [currentUrl, setCurrentUrl] = useState<string | null>(null);
  const { t } = useTranslation();

  // Subscribe to sandbox store for live URL updates (artifact_ready event)
  const storeArtifact = useSandboxStore((state) => state.artifacts.get(event.artifactId));
  // Priority: refreshed URL > store URL > event URL
  const artifactUrl = currentUrl || storeArtifact?.url || event.url;
  const artifactPreviewUrl = currentUrl || storeArtifact?.previewUrl || event.previewUrl;
  const artifactError = storeArtifact?.errorMessage || event.error;
  const artifactStatus =
    storeArtifact?.status || (event.url ? 'ready' : artifactError ? 'error' : 'uploading');

  const canvasOpenTab = useCanvasStore((s) => s.openTab);
  const setLayoutMode = useLayoutModeStore((s) => s.setMode);

  const canOpenInCanvas =
    ['code', 'document', 'data', 'image', 'video', 'audio'].includes(event.category) ||
    event.mimeType.startsWith('image/') ||
    event.mimeType.startsWith('video/') ||
    event.mimeType.startsWith('audio/') ||
    isOfficeMimeType(event.mimeType.toLowerCase()) ||
    isOfficeExtension(event.filename);

  // Refresh expired URL
  const handleRefreshUrl = async () => {
    setRefreshingUrl(true);
    setRefreshError(null);
    try {
      const newUrl = await artifactService.refreshUrl(event.artifactId);
      setCurrentUrl(newUrl);
      setImageError(false);
      setImageLoaded(false);
    } catch (err) {
      setRefreshError(getErrorMessage(err));
    } finally {
      setRefreshingUrl(false);
    }
  };

  const handleOpenInCanvas = async () => {
    const url = artifactUrl || artifactPreviewUrl;
    if (!url) return;

    // Media and Office files: open directly with URL, no content fetch needed
    const mime = (event.mimeType || '').toLowerCase();
    if (
      mime.startsWith('image/') ||
      mime.startsWith('video/') ||
      mime.startsWith('audio/') ||
      isOfficeMimeType(mime) ||
      isOfficeExtension(event.filename)
    ) {
      canvasOpenTab({
        id: event.artifactId,
        title: event.filename,
        type: 'preview',
        content: url,
        mimeType: event.mimeType,
        artifactId: event.artifactId,
        artifactUrl: url,
      });
      setLayoutMode('canvas');
      return;
    }

    try {
      // Fetch content from the artifact URL
      const response = await fetchArtifactResource(url);
      if (!response.ok) {
        throw new Error(`Failed to fetch artifact content: ${String(response.status)}`);
      }
      const responseType = response.headers.get('content-type')?.toLowerCase() || '';
      if (responseType.includes('application/pdf')) {
        canvasOpenTab({
          id: event.artifactId,
          title: event.filename,
          type: 'preview',
          content: url,
          mimeType: 'application/pdf',
          pdfVerified: true,
          artifactId: event.artifactId,
          artifactUrl: url,
        });
        setLayoutMode('canvas');
        return;
      }
      const content = await response.text();

      // Check if this is HTML content - should use preview mode with iframe
      const isHtmlFile =
        event.filename.toLowerCase().endsWith('.html') || event.mimeType === 'text/html';

      if (isHtmlFile) {
        // HTML files should be rendered in preview mode using iframe
        canvasOpenTab({
          id: event.artifactId,
          title: event.filename,
          type: 'preview',
          content,
          artifactId: event.artifactId,
          artifactUrl: url,
        });
      } else {
        const contentType = getCanvasTypeForSandboxFile(event.filename, responseType || mime);
        const ext = event.filename.split('.').pop()?.toLowerCase();

        canvasOpenTab({
          id: event.artifactId,
          title: event.filename,
          type: contentType,
          content,
          language: ext,
          artifactId: event.artifactId,
          artifactUrl: url,
        });
      }
      setLayoutMode('canvas');
      requestCanvasViewMode();
    } catch {
      // Silently fail - user can still download the file directly
    }
  };

  const getCategoryIcon = (
    category: string
  ): React.ComponentType<{ size?: number; className?: string }> => {
    switch (category) {
      case 'image':
        return ImageIcon;
      case 'video':
        return Film;
      case 'audio':
        return Music;
      case 'document':
        return FileText;
      case 'code':
        return FileCode;
      case 'data':
        return Table;
      case 'archive':
        return Archive;
      default:
        return Paperclip;
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${String(bytes)} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const isImage = event.category === 'image';
  const url = artifactUrl || artifactPreviewUrl;

  return (
    <div className="flex items-start gap-3 pb-2">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-emerald-200 bg-emerald-50 dark:border-emerald-800/55 dark:bg-emerald-950/35">
        <FileOutput size={16} className="text-emerald-600 dark:text-emerald-400" />
      </div>
      <div className={`flex-1 min-w-0 ${WIDE_MESSAGE_MAX_WIDTH_CLASSES}`}>
        <div className="rounded-md bg-white p-4 shadow-[0_0_0_1px_rgba(15,23,42,0.055),0_6px_16px_-16px_rgba(15,23,42,0.22)] dark:bg-slate-950 dark:shadow-[0_0_0_1px_rgba(148,163,184,0.12)]">
          {/* Header */}
          <div className="mb-3 flex min-w-0 items-center gap-2">
            {(() => {
              const CatIcon = getCategoryIcon(event.category);
              return <CatIcon size={17} className="text-emerald-600 dark:text-emerald-400" />;
            })()}
            <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {t('agent.messageBubble.fileGenerated', 'File Generated')}
            </span>
            {event.sourceTool && (
              <span className="max-w-[180px] truncate rounded-full bg-emerald-50 px-2 py-0.5 text-2xs font-medium text-emerald-700 ring-1 ring-emerald-100 dark:bg-emerald-950/45 dark:text-emerald-300 dark:ring-emerald-800/60">
                {event.sourceTool}
              </span>
            )}
          </div>

          {/* Image Preview */}
          {isImage && url && !imageError && (
            <div className="relative mb-3 overflow-hidden rounded-md border border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-900">
              {!imageLoaded && (
                <div className="absolute inset-0 flex items-center justify-center bg-slate-100 dark:bg-slate-800 min-h-[150px]">
                  <Loader2 className="w-6 h-6 animate-spin motion-reduce:animate-none text-slate-400" />
                </div>
              )}
              <img
                src={url}
                alt={event.filename}
                className={`max-w-full max-h-[300px] object-contain ${
                  imageLoaded ? 'opacity-100' : 'opacity-0'
                } transition-opacity duration-300`}
                onLoad={() => {
                  setImageLoaded(true);
                }}
                onError={() => {
                  setImageError(true);
                }}
              />
            </div>
          )}

          {/* Image Load Error with Refresh Option */}
          {isImage && imageError && (
            <div className="mb-3 p-4 rounded-lg border border-red-200/50 dark:border-red-800/30 bg-red-50/50 dark:bg-red-900/20">
              <div className="flex items-center gap-2 text-red-600 dark:text-red-400 mb-2">
                <XCircle size={16} />
                <span className="text-sm font-medium">
                  {t('agent.messageBubble.imageLoadFailed', 'Failed to load image')}
                </span>
              </div>
              {refreshError && (
                <p className="text-xs text-red-500 dark:text-red-400 mb-2">{refreshError}</p>
              )}
              <button
                type="button"
                onClick={() => {
                  void handleRefreshUrl();
                }}
                disabled={refreshingUrl}
                className="touch-target flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-red-100 dark:bg-red-800/50 text-red-700 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-700/50 transition-colors duration-150 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
              >
                <RefreshCw
                  size={12}
                  className={refreshingUrl ? 'animate-spin motion-reduce:animate-none' : ''}
                />
                {refreshingUrl
                  ? t('agent.messageBubble.refreshing', 'Refreshing...')
                  : t('agent.messageBubble.refreshLink', 'Refresh Link')}
              </button>
            </div>
          )}

          {/* File Info */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-slate-200/55 bg-slate-50/80 px-3 py-2.5 text-sm dark:border-slate-800/60 dark:bg-slate-900/60">
            <div className="flex min-w-[220px] flex-1 items-center gap-2">
              <File size={16} className="shrink-0 text-emerald-600 dark:text-emerald-400" />
              <span className="min-w-0 truncate font-medium text-slate-800 dark:text-slate-200">
                {event.filename}
              </span>
            </div>
            <span className="whitespace-nowrap text-xs text-slate-500 dark:text-slate-400">
              {formatSize(event.sizeBytes)}
            </span>
            {url && (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="touch-target inline-flex items-center gap-1 rounded text-xs font-medium text-emerald-700 transition-colors duration-150 hover:text-emerald-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 dark:text-emerald-300 dark:hover:text-emerald-200"
                download={event.filename}
              >
                <Download size={16} />
                {t('agent.messageBubble.download', 'Download')}
              </a>
            )}
            {canOpenInCanvas && (
              <button
                type="button"
                onClick={() => {
                  void handleOpenInCanvas();
                }}
                className="touch-target inline-flex items-center gap-1 rounded text-xs font-medium text-primary transition-colors duration-150 hover:text-primary/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
              >
                <PanelRight size={14} />
                {t('agent.messageBubble.openInCanvas', 'Canvas')}
              </button>
            )}
            {!url && artifactStatus === 'uploading' && (
              <span className="flex items-center gap-1 text-xs text-slate-400 dark:text-slate-500">
                <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />
                {t('agent.messageBubble.uploading', 'Uploading...')}
              </span>
            )}
            {!url && artifactStatus === 'error' && (
              <span className="flex items-center gap-1 text-xs text-red-500 dark:text-red-400">
                <XCircle size={14} />
                {artifactError || t('agent.messageBubble.uploadFailed', 'Upload failed')}
              </span>
            )}
            {/* Refresh button for expired/failed URLs */}
            {((isImage && imageError) || (!url && artifactStatus === 'error')) && (
              <button
                type="button"
                onClick={() => {
                  void handleRefreshUrl();
                }}
                disabled={refreshingUrl}
                className="touch-target flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400 hover:text-amber-700 dark:hover:text-amber-300 transition-colors duration-150 font-medium disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 rounded"
              >
                <RefreshCw
                  size={14}
                  className={refreshingUrl ? 'animate-spin motion-reduce:animate-none' : ''}
                />
                {refreshingUrl
                  ? t('agent.messageBubble.refreshing', 'Refreshing...')
                  : t('agent.messageBubble.refreshLink', 'Refresh')}
              </button>
            )}
            {refreshError && !imageError && (
              <span className="text-xs text-red-500 dark:text-red-400">{refreshError}</span>
            )}
          </div>

          {/* Additional metadata */}
          <div className="mt-2.5 flex flex-wrap items-center gap-2 text-2xs">
            <span className="rounded border border-slate-200 bg-slate-50 px-2 py-1 text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
              {event.mimeType}
            </span>
            <span className="rounded border border-slate-200 bg-slate-50 px-2 py-1 capitalize text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
              {event.category}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
});
ArtifactCreated.displayName = 'MessageBubble.ArtifactCreated';

// ========================================
// Root Component
// ========================================

// Safe content getter
const getContent = (event: TimelineEvent): string => {
  if ('content' in event && typeof event.content === 'string') return event.content;
  if ('thought' in event && typeof event.thought === 'string') return event.thought;
  return '';
};

const MessageBubbleRoot: React.FC<MessageBubbleRootProps> = memo(
  ({ event, isStreaming, allEvents, isPinned, onPin, onReply }) => {
    switch (event.type) {
      case 'user_message': {
        const rawContent = getContent(event);
        // Check for System Instruction prefix for SubAgent delegation
        // Format: [System Instruction: Delegate this task strictly to SubAgent "NAME"]\nCONTENT
        const systemInstructionMatch = rawContent.match(
          /^\[System Instruction: Delegate this task strictly to SubAgent "([^"]+)"\]\n/
        );

        let content = rawContent;
        let forcedSubAgentName: string | undefined;

        if (systemInstructionMatch) {
          forcedSubAgentName = systemInstructionMatch[1];
          content = rawContent.slice(systemInstructionMatch[0].length);
        }

        return (
          <UserMessage
            content={content}
            timestamp={event.timestamp}
            onReply={onReply}
            forcedSkillName={event.metadata?.forcedSkillName as string | undefined}
            forcedSubAgentName={forcedSubAgentName}
            fileMetadata={
              event.metadata?.fileMetadata as
                | Array<{
                    filename: string;
                    sandbox_path?: string | undefined;
                    mime_type: string;
                    size_bytes: number;
                  }>
                | undefined
            }
          />
        );
      }

      case 'assistant_message':
        return (
          <AssistantMessage
            content={getContent(event)}
            timestamp={event.timestamp}
            metadata={event.metadata}
            artifacts={event.artifacts}
            isStreaming={isStreaming}
            isPinned={isPinned}
            onPin={onPin}
            onReply={onReply}
          />
        );

      case 'text_delta':
        // Skip text_delta when a text_end exists (it contains the full text)
        if (allEvents?.some((e) => e.type === 'text_end')) {
          return null;
        }
        return <TextDelta content={getContent(event)} timestamp={event.timestamp} />;

      case 'thought':
        return <Thought content={getContent(event)} timestamp={event.timestamp} />;

      case 'act': {
        const observeEvent = allEvents ? findMatchingObserve(event, allEvents) : undefined;
        return <ToolExecution event={event} observeEvent={observeEvent} />;
      }

      case 'observe':
        // Observe events are rendered as part of act
        return null;

      case 'work_plan':
        return <WorkPlan event={event} />;

      case 'text_end':
        return <TextEnd event={event} isPinned={isPinned} onPin={onPin} onReply={onReply} />;

      case 'text_start':
        // Control event, no visual output needed
        return null;

      case 'artifact_created':
        return (
          <ArtifactCreated
            event={
              event as unknown as ArtifactCreatedEvent & {
                error?: string | undefined;
              }
            }
          />
        );

      // HITL Events - Render inline cards
      case 'clarification_asked': {
        const clarificationData = toClarificationData(event);
        const e = event as TimelineEvent & {
          requestId?: string | undefined;
          expiresAt?: string | undefined;
          createdAt?: string | undefined;
          answered?: boolean | undefined;
          answer?: string | undefined;
        };
        return (
          <InlineHITLCard
            hitlType="clarification"
            requestId={e.requestId || clarificationData?.request_id || ''}
            clarificationData={clarificationData}
            isAnswered={e.answered === true}
            answeredValue={e.answer}
            expiresAt={e.expiresAt}
            createdAt={e.createdAt || String(event.timestamp)}
          />
        );
      }

      case 'clarification_answered': {
        const e = event as TimelineEvent & {
          requestId?: string | undefined;
          answer?: string | undefined;
          createdAt?: string | undefined;
        };
        return (
          <InlineHITLCard
            hitlType="clarification"
            requestId={e.requestId || ''}
            isAnswered={true}
            answeredValue={e.answer}
            createdAt={e.createdAt || String(event.timestamp)}
          />
        );
      }

      case 'decision_asked': {
        const decisionData = toDecisionData(event);
        const e = event as TimelineEvent & {
          requestId?: string | undefined;
          expiresAt?: string | undefined;
          createdAt?: string | undefined;
          answered?: boolean | undefined;
          decision?: string | string[] | undefined;
        };
        return (
          <InlineHITLCard
            hitlType="decision"
            requestId={e.requestId || decisionData?.request_id || ''}
            decisionData={decisionData}
            isAnswered={e.answered === true}
            answeredValue={Array.isArray(e.decision) ? e.decision.join(', ') : e.decision}
            expiresAt={e.expiresAt}
            createdAt={e.createdAt || String(event.timestamp)}
          />
        );
      }

      case 'decision_answered': {
        const e = event as TimelineEvent & {
          requestId?: string | undefined;
          decision?: string | string[] | undefined;
          createdAt?: string | undefined;
        };
        return (
          <InlineHITLCard
            hitlType="decision"
            requestId={e.requestId || ''}
            isAnswered={true}
            answeredValue={Array.isArray(e.decision) ? e.decision.join(', ') : e.decision}
            createdAt={e.createdAt || String(event.timestamp)}
          />
        );
      }

      case 'env_var_requested': {
        const envVarData = toEnvVarData(event);
        const e = event as TimelineEvent & {
          requestId?: string | undefined;
          expiresAt?: string | undefined;
          createdAt?: string | undefined;
          answered?: boolean | undefined;
          values?: Record<string, string> | undefined;
          providedVariables?: string[] | undefined;
        };
        const answeredVal = e.values
          ? Object.keys(e.values).join(', ')
          : e.providedVariables
            ? e.providedVariables.join(', ')
            : undefined;
        return (
          <InlineHITLCard
            hitlType="env_var"
            requestId={e.requestId || envVarData?.request_id || ''}
            envVarData={envVarData}
            isAnswered={e.answered === true}
            answeredValue={answeredVal}
            expiresAt={e.expiresAt}
            createdAt={e.createdAt || String(event.timestamp)}
          />
        );
      }

      case 'env_var_provided': {
        const e = event as TimelineEvent & {
          requestId?: string | undefined;
          variableNames?: string[] | undefined;
          createdAt?: string | undefined;
        };
        return (
          <InlineHITLCard
            hitlType="env_var"
            requestId={e.requestId || ''}
            isAnswered={true}
            answeredValue={e.variableNames?.join(', ')}
            createdAt={e.createdAt || String(event.timestamp)}
          />
        );
      }

      case 'permission_asked': {
        const permissionData = toPermissionData(event);
        const e = event as TimelineEvent & {
          requestId?: string | undefined;
          expiresAt?: string | undefined;
          createdAt?: string | undefined;
          answered?: boolean | undefined;
          granted?: boolean | undefined;
        };
        return (
          <InlineHITLCard
            hitlType="permission"
            requestId={e.requestId || permissionData?.request_id || ''}
            permissionData={permissionData}
            isAnswered={e.answered === true}
            answeredValue={e.granted !== undefined ? (e.granted ? 'Granted' : 'Denied') : undefined}
            expiresAt={e.expiresAt}
            createdAt={e.createdAt || String(event.timestamp)}
          />
        );
      }

      case 'permission_replied': {
        const e = event as TimelineEvent & {
          requestId?: string | undefined;
          granted?: boolean | undefined;
          createdAt?: string | undefined;
        };
        return (
          <InlineHITLCard
            hitlType="permission"
            requestId={e.requestId || ''}
            isAnswered={true}
            answeredValue={e.granted ? 'Granted' : 'Denied'}
            createdAt={e.createdAt || String(event.timestamp)}
          />
        );
      }

      case 'permission_requested': {
        const permissionData = toPermissionData(event);
        const e = event as TimelineEvent & {
          requestId?: string | undefined;
          expiresAt?: string | undefined;
          createdAt?: string | undefined;
          answered?: boolean | undefined;
          granted?: boolean | undefined;
        };
        return (
          <InlineHITLCard
            hitlType="permission"
            requestId={e.requestId || permissionData?.request_id || ''}
            permissionData={permissionData}
            isAnswered={e.answered === true}
            answeredValue={e.granted !== undefined ? (e.granted ? 'Granted' : 'Denied') : undefined}
            expiresAt={e.expiresAt}
            createdAt={e.createdAt || String(event.timestamp)}
          />
        );
      }

      case 'permission_granted': {
        const e = event as TimelineEvent & {
          requestId?: string | undefined;
          granted?: boolean | undefined;
          createdAt?: string | undefined;
        };
        return (
          <InlineHITLCard
            hitlType="permission"
            requestId={e.requestId || ''}
            isAnswered={true}
            answeredValue={e.granted ? 'Granted' : 'Denied'}
            createdAt={e.createdAt || String(event.timestamp)}
          />
        );
      }

      case 'artifact_ready':
      case 'artifact_error':
      case 'artifacts_batch':
        // artifact_ready/artifact_error update existing artifact_created entries via store
        return null;

      case 'task_start':
      case 'task_complete':
        // Rendered in timeline view only, not in chat bubble view
        return null;

      case 'agent_spawned':
      case 'agent_completed':
      case 'agent_stopped':
      case 'agent_message_sent':
      case 'agent_message_received':
        // L4 agent lifecycle events are handled by agentNodes store, not rendered as bubbles
        return null;

      default:
        console.warn('Unknown event type in MessageBubble:', event.type);
        return null;
    }
  },
  // Custom comparator: skip re-render if only allEvents reference changed
  // (allEvents changes on every timeline update, but most bubbles don't use it)
  (prev, next) =>
    prev.event === next.event &&
    prev.isStreaming === next.isStreaming &&
    prev.isPinned === next.isPinned &&
    prev.onPin === next.onPin &&
    prev.onReply === next.onReply &&
    prev.allEvents?.length === next.allEvents?.length
);

MessageBubbleRoot.displayName = 'MessageBubble';

// ========================================
// Compound Component Export
// ========================================

export const MessageBubble = MessageBubbleRoot as MessageBubbleCompound;

MessageBubble.User = UserMessage;
MessageBubble.Assistant = AssistantMessage;
MessageBubble.TextDelta = TextDelta;
MessageBubble.Thought = Thought;
MessageBubble.ToolExecution = ToolExecution;
MessageBubble.WorkPlan = WorkPlan;
MessageBubble.TextEnd = TextEnd;
MessageBubble.ArtifactCreated = ArtifactCreated;
MessageBubble.Root = MessageBubbleRoot;

export type {
  ArtifactCreatedProps,
  AssistantMessageProps,
  MessageBubbleCompound,
  MessageBubbleProps,
  MessageBubbleRootProps,
  TextDeltaProps,
  TextEndProps,
  ThoughtProps,
  ToolExecutionProps,
  UserMessageProps,
  WorkPlanProps,
} from './types';
