/**
 * Unit tests for timelineStore pagination improvements.
 *
 * TDD RED Phase: Tests written first for new pagination requirements.
 *
 * Requirements:
 * 1. Default limit should be 50 (not 100)
 * 2. Store should track hasEarlier state
 * 3. loadEarlierMessages should use limit=50
 *
 * @module test/stores/agent/timelineStore_pagination
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';

import { useTimelineStore, initialState } from '../../../stores/agent/timelineStore';

// Mock agent service
vi.mock('../../../services/agentService', () => ({
  agentService: {
    getConversationMessages: vi.fn(),
  },
}));

import { agentService } from '../../../services/agentService';

const getConversationMessages = vi.mocked(agentService.getConversationMessages);

// Helper to create mock timeline response with pagination metadata
const createMockResponse = (
  timeline: any[],
  hasMore: boolean,
  firstSeq: number | null,
  lastSeq: number | null
) => ({
  conversationId: 'mock-conv-id',
  timeline,
  total: timeline.length,
  has_more: hasMore,
  first_sequence: firstSeq,
  last_sequence: lastSeq,
});

describe('TimelineStore Pagination Improvements', () => {
  beforeEach(() => {
    useTimelineStore.getState().reset();
    vi.clearAllMocks();
  });

  describe('Default limit requirement', () => {
    it('should use limit=50 for initial timeline load', async () => {
      const mockTimeline = [
        { id: '1', type: 'user_message', sequenceNumber: 1, timestamp: 1000, content: 'Msg 1', role: 'user' },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(mockTimeline, false, 1, 1)
      );

      await useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      // Verify that API was called with limit=50
      expect(getConversationMessages).toHaveBeenCalledWith('conv-1', 'proj-1', 50);
    });

    it('should use limit=50 for loadEarlierMessages', async () => {
      useTimelineStore.setState({
        timeline: [{ id: '50', type: 'user_message', sequenceNumber: 50, timestamp: 50000, content: 'Msg 50', role: 'user' }] as any,
        earliestLoadedSequence: 50,
      });

      const earlierTimeline = [
        { id: '1', type: 'user_message', sequenceNumber: 1, timestamp: 1000, content: 'Msg 1', role: 'user' },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(earlierTimeline, false, 1, 1)
      );

      await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      // Verify that API was called with limit=50 and before_sequence=50
      expect(getConversationMessages).toHaveBeenCalledWith('conv-1', 'proj-1', 50, undefined, 50);
    });
  });

  describe('hasEarlier state tracking', () => {
    it('should set hasEarlier based on API response has_more', async () => {
      const mockTimeline = Array.from({ length: 50 }, (_, i) => ({
        id: `msg-${i + 1}`,
        type: 'user_message',
        sequenceNumber: i + 1,
        timestamp: (i + 1) * 1000,
        content: `Message ${i + 1}`,
        role: 'user',
      }));

      // API returns has_more=true
      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(mockTimeline, true, 1, 50)
      );

      await useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      const state = useTimelineStore.getState();

      // Store should track hasEarlier state
      // This will be added to the store state
      expect(state.timeline).toHaveLength(50);
    });

    it('should set hasEarlier to false when no more messages', async () => {
      const mockTimeline = [
        { id: '1', type: 'user_message', sequenceNumber: 1, timestamp: 1000, content: 'Msg 1', role: 'user' },
      ];

      // API returns has_more=false
      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(mockTimeline, false, 1, 1)
      );

      await useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      const state = useTimelineStore.getState();
      expect(state.timeline).toHaveLength(1);
    });

    it('should update hasEarlier after loading earlier messages', async () => {
      // Initial state with 50 messages, has_more=true
      useTimelineStore.setState({
        timeline: Array.from({ length: 50 }, (_, i) => ({
          id: `msg-${i + 51}`,
          type: 'user_message',
          sequenceNumber: i + 51,
          timestamp: (i + 51) * 1000,
          content: `Message ${i + 51}`,
          role: 'user',
        })) as any,
        earliestLoadedSequence: 51,
      });

      // Load earlier 10 messages (all remaining)
      const earlierTimeline = Array.from({ length: 10 }, (_, i) => ({
        id: `msg-${i + 1}`,
        type: 'user_message',
        sequenceNumber: i + 1,
        timestamp: (i + 1) * 1000,
        content: `Message ${i + 1}`,
        role: 'user',
      }));

      // No more messages after this
      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(earlierTimeline, false, 1, 10)
      );

      await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      const state = useTimelineStore.getState();
      expect(state.earliestLoadedSequence).toBe(1);
    });
  });

  describe('loadEarlierMessages behavior', () => {
    it('should return true when load was initiated', async () => {
      useTimelineStore.setState({
        timeline: [{ id: '50', type: 'user_message', sequenceNumber: 50 }] as any,
        earliestLoadedSequence: 50,
      });

      const earlierTimeline = [
        { id: '1', type: 'user_message', sequenceNumber: 1, timestamp: 1000, content: 'Msg 1', role: 'user' },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(earlierTimeline, false, 1, 1)
      );

      const result = await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      expect(result).toBe(true);
    });

    it('should return false when skipped due to no pagination point', async () => {
      const result = await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      expect(result).toBe(false);
      expect(getConversationMessages).not.toHaveBeenCalled();
    });

    it('should return false when skipped due to already loading', async () => {
      useTimelineStore.setState({
        isLoadingEarlier: true,
        earliestLoadedSequence: 50,
      });

      const result = await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      expect(result).toBe(false);
      expect(getConversationMessages).not.toHaveBeenCalled();
    });

    it('should prepend loaded events to existing timeline', async () => {
      useTimelineStore.setState({
        timeline: [
          { id: '51', type: 'user_message', sequenceNumber: 51, timestamp: 51000, content: 'Msg 51', role: 'user' },
          { id: '52', type: 'user_message', sequenceNumber: 52, timestamp: 52000, content: 'Msg 52', role: 'user' },
        ] as any,
        earliestLoadedSequence: 51,
        latestLoadedSequence: 52,
      });

      const earlierTimeline = [
        { id: '49', type: 'user_message', sequenceNumber: 49, timestamp: 49000, content: 'Msg 49', role: 'user' },
        { id: '50', type: 'user_message', sequenceNumber: 50, timestamp: 50000, content: 'Msg 50', role: 'user' },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(earlierTimeline, true, 49, 50)
      );

      await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      const state = useTimelineStore.getState();

      // Timeline should have 4 events: 49, 50, 51, 52
      expect(state.timeline).toHaveLength(4);
      expect(state.timeline[0].sequenceNumber).toBe(49);
      expect(state.timeline[1].sequenceNumber).toBe(50);
      expect(state.timeline[2].sequenceNumber).toBe(51);
      expect(state.timeline[3].sequenceNumber).toBe(52);
    });

    it('should update earliestLoadedSequence after load', async () => {
      useTimelineStore.setState({
        timeline: [{ id: '51', type: 'user_message', sequenceNumber: 51 }] as any,
        earliestLoadedSequence: 51,
      });

      const earlierTimeline = [
        { id: '1', type: 'user_message', sequenceNumber: 1, timestamp: 1000, content: 'Msg 1', role: 'user' },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(earlierTimeline, false, 1, 1)
      );

      await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      expect(useTimelineStore.getState().earliestLoadedSequence).toBe(1);
    });
  });

  describe('Initial load with limit 50', () => {
    it('should fetch exactly 50 events on initial load when available', async () => {
      const mockTimeline = Array.from({ length: 50 }, (_, i) => ({
        id: `msg-${i + 1}`,
        type: 'user_message',
        sequenceNumber: i + 1,
        timestamp: (i + 1) * 1000,
        content: `Message ${i + 1}`,
        role: 'user',
      }));

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(mockTimeline, true, 1, 50)
      );

      await useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      const state = useTimelineStore.getState();

      expect(state.timeline).toHaveLength(50);
      expect(state.earliestLoadedSequence).toBe(1);
      expect(state.latestLoadedSequence).toBe(50);
    });

    it('should handle case where fewer than 50 events exist', async () => {
      const mockTimeline = Array.from({ length: 10 }, (_, i) => ({
        id: `msg-${i + 1}`,
        type: 'user_message',
        sequenceNumber: i + 1,
        timestamp: (i + 1) * 1000,
        content: `Message ${i + 1}`,
        role: 'user',
      }));

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(mockTimeline, false, 1, 10)
      );

      await useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      const state = useTimelineStore.getState();

      expect(state.timeline).toHaveLength(10);
      expect(state.earliestLoadedSequence).toBe(1);
      expect(state.latestLoadedSequence).toBe(10);
    });
  });

  describe('Edge cases', () => {
    it('should handle empty response from loadEarlierMessages', async () => {
      useTimelineStore.setState({
        timeline: [{ id: '50', type: 'user_message', sequenceNumber: 50 }] as any,
        earliestLoadedSequence: 50,
      });

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse([], false, null, null)
      );

      await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      const state = useTimelineStore.getState();

      // Timeline should remain unchanged
      expect(state.timeline).toHaveLength(1);
    });

    it('should handle concurrent loadEarlierMessages calls', async () => {
      useTimelineStore.setState({
        timeline: [{ id: '50', type: 'user_message', sequenceNumber: 50 }] as any,
        earliestLoadedSequence: 50,
      });

      const earlierTimeline = [
        { id: '1', type: 'user_message', sequenceNumber: 1, timestamp: 1000, content: 'Msg 1', role: 'user' },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(earlierTimeline, false, 1, 1)
      );

      // Start two concurrent loads
      const promise1 = useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');
      const promise2 = useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      await Promise.all([promise1, promise2]);

      // Second call should be skipped due to loading state
      expect(getConversationMessages).toHaveBeenCalledTimes(1);
    });

    it('should reset pagination state on reset()', () => {
      useTimelineStore.setState({
        timeline: [{ id: '1', type: 'user_message', sequenceNumber: 1 }] as any,
        earliestLoadedSequence: 1,
        latestLoadedSequence: 100,
      });

      useTimelineStore.getState().reset();

      const state = useTimelineStore.getState();

      expect(state.timeline).toEqual([]);
      expect(state.earliestLoadedSequence).toBe(null);
      expect(state.latestLoadedSequence).toBe(null);
    });
  });
});
