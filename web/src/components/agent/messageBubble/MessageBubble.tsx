/**
 * MessageBubble - Modern message bubble component
 *
 * Compound Component Pattern for flexible message rendering.
 * Features modern glass-morphism design, smooth animations, and improved UX.
 */

import React, { memo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';

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
} from 'lucide-react';

import { useCanvasStore } from '@/stores/canvasStore';
import { useLayoutModeStore } from '@/stores/layoutMode';
import { useSandboxStore } from '@/stores/sandbox';

import { MARKDOWN_PROSE_CLASSES } from '../styles';
import { CodeBlock as SharedCodeBlock } from '../chat/CodeBlock';
import { remarkPlugins, rehypePlugins, safeMarkdownComponents } from '../chat/markdownPlugins';
import { MessageActionBar } from '../chat/MessageActionBar';
import { SaveTemplateModal } from '../chat/SaveTemplateModal';

// Import types without type qualifier
import { InlineHITLCard } from '../InlineHITLCard';

import type {
  UserMessageProps,
  AssistantMessageProps,
  TextDeltaProps,
  ThoughtProps,
  ToolExecutionProps,
  WorkPlanProps,
  StepStartProps,
  TextEndProps,
  ArtifactCreatedProps,
  MessageBubbleRootProps,
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
    context?: Record<string, unknown>;
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
    allowCustom?: boolean;
    context?: Record<string, unknown>;
    defaultOption?: string;
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
    message?: string;
    context?: Record<string, unknown>;
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
  const e = event as PermissionAskedTimelineEvent | PermissionRequestedTimelineEvent;
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
const formatToolOutput = (output: any): { type: 'text' | 'json' | 'error'; content: string } => {
  if (!output) return { type: 'text', content: 'No output' };

  if (typeof output === 'string') {
    if (output.toLowerCase().includes('error:') || output.toLowerCase().includes('failed')) {
      return { type: 'error', content: output };
    }
    return { type: 'text', content: output };
  }

  if (typeof output === 'object') {
    if (output.error || output.errorMessage || output.error_message) {
      const errorContent = output.errorMessage || output.error_message || output.error;
      if (typeof errorContent === 'string') {
        return { type: 'error', content: errorContent };
      }
    }

    try {
      return { type: 'json', content: JSON.stringify(output, null, 2) };
    } catch {
      return { type: 'text', content: String(output) };
    }
  }

  return { type: 'text', content: String(output) };
};

// Find matching observe event for act
const findMatchingObserve = (
  actEvent: ActEvent,
  events: TimelineEvent[]
): ObserveEvent | undefined => {
  if (!events || !actEvent) return undefined;
  const actIndex = events.indexOf(actEvent as unknown as TimelineEvent);
  if (actIndex === -1) return undefined;

  for (let i = actIndex + 1; i < events.length; i++) {
    const event = events[i];
    if (event.type === 'observe') {
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

// User Message Component - Modern floating style with action bar
const UserMessage: React.FC<UserMessageProps> = memo(({ content, onReply }) => {
  if (!content) return null;
  return (
    <div className="group flex items-end justify-end gap-3 mb-6 animate-fade-in-up">
      <div className="max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
        <div className="relative">
          {/* Subtle gradient background */}
          <div className="absolute inset-0 bg-gradient-to-br from-primary/20 to-primary/5 rounded-2xl rounded-br-sm blur-sm -z-10" />
          <div className="bg-white dark:bg-slate-800 border border-slate-200/60 dark:border-slate-700/60 rounded-2xl rounded-br-sm px-5 py-3.5 shadow-sm hover:shadow-md transition-shadow duration-200">
            <p className="text-[15px] leading-relaxed whitespace-pre-wrap break-words text-slate-800 dark:text-slate-100 font-normal">
              {content}
            </p>
          </div>
          {/* Action bar - appears on hover */}
          <div className="absolute -bottom-8 right-0 z-10">
            <MessageActionBar role="user" content={content} onReply={onReply} />
          </div>
        </div>
      </div>
      <div className="w-8 h-8 rounded-full bg-gradient-to-br from-slate-100 to-slate-200 dark:from-slate-700 dark:to-slate-800 flex items-center justify-center flex-shrink-0 shadow-sm">
        <User size={16} className="text-slate-500 dark:text-slate-400" />
      </div>
    </div>
  );
});
UserMessage.displayName = 'MessageBubble.User';

// Assistant Message Component - Modern card style with action bar
const AssistantMessage: React.FC<AssistantMessageProps> = memo(({ content, isStreaming, isPinned, onPin, onReply }) => {
  const [showSaveTemplate, setShowSaveTemplate] = useState(false);
  if (!content && !isStreaming) return null;
  return (
    <div className="group flex items-start gap-3 mb-6 animate-fade-in-up">
      <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-primary to-primary-600 flex items-center justify-center flex-shrink-0 shadow-sm shadow-primary/20">
        <Bot size={18} className="text-white" />
      </div>
      <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
        <div className="relative">
          <div className="bg-white dark:bg-slate-800/90 border border-slate-200/80 dark:border-slate-700/50 rounded-2xl rounded-tl-sm px-5 py-4 shadow-sm hover:shadow-md transition-all duration-200">
            <div className={MARKDOWN_PROSE_CLASSES}>
            {content ? (
              <ReactMarkdown
                remarkPlugins={remarkPlugins}
                rehypePlugins={rehypePlugins}
                components={{
                  pre: SharedCodeBlock,
                  ...safeMarkdownComponents,
                }}
              >
                {content}
              </ReactMarkdown>
            ) : null}
          </div>
        </div>
          {/* Action bar - appears on hover */}
          {!isStreaming && content && (
            <div className="absolute -bottom-8 left-0 z-10">
              <MessageActionBar
                role="assistant"
                content={content}
                isPinned={isPinned}
                onPin={onPin}
                onReply={onReply}
                onSaveAsTemplate={() => setShowSaveTemplate(true)}
              />
            </div>
          )}
        </div>
      </div>
      {showSaveTemplate && (
        <SaveTemplateModal
          content={content || ''}
          visible={showSaveTemplate}
          onClose={() => setShowSaveTemplate(false)}
          onSave={() => setShowSaveTemplate(false)}
        />
      )}
    </div>
  );
});
AssistantMessage.displayName = 'MessageBubble.Assistant';

// Text Delta Component (for streaming content)
const TextDelta: React.FC<TextDeltaProps> = memo(({ content }) => {
  if (!content) return null;
  return (
    <div className="flex items-start gap-3 mb-6 animate-fade-in-up">
      <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-primary to-primary-600 flex items-center justify-center flex-shrink-0 shadow-sm shadow-primary/20">
        <Bot size={18} className="text-white" />
      </div>
      <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
        <div className="bg-white dark:bg-slate-800/90 border border-slate-200/80 dark:border-slate-700/50 rounded-2xl rounded-tl-sm px-5 py-4 shadow-sm">
          <div className={MARKDOWN_PROSE_CLASSES}>
            <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={safeMarkdownComponents}>{content}</ReactMarkdown>
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
    <div className="flex items-start gap-3 mb-4 animate-fade-in-up">
      <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
        <Lightbulb size={16} className="text-slate-500 dark:text-slate-400" />
      </div>
      <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
        <div className="bg-slate-50/80 dark:bg-slate-800/50 border border-slate-200/60 dark:border-slate-700/40 rounded-xl overflow-hidden">
          <button
            onClick={() => setExpanded(!expanded)}
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
  if (!event) return null;

  const hasError = observeEvent?.isError;
  const duration =
    observeEvent && event ? (observeEvent.timestamp || 0) - (event.timestamp || 0) : null;

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
    <div className="flex items-start gap-3 mb-4 animate-fade-in-up">
      <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
        <Wrench
          size={16}
          className="text-slate-500 dark:text-slate-400"
        />
      </div>
      <div className="flex-1 min-w-0 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
        <div className="bg-white dark:bg-slate-800 border border-slate-200/80 dark:border-slate-700/50 rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-shadow duration-200">
          {/* Header */}
          <button
            onClick={() => setExpanded(!expanded)}
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
                      {JSON.stringify(event.toolInput || {}, null, 2)}
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
  const steps = event?.steps || [];

  if (!steps.length) return null;

  return (
    <div className="flex items-start gap-3 mb-4 animate-fade-in-up">
      <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
        <Sparkles size={16} className="text-primary" />
      </div>
      <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
        <div className="bg-slate-50/80 dark:bg-slate-800/50 border border-slate-200/60 dark:border-slate-700/40 rounded-xl overflow-hidden">
          <button
            onClick={() => setExpanded(!expanded)}
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
                {steps.map((step: any, index: number) => (
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

// Step Start Component - Modern step indicator
const StepStart: React.FC<StepStartProps> = memo(({ event }) => {
  const stepDesc = event?.stepDescription;
  const stepIndex = event?.stepIndex;

  if (!stepDesc) return null;

  return (
    <div className="flex items-start gap-3 mb-4 animate-fade-in-up">
      <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
        <span className="text-primary text-xs font-semibold">
          {stepIndex !== undefined ? stepIndex + 1 : '•'}
        </span>
      </div>
      <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
        <div className="text-sm text-slate-600 dark:text-slate-400 bg-slate-50/50 dark:bg-slate-800/30 px-3 py-2 rounded-lg border border-slate-200/40 dark:border-slate-700/30">
          {stepDesc}
        </div>
      </div>
    </div>
  );
});
StepStart.displayName = 'MessageBubble.StepStart';

// Text End Component with action bar
const TextEnd: React.FC<TextEndProps> = memo(({ event, isPinned, onPin, onReply }) => {
  const [showSaveTemplate, setShowSaveTemplate] = useState(false);
  const fullText = 'fullText' in event ? (event.fullText as string) : '';
  if (!fullText || !fullText.trim()) return null;

  return (
    <div className="group flex items-start gap-3 mb-6 animate-fade-in-up">
      <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-primary to-primary-600 flex items-center justify-center flex-shrink-0 shadow-sm shadow-primary/20">
        <Bot size={18} className="text-white" />
      </div>
      <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
        <div className="relative">
          <div className="bg-white dark:bg-slate-800/90 border border-slate-200/80 dark:border-slate-700/50 rounded-2xl rounded-tl-sm px-5 py-4 shadow-sm">
            <div className={MARKDOWN_PROSE_CLASSES}>
              <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={safeMarkdownComponents}>{fullText}</ReactMarkdown>
            </div>
          </div>
          {/* Action bar - appears on hover */}
          <div className="absolute -bottom-8 left-0 z-10">
            <MessageActionBar
              role="assistant"
              content={fullText}
              isPinned={isPinned}
              onPin={onPin}
              onReply={onReply}
              onSaveAsTemplate={() => setShowSaveTemplate(true)}
            />
          </div>
        </div>
        {showSaveTemplate && (
          <SaveTemplateModal
            content={fullText}
            visible={showSaveTemplate}
            onClose={() => setShowSaveTemplate(false)}
            onSave={() => setShowSaveTemplate(false)}
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
  const { t } = useTranslation();

  // Subscribe to sandbox store for live URL updates (artifact_ready event)
  const storeArtifact = useSandboxStore((state) => state.artifacts.get(event.artifactId));
  const artifactUrl = storeArtifact?.url || event.url;
  const artifactPreviewUrl = storeArtifact?.previewUrl || event.previewUrl;
  const artifactError = storeArtifact?.errorMessage || event.error;
  const artifactStatus = storeArtifact?.status || (event.url ? 'ready' : artifactError ? 'error' : 'uploading');

  const canvasOpenTab = useCanvasStore((s) => s.openTab);
  const setLayoutMode = useLayoutModeStore((s) => s.setMode);

  const canOpenInCanvas = ['code', 'document', 'data'].includes(event.category);

  const handleOpenInCanvas = () => {
    const ext = event.filename.split('.').pop() || '';
    const type = event.category === 'code' ? 'code' as const
      : event.category === 'data' ? 'data' as const
      : 'markdown' as const;
    canvasOpenTab({
      id: event.artifactId,
      title: event.filename,
      type,
      content: t('agent.canvas.loadingContent', 'Loading content...'),
      language: ext,
    });
    setLayoutMode('canvas');
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
    if (bytes < 1024) return `${bytes} B`;
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
                onLoad={() => setImageLoaded(true)}
                onError={() => setImageError(true)}
              />
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
                onClick={handleOpenInCanvas}
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
const getContent = (event: any): string => {
  if (!event) return '';
  return event.content || event.thought || '';
};

const MessageBubbleRoot: React.FC<MessageBubbleRootProps> = memo(
  ({ event, isStreaming, allEvents, isPinned, onPin, onReply }) => {
    if (!event) return null;

    switch (event.type) {
      case 'user_message':
        return <UserMessage content={getContent(event)} onReply={onReply} />;

      case 'assistant_message':
        return <AssistantMessage content={getContent(event)} isStreaming={isStreaming} isPinned={isPinned} onPin={onPin} onReply={onReply} />;

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
          ? findMatchingObserve(event as ActEvent, allEvents)
          : undefined;
        return <ToolExecution event={event as ActEvent} observeEvent={observeEvent} />;
      }

      case 'observe':
        // Observe events are rendered as part of act
        return null;

      case 'work_plan':
        return <WorkPlan event={event} />;

      case 'step_start':
        return <StepStart event={event} />;

      case 'text_end':
        return <TextEnd event={event} isPinned={isPinned} onPin={onPin} onReply={onReply} />;

      case 'step_end':
      case 'text_start':
        // These are control events, no visual output needed
        return null;

      case 'artifact_created':
        console.log('[MessageBubble] Rendering artifact_created event:', event);
        return <ArtifactCreated event={event as unknown as ArtifactCreatedEvent & { error?: string }} />;

      // HITL Events - Render inline cards
      case 'clarification_asked': {
        const clarificationData = toClarificationData(event);
        const e = event as TimelineEvent & {
          requestId?: string;
          expiresAt?: string;
          createdAt?: string;
          answered?: boolean;
          answer?: string;
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
          requestId?: string;
          answer?: string;
          createdAt?: string;
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
          requestId?: string;
          expiresAt?: string;
          createdAt?: string;
          answered?: boolean;
          decision?: string;
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
          requestId?: string;
          decision?: string;
          createdAt?: string;
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
          requestId?: string;
          expiresAt?: string;
          createdAt?: string;
          answered?: boolean;
          values?: Record<string, string>;
        };
        return (
          <InlineHITLCard
            hitlType="env_var"
            requestId={e.requestId || envVarData?.request_id || ''}
            envVarData={envVarData}
            isAnswered={e.answered === true}
            answeredValue={e.values ? Object.keys(e.values).join(', ') : undefined}
            expiresAt={e.expiresAt}
            createdAt={e.createdAt || String(event.timestamp)}
          />
        );
      }

      case 'env_var_provided': {
        const e = event as TimelineEvent & {
          requestId?: string;
          variableNames?: string[];
          createdAt?: string;
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
          requestId?: string;
          expiresAt?: string;
          createdAt?: string;
          answered?: boolean;
          granted?: boolean;
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
          requestId?: string;
          granted?: boolean;
          createdAt?: string;
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
          requestId?: string;
          expiresAt?: string;
          createdAt?: string;
          answered?: boolean;
          granted?: boolean;
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
          requestId?: string;
          granted?: boolean;
          createdAt?: string;
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

      default:
        console.warn('Unknown event type in MessageBubble:', (event as any).type);
        return null;
    }
  }
);

MessageBubbleRoot.displayName = 'MessageBubble';

// ========================================
// Compound Component Export
// ========================================

export const MessageBubble = MessageBubbleRoot as any;

MessageBubble.User = UserMessage;
MessageBubble.Assistant = AssistantMessage;
MessageBubble.TextDelta = TextDelta;
MessageBubble.Thought = Thought;
MessageBubble.ToolExecution = ToolExecution;
MessageBubble.WorkPlan = WorkPlan;
MessageBubble.StepStart = StepStart;
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
  StepStartProps,
  TextEndProps,
  ArtifactCreatedProps,
  MessageBubbleCompound,
} from './types';
