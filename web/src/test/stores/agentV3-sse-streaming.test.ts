/**
 * Tests for agentV3 store SSE streaming with timeline integration
 *
 * This test suite verifies that the agentV3 store correctly
 * uses appendSSEEventToTimeline() to update the timeline state
 * during SSE streaming.
 *
 * TDD Phase: SSE Adapter Integration into agentV3 Store
 */

import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

import { useAgentV3Store } from '../../stores/agentV3';

import type {
  AgentEvent,
  MessageEventData,
  ThoughtEventData,
  ActEventData,
  ObserveEventData,
  CompleteEventData,
} from '../../types/agent';

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
        first_sequence: null,
        last_sequence: null,
      })
    ),
    createConversation: vi.fn(() => Promise.resolve({ id: 'new-conv', project_id: 'proj-123' })),
    deleteConversation: vi.fn(() => Promise.resolve()),
    chat: vi.fn(),
    stopChat: vi.fn(),
    getExecutionStatus: vi.fn(() =>
      Promise.resolve({
        is_running: false,
        last_sequence: 0,
      })
    ),
  },
}));

describe('agentV3 Store - SSE Timeline Integration', () => {
  beforeEach(() => {
    // Reset store before each test
    useAgentV3Store.setState({
      conversations: [],
      activeConversationId: null,
      messages: [],
      timeline: [],
      isLoadingHistory: false,
      isStreaming: false,
      streamStatus: 'idle',
      error: null,
      agentState: 'idle',
      currentThought: '',
      activeToolCalls: new Map(),
      pendingToolsStack: [],
      workPlan: null,
      isPlanMode: false,
      showPlanPanel: true,
      showHistorySidebar: true,
      pendingDecision: null,
      doomLoopDetected: null,
    });

    vi.clearAllMocks();
  });

  describe('User Message - Timeline Append', () => {
    it('should append user message event to timeline when sending message', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      // Mock createConversation to return a conversation
      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.createConversation).mockResolvedValue({
        id: 'conv-1',
        project_id: 'proj-123',
        title: 'Test',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      } as any);

      // Mock chat to resolve immediately
      vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
        // Simulate minimal SSE flow
        handler.onMessage?.({
          type: 'message',
          data: {
            id: 'msg-1',
            role: 'user',
            content: 'Hello',
            created_at: new Date().toISOString(),
          },
        } as AgentEvent<MessageEventData>);
        return Promise.resolve();
      });

      await act(async () => {
        await result.current.sendMessage('Hello', 'proj-123');
      });

      // Verify timeline has user message
      const timeline = result.current.timeline;
      expect(timeline.length).toBeGreaterThan(0);
      expect(timeline[0].type).toBe('user_message');
      if (timeline[0].type === 'user_message') {
        expect(timeline[0].content).toBe('Hello');
      }
    });

    it('should set correct sequence number for user message', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.createConversation).mockResolvedValue({
        id: 'conv-1',
        project_id: 'proj-123',
        title: 'Test',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      } as any);

      vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
        handler.onMessage?.({
          type: 'message',
          data: {
            id: 'msg-1',
            role: 'user',
            content: 'Test',
            created_at: new Date().toISOString(),
          },
        } as AgentEvent<MessageEventData>);
        return Promise.resolve();
      });

      await act(async () => {
        await result.current.sendMessage('Test', 'proj-123');
      });

      const timeline = result.current.timeline;
      expect(timeline[0].sequenceNumber).toBe(1);
    });
  });

  describe('SSE Events - Timeline Append During Streaming', () => {
    it('should append thought event to timeline during streaming', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      // Start with existing user message in timeline
      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-1',
          timeline: [
            {
              id: 'user-1',
              type: 'user_message',
              sequenceNumber: 1,
              timestamp: Date.now(),
              content: 'Help me',
              role: 'user',
            },
          ],
        });
      });

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
        // Simulate thought event
        handler.onThought?.({
          type: 'thought',
          data: {
            thought: 'I should help the user',
            thought_level: 'task',
            step_number: 1,
          },
        } as AgentEvent<ThoughtEventData>);
        return Promise.resolve();
      });

      await act(async () => {
        await result.current.sendMessage('Help me', 'proj-123');
      });

      const timeline = result.current.timeline;
      // Should have user message + thought
      expect(timeline.length).toBeGreaterThan(1);
      const thoughtEvent = timeline.find((e) => e.type === 'thought');
      expect(thoughtEvent).toBeDefined();
      if (thoughtEvent?.type === 'thought') {
        expect(thoughtEvent.content).toBe('I should help the user');
      }
    });

    it('should append act event to timeline during streaming', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-1',
          timeline: [
            {
              id: 'user-1',
              type: 'user_message',
              sequenceNumber: 1,
              timestamp: Date.now(),
              content: 'Search',
              role: 'user',
            },
          ],
        });
      });

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
        handler.onAct?.({
          type: 'act',
          data: {
            tool_name: 'web_search',
            tool_input: { query: 'test' },
            step_number: 1,
          },
        } as AgentEvent<ActEventData>);
        return Promise.resolve();
      });

      await act(async () => {
        await result.current.sendMessage('Search', 'proj-123');
      });

      const timeline = result.current.timeline;
      const actEvent = timeline.find((e) => e.type === 'act');
      expect(actEvent).toBeDefined();
      if (actEvent?.type === 'act') {
        expect(actEvent.toolName).toBe('web_search');
      }
    });

    it('should append observe event to timeline during streaming', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-1',
          timeline: [
            {
              id: 'user-1',
              type: 'user_message',
              sequenceNumber: 1,
              timestamp: Date.now(),
              content: 'Search',
              role: 'user',
            },
          ],
        });
      });

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
        handler.onAct?.({
          type: 'act',
          data: {
            tool_name: 'web_search',
            tool_input: { query: 'test' },
            step_number: 1,
          },
        } as AgentEvent<ActEventData>);
        handler.onObserve?.({
          type: 'observe',
          data: {
            observation: 'Search completed',
          },
        } as AgentEvent<ObserveEventData>);
        return Promise.resolve();
      });

      await act(async () => {
        await result.current.sendMessage('Search', 'proj-123');
      });

      const timeline = result.current.timeline;
      const observeEvent = timeline.find((e) => e.type === 'observe');
      expect(observeEvent).toBeDefined();
      if (observeEvent?.type === 'observe') {
        expect(observeEvent.toolOutput).toBe('Search completed');
      }
    });

    it('should append assistant_message event on complete', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-1',
          timeline: [
            {
              id: 'user-1',
              type: 'user_message',
              sequenceNumber: 1,
              timestamp: Date.now(),
              content: 'Hello',
              role: 'user',
            },
          ],
        });
      });

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
        handler.onComplete?.({
          type: 'complete',
          data: {
            content: 'Here is the answer',
            id: 'msg-complete',
            trace_url: 'https://trace.com',
            artifacts: [],
          },
        } as AgentEvent<CompleteEventData>);
        return Promise.resolve();
      });

      await act(async () => {
        await result.current.sendMessage('Hello', 'proj-123');
      });

      const timeline = result.current.timeline;
      const assistantMsg = timeline.find((e) => e.type === 'assistant_message');
      expect(assistantMsg).toBeDefined();
      if (assistantMsg?.type === 'assistant_message') {
        expect(assistantMsg.content).toBe('Here is the answer');
      }
    });
  });

  describe('Sequence Number Management', () => {
    it('should increment sequence numbers for each appended event', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-1',
          timeline: [],
        });
      });

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
        handler.onMessage?.({
          type: 'message',
          data: {
            id: 'msg-1',
            role: 'user',
            content: 'Hello',
            created_at: new Date().toISOString(),
          },
        } as AgentEvent<MessageEventData>);
        handler.onThought?.({
          type: 'thought',
          data: { thought: 'Thinking', thought_level: 'task' },
        } as AgentEvent<ThoughtEventData>);
        handler.onAct?.({
          type: 'act',
          data: { tool_name: 'search', tool_input: {}, step_number: 1 },
        } as AgentEvent<ActEventData>);
        handler.onObserve?.({
          type: 'observe',
          data: { observation: 'Result' },
        } as AgentEvent<ObserveEventData>);
        handler.onComplete?.({
          type: 'complete',
          data: { content: 'Done', id: 'msg-2', artifacts: [] },
        } as AgentEvent<CompleteEventData>);
        return Promise.resolve();
      });

      await act(async () => {
        await result.current.sendMessage('Hello', 'proj-123');
      });

      const timeline = result.current.timeline;
      const sequenceNumbers = timeline.map((e) => e.sequenceNumber);

      // Should have incrementing sequence numbers
      for (let i = 1; i < sequenceNumbers.length; i++) {
        expect(sequenceNumbers[i]).toBeGreaterThan(sequenceNumbers[i - 1]);
      }
    });

    it('should continue sequence from existing timeline', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      // Start with existing events
      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-1',
          timeline: [
            {
              id: 'existing-1',
              type: 'user_message',
              sequenceNumber: 1,
              timestamp: Date.now(),
              content: 'Previous',
              role: 'user',
            },
            {
              id: 'existing-2',
              type: 'assistant_message',
              sequenceNumber: 2,
              timestamp: Date.now(),
              content: 'Response',
              role: 'assistant',
            },
          ],
        });
      });

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
        // SSE returns a thought event (not the user message which was created locally)
        handler.onThought?.({
          type: 'thought',
          data: {
            thought: 'Processing new message',
            thought_level: 'task',
            step_number: 1,
          },
        } as AgentEvent<ThoughtEventData>);
        return Promise.resolve();
      });

      await act(async () => {
        await result.current.sendMessage('New message', 'proj-123');
      });

      const timeline = result.current.timeline;
      // Find the user message that was created locally
      const userMessages = timeline.filter((e) => e.type === 'user_message');
      // Should have 2 user messages now (original + new)
      expect(userMessages.length).toBe(2);

      // The new user message should have sequence number 3
      const newUserMessage = userMessages[userMessages.length - 1];
      expect(newUserMessage.sequenceNumber).toBe(3);

      // The thought event should have sequence number 4
      const thoughtEvents = timeline.filter((e) => e.type === 'thought');
      const newThought = thoughtEvents[thoughtEvents.length - 1];
      expect(newThought.sequenceNumber).toBe(4);
    });
  });

  describe('Timeline-Messages Consistency', () => {
    it('should keep messages in sync with timeline', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.createConversation).mockResolvedValue({
        id: 'conv-1',
        project_id: 'proj-123',
        title: 'Test',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      } as any);

      vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
        handler.onMessage?.({
          type: 'message',
          data: {
            id: 'msg-1',
            role: 'user',
            content: 'Hello',
            created_at: new Date().toISOString(),
          },
        } as AgentEvent<MessageEventData>);
        handler.onComplete?.({
          type: 'complete',
          data: { content: 'Hi there!', id: 'msg-2', artifacts: [] },
        } as AgentEvent<CompleteEventData>);
        return Promise.resolve();
      });

      await act(async () => {
        await result.current.sendMessage('Hello', 'proj-123');
      });

      const timeline = result.current.timeline;
      const messages = result.current.messages;

      // Both should have the same number of message-type events
      const timelineMessages = timeline.filter(
        (e) => e.type === 'user_message' || e.type === 'assistant_message'
      );
      expect(messages.length).toBe(timelineMessages.length);
    });
  });
});
