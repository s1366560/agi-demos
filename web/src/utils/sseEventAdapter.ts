/**
 * SSE Event Adapter
 *
 * Converts SSE AgentEvent types to TimelineEvent format, ensuring
 * consistency between streaming and historical messages.
 *
 * This adapter provides the conversion layer needed to unify the
 * two data paths:
 * - SSE streaming events → TimelineEvent
 * - Historical API → TimelineEvent (already correct)
 *
 * @module utils/sseEventAdapter
 */

import type {
  AgentEvent,
  TimelineEvent,
  MessageEventData,
  ThoughtEventData,
  ActEventData,
  ObserveEventData,
  WorkPlanEventData,
  StepStartEventData,
  StepEndEventData,
  CompleteEventData,
  TextDeltaEventData,
  TextEndEventData,
  BaseTimelineEvent,
  DesktopStartedEventData,
  DesktopStoppedEventData,
  DesktopStatusEventData,
  TerminalStartedEventData,
  TerminalStoppedEventData,
  TerminalStatusEventData,
  ScreenshotUpdateEventData,
} from '../types/agent';

/**
 * Sequence number counter for timeline events
 * Starts at 1 and increments for each event
 */
let sequenceCounter = 0;

/**
 * Reset the sequence number counter to 0
 * Call this when starting a new conversation or in tests
 */
export function resetSequenceCounter(): void {
  sequenceCounter = 0;
}

/**
 * Get the current sequence counter value (for testing)
 * @internal
 */
export function getSequenceCounter(): number {
  return sequenceCounter;
}

/**
 * Get the next sequence number for a timeline event
 *
 * @param reset - If true, reset counter before getting next number
 * @returns The next sequence number
 */
export function getNextSequenceNumber(reset = false): number {
  if (reset) {
    sequenceCounter = 0;
  }
  return ++sequenceCounter;
}

/**
 * Generate a unique ID for a timeline event
 *
 * Format: `{type}-{timestamp}-{random}`
 *
 * @param type - The event type (e.g., 'thought', 'act')
 * @param prefix - Optional custom prefix (defaults to type)
 * @returns A unique event ID
 */
export function generateTimelineEventId(
  type: string,
  prefix?: string
): string {
  const prefixPart = prefix ?? type;
  const timestamp = Math.floor(Date.now() / 1000); // Unix timestamp in seconds
  const random = Math.random().toString(36).substring(2, 8);
  return `${prefixPart}-${timestamp.toString(16)}-${random}`;
}

/**
 * Convert an SSE AgentEvent to a TimelineEvent
 *
 * Maps SSE event types to unified TimelineEvent types.
 * Returns null for unsupported event types.
 *
 * @param event - The SSE event to convert
 * @param sequenceNumber - The sequence number for this event
 * @returns A TimelineEvent or null if event type is not supported
 */
export function sseEventToTimeline(
  event: AgentEvent<unknown>,
  sequenceNumber: number
): TimelineEvent | null {
  const timestamp = Date.now();

  switch (event.type) {
    case 'message': {
      const data = event.data as unknown as MessageEventData;
      const baseEvent: BaseTimelineEvent = {
        id: data.id || generateTimelineEventId('message'),
        type: data.role === 'user' ? ('user_message' as const) : ('assistant_message' as const),
        sequenceNumber,
        timestamp,
      };

      if (data.role === 'user') {
        return {
          ...baseEvent,
          type: 'user_message',
          content: data.content,
          role: 'user',
        };
      } else {
        return {
          ...baseEvent,
          type: 'assistant_message',
          content: data.content,
          role: 'assistant',
          artifacts: data.artifacts,
          metadata: data.artifacts ? { artifacts: data.artifacts } : undefined,
        };
      }
    }

    case 'thought': {
      const data = event.data as unknown as ThoughtEventData;
      return {
        id: generateTimelineEventId('thought'),
        type: 'thought',
        sequenceNumber,
        timestamp,
        content: data.thought,
      };
    }

    case 'act': {
      const data = event.data as unknown as ActEventData;
      return {
        id: generateTimelineEventId('act'),
        type: 'act',
        sequenceNumber,
        timestamp,
        toolName: data.tool_name,
        toolInput: data.tool_input,
        execution_id: data.execution_id, // Unique ID for act/observe matching
        execution: {
          startTime: timestamp,
          endTime: 0, // Will be set when observe arrives
          duration: 0,
        },
      };
    }

    case 'observe':
    case 'tool_result': {
      const data = event.data as unknown as ObserveEventData;
      return {
        id: generateTimelineEventId('observe'),
        type: 'observe',
        sequenceNumber,
        timestamp,
        toolName: data.tool_name ?? 'unknown', // Use tool_name from event
        execution_id: data.execution_id, // Unique ID for act/observe matching
        toolOutput: data.observation,
        isError: false,
      };
    }

    case 'work_plan': {
      const data = event.data as unknown as WorkPlanEventData;
      return {
        id: generateTimelineEventId('work_plan'),
        type: 'work_plan',
        sequenceNumber,
        timestamp,
        steps: data.steps.map((s) => ({
          step_number: s.step_number,
          description: s.description,
          expected_output: s.expected_output,
        })),
        status: data.status,
      };
    }

    case 'step_start': {
      const data = event.data as unknown as StepStartEventData;
      return {
        id: generateTimelineEventId('step_start'),
        type: 'step_start',
        sequenceNumber,
        timestamp,
        stepIndex: data.step_number,
        stepDescription: data.description,
      };
    }

    case 'step_end':
    case 'step_finish': {
      const data = event.data as unknown as StepEndEventData;
      return {
        id: generateTimelineEventId('step_end'),
        type: 'step_end',
        sequenceNumber,
        timestamp,
        stepIndex: data.step_number,
        status: data.success ? 'completed' : 'failed',
      };
    }

    case 'complete': {
      const data = event.data as unknown as CompleteEventData;
      return {
        id: data.id || data.message_id || generateTimelineEventId('assistant'),
        type: 'assistant_message',
        sequenceNumber,
        timestamp,
        content: data.content,
        role: 'assistant',
        artifacts: data.artifacts,
        metadata: data.trace_url
          ? { traceUrl: data.trace_url, artifacts: data.artifacts }
          : { artifacts: data.artifacts },
      };
    }

    case 'text_start': {
      return {
        id: generateTimelineEventId('text_start'),
        type: 'text_start',
        sequenceNumber,
        timestamp,
      };
    }

    case 'text_delta': {
      const data = event.data as unknown as TextDeltaEventData;
      return {
        id: generateTimelineEventId('text_delta'),
        type: 'text_delta',
        sequenceNumber,
        timestamp,
        content: data.delta,
      };
    }

    case 'text_end': {
      const data = event.data as unknown as TextEndEventData;
      return {
        id: generateTimelineEventId('text_end'),
        type: 'text_end',
        sequenceNumber,
        timestamp,
        fullText: data.full_text,
      };
    }

    // Sandbox events - desktop and terminal
    case 'desktop_started': {
      const data = event.data as unknown as DesktopStartedEventData;
      return {
        id: generateTimelineEventId('desktop_started'),
        type: 'desktop_started',
        sequenceNumber,
        timestamp,
        sandboxId: data.sandbox_id,
        url: data.url,
        display: data.display,
        resolution: data.resolution,
        port: data.port,
      };
    }

    case 'desktop_stopped': {
      const data = event.data as unknown as DesktopStoppedEventData;
      return {
        id: generateTimelineEventId('desktop_stopped'),
        type: 'desktop_stopped',
        sequenceNumber,
        timestamp,
        sandboxId: data.sandbox_id,
      };
    }

    case 'desktop_status': {
      const data = event.data as unknown as DesktopStatusEventData;
      return {
        id: generateTimelineEventId('desktop_status'),
        type: 'desktop_status',
        sequenceNumber,
        timestamp,
        sandboxId: data.sandbox_id,
        running: data.running,
        url: data.url,
        display: data.display,
        resolution: data.resolution,
        port: data.port,
      };
    }

    case 'terminal_started': {
      const data = event.data as unknown as TerminalStartedEventData;
      return {
        id: generateTimelineEventId('terminal_started'),
        type: 'terminal_started',
        sequenceNumber,
        timestamp,
        sandboxId: data.sandbox_id,
        url: data.url,
        port: data.port,
        sessionId: data.sessionId,
      };
    }

    case 'terminal_stopped': {
      const data = event.data as unknown as TerminalStoppedEventData;
      return {
        id: generateTimelineEventId('terminal_stopped'),
        type: 'terminal_stopped',
        sequenceNumber,
        timestamp,
        sandboxId: data.sandbox_id,
        sessionId: data.sessionId ?? undefined,
      };
    }

    case 'terminal_status': {
      const data = event.data as unknown as TerminalStatusEventData;
      return {
        id: generateTimelineEventId('terminal_status'),
        type: 'terminal_status',
        sequenceNumber,
        timestamp,
        sandboxId: data.sandbox_id,
        running: data.running,
        url: data.url,
        port: data.port,
        sessionId: data.sessionId ?? undefined,
      };
    }

    case 'screenshot_update': {
      const data = event.data as unknown as ScreenshotUpdateEventData;
      return {
        id: generateTimelineEventId('screenshot_update'),
        type: 'screenshot_update',
        sequenceNumber,
        timestamp,
        sandboxId: data.sandbox_id,
        imageUrl: data.imageUrl,
      };
    }

    // Unsupported event types - return null
    case 'start':
    case 'status':
    case 'cost_update':
    case 'retry':
    case 'compact_needed':
    case 'error':
    case 'doom_loop_detected':
    case 'doom_loop_intervened':
    case 'clarification_asked':
    case 'clarification_answered':
    case 'decision_asked':
    case 'decision_answered':
    case 'permission_asked':
    case 'permission_replied':
    case 'skill_matched':
    case 'skill_execution_start':
    case 'skill_tool_start':
    case 'skill_tool_result':
    case 'skill_execution_complete':
    case 'skill_fallback':
    case 'pattern_match':
    case 'context_compressed':
    case 'plan_mode_enter':
    case 'plan_mode_exit':
    case 'plan_created':
    case 'plan_updated':
    case 'plan_status_changed':
    case 'title_generated':
    case 'thought_delta':
      return null;

    default:
      // Unknown event type - return null for type safety
      return null;
  }
}

/**
 * Convert a batch of SSE events to TimelineEvents
 *
 * Automatically assigns sequence numbers starting from 1.
 * Filters out null events (unsupported event types).
 * Resets sequence counter for each batch.
 *
 * @param events - Array of SSE events to convert
 * @returns Array of TimelineEvents (filtered to exclude nulls)
 */
export function batchConvertSSEEvents(
  events: AgentEvent<unknown>[]
): TimelineEvent[] {
  // Reset sequence for each batch
  resetSequenceCounter();

  const timelineEvents: TimelineEvent[] = [];

  for (const event of events) {
    const sequenceNumber = getNextSequenceNumber();
    const timelineEvent = sseEventToTimeline(event, sequenceNumber);

    if (timelineEvent) {
      timelineEvents.push(timelineEvent);
    }
  }

  return timelineEvents;
}

/**
 * Convert an SSE event and append it to an existing timeline
 *
 * Use this for streaming scenarios where events arrive one at a time.
 *
 * @param existingTimeline - The current timeline
 * @param event - The new SSE event to append
 * @returns Updated timeline with the new event (or unchanged if event type is unsupported)
 */
export function appendSSEEventToTimeline(
  existingTimeline: TimelineEvent[],
  event: AgentEvent<unknown>
): TimelineEvent[] {
  const lastSequence =
    existingTimeline.length > 0
      ? existingTimeline[existingTimeline.length - 1].sequenceNumber
      : 0;
  const nextSequence = lastSequence + 1;

  const timelineEvent = sseEventToTimeline(event, nextSequence);

  if (!timelineEvent) {
    return existingTimeline; // Unsupported event type, no change
  }

  return [...existingTimeline, timelineEvent];
}

/**
 * Check if an SSE event type is supported (convertible to TimelineEvent)
 *
 * @param eventType - The SSE event type to check
 * @returns true if the event type can be converted
 */
export function isSupportedEventType(eventType: string): boolean {
  const supportedTypes = [
    'message',
    'thought',
    'act',
    'observe',
    'tool_result',
    'work_plan',
    'step_start',
    'step_end',
    'step_finish',
    'complete',
    'text_start',
    'text_delta',
    'text_end',
    // Sandbox events
    'desktop_started',
    'desktop_stopped',
    'desktop_status',
    'terminal_started',
    'terminal_stopped',
    'terminal_status',
    'screenshot_update',
  ];

  return supportedTypes.includes(eventType);
}
