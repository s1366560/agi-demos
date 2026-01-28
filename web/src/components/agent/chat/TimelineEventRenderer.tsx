/**
 * TimelineEventRenderer - Unified TimelineEvent renderer
 *
 * This component provides a unified interface for rendering TimelineEvents,
 * ensuring consistent behavior between streaming and historical messages.
 *
 * @module components/agent/chat/TimelineEventRenderer
 */

import React, { useMemo, memo } from 'react';
import { MessageStream } from './MessageStream';
import { TimelineEventGroup } from './TimelineEventGroup';
import { groupTimelineEvents } from '../../../utils/timelineEventAdapter';
import type { TimelineEvent } from '../../../types/agent';

interface TimelineEventRendererProps {
  /** Timeline events to render */
  events: TimelineEvent[];
  /** Whether currently streaming (affects live updates) */
  isStreaming?: boolean;
  /** Whether to show execution details inline */
  showExecutionDetails?: boolean;
  /** Additional CSS class name */
  className?: string;
}

/**
 * TimelineEventRenderer component
 *
 * Renders TimelineEvents in a consistent unified format.
 * Uses groupTimelineEvents to convert events into renderable groups.
 *
 * @example
 * ```tsx
 * import { TimelineEventRenderer } from '@/components/agent/chat/TimelineEventRenderer'
 *
 * function ChatArea({ timeline, isStreaming }) {
 *   return (
 *     <TimelineEventRenderer
 *       events={timeline}
 *       isStreaming={isStreaming}
 *     />
 *   )
 * }
 * ```
 */
export const TimelineEventRenderer: React.FC<TimelineEventRendererProps> = memo(({
  events,
  isStreaming = false,
  showExecutionDetails: _showExecutionDetails = true,
  className = '',
}) => {
  // Memoize grouping to avoid re-computing on every render
  const groups = useMemo(
    () => groupTimelineEvents(events),
    [events]
  );

  // Empty state
  if (groups.length === 0) {
    return (
      <MessageStream className={className}>
        <div className="flex items-center justify-center h-96">
          <div className="text-center text-slate-500 dark:text-slate-400">
            <span className="material-symbols-outlined text-4xl mb-2">chat</span>
            <p>No messages yet. Start a conversation!</p>
          </div>
        </div>
      </MessageStream>
    );
  }

  return (
    <MessageStream className={className}>
      {groups.map((group) => (
        <TimelineEventGroup
          key={group.id}
          group={group}
          isStreaming={isStreaming}
        />
      ))}
    </MessageStream>
  );
});

TimelineEventRenderer.displayName = 'TimelineEventRenderer';

export default TimelineEventRenderer;
