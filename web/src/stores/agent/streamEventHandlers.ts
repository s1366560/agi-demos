/**
 * Stream event handler factory for SSE events in agent conversations.
 *
 * Extracted from agentV3.ts to reduce file size and improve maintainability.
 * This module creates the AgentStreamHandler used by sendMessage.
 */

import { appendSSEEventToTimeline } from '../../utils/sseEventAdapter';
import { tabSync } from '../../utils/tabSync';

import type {
  AgentStreamHandler,
  AgentEvent,
  ThoughtEventData,
  WorkPlanEventData,
  StepStartEventData,
  CompleteEventData,
  ClarificationAskedEventData,
  DecisionAskedEventData,
  EnvVarRequestedEventData,
  PermissionAskedEventData,
  CostUpdateEventData,
  WorkPlan,
  ExecutionPlan,
  ToolCall,
  PlanExecutionStartEvent,
  PlanExecutionCompleteEvent,
  ReflectionCompleteEvent,
  ArtifactReadyEventData,
  ArtifactErrorEventData,
  ArtifactCreatedEvent,
} from '../../types/agent';
import type { ConversationState, CostTrackingState } from '../../types/conversationState';
import type { AdditionalAgentHandlers } from '../agentV3';

/**
 * Delta buffer management interface for token batching
 */
export interface DeltaBufferState {
  textDeltaBuffer: string;
  textDeltaFlushTimer: ReturnType<typeof setTimeout> | null;
  thoughtDeltaBuffer: string;
  thoughtDeltaFlushTimer: ReturnType<typeof setTimeout> | null;
}

/**
 * Dependencies injected from the store into the handler factory
 */
export interface StreamHandlerDeps {
  get: () => {
    activeConversationId: string | null;
    getConversationState: (conversationId: string) => ConversationState;
    updateConversationState: (conversationId: string, updates: Partial<ConversationState>) => void;
  };
  set: (
    updater:
      | Partial<Record<string, unknown>>
      | ((state: Record<string, unknown>) => Partial<Record<string, unknown>>)
  ) => void;
  getDeltaBuffer: (conversationId: string) => DeltaBufferState;
  clearDeltaBuffers: (conversationId: string) => void;
  clearAllDeltaBuffers: () => void;
  timelineToMessages: (timeline: any[]) => any[];
  tokenBatchIntervalMs: number;
  thoughtBatchIntervalMs: number;
}

/**
 * Create the SSE stream event handler for a conversation.
 *
 * @param handlerConversationId - The conversation ID this handler is bound to
 * @param additionalHandlers - Optional external integration handlers
 * @param deps - Store dependencies (get, set, buffer helpers)
 * @returns An AgentStreamHandler with all event callbacks wired up
 */
export function createStreamEventHandlers(
  handlerConversationId: string,
  additionalHandlers: AdditionalAgentHandlers | undefined,
  deps: StreamHandlerDeps
): AgentStreamHandler {
  const {
    get,
    set,
    getDeltaBuffer,
    clearDeltaBuffers,
    clearAllDeltaBuffers,
    timelineToMessages,
    tokenBatchIntervalMs,
    thoughtBatchIntervalMs,
  } = deps;

  // Type-safe wrapper for set to handle both object and updater forms
  const setState = set as any;

  return {
    onMessage: (_event) => {},

    onThoughtDelta: (event) => {
      const delta = event.data.delta;
      if (!delta) return;

      const buffer = getDeltaBuffer(handlerConversationId);
      buffer.thoughtDeltaBuffer += delta;

      if (!buffer.thoughtDeltaFlushTimer) {
        buffer.thoughtDeltaFlushTimer = setTimeout(() => {
          const bufferedContent = buffer.thoughtDeltaBuffer;
          buffer.thoughtDeltaBuffer = '';
          buffer.thoughtDeltaFlushTimer = null;

          if (bufferedContent) {
            const { activeConversationId, updateConversationState, getConversationState } = get();

            const convState = getConversationState(handlerConversationId);
            const newThought = convState.streamingThought + bufferedContent;
            updateConversationState(handlerConversationId, {
              streamingThought: newThought,
              isThinkingStreaming: true,
              agentState: 'thinking',
            });

            if (handlerConversationId === activeConversationId) {
              setState({
                streamingThought: newThought,
                isThinkingStreaming: true,
                agentState: 'thinking',
              });
            }
          }
        }, thoughtBatchIntervalMs);
      }
    },

    onThought: (event) => {
      const newThought = event.data.thought;
      const { activeConversationId, updateConversationState, getConversationState } = get();

      const thoughtEvent: AgentEvent<ThoughtEventData> = event as AgentEvent<ThoughtEventData>;
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, thoughtEvent);

      const stateUpdates: Partial<ConversationState> = {
        agentState: 'thinking',
        timeline: updatedTimeline,
        streamingThought: '',
        isThinkingStreaming: false,
      };

      if (newThought && newThought.trim() !== '') {
        stateUpdates.currentThought = convState.currentThought + '\n' + newThought;
      }

      updateConversationState(handlerConversationId, stateUpdates);

      if (handlerConversationId === activeConversationId) {
        setState((state: any) => {
          if (!newThought || newThought.trim() === '') {
            return {
              agentState: 'thinking',
              timeline: updatedTimeline,
              streamingThought: '',
              isThinkingStreaming: false,
            };
          }
          return {
            currentThought: state.currentThought + '\n' + newThought,
            streamingThought: '',
            isThinkingStreaming: false,
            agentState: 'thinking',
            timeline: updatedTimeline,
          };
        });
      }
    },

    onWorkPlan: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();

      const workPlanEvent: AgentEvent<WorkPlanEventData> = event as AgentEvent<WorkPlanEventData>;
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, workPlanEvent);

      const newWorkPlan: WorkPlan = {
        id: event.data.plan_id,
        conversation_id: event.data.conversation_id,
        status: event.data.status,
        steps: event.data.steps.map((s) => ({
          step_number: s.step_number,
          description: s.description,
          thought_prompt: '',
          required_tools: [],
          expected_output: s.expected_output,
          dependencies: [],
        })),
        current_step_index: event.data.current_step,
        created_at: new Date().toISOString(),
      };

      updateConversationState(handlerConversationId, {
        workPlan: newWorkPlan,
        timeline: updatedTimeline,
      });

      if (handlerConversationId === activeConversationId) {
        setState({
          workPlan: newWorkPlan,
          timeline: updatedTimeline,
        });
      }
    },

    onStepStart: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();

      const stepStartEvent: AgentEvent<StepStartEventData> =
        event as AgentEvent<StepStartEventData>;
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, stepStartEvent);

      const updates: Partial<ConversationState> = { timeline: updatedTimeline };
      if (convState.workPlan) {
        updates.workPlan = {
          ...convState.workPlan,
          current_step_index: event.data.current_step,
        };
        updates.agentState = 'acting';
      }
      updateConversationState(handlerConversationId, updates);

      if (handlerConversationId === activeConversationId) {
        setState((state: any) => {
          if (!state.workPlan) {
            return { timeline: updatedTimeline };
          }
          const newPlan = { ...state.workPlan };
          newPlan.current_step_index = event.data.current_step;
          return { workPlan: newPlan, agentState: 'acting', timeline: updatedTimeline };
        });
      }
    },

    onStepEnd: (_event) => {},

    onPlanExecutionStart: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();

      const executionPlanEvent: AgentEvent<PlanExecutionStartEvent> = event;
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, executionPlanEvent);

      const eventData = (event as any).data || {};
      const newExecutionPlan: ExecutionPlan = {
        id: eventData.plan_id || `plan-${Date.now()}`,
        conversation_id: handlerConversationId,
        user_query: eventData.user_query || '',
        steps: [],
        status: 'executing',
        reflection_enabled: true,
        max_reflection_cycles: 3,
        completed_steps: [],
        failed_steps: [],
        progress_percentage: 0,
        is_complete: false,
      };

      updateConversationState(handlerConversationId, {
        executionPlan: newExecutionPlan,
        timeline: updatedTimeline,
      });

      if (handlerConversationId === activeConversationId) {
        setState({
          executionPlan: newExecutionPlan,
          timeline: updatedTimeline,
        });
      }
    },

    onPlanExecutionComplete: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();

      const executionPlanEvent: AgentEvent<PlanExecutionCompleteEvent> = event;
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, executionPlanEvent);

      const eventData = (event as any).data || {};

      const updatedExecutionPlan = convState.executionPlan
        ? {
            ...convState.executionPlan,
            status: eventData.status || convState.executionPlan.status,
            completed_steps: Array(eventData.completed_steps || 0).fill(''),
            failed_steps: Array(eventData.failed_steps || 0).fill(''),
            progress_percentage:
              (eventData.completed_steps || 0) / (convState.executionPlan.steps.length || 1),
            is_complete: eventData.status === 'completed' || eventData.status === 'failed',
          }
        : null;

      updateConversationState(handlerConversationId, {
        executionPlan: updatedExecutionPlan,
        timeline: updatedTimeline,
      });

      if (handlerConversationId === activeConversationId) {
        setState({
          executionPlan: updatedExecutionPlan,
          timeline: updatedTimeline,
        });
      }
    },

    onReflectionComplete: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();

      const reflectionEvent: AgentEvent<ReflectionCompleteEvent> = event;
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, reflectionEvent);

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });

      if (handlerConversationId === activeConversationId) {
        setState({ timeline: updatedTimeline });
      }
    },

    onAct: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();

      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);

      const toolName = event.data.tool_name;
      const startTime = Date.now();

      const newCall: ToolCall & { status: 'running'; startTime: number } = {
        name: toolName,
        arguments: event.data.tool_input,
        status: 'running',
        startTime,
      };

      const newMap = new Map(convState.activeToolCalls);
      newMap.set(toolName, newCall);

      const newStack = [...convState.pendingToolsStack, toolName];

      updateConversationState(handlerConversationId, {
        activeToolCalls: newMap,
        pendingToolsStack: newStack,
        agentState: 'acting',
        timeline: updatedTimeline,
      });

      if (handlerConversationId === activeConversationId) {
        setState({
          activeToolCalls: newMap,
          pendingToolsStack: newStack,
          agentState: 'acting',
          timeline: updatedTimeline,
        });
      }

      additionalHandlers?.onAct?.(event);
    },

    onObserve: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();

      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);

      const stack = [...convState.pendingToolsStack];
      stack.pop();

      updateConversationState(handlerConversationId, {
        pendingToolsStack: stack,
        agentState: 'observing',
        timeline: updatedTimeline,
      });

      if (handlerConversationId === activeConversationId) {
        setState({
          pendingToolsStack: stack,
          agentState: 'observing',
          timeline: updatedTimeline,
        });
      }

      additionalHandlers?.onObserve?.(event);
    },

    onTextStart: () => {
      const { activeConversationId, updateConversationState } = get();

      updateConversationState(handlerConversationId, {
        streamStatus: 'streaming',
        streamingAssistantContent: '',
      });

      if (handlerConversationId === activeConversationId) {
        setState({ streamStatus: 'streaming', streamingAssistantContent: '' });
      }
    },

    onTextDelta: (event) => {
      const delta = event.data.delta;
      if (import.meta.env.DEV) {
        console.log(
          `[AgentV3] onTextDelta: delta="${delta?.substring(0, 30)}...", conv=${handlerConversationId}`
        );
      }
      if (!delta) return;

      const buffer = getDeltaBuffer(handlerConversationId);
      buffer.textDeltaBuffer += delta;

      if (!buffer.textDeltaFlushTimer) {
        buffer.textDeltaFlushTimer = setTimeout(() => {
          const bufferedContent = buffer.textDeltaBuffer;
          buffer.textDeltaBuffer = '';
          buffer.textDeltaFlushTimer = null;

          if (bufferedContent) {
            const { activeConversationId, updateConversationState, getConversationState } = get();

            const convState = getConversationState(handlerConversationId);
            const newContent = convState.streamingAssistantContent + bufferedContent;
            updateConversationState(handlerConversationId, {
              streamingAssistantContent: newContent,
              streamStatus: 'streaming',
            });

            if (handlerConversationId === activeConversationId) {
              setState({
                streamingAssistantContent: newContent,
                streamStatus: 'streaming',
              });
            }
          }
        }, tokenBatchIntervalMs);
      }
    },

    onTextEnd: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();

      const buffer = getDeltaBuffer(handlerConversationId);
      if (buffer.textDeltaFlushTimer) {
        clearTimeout(buffer.textDeltaFlushTimer);
        buffer.textDeltaFlushTimer = null;
      }
      const remainingBuffer = buffer.textDeltaBuffer;
      buffer.textDeltaBuffer = '';

      const convState = getConversationState(handlerConversationId);
      const fullText = event.data.full_text;
      const finalContent = fullText || convState.streamingAssistantContent + remainingBuffer;

      const textEndEvent: AgentEvent<any> = {
        type: 'text_end',
        data: { full_text: finalContent },
      };
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, textEndEvent);

      // Clear streamingAssistantContent so the streaming bubble disappears.
      // The text_end event in the timeline now renders the full text instead,
      // preventing duplicate content display.
      updateConversationState(handlerConversationId, {
        streamingAssistantContent: '',
        timeline: updatedTimeline,
      });

      if (handlerConversationId === activeConversationId) {
        setState({
          streamingAssistantContent: '',
          timeline: updatedTimeline,
        });
      }
    },

    onClarificationAsked: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();

      const clarificationEvent: AgentEvent<ClarificationAskedEventData> = {
        type: 'clarification_asked',
        data: event.data,
      };
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, clarificationEvent);

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        pendingClarification: event.data,
        agentState: 'awaiting_input',
      });

      if (handlerConversationId === activeConversationId) {
        setState({
          timeline: updatedTimeline,
          pendingClarification: event.data,
          agentState: 'awaiting_input',
        });
      }
    },

    onDecisionAsked: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();

      const decisionEvent: AgentEvent<DecisionAskedEventData> = {
        type: 'decision_asked',
        data: event.data,
      };
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, decisionEvent);

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        pendingDecision: event.data,
        agentState: 'awaiting_input',
      });

      if (handlerConversationId === activeConversationId) {
        setState({
          timeline: updatedTimeline,
          pendingDecision: event.data,
          agentState: 'awaiting_input',
        });
      }
    },

    onDoomLoopDetected: (event) => {
      const { activeConversationId, updateConversationState } = get();

      updateConversationState(handlerConversationId, {
        doomLoopDetected: event.data,
      });

      if (handlerConversationId === activeConversationId) {
        setState({ doomLoopDetected: event.data });
      }
    },

    onEnvVarRequested: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();

      const envVarEvent: AgentEvent<EnvVarRequestedEventData> = {
        type: 'env_var_requested',
        data: event.data,
      };
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, envVarEvent);

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        pendingEnvVarRequest: event.data,
        agentState: 'awaiting_input',
      });

      if (handlerConversationId === activeConversationId) {
        setState({
          timeline: updatedTimeline,
          pendingEnvVarRequest: event.data,
          agentState: 'awaiting_input',
        });
      }
    },

    onPermissionAsked: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();

      const permissionEvent: AgentEvent<PermissionAskedEventData> = {
        type: 'permission_asked',
        data: event.data,
      };
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, permissionEvent);

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        pendingPermission: event.data,
        agentState: 'awaiting_input',
      });

      if (handlerConversationId === activeConversationId) {
        setState({
          timeline: updatedTimeline,
          pendingPermission: event.data,
          agentState: 'awaiting_input',
        });
      }
    },

    onPermissionReplied: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();

      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        pendingPermission: null,
        agentState: event.data.granted ? 'thinking' : 'idle',
      });

      if (handlerConversationId === activeConversationId) {
        setState({
          timeline: updatedTimeline,
          pendingPermission: null,
          agentState: event.data.granted ? 'thinking' : 'idle',
        });
      }
    },

    onDoomLoopIntervened: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();

      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        doomLoopDetected: null,
      });

      if (handlerConversationId === activeConversationId) {
        setState({
          timeline: updatedTimeline,
          doomLoopDetected: null,
        });
      }
    },

    onCostUpdate: (event) => {
      const { activeConversationId, updateConversationState } = get();

      const costData = event.data as CostUpdateEventData;
      const costTracking: CostTrackingState = {
        inputTokens: costData.input_tokens,
        outputTokens: costData.output_tokens,
        totalTokens: costData.total_tokens,
        costUsd: costData.cost_usd,
        model: costData.model,
        lastUpdated: new Date().toISOString(),
      };

      updateConversationState(handlerConversationId, {
        costTracking,
      });

      if (handlerConversationId === activeConversationId) {
        setState({ costTracking });
      }

      // Forward to context store
      const { useContextStore } = require('../../stores/contextStore');
      useContextStore.getState().handleCostUpdate(costData as unknown as Record<string, unknown>);
    },

    onContextCompressed: (event) => {
      const { useContextStore } = require('../../stores/contextStore');
      useContextStore.getState().handleContextCompressed(event.data as unknown as Record<string, unknown>);
    },

    onContextStatus: (event) => {
      const { useContextStore } = require('../../stores/contextStore');
      useContextStore.getState().handleContextStatus(event.data as unknown as Record<string, unknown>);
    },

    onArtifactCreated: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();

      console.log('[AgentV3] Artifact created event:', event.data);
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });

      if (handlerConversationId === activeConversationId) {
        setState({ timeline: updatedTimeline });
      }
    },

    onArtifactReady: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();
      const data = event.data as ArtifactReadyEventData;

      console.log('[AgentV3] Artifact ready event:', data.artifact_id);
      const convState = getConversationState(handlerConversationId);

      // Update the existing artifact_created timeline entry with URL
      const updatedTimeline = convState.timeline.map((item) => {
        if (
          item.type === 'artifact_created' &&
          (item as ArtifactCreatedEvent).artifactId === data.artifact_id
        ) {
          return {
            ...item,
            url: data.url,
            previewUrl: data.preview_url,
          };
        }
        return item;
      });

      updateConversationState(handlerConversationId, { timeline: updatedTimeline });
      if (handlerConversationId === activeConversationId) {
        setState({ timeline: updatedTimeline });
      }
    },

    onArtifactError: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();
      const data = event.data as ArtifactErrorEventData;

      console.warn('[AgentV3] Artifact error event:', data.artifact_id, data.error);
      const convState = getConversationState(handlerConversationId);

      // Update the existing artifact_created timeline entry with error
      const updatedTimeline = convState.timeline.map((item) => {
        if (
          item.type === 'artifact_created' &&
          (item as ArtifactCreatedEvent).artifactId === data.artifact_id
        ) {
          return {
            ...item,
            error: data.error,
          };
        }
        return item;
      });

      updateConversationState(handlerConversationId, { timeline: updatedTimeline });
      if (handlerConversationId === activeConversationId) {
        setState({ timeline: updatedTimeline });
      }
    },

    onTitleGenerated: (event) => {
      const data = event.data as {
        conversation_id: string;
        title: string;
        generated_at: string;
        message_id?: string;
        generated_by?: string;
      };
      console.log('[AgentV3] Title generated event:', data);

      setState((state: any) => {
        const updatedList = state.conversations.map((c: any) =>
          c.id === data.conversation_id ? { ...c, title: data.title } : c
        );
        return { conversations: updatedList };
      });
    },

    onComplete: (event) => {
      console.log(
        `[AgentV3] onComplete: handler=${handlerConversationId}, content preview="${(event.data as any)?.content?.substring(0, 50)}..."`
      );
      const { activeConversationId, updateConversationState, getConversationState } = get();

      clearAllDeltaBuffers();

      const convState = getConversationState(handlerConversationId);

      // Remove transient streaming events (text_start, text_end, text_delta) from timeline.
      // These are never persisted to DB, so keeping them causes a mismatch between
      // in-memory state and what history API returns after refresh.
      const cleanedTimeline = convState.timeline.filter(
        (e) => e.type !== 'text_start' && e.type !== 'text_end' && e.type !== 'text_delta'
      );

      // Always add assistant_message from the complete event (if it has content).
      // This matches what the backend persists (complete -> assistant_message conversion).
      const completeEvent: AgentEvent<CompleteEventData> =
        event as AgentEvent<CompleteEventData>;
      const hasContent = !!(completeEvent.data as any)?.content?.trim();
      const updatedTimeline = hasContent
        ? appendSSEEventToTimeline(cleanedTimeline, completeEvent)
        : cleanedTimeline;

      const newMessages = timelineToMessages(updatedTimeline);

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        streamingAssistantContent: '',
        isStreaming: false,
        streamStatus: 'idle',
        agentState: 'idle',
        activeToolCalls: new Map(),
        pendingToolsStack: [],
      });

      if (handlerConversationId === activeConversationId) {
        setState({
          messages: newMessages,
          timeline: updatedTimeline,
          streamingAssistantContent: '',
          isStreaming: false,
          streamStatus: 'idle',
          agentState: 'idle',
          activeToolCalls: new Map(),
          pendingToolsStack: [],
        });
      }

      tabSync.broadcastConversationCompleted(handlerConversationId);
      tabSync.broadcastStreamingStateChanged(handlerConversationId, false, 'idle');
    },

    onError: (event) => {
      const { activeConversationId, updateConversationState, getConversationState } = get();

      clearDeltaBuffers(handlerConversationId);

      const convState = getConversationState(handlerConversationId);

      updateConversationState(handlerConversationId, {
        error: event.data.message,
        isStreaming: false,
        streamStatus: 'error',
        pendingToolsStack: [],
        streamingAssistantContent: convState.streamingAssistantContent || '',
        streamingThought: '',
        isThinkingStreaming: false,
      });

      if (handlerConversationId === activeConversationId) {
        setState({
          error: event.data.message,
          isStreaming: false,
          streamStatus: 'error',
          pendingToolsStack: [],
          streamingThought: '',
          isThinkingStreaming: false,
        });
      }
    },

    onClose: () => {
      const { activeConversationId, updateConversationState } = get();

      clearDeltaBuffers(handlerConversationId);

      updateConversationState(handlerConversationId, {
        isStreaming: false,
        streamStatus: 'idle',
      });

      if (handlerConversationId === activeConversationId) {
        setState({ isStreaming: false, streamStatus: 'idle' });
      }
    },
  };
}
