/**
 * MessageBubble - Modern message bubble component
 *
 * Compound Component Pattern for flexible message rendering.
 */

import React, { memo, useState, useEffect } from 'react';
import { LazyAvatar, LazyTag } from '@/components/ui/lazyAntd';
import {
  User,
  Sparkles,
  Wrench,
  CheckCircle2,
  XCircle,
  Loader2,
  ChevronDown,
  ChevronUp,
  Clock
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type {
  TimelineEvent,
  ActEvent,
  ObserveEvent,
  ArtifactCreatedEvent,
} from '../../../types/agent';
// Import types without type qualifier
import {
  MessageBubbleCompound,
  UserMessageProps,
  AssistantMessageProps,
  TextDeltaProps,
  ThoughtProps,
  ToolExecutionProps,
  WorkPlanProps,
  StepStartProps,
  TextEndProps,
  ArtifactCreatedProps,
} from './types';

// ========================================
// Marker Symbols
// ========================================

const _UserMarker = Symbol('MessageBubble.User');
const _AssistantMarker = Symbol('MessageBubble.Assistant');
const _TextDeltaMarker = Symbol('MessageBubble.TextDelta');
const _ThoughtMarker = Symbol('MessageBubble.Thought');
const _ToolExecutionMarker = Symbol('MessageBubble.ToolExecution');
const _WorkPlanMarker = Symbol('MessageBubble.WorkPlan');
const _StepStartMarker = Symbol('MessageBubble.StepStart');
const _TextEndMarker = Symbol('MessageBubble.TextEnd');
const _ArtifactCreatedMarker = Symbol('MessageBubble.ArtifactCreated');

// ========================================
// Utilities
// ========================================

// Dynamic import hook for syntax highlighter
const useSyntaxHighlighter = () => {
  const [SyntaxHighlighter, setSyntaxHighlighter] = useState<any>(null);
  const [vscDarkPlus, setVscDarkPlus] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    let mounted = true;
    const loadHighlighter = async () => {
      if (isLoading || SyntaxHighlighter) return;

      setIsLoading(true);
      try {
        const [{ Prism }, { vscDarkPlus: styles }] = await Promise.all([
          import('react-syntax-highlighter'),
          import('react-syntax-highlighter/dist/esm/styles/prism')
        ]);
        if (mounted) {
          setSyntaxHighlighter(() => Prism);
          setVscDarkPlus(() => styles);
        }
      } catch (error) {
        console.warn('Failed to load syntax highlighter:', error);
      } finally {
        if (mounted) setIsLoading(false);
      }
    };

    loadHighlighter();
    return () => { mounted = false; };
  }, [isLoading, SyntaxHighlighter]);

  return { SyntaxHighlighter, vscDarkPlus, isLoading };
};

// Code block component with lazy loading
const CodeBlock: React.FC<{ language: string; children: string }> = ({ language, children }) => {
  const { SyntaxHighlighter, vscDarkPlus } = useSyntaxHighlighter();

  if (!SyntaxHighlighter || !vscDarkPlus) {
    return (
      <code className="font-mono text-sm bg-slate-100 dark:bg-slate-800 p-3 rounded block overflow-x-auto">
        {children}
      </code>
    );
  }

  return (
    <SyntaxHighlighter
      style={vscDarkPlus}
      language={language}
      PreTag="div"
    >
      {String(children).replace(/\n$/, '')}
    </SyntaxHighlighter>
  );
};

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
const findMatchingObserve = (actEvent: ActEvent, events: TimelineEvent[]): ObserveEvent | undefined => {
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
// Sub-Components
// ========================================

// User Message Component
const UserMessage: React.FC<UserMessageProps> = memo(({ content }) => {
  if (!content) return null;
  return (
    <div className="flex items-start justify-end gap-3 mb-4 animate-slide-up">
      <div className="max-w-[85%] md:max-w-[75%]">
        <div className="bg-primary/10 border border-primary/20 rounded-2xl rounded-tr-sm px-4 py-3 shadow-sm">
          <p className="text-base leading-relaxed whitespace-pre-wrap break-words text-slate-900 dark:text-slate-100 font-sans">{content}</p>
        </div>
      </div>
      <LazyAvatar className="w-8 h-8 bg-slate-200 dark:bg-slate-700 flex-shrink-0">
        <User size={16} className="text-slate-600 dark:text-slate-400" />
      </LazyAvatar>
    </div>
  );
});
UserMessage.displayName = 'MessageBubble.User';

// Assistant Message Component
const AssistantMessage: React.FC<AssistantMessageProps> = memo(({ content, isStreaming }) => {
  if (!content && !isStreaming) return null;
  return (
    <div className="flex items-start gap-3 mb-4 animate-slide-up">
      <LazyAvatar className="w-8 h-8 bg-gradient-to-br from-primary to-primary-600 flex-shrink-0">
        <Sparkles size={16} className="text-white" />
      </LazyAvatar>
      <div className="flex-1 max-w-[85%] md:max-w-[75%]">
        <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
          <div className="prose prose-sm dark:prose-invert max-w-none font-sans">
            {content ? (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  code({ node, inline, className, children, ...props }: any) {
                    const match = /language-(\w+)/.exec(className || '');
                    return !inline && match ? (
                      <CodeBlock language={match[1]}>{String(children).replace(/\n$/, '')}</CodeBlock>
                    ) : (
                      <code className={`${className} font-mono text-sm`} {...props}>
                        {children}
                      </code>
                    );
                  },
                  p({ children }) {
                    return <p className="text-base leading-relaxed break-words">{children}</p>;
                  },
                  pre({ children }) {
                    return <pre className="overflow-x-auto max-w-full">{children}</pre>;
                  },
                }}
              >
                {content}
              </ReactMarkdown>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
});
AssistantMessage.displayName = 'MessageBubble.Assistant';

// Text Delta Component (for streaming content)
const TextDelta: React.FC<TextDeltaProps> = memo(({ content }) => {
  if (!content) return null;
  return (
    <div className="flex items-start gap-3 mb-4 animate-slide-up">
      <LazyAvatar className="w-8 h-8 bg-gradient-to-br from-primary to-primary-600 flex-shrink-0">
        <Sparkles size={16} className="text-white" />
      </LazyAvatar>
      <div className="flex-1 max-w-[85%] md:max-w-[75%]">
        <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
          <div className="prose prose-sm dark:prose-invert max-w-none font-sans prose-p:my-1.5 prose-headings:mt-3 prose-headings:mb-1.5 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-pre:bg-slate-100 prose-pre:dark:bg-slate-800 prose-code:text-primary prose-code:before:content-none prose-code:after:content-none prose-a:text-primary prose-a:no-underline hover:prose-a:underline prose-th:text-left prose-img:rounded-lg prose-img:shadow-md leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {content}
            </ReactMarkdown>
          </div>
        </div>
      </div>
    </div>
  );
});
TextDelta.displayName = 'MessageBubble.TextDelta';

// Thought/Reasoning Component
const Thought: React.FC<ThoughtProps> = memo(({ content }) => {
  if (!content) return null;

  return (
    <div className="flex items-start gap-3 mb-3 animate-slide-up">
      <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
        <span className="material-symbols-outlined text-primary text-lg">psychology</span>
      </div>
      <div className="flex-1 max-w-[85%] md:max-w-[75%]">
        <div className="bg-slate-50 dark:bg-surface-dark/50 border border-slate-200 dark:border-border-dark rounded-2xl rounded-tl-none p-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="material-symbols-outlined text-sm text-primary">chevron_right</span>
            <span className="font-semibold uppercase text-[10px] text-primary">Reasoning Log</span>
          </div>
          <div className="mt-3 pl-4 border-l-2 border-slate-200 dark:border-border-dark text-sm text-slate-500 dark:text-text-muted leading-relaxed">
            <p className="whitespace-pre-wrap">{content}</p>
          </div>
        </div>
      </div>
    </div>
  );
});
Thought.displayName = 'MessageBubble.Thought';

// Tool Execution Component
const ToolExecution: React.FC<ToolExecutionProps> = memo(({ event, observeEvent }) => {
  const [expanded, setExpanded] = useState(!observeEvent);
  if (!event) return null;

  const hasError = observeEvent?.isError;
  const duration = observeEvent && event
    ? (observeEvent.timestamp || 0) - (event.timestamp || 0)
    : null;

  const statusIcon = observeEvent ? (
    hasError ? <XCircle size={16} className="text-red-500" /> : <CheckCircle2 size={16} className="text-emerald-500" />
  ) : (
    <Loader2 size={16} className="text-primary animate-spin" />
  );

  const statusText = observeEvent
    ? (hasError ? 'Failed' : 'Success')
    : 'Running';

  return (
    <div className="flex items-start gap-3 mb-3 animate-slide-up">
      <div className={`
        w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0
        ${observeEvent
          ? (hasError ? 'bg-red-50 dark:bg-red-900/20' : 'bg-emerald-50 dark:bg-emerald-900/20')
          : 'bg-blue-50 dark:bg-blue-900/20'
        }
      `}>
        <Wrench size={16} className={`
          ${observeEvent
            ? (hasError ? 'text-red-500' : 'text-emerald-500')
            : 'text-primary'
          }
        `} />
      </div>
      <div className="flex-1 min-w-0 max-w-[85%] md:max-w-[75%]">
        <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden shadow-sm max-w-full">
          {/* Header */}
          <button
            onClick={() => setExpanded(!expanded)}
            className="w-full px-4 py-3 flex items-center justify-between hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors"
          >
            <div className="flex items-center gap-3 min-w-0 flex-1">
              <span className="font-medium text-sm text-slate-900 dark:text-slate-100 truncate">
                {event.toolName || 'Unknown Tool'}
              </span>
              <LazyTag className={`
                flex-shrink-0
                ${observeEvent
                  ? (hasError ? 'bg-red-50 text-red-600 border-red-200' : 'bg-emerald-50 text-emerald-600 border-emerald-200')
                  : 'bg-blue-50 text-primary border-blue-200'
                }
              `}>
                <span className="flex items-center gap-1">
                  {statusIcon}
                  {statusText}
                </span>
              </LazyTag>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0 ml-2">
              {duration && duration > 0 && (
                <span className="text-xs text-slate-400 flex items-center gap-1">
                  <Clock size={12} />
                  {duration}ms
                </span>
              )}
              {expanded ? <ChevronUp size={16} className="text-slate-400" /> : <ChevronDown size={16} className="text-slate-400" />}
            </div>
          </button>

          {/* Content */}
          {expanded && (
            <div className="px-4 pb-4 border-t border-slate-100 dark:border-slate-700 max-w-full">
              {/* Input */}
              <div className="mt-3 max-w-full">
                <p className="text-xs font-medium text-slate-500 mb-1.5 uppercase tracking-wide">Input</p>
                <div className="rounded-lg overflow-hidden border border-slate-200 dark:border-slate-700 max-w-full">
                  <div className="bg-slate-100 dark:bg-slate-800 px-3 py-1.5 text-xs text-slate-500 border-b border-slate-200 dark:border-slate-700">
                    JSON
                  </div>
                  <pre className="bg-slate-50 dark:bg-slate-900 p-3 text-xs overflow-x-auto whitespace-pre-wrap break-words max-w-full">
                    <code className="text-slate-700 dark:text-slate-300 font-mono">
                      {JSON.stringify(event.toolInput || {}, null, 2)}
                    </code>
                  </pre>
                </div>
              </div>

              {/* Output */}
              {observeEvent && (
                <div className="mt-3 max-w-full">
                  <p className="text-xs font-medium text-slate-500 mb-1.5 uppercase tracking-wide">Output</p>
                  {(() => {
                    const formatted = formatToolOutput(observeEvent.toolOutput);
                    if (formatted.type === 'error') {
                      return (
                        <div className="rounded-lg p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 max-w-full">
                          <div className="flex items-start gap-2">
                            <XCircle size={14} className="text-red-500 mt-0.5 flex-shrink-0" />
                            <pre className="text-xs text-red-700 dark:text-red-300 overflow-x-auto whitespace-pre-wrap break-words max-w-full font-mono">
                              <code>{formatted.content}</code>
                            </pre>
                          </div>
                        </div>
                      );
                    }
                    if (formatted.type === 'json') {
                      return (
                        <div className="rounded-lg overflow-hidden border border-slate-200 dark:border-slate-700 max-w-full">
                          <div className="bg-slate-100 dark:bg-slate-800 px-3 py-1.5 text-xs text-slate-500 border-b border-slate-200 dark:border-slate-700">
                            JSON
                          </div>
                          <pre className="bg-slate-50 dark:bg-slate-900 p-3 text-xs overflow-x-auto whitespace-pre-wrap break-words max-w-full">
                            <code className="text-slate-700 dark:text-slate-300 font-mono">{formatted.content}</code>
                          </pre>
                        </div>
                      );
                    }
                    return (
                      <pre className="rounded-lg p-3 text-xs overflow-x-auto whitespace-pre-wrap break-words max-w-full bg-slate-50 dark:bg-slate-900 text-slate-700 dark:text-slate-300 font-mono">
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

// Work Plan Component
const WorkPlan: React.FC<WorkPlanProps> = memo(({ event }) => {
  const [expanded, setExpanded] = useState(true);
  const steps = event?.steps || [];

  if (!steps.length) return null;

  return (
    <div className="flex items-start gap-3 mb-3 animate-slide-up">
      <div className="w-8 h-8 rounded-lg bg-purple-100 dark:bg-purple-900/20 flex items-center justify-center flex-shrink-0">
        <Sparkles size={16} className="text-purple-600 dark:text-purple-400" />
      </div>
      <div className="flex-1">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-slate-100 transition-colors"
        >
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          <span>Work Plan: {steps.length} steps</span>
        </button>
        {expanded && (
          <div className="mt-2 space-y-2">
            {steps.map((step: any, index: number) => (
              <div
                key={index}
                className="flex items-center gap-3 p-2 bg-purple-50 dark:bg-purple-900/10 rounded-lg"
              >
                <span className="w-6 h-6 rounded-full bg-white dark:bg-slate-800 text-xs font-medium flex items-center justify-center text-purple-600 flex-shrink-0">
                  {index + 1}
                </span>
                <span className="text-sm text-slate-700 dark:text-slate-300 break-words">{step.description || 'No description'}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
});
WorkPlan.displayName = 'MessageBubble.WorkPlan';

// Step Start Component
const StepStart: React.FC<StepStartProps> = memo(({ event }) => {
  const stepDesc = event?.stepDescription || event?.description;
  const stepIndex = event?.stepIndex ?? event?.step_index;

  if (!stepDesc) return null;

  return (
    <div className="flex items-start gap-3 my-2 opacity-70 animate-slide-up">
      <div className="w-7 h-7 rounded-full bg-amber-100 dark:bg-amber-500/10 flex items-center justify-center shrink-0">
        <span className="text-amber-600 text-xs">{stepIndex !== undefined ? stepIndex + 1 : '•'}</span>
      </div>
      <div className="flex-1 text-sm text-slate-600 dark:text-slate-400 pt-1 break-words">
        {stepDesc}
      </div>
    </div>
  );
});
StepStart.displayName = 'MessageBubble.StepStart';

// Text End Component
const TextEnd: React.FC<TextEndProps> = memo(({ event }) => {
  const fullText = 'fullText' in event ? (event.fullText as string) : '';
  if (!fullText || !fullText.trim()) return null;

  return (
    <div className="flex items-start gap-3 mb-4 animate-slide-up">
      <LazyAvatar className="w-8 h-8 bg-gradient-to-br from-primary to-primary-600 flex-shrink-0">
        <Sparkles size={16} className="text-white" />
      </LazyAvatar>
      <div className="flex-1 max-w-[85%] md:max-w-[75%]">
        <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
          <div className="prose prose-sm dark:prose-invert max-w-none font-sans prose-p:my-1.5 prose-headings:mt-3 prose-headings:mb-1.5 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-pre:bg-slate-100 prose-pre:dark:bg-slate-800 prose-code:text-primary prose-code:before:content-none prose-code:after:content-none prose-a:text-primary prose-a:no-underline hover:prose-a:underline prose-th:text-left prose-img:rounded-lg prose-img:shadow-md leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {fullText}
            </ReactMarkdown>
          </div>
        </div>
      </div>
    </div>
  );
});
TextEnd.displayName = 'MessageBubble.TextEnd';

// Artifact Created Component
const ArtifactCreated: React.FC<ArtifactCreatedProps> = memo(({ event }) => {
  const [imageError, setImageError] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);

  const getCategoryIcon = (category: string) => {
    switch (category) {
      case 'image': return 'image';
      case 'video': return 'movie';
      case 'audio': return 'audio_file';
      case 'document': return 'description';
      case 'code': return 'code';
      case 'data': return 'table_chart';
      case 'archive': return 'folder_zip';
      default: return 'attach_file';
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const isImage = event.category === 'image';
  const url = event.url || event.previewUrl;

  return (
    <div className="flex items-start gap-3 animate-slide-up">
      <div className="w-8 h-8 rounded-full bg-emerald-100 dark:bg-emerald-900/50 flex items-center justify-center shrink-0 mt-0.5 shadow-sm">
        <span className="material-symbols-outlined text-emerald-600 dark:text-emerald-400 text-lg">
          {getCategoryIcon(event.category)}
        </span>
      </div>
      <div className="flex-1 min-w-0">
        <div className="bg-gradient-to-r from-emerald-50 to-teal-50 dark:from-emerald-900/30 dark:to-teal-900/30 rounded-xl p-4 border border-emerald-200/50 dark:border-emerald-700/50">
          {/* Header */}
          <div className="flex items-center gap-2 mb-3">
            <span className="material-symbols-outlined text-emerald-600 dark:text-emerald-400 text-lg">
              {getCategoryIcon(event.category)}
            </span>
            <span className="text-sm font-medium text-emerald-700 dark:text-emerald-300">
              文件已生成
            </span>
            {event.sourceTool && (
              <span className="text-xs px-2 py-0.5 bg-emerald-100 dark:bg-emerald-800/50 text-emerald-600 dark:text-emerald-400 rounded">
                {event.sourceTool}
              </span>
            )}
          </div>

          {/* Image Preview */}
          {isImage && url && !imageError && (
            <div className="mb-3 relative">
              {!imageLoaded && (
                <div className="absolute inset-0 flex items-center justify-center bg-slate-100 dark:bg-slate-800 rounded-lg min-h-[100px]">
                  <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
                </div>
              )}
              <img
                src={url}
                alt={event.filename}
                className={`max-w-full max-h-[300px] rounded-lg shadow-sm object-contain ${
                  imageLoaded ? 'opacity-100' : 'opacity-0'
                } transition-opacity duration-300`}
                onLoad={() => setImageLoaded(true)}
                onError={() => setImageError(true)}
              />
            </div>
          )}

          {/* File Info */}
          <div className="flex items-center gap-3 text-sm">
            <div className="flex items-center gap-2 flex-1 min-w-0">
              <span className="material-symbols-outlined text-slate-500 dark:text-slate-400 text-base">
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
                className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400 hover:text-emerald-700 dark:hover:text-emerald-300 transition-colors"
                download={event.filename}
              >
                <span className="material-symbols-outlined text-base">
                  download
                </span>
                下载
              </a>
            )}
          </div>

          {/* Additional metadata */}
          <div className="mt-2 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
            <span className="px-2 py-0.5 bg-white/50 dark:bg-slate-800/50 rounded">
              {event.mimeType}
            </span>
            <span className="capitalize px-2 py-0.5 bg-white/50 dark:bg-slate-800/50 rounded">
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

const MessageBubbleRoot: React.FC<MessageBubbleRootProps> = memo(({
  event,
  isStreaming,
  allEvents,
}) => {
  if (!event) return null;

  switch (event.type) {
    case 'user_message':
      return <UserMessage content={getContent(event)} />;

    case 'assistant_message':
      return (
        <AssistantMessage
          content={getContent(event)}
          isStreaming={isStreaming}
        />
      );

    case 'text_delta':
      return <TextDelta content={getContent(event)} />;

    case 'thought':
      return <Thought content={getContent(event)} />;

    case 'act': {
      const observeEvent = allEvents ? findMatchingObserve(event as ActEvent, allEvents) : undefined;
      return (
        <ToolExecution
          event={event as ActEvent}
          observeEvent={observeEvent}
        />
      );
    }

    case 'observe':
      // Observe events are rendered as part of act
      return null;

    case 'work_plan':
      return <WorkPlan event={event} />;

    case 'step_start':
      return <StepStart event={event} />;

    case 'text_end':
      return <TextEnd event={event} />;

    case 'step_end':
    case 'text_start':
      // These are control events, no visual output needed
      return null;

    case 'artifact_created':
      console.log('[MessageBubble] Rendering artifact_created event:', event);
      return <ArtifactCreated event={event as unknown as ArtifactCreatedEvent} />;

    // These artifact events don't need visual rendering
    case 'artifact_ready':
    case 'artifact_error':
    case 'artifacts_batch':
      return null;

    default:
      // Unknown event type - log for debugging
      console.warn('Unknown event type in MessageBubble:', (event as any).type);
      return null;
  }
});

MessageBubbleRoot.displayName = 'MessageBubble';

// ========================================
// Compound Component Export
// ========================================

// Direct export like legacy file
export const MessageBubble = MessageBubbleRoot as any;

// Attach sub-components
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

// Export types for external use
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
