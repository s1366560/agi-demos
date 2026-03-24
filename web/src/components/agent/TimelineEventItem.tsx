/**
 * TimelineEventItem - Thin orchestrator for timeline event rendering
 *
 * Dispatches each TimelineEvent to the appropriate sub-component
 * from ./timeline-items/. User and assistant message cases are
 * rendered inline since they depend on external chat components.
 *
 * @module components/agent/TimelineEventItem
 */

import { memo, useMemo } from 'react';

import { AgentMessageIndicator } from './chat/AgentMessageIndicator';
import { AssistantMessage } from './chat/AssistantMessage';
import { UserMessage } from './chat/MessageStream';
import { SubAgentDelegationIndicator } from './chat/SubAgentDelegationIndicator';
import {
  TimeBadge,
  ThoughtItem,
  ActItem,
  ObserveItem,
  WorkPlanItem,
  TextDeltaItem,
  TextEndItem,
  ClarificationAskedItem,
  DecisionAskedItem,
  EnvVarRequestedItem,
  ArtifactCreatedItem,
  TaskStartItem,
  TaskCompleteItem,
} from './timeline-items';

import type { ArtifactCreatedEvent, TimelineEvent } from '../../types/agent';

export interface TimelineEventItemProps {
  /** The timeline event to render */
  event: TimelineEvent;
  /** Whether currently streaming */
  isStreaming?: boolean | undefined;
  /** All timeline events (for looking ahead to find observe events) */
  allEvents?: TimelineEvent[] | undefined;
  /** Index of the event in the timeline for staggered animations */
  index?: number;
}

export const TimelineEventItem: React.FC<TimelineEventItemProps> = memo(
  ({ event, isStreaming = false, allEvents, index }) => {
    // Memoize events array to prevent unnecessary recalculations
    const events = useMemo(() => allEvents ?? [event], [allEvents, event]);
    const delayStyle = { animationDelay: `${String(Math.min(index ?? 0, 5) * 50)}ms` };

    // Pre-compute text_end existence to avoid O(n) check per text_delta event
    const hasTextEnd = useMemo(
      () => events.some((e) => e.type === 'text_end'),
      [events]
    );

    switch (event.type) {
      case 'user_message':
        return (
          <div className="my-4 animate-slide-up" style={delayStyle}>
            <div className="flex items-start justify-end gap-3">
              <div className="flex flex-col items-end gap-1 max-w-[80%]">
                <UserMessage
                  content={event.content}
                  forcedSkillName={event.metadata?.forcedSkillName as string | undefined}
                  fileMetadata={
                    event.metadata?.fileMetadata as
                      | Array<{
                          filename: string;
                          sandbox_path?: string | undefined;
                          mime_type: string;
                          size_bytes: number;
                        }>
                      | undefined
                  }
                />
                <TimeBadge timestamp={event.timestamp} />
              </div>
            </div>
          </div>
        );

      case 'assistant_message':
        return (
          <div className="my-4 animate-slide-up" style={delayStyle}>
            <div className="flex items-start gap-3">
              <div className="flex flex-col gap-1 flex-1">
                <AssistantMessage
                  content={event.content}
                  isStreaming={isStreaming}
                  generatedAt={new Date(event.timestamp).toISOString()}
                />
                <div className="pl-11">
                  <TimeBadge timestamp={event.timestamp} />
                </div>
              </div>
            </div>
          </div>
        );

      case 'thought':
        return (
          <div className="my-3 animate-slide-up" style={delayStyle}>
            <ThoughtItem event={event} isStreaming={isStreaming} />
          </div>
        );

      case 'act':
        return (
          <div className="my-3 animate-slide-up" style={delayStyle}>
            <ActItem event={event} allEvents={events} />
          </div>
        );

      case 'observe':
        return (
          <div className="my-3 animate-slide-up" style={delayStyle}>
            <ObserveItem event={event} allEvents={events} />
          </div>
        );

      case 'work_plan':
        return (
          <div className="my-3 animate-slide-up" style={delayStyle}>
            <WorkPlanItem event={event} />
          </div>
        );

      case 'text_delta':
        // Skip text_delta when a text_end exists (it contains the full text)
        if (hasTextEnd) {
          return null;
        }
        return (
          <div className="my-4 animate-slide-up" style={delayStyle}>
            <TextDeltaItem event={event} />
          </div>
        );

      case 'text_start':
        return null;

      case 'text_end':
        return (
          <div className="my-4 animate-slide-up" style={delayStyle}>
            <TextEndItem event={event} />
          </div>
        );

      // Human-in-the-loop events
      case 'clarification_asked':
        return (
          <div className="my-3 animate-slide-up" style={delayStyle}>
            <ClarificationAskedItem event={event} />
          </div>
        );

      case 'clarification_answered':
        // Already shown as part of clarification_asked when answered
        return null;

      case 'decision_asked':
        return (
          <div className="my-3 animate-slide-up" style={delayStyle}>
            <DecisionAskedItem event={event} />
          </div>
        );

      case 'decision_answered':
        // Already shown as part of decision_asked when answered
        return null;

      case 'env_var_requested':
        return (
          <div className="my-3 animate-slide-up" style={delayStyle}>
            <EnvVarRequestedItem event={event} />
          </div>
        );

      case 'env_var_provided':
        // Already shown as part of env_var_requested when answered
        return null;

      case 'artifact_created':
        return (
          <div className="my-3 animate-slide-up" style={delayStyle}>
            <ArtifactCreatedItem
              event={event as ArtifactCreatedEvent & { error?: string | undefined }}
            />
          </div>
        );

      case 'artifact_ready':
      case 'artifact_error':
      case 'artifacts_batch':
        // artifact_ready/artifact_error update existing artifact_created entries via store
        return null;

      case 'task_start':
        return (
          <div className="animate-slide-up" style={delayStyle}>
            <TaskStartItem event={event} />
          </div>
        );

      case 'task_complete':
        return (
          <div className="animate-slide-up" style={delayStyle}>
            <TaskCompleteItem event={event} />
          </div>
        );

      case 'agent_spawned': {
        const spawned = event;
        return (
          <div className="my-2 animate-slide-up" style={delayStyle}>
            <SubAgentDelegationIndicator
              subagentName={spawned.agentName ?? spawned.agentId}
              triggerType={spawned.mode === 'session' ? 'keyword' : 'explicit'}
              taskDescription={spawned.taskSummary ?? undefined}
              status="started"
            />
          </div>
        );
      }

      case 'agent_completed': {
        const completed = event;
        return (
          <div className="my-2 animate-slide-up" style={delayStyle}>
            <SubAgentDelegationIndicator
              subagentName={completed.agentName ?? completed.agentId}
              triggerType="explicit"
              taskDescription={completed.result ?? undefined}
              status={completed.success ? 'completed' : 'failed'}
            />
          </div>
        );
      }

      case 'agent_stopped': {
        const stopped = event;
        return (
          <div className="my-2 animate-slide-up" style={delayStyle}>
            <SubAgentDelegationIndicator
              subagentName={stopped.agentName ?? stopped.agentId}
              triggerType="explicit"
              taskDescription={stopped.reason ?? 'Stopped'}
              status="failed"
            />
          </div>
        );
      }

      case 'agent_message_sent': {
        const sent = event;
        return (
          <div className="my-2 animate-slide-up" style={delayStyle}>
            <AgentMessageIndicator
              direction="sent"
              fromAgentName={sent.fromAgentName}
              toAgentName={sent.toAgentName}
              messagePreview={sent.messagePreview}
            />
          </div>
        );
      }
      case 'agent_message_received': {
        const received = event;
        return (
          <div className="my-2 animate-slide-up" style={delayStyle}>
            <AgentMessageIndicator
              direction="received"
              fromAgentName={received.fromAgentName}
              messagePreview={received.messagePreview}
            />
          </div>
        );
      }

      default:
        if (import.meta.env.DEV) {
          console.warn('Unknown event type in TimelineEventItem:', (event as { type: string }).type);
        }
        return null;
    }
  }
);

TimelineEventItem.displayName = 'TimelineEventItem';

export default TimelineEventItem;
