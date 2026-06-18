/**
 * Tests for agentV3 store timeline field
 *
 * This test suite verifies that the agentV3 store correctly
 * stores and manages TimelineEvent[] as the primary data source,
 * ensuring consistency between streaming and historical messages.
 *
 * TDD Phase 1: Add timeline field to AgentV3State
 */

import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

import { useAgentV3Store } from '../../stores/agentV3';
import { useTimelineStore } from '../../stores/agent/timelineStore';
import { useStreamingStore } from '../../stores/agent/streamingStore';
import { useExecutionStore } from '../../stores/agent/executionStore';
import { createDefaultConversationState } from '../../types/conversationState';

import type { TimelineEvent } from '../../types/agent';

// Mock the services
vi.mock('../../services/agentService', () => ({
  agentService: {
    getConversations: vi.fn(() => Promise.resolve([])),
    getConversationMessages: vi.fn(() =>
      Promise.resolve({
        conversationId: 'conv-123',
        timeline: [],
        total: 0,
        has_more: false,
        first_time_us: null,
        first_counter: null,
        last_time_us: null,
        last_counter: null,
      })
    ),
    createConversation: vi.fn(() => Promise.resolve({ id: 'new-conv', project_id: 'proj-123' })),
    deleteConversation: vi.fn(() => Promise.resolve()),
    getExecutionStatus: vi.fn(() => Promise.resolve({ is_running: false, last_sequence: 0 })),
    connect: vi.fn(() => Promise.resolve()),
    isConnected: vi.fn(() => true),
    subscribe: vi.fn(),
    listConversations: vi.fn(() => Promise.resolve({ items: [], has_more: false, total: 0 })),
  },
}));

vi.mock('../../stores/contextStore', () => ({
  useContextStore: {
    getState: vi.fn(() => ({
      fetchContextStatus: vi.fn(() => Promise.resolve()),
    })),
  },
}));

vi.mock('../../services/planService', () => ({
  planService: {
    getMode: vi.fn(() => Promise.resolve({ mode: 'act' })),
  },
}));

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn(() => Promise.resolve({ tasks: [] })),
  },
}));

vi.mock('../../utils/conversationDB', () => ({
  saveConversationState: vi.fn(() => Promise.resolve()),
  loadConversationState: vi.fn(() => Promise.resolve(null)),
  deleteConversationState: vi.fn(() => Promise.resolve()),
}));

function getTimeline() {
  return useTimelineStore.getState().agentTimeline;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

describe('agentV3 Store - Timeline Field', () => {
  beforeEach(() => {
    useAgentV3Store.setState({
      conversations: [],
      activeConversationId: null,
      conversationStates: new Map(),
    });

    useTimelineStore.getState().resetAgentTimeline();
    useStreamingStore.getState().resetAgentStreaming();
    useExecutionStore.getState().resetAgentExecution();

    vi.clearAllMocks();
  });

  describe('State Structure', () => {
    it('should have timeline field in state', () => {
      renderHook(() => useAgentV3Store());
      expect(Array.isArray(getTimeline())).toBe(true);
    });

    it('should initialize timeline as empty array', () => {
      renderHook(() => useAgentV3Store());
      expect(getTimeline()).toEqual([]);
      expect(getTimeline().length).toBe(0);
    });

    it('should maintain both timeline and messages for backward compatibility', () => {
      renderHook(() => useAgentV3Store());
      const tls = useTimelineStore.getState();
      expect(Array.isArray(tls.agentTimeline)).toBe(true);
      expect(Array.isArray(tls.agentMessages)).toBe(true);
    });
  });

  describe('loadMessages - Timeline Storage', () => {
    it('should store timeline from API response', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      const mockTimeline: TimelineEvent[] = [
        {
          id: 'user-1',
          type: 'user_message',
          eventTimeUs: Date.now() * 1000,
          eventCounter: 1,
          timestamp: Date.now(),
          content: 'Hello',
          role: 'user',
        },
        {
          id: 'assistant-1',
          type: 'assistant_message',
          eventTimeUs: Date.now() * 1000 + 1000,
          eventCounter: 2,
          timestamp: Date.now() + 1000,
          content: 'Hi there!',
          role: 'assistant',
        },
        {
          id: 'thought-1',
          type: 'thought',
          eventTimeUs: Date.now() * 1000 + 2000,
          eventCounter: 3,
          timestamp: Date.now() + 2000,
          content: 'I should help...',
        },
      ];

      vi.mocked(
        (await import('../../services/agentService')).agentService
      ).getConversationMessages.mockResolvedValue({
        conversationId: 'conv-123',
        timeline: mockTimeline,
        total: 3,
        has_more: false,
        first_time_us: mockTimeline[0].eventTimeUs,
        first_counter: 1,
        last_time_us: mockTimeline[2].eventTimeUs,
        last_counter: 3,
      } as any);

      await act(async () => {
        useAgentV3Store.setState({ activeConversationId: 'conv-123' });
        await result.current.loadMessages('conv-123', 'proj-123');
      });

      const timeline = getTimeline();
      expect(timeline).toEqual(mockTimeline);
      expect(timeline.length).toBe(3);
    });

    it('should clear timeline when loading new conversation', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      act(() => {
        useAgentV3Store.setState({ activeConversationId: 'old-conv' });
        useTimelineStore.getState().setAgentTimeline([
          {
            id: 'old-1',
            type: 'user_message',
            eventTimeUs: Date.now() * 1000,
            eventCounter: 1,
            timestamp: Date.now(),
            content: 'Old message',
            role: 'user',
          } as TimelineEvent,
        ]);
      });

      expect(getTimeline().length).toBe(1);

      vi.mocked(
        (await import('../../services/agentService')).agentService
      ).getConversationMessages.mockResolvedValue({
        conversationId: 'conv-456',
        timeline: [],
        total: 0,
        has_more: false,
        first_time_us: null,
        first_counter: null,
        last_time_us: null,
        last_counter: null,
      } as any);

      await act(async () => {
        useAgentV3Store.setState({ activeConversationId: 'conv-456' });
        await result.current.loadMessages('conv-456', 'proj-123');
      });

      expect(getTimeline()).toEqual([]);
    });

    it('ignores cached history when active conversation changes before hydration finishes', async () => {
      const { result } = renderHook(() => useAgentV3Store());
      const staleTimeline: TimelineEvent[] = [
        {
          id: 'stale-1',
          type: 'user_message',
          eventTimeUs: Date.now() * 1000,
          eventCounter: 1,
          timestamp: Date.now(),
          content: 'Stale cached message',
          role: 'user',
        } as TimelineEvent,
      ];
      const currentTimeline: TimelineEvent[] = [
        {
          id: 'current-1',
          type: 'user_message',
          eventTimeUs: Date.now() * 1000 + 1,
          eventCounter: 1,
          timestamp: Date.now(),
          content: 'Current conversation message',
          role: 'user',
        } as TimelineEvent,
      ];
      const cachedStateRequest = deferred<ReturnType<typeof createDefaultConversationState>>();
      const conversationDb = await import('../../utils/conversationDB');
      vi.mocked(conversationDb.loadConversationState).mockReturnValueOnce(
        cachedStateRequest.promise as any
      );
      const agentServiceMock = vi.mocked(
        (await import('../../services/agentService')).agentService
      );

      act(() => {
        useAgentV3Store.setState({ activeConversationId: 'conv-a' });
      });
      const loadPromise = result.current.loadMessages('conv-a', 'proj-123');

      await act(async () => {
        await Promise.resolve();
      });

      act(() => {
        useAgentV3Store.setState({ activeConversationId: 'conv-b' });
        useTimelineStore.getState().setAgentTimeline(currentTimeline);
      });

      cachedStateRequest.resolve({
        ...createDefaultConversationState(),
        timeline: staleTimeline,
      });
      await act(async () => {
        await loadPromise;
      });

      expect(getTimeline()).toEqual(currentTimeline);
      expect(agentServiceMock.getConversationMessages).not.toHaveBeenCalled();
    });

    it('keeps a fresh blank conversation interactive while history hydrates', async () => {
      const { result } = renderHook(() => useAgentV3Store());
      const baseTime = Date.now() * 1000;
      let resolveMessages:
        | ((value: {
            conversationId: string;
            timeline: TimelineEvent[];
            total: number;
            has_more: boolean;
            first_time_us: number | null;
            first_counter: number | null;
            last_time_us: number | null;
            last_counter: number | null;
          }) => void)
        | undefined;

      vi.mocked(
        (await import('../../services/agentService')).agentService
      ).getConversationMessages.mockImplementation(
        () =>
          new Promise<any>((resolve) => {
            resolveMessages = resolve;
          })
      );

      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-fresh',
          conversationStates: new Map([['conv-fresh', createDefaultConversationState()]]),
        });
      });

      const loadPromise = result.current.loadMessages('conv-fresh', 'proj-123');
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(useTimelineStore.getState().agentIsLoadingHistory).toBe(false);

      resolveMessages?.({
        conversationId: 'conv-fresh',
        timeline: [],
        total: 0,
        has_more: false,
        first_time_us: null,
        first_counter: null,
        last_time_us: baseTime,
        last_counter: 0,
      });

      await act(async () => {
        await loadPromise;
      });

      expect(useTimelineStore.getState().agentIsLoadingHistory).toBe(false);
    });

    it('joins concurrent message loads for the same conversation', async () => {
      const { result } = renderHook(() => useAgentV3Store());
      const responseRequest = deferred<{
        conversationId: string;
        timeline: TimelineEvent[];
        total: number;
        has_more: boolean;
        first_time_us: number | null;
        first_counter: number | null;
        last_time_us: number | null;
        last_counter: number | null;
      }>();
      const agentServiceMock = vi.mocked(
        (await import('../../services/agentService')).agentService
      );
      agentServiceMock.getConversationMessages.mockReturnValueOnce(responseRequest.promise as any);

      act(() => {
        useAgentV3Store.setState({ activeConversationId: 'conv-deduped' });
      });

      const firstLoad = result.current.loadMessages('conv-deduped', 'proj-123');
      const secondLoad = result.current.loadMessages('conv-deduped', 'proj-123');

      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(agentServiceMock.getConversationMessages).toHaveBeenCalledTimes(1);

      responseRequest.resolve({
        conversationId: 'conv-deduped',
        timeline: [],
        total: 0,
        has_more: false,
        first_time_us: null,
        first_counter: null,
        last_time_us: null,
        last_counter: null,
      });

      await act(async () => {
        await Promise.all([firstLoad, secondLoad]);
      });

      expect(agentServiceMock.subscribe).toHaveBeenCalledTimes(1);
    });

    it('skips recent completed message loads unless forced', async () => {
      const { result } = renderHook(() => useAgentV3Store());
      const agentServiceMock = vi.mocked(
        (await import('../../services/agentService')).agentService
      );
      agentServiceMock.getConversationMessages.mockResolvedValue({
        conversationId: 'conv-recent',
        timeline: [],
        total: 0,
        has_more: false,
        first_time_us: null,
        first_counter: null,
        last_time_us: null,
        last_counter: null,
      } as any);

      act(() => {
        useAgentV3Store.setState({ activeConversationId: 'conv-recent' });
      });

      await act(async () => {
        await result.current.loadMessages('conv-recent', 'proj-123');
      });
      expect(agentServiceMock.getConversationMessages).toHaveBeenCalledTimes(1);

      await act(async () => {
        await result.current.loadMessages('conv-recent', 'proj-123');
      });
      expect(agentServiceMock.getConversationMessages).toHaveBeenCalledTimes(1);

      await act(async () => {
        await result.current.loadMessages('conv-recent', 'proj-123', { force: true });
      });
      expect(agentServiceMock.getConversationMessages).toHaveBeenCalledTimes(2);
    });
  });

  describe('Streaming - Timeline Append', () => {
    it('should append thought events to timeline during streaming', () => {
      renderHook(() => useAgentV3Store());

      const initialTimeline: TimelineEvent[] = [
        {
          id: 'user-1',
          type: 'user_message',
          eventTimeUs: Date.now() * 1000,
          eventCounter: 1,
          timestamp: Date.now(),
          content: 'Help me',
          role: 'user',
        },
      ];

      act(() => {
        useTimelineStore.getState().setAgentTimeline(initialTimeline);
      });

      const thoughtEvent: TimelineEvent = {
        id: 'thought-1',
        type: 'thought',
        eventTimeUs: Date.now() * 1000 + 1000,
        eventCounter: 2,
        timestamp: Date.now() + 1000,
        content: 'I should help the user',
      };

      act(() => {
        useTimelineStore.getState().setAgentTimeline([...initialTimeline, thoughtEvent]);
      });

      expect(getTimeline().length).toBe(2);
      expect(getTimeline()[1]).toEqual(thoughtEvent);
    });

    it('should append act events to timeline during streaming', () => {
      renderHook(() => useAgentV3Store());

      const actEvent: TimelineEvent = {
        id: 'act-1',
        type: 'act',
        eventTimeUs: Date.now() * 1000,
        eventCounter: 2,
        timestamp: Date.now(),
        toolName: 'web_search',
        toolInput: { query: 'test' },
      };

      act(() => {
        useTimelineStore.getState().setAgentTimeline([actEvent]);
      });

      expect(getTimeline()).toContainEqual(actEvent);
    });

    it('should append observe events to timeline during streaming', () => {
      renderHook(() => useAgentV3Store());

      const observeEvent: TimelineEvent = {
        id: 'observe-1',
        type: 'observe',
        eventTimeUs: Date.now() * 1000,
        eventCounter: 3,
        timestamp: Date.now(),
        toolName: 'web_search',
        toolOutput: 'Search results',
        isError: false,
      };

      act(() => {
        useTimelineStore.getState().setAgentTimeline([observeEvent]);
      });

      expect(getTimeline()).toContainEqual(observeEvent);
    });

    it('should maintain event order by sequenceNumber', () => {
      renderHook(() => useAgentV3Store());

      const events: TimelineEvent[] = [
        {
          id: 'event-3',
          type: 'thought',
          eventTimeUs: 3000,
          eventCounter: 3,
          timestamp: 3000,
          content: 'Third',
        },
        {
          id: 'event-1',
          type: 'user_message',
          eventTimeUs: 1000,
          eventCounter: 1,
          timestamp: 1000,
          content: 'First',
          role: 'user',
        },
        {
          id: 'event-2',
          type: 'assistant_message',
          eventTimeUs: 2000,
          eventCounter: 2,
          timestamp: 2000,
          content: 'Second',
          role: 'assistant',
        },
      ];

      act(() => {
        useTimelineStore.getState().setAgentTimeline(events);
      });

      expect(getTimeline().length).toBe(3);
    });
  });

  describe('Timeline Consistency', () => {
    it('should have consistent event types between API and streaming', () => {
      renderHook(() => useAgentV3Store());

      const apiEvents: TimelineEvent[] = [
        {
          id: 'api-1',
          type: 'user_message',
          eventTimeUs: Date.now() * 1000,
          eventCounter: 1,
          timestamp: Date.now(),
          content: 'From API',
          role: 'user',
        },
        {
          id: 'api-2',
          type: 'thought',
          eventTimeUs: Date.now() * 1000 + 1,
          eventCounter: 2,
          timestamp: Date.now(),
          content: 'From API thought',
        },
        {
          id: 'api-3',
          type: 'act',
          eventTimeUs: Date.now() * 1000 + 2,
          eventCounter: 3,
          timestamp: Date.now(),
          toolName: 'search',
          toolInput: { query: 'test' },
        },
        {
          id: 'api-4',
          type: 'observe',
          eventTimeUs: Date.now() * 1000 + 3,
          eventCounter: 4,
          timestamp: Date.now(),
          toolName: 'search',
          toolOutput: 'result',
          isError: false,
        },
      ];

      act(() => {
        useTimelineStore.getState().setAgentTimeline(apiEvents);
      });

      const timeline = getTimeline();
      expect(timeline.length).toBe(4);
      expect(timeline[0].type).toBe('user_message');
      expect(timeline[1].type).toBe('thought');
      expect(timeline[2].type).toBe('act');
      expect(timeline[3].type).toBe('observe');
    });
  });

  describe('Backward Compatibility', () => {
    it('should still provide messages field derived from timeline', () => {
      renderHook(() => useAgentV3Store());

      const timeline: TimelineEvent[] = [
        {
          id: 'user-1',
          type: 'user_message',
          eventTimeUs: Date.now() * 1000,
          eventCounter: 1,
          timestamp: Date.now(),
          content: 'Hello',
          role: 'user',
        },
      ];

      act(() => {
        useTimelineStore.getState().setAgentTimeline(timeline);
      });

      expect(Array.isArray(useTimelineStore.getState().agentMessages)).toBe(true);
    });
  });

  describe('loadMessages - Timeline Sorting', () => {
    it('should sort timeline by eventTimeUs even if API returns unsorted', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      const baseTime = Date.now() * 1000;
      const unsortedTimeline: TimelineEvent[] = [
        {
          id: 'assistant-2',
          type: 'assistant_message',
          eventTimeUs: baseTime + 2000000,
          eventCounter: 3,
          timestamp: Date.now() + 2000,
          content: 'Second response',
          role: 'assistant',
        },
        {
          id: 'user-1',
          type: 'user_message',
          eventTimeUs: baseTime,
          eventCounter: 1,
          timestamp: Date.now(),
          content: 'First message',
          role: 'user',
        },
        {
          id: 'assistant-1',
          type: 'assistant_message',
          eventTimeUs: baseTime + 1000000,
          eventCounter: 2,
          timestamp: Date.now() + 1000,
          content: 'First response',
          role: 'assistant',
        },
      ];

      vi.mocked(
        (await import('../../services/agentService')).agentService
      ).getConversationMessages.mockResolvedValue({
        conversationId: 'conv-123',
        timeline: unsortedTimeline,
        total: 3,
        has_more: false,
        first_time_us: baseTime,
        first_counter: 1,
        last_time_us: baseTime + 2000000,
        last_counter: 3,
      } as any);

      await act(async () => {
        useAgentV3Store.setState({ activeConversationId: 'conv-123' });
        await result.current.loadMessages('conv-123', 'proj-123');
      });

      const timeline = getTimeline();
      expect(timeline.length).toBe(3);
      expect(timeline[0].eventCounter).toBe(1);
      expect(timeline[1].eventCounter).toBe(2);
      expect(timeline[2].eventCounter).toBe(3);
      expect(timeline[0].type).toBe('user_message');
      expect(timeline[1].type).toBe('assistant_message');
      expect(timeline[2].type).toBe('assistant_message');
    });

    it('should maintain sort order when loading earlier messages', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      const baseTime = Date.now() * 1000;
      const existingTimeline: TimelineEvent[] = [
        {
          id: 'user-3',
          type: 'user_message',
          eventTimeUs: baseTime + 5000000,
          eventCounter: 5,
          timestamp: Date.now(),
          content: 'Latest message',
          role: 'user',
        },
        {
          id: 'assistant-3',
          type: 'assistant_message',
          eventTimeUs: baseTime + 6000000,
          eventCounter: 6,
          timestamp: Date.now() + 1000,
          content: 'Latest response',
          role: 'assistant',
        },
      ];

      act(() => {
        useAgentV3Store.setState({ activeConversationId: 'conv-123' });
        const tls = useTimelineStore.getState();
        tls.setAgentTimeline(existingTimeline);
        tls.setAgentHasEarlier(true);
        tls.setAgentEarliestPointers(baseTime + 5000000, 5);
      });

      const earlierTimeline: TimelineEvent[] = [
        {
          id: 'user-1',
          type: 'user_message',
          eventTimeUs: baseTime + 1000000,
          eventCounter: 1,
          timestamp: Date.now() - 2000,
          content: 'First message',
          role: 'user',
        },
        {
          id: 'assistant-1',
          type: 'assistant_message',
          eventTimeUs: baseTime + 2000000,
          eventCounter: 2,
          timestamp: Date.now() - 1000,
          content: 'First response',
          role: 'assistant',
        },
      ];

      vi.mocked(
        (await import('../../services/agentService')).agentService
      ).getConversationMessages.mockResolvedValue({
        conversationId: 'conv-123',
        timeline: earlierTimeline,
        total: 2,
        has_more: false,
        first_time_us: baseTime + 1000000,
        first_counter: 1,
        last_time_us: baseTime + 2000000,
        last_counter: 2,
      } as any);

      await act(async () => {
        await result.current.loadEarlierMessages('conv-123', 'proj-123');
      });

      const timeline = getTimeline();
      expect(timeline.length).toBe(4);
      expect(timeline[0].eventCounter).toBe(1);
      expect(timeline[1].eventCounter).toBe(2);
      expect(timeline[2].eventCounter).toBe(5);
      expect(timeline[3].eventCounter).toBe(6);
    });
  });
});
