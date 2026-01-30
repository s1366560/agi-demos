/**
 * MessageArea - Modern message display area
 */

import React, { useRef, useEffect, useCallback, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Button } from 'antd';
import { LoadingOutlined } from '@ant-design/icons';
import { MessageBubble } from './MessageBubble';
import { PlanModeBanner } from './PlanModeBanner';
import { StreamingThoughtBubble } from './StreamingThoughtBubble';
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
    <div className="h-full w-full relative flex flex-col overflow-hidden">
      {/* Plan Mode Banner */}
      {planModeStatus?.is_in_plan_mode && (
        <div className="flex-shrink-0">
          <PlanModeBanner
            status={planModeStatus}
            onViewPlan={onViewPlan}
            onExit={onExitPlanMode}
          />
        </div>
      )}

      {/* Message List */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto chat-scrollbar p-4 md:p-6 min-h-0"
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
                  <div className="prose prose-sm dark:prose-invert max-w-none font-sans prose-p:my-1.5 prose-headings:mt-3 prose-headings:mb-1.5 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-pre:bg-slate-100 prose-pre:dark:bg-slate-800 prose-code:text-primary prose-code:before:content-none prose-code:after:content-none prose-a:text-primary prose-a:no-underline hover:prose-a:underline prose-th:text-left prose-img:rounded-lg prose-img:shadow-md leading-relaxed">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {streamingContent}
                    </ReactMarkdown>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Scroll to bottom button */}
      {showScrollButton && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-6 right-6 z-10 flex items-center justify-center w-10 h-10 rounded-full bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 shadow-md border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700 hover:shadow-lg transition-all animate-fade-in"
          title="Scroll to bottom"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
          </svg>
        </button>
      )}


    </div>
  );
};
