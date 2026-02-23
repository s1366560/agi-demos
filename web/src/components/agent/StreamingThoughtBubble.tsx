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
      <div className="flex items-start gap-3 mb-4 animate-fade-in-up">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-100 to-orange-100 dark:from-amber-900/40 dark:to-orange-900/30 flex items-center justify-center flex-shrink-0">
          <span className="material-symbols-outlined text-base text-amber-600 dark:text-amber-400">
            psychology
          </span>
        </div>
        <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
          <div className="bg-gradient-to-r from-amber-50/80 to-orange-50/50 dark:from-amber-900/20 dark:to-orange-900/10 border border-amber-200/50 dark:border-amber-800/30 rounded-xl overflow-hidden">
            <div className="px-4 py-2.5 flex items-center gap-2">
              <span className="text-xs font-semibold text-amber-700 dark:text-amber-400 uppercase tracking-wider">
                Reasoning
              </span>
              <span className="text-xs text-amber-600/70 dark:text-amber-500/70">Thinking...</span>
              {isStreaming && (
                <span className="flex gap-0.5 ml-1">
                  <span
                    className="w-1 h-1 bg-amber-500 rounded-full animate-bounce"
                    style={{ animationDelay: '0ms' }}
                  />
                  <span
                    className="w-1 h-1 bg-amber-500 rounded-full animate-bounce"
                    style={{ animationDelay: '150ms' }}
                  />
                  <span
                    className="w-1 h-1 bg-amber-500 rounded-full animate-bounce"
                    style={{ animationDelay: '300ms' }}
                  />
                </span>
              )}
            </div>
            <div className="px-4 pb-3 text-sm text-amber-900/70 dark:text-amber-100/60 leading-relaxed max-h-[300px] overflow-y-auto">
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
