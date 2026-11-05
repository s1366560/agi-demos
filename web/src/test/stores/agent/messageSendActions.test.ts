import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { agentService } from '../../../services/agentService';
import { ApiError, ApiErrorType } from '../../../services/client/ApiError';
import { runInputService } from '../../../services/runInputService';
import * as deltaBuffers from '../../../stores/agent/deltaBuffers';
import { createMessageSendActions } from '../../../stores/agent/messageSendActions';
import { createDefaultConversationState } from '../../../types/conversationState';
import { installResourceOperationFixtureV2 } from '../../services/webResourceOperationFixtureV2';

import type { ConversationState } from '../../../types/conversationState';

describe('abortStream', () => {
  let fixture: ReturnType<typeof installResourceOperationFixtureV2>;
  let state: ConversationState;
  let actions: ReturnType<typeof createMessageSendActions>;

  beforeEach(() => {
    fixture = installResourceOperationFixtureV2();
    state = {
      ...createDefaultConversationState(),
      isStreaming: true,
      streamStatus: 'streaming',
      agentState: 'acting',
      streamingAssistantContent: 'Partial answer',
      streamingThought: 'Current reasoning',
      pendingToolsStack: ['memory_update'],
    };
    vi.spyOn(agentService, 'stopChat').mockReturnValue(true);
    vi.spyOn(deltaBuffers, 'clearDeltaBuffers');
    vi.spyOn(runInputService, 'getActiveRun').mockResolvedValue({
      conversation_id: 'conversation-1',
      run_id: 'run-7',
      turn_id: 'turn-1',
      run_revision: 7,
      status: 'running',
      allowed_actions: ['kill_run'],
      authority_revision: 7,
    });
    actions = createMessageSendActions({
      get: () => ({
        activeConversationId: 'conversation-1',
        conversationStates: new Map([['conversation-1', state]]),
        respondToPermission: vi.fn(),
        getConversationState: () => state,
        updateConversationState: (_id, updates) => Object.assign(state, updates),
        getStreamingConversationCount: () => 1,
      }),
      set: vi.fn(),
      resetCanvasForConversationScope: vi.fn(),
    });
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    await fixture.close();
  });

  it('requests cancellation for the authoritative run and preserves streaming until terminal events', async () => {
    vi.spyOn(runInputService, 'cancel').mockResolvedValue({
      accepted: true,
      status: 'cancel_requested',
      run: { id: 'run-7', revision: 7, status: 'running' },
    });

    await actions.abortStream();

    expect(runInputService.getActiveRun).toHaveBeenCalledWith('conversation-1');
    expect(runInputService.cancel).toHaveBeenCalledWith('run-7', 7);
    expect(agentService.stopChat).not.toHaveBeenCalled();
    expect(deltaBuffers.clearDeltaBuffers).not.toHaveBeenCalled();
    expect(state).toMatchObject({
      isStreaming: true,
      streamStatus: 'streaming',
      agentState: 'acting',
      streamingAssistantContent: 'Partial answer',
      streamingThought: 'Current reasoning',
      pendingToolsStack: ['memory_update'],
    });
  });

  it('surfaces a rejected cancellation without pretending that the run stopped', async () => {
    const message = 'Resolve the pending interaction before cancelling this run';
    vi.spyOn(runInputService, 'cancel').mockRejectedValue(
      new ApiError(ApiErrorType.CONFLICT, 'CONFLICT', message, 409)
    );

    await actions.abortStream();

    expect(state).toMatchObject({
      error: message,
      isStreaming: true,
      streamStatus: 'streaming',
      agentState: 'acting',
      streamingAssistantContent: 'Partial answer',
      pendingToolsStack: ['memory_update'],
    });
    expect(deltaBuffers.clearDeltaBuffers).not.toHaveBeenCalled();
  });
});
