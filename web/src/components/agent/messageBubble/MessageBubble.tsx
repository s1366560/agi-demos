/**
 * MessageBubble - Modern message bubble component
 *
 * Compound Component Pattern for flexible message rendering.
 * Features modern glass-morphism design, smooth animations, and improved UX.
 */

import React, { memo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';

import {
  User,
  Sparkles,
  Wrench,
  CheckCircle2,
  XCircle,
  Loader2,
  ChevronDown,
  ChevronUp,
  Clock,
  Bot,
  Lightbulb,
  FileOutput,
  PanelRight,
  RefreshCw,
} from 'lucide-react';

import { useCanvasStore } from '@/stores/canvasStore';
import { useLayoutModeStore } from '@/stores/layoutMode';
import { useSandboxStore } from '@/stores/sandbox';

import { artifactService } from '@/services/artifactService';

import { CodeBlock as SharedCodeBlock } from '../chat/CodeBlock';
import { useMarkdownPlugins, safeMarkdownComponents } from '../chat/markdownPlugins';
import { MessageActionBar } from '../chat/MessageActionBar';
import { SaveTemplateModal } from '../chat/SaveTemplateModal';
import { InlineHITLCard } from '../InlineHITLCard';
import { MARKDOWN_PROSE_CLASSES } from '../styles';

import { getErrorMessage } from '@/types/common';

import type {
  UserMessageProps,
  AssistantMessageProps,
  TextDeltaProps,
  ThoughtProps,
  ToolExecutionProps,
  WorkPlanProps,
  TextEndProps,
  ArtifactCreatedProps,
  MessageBubbleRootProps,
  MessageBubbleCompound,
} from './types';
import type {
  TimelineEvent,
  ActEvent,
  ObserveEvent,
  ArtifactCreatedEvent,
  ClarificationAskedEventData,
  DecisionAskedEventData,
  EnvVarRequestedEventData,
  PermissionAskedEventData,
  PermissionAskedTimelineEvent,
  PermissionRequestedTimelineEvent,
} from '../../../types/agent';

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
const formatToolOutput = (output: unknown): { type: 'text' | 'json' | 'error'; content: string } => {
  if (!output) return { type: 'text', content: 'No output' };

  if (typeof output === 'string') {
    if (output.toLowerCase().includes('error:') || output.toLowerCase().includes('failed')) {
      return { type: 'error', content: output };
    }
    return { type: 'text', content: output };
  }

  if (typeof output === 'object') {
    if ('error' in output || 'errorMessage' in output || 'error_message' in output) {
      const errorContent = ('errorMessage' in output ? output.errorMessage : 'error_message' in output ? output.error_message : 'error' in output ? output.error : undefined) as string | undefined;
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

function getFileIconForMime(mimeType: string): string {
  if (mimeType.startsWith('image/')) return 'image';
  if (mimeType.startsWith('video/')) return 'movie';
  if (mimeType.startsWith('audio/')) return 'audio_file';
  if (mimeType === 'application/pdf') return 'picture_as_pdf';
  if (mimeType.includes('spreadsheet') || mimeType.includes('excel')) return 'table_chart';
  if (mimeType.includes('presentation') || mimeType.includes('powerpoint')) return 'slideshow';
  if (mimeType.includes('zip') || mimeType.includes('tar') || mimeType.includes('compress'))
    return 'folder_zip';
  if (
    mimeType.startsWith('text/') ||
    mimeType.includes('json') ||
    mimeType.includes('xml') ||
    mimeType.includes('javascript') ||
    mimeType.includes('typescript')
  )
    return 'code';
  return 'description';
}

// User Message Component - Modern floating style with action bar
const UserMessage: React.FC<UserMessageProps> = memo(
  ({ content, onReply, forcedSkillName, forcedSubAgentName, fileMetadata }) => {
    if (!content) return null;
    const hasFiles = fileMetadata && fileMetadata.length > 0;

    // Determine bubble style based on forced type
    const isSkill = !!forcedSkillName;
    const isSubAgent = !!forcedSubAgentName;
    const isForced = isSkill || isSubAgent;

    let gradientClass = '';
    if (isSubAgent) {
      gradientClass = 'bg-gradient-to-r from-purple-400 via-purple-500/80 to-purple-400';
    } else if (isSkill) {
      gradientClass = 'bg-gradient-to-r from-indigo-400 via-primary/80 to-indigo-400';
    }

    return (
      <div className="group flex flex-col items-end gap-1 mb-2 animate-fade-in-up">
        {/* Main row: bubble + avatar */}
        <div className="flex items-end justify-end gap-3 w-full">
          <div className="max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
            <div
              className={
                isForced ? `relative ${gradientClass} rounded-xl rounded-br-sm p-px` : 'relative'
              }
            >
              {!isForced && (
                <div className="absolute inset-0 bg-gradient-to-br from-primary/20 to-primary/5 rounded-xl rounded-br-sm blur-sm -z-10" />
              )}

              {/* Badge Icon for Forced Execution */}
              {isForced && (
                <div
                  className={`absolute left-0 top-1/2 -translate-x-1/2 -translate-y-1/2 w-4 h-4 rounded-full flex items-center justify-center ring-2 ring-white dark:ring-slate-800 z-10 ${isSubAgent ? 'bg-gradient-to-br from-purple-400 to-purple-600' : 'bg-gradient-to-br from-indigo-400 to-primary/90'}`}
                >
                  {isSubAgent ? (
                    <svg
                      className="w-[9px] h-[9px] text-white"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="3"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
                      <line x1="8" y1="21" x2="16" y2="21" />
                      <line x1="12" y1="17" x2="12" y2="21" />
                    </svg>
                  ) : (
                    <svg
                      className="w-[9px] h-[9px] text-white"
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
                    ? 'bg-white dark:bg-slate-800 rounded-xl rounded-br-sm px-4 py-2.5'
                    : 'bg-white dark:bg-slate-800 border border-slate-200/60 dark:border-slate-700/60 rounded-xl rounded-br-sm px-4 py-2.5 shadow-sm hover:shadow-md transition-shadow duration-200'
                }
              >
                <p className="text-[15px] leading-relaxed whitespace-pre-wrap break-words text-slate-800 dark:text-slate-100 font-normal">
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
                  className={`absolute bottom-0 right-4 translate-y-1/2 px-1.5 bg-white dark:bg-slate-800 text-[10px] font-medium leading-none tracking-wide ${isSubAgent ? 'text-purple-600 dark:text-purple-400' : 'text-primary/70'}`}
                >
                  {isSubAgent ? `@${forcedSubAgentName}` : forcedSkillName}
                </div>
              )}
            </div>
          </div>
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-slate-100 to-slate-200 dark:from-slate-700 dark:to-slate-800 flex items-center justify-center flex-shrink-0 shadow-sm">
            <User size={16} className="text-slate-500 dark:text-slate-400" />
          </div>
        </div>
        {/* Attachment row: below bubble, aligned under bubble (offset by avatar width) */}
        {hasFiles && (
          <div className={`flex flex-col items-end gap-1 mr-11 ${isForced ? 'mt-2' : 'mt-0.5'}`}>
            {fileMetadata.map((file, idx) => (
              <div
                key={idx}
                className="inline-flex items-center gap-2 px-3 py-1.5 bg-slate-100 dark:bg-slate-800 border border-slate-200/60 dark:border-slate-700/60 rounded-lg"
              >
                <span className="material-symbols-outlined text-[16px] text-slate-500 dark:text-slate-400">
                  {getFileIconForMime(file.mime_type)}
                </span>
                <span className="text-xs text-slate-700 dark:text-slate-300 truncate max-w-[200px]">
                  {file.filename}
                </span>
                <span className="text-[10px] text-slate-400 dark:text-slate-500 whitespace-nowrap">
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
};

// Assistant Message Component - Modern card style with action bar
const AssistantMessage: React.FC<AssistantMessageProps> = memo(
  ({ content, isStreaming, isPinned, onPin, onReply }) => {
    const [showSaveTemplate, setShowSaveTemplate] = useState(false);
    const { remarkPlugins, rehypePlugins } = useMarkdownPlugins(content);
    if (!content && !isStreaming) return null;
    return (
      <div className="group flex items-start gap-3 mb-2 animate-fade-in-up">
        <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-primary to-primary-600 flex items-center justify-center flex-shrink-0 shadow-sm shadow-primary/20">
          <Bot size={18} className="text-white" />
        </div>
        <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
          <div className="relative">
            <div className="bg-white dark:bg-slate-800/90 border border-slate-200/80 dark:border-slate-700/50 rounded-xl rounded-tl-sm px-4 py-2.5 shadow-sm hover:shadow-md transition-all duration-200">
              <div className={MARKDOWN_PROSE_CLASSES}>
                {content ? (
                  <ReactMarkdown
                    remarkPlugins={remarkPlugins}
                    rehypePlugins={rehypePlugins}
                    components={ASSISTANT_COMPONENTS}
                  >
                    {content}
                  </ReactMarkdown>
                ) : null}
              </div>
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
                  onSaveAsTemplate={() => { setShowSaveTemplate(true); }}
                />
              </div>
            )}
          </div>
        </div>
        {showSaveTemplate && (
          <SaveTemplateModal
            content={content || ''}
            visible={showSaveTemplate}
            onClose={() => { setShowSaveTemplate(false); }}
            onSave={() => { setShowSaveTemplate(false); }}
          />
        )}
      </div>
    );
  }
);
AssistantMessage.displayName = 'MessageBubble.Assistant';

// Text Delta Component (for streaming content)
const TextDelta: React.FC<TextDeltaProps> = memo(({ content }) => {
  const { remarkPlugins, rehypePlugins } = useMarkdownPlugins(content);
  if (!content) return null;
  return (
    <div className="flex items-start gap-3 mb-2 animate-fade-in-up">
      <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-primary to-primary-600 flex items-center justify-center flex-shrink-0 shadow-sm shadow-primary/20">
        <Bot size={18} className="text-white" />
      </div>
      <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
        <div className="bg-white dark:bg-slate-800/90 border border-slate-200/80 dark:border-slate-700/50 rounded-xl rounded-tl-sm px-4 py-2.5 shadow-sm">
          <div className={MARKDOWN_PROSE_CLASSES}>
            <ReactMarkdown
              remarkPlugins={remarkPlugins}
              rehypePlugins={rehypePlugins}
              components={safeMarkdownComponents}
            >
              {content}
            </ReactMarkdown>
          </div>
        </div>
      </div>
    </div>
  );
});
TextDelta.displayName = 'MessageBubble.TextDelta';

// Thought/Reasoning Component - Modern pill style
const Thought: React.FC<ThoughtProps> = memo(({ content }) => {
  const [expanded, setExpanded] = useState(true);
  const { t } = useTranslation();

  if (!content) return null;

  return (
    <div className="flex items-start gap-3 mb-2 animate-fade-in-up">
      <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
        <Lightbulb size={16} className="text-slate-500 dark:text-slate-400" />
      </div>
      <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
        <div className="bg-slate-50/80 dark:bg-slate-800/50 border border-slate-200/60 dark:border-slate-700/40 rounded-xl overflow-hidden">
          <button
            onClick={() => { setExpanded(!expanded); }}
            className="w-full px-4 py-2.5 flex items-center gap-2 hover:bg-slate-100/50 dark:hover:bg-slate-700/30 transition-colors"
          >
            <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              {t('agent.messageBubble.reasoning', 'Reasoning')}
            </span>
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
  const duration =
    observeEvent ? (observeEvent.timestamp || 0) - (event.timestamp || 0) : null;

  const statusIcon = observeEvent ? (
    hasError ? (
      <XCircle size={16} className="text-red-500" />
    ) : (
      <CheckCircle2 size={16} className="text-emerald-500" />
    )
  ) : (
    <Loader2 size={16} className="text-blue-500 animate-spin" />
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
    <div className="flex items-start gap-3 mb-2 animate-fade-in-up">
      <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
        <Wrench size={16} className="text-slate-500 dark:text-slate-400" />
      </div>
      <div className="flex-1 min-w-0 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
        <div className="bg-white dark:bg-slate-800 border border-slate-200/80 dark:border-slate-700/50 rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-shadow duration-200">
          {/* Header */}
          <button
            onClick={() => { setExpanded(!expanded); }}
            className="w-full px-4 py-3 flex items-center justify-between hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors"
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
            <div className="px-4 pb-4 border-t border-slate-100 dark:border-slate-700/50">
              {/* Input */}
              <div className="mt-3">
                <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 mb-2 uppercase tracking-wide">
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
                  <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 mb-2 uppercase tracking-wide">
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
    <div className="flex items-start gap-3 mb-4 animate-fade-in-up">
      <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
        <Sparkles size={16} className="text-primary" />
      </div>
      <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
        <div className="bg-slate-50/80 dark:bg-slate-800/50 border border-slate-200/60 dark:border-slate-700/40 rounded-xl overflow-hidden">
          <button
            onClick={() => { setExpanded(!expanded); }}
            className="w-full px-4 py-3 flex items-center justify-between hover:bg-slate-100/50 dark:hover:bg-slate-700/30 transition-colors"
          >
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm text-slate-800 dark:text-slate-200">
                {t('agent.messageBubble.workPlan', 'Work Plan')}
              </span>
              <span className="text-xs text-primary bg-primary/10 px-2 py-0.5 rounded-full">
                {t('agent.messageBubble.steps', '{{count}} steps', { count: steps.length })}
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
                    className="flex items-start gap-3 p-3 bg-white/60 dark:bg-slate-800/40 rounded-lg border border-slate-200/50 dark:border-slate-700/30"
                  >
                    <span className="w-6 h-6 rounded-full bg-primary text-xs font-semibold flex items-center justify-center text-white flex-shrink-0 shadow-sm">
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
  const { remarkPlugins, rehypePlugins } = useMarkdownPlugins(fullText);
  if (!fullText || !fullText.trim()) return null;

  return (
    <div className="group flex items-start gap-3 mb-6 animate-fade-in-up">
      <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-primary to-primary-600 flex items-center justify-center flex-shrink-0 shadow-sm shadow-primary/20">
        <Bot size={18} className="text-white" />
      </div>
      <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
        <div className="relative">
          <div className="bg-white dark:bg-slate-800/90 border border-slate-200/80 dark:border-slate-700/50 rounded-xl rounded-tl-sm px-5 py-4 shadow-sm">
            <div className={MARKDOWN_PROSE_CLASSES}>
              <ReactMarkdown
                remarkPlugins={remarkPlugins}
                rehypePlugins={rehypePlugins}
                components={safeMarkdownComponents}
              >
                {fullText}
              </ReactMarkdown>
            </div>
          </div>
          {/* Action bar - appears on hover at top-right */}
          <div className="absolute -top-3 right-2 z-10">
            <MessageActionBar
              role="assistant"
              content={fullText}
              isPinned={isPinned}
              onPin={onPin}
              onReply={onReply}
              onSaveAsTemplate={() => { setShowSaveTemplate(true); }}
            />
          </div>
        </div>
        {showSaveTemplate && (
          <SaveTemplateModal
            content={fullText}
            visible={showSaveTemplate}
            onClose={() => { setShowSaveTemplate(false); }}
            onSave={() => { setShowSaveTemplate(false); }}
          />
        )}
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

  const canOpenInCanvas = ['code', 'document', 'data'].includes(event.category);

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

    try {
      // Fetch content from the artifact URL
      const response = await fetch(url);
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
        // Determine canvas content type from artifact category
        const typeMap: Record<string, 'code' | 'markdown' | 'data'> = {
          code: 'code',
          document: 'markdown',
          data: 'data',
        };
        const contentType = typeMap[event.category] || 'code';
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
    } catch {
      // Silently fail - user can still download the file directly
    }
  };

  const getCategoryIcon = (category: string) => {
    switch (category) {
      case 'image':
        return 'image';
      case 'video':
        return 'movie';
      case 'audio':
        return 'audio_file';
      case 'document':
        return 'description';
      case 'code':
        return 'code';
      case 'data':
        return 'table_chart';
      case 'archive':
        return 'folder_zip';
      default:
        return 'attach_file';
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
    <div className="flex items-start gap-3 mb-4 animate-fade-in-up">
      <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-100 to-teal-100 dark:from-emerald-900/40 dark:to-teal-900/30 flex items-center justify-center shrink-0">
        <FileOutput size={16} className="text-emerald-600 dark:text-emerald-400" />
      </div>
      <div className="flex-1 min-w-0 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
        <div className="bg-gradient-to-r from-emerald-50/90 to-teal-50/70 dark:from-emerald-900/25 dark:to-teal-900/15 rounded-xl p-4 border border-emerald-200/50 dark:border-emerald-800/30 shadow-sm">
          {/* Header */}
          <div className="flex items-center gap-2 mb-3">
            <span className="material-symbols-outlined text-emerald-600 dark:text-emerald-400 text-lg">
              {getCategoryIcon(event.category)}
            </span>
            <span className="text-sm font-semibold text-emerald-800 dark:text-emerald-300">
              {t('agent.messageBubble.fileGenerated', 'File Generated')}
            </span>
            {event.sourceTool && (
              <span className="text-xs px-2 py-0.5 bg-emerald-100 dark:bg-emerald-800/50 text-emerald-600 dark:text-emerald-400 rounded-full">
                {event.sourceTool}
              </span>
            )}
          </div>

          {/* Image Preview */}
          {isImage && url && !imageError && (
            <div className="mb-3 relative rounded-lg overflow-hidden border border-emerald-200/50 dark:border-emerald-800/30">
              {!imageLoaded && (
                <div className="absolute inset-0 flex items-center justify-center bg-slate-100 dark:bg-slate-800 min-h-[150px]">
                  <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
                </div>
              )}
              <img
                src={url}
                alt={event.filename}
                className={`max-w-full max-h-[300px] object-contain ${
                  imageLoaded ? 'opacity-100' : 'opacity-0'
                } transition-opacity duration-300`}
                onLoad={() => { setImageLoaded(true); }}
                onError={() => { setImageError(true); }}
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
                onClick={() => { void handleRefreshUrl(); }}
                disabled={refreshingUrl}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-red-100 dark:bg-red-800/50 text-red-700 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-700/50 transition-colors disabled:opacity-50"
              >
                <RefreshCw size={12} className={refreshingUrl ? 'animate-spin' : ''} />
                {refreshingUrl
                  ? t('agent.messageBubble.refreshing', 'Refreshing...')
                  : t('agent.messageBubble.refreshLink', 'Refresh Link')}
              </button>
            </div>
          )}

          {/* File Info */}
          <div className="flex items-center gap-3 text-sm bg-white/60 dark:bg-slate-800/40 rounded-lg p-3 border border-emerald-100 dark:border-emerald-800/20">
            <div className="flex items-center gap-2 flex-1 min-w-0">
              <span className="material-symbols-outlined text-emerald-500 dark:text-emerald-400 text-base">
                insert_drive_file
              </span>
              <span className="truncate text-slate-700 dark:text-slate-300 font-medium">
                {event.filename}
              </span>
            </div>
            <span className="text-xs text-slate-500 dark:text-slate-400 whitespace-nowrap">
              {formatSize(event.sizeBytes)}
            </span>
            {url && (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400 hover:text-emerald-700 dark:hover:text-emerald-300 transition-colors font-medium"
                download={event.filename}
              >
                <span className="material-symbols-outlined text-base">download</span>
                {t('agent.messageBubble.download', 'Download')}
              </a>
            )}
            {canOpenInCanvas && (
              <button
                type="button"
                onClick={() => { void handleOpenInCanvas(); }}
                className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 transition-colors font-medium"
              >
                <PanelRight size={14} />
                {t('agent.messageBubble.openInCanvas', 'Canvas')}
              </button>
            )}
            {!url && artifactStatus === 'uploading' && (
              <span className="flex items-center gap-1 text-xs text-slate-400 dark:text-slate-500">
                <Loader2 size={14} className="animate-spin" />
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
                onClick={() => { void handleRefreshUrl(); }}
                disabled={refreshingUrl}
                className="flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400 hover:text-amber-700 dark:hover:text-amber-300 transition-colors font-medium disabled:opacity-50"
              >
                <RefreshCw size={14} className={refreshingUrl ? 'animate-spin' : ''} />
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
          <div className="mt-3 flex items-center gap-2 text-xs">
            <span className="px-2 py-1 bg-white/50 dark:bg-slate-800/50 rounded text-slate-500 dark:text-slate-400 border border-emerald-100 dark:border-emerald-800/20">
              {event.mimeType}
            </span>
            <span className="capitalize px-2 py-1 bg-white/50 dark:bg-slate-800/50 rounded text-slate-500 dark:text-slate-400 border border-emerald-100 dark:border-emerald-800/20">
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
        let forcedSubAgentName: string | undefined = undefined;

        if (systemInstructionMatch) {
          forcedSubAgentName = systemInstructionMatch[1];
          content = rawContent.slice(systemInstructionMatch[0].length);
        }

        return (
          <UserMessage
            content={content}
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
        return <TextDelta content={getContent(event)} />;

      case 'thought':
        return <Thought content={getContent(event)} />;

      case 'act': {
        const observeEvent = allEvents
          ? findMatchingObserve(event, allEvents)
          : undefined;
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
          <ArtifactCreated event={event as unknown as ArtifactCreatedEvent & { error?: string | undefined }} />
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
          decision?: string | undefined;
        };
        return (
          <InlineHITLCard
            hitlType="decision"
            requestId={e.requestId || decisionData?.request_id || ''}
            decisionData={decisionData}
            isAnswered={e.answered === true}
            answeredValue={e.decision}
            expiresAt={e.expiresAt}
            createdAt={e.createdAt || String(event.timestamp)}
          />
        );
      }

      case 'decision_answered': {
        const e = event as TimelineEvent & {
          requestId?: string | undefined;
          decision?: string | undefined;
          createdAt?: string | undefined;
        };
        return (
          <InlineHITLCard
            hitlType="decision"
            requestId={e.requestId || ''}
            isAnswered={true}
            answeredValue={e.decision}
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
  MessageBubbleProps,
  MessageBubbleRootProps,
  UserMessageProps,
  AssistantMessageProps,
  TextDeltaProps,
  ThoughtProps,
  ToolExecutionProps,
  WorkPlanProps,
  TextEndProps,
  ArtifactCreatedProps,
  MessageBubbleCompound,
} from './types';
