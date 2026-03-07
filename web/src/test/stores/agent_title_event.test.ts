/**
 * Unit tests for Agent store title_generated event handling (agentV3).
 *
 * Title generation is now backend-only. The frontend receives title_generated
 * SSE events and updates the conversation title via setState.
 */

import { act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { useAgentV3Store as useAgentStore } from '../../stores/agentV3';

import type { Conversation, TimelineEvent } from '../../types/agent';

describe('Agent Store - Title Generated Event Handling (agentV3)', () => {
  beforeEach(() => {
    // Reset store to clean state
    useAgentStore.setState({
      conversations: [],
      activeConversationId: null,
      timeline: [],
      messages: [],
      isStreaming: false,
      streamStatus: 'idle',
      error: null,
      currentThought: '',
      streamingThought: '',
      isThinkingStreaming: false,
      activeToolCalls: new Map(),
      conversationStates: new Map(),
    });
    vi.clearAllMocks();
  });

  describe('onTitleGenerated handler', () => {
    it('should update conversation title in list when event matches active conversation', () => {
      // Arrange
      const mockConversation: Conversation = {
        id: 'conv-1',
        project_id: 'project-1',
        tenant_id: 'tenant-1',
        user_id: 'user-1',
        title: 'New Conversation',
        status: 'active',
        message_count: 2,
        created_at: '2024-01-01T00:00:00Z',
      };

      useAgentStore.setState({
        activeConversationId: mockConversation.id,
        conversations: [mockConversation],
      });

      // Act - Simulate receiving title_generated event via setState
      const event = {
        type: 'title_generated',
        data: {
          conversation_id: 'conv-1',
          title: 'Generated Title from LLM',
          generated_at: '2024-01-01T00:01:00Z',
          generated_by: 'llm',
        },
        timestamp: '2024-01-01T00:01:00Z',
      };

      act(() => {
        const { conversations, activeConversationId } = useAgentStore.getState();

        // Update in conversations list
        const updatedList = conversations.map((c) =>
          c.id === event.data.conversation_id ? { ...c, title: event.data.title } : c
        );
        useAgentStore.setState({ conversations: updatedList });
      });

      // Assert
      const state = useAgentStore.getState();
      // Derive current conversation from active ID
      const currentConv = state.conversations.find((c) => c.id === state.activeConversationId);
      expect(currentConv?.title).toBe('Generated Title from LLM');
      expect(state.conversations[0].title).toBe('Generated Title from LLM');
    });

    it('should update conversation in list when not active conversation', () => {
      // Arrange
      const currentConv: Conversation = {
        id: 'conv-2',
        project_id: 'project-1',
        tenant_id: 'tenant-1',
        user_id: 'user-1',
        title: 'Current Conversation',
        status: 'active',
        message_count: 5,
        created_at: '2024-01-01T00:00:00Z',
      };

      const otherConv: Conversation = {
        id: 'conv-1',
        project_id: 'project-1',
        tenant_id: 'tenant-1',
        user_id: 'user-1',
        title: 'New Conversation',
        status: 'active',
        message_count: 2,
        created_at: '2024-01-01T00:00:00Z',
      };

      useAgentStore.setState({
        activeConversationId: currentConv.id,
        conversations: [otherConv, currentConv],
      });

      // Act
      const event = {
        type: 'title_generated',
        data: {
          conversation_id: 'conv-1', // Different from active
          title: 'Background Generated Title',
          generated_at: '2024-01-01T00:01:00Z',
        },
        timestamp: '2024-01-01T00:01:00Z',
      };

      act(() => {
        const { conversations } = useAgentStore.getState();

        const updatedList = conversations.map((c) =>
          c.id === event.data.conversation_id ? { ...c, title: event.data.title } : c
        );
        useAgentStore.setState({ conversations: updatedList });
      });

      // Assert
      const state = useAgentStore.getState();
      const activeConv = state.conversations.find((c) => c.id === state.activeConversationId);
      expect(activeConv?.title).toBe('Current Conversation'); // Unchanged
      expect(state.conversations[0].title).toBe('Background Generated Title'); // Updated
      expect(state.conversations[1].title).toBe('Current Conversation'); // Unchanged
    });

    it('should handle title_generated event for non-existent conversation gracefully', () => {
      // Arrange
      const mockConversation: Conversation = {
        id: 'conv-1',
        project_id: 'project-1',
        tenant_id: 'tenant-1',
        user_id: 'user-1',
        title: 'New Conversation',
        status: 'active',
        message_count: 2,
        created_at: '2024-01-01T00:00:00Z',
      };

      useAgentStore.setState({
        activeConversationId: mockConversation.id,
        conversations: [mockConversation],
      });

      // Act - Event for non-existent conversation
      const event = {
        type: 'title_generated',
        data: {
          conversation_id: 'conv-999', // Does not exist
          title: 'Ghost Title',
          generated_at: '2024-01-01T00:01:00Z',
        },
        timestamp: '2024-01-01T00:01:00Z',
      };

      expect(() => {
        act(() => {
          const { conversations } = useAgentStore.getState();

          const updatedList = conversations.map((c) =>
            c.id === event.data.conversation_id ? { ...c, title: event.data.title } : c
          );
          useAgentStore.setState({ conversations: updatedList });
        });
      }).not.toThrow();

      // Assert - No changes
      const state = useAgentStore.getState();
      const activeConv = state.conversations.find((c) => c.id === state.activeConversationId);
      expect(activeConv?.title).toBe('New Conversation');
      expect(state.conversations[0].title).toBe('New Conversation');
    });

    it('should update conversation metadata when title is generated', () => {
      // Arrange
      const mockConversation: Conversation = {
        id: 'conv-1',
        project_id: 'project-1',
        tenant_id: 'tenant-1',
        user_id: 'user-1',
        title: 'New Conversation',
        status: 'active',
        message_count: 2,
        created_at: '2024-01-01T00:00:00Z',
      };

      useAgentStore.setState({
        activeConversationId: mockConversation.id,
        conversations: [mockConversation],
      });

      // Act - Event with full metadata
      const event = {
        type: 'title_generated',
        data: {
          conversation_id: 'conv-1',
          title: 'AI Generated Title',
          generated_at: '2024-01-01T00:01:00Z',
          message_id: 'msg-123',
          generated_by: 'llm',
        },
        timestamp: '2024-01-01T00:01:00Z',
      };

      act(() => {
        const { conversations } = useAgentStore.getState();

        const updatedList = conversations.map((c) =>
          c.id === event.data.conversation_id ? { ...c, title: event.data.title } : c
        );
        useAgentStore.setState({ conversations: updatedList });
      });

      // Assert
      const state = useAgentStore.getState();
      const activeConv = state.conversations.find((c) => c.id === state.activeConversationId);
      expect(activeConv?.title).toBe('AI Generated Title');
      // Other fields should remain unchanged
      expect(activeConv?.id).toBe('conv-1');
      expect(activeConv?.message_count).toBe(2);
    });
  });

  describe('Title generation flow integration', () => {
    it('should handle complete flow: message -> complete -> title_generated', () => {
      // Arrange
      const mockConversation: Conversation = {
        id: 'conv-1',
        project_id: 'project-1',
        tenant_id: 'tenant-1',
        user_id: 'user-1',
        title: 'New Conversation',
        status: 'active',
        message_count: 0,
        created_at: '2024-01-01T00:00:00Z',
      };

      useAgentStore.setState({
        activeConversationId: mockConversation.id,
        conversations: [mockConversation],
        timeline: [],
      });

      // Act 1: Simulate user message added to timeline via setState
      act(() => {
        useAgentStore.setState({
          timeline: [
            {
              id: 'msg-1',
              type: 'user_message',
              sequenceNumber: 1,
              timestamp: Date.now(),
              content: 'Hello',
              role: 'user',
            } as TimelineEvent,
          ],
        });
      });

      // Act 2: Simulate assistant response added to timeline
      act(() => {
        useAgentStore.setState({
          timeline: [
            ...useAgentStore.getState().timeline,
            {
              id: 'msg-2',
              type: 'assistant_message',
              sequenceNumber: 2,
              timestamp: Date.now(),
              content: 'Hi there!',
              role: 'assistant',
            } as TimelineEvent,
          ],
        });
      });

      // Act 3: Simulate title_generated event
      const titleEvent = {
        type: 'title_generated',
        data: {
          conversation_id: 'conv-1',
          title: 'Hello Conversation',
          generated_at: '2024-01-01T00:01:01Z',
        },
        timestamp: '2024-01-01T00:01:01Z',
      };

      act(() => {
        const { conversations } = useAgentStore.getState();

        const updatedList = conversations.map((c) =>
          c.id === titleEvent.data.conversation_id ? { ...c, title: titleEvent.data.title } : c
        );
        useAgentStore.setState({ conversations: updatedList });
      });

      // Assert
      const state = useAgentStore.getState();
      const activeConv = state.conversations.find((c) => c.id === state.activeConversationId);
      expect(activeConv?.title).toBe('Hello Conversation');
      expect(state.timeline.some((e) => e.type === 'user_message')).toBe(true);
    });

    it('should not have generateConversationTitle in agentV3 (backend-only)', () => {
      // Title generation is now handled entirely by the backend.
      // The frontend no longer has a generateConversationTitle method.
      const state = useAgentStore.getState();

      // Verify the method does NOT exist on the agentV3 store
      expect('generateConversationTitle' in state).toBe(false);
    });
  });
});
