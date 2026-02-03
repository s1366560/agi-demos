/**
 * MessageArea - Modern message display area with aggressive preloading
 *
 * Features:
 * - Aggressive preloading for seamless backward pagination (用户几乎感知不到加载)
 * - Scroll position restoration without jumping
 * - Auto-scroll to bottom for new messages
 * - Scroll to bottom button when user scrolls up
 */

import { useRef, useEffect, useCallback, useState, memo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
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
  isLoading: boolean;  // 初始加载状态（显示 loading spinner）
  planModeStatus: PlanModeStatus | null;
  onViewPlan: () => void;
  onExitPlanMode: () => void;
  // Pagination props
  hasEarlierMessages?: boolean;
  onLoadEarlier?: () => void;
  isLoadingEarlier?: boolean;  // 分页加载状态（不影响初始 loading）
  // Preload configuration
  preloadItemCount?: number; // 当剩余消息数少于此值时触发预加载
  // Conversation ID for scroll reset on conversation change
  conversationId?: string | null;
}

// Check if scroll is near bottom
const isNearBottom = (element: HTMLElement, threshold = 100): boolean => {
  const { scrollHeight, scrollTop, clientHeight } = element;
  return scrollHeight - scrollTop - clientHeight < threshold;
};

// Memoized MessageArea to prevent unnecessary re-renders (rerender-memo)
export const MessageArea = memo<MessageAreaProps>(({
  timeline,
  streamingContent,
  streamingThought,
  isStreaming,
  isThinkingStreaming,
  isLoading,
  planModeStatus,
  onViewPlan,
  onExitPlanMode,
  hasEarlierMessages = false,
  onLoadEarlier,
  isLoadingEarlier: propIsLoadingEarlier = false,
  preloadItemCount = 10, // 当用户看到前10条消息时就开始加载更多
  conversationId,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const [showLoadingIndicator, setShowLoadingIndicator] = useState(false);
  
  // Pagination state refs
  const prevTimelineLengthRef = useRef(timeline.length);
  const previousScrollHeightRef = useRef(0);
  const previousScrollTopRef = useRef(0);
  const isLoadingEarlierRef = useRef(false);
  const isInitialLoadRef = useRef(true);
  const hasScrolledInitiallyRef = useRef(false);
  const loadingIndicatorTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const lastLoadTimeRef = useRef(0);
  
  // Track if user has manually scrolled up during streaming
  // This is used to disable auto-scroll if user explicitly scrolls up to read
  const userScrolledUpRef = useRef(false);

  // Save scroll position before loading earlier messages
  const saveScrollPosition = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    
    previousScrollHeightRef.current = container.scrollHeight;
    previousScrollTopRef.current = container.scrollTop;
  }, []);

  // Restore scroll position after loading earlier messages
  const restoreScrollPosition = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    const newScrollHeight = container.scrollHeight;
    const heightDifference = newScrollHeight - previousScrollHeightRef.current;
    
    // Restore scroll position: new position = old position + height of new content
    const targetScrollTop = previousScrollTopRef.current + heightDifference;
    
    container.scrollTop = targetScrollTop;
    
    // Clear saved values
    previousScrollHeightRef.current = 0;
    previousScrollTopRef.current = 0;
  }, []);

  // 核心优化：激进的预加载逻辑
  const checkAndPreload = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    if (
      !isLoadingEarlierRef.current &&
      !propIsLoadingEarlier &&
      hasEarlierMessages &&
      onLoadEarlier
    ) {
      const { scrollTop } = container;
      
      // 计算平均消息高度（估算）
      const avgMessageHeight = 100; // 平均每条消息约100px
      const visibleItemsFromTop = Math.ceil(scrollTop / avgMessageHeight);
      
      // 当从顶部可见的消息数少于阈值时，触发预加载
      // 这意味着用户还没滚动到顶部，但已经"接近"顶部了
      if (visibleItemsFromTop < preloadItemCount) {
        // 防抖动：确保两次加载之间至少有 300ms 间隔
        const now = Date.now();
        if (now - lastLoadTimeRef.current < 300) return;
        
        // Save current scroll position BEFORE new content loads
        saveScrollPosition();
        
        isLoadingEarlierRef.current = true;
        lastLoadTimeRef.current = now;

        // 延迟显示 loading 指示器，如果加载很快用户就看不到
        loadingIndicatorTimeoutRef.current = setTimeout(() => {
          setShowLoadingIndicator(true);
        }, 300);

        onLoadEarlier();

        // Reset loading flag after a delay
        setTimeout(() => {
          isLoadingEarlierRef.current = false;
        }, 500);
      }
    }
  // Note: isLoading is used inside checkAndPreload but the effect should re-run when hasEarlierMessages changes
  }, [hasEarlierMessages, onLoadEarlier, preloadItemCount, saveScrollPosition, propIsLoadingEarlier]);

  // Handle scroll events
  const handleScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container || isLoading) return;

    // 检查是否需要预加载
    checkAndPreload();

    const atBottom = isNearBottom(container, 100);
    setShowScrollButton(!atBottom && timeline.length > 0);
    
    // Track if user has manually scrolled up during streaming
    // This disables auto-scroll until they scroll back down
    if (isStreaming && !atBottom) {
      userScrolledUpRef.current = true;
    } else if (isStreaming && atBottom) {
      userScrolledUpRef.current = false;
    }
  }, [isLoading, timeline.length, checkAndPreload, isStreaming]);

  // Handle timeline changes
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const currentTimelineLength = timeline.length;
    const previousTimelineLength = prevTimelineLengthRef.current;
    const hasNewMessages = currentTimelineLength > previousTimelineLength;
    const isInitialLoad = isInitialLoadRef.current && currentTimelineLength > 0;

    // Initial load - scroll to bottom once
    if (isInitialLoad && !hasScrolledInitiallyRef.current) {
      hasScrolledInitiallyRef.current = true;
      isInitialLoadRef.current = false;
      
      requestAnimationFrame(() => {
        if (containerRef.current) {
          containerRef.current.scrollTop = containerRef.current.scrollHeight;
        }
      });
      prevTimelineLengthRef.current = currentTimelineLength;
      return;
    }

    // Loading earlier messages - restore scroll position
    if (hasNewMessages && !isLoading && previousScrollHeightRef.current > 0) {
      restoreScrollPosition();
      prevTimelineLengthRef.current = currentTimelineLength;

      // 隐藏 loading 指示器 - use timeout to avoid sync setState
      if (loadingIndicatorTimeoutRef.current) {
        clearTimeout(loadingIndicatorTimeoutRef.current);
        loadingIndicatorTimeoutRef.current = null;
      }
      // Queue state update to avoid synchronous setState in effect
      setTimeout(() => setShowLoadingIndicator(false), 0);
      return;
    }

    // New messages arriving while streaming or user is at bottom - auto scroll
    if (hasNewMessages) {
      if (isStreaming || isNearBottom(container, 200)) {
        requestAnimationFrame(() => {
          if (containerRef.current) {
            containerRef.current.scrollTop = containerRef.current.scrollHeight;
          }
        });
        // Queue state update to avoid sync setState in effect
        setTimeout(() => setShowScrollButton(false), 0);
      } else {
        // User is scrolled up and new messages arrived - show button
        setTimeout(() => setShowScrollButton(true), 0);
      }
    }

    prevTimelineLengthRef.current = currentTimelineLength;
  }, [timeline.length, isStreaming, isLoading, restoreScrollPosition]);

  // Auto-scroll when streaming content or thought updates (for real-time streaming)
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Always auto-scroll during streaming unless user has explicitly scrolled up
    // This ensures real-time content is always visible
    if (isStreaming && !userScrolledUpRef.current) {
      requestAnimationFrame(() => {
        if (containerRef.current) {
          containerRef.current.scrollTop = containerRef.current.scrollHeight;
        }
      });
    }
  }, [streamingContent, streamingThought, isStreaming]);

  // Reset scroll state when conversation changes
  useEffect(() => {
    // Reset all scroll-related refs when conversationId changes
    isInitialLoadRef.current = true;
    hasScrolledInitiallyRef.current = false;
    prevTimelineLengthRef.current = 0;
    previousScrollHeightRef.current = 0;
    previousScrollTopRef.current = 0;
    isLoadingEarlierRef.current = false;
    userScrolledUpRef.current = false; // Reset user scroll state
    
    // Scroll to bottom after a short delay to ensure rendering is complete
    const timeoutId = setTimeout(() => {
      const container = containerRef.current;
      if (container && timeline.length > 0) {
        container.scrollTop = container.scrollHeight;
        isInitialLoadRef.current = false;
        hasScrolledInitiallyRef.current = true;
        prevTimelineLengthRef.current = timeline.length;
      }
    }, 100);
    
    return () => clearTimeout(timeoutId);
  }, [conversationId]); // Only trigger when conversationId changes

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (loadingIndicatorTimeoutRef.current) {
        clearTimeout(loadingIndicatorTimeoutRef.current);
      }
    };
  }, []);

  // Reset userScrolledUpRef when streaming ends
  useEffect(() => {
    if (!isStreaming) {
      userScrolledUpRef.current = false;
    }
  }, [isStreaming]);

  // Scroll to bottom handler
  const scrollToBottom = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    container.scrollTo({
      top: container.scrollHeight,
      behavior: 'smooth',
    });
    setShowScrollButton(false);
  }, []);

  // Loading state
  if (isLoading && timeline.length === 0) {
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

  // 判断是否应该显示 loading 指示器
  const shouldShowLoading = (propIsLoadingEarlier && hasEarlierMessages) || (showLoadingIndicator && hasEarlierMessages);

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

      {/* Loading indicator for earlier messages - 更加低调的样式 */}
      {shouldShowLoading && (
        <div className="absolute top-2 left-0 right-0 z-10 flex justify-center pointer-events-none">
          <div className="flex items-center px-3 py-1.5 bg-slate-100/90 dark:bg-slate-800/90 backdrop-blur-sm rounded-full shadow-sm border border-slate-200/50 dark:border-slate-700/50 opacity-70">
            <LoadingOutlined className="text-primary mr-2" spin />
            <span className="text-xs text-slate-500">加载中...</span>
          </div>
        </div>
      )}

      {/* Message List */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto chat-scrollbar p-4 md:p-6 pb-24 min-h-0"
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
          {/* Rendered BEFORE streaming content to maintain correct order: thought -> response */}
          {(isThinkingStreaming || streamingThought) && (
            <StreamingThoughtBubble 
              content={streamingThought || ''} 
              isStreaming={!!isThinkingStreaming} 
            />
          )}

          {/* Streaming content indicator - shows text_delta content in real-time */}
          {/* Only show when streaming AND we have content AND NOT thinking (to avoid showing response before thought) */}
          {isStreaming && streamingContent && !isThinkingStreaming && (
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
});

MessageArea.displayName = 'MessageArea';
