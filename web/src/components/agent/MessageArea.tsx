/**
 * MessageArea - Modern message display area
 */

import React, { useRef, useEffect, useCallback, useState, memo } from 'react';
import { Button } from 'antd';
import { DownOutlined, LoadingOutlined } from '@ant-design/icons';
import { MessageBubble } from './MessageBubble';
import { PlanModeBanner } from './PlanModeBanner';
import type { TimelineEvent, PlanModeStatus } from '../../types/agent';

interface MessageAreaProps {
  timeline: TimelineEvent[];
  streamingContent?: string;
  streamingThought?: string;
  isStreaming: boolean;
  isThinkingStreaming?: boolean;
  isLoading: boolean;
  planModeStatus: PlanModeStatus | null;
  onViewPlan: () => void;
  onExitPlanMode: () => void;
}

// Check if scroll is near bottom
const isNearBottom = (element: HTMLElement, threshold = 100): boolean => {
  const { scrollHeight, scrollTop, clientHeight } = element;
  return scrollHeight - scrollTop - clientHeight < threshold;
};

// Streaming thought bubble - memoized to prevent unnecessary re-renders
// Only re-renders when content actually changes
const StreamingThoughtBubble = memo<{ content: string; isStreaming: boolean }>(
  ({ content, isStreaming }) => {
    return (
      <div className="flex items-start gap-3 mb-3 animate-slide-up">
        <div className="w-8 h-8 rounded-lg bg-amber-100 dark:bg-amber-900/20 flex items-center justify-center flex-shrink-0">
          <svg className="w-4 h-4 text-amber-600 dark:text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
        </div>
        <div className="flex-1 max-w-[85%] md:max-w-[75%]">
          <div className="bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-medium text-amber-600 dark:text-amber-400 uppercase tracking-wide">Thinking</span>
              {isStreaming && (
                <span className="flex gap-0.5">
                  <span className="w-1 h-1 bg-amber-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-1 h-1 bg-amber-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-1 h-1 bg-amber-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </span>
              )}
            </div>
            <p className="text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap italic font-sans break-words">{content}</p>
            {isStreaming && <span className="typing-cursor" />}
          </div>
        </div>
      </div>
    );
  },
  (prevProps, nextProps) => {
    // Custom comparison: only re-render if content changed or streaming state changed
    return prevProps.content === nextProps.content && prevProps.isStreaming === nextProps.isStreaming;
  }
);
StreamingThoughtBubble.displayName = 'StreamingThoughtBubble';

export const MessageArea: React.FC<MessageAreaProps> = ({
  timeline,
  streamingContent,
  streamingThought,
  isStreaming,
  isThinkingStreaming,
  isLoading,
  planModeStatus,
  onViewPlan,
  onExitPlanMode,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const prevTimelineLengthRef = useRef(timeline.length);
  const isAtBottomRef = useRef(true);

  // Handle scroll events
  const handleScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    const atBottom = isNearBottom(container, 100);
    isAtBottomRef.current = atBottom;
    setShowScrollButton(!atBottom && timeline.length > 0);
  }, [timeline.length]);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const hasNewMessages = timeline.length > prevTimelineLengthRef.current;
    prevTimelineLengthRef.current = timeline.length;

    if (!hasNewMessages) return;

    // If streaming or user was at bottom, auto scroll
    if (isStreaming || isAtBottomRef.current) {
      // Use setTimeout to ensure DOM has updated
      setTimeout(() => {
        if (containerRef.current) {
          containerRef.current.scrollTop = containerRef.current.scrollHeight;
        }
      }, 0);
      setShowScrollButton(false);
    } else {
      // User is scrolled up and new messages arrived - show button
      setShowScrollButton(true);
    }
  }, [timeline, isStreaming]);

  // Initial scroll to bottom when first messages load
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    
    if (timeline.length > 0 && prevTimelineLengthRef.current === 0) {
      container.scrollTop = container.scrollHeight;
      isAtBottomRef.current = true;
    }
  }, [timeline.length]);

  // Scroll to bottom handler
  const scrollToBottom = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    container.scrollTo({
      top: container.scrollHeight,
      behavior: 'smooth',
    });
    isAtBottomRef.current = true;
    setShowScrollButton(false);
  }, []);

  // Loading state
  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <LoadingOutlined className="text-4xl text-primary mb-4" spin />
          <p className="text-slate-500">Loading conversation...</p>
        </div>
      </div>
    );
  }

  // Empty state
  if (timeline.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center text-slate-400">
          <p>No messages yet</p>
          <p className="text-sm">Start a conversation to see messages here</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full relative flex flex-col">
      {/* Plan Mode Banner */}
      {planModeStatus?.is_in_plan_mode && (
        <PlanModeBanner
          status={planModeStatus}
          onViewPlan={onViewPlan}
          onExit={onExitPlanMode}
        />
      )}

      {/* Message List */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto chat-scrollbar p-4 md:p-6"
      >
        <div className="w-full space-y-3">
          {timeline.map((event, index) => (
            <MessageBubble
              key={event.id || `event-${index}`}
              event={event}
              isStreaming={isStreaming && index === timeline.length - 1}
              allEvents={timeline}
            />
          ))}
          {/* Streaming thought indicator - shows thought_delta content in real-time */}
          {(isThinkingStreaming || streamingThought) && (
            <StreamingThoughtBubble 
              content={streamingThought || ''} 
              isStreaming={!!isThinkingStreaming} 
            />
          )}

          {/* Streaming content indicator - shows text_delta content in real-time */}
          {isStreaming && streamingContent && (
            <div className="flex items-start gap-3 animate-slide-up">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-primary-600 flex items-center justify-center flex-shrink-0">
                <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
              <div className="flex-1 max-w-[85%] md:max-w-[75%]">
                <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
                  <div className="prose prose-sm dark:prose-invert max-w-none font-sans">
                    <p className="whitespace-pre-wrap text-slate-800 dark:text-slate-200 text-base leading-relaxed break-words">{streamingContent}</p>
                    <span className="typing-cursor" />
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Scroll to bottom button */}
      {showScrollButton && (
        <Button
          type="primary"
          shape="round"
          icon={<DownOutlined />}
          onClick={scrollToBottom}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 shadow-lg animate-fade-in z-10"
        >
          Scroll to bottom
        </Button>
      )}


    </div>
  );
};
