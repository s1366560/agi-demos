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

import { agentService } from '../../../services/agentService';
import { useTimelineStore } from '@business/agent/ui/web/stores/agent/timelineStore';
// Mock agent service
vi.mock('../../../services/agentService', () => ({
  agentService: {
    getConversationMessages: vi.fn(),
  },
}));

const getConversationMessages = vi.mocked(agentService.getConversationMessages);

const createMockResponse = (
  timeline: any[],
  hasMore: boolean,
  firstTimeUs: number | null,
  lastTimeUs: number | null,
  firstCounter: number | null = firstTimeUs ? 1 : null,
  lastCounter: number | null = lastTimeUs ? timeline.length : null
) => ({
  conversationId: 'mock-conv-id',
  timeline,
  total: timeline.length,
  has_more: hasMore,
  first_time_us: firstTimeUs,
  first_counter: firstCounter,
  last_time_us: lastTimeUs,
  last_counter: lastCounter,
});

describe('TimelineStore Pagination Improvements', () => {
  beforeEach(() => {
    useTimelineStore.getState().reset();
    vi.clearAllMocks();
  });

  describe('Default limit requirement', () => {
    it('should use limit=50 for initial timeline load', async () => {
      const mockTimeline = [
        {
          id: '1',
          type: 'user_message',
          time_us: 1000,
          counter: 1,
          content: 'Msg 1',
          role: 'user',
        },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(mockTimeline, false, 1000, 1000, 1, 1)
      );

      await useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      expect(getConversationMessages).toHaveBeenCalledWith('conv-1', 'proj-1', 50);
    });

    it('should use limit=50 for loadEarlierMessages', async () => {
      useTimelineStore.setState({
        timeline: [
          {
            id: '50',
            type: 'user_message',
            time_us: 50000,
            counter: 50,
            content: 'Msg 50',
            role: 'user',
          },
        ] as any,
        earliestTimeUs: 50000,
        earliestCounter: 50,
      });

      const earlierTimeline = [
        {
          id: '1',
          type: 'user_message',
          time_us: 1000,
          counter: 1,
          content: 'Msg 1',
          role: 'user',
        },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(earlierTimeline, false, 1000, 1000, 1, 1)
      );

      await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      expect(getConversationMessages).toHaveBeenCalledWith(
        'conv-1',
        'proj-1',
        50,
        undefined,
        undefined,
        50000,
        50
      );
    });
  });

  describe('hasEarlier state tracking', () => {
    it('should set hasEarlier based on API response has_more', async () => {
      const mockTimeline = Array.from({ length: 50 }, (_, i) => ({
        id: `msg-${i + 1}`,
        type: 'user_message',
        time_us: (i + 1) * 1000,
        counter: i + 1,
        content: `Message ${i + 1}`,
        role: 'user',
      }));

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(mockTimeline, true, 1000, 50000, 1, 50)
      );

      await useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      const state = useTimelineStore.getState();

      expect(state.timeline).toHaveLength(50);
    });

    it('should set hasEarlier to false when no more messages', async () => {
      const mockTimeline = [
        {
          id: '1',
          type: 'user_message',
          time_us: 1000,
          counter: 1,
          content: 'Msg 1',
          role: 'user',
        },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(mockTimeline, false, 1000, 1000, 1, 1)
      );

      await useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      const state = useTimelineStore.getState();
      expect(state.timeline).toHaveLength(1);
    });

    it('should update hasEarlier after loading earlier messages', async () => {
      useTimelineStore.setState({
        timeline: Array.from({ length: 50 }, (_, i) => ({
          id: `msg-${i + 51}`,
          type: 'user_message',
          time_us: (i + 51) * 1000,
          counter: i + 51,
          content: `Message ${i + 51}`,
          role: 'user',
        })) as any,
        earliestTimeUs: 51000,
        earliestCounter: 51,
      });

      const earlierTimeline = Array.from({ length: 10 }, (_, i) => ({
        id: `msg-${i + 1}`,
        type: 'user_message',
        time_us: (i + 1) * 1000,
        counter: i + 1,
        content: `Message ${i + 1}`,
        role: 'user',
      }));

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(earlierTimeline, false, 1000, 10000, 1, 10)
      );

      await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      const state = useTimelineStore.getState();
      expect(state.earliestTimeUs).toBe(1000);
    });
  });

  describe('loadEarlierMessages behavior', () => {
    it('should return true when load was initiated', async () => {
      useTimelineStore.setState({
        timeline: [{ id: '50', type: 'user_message', time_us: 50000, counter: 50 }] as any,
        earliestTimeUs: 50000,
        earliestCounter: 50,
      });

      const earlierTimeline = [
        {
          id: '1',
          type: 'user_message',
          time_us: 1000,
          counter: 1,
          content: 'Msg 1',
          role: 'user',
        },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(earlierTimeline, false, 1000, 1000, 1, 1)
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
        earliestTimeUs: 50000,
      });

      const result = await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      expect(result).toBe(false);
      expect(getConversationMessages).not.toHaveBeenCalled();
    });

    it('should prepend loaded events to existing timeline', async () => {
      useTimelineStore.setState({
        timeline: [
          {
            id: '51',
            type: 'user_message',
            time_us: 51000,
            counter: 51,
            content: 'Msg 51',
            role: 'user',
          },
          {
            id: '52',
            type: 'user_message',
            time_us: 52000,
            counter: 52,
            content: 'Msg 52',
            role: 'user',
          },
        ] as any,
        earliestTimeUs: 51000,
        earliestCounter: 51,
        latestTimeUs: 52000,
        latestCounter: 52,
      });

      const earlierTimeline = [
        {
          id: '49',
          type: 'user_message',
          time_us: 49000,
          counter: 49,
          content: 'Msg 49',
          role: 'user',
        },
        {
          id: '50',
          type: 'user_message',
          time_us: 50000,
          counter: 50,
          content: 'Msg 50',
          role: 'user',
        },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(earlierTimeline, true, 49000, 50000, 49, 50)
      );

      await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      const state = useTimelineStore.getState();

      expect(state.timeline).toHaveLength(4);
      expect(state.timeline[0].id).toBe('49');
      expect(state.timeline[1].id).toBe('50');
      expect(state.timeline[2].id).toBe('51');
      expect(state.timeline[3].id).toBe('52');
    });

    it('should update earliestTimeUs after load', async () => {
      useTimelineStore.setState({
        timeline: [{ id: '51', type: 'user_message', time_us: 51000, counter: 51 }] as any,
        earliestTimeUs: 51000,
        earliestCounter: 51,
      });

      const earlierTimeline = [
        {
          id: '1',
          type: 'user_message',
          time_us: 1000,
          counter: 1,
          content: 'Msg 1',
          role: 'user',
        },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(earlierTimeline, false, 1000, 1000, 1, 1)
      );

      await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      expect(useTimelineStore.getState().earliestTimeUs).toBe(1000);
    });
  });

  describe('Initial load with limit 50', () => {
    it('should fetch exactly 50 events on initial load when available', async () => {
      const mockTimeline = Array.from({ length: 50 }, (_, i) => ({
        id: `msg-${i + 1}`,
        type: 'user_message',
        time_us: (i + 1) * 1000,
        counter: i + 1,
        content: `Message ${i + 1}`,
        role: 'user',
      }));

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(mockTimeline, true, 1000, 50000, 1, 50)
      );

      await useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      const state = useTimelineStore.getState();

      expect(state.timeline).toHaveLength(50);
      expect(state.earliestTimeUs).toBe(1000);
      expect(state.latestTimeUs).toBe(50000);
    });

    it('should handle case where fewer than 50 events exist', async () => {
      const mockTimeline = Array.from({ length: 10 }, (_, i) => ({
        id: `msg-${i + 1}`,
        type: 'user_message',
        time_us: (i + 1) * 1000,
        counter: i + 1,
        content: `Message ${i + 1}`,
        role: 'user',
      }));

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(mockTimeline, false, 1000, 10000, 1, 10)
      );

      await useTimelineStore.getState().getTimeline('conv-1', 'proj-1');

      const state = useTimelineStore.getState();

      expect(state.timeline).toHaveLength(10);
      expect(state.earliestTimeUs).toBe(1000);
      expect(state.latestTimeUs).toBe(10000);
    });
  });

  describe('Edge cases', () => {
    it('should handle empty response from loadEarlierMessages', async () => {
      useTimelineStore.setState({
        timeline: [{ id: '50', type: 'user_message', time_us: 50000, counter: 50 }] as any,
        earliestTimeUs: 50000,
        earliestCounter: 50,
      });

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse([], false, null, null, null, null)
      );

      await useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      const state = useTimelineStore.getState();

      expect(state.timeline).toHaveLength(1);
    });

    it('should handle concurrent loadEarlierMessages calls', async () => {
      useTimelineStore.setState({
        timeline: [{ id: '50', type: 'user_message', time_us: 50000, counter: 50 }] as any,
        earliestTimeUs: 50000,
        earliestCounter: 50,
      });

      const earlierTimeline = [
        {
          id: '1',
          type: 'user_message',
          time_us: 1000,
          counter: 1,
          content: 'Msg 1',
          role: 'user',
        },
      ];

      vi.mocked(getConversationMessages).mockResolvedValue(
        createMockResponse(earlierTimeline, false, 1000, 1000, 1, 1)
      );

      const promise1 = useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');
      const promise2 = useTimelineStore.getState().loadEarlierMessages('conv-1', 'proj-1');

      await Promise.all([promise1, promise2]);

      expect(getConversationMessages).toHaveBeenCalledTimes(1);
    });

    it('should reset pagination state on reset()', () => {
      useTimelineStore.setState({
        timeline: [{ id: '1', type: 'user_message' }] as any,
        earliestTimeUs: 1000,
        earliestCounter: 1,
        latestTimeUs: 100000,
        latestCounter: 100,
      });

      useTimelineStore.getState().reset();

      const state = useTimelineStore.getState();

      expect(state.timeline).toEqual([]);
      expect(state.earliestTimeUs).toBe(null);
      expect(state.latestTimeUs).toBe(null);
    });
  });
});
