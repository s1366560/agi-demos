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
 * - earliestTimeUs/earliestCounter: Pagination pointer for backward loading
 * - latestTimeUs/latestCounter: Pagination pointer for forward loading
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
  isLoadingEarlier: boolean; // Separate loading state for pagination
  timelineError: string | null;
  earliestTimeUs: number | null;
  earliestCounter: number | null;
  latestTimeUs: number | null;
  latestCounter: number | null;
  hasEarlier: boolean; // Whether there are earlier messages to load

  // Actions
  getTimeline: (conversationId: string, projectId: string) => Promise<void>;
  addTimelineEvent: (event: TimelineEvent) => void;
  clearTimeline: () => void;
  prependTimelineEvents: (events: TimelineEvent[]) => void;
  loadEarlierMessages: (conversationId: string, projectId: string) => Promise<boolean>;
  reset: () => void;
}

/**
 * Maximum number of timeline events kept in memory.
 * When exceeded, oldest events are trimmed from the front
 * and hasEarlier is set to true so they can be re-loaded via pagination.
 */
const MAX_TIMELINE_EVENTS = 2000;

/**
 * Initial state for Timeline store
 */
export const initialState = {
  timeline: [],
  timelineLoading: false,
  isLoadingEarlier: false,
  timelineError: null,
  earliestTimeUs: null,
  earliestCounter: null,
  latestTimeUs: null,
  latestCounter: null,
  hasEarlier: false,
};

/**
 * Timeline Store
 *
 * Zustand store for managing timeline state.
 */
export const useTimelineStore = create<TimelineState>()(
  devtools(
    (set, get) => ({
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
        set({ timelineLoading: true, timelineError: null });

        try {
          const response = (await agentService.getConversationMessages(
            conversationId,
            projectId,
            50 // Changed from 100 to 50
          )) as any; // Type cast to access pagination metadata

          // Extract pagination metadata from response
          const firstTimeUs = response.first_time_us ?? null;
          const firstCounter = response.first_counter ?? null;
          const lastTimeUs = response.last_time_us ?? null;
          const lastCounter = response.last_counter ?? null;

          set({
            timeline: response.timeline,
            timelineLoading: false,
            earliestTimeUs: firstTimeUs,
            earliestCounter: firstCounter,
            latestTimeUs: lastTimeUs,
            latestCounter: lastCounter,
            hasEarlier: response.has_more ?? false,
          });
        } catch (error: unknown) {
          const err = error as { response?: { data?: { detail?: string | undefined } | undefined } | undefined; message?: string | undefined };
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

        let newTimeline = [...timeline, event];
        if (newTimeline.length > MAX_TIMELINE_EVENTS) {
          newTimeline = newTimeline.slice(newTimeline.length - MAX_TIMELINE_EVENTS);
          set({ timeline: newTimeline, hasEarlier: true });
        } else {
          set({ timeline: newTimeline });
        }
      },

      /**
       * Clear timeline
       *
       * Removes all events from the timeline.
       */
      clearTimeline: () => { set({ timeline: [] }); },

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
        let newTimeline = [...events, ...timeline];
        if (newTimeline.length > MAX_TIMELINE_EVENTS) {
          newTimeline = newTimeline.slice(0, MAX_TIMELINE_EVENTS);
        }
        set({ timeline: newTimeline });
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
        const { earliestTimeUs, earliestCounter, isLoadingEarlier } = get();

        // Guard: Don't load if already loading or no pagination point exists
        if (!earliestTimeUs || isLoadingEarlier) {
          return false;
        }

        set({ isLoadingEarlier: true, timelineError: null });

        try {
          const response = (await agentService.getConversationMessages(
            conversationId,
            projectId,
            50,
            undefined, // fromTimeUs
            undefined, // fromCounter
            earliestTimeUs, // beforeTimeUs
            earliestCounter ?? undefined // beforeCounter
          )) as any;

          // Prepend new events to existing timeline
          const { timeline } = get();
          let newTimeline = [...response.timeline, ...timeline];
          if (newTimeline.length > MAX_TIMELINE_EVENTS) {
            newTimeline = newTimeline.slice(0, MAX_TIMELINE_EVENTS);
          }

          set({
            timeline: newTimeline,
            isLoadingEarlier: false,
            earliestTimeUs: response.first_time_us ?? null,
            earliestCounter: response.first_counter ?? null,
            hasEarlier: response.has_more ?? false,
          });

          return true;
        } catch (error: unknown) {
          const err = error as { response?: { data?: { detail?: string | undefined } | undefined } | undefined; message?: string | undefined };
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
 * Derived selector: Get earliest loaded time (microseconds)
 *
 * @returns Earliest time in microseconds or null
 */
export const useEarliestTimeUs = () => useTimelineStore((state) => state.earliestTimeUs);

/**
 * Derived selector: Get earliest loaded counter
 *
 * @returns Earliest counter or null
 */
export const useEarliestCounter = () => useTimelineStore((state) => state.earliestCounter);

/**
 * Derived selector: Get latest loaded time (microseconds)
 *
 * @returns Latest time in microseconds or null
 */
export const useLatestTimeUs = () => useTimelineStore((state) => state.latestTimeUs);

/**
 * Derived selector: Get latest loaded counter
 *
 * @returns Latest counter or null
 */
export const useLatestCounter = () => useTimelineStore((state) => state.latestCounter);

/**
 * Derived selector: Get hasEarlier state
 *
 * @returns Whether there are earlier messages to load
 */
export const useHasEarlier = () => useTimelineStore((state) => state.hasEarlier);

/**
 * Type export for store (used in tests)
 */
export type TimelineStore = ReturnType<typeof useTimelineStore.getState>;
