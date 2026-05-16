/**
 * Active conversation switching action extracted from agentV3.ts.
 *
 * Contains setActiveConversation which handles saving current state,
 * LRU eviction, and restoring new conversation state.
 */

import {
  createDefaultConversationState,
  type ConversationState,
} from '../../types/conversationState';
import { getHITLSummaryFromState } from '../../types/conversationState';
import { saveConversationState } from '../../utils/conversationDB';
import { useContextStore } from '../contextStore';

import { replayCanvasEventsFromTimeline } from './canvasReplay';
import { useConversationsStore } from './conversationsStore';
import { clearAllDeltaBuffers, clearAllTimelineBuffers } from './deltaBuffers';
import { useExecutionStore } from './executionStore';
import { useAgentHITLStore } from './hitlStore';
import { touchConversation, evictStaleConversationStates } from './persistence';
import { useStreamingStore } from './streamingStore';
import { useTimelineStore } from './timelineStore';

import type { AgentV3State } from './types';
import type { StoreApi } from 'zustand';

export interface ActiveConversationDeps {
  get: () => {
    activeConversationId: string | null;
    conversationStates: Map<string, ConversationState>;
  };
  set: StoreApi<AgentV3State>['setState'];
  resetCanvasForConversationScope: () => void;
}

export function createActiveConversationActions(deps: ActiveConversationDeps) {
  const { get, set, resetCanvasForConversationScope } = deps;

  return {
    setActiveConversation: (id: string | null): void => {
      const { activeConversationId, conversationStates } = get();

      // Skip if already on this conversation
      if (activeConversationId === id) return;

      // CRITICAL: Clear delta buffers when switching conversations
      clearAllDeltaBuffers();
      clearAllTimelineBuffers();
      resetCanvasForConversationScope();

      // Reset context status for the new conversation.
      useContextStore.getState().reset();

      // Save current conversation state before switching
      if (activeConversationId && activeConversationId !== id) {
        const newStates = new Map(conversationStates);
        const currentState =
          newStates.get(activeConversationId) || createDefaultConversationState();

        // Read current sub-store state to persist back into conversation Map
        const ss = useStreamingStore.getState();
        const es = useExecutionStore.getState();
        const ts = useTimelineStore.getState();
        const hs = useAgentHITLStore.getState();

        newStates.set(activeConversationId, {
          ...currentState,
          timeline: ts.agentTimeline,
          hasEarlier: ts.agentHasEarlier,
          earliestTimeUs: ts.agentEarliestTimeUs,
          earliestCounter: ts.agentEarliestCounter,
          isStreaming: ss.agentIsStreaming,
          streamStatus: ss.agentStreamStatus,
          streamingAssistantContent: ss.agentStreamingAssistantContent,
          error: ss.agentError,
          agentState: es.agentExecutionState,
          currentThought: ss.agentCurrentThought,
          streamingThought: ss.agentStreamingThought,
          isThinkingStreaming: ss.agentIsThinkingStreaming,
          activeToolCalls: es.agentActiveToolCalls,
          pendingToolsStack: es.agentPendingToolsStack,
          isPlanMode: es.agentIsPlanMode,
          pendingClarification: hs.pendingClarification,
          pendingDecision: hs.pendingDecision,
          pendingEnvVarRequest: hs.pendingEnvVarRequest,
          doomLoopDetected: hs.doomLoopDetected,
          pendingHITLSummary: getHITLSummaryFromState({
            ...currentState,
            pendingClarification: hs.pendingClarification,
            pendingDecision: hs.pendingDecision,
            pendingEnvVarRequest: hs.pendingEnvVarRequest,
          } as ConversationState),
        });
        set({ conversationStates: newStates });

        // Persist to IndexedDB
        saveConversationState(
          activeConversationId,
          newStates.get(activeConversationId) as ConversationState
        ).catch(console.error);
      }

      // Track LRU access order and evict stale entries
      if (id) {
        touchConversation(id);
      }
      {
        const currentStates = get().conversationStates;
        const evictedStates = evictStaleConversationStates(currentStates, id);
        if (evictedStates.size !== currentStates.size) {
          set({ conversationStates: evictedStates });
        }
      }

      // Load new conversation state if exists
      if (id) {
        const newState = conversationStates.get(id);
        if (newState) {
          // Sort timeline by eventTimeUs + eventCounter to ensure correct order
          const sortedTimeline = [...newState.timeline].sort((a, b) => {
            const timeDiff = a.eventTimeUs - b.eventTimeUs;
            if (timeDiff !== 0) return timeDiff;
            return a.eventCounter - b.eventCounter;
          });
          set({
            activeConversationId: id,
          });

          // Sync sub-stores from loaded conversation state
          useTimelineStore.getState().setAgentTimeline(sortedTimeline);
          useTimelineStore.getState().setAgentHasEarlier(newState.hasEarlier);
          useTimelineStore
            .getState()
            .setAgentEarliestPointers(newState.earliestTimeUs, newState.earliestCounter);

          useStreamingStore.getState().setAgentIsStreaming(newState.isStreaming);
          useStreamingStore.getState().setAgentStreamStatus(newState.streamStatus);
          useStreamingStore
            .getState()
            .setAgentStreamingAssistantContent(newState.streamingAssistantContent);
          useStreamingStore.getState().setAgentError(newState.error);
          useStreamingStore.getState().setAgentCurrentThought(newState.currentThought);
          useStreamingStore.getState().setAgentStreamingThought(newState.streamingThought);
          useStreamingStore.getState().setAgentIsThinkingStreaming(newState.isThinkingStreaming);

          useExecutionStore.getState().setAgentExecutionState(newState.agentState);
          useExecutionStore.getState().setAgentActiveToolCalls(newState.activeToolCalls);
          useExecutionStore.getState().setAgentPendingToolsStack(newState.pendingToolsStack);
          useExecutionStore.getState().setAgentIsPlanMode(newState.isPlanMode);

          useAgentHITLStore.getState().syncFromConversation({
            pendingClarification: newState.pendingClarification,
            pendingDecision: newState.pendingDecision,
            pendingEnvVarRequest: newState.pendingEnvVarRequest,
            pendingPermission: null,
            doomLoopDetected: newState.doomLoopDetected,
            costTracking: null,
            suggestions: newState.suggestions,
            pinnedEventIds: new Set(),
          });
          // Sync currentConversation to conversationsStore
          const convForLoaded = useConversationsStore
            .getState()
            .conversations.find((c) => c.id === id);
          useConversationsStore.getState().setCurrentConversation(convForLoaded ?? null);
          replayCanvasEventsFromTimeline(sortedTimeline);
          return;
        }
      }

      // Default state for new/unloaded conversation
      set({
        activeConversationId: id,
      });

      // Reset all sub-stores to defaults
      useTimelineStore.getState().setAgentTimeline([]);
      useTimelineStore.getState().setAgentHasEarlier(false);
      useTimelineStore.getState().setAgentEarliestPointers(null, null);

      useStreamingStore.getState().resetAgentStreaming();

      useExecutionStore.getState().resetAgentExecution();

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
      const convForDefault = id
        ? (useConversationsStore.getState().conversations.find((c) => c.id === id) ?? null)
        : null;
      useConversationsStore.getState().setCurrentConversation(convForDefault);
    },
  };
}
