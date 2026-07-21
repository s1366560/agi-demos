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

import { memo, useState, useEffect, useRef, useCallback, useId } from 'react';

import { useTranslation } from 'react-i18next';

import { ChevronDown, ChevronRight, Brain } from 'lucide-react';

import type { TFunction } from 'i18next';

export interface ThinkingBlockProps {
  content: string;
  isStreaming: boolean;
  /** Start time for duration tracking (epoch ms) */
  startTime?: number | undefined;
  /** Reasoning steps for progress indication */
  steps?: string[] | undefined;
  /** Current step index */
  currentStep?: number | undefined;
}

function tFallback(t: TFunction, key: string, fallback: string): string {
  const translated = t(key, fallback);
  return translated === key ? fallback : translated;
}

export const ThinkingBlock = memo<ThinkingBlockProps>(
  ({ content, isStreaming, startTime, steps, currentStep = 0 }) => {
    const { t } = useTranslation();
    const [expanded, setExpanded] = useState(true);
    const [duration, setDuration] = useState(0);
    const contentRef = useRef<HTMLDivElement>(null);
    const buttonRef = useRef<HTMLButtonElement>(null);
    const contentId = useId();
    const labelId = useId();

    // Track thinking duration
    useEffect(() => {
      if (!isStreaming || !startTime) return;

      const interval = setInterval(() => {
        setDuration(Math.floor((Date.now() - startTime) / 1000));
      }, 1000);

      return () => {
        clearInterval(interval);
      };
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
      if (seconds < 60) return `${String(seconds)}s`;
      const mins = Math.floor(seconds / 60);
      const secs = seconds % 60;
      return `${String(mins)}m ${String(secs)}s`;
    };

    // Truncate content for collapsed preview
    const previewText = content
      ? content.slice(0, 100).replace(/\n/g, ' ').trim() + (content.length > 100 ? '…' : '')
      : t('agent.thinking.analyzing', 'Analyzing your request…');

    // Calculate progress percentage
    const progressPercentage =
      steps && steps.length > 0 ? ((currentStep + 1) / steps.length) * 100 : 0;

    return (
      <div className="flex items-start gap-3 pb-2 animate-fade-in-up">
        {/* Icon */}
        <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
          <Brain
            size={16}
            className={`text-slate-500 dark:text-slate-400 ${isStreaming ? 'animate-pulse motion-reduce:animate-none' : ''}`}
          />
        </div>

        {/* Content */}
        <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
          <div className="overflow-hidden rounded-md border border-slate-200 bg-slate-50/80 dark:border-slate-700 dark:bg-slate-800/50">
            {/* Header - always visible */}
            <button
              ref={buttonRef}
              type="button"
              onClick={() => {
                setExpanded(!expanded);
              }}
              onKeyDown={handleKeyDown}
              aria-expanded={expanded}
              aria-controls={contentId}
              aria-label={
                expanded
                  ? tFallback(t, 'agent.thinking.collapse', 'Collapse thinking')
                  : tFallback(t, 'agent.thinking.expand', 'Expand thinking')
              }
              className="w-full px-4 py-2.5 flex items-center gap-2 hover:bg-slate-100/50 dark:hover:bg-slate-700/30 transition-colors duration-150 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset"
            >
              {expanded ? (
                <ChevronDown size={14} className="text-slate-400 flex-shrink-0" />
              ) : (
                <ChevronRight size={14} className="text-slate-400 flex-shrink-0" />
              )}

              <span
                id={labelId}
                className="text-2xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider flex-shrink-0"
              >
                {t('agent.thinking.title', 'Thinking')}
              </span>

              {/* Streaming dots */}
              {isStreaming && (
                <span
                  className="flex flex-shrink-0 items-center gap-1 motion-reduce:hidden"
                  aria-hidden="true"
                >
                  <span
                    className="h-1 w-1 rounded-full bg-slate-400 animate-pulse"
                    style={{ animationDelay: '0ms' }}
                  />
                  <span
                    className="h-1 w-1 rounded-full bg-slate-400 animate-pulse"
                    style={{ animationDelay: '150ms' }}
                  />
                  <span
                    className="h-1 w-1 rounded-full bg-slate-400 animate-pulse"
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
                  className="h-full bg-primary transition-[width] duration-300 ease-in-out"
                  style={{ width: `${String(progressPercentage)}%` }}
                  role="progressbar"
                  aria-valuenow={progressPercentage}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={tFallback(t, 'agent.thinking.progress', 'Thinking progress')}
                />
              </div>
            )}

            {/* Expandable content */}
            <div
              id={contentId}
              role="region"
              aria-labelledby={labelId}
              className={`
                overflow-hidden transition-[color,background-color,border-color,box-shadow,opacity,transform,max-height] duration-300 ease-in-out
                ${expanded ? 'max-h-[400px]' : 'max-h-0'}
              `}
            >
              <div ref={contentRef} className="px-4 pb-3 max-h-[360px] overflow-y-auto">
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
                          className={`w-4 h-4 rounded-full flex items-center justify-center text-2xs ${
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
