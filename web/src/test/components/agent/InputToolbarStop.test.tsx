import { Suspense } from 'react';

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { InputToolbar } from '@/components/agent/InputToolbar';
import { ApiError, ApiErrorType } from '@/services/client/ApiError';
import { httpClient } from '@/services/client/httpClient';
import * as agentPersistence from '@/stores/agent/persistence';
import { useStreamingStore } from '@/stores/agent/streamingStore';
import { useAgentV3Store } from '@/stores/agentV3';
import { createDefaultConversationState } from '@/types/conversationState';

import { installResourceOperationFixtureV2 } from '../../services/webResourceOperationFixtureV2';

vi.mock('@/components/agent/ComposerPlusMenu', () => ({ ComposerPlusMenu: () => null }));
vi.mock('@/components/agent/PermissionModeSwitcher', () => ({
  PermissionModeSwitcher: () => null,
}));
vi.mock('@/components/agent/ThinkingLevelSwitcher', () => ({ ThinkingLevelSwitcher: () => null }));
vi.mock('@/components/agent/chat/ModelSwitchPopover', () => ({ ModelSwitchPopover: () => null }));
vi.mock('@/components/agent/chat/VoiceWaveform', () => ({ VoiceWaveform: () => null }));
vi.mock('@/components/plugins/PluginSlotOutlet', () => ({ PluginSlotOutlet: () => null }));

describe('Stop button cancellation integration', () => {
  it('uses the current conversation ID and exposes a rejected cancellation in that conversation', async () => {
    const fixture = installResourceOperationFixtureV2();
    const previousAgentState = useAgentV3Store.getState();
    const previousStreamingState = useStreamingStore.getState();
    const conversationId = 'conversation-current';
    const message = 'Resolve the pending interaction before cancelling this run';
    vi.spyOn(agentPersistence, 'scheduleSave').mockImplementation(() => undefined);
    useAgentV3Store.setState({
      activeConversationId: conversationId,
      conversationStates: new Map([
        [
          conversationId,
          {
            ...createDefaultConversationState(),
            isStreaming: true,
            streamStatus: 'streaming',
            agentState: 'awaiting_input',
          },
        ],
      ]),
    });
    vi.spyOn(httpClient, 'get').mockResolvedValue({
      active_run: {
        id: 'run-current',
        turn_id: 'turn-current',
        conversation_id: conversationId,
        revision: 7,
        status: 'running',
        allowed_actions: ['kill_run'],
        authority_revision: 7,
      },
    });
    vi.spyOn(httpClient, 'post').mockRejectedValue(
      new ApiError(ApiErrorType.CONFLICT, 'CONFLICT', message, 409)
    );
    const view = render(
      <Suspense fallback={null}>
        <InputToolbar
          fileInputRef={{ current: null }}
          attachments={[]}
          capabilities={{
            model: null,
            supportsAttachment: true,
            supportsTemperature: true,
            supportsTopP: true,
            supportsFrequencyPenalty: true,
            supportsPresencePenalty: true,
            supportsSeed: true,
            supportsStop: true,
            supportsResponseFormat: true,
            temperatureRange: [0, 2],
            topPRange: [0, 1],
            maxOutputTokens: 128000,
          }}
          setTemplateLibraryVisible={vi.fn()}
          isListening={false}
          voiceAnalyser={null}
          voiceOperation={null}
          toggleVoiceInput={async () => undefined}
          voiceCallStatus="idle"
          handleVoiceCall={vi.fn()}
          activeConversationId={conversationId}
          isStreaming
          onSlashSelect={vi.fn()}
          charCount={0}
          canSend={false}
          handleSend={vi.fn()}
          onAbort={useAgentV3Store.getState().abortStream}
        />
      </Suspense>
    );

    try {
      fireEvent.click(await screen.findByRole('button', { name: 'Stop' }));

      await waitFor(() => {
        expect(httpClient.get).toHaveBeenCalledWith(
          `/agent/conversations/${conversationId}/active-run`
        );
        expect(httpClient.post).toHaveBeenCalledWith('/agent/runs/run-current/cancel', {
          expected_revision: 7,
        });
        expect(useAgentV3Store.getState().getConversationState(conversationId)).toMatchObject({
          error: message,
          isStreaming: true,
          streamStatus: 'streaming',
          agentState: 'awaiting_input',
        });
        expect(useStreamingStore.getState().agentError).toBe(message);
      });
      expect([...useAgentV3Store.getState().conversationStates.keys()]).toEqual([conversationId]);
    } finally {
      view.unmount();
      useAgentV3Store.setState(previousAgentState, true);
      useStreamingStore.setState(previousStreamingState, true);
      vi.restoreAllMocks();
      await fixture.close();
    }
  });
});
