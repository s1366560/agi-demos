/**
 * Delta buffer management for per-conversation token batching.
 *
 * Extracted from agentV3.ts to reduce file size and improve maintainability.
 * Buffers batch rapid token/thought/act updates to reduce re-renders.
 *
 * Timeline commit buffer: batches timeline-appending SSE events so that
 * multiple events arriving within a short window produce a single
 * `updateConversationState` call instead of one per event.
 */

import { sseEventToTimeline } from '../../utils/sseEventAdapter';

import type { AgentEvent, TimelineEvent , ActDeltaEventData } from '../../types/agent';
import type { ConversationState } from '../../types/conversationState';

/**
 * Token delta batching configuration
 * Batches rapid token updates to reduce re-renders and improve performance
 */
export const TOKEN_BATCH_INTERVAL_MS = 50; // Batch tokens every 50ms for smooth streaming
export const THOUGHT_BATCH_INTERVAL_MS = 50; // Same for thought deltas

/**
 * Per-conversation delta buffer state
 * Using Map to isolate buffers per conversation, preventing cross-conversation contamination
 */
export interface DeltaBufferState {
  textDeltaBuffer: string;
  textDeltaFlushTimer: ReturnType<typeof setTimeout> | null;
  thoughtDeltaBuffer: string;
  thoughtDeltaFlushTimer: ReturnType<typeof setTimeout> | null;
  actDeltaBuffer: ActDeltaEventData | null;
  actDeltaFlushTimer: ReturnType<typeof setTimeout> | null;
}

const deltaBuffers = new Map<string, DeltaBufferState>();

/**
 * Get or create delta buffer state for a conversation
 */
export function getDeltaBuffer(conversationId: string): DeltaBufferState {
  let buffer = deltaBuffers.get(conversationId);
  if (!buffer) {
    buffer = {
      textDeltaBuffer: '',
      textDeltaFlushTimer: null,
      thoughtDeltaBuffer: '',
      thoughtDeltaFlushTimer: null,
      actDeltaBuffer: null,
      actDeltaFlushTimer: null,
    };
    deltaBuffers.set(conversationId, buffer);
  }
  return buffer;
}

/**
 * Clear delta buffers for a specific conversation
 * IMPORTANT: Call this before starting any new streaming session to prevent
 * stale buffer content from being flushed into the new session
 */
export function clearDeltaBuffers(conversationId: string): void {
  const buffer = deltaBuffers.get(conversationId);
  if (buffer) {
    if (buffer.textDeltaFlushTimer) {
      clearTimeout(buffer.textDeltaFlushTimer);
      buffer.textDeltaFlushTimer = null;
    }
    if (buffer.thoughtDeltaFlushTimer) {
      clearTimeout(buffer.thoughtDeltaFlushTimer);
      buffer.thoughtDeltaFlushTimer = null;
    }
    if (buffer.actDeltaFlushTimer) {
      clearTimeout(buffer.actDeltaFlushTimer);
      buffer.actDeltaFlushTimer = null;
    }
    buffer.textDeltaBuffer = '';
    buffer.thoughtDeltaBuffer = '';
    buffer.actDeltaBuffer = null;
  }
}

/**
 * Clear all delta buffers across all conversations
 * Used when switching conversations or on cleanup
 */
export function clearAllDeltaBuffers(): void {
  deltaBuffers.forEach((_buffer, conversationId) => {
    clearDeltaBuffers(conversationId);
  });
  deltaBuffers.clear();
}

/**
 * Delete a delta buffer entry for a conversation (after cleanup)
 */
export function deleteDeltaBuffer(conversationId: string): void {
  deltaBuffers.delete(conversationId);
}

// ---------------------------------------------------------------------------
// Timeline commit buffer
// ---------------------------------------------------------------------------

export const TIMELINE_BATCH_INTERVAL_MS = 100;

interface TimelineBufferEntry {
  event: AgentEvent<unknown>;
  stateUpdates: Partial<ConversationState> | null;
}

interface TimelineCommitBufferState {
  pendingEntries: TimelineBufferEntry[];
  flushTimer: ReturnType<typeof setTimeout> | null;
}

export interface TimelineBufferDeps {
  getConversationState: (conversationId: string) => ConversationState;
  updateConversationState: (conversationId: string, updates: Partial<ConversationState>) => void;
}

const timelineBuffers = new Map<string, TimelineCommitBufferState>();

function getTimelineBuffer(conversationId: string): TimelineCommitBufferState {
  let buf = timelineBuffers.get(conversationId);
  if (!buf) {
    buf = { pendingEntries: [], flushTimer: null };
    timelineBuffers.set(conversationId, buf);
  }
  return buf;
}

function flushNow(conversationId: string, deps: TimelineBufferDeps): void {
  const buf = timelineBuffers.get(conversationId);
  if (!buf || buf.pendingEntries.length === 0) return;

  const entries = buf.pendingEntries;
  buf.pendingEntries = [];

  if (buf.flushTimer) {
    clearTimeout(buf.flushTimer);
    buf.flushTimer = null;
  }

  const convState = deps.getConversationState(conversationId);
  let timeline = convState.timeline;

  let mergedStateUpdates: Partial<ConversationState> = {};

  for (const entry of entries) {
    const timelineEvent: TimelineEvent | null = sseEventToTimeline(entry.event);
    if (timelineEvent) {
      timeline = timeline.concat(timelineEvent);
    }
    if (entry.stateUpdates) {
      mergedStateUpdates = { ...mergedStateUpdates, ...entry.stateUpdates };
    }
  }

  deps.updateConversationState(conversationId, {
    ...mergedStateUpdates,
    timeline,
  });
}

let _boundDeps: Map<string, TimelineBufferDeps> = new Map();

export function bindTimelineBufferDeps(
  conversationId: string,
  deps: TimelineBufferDeps
): void {
  _boundDeps.set(conversationId, deps);
}

export function queueTimelineEvent(
  conversationId: string,
  event: AgentEvent<unknown>,
  immediateStateUpdates?: Partial<ConversationState>
): void {
  const buf = getTimelineBuffer(conversationId);
  buf.pendingEntries.push({
    event,
    stateUpdates: immediateStateUpdates ?? null,
  });

  if (!buf.flushTimer) {
    const deps = _boundDeps.get(conversationId);
    buf.flushTimer = setTimeout(() => {
      buf.flushTimer = null;
      if (deps) {
        flushNow(conversationId, deps);
      }
    }, TIMELINE_BATCH_INTERVAL_MS);
  }
}

export function flushTimelineBufferSync(conversationId: string): void {
  const deps = _boundDeps.get(conversationId);
  if (deps) {
    flushNow(conversationId, deps);
  }
}

export function clearTimelineBuffer(conversationId: string): void {
  const buf = timelineBuffers.get(conversationId);
  if (buf) {
    if (buf.flushTimer) {
      clearTimeout(buf.flushTimer);
      buf.flushTimer = null;
    }
    buf.pendingEntries = [];
  }
  _boundDeps.delete(conversationId);
}

export function clearAllTimelineBuffers(): void {
  timelineBuffers.forEach((_buf, cid) => {
    clearTimelineBuffer(cid);
  });
  timelineBuffers.clear();
  _boundDeps = new Map();
}
