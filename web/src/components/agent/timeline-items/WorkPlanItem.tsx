/**
 * WorkPlanItem - Render work_plan timeline events
 */

import { memo } from 'react';

import { useAgentV3Store } from '../../../stores/agentV3';
import { AgentSection, ReasoningLogCard } from '../chat/MessageStream';

import { PlanReviewGate } from './PlanReviewGate';
import { TimeBadge } from './shared';

import type { TimelineEvent } from '../../../types/agent';

interface WorkPlanItemProps {
  event: TimelineEvent;
}

export const WorkPlanItem = memo(
  function WorkPlanItem({ event }: WorkPlanItemProps) {
    const conversationId = useAgentV3Store((s) => s.activeConversationId);
    if (event.type !== 'work_plan') return null;

    return (
      <div className="flex flex-col gap-1">
        <AgentSection icon="psychology">
          <ReasoningLogCard
            steps={event.steps.map((s) => s.description)}
            summary={`Work Plan: ${String(event.steps.length)} steps`}
            completed={event.status === 'completed'}
            expanded={event.status !== 'completed'}
          />
          <PlanReviewGate conversationId={conversationId ?? undefined} event={event} />
        </AgentSection>
        <div className="pl-12">
          <TimeBadge timestamp={event.timestamp} />
        </div>
      </div>
    );
  },
  (prev, next) => {
    return prev.event.id === next.event.id && prev.event.type === next.event.type;
  }
);
