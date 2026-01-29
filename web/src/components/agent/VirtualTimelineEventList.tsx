/**
 * VirtualTimelineEventList - Optimized virtualized timeline event list
 *
 * Uses @tanstack/react-virtual with TimelineEventItem for efficient
 * rendering of large conversation histories.
 *
 * Features:
 * - Virtual scrolling for performance
 * - Auto-scroll to bottom during streaming
 * - Manual scroll position preservation
 * - Floating scroll controls
 * - Smooth animations
 *
 * @module components/agent/VirtualTimelineEventList
 */

import React, { useRef, useEffect, useCallback, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Button, Badge } from "antd";
import {
  DownOutlined,
  MessageOutlined,
} from "@ant-design/icons";
import { TimelineEventItem } from "./TimelineEventItem";
import { MessageStream } from "./chat/MessageStream";
import type { TimelineEvent } from "../../types/agent";

interface VirtualTimelineEventListProps {
  /** Timeline events to render */
  timeline: TimelineEvent[];
  /** Whether currently streaming */
  isStreaming?: boolean;
  /** Additional CSS class name */
  className?: string;
  /** Height of the container (default: auto from parent) */
  height?: number;
}

/**
 * Estimate height for a single timeline event
 */
function estimateEventHeight(event: TimelineEvent): number {
  // Base height for any event
  let height = 60;

  switch (event.type) {
    case "user_message":
      height = 70;
      break;
    case "assistant_message":
      height = 100;
      break;
    case "thought":
      height = 100;
      break;
    case "act":
    case "observe":
      height = 180;
      break;
    case "work_plan":
      height = 120 + (event.steps?.length || 0) * 35;
      break;
    case "text_delta":
      height = 50;
      break;
    default:
      height = 60;
  }

  return height;
}

/**
 * Empty State Component
 */
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
        Send a message to begin chatting with the AI agent. You can ask
        questions, request tasks, or plan complex workflows.
      </p>
    </div>
  </div>
);

/**
 * Scroll to Bottom Button
 */
const ScrollToBottomButton: React.FC<{
  onClick: () => void;
  show: boolean;
  hasNewMessages?: boolean;
}> = ({ onClick, show, hasNewMessages }) => {
  if (!show) return null;

  return (
    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-20 animate-fade-in">
      <Button
        type="primary"
        shape="round"
        size="middle"
        icon={<DownOutlined />}
        onClick={onClick}
        className="shadow-lg hover:shadow-xl transition-all flex items-center gap-1 pr-4"
      >
        {hasNewMessages ? "New messages" : "Scroll to bottom"}
      </Button>
    </div>
  );
};

/**
 * VirtualTimelineEventList component
 *
 * @example
 * ```tsx
 * import { VirtualTimelineEventList } from '@/components/agent/VirtualTimelineEventList'
 *
 * function ChatArea({ timeline, isStreaming }) {
 *   return (
 *     <VirtualTimelineEventList
 *       timeline={timeline}
 *       isStreaming={isStreaming}
 *     />
 *   )
 * }
 * ```
 */
export const VirtualTimelineEventList: React.FC<
  VirtualTimelineEventListProps
> = ({
  timeline,
  isStreaming = false,
  className = "",
  height: propHeight,
}) => {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const [hasNewMessages, setHasNewMessages] = useState(false);
  const prevTimelineLength = useRef(timeline.length);

  // Set up virtual row virtualizer
  const estimateEventHeightCallback = useCallback(
    (index: number) => {
      return estimateEventHeight(timeline[index]);
    },
    [timeline]
  );

  const eventVirtualizer = useVirtualizer({
    count: timeline.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: estimateEventHeightCallback,
    overscan: 5,
  });

  // Track user scroll position
  useEffect(() => {
    const scrollContainer = scrollContainerRef.current;
    if (!scrollContainer) return;

    const handleScroll = () => {
      const isNearBottom =
        scrollContainer.scrollHeight -
          scrollContainer.scrollTop -
          scrollContainer.clientHeight <
        150;
      autoScrollRef.current = isNearBottom;
      setShowScrollButton(!isNearBottom && timeline.length > 0);
    };

    scrollContainer.addEventListener("scroll", handleScroll, { passive: true });
    return () => scrollContainer.removeEventListener("scroll", handleScroll);
  }, [timeline.length]);

  // Auto-scroll to bottom when content changes
  useEffect(() => {
    if (!scrollContainerRef.current) return;

    if (autoScrollRef.current || isStreaming) {
      scrollContainerRef.current.scrollTop =
        scrollContainerRef.current.scrollHeight;
    } else if (timeline.length > prevTimelineLength.current) {
      // New messages arrived but user scrolled up
      setHasNewMessages(true);
    }

    prevTimelineLength.current = timeline.length;
  }, [timeline.length, isStreaming]);

  // Scroll to bottom handler
  const scrollToBottom = useCallback(() => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTop =
        scrollContainerRef.current.scrollHeight;
      autoScrollRef.current = true;
      setHasNewMessages(false);
    }
  }, []);

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

  const virtualRows = eventVirtualizer.getVirtualItems();
  const totalSize = eventVirtualizer.getTotalSize();

  return (
    <div className="relative flex-1 overflow-hidden">
      <div
        ref={scrollContainerRef}
        data-testid="virtual-scroll-container"
        className={`h-full overflow-y-auto chat-scrollbar ${className}`}
        style={propHeight ? { height: propHeight } : undefined}
      >
        <div className="py-6 px-4 min-h-full">
          <div className="w-full max-w-4xl mx-auto">
            {/* Message Stream Container */}
            <MessageStream>
              <div
                data-testid="virtual-message-list"
                style={{
                  position: "relative",
                  height: `${totalSize}px`,
                  width: "100%",
                }}
              >
                {virtualRows.map((virtualRow) => {
                  const event = timeline[virtualRow.index];
                  if (!event) return null;

                  return (
                    <div
                      key={virtualRow.key}
                      ref={eventVirtualizer.measureElement}
                      data-index={virtualRow.index}
                      data-testid={`virtual-row-${virtualRow.index}`}
                      style={{
                        position: "absolute",
                        top: 0,
                        left: 0,
                        width: "100%",
                        transform: `translateY(${virtualRow.start}px)`,
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
              <div ref={bottomRef} className="h-4" />
            </MessageStream>
          </div>
        </div>
      </div>

      {/* Scroll to Bottom Button */}
      <ScrollToBottomButton
        onClick={scrollToBottom}
        show={showScrollButton || (hasNewMessages && !isStreaming)}
        hasNewMessages={hasNewMessages}
      />

      {/* Message Count Badge - top right */}
      <div className="absolute top-4 right-4 z-10">
        <Badge
          count={timeline.length}
          showZero={false}
          style={{
            backgroundColor: "#f1f5f9",
            color: "#64748b",
            fontSize: "11px",
            fontWeight: 500,
          }}
        />
      </div>
    </div>
  );
};

VirtualTimelineEventList.displayName = "VirtualTimelineEventList";

export default VirtualTimelineEventList;
