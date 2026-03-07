/**
 * Conversation state persistence with debounced saves and LRU eviction.
 *
 * Extracted from agentV3.ts to reduce file size and improve maintainability.
 * Handles IndexedDB persistence, LRU cache eviction, and beforeunload flushing.
 *
 * NOTE: flushPendingSaves() uses a lazy import of useAgentV3Store to break
 * the circular dependency (persistence -> store -> persistence).
 */

import { saveConversationState } from '../../utils/conversationDB';

import type { ConversationState } from '../../types/conversationState';

/**
 * Maximum number of conversation states to keep in memory.
 * When exceeded, the least-recently-accessed non-active, non-streaming
 * conversations are evicted to prevent unbounded memory growth.
 * Evicted conversations can be re-loaded from server on demand.
 */
export const MAX_CACHED_CONVERSATIONS = 10;

/**
 * Pending save state for beforeunload flush
 */
const pendingSaves = new Map<string, NodeJS.Timeout>();
const SAVE_DEBOUNCE_MS = 500;

/**
 * LRU access order tracking for conversation state cache eviction.
 * Most recently accessed conversation ID is at the end.
 */
const conversationAccessOrder: string[] = [];

/**
 * Record a conversation as recently accessed (move to end of LRU list)
 */
export function touchConversation(conversationId: string): void {
  const idx = conversationAccessOrder.indexOf(conversationId);
  if (idx !== -1) {
    conversationAccessOrder.splice(idx, 1);
  }
  conversationAccessOrder.push(conversationId);
}

/**
 * Evict least-recently-used conversation states when cache exceeds limit.
 * Skips the active conversation and any currently streaming conversations.
 * Evicted conversations are persisted to IndexedDB before removal.
 */
export function evictStaleConversationStates(
  states: Map<string, ConversationState>,
  activeId: string | null
): Map<string, ConversationState> {
  if (states.size <= MAX_CACHED_CONVERSATIONS) {
    return states;
  }

  const newStates = new Map(states);
  const evictCount = newStates.size - MAX_CACHED_CONVERSATIONS;
  let evicted = 0;

  // Walk LRU list from oldest (front) to newest
  for (let i = 0; i < conversationAccessOrder.length && evicted < evictCount; i++) {
    const id = conversationAccessOrder[i];
    if (!id || id === activeId) continue;
    const convState = newStates.get(id);
    if (convState?.isStreaming) continue;

    // Persist to IndexedDB before eviction
    if (convState) {
      saveConversationState(id, convState).catch(console.error);
    }
    newStates.delete(id);
    conversationAccessOrder.splice(i, 1);
    i--;
    evicted++;
  }

  return newStates;
}

/**
 * Schedule a debounced save for a conversation
 */
export function scheduleSave(conversationId: string, state: ConversationState): void {
  // Clear existing timer
  const existingTimer = pendingSaves.get(conversationId);
  if (existingTimer) {
    clearTimeout(existingTimer);
  }

  // Schedule new save
  const timer = setTimeout(() => {
    saveConversationState(conversationId, state).catch(console.error);
    pendingSaves.delete(conversationId);
  }, SAVE_DEBOUNCE_MS);

  pendingSaves.set(conversationId, timer);
}

/**
 * Flush all pending saves immediately (for beforeunload).
 * Uses lazy import to avoid circular dependency with the store.
 */
export async function flushPendingSaves(): Promise<void> {
  // Clear all timers
  pendingSaves.forEach((timer) => {
    clearTimeout(timer);
  });
  pendingSaves.clear();

  // Lazy import to break circular dependency
  const { useAgentV3Store } = await import('../agentV3');

  // Get current store state and save all conversation states
  const state = useAgentV3Store.getState();
  const savePromises: Promise<void>[] = [];

  state.conversationStates.forEach((convState: ConversationState, conversationId: string) => {
    savePromises.push(saveConversationState(conversationId, convState).catch(console.error));
  });

  await Promise.all(savePromises);
}

// Register beforeunload handler for reliable persistence
if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', () => {
    // Use synchronous approach for beforeunload
    // Note: IndexedDB operations may not complete, but we try our best
    flushPendingSaves();
  });

  // Also handle visibilitychange for mobile browsers
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      flushPendingSaves();
    }
  });
}

/**
 * Cancel a pending save for a conversation and remove from pending map.
 */
export function cancelPendingSave(conversationId: string): void {
  const timer = pendingSaves.get(conversationId);
  if (timer) {
    clearTimeout(timer);
    pendingSaves.delete(conversationId);
  }
}

/**
 * Remove a conversation from LRU access order tracking.
 */
export function removeFromAccessOrder(conversationId: string): void {
  const idx = conversationAccessOrder.indexOf(conversationId);
  if (idx !== -1) {
    conversationAccessOrder.splice(idx, 1);
  }
}
