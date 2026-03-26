/**
 * ToolItems - Act and Observe timeline event rendering with status tracking
 */

import { memo } from 'react';

import { AgentSection, ToolExecutionCardDisplay } from '../chat/MessageStream';

import { isAgentTool, AgentToolCard } from './AgentToolCards';
import { TimeBadge } from './shared';

import type { ActEvent, ObserveEvent, TimelineEvent } from '../../../types/agent';

/**
 * Find matching observe event for an act event
 */
// eslint-disable-next-line react-refresh/only-export-components
export function findMatchingObserve(
  actEvent: ActEvent,
  events: TimelineEvent[]
): ObserveEvent | undefined {
  const actIndex = events.indexOf(actEvent);

  for (let i = actIndex + 1; i < events.length; i++) {
    const event = events[i];
    if (!event) continue;
    if (event.type !== 'observe') continue;

    // Priority 1: Match by execution_id
    if (actEvent.execution_id && event.execution_id) {
      if (actEvent.execution_id === event.execution_id) {
        return event;
      }
      continue;
    }

    // Priority 2: Fallback to toolName matching
    if (event.toolName === actEvent.toolName) {
      return event;
    }
  }
  return undefined;
}

interface ActItemProps {
  event: TimelineEvent;
  allEvents?: TimelineEvent[] | undefined;
}

export const ActItem = memo(
  function ActItem({ event, allEvents }: ActItemProps) {
    if (event.type !== 'act') return null;

    const observeEvent = allEvents ? findMatchingObserve(event, allEvents) : undefined;

    if (isAgentTool(event.toolName)) {
      return <AgentToolCard event={event} observeEvent={observeEvent} />;
    }

    const ToolCard = observeEvent ? (
      <AgentSection icon="construction" iconBg="bg-slate-100 dark:bg-slate-800" opacity={true}>
        <ToolExecutionCardDisplay
          toolName={event.toolName}
          status={observeEvent.isError ? 'error' : 'success'}
          parameters={event.toolInput}
          result={observeEvent.isError ? undefined : observeEvent.toolOutput}
          error={observeEvent.isError ? observeEvent.toolOutput : undefined}
          duration={observeEvent.timestamp - event.timestamp}
          defaultExpanded={false}
        />
      </AgentSection>
    ) : (
      <AgentSection icon="construction" iconBg="bg-slate-100 dark:bg-slate-800">
        <ToolExecutionCardDisplay
          toolName={event.toolName}
          status="running"
          parameters={event.toolInput}
          defaultExpanded={true}
        />
      </AgentSection>
    );

    return (
      <div className="flex flex-col gap-1">
        {ToolCard}
        <div className="pl-12">
          <TimeBadge timestamp={event.timestamp} />
        </div>
      </div>
    );
  },
  (prev, next) => {
    return (
      prev.event.id === next.event.id &&
      prev.event.type === next.event.type &&
      prev.event.timestamp === next.event.timestamp &&
      (prev.event.type === 'act' && next.event.type === 'act'
        ? prev.event.execution_id === next.event.execution_id
        : true) &&
      prev.allEvents === next.allEvents
    );
  }
);

interface ObserveItemProps {
  event: TimelineEvent;
  allEvents?: TimelineEvent[] | undefined;
}

export const ObserveItem = memo(
  function ObserveItem({ event, allEvents }: ObserveItemProps) {
    if (event.type !== 'observe') return null;

    const hasMatchingAct = allEvents
      ? allEvents.some((e) => {
          if (e.type !== 'act') return false;
          if (e.execution_id && event.execution_id) {
            return e.execution_id === event.execution_id;
          }
          return e.toolName === event.toolName && e.timestamp < event.timestamp;
        })
      : false;

    if (hasMatchingAct) {
      return null;
    }

    return (
      <div className="flex flex-col gap-1">
        <AgentSection icon="construction" iconBg="bg-slate-100 dark:bg-slate-800" opacity={true}>
          <ToolExecutionCardDisplay
            toolName={event.toolName}
            status={event.isError ? 'error' : 'success'}
            result={event.toolOutput}
            error={event.isError ? event.toolOutput : undefined}
            defaultExpanded={false}
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
      prev.event.type === next.event.type &&
      prev.event.timestamp === next.event.timestamp &&
      (prev.event.type === 'observe' && next.event.type === 'observe'
        ? prev.event.execution_id === next.event.execution_id
        : true) &&
      prev.allEvents === next.allEvents
    );
  }
);
