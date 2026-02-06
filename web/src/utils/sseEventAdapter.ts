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
 * Supports both legacy format and new EventEnvelope format:
 * - Legacy: { type: string, data: T }
 * - Envelope: { schema_version, event_id, event_type, payload, ... }
 *
 * @module utils/sseEventAdapter
 */

import { isEventEnvelope } from '../types/generated/eventEnvelope';

import type {
  AgentEvent,
  AgentEventType,
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
  SandboxCreatedEventData,
  SandboxTerminatedEventData,
  SandboxStatusEventData,
  ClarificationAskedEventData,
  ClarificationAnsweredEventData,
  DecisionAskedEventData,
  DecisionAnsweredEventData,
  EnvVarRequestedEventData,
  EnvVarProvidedEventData,
  ArtifactCreatedEventData,
  ArtifactCategory,
} from '../types/agent';
import type { EventEnvelope } from '../types/generated/eventEnvelope';

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
export function generateTimelineEventId(type: string, prefix?: string): string {
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
      // Get observation value - support both 'observation' (legacy) and 'result' (new) fields
      // Also handle case where result is an object (e.g., from export_artifact)
      let observationValue: string | undefined;
      const rawResult = (data as any).result ?? data.observation;
      if (typeof rawResult === 'string') {
        observationValue = rawResult;
      } else if (rawResult !== null && rawResult !== undefined) {
        // If result is an object, try to extract meaningful text or stringify it
        if (typeof rawResult === 'object' && 'content' in rawResult) {
          // MCP-style result with content array
          const content = (rawResult as any).content;
          if (Array.isArray(content) && content.length > 0) {
            observationValue = content[0]?.text ?? JSON.stringify(rawResult);
          } else {
            observationValue = JSON.stringify(rawResult);
          }
        } else {
          observationValue = JSON.stringify(rawResult);
        }
      }

      // Determine if this is an error:
      // Only check if 'error' field is present in data
      // Note: We no longer check if observation starts with 'Error:'
      // as this caused false positives for valid tool outputs
      const isError = !!data.error;

      return {
        id: generateTimelineEventId('observe'),
        type: 'observe',
        sequenceNumber,
        timestamp,
        toolName: data.tool_name ?? 'unknown', // Use tool_name from event
        execution_id: data.execution_id, // Unique ID for act/observe matching
        toolOutput: observationValue,
        isError,
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

    // Sandbox events - container lifecycle
    case 'sandbox_created': {
      const data = event.data as unknown as SandboxCreatedEventData;
      return {
        id: generateTimelineEventId('sandbox_created'),
        type: 'sandbox_created',
        sequenceNumber,
        timestamp,
        sandboxId: data.sandbox_id,
        projectId: data.project_id,
        status: data.status,
        endpoint: data.endpoint,
        websocketUrl: data.websocket_url,
      };
    }

    case 'sandbox_terminated': {
      const data = event.data as unknown as SandboxTerminatedEventData;
      return {
        id: generateTimelineEventId('sandbox_terminated'),
        type: 'sandbox_terminated',
        sequenceNumber,
        timestamp,
        sandboxId: data.sandbox_id,
      };
    }

    case 'sandbox_status': {
      const data = event.data as unknown as SandboxStatusEventData;
      return {
        id: generateTimelineEventId('sandbox_status'),
        type: 'sandbox_status',
        sequenceNumber,
        timestamp,
        sandboxId: data.sandbox_id,
        status: data.status,
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

    // Human-in-the-loop event types
    case 'clarification_asked': {
      const data = event.data as unknown as ClarificationAskedEventData;
      return {
        id: generateTimelineEventId('clarification_asked'),
        type: 'clarification_asked',
        sequenceNumber,
        timestamp,
        requestId: data.request_id,
        question: data.question,
        clarificationType: data.clarification_type,
        options: data.options,
        allowCustom: data.allow_custom,
        context: data.context,
        answered: false,
      };
    }

    case 'clarification_answered': {
      const data = event.data as unknown as ClarificationAnsweredEventData;
      return {
        id: generateTimelineEventId('clarification_answered'),
        type: 'clarification_answered',
        sequenceNumber,
        timestamp,
        requestId: data.request_id,
        answer: data.answer,
      };
    }

    case 'decision_asked': {
      const data = event.data as unknown as DecisionAskedEventData;
      return {
        id: generateTimelineEventId('decision_asked'),
        type: 'decision_asked',
        sequenceNumber,
        timestamp,
        requestId: data.request_id,
        question: data.question,
        decisionType: data.decision_type,
        options: data.options,
        allowCustom: data.allow_custom,
        context: data.context,
        defaultOption: data.default_option,
        answered: false,
      };
    }

    case 'decision_answered': {
      const data = event.data as unknown as DecisionAnsweredEventData;
      return {
        id: generateTimelineEventId('decision_answered'),
        type: 'decision_answered',
        sequenceNumber,
        timestamp,
        requestId: data.request_id,
        decision: data.decision,
      };
    }

    case 'env_var_requested': {
      const data = event.data as unknown as EnvVarRequestedEventData;
      return {
        id: generateTimelineEventId('env_var_requested'),
        type: 'env_var_requested',
        sequenceNumber,
        timestamp,
        requestId: data.request_id,
        toolName: data.tool_name,
        fields: data.fields,
        message: data.message,
        context: data.context,
        answered: false,
      };
    }

    case 'env_var_provided': {
      const data = event.data as unknown as EnvVarProvidedEventData;
      return {
        id: generateTimelineEventId('env_var_provided'),
        type: 'env_var_provided',
        sequenceNumber,
        timestamp,
        requestId: data.request_id,
        toolName: data.tool_name,
        variableNames: data.variable_names,
      };
    }

    case 'artifact_created': {
      const data = event.data as unknown as ArtifactCreatedEventData;
      return {
        id: generateTimelineEventId('artifact_created'),
        type: 'artifact_created',
        sequenceNumber,
        timestamp,
        artifactId: data.artifact_id,
        filename: data.filename,
        mimeType: data.mime_type,
        category: data.category as ArtifactCategory,
        sizeBytes: data.size_bytes,
        url: data.url,
        previewUrl: data.preview_url,
        toolExecutionId: data.tool_execution_id,
        sourceTool: data.source_tool,
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
 * Automatically assigns sequence numbers.
 * Filters out null events (unsupported event types).
 *
 * Note: Does NOT reset sequence counter to ensure continuity
 * across multiple HITL scenarios. Call resetSequenceCounter()
 * explicitly if you need to start from 1.
 *
 * @param events - Array of SSE events to convert
 * @returns Array of TimelineEvents (filtered to exclude nulls)
 */
export function batchConvertSSEEvents(events: AgentEvent<unknown>[]): TimelineEvent[] {
  // 注意：不在批量转换时重置计数器，以确保多次 HITL 场景下的事件序列连续性
  // 如果需要重置，请显式调用 resetSequenceCounter()
  // resetSequenceCounter();

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
 * Convert a batch of SSE events to TimelineEvents with sequence reset
 *
 * Use this when you explicitly need to start sequence numbers from 1,
 * such as when loading a new conversation history.
 *
 * @param events - Array of SSE events to convert
 * @returns Array of TimelineEvents (filtered to exclude nulls)
 */
export function batchConvertSSEEventsWithReset(events: AgentEvent<unknown>[]): TimelineEvent[] {
  resetSequenceCounter();
  return batchConvertSSEEvents(events);
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
    existingTimeline.length > 0 ? existingTimeline[existingTimeline.length - 1].sequenceNumber : 0;
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
    // Sandbox lifecycle events
    'sandbox_created',
    'sandbox_terminated',
    'sandbox_status',
  ];

  return supportedTypes.includes(eventType);
}

// =============================================================================
// EventEnvelope Support
// =============================================================================

/**
 * Correlation tracking metadata for timeline events
 */
export interface CorrelationMetadata {
  /** Event envelope ID (if from envelope) */
  envelopeId?: string;
  /** Correlation ID for tracing related events */
  correlationId?: string;
  /** Causation ID (parent event that caused this) */
  causationId?: string;
  /** Schema version of the source event */
  schemaVersion?: string;
}

/**
 * Extended TimelineEvent with correlation tracking
 */
export type TimelineEventWithCorrelation = TimelineEvent & CorrelationMetadata;

/**
 * Convert an EventEnvelope to a TimelineEvent
 *
 * This function unwraps the envelope and converts the payload to a TimelineEvent,
 * preserving correlation information.
 *
 * @param envelope - The EventEnvelope to convert
 * @param sequenceNumber - The sequence number for this event
 * @returns A TimelineEvent with correlation info, or null if unsupported
 */
export function envelopeToTimeline(
  envelope: EventEnvelope<unknown>,
  sequenceNumber: number
): TimelineEventWithCorrelation | null {
  // Convert envelope to legacy AgentEvent format for processing
  const legacyEvent: AgentEvent<unknown> = {
    type: envelope.event_type as AgentEventType,
    data: envelope.payload,
  };

  // Use existing conversion logic
  const baseEvent = sseEventToTimeline(legacyEvent, sequenceNumber);

  if (!baseEvent) {
    return null;
  }

  // Enhance with correlation information
  return {
    ...baseEvent,
    envelopeId: envelope.event_id,
    correlationId: envelope.correlation_id,
    causationId: envelope.causation_id,
    schemaVersion: envelope.schema_version,
  };
}

/**
 * Parse raw SSE data and convert to TimelineEvent
 *
 * Automatically detects and handles both formats:
 * - New EventEnvelope format (with schema_version, event_id, etc.)
 * - Legacy AgentEvent format (with type and data)
 *
 * @param rawData - Raw JSON data (string or parsed object)
 * @param sequenceNumber - The sequence number for this event
 * @returns TimelineEvent with optional correlation info, or null if unsupported
 */
export function parseAndConvertEvent(
  rawData: unknown,
  sequenceNumber: number
): TimelineEventWithCorrelation | null {
  // Handle string input
  let data: unknown;
  if (typeof rawData === 'string') {
    try {
      data = JSON.parse(rawData);
    } catch {
      console.warn('Failed to parse event data:', rawData);
      return null;
    }
  } else {
    data = rawData;
  }

  // Check if it's an envelope format
  if (isEventEnvelope(data)) {
    return envelopeToTimeline(data as EventEnvelope<unknown>, sequenceNumber);
  }

  // Check if it's legacy format
  const legacy = data as { type?: string; data?: unknown };
  if (typeof legacy.type === 'string' && legacy.data !== undefined) {
    const event: AgentEvent<unknown> = {
      type: legacy.type as AgentEventType,
      data: legacy.data,
    };
    const baseEvent = sseEventToTimeline(event, sequenceNumber);
    return baseEvent as TimelineEventWithCorrelation;
  }

  console.warn('Unknown event format:', data);
  return null;
}

/**
 * Convert a batch of mixed events (envelopes or legacy) to TimelineEvents
 *
 * @param events - Array of raw events (can be mixed formats)
 * @returns Array of TimelineEvents with correlation info
 */
export function batchConvertMixedEvents(events: unknown[]): TimelineEventWithCorrelation[] {
  resetSequenceCounter();

  const timelineEvents: TimelineEventWithCorrelation[] = [];

  for (const event of events) {
    const sequenceNumber = getNextSequenceNumber();
    const timelineEvent = parseAndConvertEvent(event, sequenceNumber);

    if (timelineEvent) {
      timelineEvents.push(timelineEvent);
    }
  }

  return timelineEvents;
}

/**
 * Group timeline events by correlation ID
 *
 * Useful for visualizing event chains and debugging.
 *
 * @param events - Array of timeline events with correlation info
 * @returns Map of correlation ID → array of related events
 */
export function groupByCorrelation(
  events: TimelineEventWithCorrelation[]
): Map<string, TimelineEventWithCorrelation[]> {
  const groups = new Map<string, TimelineEventWithCorrelation[]>();

  for (const event of events) {
    const key = event.correlationId || 'uncorrelated';
    const existing = groups.get(key) || [];
    existing.push(event);
    groups.set(key, existing);
  }

  return groups;
}

/**
 * Build a causation tree from events
 *
 * Returns a map of event ID → child events, useful for tracing
 * the chain of events.
 *
 * @param events - Array of timeline events with correlation info
 * @returns Map of parent event ID → child events
 */
export function buildCausationTree(
  events: TimelineEventWithCorrelation[]
): Map<string, TimelineEventWithCorrelation[]> {
  const tree = new Map<string, TimelineEventWithCorrelation[]>();

  for (const event of events) {
    if (event.causationId) {
      const existing = tree.get(event.causationId) || [];
      existing.push(event);
      tree.set(event.causationId, existing);
    }
  }

  return tree;
}
