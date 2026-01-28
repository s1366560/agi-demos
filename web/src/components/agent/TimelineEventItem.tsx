/**
 * TimelineEventItem - Single timeline event renderer
 *
 * Renders individual TimelineEvents in chronological order.
 * This component is used for timeline-mode rendering where each
 * event is displayed independently rather than grouped.
 *
 * @module components/agent/TimelineEventItem
 */

import { memo } from 'react';
import { UserMessage, AgentSection, ToolExecutionCardDisplay } from './chat/MessageStream';
import { AssistantMessage } from './chat/AssistantMessage';
import { ReasoningLogCard } from './chat/MessageStream';
import type { TimelineEvent, ActEvent, ObserveEvent } from '../../types/agent';

export interface TimelineEventItemProps {
  /** The timeline event to render */
  event: TimelineEvent;
  /** Whether currently streaming */
  isStreaming?: boolean;
  /** All timeline events (for looking ahead to find observe events) */
  allEvents?: TimelineEvent[];
}

/**
 * Find matching observe event for an act event
 *
 * Uses execution_id for precise matching with fallback to toolName.
 */
function findMatchingObserve(actEvent: ActEvent, events: TimelineEvent[]): ObserveEvent | undefined {
  const actIndex = events.indexOf(actEvent);

  for (let i = actIndex + 1; i < events.length; i++) {
    const event = events[i];
    if (event.type !== 'observe') continue;

    // Priority 1: Match by execution_id (most precise)
    if (actEvent.execution_id && event.execution_id) {
      if (actEvent.execution_id === event.execution_id) {
        return event;
      }
      // If execution_ids don't match, continue searching
      continue;
    }

    // Priority 2: Fallback to toolName matching (for backward compatibility)
    if (event.toolName === actEvent.toolName) {
      return event;
    }
  }
  return undefined;
}

/**
 * Render thought event
 */
function ThoughtItem({ event, isStreaming }: { event: TimelineEvent; isStreaming: boolean }) {
  if (event.type !== 'thought') return null;

  return (
    <AgentSection icon="psychology" opacity={!isStreaming}>
      <ReasoningLogCard
        steps={[event.content]}
        summary="Thinking..."
        completed={!isStreaming}
        expanded={isStreaming}
      />
    </AgentSection>
  );
}

/**
 * Render act (tool call) event
 */
function ActItem({ event, allEvents }: { event: TimelineEvent; allEvents?: TimelineEvent[] }) {
  if (event.type !== 'act') return null;

  // Look ahead to find matching observe event
  const observeEvent = allEvents ? findMatchingObserve(event, allEvents) : undefined;
  const hasCompleted = !!observeEvent;

  // If completed, show the result inline; otherwise show running state
  if (hasCompleted && observeEvent) {
    // Tool completed - show with result
    return (
      <AgentSection icon="construction" iconBg="bg-slate-200 dark:bg-border-dark" opacity={true}>
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
    );
  }

  // Tool still running
  return (
    <AgentSection icon="construction" iconBg="bg-slate-200 dark:bg-border-dark">
      <ToolExecutionCardDisplay
        toolName={event.toolName}
        status="running"
        parameters={event.toolInput}
        defaultExpanded={true}
      />
    </AgentSection>
  );
}

/**
 * Render observe (tool result) event
 * Only renders if the act event didn't already display the result
 */
function ObserveItem({ event, allEvents }: { event: TimelineEvent; allEvents?: TimelineEvent[] }) {
  if (event.type !== 'observe') return null;

  // Find the matching act event using same logic as findMatchingObserve
  const hasMatchingAct = allEvents ? allEvents.some((e) => {
    if (e.type !== 'act') return false;

    // Priority 1: Match by execution_id
    if ((e as ActEvent).execution_id && event.execution_id) {
      return (e as ActEvent).execution_id === event.execution_id;
    }

    // Priority 2: Fallback to toolName matching
    return e.toolName === event.toolName && e.timestamp < event.timestamp;
  }) : false;

  // Skip if we found a matching act (result will be displayed there)
  if (hasMatchingAct) {
    return null;
  }

  // Orphaned observe event (no matching act) - display it
  return (
    <AgentSection icon="construction" iconBg="bg-slate-200 dark:bg-border-dark" opacity={true}>
      <ToolExecutionCardDisplay
        toolName={event.toolName}
        status={event.isError ? 'error' : 'success'}
        result={event.toolOutput}
        error={event.isError ? event.toolOutput : undefined}
        defaultExpanded={false}
      />
    </AgentSection>
  );
}

/**
 * Render work_plan event
 */
function WorkPlanItem({ event }: { event: TimelineEvent }) {
  if (event.type !== 'work_plan') return null;

  return (
    <AgentSection icon="psychology">
      <ReasoningLogCard
        steps={event.steps.map((s) => s.description)}
        summary={`Work Plan: ${event.steps.length} steps`}
        completed={event.status === 'completed'}
        expanded={event.status !== 'completed'}
      />
    </AgentSection>
  );
}

/**
 * Render step_start event
 * Only renders when there's meaningful step data
 */
function StepStartItem({ event }: { event: TimelineEvent }) {
  if (event.type !== 'step_start') return null;

  const stepDesc = event.stepDescription;

  // Don't render if no meaningful description
  if (!stepDesc || stepDesc.trim() === '') {
    return null;
  }

  const stepIndex = event.stepIndex;

  return (
    <div className="flex items-start gap-4 opacity-70">
      <div className="w-8 h-8 rounded-full bg-amber-100 dark:bg-amber-500/10 flex items-center justify-center shrink-0">
        <span className="material-symbols-outlined text-amber-600 text-sm">play_arrow</span>
      </div>
      <div className="flex-1 text-sm text-slate-600 dark:text-slate-400">
        {stepIndex !== undefined ? `Step ${stepIndex}: ` : ''}{stepDesc}
      </div>
    </div>
  );
}

/**
 * Render text_delta event (typewriter effect)
 */
function TextDeltaItem({ event, isStreaming }: { event: TimelineEvent; isStreaming: boolean }) {
  if (event.type !== 'text_delta') return null;

  return (
    <div className="flex items-start gap-3">
      <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center shrink-0 mt-0.5">
        <span className="material-symbols-outlined text-primary text-lg">smart_toy</span>
      </div>
      <div className={`flex-1 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-2xl rounded-tl-none shadow-sm p-5 prose prose-sm dark:prose-invert max-w-none ${
        isStreaming ? 'typing-cursor' : ''
      }`}>
        {event.content}
      </div>
    </div>
  );
}

/**
 * TimelineEventItem component
 *
 * Renders a single TimelineEvent based on its type.
 *
 * @example
 * ```tsx
 * import { TimelineEventItem } from '@/components/agent/TimelineEventItem'
 *
 * function TimelineView({ timeline }) {
 *   return (
 *     <div>
 *       {timeline.map(event => (
 *         <TimelineEventItem key={event.id} event={event} />
 *       ))}
 *     </div>
 *   )
 * }
 * ```
 */
export const TimelineEventItem: React.FC<TimelineEventItemProps> = memo(({
  event,
  isStreaming = false,
  allEvents,
}) => {
  // Use allEvents if provided, otherwise use single event array
  const events = allEvents ?? [event];

  switch (event.type) {
    case 'user_message':
      return (
        <div className="animate-slide-up">
          <UserMessage content={event.content} />
        </div>
      );

    case 'assistant_message':
      return (
        <div className="mb-6 animate-slide-up">
          <AssistantMessage
            content={event.content}
            isStreaming={isStreaming}
            generatedAt={new Date(event.timestamp).toISOString()}
          />
        </div>
      );

    case 'thought':
      return (
        <div className="mb-6 animate-slide-up">
          <ThoughtItem event={event} isStreaming={isStreaming} />
        </div>
      );

    case 'act':
      return (
        <div className="mb-6 animate-slide-up">
          <ActItem event={event} allEvents={events} />
        </div>
      );

    case 'observe':
      return (
        <div className="mb-6 animate-slide-up">
          <ObserveItem event={event} allEvents={events} />
        </div>
      );

    case 'work_plan':
      return (
        <div className="mb-6 animate-slide-up">
          <WorkPlanItem event={event} />
        </div>
      );

    case 'step_start':
      // Don't render if no meaningful description
      if (!event.stepDescription || event.stepDescription.trim() === '') {
        return null;
      }
      return (
        <div className="animate-slide-up">
          <StepStartItem event={event} />
        </div>
      );

    case 'step_end':
      // step_end doesn't need visual representation in timeline mode
      return null;

    case 'text_delta':
      return (
        <div className="mb-6 animate-slide-up">
          <TextDeltaItem event={event} isStreaming={isStreaming} />
        </div>
      );

    case 'text_start':
    case 'text_end':
      // These are control events, no visual output needed
      return null;

    default:
      // Unknown event type - log for debugging
      console.warn('Unknown event type in TimelineEventItem:', (event as { type: string }).type);
      return null;
  }
});

TimelineEventItem.displayName = 'TimelineEventItem';

export default TimelineEventItem;
