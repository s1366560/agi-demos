/**
 * Unit tests for Agent store pagination functionality.
 *
 * TDD: Tests written first (RED phase) for backward pagination support.
 */

import { act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// FIXME: This test was written for the old agent store (agent.ts).
// The new agentV3 store has a different API. This test needs to be migrated.
import { useAgentV3Store as useAgentStore } from '../../stores/agentV3';

import type { TimelineEvent } from '../../types/agent';

// Mock agent service
vi.mock('../../services/agentService', () => ({
  agentService: {
    getConversationMessages: vi.fn(),
    chat: vi.fn(),
    createConversation: vi.fn(),
    listConversations: vi.fn(),
  },
}));

import { agentService } from '../../services/agentService';

describe('Agent Store Pagination', () => {
  beforeEach(() => {
    // Reset store before each test
    const { reset } = useAgentStore.getState();
    reset();
    vi.clearAllMocks();
  });

  describe('getTimeline - initial load', () => {
    it('should set pagination metadata on initial load', async () => {
      // Arrange
      const mockTimeline: TimelineEvent[] = [
        {
          id: '1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'Hello',
          role: 'user',
        },
        {
          id: '2',
          type: 'assistant_message',
          sequenceNumber: 2,
          timestamp: 2000,
          content: 'Hi',
          role: 'assistant',
        },
        {
          id: '3',
          type: 'user_message',
          sequenceNumber: 3,
          timestamp: 3000,
          content: 'How are you?',
          role: 'user',
        },
      ];
      const mockResponse = {
        conversationId: 'conv-1',
        timeline: mockTimeline,
        total: 3,
        has_more: true,
        first_sequence: 1,
        last_sequence: 3,
      };
      vi.mocked(agentService.getConversationMessages).mockResolvedValue(mockResponse);

      // Act
      const { getTimeline } = useAgentStore.getState();

      await act(async () => {
        await getTimeline('conv-1', 'project-1', 100);
      });

      // Assert
      const state = useAgentStore.getState();
      expect(state.timeline).toEqual(mockResponse.timeline);
      expect(state.earliestLoadedSequence).toBe(1);
      expect(state.latestLoadedSequence).toBe(3);
      expect(state.hasEarlierMessages).toBe(true);
      expect(state.timelineLoading).toBe(false);
    });

    it('should handle empty timeline response', async () => {
      // Arrange
      const mockResponse = {
        conversationId: 'conv-1',
        timeline: [],
        total: 0,
        has_more: false,
        first_sequence: null,
        last_sequence: null,
      };
      vi.mocked(agentService.getConversationMessages).mockResolvedValue(mockResponse);

      // Act
      const { getTimeline } = useAgentStore.getState();

      await act(async () => {
        await getTimeline('conv-1', 'project-1', 100);
      });

      // Assert
      const state = useAgentStore.getState();
      expect(state.timeline).toEqual([]);
      expect(state.earliestLoadedSequence).toBeNull();
      expect(state.latestLoadedSequence).toBeNull();
      expect(state.hasEarlierMessages).toBe(false);
    });
  });

  describe('loadEarlierMessages - backward pagination', () => {
    it('should load messages before earliestLoadedSequence', async () => {
      // Arrange - Set initial state
      useAgentStore.setState({
        earliestLoadedSequence: 11,
        latestLoadedSequence: 20,
        timeline: Array.from(
          { length: 10 },
          (_, i): TimelineEvent => ({
            id: `msg-${i + 11}`,
            type: 'user_message',
            sequenceNumber: i + 11,
            timestamp: (i + 11) * 1000,
            content: `Message ${i + 11}`,
            role: 'user',
          })
        ),
        hasEarlierMessages: true,
      });

      const mockEarlierTimeline: TimelineEvent[] = [
        {
          id: 'msg-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'Msg 1',
          role: 'user',
        },
        {
          id: 'msg-2',
          type: 'assistant_message',
          sequenceNumber: 2,
          timestamp: 2000,
          content: 'Msg 2',
          role: 'assistant',
        },
        {
          id: 'msg-3',
          type: 'user_message',
          sequenceNumber: 3,
          timestamp: 3000,
          content: 'Msg 3',
          role: 'user',
        },
      ];
      const mockEarlierResponse = {
        conversationId: 'conv-1',
        timeline: mockEarlierTimeline,
        total: 3,
        has_more: false,
        first_sequence: 1,
        last_sequence: 3,
      };
      vi.mocked(agentService.getConversationMessages).mockResolvedValue(mockEarlierResponse);

      // Act
      const { loadEarlierMessages } = useAgentStore.getState();

      await act(async () => {
        await loadEarlierMessages('conv-1', 'project-1', 10);
      });

      // Assert
      const state = useAgentStore.getState();
      expect(state.timeline.length).toBe(13); // 10 original + 3 new
      expect(state.timeline[0].sequenceNumber).toBe(1); // First event is now 1
      expect(state.timeline[state.timeline.length - 1].sequenceNumber).toBe(20); // Last event is still 20
      expect(state.earliestLoadedSequence).toBe(1);
      expect(state.hasEarlierMessages).toBe(false);
      expect(agentService.getConversationMessages).toHaveBeenCalledWith(
        'conv-1',
        'project-1',
        10,
        undefined,
        11 // before_sequence
      );
    });

    it('should not load when no earliestLoadedSequence exists', async () => {
      // Arrange
      useAgentStore.setState({
        earliestLoadedSequence: null,
        hasEarlierMessages: true,
      });
      const getMessagesSpy = vi.spyOn(agentService, 'getConversationMessages');

      // Act
      const { loadEarlierMessages } = useAgentStore.getState();

      await act(async () => {
        await loadEarlierMessages('conv-1', 'project-1', 10);
      });

      // Assert
      expect(getMessagesSpy).not.toHaveBeenCalled();
    });

    it('should not load when already loading', async () => {
      // Arrange
      useAgentStore.setState({
        earliestLoadedSequence: 11,
        hasEarlierMessages: true,
        timelineLoading: true,
      });
      const getMessagesSpy = vi.spyOn(agentService, 'getConversationMessages');

      // Act
      const { loadEarlierMessages } = useAgentStore.getState();

      await act(async () => {
        await loadEarlierMessages('conv-1', 'project-1', 10);
      });

      // Assert
      expect(getMessagesSpy).not.toHaveBeenCalled();
    });
  });

  describe('prependTimelineEvents', () => {
    it('should add events to the beginning of timeline', () => {
      // Arrange
      const existingTimeline: TimelineEvent[] = [
        {
          id: 'msg-10',
          type: 'user_message',
          sequenceNumber: 10,
          timestamp: 10000,
          content: 'Msg 10',
          role: 'user',
        },
      ];
      useAgentStore.setState({ timeline: existingTimeline });

      const newEvents: TimelineEvent[] = [
        {
          id: 'msg-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'Msg 1',
          role: 'user',
        },
        {
          id: 'msg-2',
          type: 'assistant_message',
          sequenceNumber: 2,
          timestamp: 2000,
          content: 'Msg 2',
          role: 'assistant',
        },
      ];

      // Act
      const { prependTimelineEvents } = useAgentStore.getState();

      act(() => {
        prependTimelineEvents(newEvents);
      });

      // Assert
      const state = useAgentStore.getState();
      expect(state.timeline.length).toBe(3);
      expect(state.timeline[0].id).toBe('msg-1');
      expect(state.timeline[1].id).toBe('msg-2');
      expect(state.timeline[2].id).toBe('msg-10');
    });
  });

  describe('setCurrentConversation - resets pagination state', () => {
    it('should reset pagination state when switching conversations', async () => {
      // Arrange - Set initial state
      useAgentStore.setState({
        earliestLoadedSequence: 10,
        latestLoadedSequence: 20,
        hasEarlierMessages: true,
        timeline: [
          {
            id: 'msg-1',
            type: 'user_message',
            sequenceNumber: 10,
            timestamp: 10000,
            content: 'Msg',
            role: 'user',
          },
        ],
      });

      const mockTimeline: TimelineEvent[] = [
        {
          id: 'msg-2',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'New',
          role: 'user',
        },
      ];
      const mockResponse = {
        conversationId: 'conv-2',
        timeline: mockTimeline,
        total: 1,
        has_more: false,
        first_sequence: 1,
        last_sequence: 1,
      };
      vi.mocked(agentService.getConversationMessages).mockResolvedValue(mockResponse);

      // Act
      const { setCurrentConversation } = useAgentStore.getState();

      await act(async () => {
        setCurrentConversation({ id: 'conv-2', project_id: 'project-2', title: 'New Conv' } as any);
      });

      // Assert
      const state = useAgentStore.getState();
      // State should be updated with new conversation's data
      expect(state.currentConversation?.id).toBe('conv-2');
      // Pagination state should reflect new conversation
      expect(state.earliestLoadedSequence).toBe(1);
      expect(state.timeline.length).toBe(1);
    });
  });
});
