/**
 * VirtualTimelineEventList - Optimized virtualized timeline event list
 *
 * Features:
 * - Virtual scrolling for performance with large conversation histories
 * - Aggressive preloading for seamless backward pagination (用户几乎感知不到加载)
 * - Auto-scroll to bottom for new messages
 * - Scroll position restoration after loading earlier messages
 * - No scroll jumping or flickering during pagination
 */

import React, { useRef, useEffect, useCallback, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Button, Spin } from "antd";
import { DownOutlined, MessageOutlined } from "@ant-design/icons";
import { TimelineEventItem } from "./TimelineEventItem";
import { MessageStream } from "./chat/MessageStream";
import type { TimelineEvent } from "../../types/agent";

interface VirtualTimelineEventListProps {
  timeline: TimelineEvent[];
  isStreaming?: boolean;
  className?: string;
  height?: number;
  // Pagination props
  hasEarlierMessages?: boolean;
  isLoadingEarlier?: boolean;
  onLoadEarlier?: () => void;
  // Preload configuration
  preloadThreshold?: number; // Number of items before end to trigger preload
  // Conversation ID for scroll reset on conversation change
  conversationId?: string | null;
}

function estimateEventHeight(event: TimelineEvent): number {
  switch (event.type) {
    case "user_message":
      return 70;
    case "assistant_message":
      return 100;
    case "thought":
      return 100;
    case "act":
    case "observe":
      return 180;
    case "work_plan":
      return 120 + (event.steps?.length || 0) * 35;
    case "text_delta":
      return 50;
    default:
      return 60;
  }
}

const EmptyState: React.FC = () => (
  <div className="flex items-center justify-center min-h-[400px]">
    <div className="text-center">
      <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-primary/10 to-primary/5 flex items-center justify-center shadow-sm">
        <MessageOutlined className="text-2xl text-primary" />
      </div>
      <h3 className="text-slate-700 font-medium mb-2 text-lg">
        Start a conversation
      </h3>
      <p className="text-slate-400 text-sm max-w-xs mx-auto leading-relaxed">
        Send a message to begin chatting with the AI agent.
      </p>
    </div>
  </div>
);

const ScrollToBottomButton: React.FC<{
  onClick: () => void;
  show: boolean;
}> = ({ onClick, show }) => {
  if (!show) return null;

  return (
    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-20 animate-fade-in">
      <Button
        type="primary"
        shape="round"
        size="middle"
        icon={<DownOutlined />}
        onClick={onClick}
        className="shadow-lg hover:shadow-xl transition-all"
      >
        Scroll to bottom
      </Button>
    </div>
  );
};

// Check if scroll is near bottom
const isNearBottom = (element: HTMLElement, threshold = 100): boolean => {
  const { scrollHeight, scrollTop, clientHeight } = element;
  return scrollHeight - scrollTop - clientHeight < threshold;
};

export const VirtualTimelineEventList: React.FC<
  VirtualTimelineEventListProps
> = ({
  timeline,
  isStreaming = false,
  className = "",
  height: propHeight,
  hasEarlierMessages = false,
  isLoadingEarlier = false,
  onLoadEarlier,
  preloadThreshold = 8, // 当用户看到前8条消息时就开始加载更多
  conversationId,
}) => {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const [showLoadingIndicator, setShowLoadingIndicator] = useState(false);
  
  // Pagination state refs
  const isLoadingEarlierRef = useRef(false);
  const previousTimelineLengthRef = useRef(0);
  const firstVisibleItemIndexRef = useRef(0);
  const firstVisibleItemOffsetRef = useRef(0);
  const isInitialLoadRef = useRef(true);
  const hasScrolledInitiallyRef = useRef(false);
  const loadingIndicatorTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const lastLoadTimeRef = useRef(0);
  
  // Virtual list setup - 增加 overscan 预渲染更多项目
  const estimateEventHeightCallback = useCallback(
    (index: number) => estimateEventHeight(timeline[index]),
    [timeline]
  );

  const eventVirtualizer = useVirtualizer({
    count: timeline.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: estimateEventHeightCallback,
    overscan: 10, // 增加预渲染数量，让滚动更平滑
    scrollPaddingEnd: 0,
  });

  const virtualItems = eventVirtualizer.getVirtualItems();
  const totalHeight = eventVirtualizer.getTotalSize();

  // Save current scroll state for pagination
  const saveScrollState = useCallback(() => {
    if (virtualItems.length > 0) {
      const firstItem = virtualItems[0];
      firstVisibleItemIndexRef.current = firstItem.index;
      firstVisibleItemOffsetRef.current = firstItem.start - (scrollContainerRef.current?.scrollTop || 0);
    }
  }, [virtualItems]);

  // Restore scroll position after loading earlier messages
  const restoreScrollPosition = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const previousLength = previousTimelineLengthRef.current;
    const currentLength = timeline.length;
    const itemsAdded = currentLength - previousLength;

    if (itemsAdded <= 0) return;

    // Calculate the new scroll position
    const newScrollTop = eventVirtualizer.getOffsetForIndex(itemsAdded)?.[0] || 0;
    const targetScrollTop = newScrollTop + firstVisibleItemOffsetRef.current;

    // Use requestAnimationFrame to ensure DOM has updated
    requestAnimationFrame(() => {
      container.scrollTop = targetScrollTop;
      
      // Reset refs
      firstVisibleItemIndexRef.current = 0;
      firstVisibleItemOffsetRef.current = 0;
    });
  }, [timeline.length, eventVirtualizer]);

  // 核心优化：激进的预加载逻辑
  const checkAndPreload = useCallback(() => {
    if (
      !isLoadingEarlierRef.current &&
      !isLoadingEarlier &&
      hasEarlierMessages &&
      onLoadEarlier &&
      virtualItems.length > 0
    ) {
      const firstVisibleIndex = virtualItems[0].index;
      
      // 当第一个可见项目索引小于阈值时，触发预加载
      // 这意味着用户还没滚动到顶部，但已经"接近"顶部了
      if (firstVisibleIndex < preloadThreshold) {
        // 防抖动：确保两次加载之间至少有 300ms 间隔
        const now = Date.now();
        if (now - lastLoadTimeRef.current < 300) return;
        
        // Save current scroll state before loading
        saveScrollState();
        previousTimelineLengthRef.current = timeline.length;
        
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
  }, [virtualItems, isLoadingEarlier, hasEarlierMessages, onLoadEarlier, timeline.length, preloadThreshold, saveScrollState]);

  // Handle scroll events
  const handleScroll = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    // 检查是否需要预加载
    checkAndPreload();

    // Update button visibility based on scroll position
    const nearBottom = isNearBottom(container, 150);
    setShowScrollButton(!nearBottom && timeline.length > 0);
  }, [timeline.length, checkAndPreload]);

  // Initial scroll to bottom on first load
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    // Only scroll on initial load when we first get messages
    if (timeline.length > 0 && isInitialLoadRef.current && !hasScrolledInitiallyRef.current) {
      hasScrolledInitiallyRef.current = true;
      isInitialLoadRef.current = false;
      
      // Scroll to bottom after a short delay to ensure rendering is complete
      requestAnimationFrame(() => {
        eventVirtualizer.scrollToIndex(timeline.length - 1, { align: 'end' });
      });
    }
  }, [timeline.length, eventVirtualizer]);

  // Handle timeline changes - restore scroll position after loading earlier messages
  useEffect(() => {
    const previousLength = previousTimelineLengthRef.current;
    const currentLength = timeline.length;

    // If we loaded earlier messages (timeline grew from the beginning)
    if (currentLength > previousLength && previousLength > 0 && !isLoadingEarlier) {
      restoreScrollPosition();
      previousTimelineLengthRef.current = currentLength;
      
      // 隐藏 loading 指示器
      setShowLoadingIndicator(false);
      if (loadingIndicatorTimeoutRef.current) {
        clearTimeout(loadingIndicatorTimeoutRef.current);
        loadingIndicatorTimeoutRef.current = null;
      }
    } else if (currentLength !== previousLength) {
      // Update the ref for next comparison
      previousTimelineLengthRef.current = currentLength;
    }
  }, [timeline.length, isLoadingEarlier, restoreScrollPosition]);

  // Auto-scroll to bottom when streaming new messages (only if user is near bottom)
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const previousLength = previousTimelineLengthRef.current;
    const currentLength = timeline.length;

    // Check if new messages were added at the end
    if (currentLength > previousLength) {
      // Only auto-scroll if streaming or user is near bottom
      if (isStreaming || isNearBottom(container, 200)) {
        requestAnimationFrame(() => {
          eventVirtualizer.scrollToIndex(currentLength - 1, { align: 'end' });
        });
        setShowScrollButton(false);
      } else {
        // User is scrolled up - show the scroll button
        setShowScrollButton(true);
      }
    }
  }, [timeline.length, isStreaming, eventVirtualizer]);

  // Reset scroll state when conversation changes
  useEffect(() => {
    // Reset all scroll-related refs when conversationId changes
    isInitialLoadRef.current = true;
    hasScrolledInitiallyRef.current = false;
    previousTimelineLengthRef.current = 0;
    isLoadingEarlierRef.current = false;
    firstVisibleItemIndexRef.current = 0;
    firstVisibleItemOffsetRef.current = 0;
    
    // Scroll to bottom after a short delay to ensure rendering is complete
    const timeoutId = setTimeout(() => {
      if (timeline.length > 0) {
        eventVirtualizer.scrollToIndex(timeline.length - 1, { align: 'end' });
        isInitialLoadRef.current = false;
        hasScrolledInitiallyRef.current = true;
        previousTimelineLengthRef.current = timeline.length;
      }
    }, 100);
    
    return () => clearTimeout(timeoutId);
  }, [conversationId, eventVirtualizer]); // Only trigger when conversationId changes

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (loadingIndicatorTimeoutRef.current) {
        clearTimeout(loadingIndicatorTimeoutRef.current);
      }
    };
  }, []);

  // Scroll to bottom handler
  const scrollToBottom = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    eventVirtualizer.scrollToIndex(timeline.length - 1, { 
      align: 'end',
      behavior: 'smooth'
    });
    setShowScrollButton(false);
  }, [timeline.length, eventVirtualizer]);

  // Empty state
  if (timeline.length === 0) {
    return (
      <div
        className={`flex-1 overflow-y-auto p-6 chat-scrollbar ${className}`}
        ref={scrollContainerRef}
      >
        <div className="w-full max-w-4xl mx-auto">
          <EmptyState />
        </div>
      </div>
    );
  }

  // 判断是否应该显示 loading 指示器
  const shouldShowLoading = (isLoadingEarlier || showLoadingIndicator) && hasEarlierMessages;

  return (
    <div className="relative flex-1 overflow-hidden">
      {/* Loading indicator for earlier messages - 更加低调的样式 */}
      {shouldShowLoading && (
        <div className="absolute top-2 left-0 right-0 z-10 flex justify-center pointer-events-none">
          <div className="flex items-center px-3 py-1.5 bg-slate-100/90 dark:bg-slate-800/90 backdrop-blur-sm rounded-full shadow-sm border border-slate-200/50 dark:border-slate-700/50 opacity-70">
            <Spin size="small" />
            <span className="ml-2 text-xs text-slate-500">加载中...</span>
          </div>
        </div>
      )}

      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        data-testid="virtual-scroll-container"
        className={`h-full overflow-y-auto chat-scrollbar ${className}`}
        style={propHeight ? { height: propHeight } : undefined}
      >
        <div className="py-6 px-4 min-h-full">
          <div className="w-full max-w-4xl mx-auto">
            <MessageStream>
              <div
                data-testid="virtual-message-list"
                style={{
                  position: "relative",
                  height: `${totalHeight}px`,
                  width: "100%",
                }}
              >
                {virtualItems.map((virtualItem) => {
                  const event = timeline[virtualItem.index];
                  if (!event) return null;

                  return (
                    <div
                      key={virtualItem.key}
                      ref={eventVirtualizer.measureElement}
                      data-index={virtualItem.index}
                      style={{
                        position: "absolute",
                        top: 0,
                        left: 0,
                        width: "100%",
                        transform: `translateY(${virtualItem.start}px)`,
                        // Use content-visibility for off-screen items (rendering-content-visibility)
                        contentVisibility: virtualItem.index >= virtualItems[0].index && virtualItem.index <= virtualItems[virtualItems.length - 1].index ? 'visible' : 'auto',
                      }}
                    >
                      <TimelineEventItem
                        event={event}
                        isStreaming={isStreaming}
                        allEvents={timeline}
                      />
                    </div>
                  );
                })}
              </div>
            </MessageStream>
          </div>
        </div>
      </div>

      {/* Scroll to Bottom Button */}
      <ScrollToBottomButton
        onClick={scrollToBottom}
        show={showScrollButton}
      />
    </div>
  );
};

VirtualTimelineEventList.displayName = "VirtualTimelineEventList";

export default VirtualTimelineEventList;
