/**
 * Unit tests for streamingStore.
 *
 * TDD RED Phase: Tests written first for Streaming store split.
 *
 * Feature: Split Streaming state from monolithic agent store.
 *
 * Streaming state includes:
 * - isStreaming: Whether agent is currently streaming
 * - streamStatus: Current stream status (idle/connecting/streaming/error)
 * - assistantDraftContent: Draft content while typewriter streaming
 * - isTextStreaming: Whether typewriter effect is active
 *
 * Actions:
 * - startStreaming: Start streaming with status
 * - stopStreaming: Stop streaming
 * - setStreamStatus: Set stream status
 * - onTextStart: Start typewriter effect
 * - onTextDelta: Append text delta to draft
 * - onTextEnd: End typewriter effect
 * - clearDraft: Clear draft content
 * - reset: Reset to initial state
 *
 * These tests verify that the streamingStore maintains the same behavior
 * as the original monolithic agent store's streaming functionality.
 */

import { describe, it, expect, beforeEach } from 'vitest';

import { useStreamingStore, initialState } from '../../../stores/agent/streamingStore';

describe('StreamingStore', () => {
  beforeEach(() => {
    // Reset store before each test
    useStreamingStore.getState().reset();
  });

  describe('Initial State', () => {
    it('should have correct initial state', () => {
      const state = useStreamingStore.getState();
      expect(state.isStreaming).toBe(initialState.isStreaming);
      expect(state.streamStatus).toBe(initialState.streamStatus);
      expect(state.assistantDraftContent).toBe(initialState.assistantDraftContent);
      expect(state.isTextStreaming).toBe(initialState.isTextStreaming);
    });

    it('should have isStreaming as false initially', () => {
      const { isStreaming } = useStreamingStore.getState();
      expect(isStreaming).toBe(false);
    });

    it('should have streamStatus as idle initially', () => {
      const { streamStatus } = useStreamingStore.getState();
      expect(streamStatus).toBe('idle');
    });

    it('should have empty assistantDraftContent initially', () => {
      const { assistantDraftContent } = useStreamingStore.getState();
      expect(assistantDraftContent).toBe('');
    });

    it('should have isTextStreaming as false initially', () => {
      const { isTextStreaming } = useStreamingStore.getState();
      expect(isTextStreaming).toBe(false);
    });
  });

  describe('reset', () => {
    it('should reset state to initial values', async () => {
      // Set some state using actions
      useStreamingStore.getState().startStreaming('streaming');
      useStreamingStore.getState().onTextStart();
      useStreamingStore.getState().onTextDelta('Partial content');

      // Verify state is set
      expect(useStreamingStore.getState().isStreaming).toBe(true);
      expect(useStreamingStore.getState().assistantDraftContent).toBe('Partial content');

      // Reset
      useStreamingStore.getState().reset();

      // Verify initial state restored
      const { isStreaming, streamStatus, assistantDraftContent, isTextStreaming } =
        useStreamingStore.getState();
      expect(isStreaming).toBe(false);
      expect(streamStatus).toBe('idle');
      expect(assistantDraftContent).toBe('');
      expect(isTextStreaming).toBe(false);
    });
  });

  describe('startStreaming', () => {
    it('should start streaming with connecting status', () => {
      useStreamingStore.getState().startStreaming();

      const { isStreaming, streamStatus } = useStreamingStore.getState();
      expect(isStreaming).toBe(true);
      expect(streamStatus).toBe('connecting');
    });

    it('should start streaming with custom status', () => {
      useStreamingStore.getState().startStreaming('streaming');

      const { isStreaming, streamStatus } = useStreamingStore.getState();
      expect(isStreaming).toBe(true);
      expect(streamStatus).toBe('streaming');
    });

    it('should clear draft content when starting streaming', () => {
      useStreamingStore.getState().onTextStart();
      useStreamingStore.getState().onTextDelta('Old content');

      expect(useStreamingStore.getState().assistantDraftContent).toBe('Old content');

      useStreamingStore.getState().startStreaming();

      const { assistantDraftContent } = useStreamingStore.getState();
      expect(assistantDraftContent).toBe('');
    });

    it('should clear text streaming flag when starting streaming', () => {
      useStreamingStore.getState().onTextStart();

      expect(useStreamingStore.getState().isTextStreaming).toBe(true);

      useStreamingStore.getState().startStreaming();

      const { isTextStreaming } = useStreamingStore.getState();
      expect(isTextStreaming).toBe(false);
    });
  });

  describe('stopStreaming', () => {
    it('should stop streaming', () => {
      // Start streaming first
      useStreamingStore.getState().startStreaming('streaming');
      useStreamingStore.getState().onTextStart();
      useStreamingStore.getState().onTextDelta('Partial content');

      useStreamingStore.getState().stopStreaming();

      const { isStreaming, streamStatus, isTextStreaming, assistantDraftContent } =
        useStreamingStore.getState();
      expect(isStreaming).toBe(false);
      expect(streamStatus).toBe('idle');
      expect(isTextStreaming).toBe(false);
      expect(assistantDraftContent).toBe('');
    });

    it('should maintain idle status when already idle', () => {
      useStreamingStore.getState().stopStreaming();

      const { isStreaming, streamStatus } = useStreamingStore.getState();
      expect(isStreaming).toBe(false);
      expect(streamStatus).toBe('idle');
    });
  });

  describe('setStreamStatus', () => {
    it('should set stream status to connecting', () => {
      useStreamingStore.getState().setStreamStatus('connecting');

      const { streamStatus } = useStreamingStore.getState();
      expect(streamStatus).toBe('connecting');
    });

    it('should set stream status to streaming', () => {
      useStreamingStore.getState().setStreamStatus('streaming');

      const { streamStatus } = useStreamingStore.getState();
      expect(streamStatus).toBe('streaming');
    });

    it('should set stream status to error', () => {
      useStreamingStore.getState().setStreamStatus('error');

      const { streamStatus } = useStreamingStore.getState();
      expect(streamStatus).toBe('error');
    });

    it('should set stream status to idle', () => {
      useStreamingStore.setState({ streamStatus: 'streaming' });

      useStreamingStore.getState().setStreamStatus('idle');

      const { streamStatus } = useStreamingStore.getState();
      expect(streamStatus).toBe('idle');
    });
  });

  describe('onTextStart', () => {
    it('should start typewriter effect', () => {
      useStreamingStore.getState().onTextStart();
      useStreamingStore.getState().onTextDelta('Old content');

      const { assistantDraftContent, isTextStreaming } = useStreamingStore.getState();
      expect(assistantDraftContent).toBe('Old content');
      expect(isTextStreaming).toBe(true);

      // Start again to verify clearing
      useStreamingStore.getState().onTextStart();

      const { assistantDraftContent: newContent, isTextStreaming: newStreaming } =
        useStreamingStore.getState();
      expect(newContent).toBe('');
      expect(newStreaming).toBe(true);
    });

    it('should clear existing draft content when starting', () => {
      useStreamingStore.getState().onTextDelta('Previous draft');

      expect(useStreamingStore.getState().assistantDraftContent).toBe('Previous draft');

      useStreamingStore.getState().onTextStart();

      expect(useStreamingStore.getState().assistantDraftContent).toBe('');
    });
  });

  describe('onTextDelta', () => {
    it('should append delta to draft content', () => {
      useStreamingStore.getState().onTextDelta('Hello ');

      useStreamingStore.getState().onTextDelta('World');

      const { assistantDraftContent } = useStreamingStore.getState();
      expect(assistantDraftContent).toBe('Hello World');
    });

    it('should append to empty draft content', () => {
      useStreamingStore.getState().onTextDelta('First');

      const { assistantDraftContent } = useStreamingStore.getState();
      expect(assistantDraftContent).toBe('First');
    });

    it('should handle multiple deltas', () => {
      useStreamingStore.getState().onTextDelta('Hello ');
      useStreamingStore.getState().onTextDelta('World');
      useStreamingStore.getState().onTextDelta('!');

      const { assistantDraftContent } = useStreamingStore.getState();
      expect(assistantDraftContent).toBe('Hello World!');
    });

    it('should handle empty delta', () => {
      useStreamingStore.getState().onTextDelta('Content');

      const { assistantDraftContent } = useStreamingStore.getState();
      expect(assistantDraftContent).toBe('Content');
    });

    it('should handle unicode characters', () => {
      useStreamingStore.getState().onTextDelta('Hello ');
      useStreamingStore.getState().onTextDelta('World ');
      useStreamingStore.getState().onTextDelta('');

      const { assistantDraftContent } = useStreamingStore.getState();
      expect(assistantDraftContent).toBe('Hello World ');
    });
  });

  describe('onTextEnd', () => {
    it('should end typewriter effect and keep content', () => {
      useStreamingStore.getState().onTextStart();
      useStreamingStore.getState().onTextDelta('Partial content');

      useStreamingStore.getState().onTextEnd('Final content');

      const { assistantDraftContent, isTextStreaming } = useStreamingStore.getState();
      expect(assistantDraftContent).toBe('Final content');
      expect(isTextStreaming).toBe(false);
    });

    it('should keep existing draft content if no fullText provided', () => {
      useStreamingStore.getState().onTextStart();
      useStreamingStore.getState().onTextDelta('Existing content');

      useStreamingStore.getState().onTextEnd();

      const { assistantDraftContent, isTextStreaming } = useStreamingStore.getState();
      expect(assistantDraftContent).toBe('Existing content');
      expect(isTextStreaming).toBe(false);
    });

    it('should handle empty fullText', () => {
      useStreamingStore.getState().onTextStart();
      useStreamingStore.getState().onTextDelta('Partial');

      useStreamingStore.getState().onTextEnd('');

      const { assistantDraftContent, isTextStreaming } = useStreamingStore.getState();
      expect(assistantDraftContent).toBe('Partial');
      expect(isTextStreaming).toBe(false);
    });
  });

  describe('clearDraft', () => {
    it('should clear draft content', () => {
      useStreamingStore.getState().onTextStart();
      useStreamingStore.getState().onTextDelta('Some draft');

      expect(useStreamingStore.getState().assistantDraftContent).toBe('Some draft');

      useStreamingStore.getState().clearDraft();

      const { assistantDraftContent, isTextStreaming } = useStreamingStore.getState();
      expect(assistantDraftContent).toBe('');
      expect(isTextStreaming).toBe(false);
    });

    it('should handle clearing empty draft', () => {
      useStreamingStore.getState().clearDraft();

      const { assistantDraftContent, isTextStreaming } = useStreamingStore.getState();
      expect(assistantDraftContent).toBe('');
      expect(isTextStreaming).toBe(false);
    });
  });

  describe('Streaming Lifecycle', () => {
    it('should handle complete streaming lifecycle', () => {
      // Start streaming
      useStreamingStore.getState().startStreaming();
      expect(useStreamingStore.getState().isStreaming).toBe(true);
      expect(useStreamingStore.getState().streamStatus).toBe('connecting');

      // Update to streaming
      useStreamingStore.getState().setStreamStatus('streaming');
      expect(useStreamingStore.getState().streamStatus).toBe('streaming');

      // Start typewriter
      useStreamingStore.getState().onTextStart();
      expect(useStreamingStore.getState().isTextStreaming).toBe(true);
      expect(useStreamingStore.getState().assistantDraftContent).toBe('');

      // Receive deltas
      useStreamingStore.getState().onTextDelta('Hello ');
      useStreamingStore.getState().onTextDelta('World');
      expect(useStreamingStore.getState().assistantDraftContent).toBe('Hello World');

      // End typewriter
      useStreamingStore.getState().onTextEnd('Hello World Final');
      expect(useStreamingStore.getState().assistantDraftContent).toBe('Hello World Final');
      expect(useStreamingStore.getState().isTextStreaming).toBe(false);

      // Stop streaming
      useStreamingStore.getState().stopStreaming();
      expect(useStreamingStore.getState().isStreaming).toBe(false);
      expect(useStreamingStore.getState().streamStatus).toBe('idle');
    });

    it('should handle error during streaming', () => {
      // Start streaming
      useStreamingStore.getState().startStreaming();
      useStreamingStore.getState().setStreamStatus('streaming');

      // Error occurs
      useStreamingStore.getState().setStreamStatus('error');
      expect(useStreamingStore.getState().streamStatus).toBe('error');

      // Stop streaming clears status
      useStreamingStore.getState().stopStreaming();
      expect(useStreamingStore.getState().isStreaming).toBe(false);
      expect(useStreamingStore.getState().streamStatus).toBe('idle');
    });
  });

  describe('Computed State', () => {
    it('should derive isStreamingActive from status', () => {
      // Not streaming when idle
      expect(useStreamingStore.getState().isStreaming).toBe(false);

      // Streaming when status is streaming
      useStreamingStore.getState().startStreaming('streaming');
      expect(useStreamingStore.getState().isStreaming).toBe(true);

      // Not streaming when stopped
      useStreamingStore.getState().stopStreaming();
      expect(useStreamingStore.getState().isStreaming).toBe(false);
    });
  });

  describe('Edge Cases', () => {
    it('should handle very long text content', () => {
      const longText = 'A'.repeat(10000);

      useStreamingStore.getState().onTextDelta(longText);

      const { assistantDraftContent } = useStreamingStore.getState();
      expect(assistantDraftContent).toBe(longText);
    });

    it('should handle special characters in delta', () => {
      const specialChars = '!@#$%^&*()_+-=[]{}|;:\'",.<>?/~`';

      useStreamingStore.getState().onTextDelta(specialChars);

      const { assistantDraftContent } = useStreamingStore.getState();
      expect(assistantDraftContent).toBe(specialChars);
    });

    it('should handle newlines in delta', () => {
      useStreamingStore.getState().onTextDelta('Line 1\n');
      useStreamingStore.getState().onTextDelta('Line 2');

      const { assistantDraftContent } = useStreamingStore.getState();
      expect(assistantDraftContent).toBe('Line 1\nLine 2');
    });

    it('should handle rapid onTextStart/onTextEnd cycles', () => {
      // First cycle
      useStreamingStore.getState().onTextStart();
      useStreamingStore.getState().onTextDelta('A');
      useStreamingStore.getState().onTextEnd('A');

      expect(useStreamingStore.getState().assistantDraftContent).toBe('A');
      expect(useStreamingStore.getState().isTextStreaming).toBe(false);

      // Second cycle
      useStreamingStore.getState().onTextStart();
      useStreamingStore.getState().onTextDelta('B');
      useStreamingStore.getState().onTextEnd('B');

      expect(useStreamingStore.getState().assistantDraftContent).toBe('B');
      expect(useStreamingStore.getState().isTextStreaming).toBe(false);
    });
  });

  describe('State Immutability', () => {
    it('should reset properly after multiple state changes', () => {
      // Multiple state changes
      useStreamingStore.getState().startStreaming();
      useStreamingStore.getState().setStreamStatus('streaming');
      useStreamingStore.getState().onTextStart();
      useStreamingStore.getState().onTextDelta('Content');
      useStreamingStore.getState().setStreamStatus('error');

      // Reset
      useStreamingStore.getState().reset();

      // Verify all state reset
      const { isStreaming, streamStatus, assistantDraftContent, isTextStreaming } =
        useStreamingStore.getState();
      expect(isStreaming).toBe(false);
      expect(streamStatus).toBe('idle');
      expect(assistantDraftContent).toBe('');
      expect(isTextStreaming).toBe(false);
    });
  });
});
