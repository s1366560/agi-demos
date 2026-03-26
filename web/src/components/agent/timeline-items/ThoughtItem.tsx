/**
 * ThoughtItem - Render thought (reasoning) timeline events
 */

import { memo } from 'react';

import { AgentSection, ReasoningLogCard } from '../chat/MessageStream';

import { TimeBadge } from './shared';

import type { TimelineEvent } from '../../../types/agent';

interface ThoughtItemProps {
  event: TimelineEvent;
  isStreaming: boolean;
}

export const ThoughtItem = memo(
  function ThoughtItem({ event, isStreaming }: ThoughtItemProps) {
    if (event.type !== 'thought') return null;

    return (
      <div className="flex flex-col gap-1">
        <AgentSection icon="psychology" opacity={!isStreaming}>
          <ReasoningLogCard
            steps={[event.content]}
            summary="Thinking..."
            completed={!isStreaming}
            expanded={isStreaming}
          />
        </AgentSection>
        <div className="pl-12">
          <TimeBadge timestamp={event.timestamp} />
        </div>
      </div>
    );
  },
  (prev, next) => {
    return (
      prev.event.id === next.event.id &&
      prev.isStreaming === next.isStreaming &&
      (prev.event.type === 'thought' && next.event.type === 'thought'
        ? prev.event.content === next.event.content
        : prev.event.type === next.event.type)
    );
  }
);
