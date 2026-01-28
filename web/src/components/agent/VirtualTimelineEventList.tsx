/**
 * VirtualTimelineEventList - Virtualized timeline event list component
 *
 * Combines @tanstack/react-virtual with TimelineEventRenderer for efficient
 * rendering of large conversation histories while maintaining consistent
 * rendering between streaming and historical messages.
 *
 * @module components/agent/VirtualTimelineEventList
 */

import React, { useRef, useEffect, useCallback, useMemo, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { groupTimelineEvents } from '../../utils/timelineEventAdapter';
import { TimelineEventRenderer } from './chat/TimelineEventRenderer';
import { MessageStream } from './chat/MessageStream';
import type { TimelineEvent } from '../../types/agent';
import type { EventGroup } from '../../utils/timelineEventAdapter';

interface VirtualTimelineEventListProps {
  /** Timeline events to render */
  timeline: TimelineEvent[];
  /** Whether currently streaming */
  isStreaming?: boolean;
  /** Whether to show execution details inline */
  showExecutionDetails?: boolean;
  /** Additional CSS class name */
  className?: string;
  /** Height of the container (default: auto from parent) */
  height?: number;
}

/**
 * Estimate height for an event group
 */
function estimateGroupHeight(group: EventGroup): number {
  // Base height
  let height = 80;

  // Add height for thoughts
  height += group.thoughts.length * 60;

  // Add height for tool calls
  height += group.toolCalls.length * 150;

  // Add height for work plan
  if (group.workPlan && group.workPlan.steps.length > 0) {
    height += group.workPlan.steps.length * 40 + 60;
  }

  // Add height for content
  if (group.content) {
    const lines = group.content.split('\n').length;
    height += Math.max(100, lines * 20);
  }

  return height;
}

/**
 * VirtualTimelineEventList component
 *
 * Uses virtual scrolling to efficiently render large conversation histories.
 * Groups timeline events before rendering for consistent display.
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
export const VirtualTimelineEventList: React.FC<VirtualTimelineEventListProps> = ({
  timeline,
  isStreaming = false,
  showExecutionDetails = true,
  className = '',
  height: propHeight,
}) => {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [containerHeight, setContainerHeight] = useState(propHeight || 600);
  const autoScrollRef = useRef(true);

  // Memoize grouped events to avoid re-computing on every render
  const groupedEvents = useMemo(
    () => groupTimelineEvents(timeline),
    [timeline]
  );

  // Calculate container height on mount and resize
  useEffect(() => {
    if (propHeight) {
      setContainerHeight(propHeight);
      return;
    }

    const updateHeight = () => {
      const parent = scrollContainerRef.current?.parentElement;
      if (parent) {
        const height = parent.clientHeight - 32; // Account for padding
        setContainerHeight(Math.max(height, 200));
      }
    };

    updateHeight();
    window.addEventListener('resize', updateHeight);
    return () => window.removeEventListener('resize', updateHeight);
  }, [propHeight]);

  // Track user scroll position to disable auto-scroll when user scrolls up
  useEffect(() => {
    const scrollContainer = scrollContainerRef.current;
    if (!scrollContainer) return;

    const handleScroll = () => {
      const isNearBottom =
        scrollContainer.scrollHeight - scrollContainer.scrollTop - scrollContainer.clientHeight < 100;
      autoScrollRef.current = isNearBottom;
    };

    scrollContainer.addEventListener('scroll', handleScroll);
    return () => scrollContainer.removeEventListener('scroll', handleScroll);
  }, []);

  // Scroll to bottom when content changes (only if auto-scroll is enabled or streaming)
  useEffect(() => {
    if (!scrollContainerRef.current) return;

    if (autoScrollRef.current || isStreaming) {
      scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
    }
  }, [groupedEvents.length, isStreaming]);

  // Empty state
  if (timeline.length === 0) {
    return (
      <div className={`flex-1 overflow-y-auto p-4 custom-scrollbar ${className}`}>
        <MessageStream className="max-w-4xl mx-auto">
          <div className="flex items-center justify-center h-96">
            <div className="text-center text-slate-500 dark:text-slate-400">
              <span className="material-symbols-outlined text-4xl mb-2">chat</span>
              <p>No messages yet. Start a conversation!</p>
            </div>
          </div>
        </MessageStream>
      </div>
    );
  }

  // Estimate group height for virtual scrolling
  const estimateGroupHeightCallback = useCallback((index: number) => {
    return estimateGroupHeight(groupedEvents[index]);
  }, [groupedEvents]);

  // Set up virtual row virtualizer
  const rowVirtualizer = useVirtualizer({
    count: groupedEvents.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: estimateGroupHeightCallback,
    overscan: 3,
  });

  const virtualRows = rowVirtualizer.getVirtualItems();
  const totalSize = rowVirtualizer.getTotalSize();

  // Render a single event group
  const renderGroup = useCallback((group: EventGroup) => {
    return (
      <TimelineEventRenderer
        events={group.events}
        isStreaming={isStreaming && group.isStreaming}
        showExecutionDetails={showExecutionDetails}
        className=""
      />
    );
  }, [isStreaming, showExecutionDetails]);

  return (
    <div className={`flex-1 overflow-y-auto p-4 custom-scrollbar ${className}`}>
      <MessageStream className="max-w-4xl mx-auto">
        <div
          ref={scrollContainerRef}
          data-testid="virtual-scroll-container"
          className="overflow-auto"
          style={{ height: `${containerHeight}px` }}
        >
          <div
            data-testid="virtual-message-list"
            style={{
              position: 'relative',
              height: `${totalSize}px`,
              width: '100%',
            }}
          >
            {virtualRows.map((virtualRow) => {
              const group = groupedEvents[virtualRow.index];
              if (!group) return null;

              return (
                <div
                  key={virtualRow.key}
                  data-testid={`virtual-row-${virtualRow.index}`}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                >
                  {renderGroup(group)}
                </div>
              );
            })}
          </div>
        </div>
        <div ref={bottomRef} />
      </MessageStream>
    </div>
  );
};

VirtualTimelineEventList.displayName = 'VirtualTimelineEventList';

export default VirtualTimelineEventList;
