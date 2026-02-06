/**
 * Streaming Store - Split from monolithic agent store.
 *
 * This store manages streaming state for agent conversations.
 * Streaming includes connection status and typewriter effect for
 * displaying assistant responses in real-time.
 *
 * State managed:
 * - isStreaming: Whether agent is currently streaming
 * - streamStatus: Current stream status (idle/connecting/streaming/error)
 * - assistantDraftContent: Draft content while typewriter streaming
 * - isTextStreaming: Whether typewriter effect is active
 *
 * This store was split from agent.ts to improve maintainability
 * and follow single-responsibility principle.
 *
 * Uses Zustand for state management, consistent with the main agent store.
 *
 * @module stores/agent/streamingStore
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

/**
 * Stream status type
 */
export type StreamStatus = 'idle' | 'connecting' | 'streaming' | 'error';

/**
 * Streaming Store State
 */
interface StreamingState {
  // State
  isStreaming: boolean;
  streamStatus: StreamStatus;
  assistantDraftContent: string;
  isTextStreaming: boolean;

  // Actions
  startStreaming: (status?: StreamStatus) => void;
  stopStreaming: () => void;
  setStreamStatus: (status: StreamStatus) => void;
  onTextStart: () => void;
  onTextDelta: (delta: string) => void;
  onTextEnd: (fullText?: string) => void;
  clearDraft: () => void;
  reset: () => void;
}

/**
 * Initial state for Streaming store
 */
export const initialState = {
  isStreaming: false,
  streamStatus: 'idle' as StreamStatus,
  assistantDraftContent: '',
  isTextStreaming: false,
};

/**
 * Streaming Store
 *
 * Zustand store for managing streaming state.
 */
export const useStreamingStore = create<StreamingState>()(
  devtools(
    (set) => ({
      ...initialState,

      /**
       * Start streaming
       *
       * Sets streaming to true and optionally sets the stream status.
       * Clears draft content and text streaming flag.
       *
       * @param status - Optional stream status (default: 'connecting')
       */
      startStreaming: (status: StreamStatus = 'connecting') => {
        set({
          isStreaming: true,
          streamStatus: status,
          assistantDraftContent: '',
          isTextStreaming: false,
        });
      },

      /**
       * Stop streaming
       *
       * Resets all streaming state to initial values.
       */
      stopStreaming: () => {
        set({
          isStreaming: false,
          streamStatus: 'idle',
          assistantDraftContent: '',
          isTextStreaming: false,
        });
      },

      /**
       * Set stream status
       *
       * Updates the stream status without changing other state.
       *
       * @param status - The new stream status
       */
      setStreamStatus: (status: StreamStatus) => {
        set({ streamStatus: status });
      },

      /**
       * Start typewriter effect
       *
       * Clears draft content and sets text streaming to true.
       */
      onTextStart: () => {
        set({
          assistantDraftContent: '',
          isTextStreaming: true,
        });
      },

      /**
       * Append text delta to draft content
       *
       * Appends the delta to the current draft content.
       *
       * @param delta - The text delta to append
       */
      onTextDelta: (delta: string) => {
        set((state) => ({
          assistantDraftContent: state.assistantDraftContent + delta,
        }));
      },

      /**
       * End typewriter effect
       *
       * Optionally sets final content and sets text streaming to false.
       * Empty string fullText is treated as "use existing content".
       *
       * @param fullText - Optional final text content
       */
      onTextEnd: (fullText?: string) => {
        set((state) => ({
          assistantDraftContent: fullText || state.assistantDraftContent,
          isTextStreaming: false,
        }));
      },

      /**
       * Clear draft content
       *
       * Clears draft content and sets text streaming to false.
       */
      clearDraft: () => {
        set({
          assistantDraftContent: '',
          isTextStreaming: false,
        });
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
      name: 'StreamingStore',
      enabled: import.meta.env.DEV,
    }
  )
);

/**
 * Derived selector: Check if actively streaming
 *
 * Returns true when streamStatus is 'streaming' or 'connecting'
 *
 * @returns Boolean indicating if actively streaming
 */
export const useIsActiveStreaming = () =>
  useStreamingStore((state) => state.isStreaming && state.streamStatus !== 'idle');

/**
 * Derived selector: Get draft content length
 *
 * @returns Length of draft content in characters
 */
export const useDraftContentLength = () =>
  useStreamingStore((state) => state.assistantDraftContent.length);

/**
 * Type export for store (used in tests)
 */
export type StreamingStore = ReturnType<typeof useStreamingStore.getState>;
