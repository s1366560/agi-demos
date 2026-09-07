import { getWebOperationAvailabilityV2 } from '../../plugins/webOperationAdmissionV2';
/**
 * Settings-related actions extracted from agentV3.ts.
 *
 * Contains setLlmOverrides, setLlmModelOverride, loadPendingHITL,
 * clearError, and togglePinEvent actions.
 */

import { useExecutionStore } from './executionStore';
import { useAgentHITLStore } from './hitlStore';
import { useStreamingStore } from './streamingStore';

import type { AgentV3State } from './types';
import type { ConversationState } from '../../types/conversationState';
import type { LLMConfigOverrides } from '../../types/memory';
import type { StoreApi } from 'zustand';

export interface SettingsActionDeps {
  get: () => {
    conversationStates: Map<string, ConversationState>;
    updateConversationState: (conversationId: string, updates: Partial<ConversationState>) => void;
  };
  set: StoreApi<AgentV3State>['setState'];
}

export function createSettingsActions(deps: SettingsActionDeps) {
  const { get } = deps;

  return {
    /**
     * Set LLM parameter overrides for a conversation.
     * Stored inside appModelContext.llm_overrides so it flows via the existing
     * app_model_context WebSocket field to the backend.
     */
    setLlmOverrides: (conversationId: string, overrides: LLMConfigOverrides | null): void => {
      const { updateConversationState, conversationStates } = get();
      const convState = conversationStates.get(conversationId);
      const currentCtx = convState?.appModelContext ?? {};
      if (overrides) {
        updateConversationState(conversationId, {
          appModelContext: { ...currentCtx, llm_overrides: overrides },
        });
      } else {
        // Remove llm_overrides key
        const { llm_overrides: _, ...rest } = currentCtx;
        updateConversationState(conversationId, {
          appModelContext: Object.keys(rest).length > 0 ? rest : null,
        });
      }
    },

    /**
     * Set per-conversation LLM model override.
     * Stored inside appModelContext.llm_model_override and sent via app_model_context.
     */
    setLlmModelOverride: (conversationId: string, modelName: string | null): void => {
      const { updateConversationState, conversationStates } = get();
      const convState = conversationStates.get(conversationId);
      const currentCtx = convState?.appModelContext ?? {};

      const normalizedModel = modelName?.trim() || null;
      if (normalizedModel) {
        updateConversationState(conversationId, {
          appModelContext: { ...currentCtx, llm_model_override: normalizedModel },
        });
      } else {
        const { llm_model_override: _removed, ...rest } = currentCtx;
        updateConversationState(conversationId, {
          appModelContext: Object.keys(rest).length > 0 ? rest : null,
        });
      }
    },

    /**
     * Load pending HITL (Human-In-The-Loop) requests for a conversation
     * This is used to restore dialog state after page refresh
     *
     * Shows dialogs for all pending requests. If Agent crashed/restarted,
     * the recovery service will handle it when Worker restarts.
     */
    loadPendingHITL: async (conversationId: string): Promise<void> => {
      const owner = getWebOperationAvailabilityV2().owner;
      await useAgentHITLStore.getState().loadPendingHITL(conversationId);
      if (
        !getWebOperationAvailabilityV2().available ||
        getWebOperationAvailabilityV2().owner !== owner
      )
        return;
      const hs = useAgentHITLStore.getState();
      if (hs.pendingClarification || hs.pendingDecision || hs.pendingEnvVarRequest) {
        useExecutionStore.getState().setAgentExecutionState('awaiting_input');
      }
    },

    clearError: (): void => {
      useStreamingStore.getState().setAgentError(null);
    },

    togglePinEvent: (eventId: string): void => {
      useAgentHITLStore.getState().togglePinEvent(eventId);
    },
  };
}
