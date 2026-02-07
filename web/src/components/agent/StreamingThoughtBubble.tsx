/**
 * StreamingThoughtBubble - Streaming thought display component
 *
 * Uses same styling as ReasoningLogCard for consistency with final render.
 */

import { memo } from 'react';

interface StreamingThoughtBubbleProps {
  content: string;
  isStreaming: boolean;
}

export const StreamingThoughtBubble = memo<StreamingThoughtBubbleProps>(
  ({ content, isStreaming }) => {
    return (
      <div className="flex items-start gap-3 mb-3 animate-slide-up">
        <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
          <span className="material-symbols-outlined text-primary text-lg">psychology</span>
        </div>
        <div className="flex-1 max-w-[85%] md:max-w-[75%]">
          <div className="bg-slate-50 dark:bg-surface-dark/50 border border-slate-200 dark:border-border-dark rounded-2xl rounded-tl-none p-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="material-symbols-outlined text-sm text-primary">chevron_right</span>
              <span className="font-semibold uppercase text-[10px] text-primary">
                Reasoning Log
              </span>
              <span className="text-xs text-slate-600 dark:text-slate-300">Thinking...</span>
              {isStreaming && (
                <span className="flex gap-0.5 ml-2">
                  <span
                    className="w-1 h-1 bg-primary rounded-full animate-bounce"
                    style={{ animationDelay: '0ms' }}
                  />
                  <span
                    className="w-1 h-1 bg-primary rounded-full animate-bounce"
                    style={{ animationDelay: '150ms' }}
                  />
                  <span
                    className="w-1 h-1 bg-primary rounded-full animate-bounce"
                    style={{ animationDelay: '300ms' }}
                  />
                </span>
              )}
            </div>
            <div className="mt-3 pl-4 border-l-2 border-slate-200 dark:border-border-dark text-sm text-slate-500 dark:text-text-muted leading-relaxed max-h-[300px] overflow-y-auto">
              <p className="whitespace-pre-wrap">{content}</p>
            </div>
          </div>
        </div>
      </div>
    );
  },
  (prevProps, nextProps) => {
    return (
      prevProps.content === nextProps.content && prevProps.isStreaming === nextProps.isStreaming
    );
  }
);

StreamingThoughtBubble.displayName = 'StreamingThoughtBubble';
