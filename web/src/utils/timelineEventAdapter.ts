/**
 * TimelineEventAdapter - Unified TimelineEvent to Renderable Data Adapter
 *
 * This module provides utilities to convert TimelineEvents into renderable groups
 * for the chat interface. It ensures consistent rendering between:
 * - Real-time streaming (SSE events as TimelineEvents)
 * - Historical messages (API returns TimelineEvents)
 *
 * @module utils/timelineEventAdapter
 */

import type {
  TimelineEvent,
  ActEvent,
  ObserveEvent,
  ThoughtEvent,
  WorkPlanTimelineEvent,
  AssistantMessageEvent,
  UserMessageEvent,
  StepStartEvent,
  TextDeltaEvent,
} from '../types/agent';

/**
 * Aggregated tool call information
 */
export interface AggregatedToolCall {
  /** Tool name */
  name: string;
  /** Tool input parameters */
  input: Record<string, unknown>;
  /** Tool execution status */
  status: 'running' | 'success' | 'error';
  /** Tool output result */
  result?: string;
  /** Error message if failed */
  error?: string;
  /** Execution duration in milliseconds */
  duration?: number;
  /** Start time timestamp */
  startTime: number;
  /** End time timestamp */
  endTime?: number;
}

/**
 * Aggregated work plan information
 */
export interface AggregatedWorkPlan {
  /** Plan steps */
  steps: Array<{
    stepNumber: number;
    description: string;
    expectedOutput: string;
  }>;
  /** Plan status */
  status: 'planning' | 'in_progress' | 'completed' | 'failed';
  /** Current step index */
  currentStep?: number;
}

/**
 * Execution data extracted from TimelineEvents
 */
export interface ExecutionData {
  /** Thoughts from ThoughtEvent */
  thoughts: string[];
  /** Tool calls aggregated from ActEvent + ObserveEvent */
  toolCalls: AggregatedToolCall[];
  /** Work plan from WorkPlanTimelineEvent */
  workPlan?: AggregatedWorkPlan;
  /** Whether execution is still in progress */
  isStreaming: boolean;
}

/**
 * Event group for rendering
 * Represents a user message + following assistant events
 * or a standalone assistant message
 */
export interface EventGroup {
  /** Group identifier (message ID or generated ID) */
  id: string;
  /** Group type: user or assistant */
  type: 'user' | 'assistant';
  /** Message content */
  content: string;
  /** Timestamp */
  timestamp: number;
  /** Execution data (for assistant messages) */
  thoughts: string[];
  /** Tool calls */
  toolCalls: AggregatedToolCall[];
  /** Work plan */
  workPlan?: AggregatedWorkPlan;
  /** Artifacts */
  artifacts?: Array<{
    objectKey?: string;
    url: string;
    mimeType?: string;
  }>;
  /** Whether this group is streaming */
  isStreaming: boolean;
  /** Associated timeline events */
  events: TimelineEvent[];
}

/**
 * Prefixes used to identify implicit assistant groups
 * These groups are created before a real assistant_message arrives
 */
const IMPLICIT_GROUP_PREFIXES = ['implicit-assistant-', 'act-group-'] as const;

/**
 * Check if a group ID represents an implicit assistant group
 *
 * @param groupId - The group ID to check
 * @param hasContent - Whether the group has content (for work_plan groups)
 * @returns True if this is an implicit group
 */
function isImplicitGroup(groupId: string | undefined, hasContent: boolean): boolean {
  if (!groupId) return false;
  return IMPLICIT_GROUP_PREFIXES.some(prefix => groupId.startsWith(prefix)) ||
         (groupId.startsWith('group-') && !hasContent);
}

/**
 * Normalize work plan status to valid PlanStatus type
 *
 * @param status - The status from the event
 * @returns Normalized status
 */
function normalizeWorkPlanStatus(status: string): AggregatedWorkPlan['status'] {
  const validStatuses: AggregatedWorkPlan['status'][] = ['planning', 'in_progress', 'completed', 'failed'];
  return validStatuses.includes(status as AggregatedWorkPlan['status'])
    ? (status as AggregatedWorkPlan['status'])
    : 'in_progress';
}

/**
 * Create a new implicit assistant group for orphaned execution events
 *
 * @param id - The group ID
 * @param event - The event that triggered creation
 * @param initialThoughts - Optional initial thoughts array
 * @returns New implicit assistant group
 */
function createImplicitGroup(
  id: string,
  event: TimelineEvent,
  initialThoughts: string[] = []
): Partial<EventGroup> & { events: TimelineEvent[] } {
  return {
    id,
    type: 'assistant',
    content: '',
    timestamp: event.timestamp,
    thoughts: initialThoughts,
    toolCalls: [],
    events: [event],
    isStreaming: true,
  };
}

/**
 * Group TimelineEvents into renderable EventGroups
 *
 * Groups events into the expected pattern:
 * user_message -> thought -> act -> observe -> assistant_message
 *
 * Key behaviors:
 * 1. User messages create standalone groups immediately
 * 2. Assistant messages merge with implicit groups or start new groups
 * 3. Execution events (thought, act, observe) attach to current assistant group
 * 4. Orphaned execution events create implicit assistant groups
 * 5. Act/observe pairing uses order-based matching for SSE compatibility
 *
 * @param events - Array of TimelineEvents to group
 * @returns Array of EventGroups ready for rendering
 */
export function groupTimelineEvents(events: TimelineEvent[]): EventGroup[] {
  if (events.length === 0) {
    return [];
  }

  const groups: EventGroup[] = [];
  let currentGroup: (Partial<EventGroup> & { events: TimelineEvent[] }) | null = null;

  for (const event of events) {
    switch (event.type) {
      case 'user_message': {
        // Finalize any existing group
        if (currentGroup) {
          groups.push(finalizeGroup(currentGroup));
          currentGroup = null;
        }

        // Create and immediately finalize user group
        const userGroup: Partial<EventGroup> & { events: TimelineEvent[] } = {
          id: event.id,
          type: 'user',
          content: (event as UserMessageEvent).content,
          timestamp: event.timestamp,
          thoughts: [],
          toolCalls: [],
          events: [event],
          isStreaming: false,
        };
        groups.push(finalizeGroup(userGroup));
        break;
      }

      case 'assistant_message': {
        const assistantEvent = event as AssistantMessageEvent;
        const isImplicit = isImplicitGroup(currentGroup?.id, !!currentGroup?.content);

        if (isImplicit && currentGroup) {
          // Merge into current implicit group - this becomes the real assistant message
          currentGroup.id = assistantEvent.id;
          currentGroup.content = assistantEvent.content;
          currentGroup.artifacts = assistantEvent.artifacts;
          currentGroup.events.push(assistantEvent);
          currentGroup.isStreaming = false;
        } else {
          // Finalize previous group and start new assistant group
          if (currentGroup) {
            groups.push(finalizeGroup(currentGroup));
          }

          currentGroup = {
            id: assistantEvent.id,
            type: 'assistant',
            content: assistantEvent.content,
            timestamp: assistantEvent.timestamp,
            thoughts: [],
            toolCalls: [],
            artifacts: assistantEvent.artifacts,
            events: [assistantEvent],
            isStreaming: false,
          };
        }
        break;
      }

      case 'work_plan': {
        const wpEvent = event as WorkPlanTimelineEvent;

        if (!currentGroup) {
          currentGroup = createImplicitGroup(`group-${event.id}`, event);
        } else {
          currentGroup.events.push(event);
        }

        currentGroup.workPlan = {
          steps: wpEvent.steps.map((s, idx) => ({
            stepNumber: s.step_number ?? idx + 1,
            description: s.description,
            expectedOutput: s.expected_output,
          })),
          status: normalizeWorkPlanStatus(wpEvent.status),
        };
        break;
      }

      case 'step_start': {
        if (currentGroup) {
          currentGroup.events.push(event);
          if (currentGroup.workPlan) {
            currentGroup.workPlan.currentStep = (event as StepStartEvent).stepIndex;
            currentGroup.isStreaming = true;
          }
        }
        break;
      }

      case 'step_end': {
        if (currentGroup) {
          currentGroup.events.push(event);
        }
        break;
      }

      case 'thought': {
        const thoughtEvent = event as ThoughtEvent;

        if (!currentGroup) {
          currentGroup = createImplicitGroup(`implicit-assistant-${event.id}`, event, [thoughtEvent.content]);
        } else {
          currentGroup.events.push(event);
          currentGroup.thoughts!.push(thoughtEvent.content);
          currentGroup.isStreaming = true;
        }
        break;
      }

      case 'act': {
        const actEvent = event as ActEvent;

        if (!currentGroup) {
          currentGroup = createImplicitGroup(`act-group-${event.id}`, event);
        } else {
          currentGroup.events.push(event);
        }

        // Create new tool call entry
        currentGroup.toolCalls!.push({
          name: actEvent.toolName,
          input: actEvent.toolInput,
          status: 'running',
          startTime: actEvent.timestamp,
        });
        currentGroup.isStreaming = true;
        break;
      }

      case 'observe': {
        const obsEvent = event as ObserveEvent;

        if (currentGroup) {
          currentGroup.events.push(event);

          // Order-based matching: find first running tool call
          // This handles SSE case where observe.toolName is 'unknown'
          const matchingToolCall = currentGroup.toolCalls!.find(tc => tc.status === 'running');

          if (matchingToolCall) {
            const endTime = obsEvent.timestamp;
            matchingToolCall.endTime = endTime;
            matchingToolCall.duration = endTime - matchingToolCall.startTime;
            matchingToolCall.status = obsEvent.isError ? 'error' : 'success';

            if (obsEvent.isError) {
              matchingToolCall.error = obsEvent.toolOutput;
            } else {
              matchingToolCall.result = obsEvent.toolOutput;
            }
          }
        }
        break;
      }

      case 'text_delta': {
        const deltaEvent = event as TextDeltaEvent;

        // text_delta accumulates content to the current assistant group
        if (!currentGroup) {
          // Create implicit assistant group for streaming text
          currentGroup = createImplicitGroup(`text-delta-group-${event.id}`, event);
        } else {
          currentGroup.events.push(event);
        }

        // Accumulate text content
        currentGroup.content = (currentGroup.content || '') + deltaEvent.content;
        currentGroup.isStreaming = true;
        break;
      }

      case 'text_start':
      case 'text_end': {
        // These events mark the beginning/end of text streaming
        // Just add them to the current group if exists
        if (currentGroup) {
          currentGroup.events.push(event);
        }
        break;
      }

      default:
        // For any other event type, add to current group if exists
        if (currentGroup) {
          currentGroup.events.push(event);
        }
        break;
    }
  }

  // Don't forget the last group
  if (currentGroup) {
    groups.push(finalizeGroup(currentGroup));
  }

  return groups;
}

/**
 * Finalize a group by ensuring all required fields are set
 */
function finalizeGroup(
  partial: Partial<EventGroup> & { events: TimelineEvent[] }
): EventGroup {
  return {
    id: partial.id ?? `group-${Date.now()}`,
    type: partial.type ?? 'assistant',
    content: partial.content ?? '',
    timestamp: partial.timestamp ?? Date.now(),
    thoughts: partial.thoughts ?? [],
    toolCalls: partial.toolCalls ?? [],
    workPlan: partial.workPlan,
    artifacts: partial.artifacts,
    isStreaming: partial.isStreaming ?? false,
    events: partial.events,
  };
}

/**
 * Extract execution data from a collection of TimelineEvents
 *
 * @param events - Array of TimelineEvents to extract from
 * @returns Aggregated execution data
 */
export function extractExecutionData(events: TimelineEvent[]): ExecutionData {
  const thoughts: string[] = [];
  const toolCalls: AggregatedToolCall[] = [];
  let workPlan: AggregatedWorkPlan | undefined;
  const actEvents: ActEvent[] = [];

  for (const event of events) {
    if (event.type === 'thought') {
      thoughts.push((event as ThoughtEvent).content);
    } else if (event.type === 'act') {
      actEvents.push(event as ActEvent);
    } else if (event.type === 'work_plan') {
      const wpEvent = event as WorkPlanTimelineEvent;
      workPlan = {
        steps: wpEvent.steps.map((s, idx) => ({
          stepNumber: s.step_number ?? idx + 1,
          description: s.description,
          expectedOutput: s.expected_output,
        })),
        status: (wpEvent.status === 'completed' || wpEvent.status === 'failed' || wpEvent.status === 'planning' || wpEvent.status === 'in_progress')
          ? wpEvent.status
          : 'in_progress',
      };
    }
  }

  // Process act events with their matching observe events
  for (const actEvent of actEvents) {
    const observeEvent = findMatchingObserve(actEvent, events);
    const startTime = actEvent.timestamp;

    if (observeEvent) {
      const endTime = observeEvent.timestamp;
      toolCalls.push({
        name: actEvent.toolName,
        input: actEvent.toolInput,
        status: observeEvent.isError ? 'error' : 'success',
        result: observeEvent.isError ? undefined : observeEvent.toolOutput,
        error: observeEvent.isError ? observeEvent.toolOutput : undefined,
        duration: endTime - startTime,
        startTime,
        endTime,
      });
    } else {
      // No observe event found, still running
      toolCalls.push({
        name: actEvent.toolName,
        input: actEvent.toolInput,
        status: 'running',
        startTime,
      });
    }
  }

  // Check if any tool is still running
  const isStreaming = toolCalls.some((tc) => tc.status === 'running');

  return {
    thoughts,
    toolCalls,
    workPlan,
    isStreaming,
  };
}

/**
 * Find the observe event that corresponds to an act event
 *
 * @param actEvent - The act event to find matching observe for
 * @param events - All events to search in
 * @returns Matching observe event or undefined
 */
export function findMatchingObserve(
  actEvent: ActEvent,
  events: TimelineEvent[]
): ObserveEvent | undefined {
  // Find the first observe event after the act event with matching tool name
  const actIndex = events.indexOf(actEvent);

  for (let i = actIndex + 1; i < events.length; i++) {
    const event = events[i];
    if (event.type === 'observe') {
      const observeEvent = event as ObserveEvent;
      if (observeEvent.toolName === actEvent.toolName) {
        return observeEvent;
      }
    }
    // Stop if we hit another act event or message
    if (event.type === 'act' || isMessageEvent(event)) {
      break;
    }
  }

  return undefined;
}

/**
 * Check if an event is a message event (user or assistant)
 *
 * @param event - Event to check
 * @returns True if event is a message event
 */
export function isMessageEvent(event: TimelineEvent): event is UserMessageEvent | AssistantMessageEvent {
  return event.type === 'user_message' || event.type === 'assistant_message';
}

/**
 * Check if an event is an execution event (thought, act, observe)
 *
 * @param event - Event to check
 * @returns True if event is an execution event
 */
export function isExecutionEvent(event: TimelineEvent): event is ThoughtEvent | ActEvent | ObserveEvent {
  return event.type === 'thought' || event.type === 'act' || event.type === 'observe';
}
