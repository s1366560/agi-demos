/**
 * Stream event handler factory for SSE events in agent conversations.
 *
 * Extracted from agentV3.ts to reduce file size and improve maintainability.
 * This module creates the AgentStreamHandler used by sendMessage.
 */

import { appendSSEEventToTimeline } from '../../utils/sseEventAdapter';
import { tabSync } from '../../utils/tabSync';
import { useBackgroundStore } from '../backgroundStore';
import { useCanvasStore } from '../canvasStore';
import { useContextStore } from '../contextStore';
import { useLayoutModeStore } from '../layoutMode';

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
  ToolCall,
  ActDeltaEventData,
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
  actDeltaBuffer: ActDeltaEventData | null;
  actDeltaFlushTimer: ReturnType<typeof setTimeout> | null;
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
            const { updateConversationState, getConversationState } = get();

            const convState = getConversationState(handlerConversationId);
            const newThought = convState.streamingThought + bufferedContent;
            updateConversationState(handlerConversationId, {
              streamingThought: newThought,
              isThinkingStreaming: true,
              agentState: 'thinking',
            });
          }
        }, thoughtBatchIntervalMs);
      }
    },

    onThought: (event) => {
      const newThought = event.data.thought;
      const { updateConversationState, getConversationState } = get();

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
    },

    onWorkPlan: (_event) => {
      // Legacy work_plan events - no-op
    },

    onPlanExecutionStart: (_event) => {},

    onPlanExecutionComplete: (_event) => {},

    // Plan Mode change handler
    onPlanModeChanged: (event) => {
      const data = event.data as { mode: string; conversation_id: string };
      const { updateConversationState } = get();
      const isPlanMode = data.mode === 'plan';
      updateConversationState(handlerConversationId, { isPlanMode });
      if (handlerConversationId === get().activeConversationId) {
        set({ isPlanMode });
      }
    },

    // Legacy plan handlers - no-op (kept for backward SSE compatibility)
    onPlanSuggested: (_event) => {},
    onPlanExplorationStarted: (_event) => {},
    onPlanExplorationCompleted: (_event) => {},
    onPlanDraftCreated: (_event) => {},
    onPlanApproved: (_event) => {},
    onPlanCancelled: (_event) => {},
    onPlanRejected: (_event) => {},
    onWorkPlanCreated: (_event) => {},
    onWorkPlanStepStarted: (_event) => {},
    onWorkPlanStepCompleted: (_event) => {},
    onWorkPlanStepFailed: (_event) => {},
    onWorkPlanCompleted: (_event) => {},
    onWorkPlanFailed: (_event) => {},

    // Task list handlers
    onTaskListUpdated: (event) => {
      const data = event.data as { conversation_id: string; tasks: unknown[] };
      console.log('[TaskSync] task_list_updated received:', {
        conversationId: handlerConversationId,
        taskCount: data.tasks?.length ?? 0,
      });
      const { updateConversationState } = get();
      updateConversationState(handlerConversationId, {
        tasks: data.tasks as import('../../types/agent').AgentTask[],
      });
    },

    onTaskUpdated: (event) => {
      const data = event.data as {
        conversation_id: string;
        task_id: string;
        status: string;
        content?: string;
      };
      console.log('[TaskSync] task_updated received:', {
        taskId: data.task_id,
        status: data.status,
      });
      const { getConversationState, updateConversationState } = get();
      const state = getConversationState(handlerConversationId);
      const tasks = (state?.tasks ?? []).map((t: import('../../types/agent').AgentTask) =>
        t.id === data.task_id
          ? { ...t, status: data.status as import('../../types/agent').TaskStatus, ...(data.content ? { content: data.content } : {}) }
          : t
      );
      updateConversationState(handlerConversationId, { tasks });
    },

    // Task timeline handlers (add events to timeline for plan execution tracking)
    onTaskStart: (event) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, { timeline: updatedTimeline });
    },

    onTaskComplete: (event) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, { timeline: updatedTimeline });
    },

    onReflectionComplete: (event) => {
      const { updateConversationState, getConversationState } = get();

      const reflectionEvent: AgentEvent<ReflectionCompleteEvent> = event;
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, reflectionEvent);

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });
    },

    onActDelta: (event: AgentEvent<ActDeltaEventData>) => {
      const buffer = getDeltaBuffer(handlerConversationId);

      // Buffer the latest act delta (only keep the most recent accumulated_arguments)
      buffer.actDeltaBuffer = event.data;

      if (!buffer.actDeltaFlushTimer) {
        buffer.actDeltaFlushTimer = setTimeout(() => {
          const bufferedData = buffer.actDeltaBuffer;
          buffer.actDeltaBuffer = null;
          buffer.actDeltaFlushTimer = null;

          if (bufferedData) {
            const { updateConversationState, getConversationState } = get();
            const convState = getConversationState(handlerConversationId);
            const toolName = bufferedData.tool_name;

            const newMap = new Map(convState.activeToolCalls);
            const existing = newMap.get(toolName);

            if (existing) {
              newMap.set(toolName, {
                ...existing,
                partialArguments: bufferedData.accumulated_arguments,
              });
            } else {
              newMap.set(toolName, {
                name: toolName,
                arguments: {},
                status: 'preparing',
                startTime: Date.now(),
                partialArguments: bufferedData.accumulated_arguments,
              });
            }

            updateConversationState(handlerConversationId, {
              activeToolCalls: newMap,
              agentState: 'preparing',
            });
          }
        }, tokenBatchIntervalMs);
      }
    },

    onAct: (event) => {
      const { updateConversationState, getConversationState } = get();

      // Flush any pending act delta buffer since the full act event supersedes it
      const buffer = getDeltaBuffer(handlerConversationId);
      if (buffer.actDeltaFlushTimer) {
        clearTimeout(buffer.actDeltaFlushTimer);
        buffer.actDeltaFlushTimer = null;
        buffer.actDeltaBuffer = null;
      }

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

      additionalHandlers?.onAct?.(event);
    },

    onObserve: (event) => {
      const { updateConversationState, getConversationState } = get();

      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);

      const stack = [...convState.pendingToolsStack];
      stack.pop();

      updateConversationState(handlerConversationId, {
        pendingToolsStack: stack,
        agentState: 'observing',
        timeline: updatedTimeline,
      });

      additionalHandlers?.onObserve?.(event);
    },

    onTextStart: () => {
      const { updateConversationState } = get();

      updateConversationState(handlerConversationId, {
        streamStatus: 'streaming',
        streamingAssistantContent: '',
      });
    },

    onTextDelta: (event) => {
      const delta = event.data.delta;
      if (!delta) return;

      const buffer = getDeltaBuffer(handlerConversationId);
      buffer.textDeltaBuffer += delta;

      if (!buffer.textDeltaFlushTimer) {
        buffer.textDeltaFlushTimer = setTimeout(() => {
          const bufferedContent = buffer.textDeltaBuffer;
          buffer.textDeltaBuffer = '';
          buffer.textDeltaFlushTimer = null;

          if (bufferedContent) {
            const { updateConversationState, getConversationState } = get();

            const convState = getConversationState(handlerConversationId);
            const newContent = convState.streamingAssistantContent + bufferedContent;
            updateConversationState(handlerConversationId, {
              streamingAssistantContent: newContent,
              streamStatus: 'streaming',
            });
          }
        }, tokenBatchIntervalMs);
      }
    },

    onTextEnd: (event) => {
      const { updateConversationState, getConversationState } = get();

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
    },

    onClarificationAsked: (event) => {
      const { updateConversationState, getConversationState } = get();

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
    },

    onDecisionAsked: (event) => {
      const { updateConversationState, getConversationState } = get();

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
    },

    onDoomLoopDetected: (event) => {
      const { updateConversationState } = get();

      updateConversationState(handlerConversationId, {
        doomLoopDetected: event.data,
      });
    },

    onEnvVarRequested: (event) => {
      const { updateConversationState, getConversationState } = get();

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
    },

    onPermissionAsked: (event) => {
      const { updateConversationState, getConversationState } = get();

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
    },

    onPermissionReplied: (event) => {
      const { updateConversationState, getConversationState } = get();

      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        pendingPermission: null,
        agentState: event.data.granted ? 'thinking' : 'idle',
      });
    },

    onDoomLoopIntervened: (event) => {
      const { updateConversationState, getConversationState } = get();

      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        doomLoopDetected: null,
      });
    },

    onCostUpdate: (event) => {
      const { updateConversationState } = get();

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

      // Forward to context store
      useContextStore.getState().handleCostUpdate(costData as unknown as Record<string, unknown>);
    },

    onContextCompressed: (event) => {
      useContextStore.getState().handleContextCompressed(event.data as unknown as Record<string, unknown>);
    },

    onContextStatus: (event) => {
      useContextStore.getState().handleContextStatus(event.data as unknown as Record<string, unknown>);
    },

    onArtifactCreated: (event) => {
      const { updateConversationState, getConversationState } = get();

      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });
    },

    onArtifactReady: (event) => {
      const { updateConversationState, getConversationState } = get();
      const data = event.data as ArtifactReadyEventData;

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
    },

    onArtifactError: (event) => {
      const { updateConversationState, getConversationState } = get();
      const data = event.data as ArtifactErrorEventData;

      if (import.meta.env.DEV) {
        console.warn('[AgentV3] Artifact error event:', data.artifact_id, data.error);
      }
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
    },

    onArtifactOpen: (event) => {
      const data = event.data as any;
      if (!data.artifact_id || !data.content) return;

      // Open the artifact in canvas with artifact link
      useCanvasStore.getState().openTab({
        id: data.artifact_id,
        title: data.title || 'Untitled',
        type: data.content_type || 'code',
        content: data.content,
        language: data.language,
        artifactId: data.artifact_id,
        artifactUrl: data.url,
      });

      // Auto-switch to canvas layout if not already
      const currentMode = useLayoutModeStore.getState().mode;
      if (currentMode !== 'canvas') {
        useLayoutModeStore.getState().setMode('canvas');
      }
    },

    onArtifactUpdate: (event) => {
      const data = event.data as any;
      if (!data.artifact_id || data.content === undefined) return;

      const store = useCanvasStore.getState();
      const tab = store.tabs.find((t) => t.id === data.artifact_id);
      if (tab) {
        const newContent = data.append ? tab.content + data.content : data.content;
        store.updateContent(data.artifact_id, newContent);
      }
    },

    onArtifactClose: (event) => {
      const data = event.data as any;
      if (!data.artifact_id) return;

      useCanvasStore.getState().closeTab(data.artifact_id);

      // If no more tabs, switch back to chat mode
      const remaining = useCanvasStore.getState().tabs;
      if (remaining.length === 0) {
        useLayoutModeStore.getState().setMode('chat');
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

      setState((state: any) => {
        const updatedList = state.conversations.map((c: any) =>
          c.id === data.conversation_id ? { ...c, title: data.title } : c
        );
        return { conversations: updatedList };
      });
    },

    onSuggestions: (event) => {
      const { updateConversationState } = get();

      const suggestions = (event.data as any)?.suggestions ?? [];

      updateConversationState(handlerConversationId, {
        suggestions,
      });
    },

    // SubAgent handlers (L3 layer)
    onSubAgentRouted: (event) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        agentState: 'acting',
      });
    },

    onSubAgentStarted: (event) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        agentState: 'acting',
      });
    },

    onSubAgentCompleted: (event) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });
      // Update background store if this was a background execution
      const bgStore = useBackgroundStore.getState();
      const execId = event.data.subagent_id || '';
      if (bgStore.executions.has(execId)) {
        bgStore.complete(
          execId,
          event.data.summary || '',
          event.data.tokens_used,
          event.data.execution_time_ms,
        );
      }
    },

    onSubAgentFailed: (event) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });
      // Update background store if this was a background execution
      const bgStore = useBackgroundStore.getState();
      const execId = event.data.subagent_id || '';
      if (bgStore.executions.has(execId)) {
        bgStore.fail(execId, event.data.error || 'Unknown error');
      }
    },

    onParallelStarted: (event) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        agentState: 'acting',
      });
    },

    onParallelCompleted: (event) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });
    },

    onChainStarted: (event) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        agentState: 'acting',
      });
    },

    onChainStepStarted: (event) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });
    },

    onChainStepCompleted: (event) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });
    },

    onChainCompleted: (event) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });
    },

    onBackgroundLaunched: (event) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });
      // Track in background store for the panel
      const bgStore = useBackgroundStore.getState();
      bgStore.launch(
        event.data.execution_id || '',
        event.data.subagent_name || '',
        event.data.task || '',
      );
    },

    onComplete: (event) => {
      const { updateConversationState, getConversationState } = get();

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

      // Update top-level messages (not part of ConversationState)
      const { activeConversationId } = get();
      if (handlerConversationId === activeConversationId) {
        setState({ messages: newMessages });
      }

      tabSync.broadcastConversationCompleted(handlerConversationId);
      tabSync.broadcastStreamingStateChanged(handlerConversationId, false, 'idle');

      // Fallback: fetch tasks from REST API after stream completes.
      // SSE task events may be lost due to timing/Redis issues, so always
      // reconcile with the DB as the source of truth.
      (async () => {
        try {
          const { httpClient } = await import('../../services/client/httpClient');
          const res = (await httpClient.get(
            `/agent/plan/tasks/${handlerConversationId}`,
          )) as any;
          if (res && Array.isArray(res.tasks) && res.tasks.length > 0) {
            const { updateConversationState } = get();
            updateConversationState(handlerConversationId, {
              tasks: res.tasks as import('../../types/agent').AgentTask[],
            });
            console.log(
              '[TaskSync] onComplete fallback: fetched',
              res.tasks.length,
              'tasks from API',
            );
          }
        } catch {
          // Task fetch is best-effort; conversation may have no tasks
        }
      })();
    },

    onError: (event) => {
      const { updateConversationState, getConversationState } = get();

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
    },

    onClose: () => {
      const { updateConversationState } = get();

      clearDeltaBuffers(handlerConversationId);

      updateConversationState(handlerConversationId, {
        isStreaming: false,
        streamStatus: 'idle',
      });
    },
  };
}
