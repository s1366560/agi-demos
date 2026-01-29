/**
 * TimelineEventRenderer - Unified TimelineEvent renderer
 *
 * This component provides a unified interface for rendering TimelineEvents,
 * ensuring consistent behavior between streaming and historical messages.
 *
 * @module components/agent/chat/TimelineEventRenderer
 */

import React, { memo } from 'react';
import { MessageStream } from './MessageStream';
import { TimelineEventItem } from '../TimelineEventItem';
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
 * Each event is rendered independently in timeline mode.
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
  // Empty state
  if (events.length === 0) {
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
      {events.map((event) => (
        <TimelineEventItem
          key={event.id}
          event={event}
          isStreaming={isStreaming}
          allEvents={events}
        />
      ))}
    </MessageStream>
  );
});

TimelineEventRenderer.displayName = 'TimelineEventRenderer';

export default TimelineEventRenderer;
