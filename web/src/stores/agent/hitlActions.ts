/**
 * HITL (Human-In-The-Loop) response actions extracted from agentV3.ts.
 *
 * Contains respondToClarification, respondToDecision, respondToEnvVar,
 * and respondToPermission actions that use the full stream event handler
 * to properly process all agent events after HITL response.
 */

import { agentService } from '../../services/agentService';
import { tabSync } from '../../utils/tabSync';

import { createStreamEventHandlers } from './streamEventHandlers';

import type { DeltaBufferState } from './streamEventHandlers';
import type { AgentStreamHandler, TimelineEvent } from '../../types/agent';

/**
 * Store setter/getter interface needed by HITL actions
 */
export interface HITLActionDeps {
  get: () => {
    activeConversationId: string | null;
  };
  set: (updater: any) => void;
  timelineToMessages: (timeline: TimelineEvent[]) => any[];
  clearAllDeltaBuffers: () => void;
  getDeltaBuffer: (conversationId: string) => DeltaBufferState;
  clearDeltaBuffers: (conversationId: string) => void;
  updateHITLEventInTimeline: (
    timeline: TimelineEvent[],
    requestId: string,
    eventType: 'clarification_asked' | 'decision_asked' | 'env_var_requested' | 'permission_asked',
    updates: {
      answered: boolean;
      answer?: string;
      decision?: string;
      values?: Record<string, string>;
      granted?: boolean;
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

  const handler: AgentStreamHandler = createStreamEventHandlers(conversationId, undefined, {
    get: deps.get as any,
    set: deps.set as any,
    getDeltaBuffer: deps.getDeltaBuffer,
    clearDeltaBuffers: deps.clearDeltaBuffers,
    clearAllDeltaBuffers: deps.clearAllDeltaBuffers,
    timelineToMessages: deps.timelineToMessages,
    tokenBatchIntervalMs: TOKEN_BATCH_INTERVAL_MS,
    thoughtBatchIntervalMs: THOUGHT_BATCH_INTERVAL_MS,
  });

  agentService.subscribe(conversationId, handler);
}

/**
 * Create HITL response actions for the store.
 */
export function createHITLActions(deps: HITLActionDeps) {
  const { get, set, clearAllDeltaBuffers, updateHITLEventInTimeline } = deps;
  const setState = set as any;

  return {
    respondToClarification: async (requestId: string, answer: string): Promise<void> => {
      const { activeConversationId } = get();
      if (!activeConversationId) return;

      try {
        await ensureConnectedAndSubscribe(activeConversationId, deps);

        await agentService.respondToClarification(requestId, answer);
        clearAllDeltaBuffers();
        setState((state: any) => ({
          timeline: updateHITLEventInTimeline(state.timeline, requestId, 'clarification_asked', {
            answered: true,
            answer,
          }),
          pendingClarification: null,
          agentState: 'thinking',
          isStreaming: true,
          streamStatus: 'streaming',
          streamingAssistantContent: '',
        }));

        if (activeConversationId) {
          tabSync.broadcastHITLStateChanged(activeConversationId, false, 'clarification');
        }
      } catch (error) {
        console.error('Failed to respond to clarification:', error);
        setState({ agentState: 'idle', isStreaming: false, streamStatus: 'idle' });
      }
    },

    respondToDecision: async (requestId: string, decision: string): Promise<void> => {
      const { activeConversationId } = get();
      if (!activeConversationId) return;

      try {
        await ensureConnectedAndSubscribe(activeConversationId, deps);

        await agentService.respondToDecision(requestId, decision);
        clearAllDeltaBuffers();
        setState((state: any) => ({
          timeline: updateHITLEventInTimeline(state.timeline, requestId, 'decision_asked', {
            answered: true,
            decision,
          }),
          pendingDecision: null,
          agentState: 'thinking',
          isStreaming: true,
          streamStatus: 'streaming',
          streamingAssistantContent: '',
        }));

        if (activeConversationId) {
          tabSync.broadcastHITLStateChanged(activeConversationId, false, 'decision');
        }
      } catch (error) {
        console.error('Failed to respond to decision:', error);
        setState({ agentState: 'idle', isStreaming: false, streamStatus: 'idle' });
      }
    },

    respondToEnvVar: async (requestId: string, values: Record<string, string>): Promise<void> => {
      const { activeConversationId } = get();
      if (!activeConversationId) return;

      try {
        await ensureConnectedAndSubscribe(activeConversationId, deps);

        await agentService.respondToEnvVar(requestId, values);
        clearAllDeltaBuffers();
        setState((state: any) => ({
          timeline: updateHITLEventInTimeline(state.timeline, requestId, 'env_var_requested', {
            answered: true,
            values,
          }),
          pendingEnvVarRequest: null,
          agentState: 'thinking',
          isStreaming: true,
          streamStatus: 'streaming',
          streamingAssistantContent: '',
        }));

        if (activeConversationId) {
          tabSync.broadcastHITLStateChanged(activeConversationId, false, 'env_var');
        }
      } catch (error) {
        console.error('Failed to respond to env var request:', error);
        setState({ agentState: 'idle', isStreaming: false, streamStatus: 'idle' });
      }
    },

    respondToPermission: async (requestId: string, granted: boolean): Promise<void> => {
      const { activeConversationId } = get();
      if (!activeConversationId) return;

      try {
        await ensureConnectedAndSubscribe(activeConversationId, deps);

        await agentService.respondToPermission(requestId, granted);
        clearAllDeltaBuffers();
        setState((state: any) => ({
          timeline: updateHITLEventInTimeline(state.timeline, requestId, 'permission_asked', {
            answered: true,
            granted,
          }),
          pendingPermission: null,
          agentState: granted ? 'thinking' : 'idle',
          isStreaming: granted,
          streamStatus: granted ? 'streaming' : 'idle',
          streamingAssistantContent: '',
        }));

        if (activeConversationId) {
          tabSync.broadcastHITLStateChanged(activeConversationId, false, 'permission');
        }
      } catch (error) {
        console.error('Failed to respond to permission request:', error);
        setState({ agentState: 'idle', isStreaming: false, streamStatus: 'idle' });
      }
    },
  };
}
