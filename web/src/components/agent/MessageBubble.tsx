/**
 * MessageBubble - Modern message bubble component
 */

import React, { memo, useState } from 'react';
import { Avatar, Tag } from 'antd';
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
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { TimelineEvent, ActEvent, ObserveEvent } from '../../types/agent';

interface MessageBubbleProps {
  event: TimelineEvent;
  isStreaming?: boolean;
  allEvents?: TimelineEvent[];
}

// Safe content getter
const getContent = (event: any): string => {
  if (!event) return '';
  return event.content || event.thought || '';
};

// Format tool output for display
const formatToolOutput = (output: any): { type: 'text' | 'json' | 'error'; content: string } => {
  if (!output) return { type: 'text', content: 'No output' };
  
  // Handle string output
  if (typeof output === 'string') {
    // Check if it's an error message
    if (output.toLowerCase().includes('error:') || output.toLowerCase().includes('failed')) {
      return { type: 'error', content: output };
    }
    return { type: 'text', content: output };
  }
  
  // Handle object output
  if (typeof output === 'object') {
    // Check if it's an error response
    if (output.error || output.errorMessage || output.error_message) {
      const errorContent = output.errorMessage || output.error_message || output.error;
      if (typeof errorContent === 'string') {
        return { type: 'error', content: errorContent };
      }
    }
    
    // Pretty print JSON
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

// User Message Component
const UserMessage: React.FC<{ content: string }> = ({ content }) => {
  if (!content) return null;
  return (
    <div className="flex items-start justify-end gap-3 mb-4 animate-slide-up">
      <div className="max-w-[85%] md:max-w-[75%]">
        <div className="bg-primary/10 border border-primary/20 rounded-2xl rounded-tr-sm px-4 py-3 shadow-sm">
          <p className="text-base leading-relaxed whitespace-pre-wrap break-words text-slate-900 dark:text-slate-100 font-sans">{content}</p>
        </div>
      </div>
      <Avatar className="w-8 h-8 bg-slate-200 dark:bg-slate-700 flex-shrink-0">
        <User size={16} className="text-slate-600 dark:text-slate-400" />
      </Avatar>
    </div>
  );
};

// Assistant Message Component
const AssistantMessage: React.FC<{ content: string; isStreaming?: boolean }> = ({ 
  content, 
  isStreaming 
}) => {
  if (!content && !isStreaming) return null;
  return (
    <div className="flex items-start gap-3 mb-4 animate-slide-up">
      <Avatar className="w-8 h-8 bg-gradient-to-br from-primary to-primary-600 flex-shrink-0">
        <Sparkles size={16} className="text-white" />
      </Avatar>
      <div className="flex-1 max-w-[85%] md:max-w-[75%]">
        <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
          <div className="prose prose-sm dark:prose-invert max-w-none font-sans">
            {content ? (
              <ReactMarkdown
                components={{
                  code({ node, inline, className, children, ...props }: any) {
                    const match = /language-(\w+)/.exec(className || '');
                    return !inline && match ? (
                      <SyntaxHighlighter
                        style={vscDarkPlus}
                        language={match[1]}
                        PreTag="div"
                        {...props}
                      >
                        {String(children).replace(/\n$/, '')}
                      </SyntaxHighlighter>
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
            {isStreaming && <span className="typing-cursor" />}
          </div>
        </div>
      </div>
    </div>
  );
};

// Text Delta Component (for streaming content)
const TextDeltaBubble: React.FC<{ content: string; isStreaming?: boolean }> = ({ 
  content, 
  isStreaming 
}) => {
  if (!content) return null;
  return (
    <div className="flex items-start gap-3 mb-4 animate-slide-up">
      <Avatar className="w-8 h-8 bg-gradient-to-br from-primary to-primary-600 flex-shrink-0">
        <Sparkles size={16} className="text-white" />
      </Avatar>
      <div className="flex-1 max-w-[85%] md:max-w-[75%]">
        <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
          <div className="prose prose-sm dark:prose-invert max-w-none font-sans">
            <p className="whitespace-pre-wrap text-base leading-relaxed break-words">{content}</p>
            {isStreaming && <span className="typing-cursor" />}
          </div>
        </div>
      </div>
    </div>
  );
}

// Thought/Reasoning Component
const ThoughtBubble: React.FC<{ content: string; isStreaming?: boolean }> = ({ 
  content, 
  isStreaming 
}) => {
  if (!content) return null;

  return (
    <div className="flex items-start gap-3 mb-3 opacity-80 animate-slide-up">
      <div className="w-8 h-8 rounded-full bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center flex-shrink-0">
        <Sparkles size={14} className="text-amber-600 dark:text-amber-400" />
      </div>
      <div className="flex-1 max-w-[85%] md:max-w-[75%]">
        <div className="p-3 bg-amber-50 dark:bg-amber-900/20 rounded-lg border border-amber-100 dark:border-amber-900/30">
          <p className="text-sm text-slate-700 dark:text-slate-300 italic font-sans break-words">{content}</p>
        </div>
      </div>
    </div>
  );
};

// Tool Execution Component
const ToolExecution: React.FC<{ 
  event: ActEvent; 
  observeEvent?: ObserveEvent;
  allEvents?: TimelineEvent[];
}> = ({ event, observeEvent }) => {
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
              <Tag className={`
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
              </Tag>
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
};

// Work Plan Component
const WorkPlanBubble: React.FC<{ event: any }> = ({ event }) => {
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
};

// Step Start Component
const StepStartBubble: React.FC<{ event: any }> = ({ event }) => {
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
};

// Main Message Bubble Component
export const MessageBubble: React.FC<MessageBubbleProps> = memo(({
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
      return (
        <TextDeltaBubble 
          content={getContent(event)} 
          isStreaming={isStreaming}
        />
      );

    case 'thought':
      return (
        <ThoughtBubble 
          content={getContent(event)} 
          isStreaming={isStreaming}
        />
      );

    case 'act': {
      const observeEvent = allEvents ? findMatchingObserve(event as ActEvent, allEvents) : undefined;
      return (
        <ToolExecution 
          event={event as ActEvent} 
          observeEvent={observeEvent}
          allEvents={allEvents}
        />
      );
    }

    case 'observe':
      // Observe events are rendered as part of act
      return null;

    case 'work_plan':
      return <WorkPlanBubble event={event} />;

    case 'step_start':
      return <StepStartBubble event={event} />;

    case 'step_end':
    case 'text_start':
    case 'text_end':
      // These are control events, no visual output needed
      return null;

    default:
      // Unknown event type - log for debugging
      console.warn('Unknown event type in MessageBubble:', (event as any).type);
      return null;
  }
});

MessageBubble.displayName = 'MessageBubble';
