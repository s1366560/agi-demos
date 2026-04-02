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

import type { TimelineEvent, ConversationMessagesResponse, Message } from '../../types/agent';

/**
 * Timeline Store State
 */
interface TimelineState {
  // State
  timeline: TimelineEvent[];
  timelineLoading: boolean;
  isLoadingEarlier: boolean;
  timelineError: string | null;
  earliestTimeUs: number | null;
  earliestCounter: number | null;
  latestTimeUs: number | null;
  latestCounter: number | null;
  hasEarlier: boolean;

  // Agent-level state (migrating from agentV3, Wave 6a)
  agentTimeline: TimelineEvent[];
  agentMessages: Message[];
  agentIsLoadingHistory: boolean;
  agentIsLoadingEarlier: boolean;
  agentHasEarlier: boolean;
  agentEarliestTimeUs: number | null;
  agentEarliestCounter: number | null;

  // Actions
  getTimeline: (conversationId: string, projectId: string) => Promise<void>;
  addTimelineEvent: (event: TimelineEvent) => void;
  clearTimeline: () => void;
  prependTimelineEvents: (events: TimelineEvent[]) => void;
  loadEarlierMessages: (conversationId: string, projectId: string) => Promise<boolean>;
  reset: () => void;

  // Agent-level setters (Wave 6a)
  setAgentTimeline: (timeline: TimelineEvent[]) => void;
  setAgentMessages: (messages: Message[]) => void;
  setAgentIsLoadingHistory: (value: boolean) => void;
  setAgentIsLoadingEarlier: (value: boolean) => void;
  setAgentHasEarlier: (value: boolean) => void;
  setAgentEarliestPointers: (timeUs: number | null, counter: number | null) => void;
  resetAgentTimeline: () => void;
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
const agentTimelineInitialState = {
  agentTimeline: [] as TimelineEvent[],
  agentMessages: [] as Message[],
  agentIsLoadingHistory: false,
  agentIsLoadingEarlier: false,
  agentHasEarlier: false,
  agentEarliestTimeUs: null as number | null,
  agentEarliestCounter: null as number | null,
};

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
  ...agentTimelineInitialState,
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
          const response: ConversationMessagesResponse = await agentService.getConversationMessages(
            conversationId,
            projectId,
            50 // Changed from 100 to 50
          );

          set({
            timeline: response.timeline,
            timelineLoading: false,
            earliestTimeUs: response.first_time_us,
            earliestCounter: response.first_counter,
            latestTimeUs: response.last_time_us,
            latestCounter: response.last_counter,
            hasEarlier: response.has_more,
          });
        } catch (error: unknown) {
          const err = error as {
            response?: { data?: { detail?: string } };
            message?: string;
          };
          console.error('[TimelineStore] getTimeline error:', error);
          set({
            timelineError: err.response?.data?.detail || 'Failed to get timeline',
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

        let newTimeline = timeline.concat(event);
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
      clearTimeline: () => {
        set({ timeline: [] });
      },

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
          const response: ConversationMessagesResponse = await agentService.getConversationMessages(
            conversationId,
            projectId,
            50,
            undefined, // fromTimeUs
            undefined, // fromCounter
            earliestTimeUs, // beforeTimeUs
            earliestCounter ?? undefined // beforeCounter
          );

          // Prepend new events to existing timeline
          const { timeline } = get();
          let newTimeline = response.timeline.concat(timeline);
          if (newTimeline.length > MAX_TIMELINE_EVENTS) {
            newTimeline = newTimeline.slice(0, MAX_TIMELINE_EVENTS);
          }

          set({
            timeline: newTimeline,
            isLoadingEarlier: false,
            earliestTimeUs: response.first_time_us,
            earliestCounter: response.first_counter,
            hasEarlier: response.has_more,
          });

          return true;
        } catch (error: unknown) {
          const err = error as {
            response?: { data?: { detail?: string } };
            message?: string;
          };
          console.error('[TimelineStore] loadEarlierMessages error:', error);
          set({
            timelineError: err.response?.data?.detail || 'Failed to load earlier messages',
            isLoadingEarlier: false,
          });
          throw error;
        }
      },

      setAgentTimeline: (timeline: TimelineEvent[]) => {
        set({ agentTimeline: timeline });
      },

      setAgentMessages: (messages: Message[]) => {
        set({ agentMessages: messages });
      },

      setAgentIsLoadingHistory: (value: boolean) => {
        set({ agentIsLoadingHistory: value });
      },

      setAgentIsLoadingEarlier: (value: boolean) => {
        set({ agentIsLoadingEarlier: value });
      },

      setAgentHasEarlier: (value: boolean) => {
        set({ agentHasEarlier: value });
      },

      setAgentEarliestPointers: (timeUs: number | null, counter: number | null) => {
        set({ agentEarliestTimeUs: timeUs, agentEarliestCounter: counter });
      },

      resetAgentTimeline: () => {
        set(agentTimelineInitialState);
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

// Native selectors — read from timelineStore's own state (used by tests and internal actions)

export const useTimelineLoading = () => useTimelineStore((state) => state.timelineLoading);
export const useTimelineError = () => useTimelineStore((state) => state.timelineError);
export const useEarliestTimeUs = () => useTimelineStore((state) => state.earliestTimeUs);
export const useEarliestCounter = () => useTimelineStore((state) => state.earliestCounter);
export const useLatestTimeUs = () => useTimelineStore((state) => state.latestTimeUs);
export const useLatestCounter = () => useTimelineStore((state) => state.latestCounter);

// Bridge selectors — read from timelineStore's own agent-level fields.

export const useTimeline = () => useTimelineStore((s) => s.agentTimeline);
export const useMessages = () => useTimelineStore((s) => s.agentMessages);
export const useIsLoadingHistory = () => useTimelineStore((s) => s.agentIsLoadingHistory);
export const useIsLoadingEarlier = () => useTimelineStore((s) => s.agentIsLoadingEarlier);
export const useHasEarlier = () => useTimelineStore((s) => s.agentHasEarlier);

/**
 * Type export for store (used in tests)
 */
export type TimelineStore = ReturnType<typeof useTimelineStore.getState>;
