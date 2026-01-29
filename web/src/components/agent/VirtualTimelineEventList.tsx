/**
 * VirtualTimelineEventList - Virtualized timeline event list component
 *
 * Uses @tanstack/react-virtual with TimelineEventItem for efficient
 * rendering of large conversation histories.
 *
 * Renders events in timeline mode - each event is displayed independently
 * in chronological order for maximum clarity.
 *
 * @module components/agent/VirtualTimelineEventList
 */

import React, { useRef, useEffect, useCallback } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { TimelineEventItem } from './TimelineEventItem';
import { MessageStream } from './chat/MessageStream';
import type { TimelineEvent } from '../../types/agent';

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
        case 'user_message':
        case 'assistant_message':
            height = 80;
            break;
        case 'thought':
            height = 120;
            break;
        case 'act':
        case 'observe':
            height = 200;
            break;
        case 'work_plan':
            height = 150 + (event.steps?.length || 0) * 40;
            break;
        case 'text_delta':
            height = 60;
            break;
        default:
            height = 60;
    }

    return height;
}

/**
 * VirtualTimelineEventList component
 *
 * Uses virtual scrolling to efficiently render large conversation histories.
 * Each event is rendered independently in chronological timeline order.
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
    className = '',
    height: propHeight,
}) => {
    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const bottomRef = useRef<HTMLDivElement>(null);
    const autoScrollRef = useRef(true);

    // Set up virtual row virtualizer - MUST be before any early return
    // (Hooks must be called in consistent order on every render)
    const estimateEventHeightCallback = useCallback((index: number) => {
        return estimateEventHeight(timeline[index]);
    }, [timeline]);

    const eventVirtualizer = useVirtualizer({
        count: timeline.length,
        getScrollElement: () => scrollContainerRef.current,
        estimateSize: estimateEventHeightCallback,
        overscan: 3,
    });

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
    }, [timeline.length, isStreaming]);

    // Empty state
    if (timeline.length === 0) {
        return (
            <div className={`flex-1 overflow-y-auto p-6 chat-messages ${className}`}>
                <MessageStream className="w-full max-w-3xl lg:max-w-5xl xl:max-w-7xl mx-auto">
                    <div className="flex items-center justify-center min-h-[400px]">
                        <div className="text-center">
                            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-primary/10 to-primary/5 flex items-center justify-center">
                                <span className="material-symbols-outlined text-3xl text-primary">chat_bubble</span>
                            </div>
                            <h3 className="text-slate-700 font-medium mb-2">Start a conversation</h3>
                            <p className="text-slate-400 text-sm max-w-xs mx-auto">
                                Send a message to begin chatting with the AI agent.
                            </p>
                        </div>
                    </div>
                </MessageStream>
            </div>
        );
    }

    const virtualRows = eventVirtualizer.getVirtualItems();
    const totalSize = eventVirtualizer.getTotalSize();

    return (
        <div
            ref={scrollContainerRef}
            data-testid="virtual-scroll-container"
            className={`flex-1 overflow-y-auto chat-messages chat-scrollbar ${className}`}
            style={propHeight ? { height: propHeight } : undefined}
        >
            <div className="p-6 min-h-full">
                <MessageStream className="w-full max-w-3xl lg:max-w-5xl xl:max-w-7xl mx-auto">
                    <div
                        data-testid="virtual-message-list"
                        style={{
                            position: 'relative',
                            height: `${totalSize}px`,
                            width: '100%',
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
                                        position: 'absolute',
                                        top: 0,
                                        left: 0,
                                        width: '100%',
                                        transform: `translateY(${virtualRow.start}px)`,
                                    }}
                                >
                                    <TimelineEventItem event={event} isStreaming={isStreaming} allEvents={timeline} />
                                </div>
                            );
                        })}
                    </div>
                    <div ref={bottomRef} />
                </MessageStream>
            </div>
        </div>
    );
};

VirtualTimelineEventList.displayName = 'VirtualTimelineEventList';

export default VirtualTimelineEventList;
