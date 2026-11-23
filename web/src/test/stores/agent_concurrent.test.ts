/**
 * Unit tests for concurrent agent conversation switching (agentV3).
 *
 * Tests verify that the agentV3 store properly supports:
 * 1. Per-conversation state isolation via conversationStates Map
 * 2. Multiple conversations streaming simultaneously
 * 3. Proper state management when switching active conversation
 * 4. API surface for concurrent conversation support
 */

import { act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { useAgentV3Store as useAgentStore } from '@business/agent/ui/web/stores/agentV3';

import type { Conversation } from '../../types/agent';

// Mock agent service
vi.mock('../../services/agentService', () => ({
  agentService: {
    getConversationMessages: vi.fn(),
    chat: vi.fn(),
    createConversation: vi.fn(),
    listConversations: vi.fn(),
    stopChat: vi.fn(),
  },
}));

describe('Agent Store - Concurrent Conversation Support (agentV3)', () => {
  beforeEach(() => {
    // Reset store to initial state
    useAgentStore.setState({
      conversations: [],
      activeConversationId: null,
      conversationStates: new Map(),
      timeline: [],
      messages: [],
      isStreaming: false,
      streamStatus: 'idle',
      error: null,
      currentThought: '',
      streamingThought: '',
      isThinkingStreaming: false,
      activeToolCalls: new Map(),
      pendingToolsStack: [],
      agentState: 'idle',
      isLoadingHistory: false,
      isLoadingEarlier: false,
      hasEarlier: false,
      earliestTimeUs: null,
      earliestCounter: null,
    });
    vi.clearAllMocks();
  });

  describe('Per-conversation state isolation', () => {
    it('should maintain isolated state per conversation via conversationStates Map', () => {
      const conv1Id = 'conv-1';
      const conv2Id = 'conv-2';

      // Update conversation state for conv1
      const { updateConversationState } = useAgentStore.getState();

      act(() => {
        updateConversationState(conv1Id, { isStreaming: true });
        updateConversationState(conv2Id, { isStreaming: false });
      });

      // Verify states are isolated
      const state = useAgentStore.getState();
      const conv1State = state.getConversationState(conv1Id);
      const conv2State = state.getConversationState(conv2Id);

      expect(conv1State.isStreaming).toBe(true);
      expect(conv2State.isStreaming).toBe(false);
    });

    it('should return default state for unknown conversation', () => {
      const state = useAgentStore.getState();
      const unknownState = state.getConversationState('unknown-conv');

      // Should return a default ConversationState (not throw)
      expect(unknownState).toBeDefined();
      expect(unknownState.isStreaming).toBe(false);
    });

    it('should preserve global isStreaming for active conversation backward compatibility', () => {
      const convId = 'conv-1';

      useAgentStore.setState({
        activeConversationId: convId,
        isStreaming: true,
      });

      const state = useAgentStore.getState();
      expect(state.isStreaming).toBe(true);
    });
  });

  describe('Current behavior: global state for active conversation', () => {
    it('demonstrates global isStreaming reflects active conversation state', () => {
      const conv1Id = 'conv-1';

      // Set active conversation as streaming
      useAgentStore.setState({
        activeConversationId: conv1Id,
        isStreaming: true,
      });

      const state = useAgentStore.getState();
      expect(state.isStreaming).toBe(true);
      expect(state.activeConversationId).toBe(conv1Id);
    });

    it('demonstrates global currentThought is for active conversation', () => {
      const conv1Id = 'conv-1';

      useAgentStore.setState({
        activeConversationId: conv1Id,
        currentThought: 'Thinking in conv 1',
      });

      const state = useAgentStore.getState();
      expect(state.currentThought).toBe('Thinking in conv 1');
    });

    it('demonstrates activeToolCalls is a Map for concurrent tool tracking', () => {
      const toolCallId = 'tool-call-1';

      useAgentStore.setState({
        activeToolCalls: new Map([
          [
            toolCallId,
            {
              id: toolCallId,
              tool_name: 'search',
              arguments: { query: 'test' },
              status: 'running' as const,
              startTime: Date.now(),
            },
          ],
        ]),
      });

      const state = useAgentStore.getState();
      expect(state.activeToolCalls).toBeInstanceOf(Map);
      expect(state.activeToolCalls.get(toolCallId)?.status).toBe('running');
    });
  });

  describe('API verification', () => {
    it('verifies getConversationState method exists and is a function', () => {
      const state = useAgentStore.getState();
      expect(typeof state.getConversationState).toBe('function');
    });

    it('verifies updateConversationState method exists and is a function', () => {
      const state = useAgentStore.getState();
      expect(typeof state.updateConversationState).toBe('function');
    });

    it('verifies getStreamingConversationCount method exists and is a function', () => {
      const state = useAgentStore.getState();
      expect(typeof state.getStreamingConversationCount).toBe('function');
    });

    it('verifies syncActiveConversationState method exists and is a function', () => {
      const state = useAgentStore.getState();
      expect(typeof state.syncActiveConversationState).toBe('function');
    });

    it('verifies conversationStates is a Map', () => {
      const state = useAgentStore.getState();
      expect(state.conversationStates).toBeInstanceOf(Map);
    });

    it('verifies setActiveConversation method exists and is a function', () => {
      const state = useAgentStore.getState();
      expect(typeof state.setActiveConversation).toBe('function');
    });
  });

  describe('getStreamingConversationCount', () => {
    it('should return 0 when no conversations are streaming', () => {
      const state = useAgentStore.getState();
      expect(state.getStreamingConversationCount()).toBe(0);
    });

    it('should count streaming conversations correctly', () => {
      const { updateConversationState } = useAgentStore.getState();

      act(() => {
        updateConversationState('conv-1', { isStreaming: true });
        updateConversationState('conv-2', { isStreaming: true });
        updateConversationState('conv-3', { isStreaming: false });
      });

      const state = useAgentStore.getState();
      expect(state.getStreamingConversationCount()).toBe(2);
    });
  });

  describe('Conversation switching', () => {
    it('should switch active conversation via setActiveConversation', () => {
      const conv1: Conversation = {
        id: 'conv-1',
        project_id: 'proj-1',
        tenant_id: 'tenant-1',
        user_id: 'user-1',
        title: 'Conv 1',
        status: 'active',
        message_count: 2,
        created_at: '2024-01-01T00:00:00Z',
      };

      useAgentStore.setState({
        conversations: [conv1],
        activeConversationId: null,
      });

      act(() => {
        useAgentStore.getState().setActiveConversation('conv-1');
      });

      const state = useAgentStore.getState();
      expect(state.activeConversationId).toBe('conv-1');
    });

    it('should handle switching to null (deselecting conversation)', () => {
      useAgentStore.setState({
        activeConversationId: 'conv-1',
      });

      act(() => {
        useAgentStore.getState().setActiveConversation(null);
      });

      const state = useAgentStore.getState();
      expect(state.activeConversationId).toBeNull();
    });
  });

  describe('Edge cases for concurrent conversations', () => {
    it('handles activeToolCalls isolation for active conversation', () => {
      const toolCall1 = {
        id: 'tool-1',
        tool_name: 'search',
        arguments: { query: 'test' },
        status: 'running' as const,
        startTime: Date.now(),
      };

      // Set active tool call for active conversation
      useAgentStore.setState({
        activeConversationId: 'conv-1',
        activeToolCalls: new Map([['tool-1', toolCall1]]),
        isStreaming: true,
      });

      let state = useAgentStore.getState();
      expect(state.activeToolCalls.size).toBe(1);
      expect(state.activeToolCalls.get('tool-1')?.tool_name).toBe('search');

      // Switching active conversation should not affect stored tool calls
      // (global activeToolCalls reflects what's in the current active conversation)
      act(() => {
        useAgentStore.setState({
          activeConversationId: 'conv-2',
          activeToolCalls: new Map(),
          isStreaming: false,
          currentThought: '',
        });
      });

      state = useAgentStore.getState();
      expect(state.activeToolCalls.size).toBe(0);
      expect(state.isStreaming).toBe(false);
    });

    it('handles rapid state updates without errors', () => {
      const { updateConversationState } = useAgentStore.getState();

      expect(() => {
        act(() => {
          // Rapid updates to multiple conversations
          for (let i = 0; i < 10; i++) {
            updateConversationState(`conv-${i}`, {
              isStreaming: i % 2 === 0,
            });
          }
        });
      }).not.toThrow();

      const state = useAgentStore.getState();
      expect(state.conversationStates.size).toBe(10);
      expect(state.getStreamingConversationCount()).toBe(5);
    });

    it('handles updateConversationState with partial updates', () => {
      const { updateConversationState } = useAgentStore.getState();

      act(() => {
        updateConversationState('conv-1', { isStreaming: true });
      });

      // Apply a second partial update that should not overwrite isStreaming
      act(() => {
        updateConversationState('conv-1', { error: 'some error' });
      });

      const state = useAgentStore.getState();
      const convState = state.getConversationState('conv-1');
      expect(convState.isStreaming).toBe(true);
      expect(convState.error).toBe('some error');
    });
  });
});
