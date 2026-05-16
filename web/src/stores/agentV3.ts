import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

import {
  type ConversationState,
  createDefaultConversationState,
  getHITLSummaryFromState,
  HITLSummary,
} from '../types/conversationState';

import { createActiveConversationActions } from './agent/activeConversationActions';
import { createConversationLifecycleActions } from './agent/conversationLifecycleActions';
import { clearDeltaBuffers, clearAllDeltaBuffers, getDeltaBuffer } from './agent/deltaBuffers';
import { useExecutionStore } from './agent/executionStore';
import { createHITLActions } from './agent/hitlActions';
import { useAgentHITLStore } from './agent/hitlStore';
import { createMessageLoadActions } from './agent/messageLoadActions';
import { createMessageSendActions } from './agent/messageSendActions';
import { registerConversationStatesReader, scheduleSave } from './agent/persistence';
import { createSettingsActions } from './agent/settingsActions';
import { useStreamingStore } from './agent/streamingStore';
import { initTabSync, registerAgentV3Store } from './agent/tabSync';
import { useTimelineStore } from './agent/timelineStore';
import { updateHITLEventInTimeline, timelineToMessages } from './agent/timelineUtils';
import { useCanvasStore } from './canvasStore';
import { useLayoutModeStore } from './layoutMode';

// Extracted factory modules

// Extracted modules

// Re-export types for external consumers
export type { AdditionalAgentHandlers, AgentV3State } from './agent/types';
import type { AgentV3State } from './agent/types';

function resetCanvasForConversationScope(): void {
  useCanvasStore.getState().reset();
  const layoutStore = useLayoutModeStore.getState();
  if (layoutStore.mode === 'canvas') {
    layoutStore.setMode('chat');
  }
}

export const useAgentV3Store = create<AgentV3State>()(
  devtools((set, get) => ({
    conversations: [],
    activeConversationId: null,
    isCreatingConversation: false,
    hasMoreConversations: false,
    conversationsTotal: 0,

    // Per-conversation state map
    conversationStates: new Map<string, ConversationState>(),

    // ===== Multi-conversation state helpers =====

    /**
     * Get state for a specific conversation (creates default if not exists)
     */
    getConversationState: (conversationId: string) => {
      const { conversationStates } = get();
      let state = conversationStates.get(conversationId);
      if (!state) {
        state = createDefaultConversationState();
        // Don't mutate here - just return default
      }
      return state;
    },

    /**
     * Update state for a specific conversation
     */
    updateConversationState: (conversationId: string, updates: Partial<ConversationState>) => {
      set((state) => {
        const newStates = new Map(state.conversationStates);
        const currentState = newStates.get(conversationId) || createDefaultConversationState();

        // Merge updates with current state
        const updatedState: ConversationState = {
          ...currentState,
          ...updates,
          // Special handling for Maps
          activeToolCalls:
            updates.activeToolCalls !== undefined
              ? updates.activeToolCalls
              : currentState.activeToolCalls,
        };

        // Update HITL summary if HITL state changed
        if (
          updates.pendingClarification !== undefined ||
          updates.pendingDecision !== undefined ||
          updates.pendingEnvVarRequest !== undefined ||
          updates.pendingPermission !== undefined
        ) {
          updatedState.pendingHITLSummary = getHITLSummaryFromState(updatedState);
        }

        newStates.set(conversationId, updatedState);

        return { conversationStates: newStates };
      });

      // Persist to IndexedDB (debounced with beforeunload flush support)
      const fullState = get().conversationStates.get(conversationId);
      if (fullState) {
        scheduleSave(conversationId, fullState);
      }

      // Bridge HITL fields to hitlStore when active conversation is updated
      const isActiveAfter = get().activeConversationId === conversationId;
      if (isActiveAfter) {
        const hs = useAgentHITLStore.getState();
        if (updates.pendingClarification !== undefined)
          hs.setPendingClarification(updates.pendingClarification);
        if (updates.pendingDecision !== undefined) hs.setPendingDecision(updates.pendingDecision);
        if (updates.pendingEnvVarRequest !== undefined)
          hs.setPendingEnvVarRequest(updates.pendingEnvVarRequest);
        if (updates.pendingPermission !== undefined)
          hs.setPendingPermission(updates.pendingPermission);
        if (updates.doomLoopDetected !== undefined)
          hs.setDoomLoopDetected(updates.doomLoopDetected);
        if (updates.costTracking !== undefined) hs.setCostTracking(updates.costTracking);
        if (updates.suggestions !== undefined) hs.setSuggestions(updates.suggestions);

        // Bridge timeline fields to timelineStore
        const ts = useTimelineStore.getState();
        if (updates.timeline !== undefined) ts.setAgentTimeline(updates.timeline);
        if (updates.hasEarlier !== undefined) ts.setAgentHasEarlier(updates.hasEarlier);
        if (updates.earliestTimeUs !== undefined || updates.earliestCounter !== undefined) {
          const convState = get().conversationStates.get(conversationId);
          ts.setAgentEarliestPointers(
            updates.earliestTimeUs !== undefined
              ? updates.earliestTimeUs
              : (convState?.earliestTimeUs ?? null),
            updates.earliestCounter !== undefined
              ? updates.earliestCounter
              : (convState?.earliestCounter ?? null)
          );
        }

        // Bridge streaming fields to streamingStore
        const ss = useStreamingStore.getState();
        if (updates.isStreaming !== undefined) ss.setAgentIsStreaming(updates.isStreaming);
        if (updates.streamStatus !== undefined) ss.setAgentStreamStatus(updates.streamStatus);
        if (updates.error !== undefined) ss.setAgentError(updates.error);
        if (updates.streamingAssistantContent !== undefined)
          ss.setAgentStreamingAssistantContent(updates.streamingAssistantContent);
        if (updates.streamingThought !== undefined)
          ss.setAgentStreamingThought(updates.streamingThought);
        if (updates.isThinkingStreaming !== undefined)
          ss.setAgentIsThinkingStreaming(updates.isThinkingStreaming);
        if (updates.currentThought !== undefined) ss.setAgentCurrentThought(updates.currentThought);

        // Bridge execution fields to executionStore
        const es = useExecutionStore.getState();
        if (updates.agentState !== undefined) es.setAgentExecutionState(updates.agentState);
        if (updates.activeToolCalls !== undefined)
          es.setAgentActiveToolCalls(updates.activeToolCalls);
        if (updates.pendingToolsStack !== undefined)
          es.setAgentPendingToolsStack(updates.pendingToolsStack);
        if (updates.isPlanMode !== undefined) es.setAgentIsPlanMode(updates.isPlanMode);
      }
    },

    /**
     * Get count of currently streaming conversations
     */
    getStreamingConversationCount: () => {
      const { conversationStates } = get();
      let count = 0;
      conversationStates.forEach((state) => {
        if (state.isStreaming) count++;
      });
      return count;
    },

    /**
     * Get all conversations with pending HITL requests
     */
    getConversationsWithPendingHITL: () => {
      const { conversationStates } = get();
      const result: Array<{ conversationId: string; summary: HITLSummary }> = [];
      conversationStates.forEach((state, conversationId) => {
        const summary = getHITLSummaryFromState(state);
        if (summary) {
          result.push({ conversationId, summary });
        }
      });
      return result;
    },

    /**
     * Sync global state from active conversation state
     * Call this when switching conversations
     */
    syncActiveConversationState: () => {
      const { activeConversationId, conversationStates } = get();
      if (!activeConversationId) return;

      const convState = conversationStates.get(activeConversationId);
      if (!convState) return;

      // Sync sub-stores from conversation state
      const hs = useAgentHITLStore.getState();
      hs.syncFromConversation({
        pendingClarification: convState.pendingClarification,
        pendingDecision: convState.pendingDecision,
        pendingEnvVarRequest: convState.pendingEnvVarRequest,
        pendingPermission: null,
        doomLoopDetected: convState.doomLoopDetected,
        costTracking: null,
        suggestions: convState.suggestions,
        pinnedEventIds: new Set(),
      });

      const ts = useTimelineStore.getState();
      ts.setAgentTimeline(convState.timeline);
      ts.setAgentHasEarlier(convState.hasEarlier);
      ts.setAgentEarliestPointers(convState.earliestTimeUs, convState.earliestCounter);

      const ss = useStreamingStore.getState();
      ss.setAgentIsStreaming(convState.isStreaming);
      ss.setAgentStreamStatus(convState.streamStatus);
      ss.setAgentError(convState.error);
      ss.setAgentStreamingAssistantContent(convState.streamingAssistantContent);
      ss.setAgentStreamingThought(convState.streamingThought);
      ss.setAgentIsThinkingStreaming(convState.isThinkingStreaming);
      ss.setAgentCurrentThought(convState.currentThought);

      const es = useExecutionStore.getState();
      es.setAgentExecutionState(convState.agentState);
      es.setAgentActiveToolCalls(convState.activeToolCalls);
      es.setAgentPendingToolsStack(convState.pendingToolsStack);
      es.setAgentIsPlanMode(convState.isPlanMode);
    },

    // ===== Extracted action modules =====

    ...createSettingsActions({ get, set }),

    ...createConversationLifecycleActions({ get, set, resetCanvasForConversationScope }),

    ...createActiveConversationActions({ get, set, resetCanvasForConversationScope }),

    ...createMessageLoadActions({ get, set }),

    ...createMessageSendActions({ get, set, resetCanvasForConversationScope }),

    ...createHITLActions({
      get,
      set,
      timelineToMessages,
      clearAllDeltaBuffers,
      getDeltaBuffer,
      clearDeltaBuffers,
      updateHITLEventInTimeline,
    }),
  }))
);

// Initialize tab sync on module load
registerConversationStatesReader(() => useAgentV3Store.getState().conversationStates);
registerAgentV3Store(useAgentV3Store);
initTabSync();
