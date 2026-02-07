/**
 * HITL (Human-In-The-Loop) response actions extracted from agentV3.ts.
 *
 * Contains respondToClarification, respondToDecision, respondToEnvVar,
 * and respondToPermission actions that share an identical simple handler pattern.
 */

import { agentService } from '../../services/agentService';
import { appendSSEEventToTimeline } from '../../utils/sseEventAdapter';
import { tabSync } from '../../utils/tabSync';

import type {
  AgentStreamHandler,
  AgentEvent,
  ThoughtEventData,
  CompleteEventData,
  ClarificationAskedEventData,
  DecisionAskedEventData,
  EnvVarRequestedEventData,
  PermissionAskedEventData,
  CostUpdateEventData,
  TimelineEvent,
} from '../../types/agent';
import type { CostTrackingState } from '../../types/conversationState';

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

/**
 * Create the simple handler used by all HITL response actions.
 * All four HITL response functions share this identical handler pattern.
 */
function createSimpleHITLHandler(
  deps: HITLActionDeps,
  errorLogPrefix: string
): AgentStreamHandler {
  const { set, timelineToMessages } = deps;
  const setState = set as any;

  return {
    onTextDelta: (event) => {
      const delta = event.data.delta;
      if (delta) {
        setState((state: any) => ({
          streamingAssistantContent: state.streamingAssistantContent + delta,
          streamStatus: 'streaming',
        }));
      }
    },
    onTextEnd: (event) => {
      const fullText = event.data.full_text;
      if (fullText) {
        setState({ streamingAssistantContent: fullText });
      }
    },
    onComplete: (event) => {
      setState((state: any) => {
        const completeEvent: AgentEvent<CompleteEventData> =
          event as AgentEvent<CompleteEventData>;
        const updatedTimeline = appendSSEEventToTimeline(state.timeline, completeEvent);
        return {
          timeline: updatedTimeline,
          messages: timelineToMessages(updatedTimeline),
          isStreaming: false,
          streamStatus: 'idle',
          agentState: 'idle',
        };
      });
    },
    onError: (event) => {
      console.error(`${errorLogPrefix} HITL response error:`, event.data);
      setState({
        error: event.data.message || 'Agent error',
        isStreaming: false,
        streamStatus: 'error',
        agentState: 'idle',
      });
    },
    onThought: (event) => {
      setState((state: any) => {
        const thoughtEvent: AgentEvent<ThoughtEventData> =
          event as AgentEvent<ThoughtEventData>;
        const updatedTimeline = appendSSEEventToTimeline(state.timeline, thoughtEvent);
        return {
          currentThought: event.data.thought || '',
          timeline: updatedTimeline,
          agentState: 'thinking',
        };
      });
    },
    onAct: (event) => {
      setState((state: any) => {
        const updatedTimeline = appendSSEEventToTimeline(state.timeline, event);
        return {
          timeline: updatedTimeline,
          agentState: 'acting',
        };
      });
    },
    onObserve: (event) => {
      setState((state: any) => {
        const updatedTimeline = appendSSEEventToTimeline(state.timeline, event);
        return {
          timeline: updatedTimeline,
          agentState: 'observing',
        };
      });
    },
    // HITL event handlers for nested requests (agent paused again)
    onClarificationAsked: (event) => {
      const clarificationEvent: AgentEvent<ClarificationAskedEventData> = {
        type: 'clarification_asked',
        data: event.data,
      };
      setState((state: any) => {
        const updatedTimeline = appendSSEEventToTimeline(state.timeline, clarificationEvent);
        return {
          timeline: updatedTimeline,
          pendingClarification: event.data,
          agentState: 'awaiting_input',
          isStreaming: false,
          streamStatus: 'idle',
        };
      });
    },
    onDecisionAsked: (event) => {
      const decisionEvent: AgentEvent<DecisionAskedEventData> = {
        type: 'decision_asked',
        data: event.data,
      };
      setState((state: any) => {
        const updatedTimeline = appendSSEEventToTimeline(state.timeline, decisionEvent);
        return {
          timeline: updatedTimeline,
          pendingDecision: event.data,
          agentState: 'awaiting_input',
          isStreaming: false,
          streamStatus: 'idle',
        };
      });
    },
    onEnvVarRequested: (event) => {
      const envVarEvent: AgentEvent<EnvVarRequestedEventData> = {
        type: 'env_var_requested',
        data: event.data,
      };
      setState((state: any) => {
        const updatedTimeline = appendSSEEventToTimeline(state.timeline, envVarEvent);
        return {
          timeline: updatedTimeline,
          pendingEnvVarRequest: event.data,
          agentState: 'awaiting_input',
          isStreaming: false,
          streamStatus: 'idle',
        };
      });
    },
    onPermissionAsked: (event) => {
      const permissionEvent: AgentEvent<PermissionAskedEventData> = {
        type: 'permission_asked',
        data: event.data,
      };
      setState((state: any) => {
        const updatedTimeline = appendSSEEventToTimeline(state.timeline, permissionEvent);
        return {
          timeline: updatedTimeline,
          pendingPermission: event.data,
          agentState: 'awaiting_input',
          isStreaming: false,
          streamStatus: 'idle',
        };
      });
    },
    onCostUpdate: (event) => {
      const costData = event.data as CostUpdateEventData;
      const costTracking: CostTrackingState = {
        inputTokens: costData.input_tokens,
        outputTokens: costData.output_tokens,
        totalTokens: costData.total_tokens,
        costUsd: costData.cost_usd,
        model: costData.model,
        lastUpdated: new Date().toISOString(),
      };
      setState({ costTracking });
    },
  };
}

/**
 * Ensure WebSocket is connected and subscribe to conversation
 */
async function ensureConnectedAndSubscribe(
  activeConversationId: string | null,
  handler: AgentStreamHandler
): Promise<void> {
  if (!agentService.isConnected()) {
    console.log('[agentV3] Connecting WebSocket before HITL response...');
    await agentService.connect();
  }

  if (activeConversationId) {
    agentService.subscribe(activeConversationId, handler);
    console.log('[agentV3] Subscribed to conversation:', activeConversationId);
  }
}

/**
 * Create HITL response actions for the store.
 */
export function createHITLActions(deps: HITLActionDeps) {
  const { get, set, clearAllDeltaBuffers, updateHITLEventInTimeline } = deps;
  const setState = set as any;

  return {
    respondToClarification: async (requestId: string, answer: string): Promise<void> => {
      console.log('Responding to clarification', requestId, answer);
      const { activeConversationId } = get();

      try {
        const simpleHandler = createSimpleHITLHandler(deps, '[agentV3]');
        await ensureConnectedAndSubscribe(activeConversationId, simpleHandler);

        await agentService.respondToClarification(requestId, answer);
        clearAllDeltaBuffers();
        setState((state: any) => ({
          timeline: updateHITLEventInTimeline(
            state.timeline,
            requestId,
            'clarification_asked',
            { answered: true, answer }
          ),
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
      console.log('Responding to decision', requestId, decision);
      const { activeConversationId } = get();

      try {
        const simpleHandler = createSimpleHITLHandler(deps, '[agentV3]');
        await ensureConnectedAndSubscribe(activeConversationId, simpleHandler);

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
      console.log('Responding to env var request', requestId, values);
      const { activeConversationId } = get();

      try {
        const simpleHandler = createSimpleHITLHandler(deps, '[agentV3]');
        await ensureConnectedAndSubscribe(activeConversationId, simpleHandler);

        await agentService.respondToEnvVar(requestId, values);
        clearAllDeltaBuffers();
        setState((state: any) => ({
          timeline: updateHITLEventInTimeline(
            state.timeline,
            requestId,
            'env_var_requested',
            { answered: true, values }
          ),
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
      console.log('Responding to permission request', requestId, granted);
      const { activeConversationId } = get();

      try {
        const simpleHandler = createSimpleHITLHandler(deps, '[agentV3]');
        await ensureConnectedAndSubscribe(activeConversationId, simpleHandler);

        await agentService.respondToPermission(requestId, granted);
        clearAllDeltaBuffers();
        setState((state: any) => ({
          timeline: updateHITLEventInTimeline(
            state.timeline,
            requestId,
            'permission_asked',
            { answered: true, granted }
          ),
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
