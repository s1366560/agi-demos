import { useConversationsStore } from './agent/conversationsStore';
import { useExecutionStore } from './agent/executionStore';
import { useAgentHITLStore } from './agent/hitlStore';
import { useStreamingStore } from './agent/streamingStore';
import { useTimelineStore } from './agent/timelineStore';
import { useAgentV3Store } from './agentV3';

export function retireTenantAgent() {
  useAgentV3Store.setState((state) => ({
    conversations: [],
    activeConversationId: null,
    isCreatingConversation: false,
    hasMoreConversations: false,
    conversationsTotal: 0,
    conversationStates: new Map(),
    conversationScopeGeneration: state.conversationScopeGeneration + 1,
  }));
  useConversationsStore.getState().reset();
  useTimelineStore.getState().reset();
  useStreamingStore.getState().reset();
  useExecutionStore.getState().reset();
  useAgentHITLStore.getState().syncFromConversation({
    pendingClarification: null,
    pendingDecision: null,
    pendingEnvVarRequest: null,
    pendingPermission: null,
    doomLoopDetected: null,
    costTracking: null,
    suggestions: [],
    pinnedEventIds: new Set(),
  });
}
