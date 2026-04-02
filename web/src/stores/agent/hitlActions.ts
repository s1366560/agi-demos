/**
 * HITL (Human-In-The-Loop) response actions extracted from agentV3.ts.
 *
 * Contains respondToClarification, respondToDecision, respondToEnvVar,
 * and respondToPermission actions that use the full stream event handler
 * to properly process all agent events after HITL response.
 */

import { agentService } from '../../services/agentService';
import { tabSync } from '../../utils/tabSync';

import {
  queueTimelineEvent as queueTimelineEventRaw,
  flushTimelineBufferSync as flushTimelineBufferSyncRaw,
  bindTimelineBufferDeps,
} from './deltaBuffers';
import { useExecutionStore } from './executionStore';
import { useStreamingStore } from './streamingStore';
import { useTimelineStore } from './timelineStore';
import { createStreamEventHandlers, type StreamHandlerDeps } from './streamEventHandlers';

import type { DeltaBufferState } from './deltaBuffers';
import type { AgentV3State } from './types';
import type { AgentStreamHandler, TimelineEvent, Message } from '../../types/agent';
import type { ConversationState } from '../../types/conversationState';
import type { StoreApi } from 'zustand';

/**
 * Store setter/getter interface needed by HITL actions
 */
export interface HITLActionDeps {
  get: () => {
    activeConversationId: string | null;
    getConversationState: (conversationId: string) => ConversationState;
    updateConversationState: (conversationId: string, updates: Partial<ConversationState>) => void;
  };
  set: StoreApi<AgentV3State>['setState'];
  timelineToMessages: (timeline: TimelineEvent[]) => Message[];
  clearAllDeltaBuffers: () => void;
  getDeltaBuffer: (conversationId: string) => DeltaBufferState;
  clearDeltaBuffers: (conversationId: string) => void;
  updateHITLEventInTimeline: (
    timeline: TimelineEvent[],
    requestId: string,
    eventType: 'clarification_asked' | 'decision_asked' | 'env_var_requested' | 'permission_asked',
    updates: {
      answered: boolean;
      answer?: string | undefined;
      decision?: string | undefined;
      values?: Record<string, string> | undefined;
      granted?: boolean | undefined;
    }
  ) => TimelineEvent[];
}

const TOKEN_BATCH_INTERVAL_MS = 50;
const THOUGHT_BATCH_INTERVAL_MS = 80;

/**
 * Ensure WebSocket is connected and subscribe with the full stream handler.
 * Uses createStreamEventHandlers for complete event coverage (tool calls,
 * work plans, artifacts, etc.) instead of the minimal simple handler.
 */
async function ensureConnectedAndSubscribe(
  conversationId: string,
  deps: HITLActionDeps
): Promise<void> {
  if (!agentService.isConnected()) {
    await agentService.connect();
  }

  bindTimelineBufferDeps(conversationId, {
    getConversationState: deps.get().getConversationState,
    updateConversationState: deps.get().updateConversationState,
  });

  const handler: AgentStreamHandler = createStreamEventHandlers(conversationId, undefined, {
    get: deps.get,
    set: deps.set as StreamHandlerDeps['set'],
    getDeltaBuffer: deps.getDeltaBuffer,
    clearDeltaBuffers: deps.clearDeltaBuffers,
    clearAllDeltaBuffers: deps.clearAllDeltaBuffers,
    timelineToMessages: deps.timelineToMessages,
    tokenBatchIntervalMs: TOKEN_BATCH_INTERVAL_MS,
    thoughtBatchIntervalMs: THOUGHT_BATCH_INTERVAL_MS,
    queueTimelineEvent: (event, stateUpdates) => {
      queueTimelineEventRaw(conversationId, event, stateUpdates);
    },
    flushTimelineBufferSync: () => {
      flushTimelineBufferSyncRaw(conversationId);
    },
  });

  agentService.subscribe(conversationId, handler);
}

/**
 * Create HITL response actions for the store.
 */
export function createHITLActions(deps: HITLActionDeps) {
  const { get, clearAllDeltaBuffers, updateHITLEventInTimeline } = deps;

  return {
    respondToClarification: async (requestId: string, answer: string): Promise<void> => {
      const { activeConversationId } = get();
      if (!activeConversationId) return;

      try {
        await ensureConnectedAndSubscribe(activeConversationId, deps);

        await agentService.respondToClarification(requestId, answer);
        clearAllDeltaBuffers();

        // Update conversation state (timeline + HITL field)
        const convState = get().getConversationState(activeConversationId);
        const updatedTimeline = updateHITLEventInTimeline(convState.timeline, requestId, 'clarification_asked', {
          answered: true,
          answer,
        });
        get().updateConversationState(activeConversationId, {
          timeline: updatedTimeline,
          pendingClarification: null,
          agentState: 'thinking',
          isStreaming: true,
          streamStatus: 'streaming',
          streamingAssistantContent: '',
        });

        // Update sub-stores
        useTimelineStore.getState().setAgentTimeline(updatedTimeline);
        useStreamingStore.getState().setAgentIsStreaming(true);
        useStreamingStore.getState().setAgentStreamStatus('streaming');
        useStreamingStore.getState().setAgentStreamingAssistantContent('');
        useExecutionStore.getState().setAgentExecutionState('thinking');

        if (activeConversationId) {
          tabSync.broadcastHITLStateChanged(activeConversationId, false, 'clarification');
        }
      } catch (error) {
        console.error('Failed to respond to clarification:', error);
        useExecutionStore.getState().setAgentExecutionState('idle');
        useStreamingStore.getState().setAgentIsStreaming(false);
        useStreamingStore.getState().setAgentStreamStatus('idle');
      }
    },

    respondToDecision: async (requestId: string, decision: string | string[]): Promise<void> => {
      const { activeConversationId } = get();
      if (!activeConversationId) return;

      try {
        await ensureConnectedAndSubscribe(activeConversationId, deps);

        await agentService.respondToDecision(requestId, decision);
        clearAllDeltaBuffers();

        const convState = get().getConversationState(activeConversationId);
        const updatedTimeline = updateHITLEventInTimeline(convState.timeline, requestId, 'decision_asked', {
          answered: true,
          decision: Array.isArray(decision) ? decision.join(', ') : decision,
        });
        get().updateConversationState(activeConversationId, {
          timeline: updatedTimeline,
          pendingDecision: null,
          agentState: 'thinking',
          isStreaming: true,
          streamStatus: 'streaming',
          streamingAssistantContent: '',
        });

        useTimelineStore.getState().setAgentTimeline(updatedTimeline);
        useStreamingStore.getState().setAgentIsStreaming(true);
        useStreamingStore.getState().setAgentStreamStatus('streaming');
        useStreamingStore.getState().setAgentStreamingAssistantContent('');
        useExecutionStore.getState().setAgentExecutionState('thinking');

        if (activeConversationId) {
          tabSync.broadcastHITLStateChanged(activeConversationId, false, 'decision');
        }
      } catch (error) {
        console.error('Failed to respond to decision:', error);
        useExecutionStore.getState().setAgentExecutionState('idle');
        useStreamingStore.getState().setAgentIsStreaming(false);
        useStreamingStore.getState().setAgentStreamStatus('idle');
      }
    },

    respondToEnvVar: async (requestId: string, values: Record<string, string>): Promise<void> => {
      const { activeConversationId } = get();
      if (!activeConversationId) return;

      try {
        await ensureConnectedAndSubscribe(activeConversationId, deps);

        await agentService.respondToEnvVar(requestId, values);
        clearAllDeltaBuffers();

        const convState = get().getConversationState(activeConversationId);
        const updatedTimeline = updateHITLEventInTimeline(convState.timeline, requestId, 'env_var_requested', {
          answered: true,
          values,
        });
        get().updateConversationState(activeConversationId, {
          timeline: updatedTimeline,
          pendingEnvVarRequest: null,
          agentState: 'thinking',
          isStreaming: true,
          streamStatus: 'streaming',
          streamingAssistantContent: '',
        });

        useTimelineStore.getState().setAgentTimeline(updatedTimeline);
        useStreamingStore.getState().setAgentIsStreaming(true);
        useStreamingStore.getState().setAgentStreamStatus('streaming');
        useStreamingStore.getState().setAgentStreamingAssistantContent('');
        useExecutionStore.getState().setAgentExecutionState('thinking');

        if (activeConversationId) {
          tabSync.broadcastHITLStateChanged(activeConversationId, false, 'env_var');
        }
      } catch (error) {
        console.error('Failed to respond to env var request:', error);
        useExecutionStore.getState().setAgentExecutionState('idle');
        useStreamingStore.getState().setAgentIsStreaming(false);
        useStreamingStore.getState().setAgentStreamStatus('idle');
      }
    },

    respondToPermission: async (requestId: string, granted: boolean): Promise<void> => {
      const { activeConversationId } = get();
      if (!activeConversationId) return;

      try {
        await ensureConnectedAndSubscribe(activeConversationId, deps);

        await agentService.respondToPermission(requestId, granted);
        clearAllDeltaBuffers();

        const convState = get().getConversationState(activeConversationId);
        const updatedTimeline = updateHITLEventInTimeline(convState.timeline, requestId, 'permission_asked', {
          answered: true,
          granted,
        });
        get().updateConversationState(activeConversationId, {
          timeline: updatedTimeline,
          pendingPermission: null,
          agentState: granted ? 'thinking' : 'idle',
          isStreaming: granted,
          streamStatus: granted ? 'streaming' : 'idle',
          streamingAssistantContent: '',
        });

        useTimelineStore.getState().setAgentTimeline(updatedTimeline);
        useStreamingStore.getState().setAgentIsStreaming(granted);
        useStreamingStore.getState().setAgentStreamStatus(granted ? 'streaming' : 'idle');
        useStreamingStore.getState().setAgentStreamingAssistantContent('');
        useExecutionStore.getState().setAgentExecutionState(granted ? 'thinking' : 'idle');

        if (activeConversationId) {
          tabSync.broadcastHITLStateChanged(activeConversationId, false, 'permission');
        }
      } catch (error) {
        console.error('Failed to respond to permission request:', error);
        useExecutionStore.getState().setAgentExecutionState('idle');
        useStreamingStore.getState().setAgentIsStreaming(false);
        useStreamingStore.getState().setAgentStreamStatus('idle');
      }
    },
  };
}
