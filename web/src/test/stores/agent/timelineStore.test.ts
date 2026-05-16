/**
 * Unit tests for timelineStore.
 *
 * TDD RED Phase: Tests written first for Timeline store split.
 *
 * Feature: Split Timeline state from monolithic agent store.
 *
 * Timeline state includes:
 * - timeline: Array of TimelineEvent (unified event stream)
 * - timelineLoading: Loading state for timeline fetch
 * - timelineError: Error message if timeline fetch fails
 * - earliestLoadedSequence: Pagination pointer for backward loading
 * - latestLoadedSequence: Pagination pointer for forward loading
 *
 * Actions:
 * - getTimeline: Fetch timeline for conversation
 * - addTimelineEvent: Add new event to timeline
 * - clearTimeline: Clear all timeline events
 * - prependTimelineEvents: Prepend events (for pagination)
 * - loadEarlierMessages: Load earlier messages via backward pagination
 * - reset: Reset to initial state
 *
 * These tests verify that the timelineStore maintains the same behavior
 * as the original monolithic agent store's timeline functionality.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';

import { agentService } from '../../../services/agentService';
import { useTimelineStore, initialState } from '../../../stores/agent/timelineStore';
// Helper to create mock timeline response matching the full type
const createMockResponse = (
  timeline: any[],
  total: number,
  overrides?: {
    has_more?: boolean;
    first_time_us?: number | null;
    first_counter?: number | null;
    last_time_us?: number | null;
    last_counter?: number | null;
  }
) => ({
  conversationId: 'mock-conv-id',
  timeline,
  total,
  has_more: overrides?.has_more ?? false,
  first_time_us: overrides?.first_time_us ?? timeline[0]?.time_us ?? null,
  first_counter: overrides?.first_counter ?? timeline[0]?.counter ?? null,
  last_time_us: overrides?.last_time_us ?? timeline[timeline.length - 1]?.time_us ?? null,
  last_counter: overrides?.last_counter ?? timeline[timeline.length - 1]?.counter ?? null,
});

// Mock agent service
vi.mock('../../../services/agentService', () => ({
  agentService: {
    getConversationMessages: vi.fn(),
  },
}));

// Helper to access mocked method
const getConversationMessages = vi.mocked(agentService.getConversationMessages);

describe('TimelineStore', () => {
  beforeEach(() => {
    // Reset store before each test
    useTimelineStore.getState().reset();
    vi.clearAllMocks();
  });

  describe('Initial State', () => {
    it('should have correct initial state', () => {
      const state = useTimelineStore.getState();
      expect(state.timeline).toEqual(initialState.timeline);
      expect(state.timelineLoading).toBe(initialState.timelineLoading);
      expect(state.timelineError).toBe(initialState.timelineError);
      expect(state.earliestLoadedSequence).toBe(initialState.earliestLoadedSequence);
      expect(state.latestLoadedSequence).toBe(initialState.latestLoadedSequence);
    });

    it('should have empty timeline initially', () => {
      const { timeline } = useTimelineStore.getState();
      expect(timeline).toEqual([]);
    });

    it('should have timelineLoading as false initially', () => {
      const { timelineLoading } = useTimelineStore.getState();
      expect(timelineLoading).toBe(false);
    });

    it('should have timelineError as null initially', () => {
      const { timelineError } = useTimelineStore.getState();
      expect(timelineError).toBe(null);
    });

    it('should have null pagination pointers initially', () => {
      const { earliestTimeUs, earliestCounter, latestTimeUs, latestCounter } =
        useTimelineStore.getState();
      expect(earliestTimeUs).toBe(null);
      expect(earliestCounter).toBe(null);
      expect(latestTimeUs).toBe(null);
      expect(latestCounter).toBe(null);
    });
  });

  describe('reset', () => {
    it('should reset state to initial values', async () => {
      // Set some state
      useTimelineStore.setState({
        timeline: [{ id: '1', type: 'user_message', sequenceNumber: 1 } as any],
        timelineLoading: true,
        timelineError: 'Error',
        earliestTimeUs: 1000,
        earliestCounter: 1,
        latestTimeUs: 2000,
        latestCounter: 2,
      });

      // Verify state is set
      expect(useTimelineStore.getState().timeline).toHaveLength(1);
      expect(useTimelineStore.getState().timelineLoading).toBe(true);

      // Reset
      useTimelineStore.getState().reset();

      // Verify initial state restored
      const {
        timeline,
        timelineLoading,
        timelineError,
        earliestTimeUs,
        earliestCounter,
        latestTimeUs,
        latestCounter,
      } = useTimelineStore.getState();
      expect(timeline).toEqual([]);
      expect(timelineLoading).toBe(false);
      expect(timelineError).toBe(null);
      expect(earliestTimeUs).toBe(null);
      expect(earliestCounter).toBe(null);
      expect(latestTimeUs).toBe(null);
      expect(latestCounter).toBe(null);
    });
  });

  describe('getTimeline', () => {
    it('should fetch timeline successfully', async () => {
      const mockTimeline = [
        { id: '1', type: 'user_message', sequenceNumber: 1, time_us: 1000, counter: 1 },
        { id: '2', type: 'assistant_message', sequenceNumber: 2, time_us: 2000, counter: 2 },
        { id: '3', type: 'tool_execution', sequenceNumber: 3, time_us: 3000, counter: 3 },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(mockTimeline as any, 3)
      );

      await useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      const {
        timeline,
        timelineLoading,
        timelineError,
        earliestTimeUs,
        earliestCounter,
        latestTimeUs,
        latestCounter,
      } = useTimelineStore.getState();

      expect(timeline).toEqual(mockTimeline);
      expect(timelineLoading).toBe(false);
      expect(timelineError).toBe(null);
      expect(earliestTimeUs).toBe(1000);
      expect(earliestCounter).toBe(1);
      expect(latestTimeUs).toBe(3000);
      expect(latestCounter).toBe(3);
    });

    it('should set loading state during fetch', async () => {
      let resolveTimeline: (value: any) => void;
      const pendingPromise = new Promise((resolve) => {
        resolveTimeline = resolve;
      });

      vi.mocked(getConversationMessages).mockReturnValue(pendingPromise as any);

      // Start fetch (don't await)
      const fetchPromise = useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      // Check loading state
      expect(useTimelineStore.getState().timelineLoading).toBe(true);

      // Resolve and complete
      resolveTimeline!({ timeline: [], total: 0 });
      await fetchPromise;
    });

    it('should handle empty timeline response', async () => {
      vi.mocked(getConversationMessages).mockResolvedValue(createMockResponse([], 0));

      await useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      const { timeline, earliestTimeUs, latestTimeUs } = useTimelineStore.getState();

      expect(timeline).toEqual([]);
      expect(earliestTimeUs).toBe(null);
      expect(latestTimeUs).toBe(null);
    });

    it('should handle fetch error', async () => {
      const error = { response: { data: { detail: 'Network error' } } };
      vi.mocked(getConversationMessages).mockRejectedValue(error);

      await expect(useTimelineStore.getState().getTimeline('conv-1', 'proj-1')).rejects.toEqual(
        error
      );

      const { timeline, timelineLoading, timelineError } = useTimelineStore.getState();

      expect(timeline).toEqual([]);
      expect(timelineLoading).toBe(false);
      expect(timelineError).toBe('Network error');
    });

    it('should handle fetch error without detail', async () => {
      const error = { message: 'Unknown error' };
      vi.mocked(getConversationMessages).mockRejectedValue(error);

      await expect(useTimelineStore.getState().getTimeline('conv-1', 'proj-1')).rejects.toEqual(
        error
      );

      expect(useTimelineStore.getState().timelineError).toBe('Failed to get timeline');
    });

    it('should replace existing timeline on new fetch', async () => {
      // Set existing timeline
      useTimelineStore.setState({
        timeline: [
          { id: 'old', type: 'user_message', sequenceNumber: 1, time_us: 1000, counter: 1 },
        ] as any,
        earliestTimeUs: 1000,
        earliestCounter: 1,
        latestTimeUs: 1000,
        latestCounter: 1,
      });

      const newTimeline = [
        { id: 'new', type: 'assistant_message', sequenceNumber: 2, time_us: 2000, counter: 2 },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(newTimeline as any, 1)
      );

      await useTimelineStore.getState().getTimeline('conv-2', 'proj-1');

      const { timeline, earliestTimeUs, latestTimeUs } = useTimelineStore.getState();

      expect(timeline).toEqual(newTimeline);
      expect(earliestTimeUs).toBe(2000);
      expect(latestTimeUs).toBe(2000);
    });
  });

  describe('addTimelineEvent', () => {
    it('should add event to timeline', () => {
      const event = { id: '1', type: 'user_message', sequenceNumber: 1 } as any;

      useTimelineStore.getState().addTimelineEvent(event);

      const { timeline } = useTimelineStore.getState();
      expect(timeline).toHaveLength(1);
      expect(timeline[0].id).toBe('1');
      expect(timeline[0].type).toBe('user_message');
    });

    it('should append event to existing timeline', () => {
      useTimelineStore.setState({
        timeline: [
          { id: '1', type: 'user_message', sequenceNumber: 1 },
          { id: '2', type: 'assistant_message', sequenceNumber: 2 },
        ] as any,
      });

      const newEvent = { id: '3', type: 'user_message', sequenceNumber: 3 } as any;
      useTimelineStore.getState().addTimelineEvent(newEvent);

      const { timeline } = useTimelineStore.getState();
      expect(timeline).toHaveLength(3);
      expect(timeline[2].id).toBe('3');
    });

    it('should append single event to empty timeline', () => {
      const event = { id: '1', type: 'user_message', sequenceNumber: 1 } as any;

      useTimelineStore.getState().addTimelineEvent(event);

      const { timeline } = useTimelineStore.getState();
      expect(timeline).toHaveLength(1);
      expect(timeline[0].id).toBe('1');
    });

    it('should append event to end of timeline', () => {
      useTimelineStore.setState({
        timeline: [
          { id: '1', type: 'user_message', sequenceNumber: 1 },
          { id: '2', type: 'assistant_message', sequenceNumber: 2 },
        ] as any,
      });

      const newEvent = { id: '3', type: 'tool_execution', sequenceNumber: 3 } as any;
      useTimelineStore.getState().addTimelineEvent(newEvent);

      const { timeline } = useTimelineStore.getState();
      expect(timeline).toHaveLength(3);
      expect(timeline[2].id).toBe('3');
    });
  });

  describe('clearTimeline', () => {
    it('should clear all timeline events', () => {
      useTimelineStore.setState({
        timeline: [
          { id: '1', type: 'user_message', sequenceNumber: 1 },
          { id: '2', type: 'assistant_message', sequenceNumber: 2 },
        ] as any,
      });

      useTimelineStore.getState().clearTimeline();

      expect(useTimelineStore.getState().timeline).toEqual([]);
    });

    it('should handle clearing empty timeline', () => {
      useTimelineStore.getState().clearTimeline();

      expect(useTimelineStore.getState().timeline).toEqual([]);
    });
  });

  describe('prependTimelineEvents', () => {
    it('should prepend events to timeline', () => {
      useTimelineStore.setState({
        timeline: [
          { id: '3', type: 'assistant_message', sequenceNumber: 3 },
          { id: '4', type: 'user_message', sequenceNumber: 4 },
        ] as any,
      });

      const newEvents = [
        { id: '1', type: 'user_message', sequenceNumber: 1 },
        { id: '2', type: 'assistant_message', sequenceNumber: 2 },
      ] as any;

      useTimelineStore.getState().prependTimelineEvents(newEvents);

      const { timeline } = useTimelineStore.getState();
      expect(timeline).toHaveLength(4);
      expect(timeline[0].id).toBe('1');
      expect(timeline[1].id).toBe('2');
      expect(timeline[2].id).toBe('3');
      expect(timeline[3].id).toBe('4');
    });

    it('should prepend to empty timeline', () => {
      const events = [{ id: '1', type: 'user_message', sequenceNumber: 1 }] as any;

      useTimelineStore.getState().prependTimelineEvents(events);

      const { timeline } = useTimelineStore.getState();
      expect(timeline).toEqual(events);
    });

    it('should handle empty events array', () => {
      useTimelineStore.setState({
        timeline: [{ id: '1', type: 'user_message', sequenceNumber: 1 }] as any,
      });

      useTimelineStore.getState().prependTimelineEvents([]);

      const { timeline } = useTimelineStore.getState();
      expect(timeline).toHaveLength(1);
    });
  });

  describe('loadEarlierMessages', () => {
    it('should load earlier messages successfully', async () => {
      useTimelineStore.setState({
        timeline: [
          { id: '3', type: 'assistant_message', time_us: 3000, counter: 3 },
          { id: '4', type: 'user_message', time_us: 4000, counter: 4 },
        ] as any,
        earliestTimeUs: 3000,
        earliestCounter: 3,
        latestTimeUs: 4000,
        latestCounter: 4,
      });

      const earlierEvents = [
        { id: '1', type: 'user_message', time_us: 1000, counter: 1 },
        { id: '2', type: 'assistant_message', time_us: 2000, counter: 2 },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(earlierEvents as any, 4)
      );

      await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      const { timeline, earliestTimeUs, timelineLoading, timelineError } =
        useTimelineStore.getState();

      expect(timeline).toHaveLength(4);
      expect(timeline[0].id).toBe('1');
      expect(timeline[3].id).toBe('4');
      expect(earliestTimeUs).toBe(1000);
      expect(timelineLoading).toBe(false);
      expect(timelineError).toBe(null);
    });

    it('should not load if no pagination point exists', async () => {
      const result = await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      expect(result).toBe(false);
      expect(getConversationMessages).not.toHaveBeenCalled();
    });

    it('should not load if already loading', async () => {
      useTimelineStore.setState({
        isLoadingEarlier: true,
        earliestTimeUs: 10000,
      });

      const result = await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      expect(result).toBe(false);
      expect(getConversationMessages).not.toHaveBeenCalled();
    });

    it('should handle load error', async () => {
      useTimelineStore.setState({
        timeline: [{ id: '2', type: 'assistant_message', time_us: 2000, counter: 2 }] as any,
        earliestTimeUs: 2000,
        earliestCounter: 2,
      });

      const error = { response: { data: { detail: 'Load failed' } } };
      vi.mocked(getConversationMessages).mockRejectedValue(error);

      await expect(
        useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1')
      ).rejects.toEqual(error);

      expect(useTimelineStore.getState().timelineError).toBe('Load failed');
      expect(useTimelineStore.getState().timelineLoading).toBe(false);
    });

    it('should pass time-based pagination parameters to service', async () => {
      useTimelineStore.setState({
        timeline: [{ id: '10', type: 'user_message', time_us: 10000, counter: 10 }] as any,
        earliestTimeUs: 10000,
        earliestCounter: 10,
      });

      vi.mocked(getConversationMessages).mockResolvedValue(createMockResponse([] as any, 0));

      await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      expect(getConversationMessages).toHaveBeenCalledWith(
        'conv-1',
        'proj-1',
        50, // limit
        undefined, // fromTimeUs
        undefined, // fromCounter
        10000, // beforeTimeUs
        10 // beforeCounter
      );
    });
  });

  describe('Pagination State', () => {
    it('should set earliest and latest time pointers from timeline', async () => {
      const timeline = [
        { id: '1', type: 'user_message', time_us: 5000, counter: 5 },
        { id: '2', type: 'assistant_message', time_us: 6000, counter: 6 },
        { id: '3', type: 'tool_execution', time_us: 7000, counter: 7 },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(createMockResponse(timeline as any, 3));

      await useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      const { earliestTimeUs, latestTimeUs } = useTimelineStore.getState();

      expect(earliestTimeUs).toBe(5000);
      expect(latestTimeUs).toBe(7000);
    });

    it('should handle single event timeline', async () => {
      const timeline = [{ id: '1', type: 'user_message', time_us: 5000, counter: 5 }];

      vi.mocked(getConversationMessages).mockResolvedValue(createMockResponse(timeline as any, 1));

      await useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      const { earliestTimeUs, latestTimeUs } = useTimelineStore.getState();

      expect(earliestTimeUs).toBe(5000);
      expect(latestTimeUs).toBe(5000);
    });

    it('should update pagination after loading earlier messages', async () => {
      useTimelineStore.setState({
        timeline: [{ id: '5', type: 'assistant_message', time_us: 5000, counter: 5 }] as any,
        earliestTimeUs: 5000,
        earliestCounter: 5,
      });

      const earlierEvents = [
        { id: '3', type: 'user_message', time_us: 3000, counter: 3 },
        { id: '4', type: 'assistant_message', time_us: 4000, counter: 4 },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(earlierEvents as any, 3)
      );

      await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      expect(useTimelineStore.getState().earliestTimeUs).toBe(3000);
    });
  });

  describe('Edge Cases', () => {
    it('should handle rapid addTimelineEvent calls', () => {
      const store = useTimelineStore.getState();

      store.addTimelineEvent({ id: '1', type: 'user_message' } as any);
      store.addTimelineEvent({ id: '2', type: 'assistant_message' } as any);
      store.addTimelineEvent({ id: '3', type: 'tool_execution' } as any);

      const { timeline } = useTimelineStore.getState();
      expect(timeline).toHaveLength(3);
      expect(timeline[0].id).toBe('1');
      expect(timeline[1].id).toBe('2');
      expect(timeline[2].id).toBe('3');
    });

    it('should handle getTimeline called while loading', async () => {
      let firstResolve: (value: any) => void;
      const firstPromise = new Promise((resolve) => {
        firstResolve = resolve;
      });

      vi.mocked(getConversationMessages).mockReturnValueOnce(firstPromise as any);

      // Start first fetch
      const firstFetch = useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      // Start second fetch before first completes
      const secondPromise = { timeline: [], total: 0 };
      vi.mocked(getConversationMessages).mockResolvedValueOnce(secondPromise as any);
      const secondFetch = useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      // Complete both
      firstResolve!(secondPromise);
      await Promise.all([firstFetch, secondFetch]);

      // Second fetch result should win
      expect(useTimelineStore.getState().timelineLoading).toBe(false);
    });

    it('should handle clearTimeline followed by getTimeline', async () => {
      useTimelineStore.setState({
        timeline: [{ id: 'old', type: 'user_message', sequenceNumber: 1 }] as any,
      });

      useTimelineStore.getState().clearTimeline();
      expect(useTimelineStore.getState().timeline).toEqual([]);

      const newTimeline = [{ id: 'new', type: 'assistant_message', sequenceNumber: 1 }] as any;
      vi.mocked(getConversationMessages).mockResolvedValue(createMockResponse(newTimeline, 1));

      await useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      expect(useTimelineStore.getState().timeline).toEqual(newTimeline);
    });

    it('should handle timeline with gaps in time values', async () => {
      const timelineWithGaps = [
        { id: '1', type: 'user_message', time_us: 1000, counter: 1 },
        { id: '3', type: 'assistant_message', time_us: 3000, counter: 3 },
        { id: '5', type: 'tool_execution', time_us: 5000, counter: 5 },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(timelineWithGaps as any, 3)
      );

      await useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      const { earliestTimeUs, latestTimeUs } = useTimelineStore.getState();

      expect(earliestTimeUs).toBe(1000);
      expect(latestTimeUs).toBe(5000);
    });
  });

  describe('State Immutability', () => {
    it('should reset properly after multiple state changes', async () => {
      useTimelineStore.setState({
        timeline: [{ id: '1', type: 'user_message' }] as any,
        timelineLoading: true,
        isLoadingEarlier: true,
        timelineError: 'Error',
        earliestTimeUs: 10000,
        earliestCounter: 10,
        latestTimeUs: 20000,
        latestCounter: 20,
      });

      useTimelineStore.getState().reset();

      const { timeline, timelineLoading, timelineError, earliestTimeUs, latestTimeUs } =
        useTimelineStore.getState();

      expect(timeline).toEqual([]);
      expect(timelineLoading).toBe(false);
      expect(timelineError).toBe(null);
      expect(earliestTimeUs).toBe(null);
      expect(latestTimeUs).toBe(null);
    });
  });
});
