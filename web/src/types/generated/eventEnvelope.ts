/**
 * Event Envelope Types - TypeScript definitions matching Python EventEnvelope.
 *
 * Auto-generated structure matching src/domain/events/envelope.py
 *
 * The EventEnvelope provides a standardized wrapper for all domain events,
 * enabling:
 * - Schema versioning for backward/forward compatibility
 * - Event correlation and causation tracking
 * - Metadata for observability and debugging
 */

import type { AgentEventType } from './eventTypes';

/**
 * Event Envelope - wrapper for all domain events.
 *
 * Wire format:
 * {
 *   "schema_version": "1.0",
 *   "event_id": "evt_abc123",
 *   "event_type": "thought",
 *   "timestamp": "2024-01-01T00:00:00Z",
 *   "source": "memstack",
 *   "correlation_id": "corr_xyz",
 *   "causation_id": "evt_parent",
 *   "payload": { ... },
 *   "metadata": { ... }
 * }
 */
export interface EventEnvelope<T = Record<string, unknown>> {
  /** Version of the event schema (e.g., "1.0") */
  schema_version: string;

  /** Unique identifier for this event */
  event_id: string;

  /** Type of the event (from AgentEventType) */
  event_type: AgentEventType;

  /** When the event occurred (ISO 8601 format) */
  timestamp: string;

  /** System that generated the event */
  source: string;

  /** Optional ID for correlating related events (e.g., same request chain) */
  correlation_id?: string | undefined;

  /** Optional ID of the event that caused this event */
  causation_id?: string | undefined;

  /** Event-specific data */
  payload: T;

  /** Additional context (e.g., user_id, tenant_id) */
  metadata?: Record<string, unknown> | undefined;
}

/**
 * Helper to check if an object is an EventEnvelope
 */
export function isEventEnvelope(obj: unknown): obj is EventEnvelope {
  if (!obj || typeof obj !== 'object') return false;
  const envelope = obj as Record<string, unknown>;
  return (
    typeof envelope.schema_version === 'string' &&
    typeof envelope.event_id === 'string' &&
    typeof envelope.event_type === 'string' &&
    typeof envelope.timestamp === 'string' &&
    typeof envelope.source === 'string' &&
    typeof envelope.payload === 'object'
  );
}

/**
 * Parse a raw event, handling both envelope and legacy formats
 */
export function parseEventData<T = Record<string, unknown>>(
  raw: unknown
): { envelope: EventEnvelope<T> | null; legacyEvent: { type: string; data: T } | null } {
  if (!raw || typeof raw !== 'object') {
    return { envelope: null, legacyEvent: null };
  }

  // Check if it's an envelope format
  if (isEventEnvelope(raw)) {
    return { envelope: raw as EventEnvelope<T>, legacyEvent: null };
  }

  // Check if it's legacy format { type: string, data: T }
  const legacy = raw as Record<string, unknown>;
  if (typeof legacy.type === 'string' && legacy.data !== undefined) {
    return {
      envelope: null,
      legacyEvent: { type: legacy.type, data: legacy.data as T },
    };
  }

  return { envelope: null, legacyEvent: null };
}

/**
 * Convert legacy event format to envelope format
 */
export function legacyToEnvelope<T = Record<string, unknown>>(
  type: AgentEventType,
  data: T,
  options?: {
    correlationId?: string | undefined;
    causationId?: string | undefined;
    metadata?: Record<string, unknown> | undefined;
  }
): EventEnvelope<T> {
  return {
    schema_version: '1.0',
    event_id: `evt_${generateShortId()}`,
    event_type: type,
    timestamp: new Date().toISOString(),
    source: 'memstack',
    correlation_id: options?.correlationId,
    causation_id: options?.causationId,
    payload: data,
    metadata: options?.metadata,
  };
}

/**
 * Extract correlation chain from an envelope
 */
export function getCorrelationChain(envelope: EventEnvelope): {
  correlationId: string | undefined;
  causationId: string | undefined;
  eventId: string;
} {
  return {
    correlationId: envelope.correlation_id,
    causationId: envelope.causation_id,
    eventId: envelope.event_id,
  };
}

/**
 * Create a child envelope from a parent (for event chaining)
 */
export function createChildEnvelope<T = Record<string, unknown>>(
  parent: EventEnvelope,
  eventType: AgentEventType,
  payload: T,
  extraMetadata?: Record<string, unknown>
): EventEnvelope<T> {
  return {
    schema_version: parent.schema_version,
    event_id: `evt_${generateShortId()}`,
    event_type: eventType,
    timestamp: new Date().toISOString(),
    source: parent.source,
    correlation_id: parent.correlation_id,
    causation_id: parent.event_id,
    payload,
    metadata: { ...parent.metadata, ...extraMetadata },
  };
}

/**
 * Generate a short unique ID (matches Python's uuid.uuid4().hex[:12])
 */
function generateShortId(): string {
  return Math.random().toString(36).substring(2, 14) + Math.random().toString(36).substring(2, 6);
}

/**
 * Current schema version constant
 */
export const CURRENT_SCHEMA_VERSION = '1.0';

/**
 * Event source constants
 */
export const EVENT_SOURCES = {
  MEMSTACK: 'memstack',
  FRONTEND: 'frontend',
  AGENT: 'agent',
  SANDBOX: 'sandbox',
} as const;

export type EventSource = (typeof EVENT_SOURCES)[keyof typeof EVENT_SOURCES];
