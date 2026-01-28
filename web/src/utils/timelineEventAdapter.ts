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
 * Group TimelineEvents into renderable EventGroups
 *
 * @param events - Array of TimelineEvents to group
 * @returns Array of EventGroups ready for rendering
 */
export function groupTimelineEvents(events: TimelineEvent[]): EventGroup[] {
  if (events.length === 0) {
    return [];
  }

  const groups: EventGroup[] = [];
  let currentGroup: Partial<EventGroup> & { events: TimelineEvent[] } | null = null;
  let lastUserGroupId: string | null = null;

  for (const event of events) {
    // Handle user message - always creates a new group and finalize immediately
    if (event.type === 'user_message') {
      // Save previous group if exists
      if (currentGroup) {
        groups.push(finalizeGroup(currentGroup));
      }

      // Start new user group
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
      lastUserGroupId = event.id;
      currentGroup = null; // User groups are finalized immediately
      continue;
    }

    // Handle assistant message - always finalize previous group if exists
    if (event.type === 'assistant_message') {
      // Always save previous group before creating new assistant group
      if (currentGroup) {
        groups.push(finalizeGroup(currentGroup));
      }

      // Create new assistant group
      currentGroup = {
        id: event.id,
        type: 'assistant',
        content: (event as AssistantMessageEvent).content,
        timestamp: event.timestamp,
        thoughts: [],
        toolCalls: [],
        artifacts: (event as AssistantMessageEvent).artifacts,
        events: [event],
        isStreaming: false,
      };
      lastUserGroupId = null;
      continue;
    }

    // Handle work plan - associate with current assistant group
    if (event.type === 'work_plan') {
      if (!currentGroup) {
        // Create an assistant group for orphaned work plan
        currentGroup = {
          id: `group-${event.id}`,
          type: 'assistant',
          content: '',
          timestamp: event.timestamp,
          thoughts: [],
          toolCalls: [],
          events: [event],
          isStreaming: true,
        };
      } else {
        currentGroup.events.push(event);
      }

      const wpEvent = event as WorkPlanTimelineEvent;
      currentGroup.workPlan = {
        steps: wpEvent.steps.map((s, idx) => ({
          stepNumber: s.step_number ?? idx + 1,
          description: s.description,
          expectedOutput: s.expected_output,
        })),
        status: (wpEvent.status === 'completed' || wpEvent.status === 'failed' || wpEvent.status === 'planning' || wpEvent.status === 'in_progress')
          ? wpEvent.status
          : 'in_progress',
      };
      continue;
    }

    // Handle step events - update work plan current step
    if (event.type === 'step_start') {
      if (currentGroup) {
        currentGroup.events.push(event);
        if (currentGroup.workPlan) {
          const stepEvent = event as StepStartEvent;
          currentGroup.workPlan.currentStep = stepEvent.stepIndex;
          currentGroup.isStreaming = true;
        }
      }
      continue;
    }

    // Handle step end - update step status
    if (event.type === 'step_end') {
      if (currentGroup) {
        currentGroup.events.push(event);
        // Step completion is tracked in work plan status
      }
      continue;
    }

    // Handle thought events - add to current group or create implicit assistant group
    if (event.type === 'thought') {
      // If we just had a user message (no currentGroup or currentGroup was user), create implicit assistant group
      if (!currentGroup || lastUserGroupId) {
        // Finalize any existing group first
        if (currentGroup) {
          groups.push(finalizeGroup(currentGroup));
        }
        // Create implicit assistant group for thought/act events
        const thoughtEvent = event as ThoughtEvent;
        currentGroup = {
          id: `implicit-assistant-${event.id}`,
          type: 'assistant',
          content: '',
          timestamp: event.timestamp,
          thoughts: [thoughtEvent.content], // Initialize with this thought
          toolCalls: [],
          events: [event],
          isStreaming: true,
        };
        lastUserGroupId = null;
      } else {
        currentGroup.events.push(event);
        // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
        currentGroup.thoughts!.push((event as ThoughtEvent).content);
        currentGroup.isStreaming = true;
      }
      continue;
    }

    // Handle act events - add to current group's tool calls
    if (event.type === 'act') {
      if (!currentGroup) {
        // Create an assistant group for orphaned act
        currentGroup = {
          id: `act-group-${event.id}`,
          type: 'assistant',
          content: '',
          timestamp: event.timestamp,
          thoughts: [],
          toolCalls: [],
          events: [event],
          isStreaming: true,
        };
      } else {
        currentGroup.events.push(event);
        const actEvent = event as ActEvent;

        // Create a new tool call entry
        const toolCall: AggregatedToolCall = {
          name: actEvent.toolName,
          input: actEvent.toolInput,
          status: 'running',
          startTime: actEvent.timestamp,
        };

        // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
        currentGroup.toolCalls!.push(toolCall);
        currentGroup.isStreaming = true;
      }
      continue;
    }

    // Handle observe events - update matching tool call
    if (event.type === 'observe') {
      if (currentGroup) {
        currentGroup.events.push(event);
        const obsEvent = event as ObserveEvent;

        // Find the matching tool call by name
        // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
        const matchingToolCall = currentGroup.toolCalls!.find(
          (tc) => tc.name === obsEvent.toolName && tc.status === 'running'
        );

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
      continue;
    }

    // For any other event type, add to current group if exists
    if (currentGroup) {
      currentGroup.events.push(event);
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
