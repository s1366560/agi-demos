/**
 * VirtualTimelineEventList - Virtualized timeline event list component
 *
 * Combines @tanstack/react-virtual with TimelineEventRenderer for efficient
 * rendering of large conversation histories while maintaining consistent
 * rendering between streaming and historical messages.
 *
 * Supports two rendering modes:
 * - 'grouped': Events are grouped into user/assistant groups (default)
 * - 'timeline': Each event is rendered independently in chronological order
 *
 * @module components/agent/VirtualTimelineEventList
 */

import React, { useRef, useEffect, useCallback, useMemo } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { groupTimelineEvents } from '../../utils/timelineEventAdapter';
import { TimelineEventRenderer } from './chat/TimelineEventRenderer';
import { TimelineEventItem } from './TimelineEventItem';
import { MessageStream } from './chat/MessageStream';
import type { TimelineEvent } from '../../types/agent';
import type { EventGroup } from '../../utils/timelineEventAdapter';

export type RenderMode = 'grouped' | 'timeline';

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
    /** Rendering mode: 'grouped' or 'timeline' */
    renderMode?: RenderMode;
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
    renderMode = 'grouped',
}) => {
    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const bottomRef = useRef<HTMLDivElement>(null);
    const autoScrollRef = useRef(true);

    // Memoize grouped events to avoid re-computing on every render
    const groupedEvents = useMemo(
        () => groupTimelineEvents(timeline),
        [timeline]
    );

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
    }, [renderMode === 'grouped' ? groupedEvents.length : timeline.length, isStreaming, renderMode]);

    // Timeline mode: direct event rendering
    if (renderMode === 'timeline') {
        const estimateEventHeightCallback = useCallback((index: number) => {
            return estimateEventHeight(timeline[index]);
        }, [timeline]);

        const eventVirtualizer = useVirtualizer({
            count: timeline.length,
            getScrollElement: () => scrollContainerRef.current,
            estimateSize: estimateEventHeightCallback,
            overscan: 3,
        });

        const virtualRows = eventVirtualizer.getVirtualItems();
        const totalSize = eventVirtualizer.getTotalSize();

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
    }

    // Grouped mode: event group rendering (default)
    const estimateGroupHeightCallback = useCallback((index: number) => {
        return estimateGroupHeight(groupedEvents[index]);
    }, [groupedEvents]);

    // Set up virtual row virtualizer (must be called before early return)
    const rowVirtualizer = useVirtualizer({
        count: groupedEvents.length,
        getScrollElement: () => scrollContainerRef.current,
        estimateSize: estimateGroupHeightCallback,
        overscan: 3,
    });

    // Render callback (must be called before early return)
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

    const virtualRows = rowVirtualizer.getVirtualItems();
    const totalSize = rowVirtualizer.getTotalSize();

    // Empty state with improved styling
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
                            const group = groupedEvents[virtualRow.index];
                            if (!group) return null;

                            return (
                                <div
                                    key={virtualRow.key}
                                    ref={rowVirtualizer.measureElement}
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
                                    {renderGroup(group)}
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
