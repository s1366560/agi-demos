/**
 * TimelineEventItem - Optimized single timeline event renderer
 *
 * Renders individual TimelineEvents in chronological order with
 * improved visual hierarchy and spacing.
 *
 * Features:
 * - Natural time rendering for each event (不分组)
 * - Tool status tracking with act/observe matching
 *
 * @module components/agent/TimelineEventItem
 */

import { memo } from "react";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  UserMessage,
  AgentSection,
  ToolExecutionCardDisplay,
} from "./chat/MessageStream";
import { AssistantMessage } from "./chat/AssistantMessage";
import { ReasoningLogCard } from "./chat/MessageStream";
import { formatDistanceToNowCN, formatReadableTime } from "../../utils/date";
import type { TimelineEvent, ActEvent, ObserveEvent } from "../../types/agent";

/**
 * TimeBadge - Natural time display component
 * 自然时间标签组件
 */
function TimeBadge({ timestamp }: { timestamp: number }) {
  const naturalTime = formatDistanceToNowCN(timestamp);
  const readableTime = formatReadableTime(timestamp);
  
  return (
    <span 
      className="text-[10px] text-slate-400 dark:text-slate-500 select-none"
      title={new Date(timestamp).toLocaleString('zh-CN')}
    >
      {naturalTime} · {readableTime}
    </span>
  );
}

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
 */
function findMatchingObserve(
  actEvent: ActEvent,
  events: TimelineEvent[]
): ObserveEvent | undefined {
  const actIndex = events.indexOf(actEvent);

  for (let i = actIndex + 1; i < events.length; i++) {
    const event = events[i];
    if (event.type !== "observe") continue;

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

/**
 * Render thought event
 */
function ThoughtItem({
  event,
  isStreaming,
}: {
  event: TimelineEvent;
  isStreaming: boolean;
}) {
  if (event.type !== "thought") return null;

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
}

/**
 * Render act (tool call) event
 * 工具调用事件渲染 - 带状态跟踪
 */
function ActItem({
  event,
  allEvents,
}: {
  event: TimelineEvent;
  allEvents?: TimelineEvent[];
}) {
  if (event.type !== "act") return null;

  const observeEvent = allEvents ? findMatchingObserve(event, allEvents) : undefined;
  const hasCompleted = !!observeEvent;

  const ToolCard = hasCompleted && observeEvent ? (
    <AgentSection
      icon="construction"
      iconBg="bg-slate-100 dark:bg-slate-800"
      opacity={true}
    >
      <ToolExecutionCardDisplay
        toolName={event.toolName}
        status={observeEvent.isError ? "error" : "success"}
        parameters={event.toolInput}
        result={observeEvent.isError ? undefined : observeEvent.toolOutput}
        error={observeEvent.isError ? observeEvent.toolOutput : undefined}
        duration={observeEvent.timestamp - event.timestamp}
        defaultExpanded={false}
      />
    </AgentSection>
  ) : (
    <AgentSection
      icon="construction"
      iconBg="bg-slate-100 dark:bg-slate-800"
    >
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
}

/**
 * Render observe (tool result) event
 * 工具结果事件渲染 - 孤儿observe（无对应act）时显示
 */
function ObserveItem({
  event,
  allEvents,
}: {
  event: TimelineEvent;
  allEvents?: TimelineEvent[];
}) {
  if (event.type !== "observe") return null;

  const hasMatchingAct = allEvents
    ? allEvents.some((e) => {
        if (e.type !== "act") return false;
        if ((e as ActEvent).execution_id && event.execution_id) {
          return (e as ActEvent).execution_id === event.execution_id;
        }
        return e.toolName === event.toolName && e.timestamp < event.timestamp;
      })
    : false;

  if (hasMatchingAct) {
    return null;
  }

  return (
    <div className="flex flex-col gap-1">
      <AgentSection
        icon="construction"
        iconBg="bg-slate-100 dark:bg-slate-800"
        opacity={true}
      >
        <ToolExecutionCardDisplay
          toolName={event.toolName}
          status={event.isError ? "error" : "success"}
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
}

/**
 * Render work_plan event
 */
function WorkPlanItem({ event }: { event: TimelineEvent }) {
  if (event.type !== "work_plan") return null;

  return (
    <div className="flex flex-col gap-1">
      <AgentSection icon="psychology">
        <ReasoningLogCard
          steps={event.steps.map((s) => s.description)}
          summary={`Work Plan: ${event.steps.length} steps`}
          completed={event.status === "completed"}
          expanded={event.status !== "completed"}
        />
      </AgentSection>
      <div className="pl-12">
        <TimeBadge timestamp={event.timestamp} />
      </div>
    </div>
  );
}

/**
 * Render step_start event
 */
function StepStartItem({ event }: { event: TimelineEvent }) {
  if (event.type !== "step_start") return null;

  const stepDesc = event.stepDescription;
  if (!stepDesc || stepDesc.trim() === "") {
    return null;
  }

  const stepIndex = event.stepIndex;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start gap-3 my-3 opacity-70">
        <div className="w-7 h-7 rounded-full bg-amber-100 dark:bg-amber-500/10 flex items-center justify-center shrink-0">
          <span className="material-symbols-outlined text-amber-600 text-xs">
            play_arrow
          </span>
        </div>
        <div className="flex-1 text-sm text-slate-600 dark:text-slate-400 pt-1">
          {stepIndex !== undefined ? `Step ${stepIndex}: ` : ""}
          {stepDesc}
        </div>
      </div>
      <div className="pl-10">
        <TimeBadge timestamp={event.timestamp} />
      </div>
    </div>
  );
}

/**
 * Render text_delta event (typewriter effect)
 * Uses ReactMarkdown for consistent rendering with final message
 */
function TextDeltaItem({
  event,
  isStreaming,
}: {
  event: TimelineEvent;
  isStreaming: boolean;
}) {
  if (event.type !== "text_delta") return null;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start gap-3 my-4">
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center shrink-0 mt-0.5 shadow-sm">
          <span className="material-symbols-outlined text-primary text-lg">
            smart_toy
          </span>
        </div>
        <div
          className="flex-1 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-2xl rounded-tl-none shadow-sm p-4 prose prose-sm dark:prose-invert max-w-none prose-p:my-1.5 prose-headings:mt-3 prose-headings:mb-1.5 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-pre:bg-slate-100 prose-pre:dark:bg-slate-800 prose-code:text-primary prose-code:before:content-none prose-code:after:content-none prose-a:text-primary prose-a:no-underline hover:prose-a:underline prose-th:text-left prose-img:rounded-lg prose-img:shadow-md leading-relaxed"
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {event.content}
          </ReactMarkdown>
        </div>
      </div>
      <div className="pl-11">
        <TimeBadge timestamp={event.timestamp} />
      </div>
    </div>
  );
}

/**
 * TimelineEventItem component
 */
export const TimelineEventItem: React.FC<TimelineEventItemProps> = memo(
  ({ event, isStreaming = false, allEvents }) => {
    const events = allEvents ?? [event];

    switch (event.type) {
      case "user_message":
        return (
          <div className="my-4 animate-slide-up">
            <div className="flex items-start justify-end gap-3">
              <div className="flex flex-col items-end gap-1 max-w-[80%]">
                <UserMessage content={event.content} />
                <TimeBadge timestamp={event.timestamp} />
              </div>
            </div>
          </div>
        );

      case "assistant_message":
        return (
          <div className="my-4 animate-slide-up">
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

      case "thought":
        return (
          <div className="my-3 animate-slide-up">
            <ThoughtItem event={event} isStreaming={isStreaming} />
          </div>
        );

      case "act":
        return (
          <div className="my-3 animate-slide-up">
            <ActItem event={event} allEvents={events} />
          </div>
        );

      case "observe":
        return (
          <div className="my-3 animate-slide-up">
            <ObserveItem event={event} allEvents={events} />
          </div>
        );

      case "work_plan":
        return (
          <div className="my-3 animate-slide-up">
            <WorkPlanItem event={event} />
          </div>
        );

      case "step_start":
        if (!event.stepDescription || event.stepDescription.trim() === "") {
          return null;
        }
        return (
          <div className="animate-slide-up">
            <StepStartItem event={event} />
          </div>
        );

      case "step_end":
        return null;

      case "text_delta":
        return (
          <div className="my-4 animate-slide-up">
            <TextDeltaItem event={event} isStreaming={isStreaming} />
          </div>
        );

      case "text_start":
      case "text_end":
        return null;

      default:
        console.warn(
          "Unknown event type in TimelineEventItem:",
          (event as { type: string }).type
        );
        return null;
    }
  }
);

TimelineEventItem.displayName = "TimelineEventItem";

export default TimelineEventItem;
