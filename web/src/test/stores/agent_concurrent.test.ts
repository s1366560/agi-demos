/**
 * Unit tests for concurrent agent conversation switching.
 *
 * TDD: Tests written first (RED phase) for concurrent conversation support.
 *
 * Feature: Allow users to switch between conversations while one is actively
 * streaming, without interrupting the active conversation's execution.
 *
 * Key requirements:
 * 1. Each conversation maintains its own streaming state
 * 2. Switching conversations should not stop active streams
 * 3. Multiple conversations can stream simultaneously
 * 4. State is properly isolated per conversation
 */

import { act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// FIXME: This test was written for the old agent store (agent.ts).
// The new agentV3 store has a different API. This test needs to be migrated.
import { useAgentV3Store as useAgentStore } from '../../stores/agentV3';

import type { TimelineEvent, WorkPlan, ToolExecution } from '../../types/agent';

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

import { agentService } from '../../services/agentService';

// Helper function to create mock response with all required properties
function createMockResponse(conversationId: string, timeline: TimelineEvent[]) {
  return {
    conversationId,
    timeline,
    total: timeline.length,
    has_more: false,
    first_sequence: null as number | null,
    last_sequence: null as number | null,
  };
}

describe.skip('Agent Store - Concurrent Conversation Switching (RED Phase)', () => {
  beforeEach(() => {
    // Reset store before each test
    const { reset } = useAgentStore.getState();
    reset();
    vi.clearAllMocks();
  });

  describe('Current behavior analysis', () => {
    it('demonstrates global isStreaming is shared across conversations', async () => {
      // This test documents CURRENT behavior (global state)
      // After implementation, this behavior should change

      const conv1Id = 'conv-1';
      const conv2Id = 'conv-2';

      const mockTimeline: TimelineEvent[] = [
        {
          id: '1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'Hello',
          role: 'user',
        },
      ];
      const mockResponse = createMockResponse(conv1Id, mockTimeline);
      vi.mocked(agentService.getConversationMessages).mockResolvedValue(mockResponse);

      // Set conv1 as streaming
      useAgentStore.setState({
        currentConversation: { id: conv1Id, project_id: 'proj-1', title: 'Conv 1' } as any,
        isStreaming: true,
      });

      // Verify global isStreaming is true
      let state = useAgentStore.getState();
      expect(state.isStreaming).toBe(true);

      // Switch to conv2
      const mockTimeline2: TimelineEvent[] = [];
      const mockResponse2 = createMockResponse(conv2Id, mockTimeline2);
      vi.mocked(agentService.getConversationMessages).mockResolvedValue(mockResponse2);

      const { setCurrentConversation } = useAgentStore.getState();

      await act(async () => {
        setCurrentConversation({ id: conv2Id, project_id: 'proj-1', title: 'Conv 2' } as any);
      });

      // CURRENTLY: isStreaming is still true (global state)
      // This is the problem we need to fix
      state = useAgentStore.getState();
      expect(state.isStreaming).toBe(true); // Current behavior - global state

      // After implementation, we expect:
      // - A per-conversation streaming status map
      // - Ability to check streaming status for any conversation
      // - Current conversation's streaming status reflects its actual state
    });

    it('demonstrates global currentThought is shared across conversations', async () => {
      const conv1Id = 'conv-1';
      const conv2Id = 'conv-2';

      // Set conv1 with a thought
      useAgentStore.setState({
        currentConversation: { id: conv1Id, project_id: 'proj-1', title: 'Conv 1' } as any,
        currentThought: 'Thinking in conv 1',
      });

      let state = useAgentStore.getState();
      expect(state.currentThought).toBe('Thinking in conv 1');

      // Switch to conv2
      const mockTimeline2: TimelineEvent[] = [];
      const mockResponse2 = createMockResponse(conv2Id, mockTimeline2);
      vi.mocked(agentService.getConversationMessages).mockResolvedValue(mockResponse2);

      const { setCurrentConversation } = useAgentStore.getState();

      await act(async () => {
        setCurrentConversation({ id: conv2Id, project_id: 'proj-1', title: 'Conv 2' } as any);
      });

      // CURRENTLY: thought is cleared when switching (not persisted)
      state = useAgentStore.getState();
      expect(state.currentThought).toBe(null);

      // After implementation, we expect:
      // - Thoughts to be persisted per conversation
      // - Switching back to conv1 would restore its thought
    });

    it('demonstrates global workPlan is shared across conversations', async () => {
      const conv1Id = 'conv-1';
      const conv2Id = 'conv-2';

      const mockWorkPlan: WorkPlan = {
        id: 'plan-1',
        conversation_id: conv1Id,
        status: 'in_progress',
        steps: [
          {
            step_number: 1,
            description: 'Step 1',
            thought_prompt: '',
            required_tools: [],
            expected_output: '',
            dependencies: [],
          },
        ],
        current_step_index: 0,
        created_at: new Date().toISOString(),
      };

      // Set conv1 with a work plan
      useAgentStore.setState({
        currentConversation: { id: conv1Id, project_id: 'proj-1', title: 'Conv 1' } as any,
        currentWorkPlan: mockWorkPlan,
      });

      let state = useAgentStore.getState();
      expect(state.currentWorkPlan?.id).toBe('plan-1');

      // Switch to conv2
      const mockTimeline2: TimelineEvent[] = [];
      const mockResponse2 = createMockResponse(conv2Id, mockTimeline2);
      vi.mocked(agentService.getConversationMessages).mockResolvedValue(mockResponse2);

      const { setCurrentConversation } = useAgentStore.getState();

      await act(async () => {
        setCurrentConversation({ id: conv2Id, project_id: 'proj-1', title: 'Conv 2' } as any);
      });

      // CURRENTLY: work plan is lost when switching
      state = useAgentStore.getState();
      expect(state.currentWorkPlan).toBe(null);

      // After implementation, we expect:
      // - Work plans to be persisted per conversation
      // - Switching back to conv1 would restore its work plan
    });

    it('demonstrates per-conversation sendMessageLock allows concurrent conversations', async () => {
      const conv1Id = 'conv-1';
      const conv2Id = 'conv-2';

      const mockResponse = createMockResponse(conv1Id, []);
      vi.mocked(agentService.getConversationMessages).mockResolvedValue(mockResponse);

      // Create a handler reference to track if sendMessage was called
      let sendMessageCallCount = 0;
      let chatResolver: () => void = () => {};

      // Mock chat to simulate long-running stream
      vi.mocked(agentService.chat).mockImplementation(async () => {
        sendMessageCallCount++;
        return new Promise<void>((resolve) => {
          chatResolver = resolve;
        });
      });

      const { sendMessage, setCurrentConversation } = useAgentStore.getState();
      const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      // Start message for conv1 - don't await, let it run
      sendMessage(conv1Id, 'Message 1', 'proj-1').catch(() => {});

      // Wait a tick for state to update
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      });

      const state = useAgentStore.getState();
      expect(state.isStreaming).toBe(true);

      // Try to send message to conv2 - this should NOT be blocked with per-conversation locks
      await act(async () => {
        setCurrentConversation({ id: conv2Id, project_id: 'proj-1', title: 'Conv 2' } as any);
        await sendMessage(conv2Id, 'Message 2', 'proj-1');
      });

      // NEW BEHAVIOR: Second sendMessage should succeed because it's for a different conversation
      const warnCalls = consoleWarnSpy.mock.calls.filter((call) =>
        call.some((arg) => typeof arg === 'string' && arg.includes('already in progress'))
      );

      // Verify lock did NOT block second call (different conversation)
      expect(warnCalls.length).toBe(0);
      // chat should be called twice (both conversations can stream concurrently)
      expect(sendMessageCallCount).toBe(2);

      consoleWarnSpy.mockRestore();

      // Cleanup
      chatResolver();

      // Verify per-conversation streaming status
      const streamingStatuses = useAgentStore.getState().getStreamingStatuses();
      expect(streamingStatuses.get(conv1Id)).toBe(true);
      expect(streamingStatuses.get(conv2Id)).toBe(true);
    });
  });

  describe('API verification', () => {
    it('verifies per-conversation streaming status API exists', () => {
      const state = useAgentStore.getState();

      // New methods should now be available
      expect(typeof state.isConversationStreaming).toBe('function');
      expect(typeof state.getStreamingStatuses).toBe('function');
    });

    it('verifies per-conversation state management API exists', () => {
      const state = useAgentStore.getState();

      // New state management methods should be available
      expect(typeof state.getConversationState).toBe('function');
      expect(typeof state.saveConversationState).toBe('function');
      expect(typeof state.restoreConversationState).toBe('function');
      expect(typeof state.deleteConversationState).toBe('function');
    });

    it('verifies conversationStates is a Map', () => {
      const state = useAgentStore.getState();

      // conversationStates should be a Map
      expect(state.conversationStates).toBeInstanceOf(Map);
    });
  });

  describe('Edge cases for concurrent conversations', () => {
    it('handles switching while tool execution is in progress', async () => {
      const conv1Id = 'conv-1';
      const conv2Id = 'conv-2';

      const mockToolExecution: ToolExecution = {
        id: 'tool-1',
        toolName: 'search',
        input: { query: 'test' },
        status: 'running',
        startTime: new Date().toISOString(),
      };

      // Set conv1 with active tool execution
      useAgentStore.setState({
        currentConversation: { id: conv1Id, project_id: 'proj-1', title: 'Conv 1' } as any,
        currentToolExecution: mockToolExecution,
        isStreaming: true,
      });

      // Switch to conv2
      const mockTimeline2: TimelineEvent[] = [];
      const mockResponse2 = createMockResponse(conv2Id, mockTimeline2);
      vi.mocked(agentService.getConversationMessages).mockResolvedValue(mockResponse2);

      const { setCurrentConversation } = useAgentStore.getState();

      await act(async () => {
        setCurrentConversation({ id: conv2Id, project_id: 'proj-1', title: 'Conv 2' } as any);
      });

      // After switching, tool state should be clean for conv2
      const state = useAgentStore.getState();
      expect(state.currentToolExecution).toBe(null);

      // TODO: After implementation, conv1's tool execution should be preserved
      // expect(state.getToolExecutionForConversation(conv1Id)).toEqual(mockToolExecution);
    });

    it('handles switching while skill execution is in progress', async () => {
      const conv1Id = 'conv-1';
      const conv2Id = 'conv-2';

      // Set conv1 with active skill execution
      useAgentStore.setState({
        currentConversation: { id: conv1Id, project_id: 'proj-1', title: 'Conv 1' } as any,
        currentSkillExecution: {
          skill_id: 'skill-1',
          skill_name: 'Search Skill',
          execution_mode: 'direct', // Fixed: was 'sequential', must be 'direct' | 'prompt'
          match_score: 0.95,
          status: 'executing',
          tools: [],
          tool_executions: [],
          current_step: 0,
          total_steps: 2,
          started_at: new Date().toISOString(),
        },
        isStreaming: true,
      });

      // Switch to conv2
      const mockTimeline2: TimelineEvent[] = [];
      const mockResponse2 = createMockResponse(conv2Id, mockTimeline2);
      vi.mocked(agentService.getConversationMessages).mockResolvedValue(mockResponse2);

      const { setCurrentConversation } = useAgentStore.getState();

      await act(async () => {
        setCurrentConversation({ id: conv2Id, project_id: 'proj-1', title: 'Conv 2' } as any);
      });

      // After switching, skill state should be clean for conv2
      const state = useAgentStore.getState();
      expect(state.currentSkillExecution).toBe(null);

      // TODO: After implementation, conv1's skill execution should be preserved
      // expect(state.getSkillExecutionForConversation(conv1Id)?.status).toBe('executing');
    });

    it('handles rapid switching between multiple conversations', async () => {
      const conv1Id = 'conv-1';
      const conv2Id = 'conv-2';
      const conv3Id = 'conv-3';

      const mockTimeline: TimelineEvent[] = [];
      const mockResponse = createMockResponse(conv1Id, mockTimeline);
      vi.mocked(agentService.getConversationMessages).mockResolvedValue(mockResponse);

      const { setCurrentConversation } = useAgentStore.getState();

      // Rapid switching between 3 conversations
      await act(async () => {
        await setCurrentConversation({ id: conv1Id, project_id: 'proj-1', title: 'Conv 1' } as any);
        await setCurrentConversation({ id: conv2Id, project_id: 'proj-1', title: 'Conv 2' } as any);
        await setCurrentConversation({ id: conv3Id, project_id: 'proj-1', title: 'Conv 3' } as any);
        await setCurrentConversation({ id: conv1Id, project_id: 'proj-1', title: 'Conv 1' } as any);
      });

      // Should handle rapid switching without errors
      const state = useAgentStore.getState();
      expect(state.currentConversation?.id).toBe(conv1Id);
    });
  });
});
