/**
 * TimelineEventGroup - Unified TimelineEvent group renderer
 *
 * Renders EventGroups (from groupTimelineEvents) consistently
 * for both streaming and historical messages.
 *
 * @module components/agent/chat/TimelineEventGroup
 */

import React, { memo } from 'react';
import { UserMessage, AgentSection, ReasoningLogCard, ToolExecutionCardDisplay } from './MessageStream';
import { AssistantMessage } from './AssistantMessage';
import type { EventGroup, AggregatedToolCall, AggregatedWorkPlan } from '../../../utils/timelineEventAdapter';
import type { ReasoningLogCardProps } from './MessageStream';

interface TimelineEventGroupProps {
  /** The event group to render */
  group: EventGroup;
  /** Whether currently streaming (for live updates) */
  isStreaming?: boolean;
}

/**
 * Get step status display props from work plan and tool calls
 */
function getStepStatusProps(workPlan: AggregatedWorkPlan | undefined, _toolCalls: AggregatedToolCall[]): ReasoningLogCardProps | null {
  if (!workPlan) return null;

  return {
    steps: workPlan.steps.map((s: { description: string }) => s.description),
    summary: `Work Plan: ${workPlan.steps.length} steps`,
    completed: workPlan.status === 'completed',
    expanded: workPlan.status !== 'completed',
  };
}

/**
 * Render tool calls from the group
 */
function ToolCallsList({ toolCalls, isStreaming }: { toolCalls: AggregatedToolCall[], isStreaming: boolean }) {
  if (toolCalls.length === 0) return null;

  return (
    <>
      {toolCalls.map((tool, idx) => (
        <AgentSection
          key={`tool-${idx}`}
          icon="construction"
          iconBg="bg-slate-200 dark:bg-border-dark"
          opacity={!isStreaming}
        >
          <ToolExecutionCardDisplay
            toolName={tool.name}
            status={tool.status}
            parameters={tool.input}
            duration={tool.duration}
            result={tool.result}
            error={tool.error}
            defaultExpanded={tool.status === 'running' || tool.status === 'error'}
          />
        </AgentSection>
      ))}
    </>
  );
}

/**
 * Render thoughts from the group
 */
function ThoughtsList({ thoughts, isStreaming }: { thoughts: string[], isStreaming: boolean }) {
  if (thoughts.length === 0) return null;

  return (
    <AgentSection icon="psychology" opacity={!isStreaming}>
      <ReasoningLogCard
        steps={thoughts}
        summary={`Thinking...`}
        completed={!isStreaming}
        expanded={isStreaming}
      />
    </AgentSection>
  );
}

/**
 * TimelineEventGroup component
 *
 * Renders a single EventGroup, handling both user and assistant groups.
 *
 * @example
 * ```tsx
 * import { TimelineEventGroup } from '@/components/agent/chat/TimelineEventGroup'
 *
 * function ChatArea() {
 *   const groups = groupTimelineEvents(timelineEvents)
 *
 *   return (
 *     <MessageStream>
 *       {groups.map(group => (
 *         <TimelineEventGroup key={group.id} group={group} isStreaming={isStreaming} />
 *       ))}
 *     </MessageStream>
 *   )
 * }
 * ```
 */
export const TimelineEventGroup: React.FC<TimelineEventGroupProps> = memo(({
  group,
  isStreaming = false,
}) => {
  // User group - render user message bubble
  if (group.type === 'user') {
    return (
      <div className="animate-fade-in-up">
        <UserMessage content={group.content} />
      </div>
    );
  }

  // Assistant group - may contain work plan, thoughts, tool calls, and/or message
  const hasWorkPlan = group.workPlan && group.workPlan.steps.length > 0;
  const hasThoughts = group.thoughts.length > 0;
  const hasToolCalls = group.toolCalls.length > 0;
  const hasContent = group.content.length > 0;

  return (
    <div className="space-y-6 animate-slide-up">
      {/* Work Plan */}
      {hasWorkPlan && (() => {
        const props = getStepStatusProps(group.workPlan, group.toolCalls);
        return props ? (
          <AgentSection icon="psychology" opacity={!isStreaming}>
            <ReasoningLogCard {...props} />
          </AgentSection>
        ) : null;
      })()}

      {/* Thoughts */}
      {hasThoughts && <ThoughtsList thoughts={group.thoughts} isStreaming={isStreaming} />}

      {/* Tool Calls */}
      {hasToolCalls && <ToolCallsList toolCalls={group.toolCalls} isStreaming={isStreaming} />}

      {/* Final Response Content */}
      {hasContent && (
        <AssistantMessage
          content={group.content}
          isStreaming={isStreaming}
          isReport={group.artifacts !== undefined && group.artifacts.length > 0}
          generatedAt={new Date(group.timestamp).toISOString()}
        />
      )}

      {/* Streaming indicator */}
      {isStreaming && !hasContent && !hasThoughts && !hasToolCalls && !hasWorkPlan && (
        <AgentSection icon="psychology">
          <div className="bg-slate-50 dark:bg-surface-dark/50 border border-slate-200 dark:border-border-dark rounded-2xl rounded-tl-none p-4">
            <div className="flex items-center gap-2 text-slate-500">
              <span className="material-symbols-outlined text-sm spinner">autorenew</span>
              <span className="text-sm">Processing...</span>
            </div>
          </div>
        </AgentSection>
      )}
    </div>
  );
});

TimelineEventGroup.displayName = 'TimelineEventGroup';

export default TimelineEventGroup;
