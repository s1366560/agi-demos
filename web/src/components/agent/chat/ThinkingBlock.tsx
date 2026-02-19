/**
 * ThinkingBlock - Polished agent reasoning visualization
 *
 * Replaces StreamingThoughtBubble with a cleaner, collapsible design.
 * Features:
 * - Collapsed by default with summary line
 * - Expandable with smooth animation
 * - Thinking duration display
 * - Distinct left-border accent style
 * - Streaming support with animated dots
 * - Progress indication for multi-step reasoning
 * - ARIA accessibility support
 * - Keyboard navigation
 */

import { memo, useState, useEffect, useRef, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { ChevronDown, ChevronRight, Brain } from 'lucide-react';

export interface ThinkingBlockProps {
  content: string;
  isStreaming: boolean;
  /** Start time for duration tracking (epoch ms) */
  startTime?: number;
  /** Reasoning steps for progress indication */
  steps?: string[];
  /** Current step index */
  currentStep?: number;
}

export const ThinkingBlock = memo<ThinkingBlockProps>(
  ({ content, isStreaming, startTime, steps, currentStep = 0 }) => {
    const { t } = useTranslation();
    const [expanded, setExpanded] = useState(true);
    const [duration, setDuration] = useState(0);
    const contentRef = useRef<HTMLDivElement>(null);
    const buttonRef = useRef<HTMLButtonElement>(null);

    // Track thinking duration
    useEffect(() => {
      if (!isStreaming || !startTime) return;

      const interval = setInterval(() => {
        setDuration(Math.floor((Date.now() - startTime) / 1000));
      }, 1000);

      return () => clearInterval(interval);
    }, [isStreaming, startTime]);

    // Auto-scroll content while streaming
    useEffect(() => {
      if (isStreaming && expanded && contentRef.current) {
        contentRef.current.scrollTop = contentRef.current.scrollHeight;
      }
    }, [content, isStreaming, expanded]);

    // Keyboard navigation
    const handleKeyDown = useCallback(
      (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          setExpanded((prev) => !prev);
        }
        if (e.key === 'Escape' && expanded) {
          setExpanded(false);
        }
      },
      [expanded]
    );

    const formatDuration = (seconds: number): string => {
      if (seconds < 60) return `${seconds}s`;
      const mins = Math.floor(seconds / 60);
      const secs = seconds % 60;
      return `${mins}m ${secs}s`;
    };

    // Truncate content for collapsed preview
    const previewText = content
      ? content.slice(0, 100).replace(/\n/g, ' ').trim() +
        (content.length > 100 ? '...' : '')
      : t('agent.thinking.analyzing', 'Analyzing your request...');

    // Calculate progress percentage
    const progressPercentage =
      steps && steps.length > 0 ? ((currentStep + 1) / steps.length) * 100 : 0;

    return (
      <div className="flex items-start gap-3 mb-2 animate-fade-in-up">
        {/* Icon */}
        <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
          <Brain
            size={16}
            className={`text-slate-500 dark:text-slate-400 ${isStreaming ? 'animate-pulse' : ''}`}
          />
        </div>

        {/* Content */}
        <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
          <div className="border-l-3 border-slate-300 dark:border-slate-600 rounded-r-xl overflow-hidden bg-slate-50/80 dark:bg-slate-800/50">
            {/* Header - always visible */}
            <button
              ref={buttonRef}
              type="button"
              onClick={() => setExpanded(!expanded)}
              onKeyDown={handleKeyDown}
              aria-expanded={expanded}
              aria-controls="thinking-content"
              aria-label={expanded ? 'Collapse thinking' : 'Expand thinking'}
              className="w-full px-4 py-2.5 flex items-center gap-2 hover:bg-slate-100/50 dark:hover:bg-slate-700/30 transition-colors text-left focus:outline-none focus:ring-2 focus:ring-primary/50 focus:ring-inset"
            >
              {expanded ? (
                <ChevronDown size={14} className="text-slate-400 flex-shrink-0" />
              ) : (
                <ChevronRight size={14} className="text-slate-400 flex-shrink-0" />
              )}

              <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider flex-shrink-0">
                {t('agent.thinking.title', 'Thinking')}
              </span>

              {/* Streaming dots */}
              {isStreaming && (
                <span className="flex gap-0.5 flex-shrink-0" aria-hidden="true">
                  <span
                    className="w-1 h-1 bg-slate-400 rounded-full animate-bounce"
                    style={{ animationDelay: '0ms' }}
                  />
                  <span
                    className="w-1 h-1 bg-slate-400 rounded-full animate-bounce"
                    style={{ animationDelay: '150ms' }}
                  />
                  <span
                    className="w-1 h-1 bg-slate-400 rounded-full animate-bounce"
                    style={{ animationDelay: '300ms' }}
                  />
                </span>
              )}

              {/* Collapsed preview text */}
              {!expanded && (
                <span className="text-xs text-slate-400 dark:text-slate-500 truncate min-w-0">
                  {previewText}
                </span>
              )}

              {/* Duration badge */}
              {(duration > 0 || !isStreaming) && (
                <span className="ml-auto text-xs text-slate-400 dark:text-slate-500 flex-shrink-0 tabular-nums">
                  {formatDuration(duration || 0)}
                </span>
              )}
            </button>

            {/* Progress bar (when steps provided) */}
            {steps && steps.length > 0 && (
              <div className="w-full h-0.5 bg-slate-200 dark:bg-slate-700">
                <div
                  className="h-full bg-primary transition-all duration-300 ease-in-out"
                  style={{ width: `${progressPercentage}%` }}
                  role="progressbar"
                  aria-valuenow={progressPercentage}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label="Thinking progress"
                />
              </div>
            )}

            {/* Expandable content */}
            <div
              id="thinking-content"
              role="region"
              aria-labelledby="thinking-label"
              className={`
                overflow-hidden transition-all duration-300 ease-in-out
                ${expanded ? 'max-h-[400px]' : 'max-h-0'}
              `}
            >
              <div
                ref={contentRef}
                className="px-4 pb-3 max-h-[360px] overflow-y-auto"
              >
                {/* Steps list (if provided) */}
                {steps && steps.length > 0 && (
                  <div className="mb-3 space-y-1.5">
                    {steps.map((step, idx) => (
                      <div
                        key={idx}
                        className={`flex items-center gap-2 text-xs ${
                          idx === currentStep
                            ? 'text-primary font-medium'
                            : idx < currentStep
                            ? 'text-slate-500 dark:text-slate-400 line-through'
                            : 'text-slate-400 dark:text-slate-500'
                        }`}
                      >
                        <span
                          className={`w-4 h-4 rounded-full flex items-center justify-center text-[10px] ${
                            idx === currentStep
                              ? 'bg-primary/20 text-primary'
                              : idx < currentStep
                              ? 'bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400'
                              : 'bg-slate-100 dark:bg-slate-800 text-slate-400 dark:text-slate-500'
                          }`}
                        >
                          {idx < currentStep ? '✓' : idx + 1}
                        </span>
                        <span>{step}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Content */}
                <p className="text-sm text-slate-600 dark:text-slate-400 leading-relaxed whitespace-pre-wrap font-mono">
                  {content}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  },
  (prevProps, nextProps) => {
    return (
      prevProps.content === nextProps.content &&
      prevProps.isStreaming === nextProps.isStreaming &&
      prevProps.steps === nextProps.steps &&
      prevProps.currentStep === nextProps.currentStep
    );
  }
);

ThinkingBlock.displayName = 'ThinkingBlock';
