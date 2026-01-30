/**
 * Timeline Store - Split from monolithic agent store.
 *
 * This store manages timeline state for agent conversations.
 * Timeline is the unified event stream containing messages,
 * tool executions, and other conversation events.
 *
 * State managed:
 * - timeline: Array of TimelineEvent (unified event stream)
 * - timelineLoading: Loading state for initial timeline fetch
 * - isLoadingEarlier: Loading state for backward pagination (separate from timelineLoading)
 * - timelineError: Error message if timeline fetch fails
 * - earliestLoadedSequence: Pagination pointer for backward loading
 * - latestLoadedSequence: Pagination pointer for forward loading
 *
 * This store was split from agent.ts to improve maintainability
 * and follow single-responsibility principle.
 *
 * Uses Zustand for state management, consistent with the main agent store.
 *
 * @module stores/agent/timelineStore
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { agentService } from '../../services/agentService';
import type { TimelineEvent } from '../../types/agent';

/**
 * Timeline Store State
 */
interface TimelineState {
  // State
  timeline: TimelineEvent[];
  timelineLoading: boolean;
  isLoadingEarlier: boolean;  // Separate loading state for pagination
  timelineError: string | null;
  earliestLoadedSequence: number | null;
  latestLoadedSequence: number | null;
  hasEarlier: boolean;  // Whether there are earlier messages to load

  // Actions
  getTimeline: (conversationId: string, projectId: string) => Promise<void>;
  addTimelineEvent: (event: TimelineEvent) => void;
  clearTimeline: () => void;
  prependTimelineEvents: (events: TimelineEvent[]) => void;
  loadEarlierMessages: (conversationId: string, projectId: string) => Promise<boolean>;
  reset: () => void;
}

/**
 * Initial state for Timeline store
 */
export const initialState = {
  timeline: [],
  timelineLoading: false,
  isLoadingEarlier: false,
  timelineError: null,
  earliestLoadedSequence: null,
  latestLoadedSequence: null,
  hasEarlier: false,
};

/**
 * Timeline Store
 *
 * Zustand store for managing timeline state.
 */
export const useTimelineStore = create<TimelineState>()(
  devtools((set, get) => ({
  ...initialState,

  /**
   * Get timeline for conversation
   *
   * Fetches the timeline from the server and updates state.
   * Replaces existing timeline with new data.
   *
   * @param conversationId - The conversation ID
   * @param projectId - The project ID
   */
  getTimeline: async (conversationId: string, projectId: string) => {
    console.log('[TimelineStore] getTimeline called:', conversationId, projectId);
    set({ timelineLoading: true, timelineError: null });

    try {
      const response = await agentService.getConversationMessages(
        conversationId,
        projectId,
        50  // Changed from 100 to 50
      ) as any; // Type cast to access pagination metadata
      console.log('[TimelineStore] getTimeline response:', response.timeline.length, 'events');

      // Extract pagination metadata from response
      const firstSequence = response.timeline[0]?.sequenceNumber ?? null;
      const lastSequence = response.timeline[response.timeline.length - 1]?.sequenceNumber ?? null;

      set({
        timeline: response.timeline,
        timelineLoading: false,
        earliestLoadedSequence: firstSequence,
        latestLoadedSequence: lastSequence,
        hasEarlier: response.has_more ?? false,
      });
    } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
      console.error('[TimelineStore] getTimeline error:', error);
      set({
        timelineError: err?.response?.data?.detail || 'Failed to get timeline',
        timelineLoading: false,
      });
      throw error;
    }
  },

  /**
   * Add timeline event
   *
   * Adds a new event to the timeline with auto-incremented sequence number.
   *
   * @param event - The timeline event to add
   */
  addTimelineEvent: (event: TimelineEvent) => {
    const { timeline } = get();

    // Auto-assign sequence number if not provided
    const maxSeq = Math.max(0, ...timeline.map((e) => e.sequenceNumber));
    const sequenceNumber = event.sequenceNumber || maxSeq + 1;

    const newEvent: TimelineEvent = {
      ...event,
      sequenceNumber,
    };

    console.log('[TimelineStore] Adding timeline event:', newEvent.type, 'seq:', sequenceNumber);
    set({ timeline: [...timeline, newEvent] });
  },

  /**
   * Clear timeline
   *
   * Removes all events from the timeline.
   */
  clearTimeline: () => set({ timeline: [] }),

  /**
   * Prepend timeline events
   *
   * Adds new events at the beginning of the timeline.
   * Used for pagination when loading earlier messages.
   *
   * @param events - The events to prepend
   */
  prependTimelineEvents: (events: TimelineEvent[]) => {
    const { timeline } = get();
    // Add new events at the beginning of the timeline
    set({ timeline: [...events, ...timeline] });
  },

  /**
   * Load earlier messages
   *
   * Loads messages before the earliest loaded sequence (backward pagination).
   * Uses separate isLoadingEarlier state to avoid affecting UI loading indicators.
   *
   * @param conversationId - The conversation ID
   * @param projectId - The project ID
   * @returns Promise<boolean> - True if load was initiated, false if skipped
   */
  loadEarlierMessages: async (conversationId: string, projectId: string) => {
    const { earliestLoadedSequence, isLoadingEarlier } = get();

    // Guard: Don't load if already loading or no pagination point exists
    if (!earliestLoadedSequence || isLoadingEarlier) {
      console.log('[TimelineStore] Cannot load earlier messages: no pagination point or already loading');
      return false;
    }

    console.log('[TimelineStore] Loading earlier messages before sequence:', earliestLoadedSequence);
    // 使用独立的 isLoadingEarlier 状态，不影响 timelineLoading
    set({ isLoadingEarlier: true, timelineError: null });

    try {
      const response = await agentService.getConversationMessages(
        conversationId,
        projectId,
        50,  // Changed from 100 to 50
        undefined,  // from_sequence
        earliestLoadedSequence // before_sequence
      ) as any;

      // Prepend new events to existing timeline
      const { timeline } = get();
      const newTimeline = [...response.timeline, ...timeline];

      set({
        timeline: newTimeline,
        isLoadingEarlier: false,
        earliestLoadedSequence: response.timeline[0]?.sequenceNumber ?? null,
        hasEarlier: response.has_more ?? false,
      });

      return true;
    } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
      console.error('[TimelineStore] loadEarlierMessages error:', error);
      set({
        timelineError: err?.response?.data?.detail || 'Failed to load earlier messages',
        isLoadingEarlier: false,
      });
      throw error;
    }
  },

  /**
   * Reset store to initial state
   *
   * Completely resets all state in this store.
   */
  reset: () => {
    set(initialState);
  },
}),
{
  name: 'TimelineStore',
  enabled: import.meta.env.DEV,
}
)
);

/**
 * Derived selector: Get timeline events
 *
 * @returns Array of timeline events
 */
export const useTimeline = () => useTimelineStore((state) => state.timeline);

/**
 * Derived selector: Get timeline loading state (for initial load)
 *
 * @returns Boolean indicating if timeline is loading
 */
export const useTimelineLoading = () => useTimelineStore((state) => state.timelineLoading);

/**
 * Derived selector: Get isLoadingEarlier state (for pagination)
 *
 * @returns Boolean indicating if earlier messages are loading
 */
export const useIsLoadingEarlier = () => useTimelineStore((state) => state.isLoadingEarlier);

/**
 * Derived selector: Get timeline error
 *
 * @returns Error message or null
 */
export const useTimelineError = () => useTimelineStore((state) => state.timelineError);

/**
 * Derived selector: Get earliest loaded sequence
 *
 * @returns Earliest sequence number or null
 */
export const useEarliestLoadedSequence = () => useTimelineStore((state) => state.earliestLoadedSequence);

/**
 * Derived selector: Get latest loaded sequence
 *
 * @returns Latest sequence number or null
 */
export const useLatestLoadedSequence = () => useTimelineStore((state) => state.latestLoadedSequence);

/**
 * Derived selector: Get hasEarlier state
 *
 * @returns Whether there are earlier messages to load
 */
export const useHasEarlier = () => useTimelineStore((state) => state.hasEarlier);

/**
 * Derived selector: Get timeline with chat-specific fields
 *
 * Adds default fields expected by ChatArea component.
 *
 * @returns Timeline events with additional fields
 */
export const useTimelineWithChatFields = () =>
  useTimelineStore((state) =>
    state.timeline.map((event) => ({
      ...event,
      // These fields may not be present in all timeline events but are expected by ChatArea
      content: (event as any).content ?? '',
      role: (event as any).role ?? (event.type === 'user_message' ? 'user' : 'assistant'),
    }))
  );

/**
 * Type export for store (used in tests)
 */
export type TimelineStore = ReturnType<typeof useTimelineStore.getState>;
