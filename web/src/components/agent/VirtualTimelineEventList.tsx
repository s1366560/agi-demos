/**
 * VirtualTimelineEventList - Optimized virtualized timeline event list
 */

import React, { useRef, useEffect, useCallback, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Button } from "antd";
import { DownOutlined, MessageOutlined } from "@ant-design/icons";
import { TimelineEventItem } from "./TimelineEventItem";
import { MessageStream } from "./chat/MessageStream";
import type { TimelineEvent } from "../../types/agent";

interface VirtualTimelineEventListProps {
  timeline: TimelineEvent[];
  isStreaming?: boolean;
  className?: string;
  height?: number;
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
}) => {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const prevTimelineLengthRef = useRef(timeline.length);
  const isUserScrollingRef = useRef(false);
  const scrollTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Virtual list setup
  const estimateEventHeightCallback = useCallback(
    (index: number) => estimateEventHeight(timeline[index]),
    [timeline]
  );

  const eventVirtualizer = useVirtualizer({
    count: timeline.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: estimateEventHeightCallback,
    overscan: 5,
  });

  // Handle scroll events
  const handleScroll = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    // Mark that user is scrolling
    isUserScrollingRef.current = true;

    // Clear existing timeout
    if (scrollTimeoutRef.current) {
      clearTimeout(scrollTimeoutRef.current);
    }

    // Set new timeout to detect when scrolling stops
    scrollTimeoutRef.current = setTimeout(() => {
      isUserScrollingRef.current = false;
    }, 150);

    // Update button visibility based on scroll position
    const nearBottom = isNearBottom(container, 100);
    setShowScrollButton(!nearBottom && timeline.length > 0);
  }, [timeline.length]);

  // Auto-scroll to bottom when new messages arrive (only if already near bottom)
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const hasNewMessages = timeline.length > prevTimelineLengthRef.current;
    prevTimelineLengthRef.current = timeline.length;

    if (!hasNewMessages) return;

    // If streaming or user is near bottom, auto scroll
    if (isStreaming || isNearBottom(container, 200)) {
      // Use requestAnimationFrame for smoother scroll
      requestAnimationFrame(() => {
        container.scrollTop = container.scrollHeight;
      });
      setShowScrollButton(false);
    } else {
      // User is scrolled up and new messages arrived - show button
      setShowScrollButton(true);
    }
  }, [timeline.length, isStreaming]);

  // Initial scroll to bottom
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    
    // Only scroll on initial load if there are messages
    if (timeline.length > 0 && prevTimelineLengthRef.current === 0) {
      container.scrollTop = container.scrollHeight;
    }
  }, []);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (scrollTimeoutRef.current) {
        clearTimeout(scrollTimeoutRef.current);
      }
    };
  }, []);

  // Scroll to bottom handler
  const scrollToBottom = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    container.scrollTo({
      top: container.scrollHeight,
      behavior: 'smooth',
    });
    setShowScrollButton(false);
  }, []);

  const virtualItems = eventVirtualizer.getVirtualItems();
  const totalHeight = eventVirtualizer.getTotalSize();

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

  return (
    <div className="relative flex-1 overflow-hidden">
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
