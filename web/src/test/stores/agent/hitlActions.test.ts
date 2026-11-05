import { afterEach, describe, expect, it, vi } from 'vitest';

import { agentService } from '../../../services/agentService';
import { createHITLActions } from '../../../stores/agent/hitlActions';
import { useStreamingStore } from '../../../stores/agent/streamingStore';
import { createDefaultConversationState } from '../../../types/conversationState';
import { installResourceOperationFixtureV2 } from '../../services/webResourceOperationFixtureV2';

import type { ConversationState } from '../../../types/conversationState';

afterEach(() => vi.restoreAllMocks());

describe('permission response failures', () => {
  it('keeps the permission pending, exposes the error and rejects to the submitting card', async () => {
    const fixture = installResourceOperationFixtureV2();
    const failure = new Error('Permission response connection failed');
    vi.spyOn(agentService, 'connectSession').mockRejectedValue(failure);
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const state = createDefaultConversationState();
    const update = vi.fn();
    const updateHITLEventInTimeline = vi.fn(() => []);
    const actions = createHITLActions({
      get: () => ({
        activeConversationId: 'conversation-1',
        respondToPermission: vi.fn(),
        getConversationState: () => state,
        updateConversationState: update,
      }),
      set: vi.fn(),
      timelineToMessages: () => [],
      clearAllDeltaBuffers: vi.fn(),
      clearDeltaBuffers: vi.fn(),
      getDeltaBuffer: vi.fn(),
      updateHITLEventInTimeline,
    });

    try {
      await expect(actions.respondToPermission('permission-1', true)).rejects.toBe(failure);
      expect(updateHITLEventInTimeline).not.toHaveBeenCalled();
      expect(update).toHaveBeenCalledWith('conversation-1', {
        error: failure.message,
      });
    } finally {
      await fixture.close();
    }
  });

  it('keeps the run streaming after denying one tool request', async () => {
    const fixture = installResourceOperationFixtureV2();
    const state = {
      ...createDefaultConversationState(),
      isStreaming: true,
      streamStatus: 'streaming' as const,
      agentState: 'awaiting_input' as const,
      streamingAssistantContent: 'Partial answer',
    };
    const update = vi.fn();
    const clearAllDeltaBuffers = vi.fn();
    const actions = createHITLActions({
      get: () => ({
        activeConversationId: 'conversation-1',
        respondToPermission: vi.fn(),
        getConversationState: () => state,
        updateConversationState: update,
      }),
      set: vi.fn(),
      timelineToMessages: () => [],
      clearAllDeltaBuffers,
      clearDeltaBuffers: vi.fn(),
      getDeltaBuffer: vi.fn(),
      updateHITLEventInTimeline: vi.fn(() => []),
    });

    try {
      await fixture.admission.run(async (operation) => {
        vi.spyOn(agentService, 'connectSession').mockResolvedValue(operation);
        vi.spyOn(agentService, 'getOperationContext').mockReturnValue(operation);
        vi.spyOn(agentService, 'subscribe').mockReturnValue(() => undefined);
        vi.spyOn(agentService, 'respondToPermission').mockResolvedValue(undefined);

        await actions.respondToPermission('permission-1', false);

        expect(agentService.respondToPermission).toHaveBeenCalledWith('permission-1', false);
        expect(update).toHaveBeenCalledWith('conversation-1', {
          timeline: [],
          pendingPermission: null,
          agentState: 'thinking',
        });
        expect(clearAllDeltaBuffers).not.toHaveBeenCalled();
      });
    } finally {
      await fixture.close();
    }
  });

  it.each([true, false])(
    'preserves a terminal state when permission verdict %s returns after completion',
    async (granted) => {
      const fixture = installResourceOperationFixtureV2();
      const state: ConversationState = {
        ...createDefaultConversationState(),
        isStreaming: true,
        streamStatus: 'streaming',
        agentState: 'awaiting_input',
      };
      const actions = createHITLActions({
        get: () => ({
          activeConversationId: 'conversation-1',
          respondToPermission: vi.fn(),
          getConversationState: () => state,
          updateConversationState: (_id, updates) => Object.assign(state, updates),
        }),
        set: vi.fn(),
        timelineToMessages: () => [],
        clearAllDeltaBuffers: vi.fn(),
        clearDeltaBuffers: vi.fn(),
        getDeltaBuffer: vi.fn(),
        updateHITLEventInTimeline: vi.fn(() => []),
      });

      try {
        await fixture.admission.run(async (operation) => {
          vi.spyOn(agentService, 'connectSession').mockResolvedValue(operation);
          vi.spyOn(agentService, 'getOperationContext').mockReturnValue(operation);
          vi.spyOn(agentService, 'subscribe').mockReturnValue(() => undefined);
          vi.spyOn(agentService, 'respondToPermission').mockImplementation(async () => {
            // The server's terminal event is applied while the HTTP reply is in flight.
            Object.assign(state, {
              isStreaming: false,
              streamStatus: 'idle',
              agentState: 'idle',
            });
            useStreamingStore.getState().setAgentIsStreaming(false);
            useStreamingStore.getState().setAgentStreamStatus('idle');
          });

          await actions.respondToPermission('permission-1', granted);

          expect(state).toMatchObject({
            isStreaming: false,
            streamStatus: 'idle',
            agentState: 'idle',
            pendingPermission: null,
          });
          expect(useStreamingStore.getState().agentIsStreaming).toBe(false);
          expect(useStreamingStore.getState().agentStreamStatus).toBe('idle');
        });
      } finally {
        await fixture.close();
      }
    }
  );
});
