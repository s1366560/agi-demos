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
import { useUnifiedHITLStore } from '../hitlStore.unified';
import { useLayoutModeStore } from '../layoutMode';

import type {
  AgentStreamHandler,
  AgentEvent,
  MessageEventData,
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
  MemoryRecalledEventData,
  MemoryCapturedEventData,
  ExecutionPathDecidedEventData,
  SelectionTraceEventData,
  PolicyFilteredEventData,
  ExecutionNarrativeEntry,
  ToolsetChangedEventData,
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
  // Keep the most recent execution diagnostics while bounding per-conversation memory usage.
  const EXECUTION_NARRATIVE_LIMIT = 40;
  const buildNarrativeId = (stage: ExecutionNarrativeEntry['stage'], traceId?: string): string =>
    `${stage}-${traceId || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`}`;
  const appendExecutionNarrativeEntry = (
    entries: ConversationState['executionNarrative'],
    entry: ExecutionNarrativeEntry
  ): ConversationState['executionNarrative'] => {
    const nextEntries = [...entries, entry];
    return nextEntries.length <= EXECUTION_NARRATIVE_LIMIT
      ? nextEntries
      : nextEntries.slice(nextEntries.length - EXECUTION_NARRATIVE_LIMIT);
  };
  const appendExecutionInsightMarker = (
    timeline: ConversationState['timeline'],
    sourceEvent: AgentEvent<unknown>,
    thought: string
  ): ConversationState['timeline'] => {
    const payload = sourceEvent.data as Record<string, unknown>;
    const eventTimeUs =
      typeof payload?.event_time_us === 'number' ? payload.event_time_us : Date.now() * 1000;
    const eventCounter = typeof payload?.event_counter === 'number' ? payload.event_counter : 0;

    return appendSSEEventToTimeline(timeline, {
      type: 'thought',
      data: {
        thought,
        thought_level: 'task',
        event_time_us: eventTimeUs,
        event_counter: eventCounter,
      },
    } as AgentEvent<ThoughtEventData>);
  };

  return {
    onMessage: (event) => {
      const messageData = event.data as MessageEventData & {
        metadata?: { source?: string };
      };
      const source = messageData?.metadata?.source;
      if (source !== 'channel_inbound') {
        return;
      }

      const { updateConversationState, getConversationState, activeConversationId } = get();
      const convState = getConversationState(handlerConversationId);

      if (
        messageData.id &&
        convState.timeline.some((timelineEvent) => timelineEvent.id === messageData.id)
      ) {
        return;
      }

      const updatedTimeline = appendSSEEventToTimeline(
        convState.timeline,
        event
      );
      updateConversationState(handlerConversationId, { timeline: updatedTimeline });

      if (handlerConversationId === activeConversationId) {
        const newMessages = timelineToMessages(updatedTimeline);
        setState({ messages: newMessages });
      }
    },

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

      const thoughtEvent: AgentEvent<ThoughtEventData> = event;
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
          ? {
              ...t,
              status: data.status as import('../../types/agent').TaskStatus,
              ...(data.content ? { content: data.content } : {}),
            }
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

    onExecutionPathDecided: (event) => {
      const { updateConversationState, getConversationState } = get();
      const decision = event.data;
      const convState = getConversationState(handlerConversationId);
      const insight = `[Routing] ${decision.path} (${decision.confidence.toFixed(2)}) - ${decision.reason}`;
      const updatedTimeline = appendExecutionInsightMarker(convState.timeline, event, insight);
      const narrativeEntry: ExecutionNarrativeEntry = {
        id: buildNarrativeId('routing', decision.trace_id),
        stage: 'routing',
        summary: insight,
        timestamp: Date.now(),
        trace_id: decision.trace_id,
        route_id: decision.route_id,
        domain_lane:
          decision.metadata && typeof decision.metadata['domain_lane'] === 'string'
            ? (decision.metadata['domain_lane'])
            : null,
        metadata: {
          target: decision.target,
          confidence: decision.confidence,
        },
      };

      updateConversationState(handlerConversationId, {
        executionPathDecision: decision,
        timeline: updatedTimeline,
        executionNarrative: appendExecutionNarrativeEntry(
          convState.executionNarrative,
          narrativeEntry
        ),
      });
    },

    onSelectionTrace: (event) => {
      const { updateConversationState, getConversationState } = get();
      const selection = event.data;
      const convState = getConversationState(handlerConversationId);
      const budgetText =
        typeof selection.tool_budget === 'number' ? `, budget=${selection.tool_budget}` : '';
      const insight = `[Selection] kept ${selection.final_count}/${selection.initial_count}, removed ${selection.removed_total}${budgetText}`;
      const updatedTimeline = appendExecutionInsightMarker(convState.timeline, event, insight);
      const narrativeEntry: ExecutionNarrativeEntry = {
        id: buildNarrativeId('selection', selection.trace_id),
        stage: 'selection',
        summary: insight,
        timestamp: Date.now(),
        trace_id: selection.trace_id,
        route_id: selection.route_id,
        domain_lane: selection.domain_lane ?? null,
        metadata: {
          stage_count: selection.stages.length,
          budget_exceeded_stages: selection.budget_exceeded_stages ?? [],
        },
      };

      updateConversationState(handlerConversationId, {
        selectionTrace: selection,
        timeline: updatedTimeline,
        executionNarrative: appendExecutionNarrativeEntry(
          convState.executionNarrative,
          narrativeEntry
        ),
      });
    },

    onPolicyFiltered: (event) => {
      const { updateConversationState, getConversationState } = get();
      const filtered = event.data;
      const convState = getConversationState(handlerConversationId);
      const insight = `[Policy] filtered ${filtered.removed_total} tools across ${filtered.stage_count} stages`;
      const updatedTimeline = appendExecutionInsightMarker(convState.timeline, event, insight);
      const narrativeEntry: ExecutionNarrativeEntry = {
        id: buildNarrativeId('policy', filtered.trace_id),
        stage: 'policy',
        summary: insight,
        timestamp: Date.now(),
        trace_id: filtered.trace_id,
        route_id: filtered.route_id,
        domain_lane: filtered.domain_lane ?? null,
        metadata: {
          budget_exceeded_stages: filtered.budget_exceeded_stages ?? [],
          tool_budget: filtered.tool_budget,
        },
      };

      updateConversationState(handlerConversationId, {
        policyFiltered: filtered,
        timeline: updatedTimeline,
        executionNarrative: appendExecutionNarrativeEntry(
          convState.executionNarrative,
          narrativeEntry
        ),
      });
    },

    onToolsetChanged: (event) => {
      const { updateConversationState, getConversationState } = get();
      const changed = event.data;
      const convState = getConversationState(handlerConversationId);
      const actionText = changed.action || 'update';
      const pluginText = changed.plugin_name ? ` ${changed.plugin_name}` : '';
      const refreshStateText = changed.refresh_status ? ` · refresh=${changed.refresh_status}` : '';
      const refreshCountText =
        typeof changed.refreshed_tool_count === 'number'
          ? ` (${changed.refreshed_tool_count} tools)`
          : '';
      const insight = `[Toolset] ${actionText}${pluginText}${refreshStateText}${refreshCountText}`;
      const updatedTimeline = appendExecutionInsightMarker(convState.timeline, event, insight);
      const narrativeEntry: ExecutionNarrativeEntry = {
        id: buildNarrativeId('toolset', changed.trace_id),
        stage: 'toolset',
        summary: insight,
        timestamp: Date.now(),
        trace_id: changed.trace_id,
        metadata: {
          source: changed.source,
          action: changed.action,
          plugin_name: changed.plugin_name,
          refresh_status: changed.refresh_status,
          refreshed_tool_count: changed.refreshed_tool_count,
        },
      };

      updateConversationState(handlerConversationId, {
        latestToolsetChange: changed,
        timeline: updatedTimeline,
        executionNarrative: appendExecutionNarrativeEntry(
          convState.executionNarrative,
          narrativeEntry
        ),
      });
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

      // FIX: Update activeToolCalls to mark the completed tool
      // This ensures the tool is visible during fast execution
      const toolName = event.data.tool_name;
      const newMap = new Map(convState.activeToolCalls);

      if (toolName && newMap.has(toolName)) {
        const existingCall = newMap.get(toolName);
        if (existingCall) {
          newMap.set(toolName, {
            ...existingCall,
            status: 'success',
            result: event.data.observation,
          });
        }
      }

      updateConversationState(handlerConversationId, {
        pendingToolsStack: stack,
        activeToolCalls: newMap,
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

      useUnifiedHITLStore
        .getState()
        .handleSSEEvent(
          'clarification_asked',
          event.data as unknown as Record<string, unknown>,
          handlerConversationId
        );
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

      useUnifiedHITLStore
        .getState()
        .handleSSEEvent(
          'decision_asked',
          event.data as unknown as Record<string, unknown>,
          handlerConversationId
        );
    },

    onClarificationAnswered: (event) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const requestId = event.data.request_id;

      // Merge answer into the existing asked card in timeline
      const updatedTimeline = convState.timeline.map((te) =>
        te.type === 'clarification_asked' && (te as any).requestId === requestId
          ? { ...te, answered: true, answer: event.data.answer }
          : te
      );

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        pendingClarification: null,
        agentState: 'thinking',
      });

      useUnifiedHITLStore
        .getState()
        .handleSSEEvent(
          'clarification_answered',
          event.data as unknown as Record<string, unknown>,
          handlerConversationId
        );
    },

    onDecisionAnswered: (event) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const requestId = event.data.request_id;

      const updatedTimeline = convState.timeline.map((te) =>
        te.type === 'decision_asked' && (te as any).requestId === requestId
          ? { ...te, answered: true, decision: event.data.decision }
          : te
      );

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        pendingDecision: null,
        agentState: 'thinking',
      });

      useUnifiedHITLStore
        .getState()
        .handleSSEEvent(
          'decision_answered',
          event.data as unknown as Record<string, unknown>,
          handlerConversationId
        );
    },

    onEnvVarProvided: (event) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const requestId = event.data.request_id;

      const updatedTimeline = convState.timeline.map((te) =>
        te.type === 'env_var_requested' && (te as any).requestId === requestId
          ? { ...te, answered: true, providedVariables: event.data.saved_variables }
          : te
      );

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        pendingEnvVarRequest: null,
        agentState: 'thinking',
      });

      useUnifiedHITLStore
        .getState()
        .handleSSEEvent(
          'env_var_provided',
          event.data as unknown as Record<string, unknown>,
          handlerConversationId
        );
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

      useUnifiedHITLStore
        .getState()
        .handleSSEEvent(
          'env_var_requested',
          event.data as unknown as Record<string, unknown>,
          handlerConversationId
        );
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

      useUnifiedHITLStore
        .getState()
        .handleSSEEvent(
          'permission_asked',
          event.data as unknown as Record<string, unknown>,
          handlerConversationId
        );
    },

    onPermissionReplied: (event) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const requestId = event.data.request_id;

      const updatedTimeline = convState.timeline.map((te) =>
        te.type === 'permission_asked' && (te as any).requestId === requestId
          ? { ...te, answered: true, granted: event.data.granted }
          : te
      );

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        pendingPermission: null,
        agentState: event.data.granted ? 'thinking' : 'idle',
      });

      useUnifiedHITLStore
        .getState()
        .handleSSEEvent(
          'permission_replied',
          event.data as unknown as Record<string, unknown>,
          handlerConversationId
        );
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

      const costData = event.data;
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
      useContextStore
        .getState()
        .handleContextCompressed(event.data as unknown as Record<string, unknown>);
    },

    onContextStatus: (event) => {
      useContextStore
        .getState()
        .handleContextStatus(event.data as unknown as Record<string, unknown>);
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
      const data = event.data;

      const convState = getConversationState(handlerConversationId);

      // Update the existing artifact_created timeline entry with URL
      const updatedTimeline = convState.timeline.map((item) => {
        if (
          item.type === 'artifact_created' &&
          (item).artifactId === data.artifact_id
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
      const data = event.data;

      if (import.meta.env.DEV) {
        console.warn('[AgentV3] Artifact error event:', data.artifact_id, data.error);
      }
      const convState = getConversationState(handlerConversationId);

      // Update the existing artifact_created timeline entry with error
      const updatedTimeline = convState.timeline.map((item) => {
        if (
          item.type === 'artifact_created' &&
          (item).artifactId === data.artifact_id
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
          event.data.execution_time_ms
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
        event.data.task || ''
      );
    },

    // MCP App handlers
    onMCPAppResult: (event) => {
      const data = event.data as any;
      const appId = data.app_id || '';
      const htmlContent = data.resource_html || undefined;
      const uiMetadata =
        data.ui_metadata && typeof data.ui_metadata === 'object' ? data.ui_metadata : {};
      const resourceUri =
        data.resource_uri || uiMetadata.resourceUri || uiMetadata.resource_uri || undefined;
      const toolName = data.tool_name || '';
      const projectId = data.project_id || uiMetadata.project_id || '';
      const serverName = data.server_name || uiMetadata.server_name || '';

      // Cache HTML by URI for timeline "Open App" lookup
      if (resourceUri && htmlContent) {
        import('../mcpAppStore').then(({ useMCPAppStore }) => {
          useMCPAppStore.getState().cacheHtmlByUri(resourceUri, htmlContent);
        });
      }

      // SEP-1865: Merge structuredContent into tool result for the renderer
      const toolResult = data.structured_content
        ? {
            ...((typeof data.tool_result === 'object' && data.tool_result) || {}),
            structuredContent: data.structured_content,
          }
        : data.tool_result;

      const openMCPAppTab = (
        resolvedResourceUri?: string,
        options?: {
          title?: string;
          toolName?: string;
          serverName?: string;
          uiMetadata?: Record<string, unknown>;
        }
      ) => {
        const tabKey = resolvedResourceUri || appId || `app-${Date.now()}`;
        const tabId = `mcp-app-${tabKey}`;
        useCanvasStore.getState().openTab({
          id: tabId,
          title: options?.title || toolName || 'MCP App',
          type: 'mcp-app',
          content: '',
          mcpAppId: appId || undefined,
          mcpAppHtml: htmlContent,
          mcpAppToolResult: toolResult,
          mcpAppToolInput: (typeof data.tool_input === 'object' && data.tool_input) || undefined,
          mcpAppUiMetadata: options?.uiMetadata || uiMetadata,
          mcpResourceUri: resolvedResourceUri,
          mcpToolName: options?.toolName || toolName || undefined,
          mcpProjectId: projectId || undefined,
          mcpServerName: options?.serverName || serverName || undefined,
        });
        useLayoutModeStore.getState().setMode('canvas');
      };

      const shouldWaitForStoreLookup = !!appId && !resourceUri && !htmlContent;

      // Always invalidate cached resource so fresh HTML is used
      if (appId) {
        import('../mcpAppStore').then(({ useMCPAppStore }) => {
          const store = useMCPAppStore.getState();
          store.invalidateResource(appId);

          if (!resourceUri) {
            const app = store.apps[appId];
            const storeUri = app?.ui_metadata?.resourceUri;
            if (storeUri) {
              openMCPAppTab(storeUri, {
                title: (app?.ui_metadata?.title as string) || toolName || 'MCP App',
                toolName: app?.tool_name || toolName || undefined,
                serverName: app?.server_name || serverName || undefined,
                uiMetadata: (app?.ui_metadata as unknown as Record<string, unknown>) || uiMetadata,
              });
              return;
            }

            if (shouldWaitForStoreLookup) {
              openMCPAppTab(undefined, {
                title: (app?.ui_metadata?.title as string) || toolName || 'MCP App',
                toolName: app?.tool_name || toolName || undefined,
                serverName: app?.server_name || serverName || undefined,
                uiMetadata: (app?.ui_metadata as unknown as Record<string, unknown>) || uiMetadata,
              });
            }
          }
        });
      }

      if (!shouldWaitForStoreLookup) {
        openMCPAppTab(resourceUri, {
          title: uiMetadata.title || toolName || 'MCP App',
          uiMetadata,
        });
      }
    },

    onMCPAppRegistered: (event) => {
      const data = event.data as any;
      if (!data.app_id) return;
      // Dynamically import to avoid circular deps
      import('../mcpAppStore').then(({ useMCPAppStore }) => {
        const store = useMCPAppStore.getState();
        // Invalidate cached resource so re-registration picks up new HTML
        store.invalidateResource(data.app_id);
        store.addApp({
          id: data.app_id,
          project_id: '',
          tenant_id: '',
          server_id: null,
          server_name: data.server_name || '',
          tool_name: data.tool_name || '',
          ui_metadata: {
            resourceUri: data.resource_uri || '',
            title: data.title,
          },
          source: data.source || 'user_added',
          status: 'discovered',
          has_resource: false,
        });
      });
    },

    // Memory recall/capture handlers
    onMemoryRecalled: (event: AgentEvent<MemoryRecalledEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState) return;
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        recalledMemories: event.data?.memories ?? null,
        timeline: updatedTimeline,
      });
    },

    onMemoryCaptured: (event: AgentEvent<MemoryCapturedEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState) return;
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });
    },

    onComplete: (event) => {
      const { updateConversationState, getConversationState } = get();

      clearAllDeltaBuffers();

      const convState = getConversationState(handlerConversationId);

      // Remove transient streaming control events.
      // Keep text_end events intact so their IDs stay stable and avoid
      // text_end -> assistant_message remount flicker at stream completion.
      const hasTextEndMessages = convState.timeline.some(
        (e) => e.type === 'text_end' && !!(e as any).fullText?.trim()
      );
      const cleanedTimeline = convState.timeline.filter((e) => {
        if (e.type === 'text_start' || e.type === 'text_delta') {
          return false;
        }
        if (e.type === 'text_end') {
          return !!(e as any).fullText?.trim();
        }
        return true;
      });

      // Only add assistant_message from complete event when no text_end segment exists,
      // to avoid duplicating final output.
      const completeEvent: AgentEvent<CompleteEventData> = event;
      const hasContent = !!(completeEvent.data as any)?.content?.trim();
      const updatedTimeline =
        hasContent && !hasTextEndMessages
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
          const res = (await httpClient.get(`/agent/plan/tasks/${handlerConversationId}`)) as any;
          if (res && Array.isArray(res.tasks) && res.tasks.length > 0) {
            const { updateConversationState } = get();
            updateConversationState(handlerConversationId, {
              tasks: res.tasks as import('../../types/agent').AgentTask[],
            });
            console.log(
              '[TaskSync] onComplete fallback: fetched',
              res.tasks.length,
              'tasks from API'
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
