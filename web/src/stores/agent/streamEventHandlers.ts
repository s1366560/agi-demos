/**
 * Stream event handler factory for SSE events in agent conversations.
 *
 * Extracted from agentV3.ts to reduce file size and improve maintainability.
 * This module creates the AgentStreamHandler used by sendMessage.
 */

import { isCanvasPreviewable } from '../../utils/filePreview';
import { appendSSEEventToTimeline } from '../../utils/sseEventAdapter';
import { tabSync } from '../../utils/tabSync';
import { useBackgroundStore } from '../backgroundStore';
import { useCanvasStore } from '../canvasStore';
import { useContextStore } from '../contextStore';
import { useGraphStore } from '../graphStore';
import { useUnifiedHITLStore } from '../hitlStore.unified';
import { useLayoutModeStore } from '../layoutMode';

import { useExecutionStore } from './executionStore';

import { mergeA2UIMessageStream } from './a2uiMessages';

import type { DeltaBufferState } from './deltaBuffers';
import type { AdditionalAgentHandlers } from './types';
import type {
  ActDeltaEventData,
  AgentEvent,
  AgentStreamHandler,
  ClarificationAskedEventData,
  CanvasUpdatedEventData,
  A2UIActionAskedEventData,
  CompleteEventData,
  DecisionAskedEventData,
  EnvVarRequestedEventData,
  ExecutionNarrativeEntry,
  MemoryCapturedEventData,
  MemoryRecalledEventData,
  Message,
  ModelSwitchRequestedEventData,
  ModelOverrideRejectedEventData,
  MessageEventData,
  PermissionAskedEventData,
  ThoughtEventData,
  TimelineEvent,
  ToolCall,
  SubAgentQueuedEventData,
  SubAgentKilledEventData,
  SubAgentSteeredEventData,
  SubAgentDepthLimitedEventData,
  SubAgentSessionUpdateEventData,
  ToolPolicyDeniedEventData,
  AgentSpawnedEventData,
  AgentCompletedEventData,
  AgentStoppedEventData,
  GraphRunStartedEventData,
  GraphRunCompletedEventData,
  GraphRunFailedEventData,
  GraphRunCancelledEventData,
  GraphNodeStartedEventData,
  GraphNodeCompletedEventData,
  GraphNodeFailedEventData,
  GraphNodeSkippedEventData,
  GraphHandoffEventData,
} from '../../types/agent';
import type { ConversationState, CostTrackingState } from '../../types/conversationState';
import type { AgentNode } from '../../types/multiAgent';

// Re-export DeltaBufferState from canonical source for backward compatibility
export type { DeltaBufferState } from './deltaBuffers';

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
  timelineToMessages: (timeline: TimelineEvent[]) => Message[];
  tokenBatchIntervalMs: number;
  thoughtBatchIntervalMs: number;
  queueTimelineEvent: (
    event: AgentEvent<unknown>,
    immediateStateUpdates?: Partial<ConversationState>
  ) => void;
  flushTimelineBufferSync: () => void;
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
    queueTimelineEvent,
    flushTimelineBufferSync,
  } = deps;

  // Type-safe wrapper for set to handle both object and updater forms
  const setState = set as (updater: Parameters<typeof set>[0]) => void;
  // Shared timeline event type for requestId access
  interface TimelineEventWithRequestId {
    type: string;
    requestId?: string;
  }

  const THINKING_IDLE_RESET_MS = 400;
  let thoughtIdleResetTimer: ReturnType<typeof setTimeout> | null = null;
  const clearThoughtIdleResetTimer = () => {
    if (thoughtIdleResetTimer) {
      clearTimeout(thoughtIdleResetTimer);
      thoughtIdleResetTimer = null;
    }
  };
  const consumePendingThoughtDelta = (): string => {
    const buffer = getDeltaBuffer(handlerConversationId);
    if (buffer.thoughtDeltaFlushTimer) {
      clearTimeout(buffer.thoughtDeltaFlushTimer);
      buffer.thoughtDeltaFlushTimer = null;
    }
    const pending = buffer.thoughtDeltaBuffer;
    buffer.thoughtDeltaBuffer = '';
    return pending;
  };
  const armThoughtIdleResetTimer = () => {
    clearThoughtIdleResetTimer();
    thoughtIdleResetTimer = setTimeout(() => {
      thoughtIdleResetTimer = null;
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState.isThinkingStreaming) {
        return;
      }
      updateConversationState(handlerConversationId, {
        isThinkingStreaming: false,
      });
    }, THINKING_IDLE_RESET_MS);
  };
  // Keep the most recent execution diagnostics while bounding per-conversation memory usage.
  const EXECUTION_NARRATIVE_LIMIT = 40;
  const buildNarrativeId = (stage: ExecutionNarrativeEntry['stage'], traceId?: string): string =>
    `${stage}-${traceId ?? `${String(Date.now())}-${Math.random().toString(36).slice(2, 8)}`}`;
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
      typeof payload.event_time_us === 'number' ? payload.event_time_us : Date.now() * 1000;
    const eventCounter = typeof payload.event_counter === 'number' ? payload.event_counter : 0;

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
        metadata?: { source?: string | undefined } | undefined;
      };
      const source = messageData.metadata?.source;
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

      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });

      if (handlerConversationId === activeConversationId) {
        const newMessages = timelineToMessages(updatedTimeline);
        setState({ messages: newMessages });
      }
    },

    onThoughtDelta: (event) => {
      const delta = event.data.delta;
      if (!delta) return;
      armThoughtIdleResetTimer();

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
      clearThoughtIdleResetTimer();
      const pendingThoughtDelta = consumePendingThoughtDelta();
      const newThought = event.data.thought;
      const { getConversationState } = get();

      const convState = getConversationState(handlerConversationId);
      let persistedStreamingThought = convState.streamingThought + pendingThoughtDelta;
      const normalizedNewThought = (newThought || '').trim();
      const normalizedPersisted = persistedStreamingThought.trim();
      if (normalizedNewThought.length > 0) {
        if (normalizedPersisted.length === 0) {
          persistedStreamingThought = newThought;
        } else if (!normalizedPersisted.includes(normalizedNewThought)) {
          if (
            normalizedNewThought.length > normalizedPersisted.length &&
            normalizedNewThought.includes(normalizedPersisted)
          ) {
            persistedStreamingThought = newThought;
          } else if (!normalizedNewThought.includes(normalizedPersisted)) {
            persistedStreamingThought = `${normalizedPersisted}\n${newThought}`;
          }
        }
      }

      const stateUpdates: Partial<ConversationState> = {
        agentState: 'thinking',
        isThinkingStreaming: false,
        streamingThought: persistedStreamingThought,
      };

      if (newThought && newThought.trim() !== '') {
        stateUpdates.currentThought = convState.currentThought + '\n' + newThought;
      }

      queueTimelineEvent(event, stateUpdates);
      flushTimelineBufferSync();
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
        useExecutionStore.getState().setAgentIsPlanMode(isPlanMode);
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
        taskCount: data.tasks.length,
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
        content?: string | undefined;
      };
      console.log('[TaskSync] task_updated received:', {
        taskId: data.task_id,
        status: data.status,
      });
      const { getConversationState, updateConversationState } = get();
      const state = getConversationState(handlerConversationId);
      const tasks = state.tasks.map((t: import('../../types/agent').AgentTask) =>
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
      queueTimelineEvent(event);
    },

    onTaskComplete: (event) => {
      queueTimelineEvent(event);
    },

    onModelSwitchRequested: (event: AgentEvent<ModelSwitchRequestedEventData>) => {
      const model = (event.data.model || '').trim();
      if (!model) return;

      if (!event.data.provider_type) {
        console.warn(
          '[model-switch] Received model_switch_requested with no provider_type for model:',
          model
        );
      }

      const { getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const nextAppModelContext = {
        ...(convState.appModelContext ?? {}),
        llm_model_override: model,
      };

      queueTimelineEvent(event, {
        appModelContext: nextAppModelContext,
      });
    },

    onModelOverrideRejected: (event: AgentEvent<ModelOverrideRejectedEventData>) => {
      const { getConversationState } = get();

      console.warn(
        '[model-switch] Model override rejected by backend:',
        event.data.model,
        'reason:',
        event.data.reason
      );

      // Clear the rejected override from appModelContext
      const convState = getConversationState(handlerConversationId);
      const currentCtx = convState.appModelContext ?? {};
      const { llm_model_override: _removed, ...restCtx } = currentCtx;

      queueTimelineEvent(event, {
        appModelContext: Object.keys(restCtx).length > 0 ? restCtx : null,
      });
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
            ? decision.metadata['domain_lane']
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
        typeof selection.tool_budget === 'number'
          ? `, budget=${String(selection.tool_budget)}`
          : '';
      const insight = `[Selection] kept ${String(selection.final_count)}/${String(selection.initial_count)}, removed ${String(selection.removed_total)}${budgetText}`;
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
      const insight = `[Policy] filtered ${String(filtered.removed_total)} tools across ${String(filtered.stage_count)} stages`;
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
      const refreshStateText =
        changed.refresh_status &&
        changed.refresh_status !== 'deferred' &&
        changed.refresh_status !== 'not_applicable'
          ? ` · refresh=${changed.refresh_status}`
          : '';
      const refreshCountText =
        typeof changed.refreshed_tool_count === 'number'
          ? ` (${String(changed.refreshed_tool_count)} tools)`
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
      queueTimelineEvent(event);
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

      // Tool state must update immediately so the UI shows tool activity right away
      updateConversationState(handlerConversationId, {
        activeToolCalls: newMap,
        pendingToolsStack: newStack,
        agentState: 'acting',
      });

      // Timeline append is batched
      queueTimelineEvent(event);

      additionalHandlers?.onAct?.(event);
    },

    onObserve: (event) => {
      const { updateConversationState, getConversationState } = get();

      const convState = getConversationState(handlerConversationId);

      const stack = [...convState.pendingToolsStack];
      stack.pop();

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

      // Tool state must update immediately
      updateConversationState(handlerConversationId, {
        pendingToolsStack: stack,
        activeToolCalls: newMap,
        agentState: 'observing',
      });

      // Timeline append is batched
      queueTimelineEvent(event);

      additionalHandlers?.onObserve?.(event);
    },

    onTextStart: () => {
      clearThoughtIdleResetTimer();
      consumePendingThoughtDelta();
      const { updateConversationState } = get();

      updateConversationState(handlerConversationId, {
        streamStatus: 'streaming',
        streamingAssistantContent: '',
        streamingThought: '',
        isThinkingStreaming: false,
      });
    },

    onTextDelta: (event) => {
      const delta = event.data.delta;
      if (!delta) return;
      // text_start can occasionally be skipped or delayed on unreliable links.
      // When text tokens arrive, force-stop any pending thought stream to avoid
      // stale thinking blocks masking assistant output.
      clearThoughtIdleResetTimer();
      consumePendingThoughtDelta();

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
            const shouldClearThinking =
              convState.isThinkingStreaming || convState.streamingThought.trim().length > 0;
            updateConversationState(handlerConversationId, {
              streamingAssistantContent: newContent,
              streamStatus: 'streaming',
              ...(shouldClearThinking ? { streamingThought: '', isThinkingStreaming: false } : {}),
            });
          }
        }, tokenBatchIntervalMs);
      }
    },

    onTextEnd: (event) => {
      const { getConversationState } = get();

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

      interface TextEndEventData {
        full_text: string;
      }
      const textEndEvent: AgentEvent<TextEndEventData> = {
        type: 'text_end',
        data: { full_text: finalContent },
      };

      queueTimelineEvent(textEndEvent, {
        streamingAssistantContent: '',
        streamingThought: '',
        isThinkingStreaming: false,
      });
      flushTimelineBufferSync();
    },

    onClarificationAsked: (event) => {
      const clarificationEvent: AgentEvent<ClarificationAskedEventData> = {
        type: 'clarification_asked',
        data: event.data,
      };

      queueTimelineEvent(clarificationEvent, {
        pendingClarification: event.data,
        agentState: 'awaiting_input',
      });
      flushTimelineBufferSync();

      useUnifiedHITLStore
        .getState()
        .handleSSEEvent(
          'clarification_asked',
          event.data as unknown as Record<string, unknown>,
          handlerConversationId
        );
    },

    onDecisionAsked: (event) => {
      const decisionEvent: AgentEvent<DecisionAskedEventData> = {
        type: 'decision_asked',
        data: event.data,
      };

      queueTimelineEvent(decisionEvent, {
        pendingDecision: event.data,
        agentState: 'awaiting_input',
      });
      flushTimelineBufferSync();

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
        te.type === 'clarification_asked' &&
        (te as TimelineEventWithRequestId).requestId === requestId
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
        te.type === 'decision_asked' && (te as TimelineEventWithRequestId).requestId === requestId
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
        te.type === 'env_var_requested' &&
        (te as TimelineEventWithRequestId).requestId === requestId
          ? {
              ...te,
              answered: true,
              providedVariables: event.data.saved_variables,
            }
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
      const envVarEvent: AgentEvent<EnvVarRequestedEventData> = {
        type: 'env_var_requested',
        data: event.data,
      };

      queueTimelineEvent(envVarEvent, {
        pendingEnvVarRequest: event.data,
        agentState: 'awaiting_input',
      });
      flushTimelineBufferSync();

      useUnifiedHITLStore
        .getState()
        .handleSSEEvent(
          'env_var_requested',
          event.data as unknown as Record<string, unknown>,
          handlerConversationId
        );
    },

    onPermissionAsked: (event) => {
      const permissionEvent: AgentEvent<PermissionAskedEventData> = {
        type: 'permission_asked',
        data: event.data,
      };

      queueTimelineEvent(permissionEvent, {
        pendingPermission: event.data,
        agentState: 'awaiting_input',
      });
      flushTimelineBufferSync();

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
        te.type === 'permission_asked' && (te as TimelineEventWithRequestId).requestId === requestId
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
      queueTimelineEvent(event, {
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
      queueTimelineEvent(event);
    },

    onArtifactReady: (event) => {
      const { updateConversationState, getConversationState } = get();
      const data = event.data;

      const convState = getConversationState(handlerConversationId);

      // Update the existing artifact_created timeline entry with URL
      const updatedTimeline = convState.timeline.map((item) => {
        if (item.type === 'artifact_created' && item.artifactId === data.artifact_id) {
          return {
            ...item,
            url: data.url,
            previewUrl: data.preview_url,
          };
        }
        return item;
      });

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });

      // Auto-open canvas for preview-compatible binary files
      // (text/code files are already handled by onArtifactOpen from the backend)
      const mime = (data.mime_type || '').toLowerCase();
      if (data.url && isCanvasPreviewable(mime, data.filename)) {
        useCanvasStore.getState().openTab({
          id: data.artifact_id,
          title: data.filename || 'Untitled',
          type: 'preview',
          content: data.url,
          artifactId: data.artifact_id,
          artifactUrl: data.url,
          mimeType: data.mime_type,
        });

        // Auto-switch to canvas layout if not already
        const currentMode = useLayoutModeStore.getState().mode;
        if (currentMode !== 'canvas') {
          useLayoutModeStore.getState().setMode('canvas');
        }
      }
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
        if (item.type === 'artifact_created' && item.artifactId === data.artifact_id) {
          return {
            ...item,
            error: data.error,
          };
        }
        return item;
      });

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });
    },

    onArtifactsBatch: (event) => {
      const data = event.data;

      if (!Array.isArray(data.artifacts)) return;

      // Queue the batch event itself
      queueTimelineEvent(event);

      // Queue individual artifact_created timeline entries for each artifact
      for (const info of data.artifacts) {
        const artifactEvent = {
          type: 'artifact_created' as const,
          data: {
            artifact_id: info.id,
            filename: info.filename,
            mime_type: info.mimeType,
            category: info.category,
            size_bytes: info.sizeBytes,
            url: info.url,
            preview_url: info.previewUrl,
            source_tool: info.sourceTool || data.source_tool,
            tool_execution_id: data.tool_execution_id,
          },
        };
        queueTimelineEvent(artifactEvent as AgentEvent<unknown>);
      }
      flushTimelineBufferSync();

      // Auto-open canvas for the first preview-compatible artifact
      let canvasOpened = false;
      for (const info of data.artifacts) {
        const mime = (info.mimeType || '').toLowerCase();
        if (info.url && isCanvasPreviewable(mime, info.filename)) {
          useCanvasStore.getState().openTab({
            id: info.id,
            title: info.filename || 'Untitled',
            type: 'preview',
            content: info.url || '',
            artifactId: info.id,
            artifactUrl: info.url,
            mimeType: info.mimeType,
          });
          canvasOpened = true;
        }
      }

      if (canvasOpened) {
        const currentMode = useLayoutModeStore.getState().mode;
        if (currentMode !== 'canvas') {
          useLayoutModeStore.getState().setMode('canvas');
        }
      }
    },

    onArtifactOpen: (event) => {
      interface ArtifactOpenEventData {
        artifact_id: string;
        content: string;
        title?: string;
        content_type?: string;
        language?: string;
        url?: string;
      }
      const data = event.data as ArtifactOpenEventData;
      if (!data.artifact_id || !data.content) return;

      const title = data.title || 'Untitled';
      const mime = (data.content_type || '').toLowerCase();

      const isPreviewFile = isCanvasPreviewable(mime, title);

      // Open the artifact in canvas with artifact link
      useCanvasStore.getState().openTab({
        id: data.artifact_id,
        title: title,
        type: isPreviewFile
          ? 'preview'
          : ((data.content_type ?? 'code') as
              | 'code'
              | 'markdown'
              | 'preview'
              | 'data'
              | 'a2ui-surface'
              | 'mcp-app'),
        content: data.content,
        language: data.language,
        artifactId: data.artifact_id,
        artifactUrl: data.url,
        mimeType: data.content_type,
      });

      // Auto-switch to canvas layout if not already
      const currentMode = useLayoutModeStore.getState().mode;
      if (currentMode !== 'canvas') {
        useLayoutModeStore.getState().setMode('canvas');
      }
    },

    onArtifactUpdate: (event) => {
      interface ArtifactUpdateEventData {
        artifact_id: string;
        content?: string;
        append?: boolean;
      }
      const data = event.data as ArtifactUpdateEventData;
      if (!data.artifact_id || data.content === undefined) return;

      const store = useCanvasStore.getState();
      const tab = store.tabs.find((t) => t.id === data.artifact_id);
      if (tab) {
        const newContent = data.append === true ? tab.content + data.content : (data.content ?? '');
        store.updateContent(data.artifact_id, newContent);
      }
    },

    onArtifactClose: (event) => {
      interface ArtifactCloseEventData {
        artifact_id: string;
      }
      const data = event.data as ArtifactCloseEventData;
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
        message_id?: string | undefined;
        generated_by?: string | undefined;
      };

      interface StateWithConversations {
        conversations: Array<{ id: string; title?: string }>;
      }
      setState((state: unknown) => {
        const typedState = state as StateWithConversations;
        const updatedList = typedState.conversations.map((c) =>
          c.id === data.conversation_id ? { ...c, title: data.title } : c
        );
        return { conversations: updatedList };
      });
    },

    onSuggestions: (event) => {
      const { updateConversationState } = get();

      interface SuggestionsEventData {
        suggestions?: string[];
      }
      const suggestions = (event.data as SuggestionsEventData).suggestions ?? [];

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

      const subagentIdToClear = event.data.subagent_id;
      let subagentPreviews = convState.subagentPreviews;
      if (subagentIdToClear && subagentPreviews.has(subagentIdToClear)) {
        subagentPreviews = new Map(subagentPreviews);
        subagentPreviews.delete(subagentIdToClear);
      }

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        subagentPreviews,
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

      const subagentIdToClear = event.data.subagent_id;
      let subagentPreviews = convState.subagentPreviews;
      if (subagentIdToClear && subagentPreviews.has(subagentIdToClear)) {
        subagentPreviews = new Map(subagentPreviews);
        subagentPreviews.delete(subagentIdToClear);
      }

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        subagentPreviews,
      });
      // Update background store if this was a background execution
      const bgStore = useBackgroundStore.getState();
      const execId = event.data.subagent_id || '';
      if (bgStore.executions.has(execId)) {
        bgStore.fail(execId, event.data.error || 'Unknown error');
      }
    },

    onSubAgentQueued: (event: AgentEvent<SubAgentQueuedEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });
    },

    onSubAgentKilled: (event: AgentEvent<SubAgentKilledEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);

      const subagentIdToClear = event.data.subagent_id;
      let subagentPreviews = convState.subagentPreviews;
      if (subagentIdToClear && subagentPreviews.has(subagentIdToClear)) {
        subagentPreviews = new Map(subagentPreviews);
        subagentPreviews.delete(subagentIdToClear);
      }

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        subagentPreviews,
      });
      // Update background store if this was a background execution
      const bgStore = useBackgroundStore.getState();
      const execId = event.data.subagent_id || '';
      if (bgStore.executions.has(execId)) {
        bgStore.fail(execId, event.data.kill_reason || 'Killed');
      }
    },

    onSubAgentSteered: (event: AgentEvent<SubAgentSteeredEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        agentState: 'acting',
      });
    },

    onToolPolicyDenied: (event: AgentEvent<ToolPolicyDeniedEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });
    },

    onSubAgentDepthLimited: (event: AgentEvent<SubAgentDepthLimitedEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });
    },

    onSubAgentSessionUpdate: (event: AgentEvent<SubAgentSessionUpdateEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);

      // Store live preview from status_message
      const subagentId = event.data.subagent_id;
      const statusMessage = event.data.status_message;
      let subagentPreviews = convState.subagentPreviews;
      if (subagentId && statusMessage) {
        subagentPreviews = new Map(convState.subagentPreviews);
        subagentPreviews.set(subagentId, statusMessage);
      }

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        agentState: 'acting',
        subagentPreviews,
      });
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
      interface MCPAppResultEventData {
        app_id?: string;
        resource_html?: string;
        ui_metadata?: Record<string, unknown>;
        resource_uri?: string;
        tool_name?: string;
        project_id?: string;
        server_name?: string;
        structured_content?: unknown;
        tool_result?: unknown;
        tool_input?: unknown;
      }
      const data = event.data as MCPAppResultEventData;
      const appId = data.app_id || '';
      const htmlContent = data.resource_html || undefined;
      const uiMetadata =
        data.ui_metadata && typeof data.ui_metadata === 'object' ? data.ui_metadata : {};
      const resourceUri =
        data.resource_uri ??
        (uiMetadata.resourceUri as string | undefined) ??
        (uiMetadata.resource_uri as string | undefined);
      const projectId = data.project_id ?? (uiMetadata.project_id as string | undefined);
      const toolName = data.tool_name ?? '';
      const serverName = data.server_name ?? (uiMetadata.server_name as string | undefined);

      // Cache HTML by URI for timeline "Open App" lookup
      if (resourceUri && htmlContent) {
        void import('../mcpAppStore').then(({ useMCPAppStore }) => {
          useMCPAppStore.getState().cacheHtmlByUri(resourceUri, htmlContent);
        });
      }

      // SEP-1865: Merge structuredContent into tool result for the renderer
      const toolResult = data.structured_content
        ? {
            ...(typeof data.tool_result === 'object' && data.tool_result !== null
              ? (data.tool_result as Record<string, unknown>)
              : {}),
            structuredContent: data.structured_content,
          }
        : (data.tool_result as string | undefined);

      const openMCPAppTab = (
        resolvedResourceUri?: string,
        options?: {
          title?: string | undefined;
          toolName?: string | undefined;
          serverName?: string | undefined;
          uiMetadata?: Record<string, unknown> | undefined;
        }
      ) => {
        const tabKey = resolvedResourceUri ?? appId ?? `app-${String(Date.now())}`;
        const tabId = `mcp-app-${tabKey}`;
        useCanvasStore.getState().openTab({
          id: tabId,
          title: options?.title || toolName || 'MCP App',
          type: 'mcp-app',
          content: '',
          mcpAppId: appId || undefined,
          mcpAppHtml: htmlContent,
          mcpAppToolResult: toolResult,
          mcpAppToolInput:
            typeof data.tool_input === 'object' && data.tool_input !== null
              ? (data.tool_input as Record<string, unknown>)
              : undefined,
          mcpAppUiMetadata: options?.uiMetadata || uiMetadata,
          mcpResourceUri: resolvedResourceUri,
          mcpToolName: options?.toolName || toolName || undefined,
          mcpProjectId: projectId,
          mcpServerName: options?.serverName ?? serverName,
        });
        useLayoutModeStore.getState().setMode('canvas');
      };

      const shouldWaitForStoreLookup = !!appId && !resourceUri && !htmlContent;

      // Always invalidate cached resource so fresh HTML is used.
      // When appId exists, the async store lookup is the SOLE path that opens
      // the tab — it has richer metadata (storeUri, title, serverName) and we
      // must avoid the sync path also opening a tab with a different tabKey,
      // which would create a duplicate.
      if (appId) {
        void import('../mcpAppStore').then(({ useMCPAppStore }) => {
          const store = useMCPAppStore.getState();
          store.invalidateResource(appId);

          const app = store.apps[appId] as
            | { ui_metadata?: Record<string, unknown>; tool_name?: string; server_name?: string }
            | undefined;
          // Prefer resourceUri from the event, then from the store, then undefined
          const resolvedUri = resourceUri ?? (app?.ui_metadata?.resourceUri as string | undefined);

          if (resolvedUri || htmlContent) {
            openMCPAppTab(resolvedUri, {
              title:
                (app?.ui_metadata?.title as string | undefined) ??
                (uiMetadata.title as string | undefined) ??
                toolName ??
                'MCP App',
              toolName: app?.tool_name ?? toolName ?? undefined,
              serverName: app?.server_name ?? serverName ?? undefined,
              uiMetadata: app?.ui_metadata ?? uiMetadata,
            });
          } else if (shouldWaitForStoreLookup) {
            // No URI and no HTML — only open if the app has UI hints
            const hasUiHint = !!(app?.ui_metadata?.title || app?.tool_name);
            if (hasUiHint) {
              openMCPAppTab(undefined, {
                title: (app?.ui_metadata?.title as string | undefined) ?? toolName ?? 'MCP App',
                toolName: app?.tool_name ?? toolName ?? undefined,
                serverName: app?.server_name ?? serverName ?? undefined,
                uiMetadata: app?.ui_metadata ?? uiMetadata,
              });
            }
          }
        });
      } else if (htmlContent || resourceUri) {
        // No appId — open directly with whatever we have (sync path).
        // Only open a Canvas tab if we have actual content to display.
        // Non-UI tools (e.g. echo) produce no htmlContent and no resourceUri,
        // and opening an empty tab causes 'content length: 0' errors.
        openMCPAppTab(resourceUri ?? undefined, {
          title: (uiMetadata.title as string | undefined) ?? toolName ?? 'MCP App',
          uiMetadata,
        });
      }
    },

    onMCPAppRegistered: (event) => {
      interface MCPAppRegisteredEventData {
        app_id: string;
        server_name?: string;
        tool_name?: string;
        resource_uri?: string;
        title?: string;
        source?: string;
      }
      const data = event.data as unknown as MCPAppRegisteredEventData;
      if (!data.app_id) return;
      // Dynamically import to avoid circular deps
      void import('../mcpAppStore').then(({ useMCPAppStore }) => {
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
          source: (data.source ?? 'user_added') as 'user_added' | 'agent_developed',
          status: 'discovered',
          has_resource: false,
        });
      });
    },

    // Canvas handlers (A2UI deep integration)
    onCanvasUpdated: (event: AgentEvent<CanvasUpdatedEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState) return;

      const data = event.data;
      const canvasStore = useCanvasStore.getState();
      const layoutStore = useLayoutModeStore.getState();

      if (data.action === 'created' && data.block) {
        // Map backend CanvasBlock type to frontend CanvasContentType
        const typeMap: Record<string, 'code' | 'markdown' | 'preview' | 'data' | 'a2ui-surface'> = {
          code: 'code',
          markdown: 'markdown',
          image: 'preview',
          table: 'data',
          chart: 'data',
          form: 'data',
          widget: 'preview',
          a2ui_surface: 'a2ui-surface',
        };
        const tabType = typeMap[data.block.block_type] ?? 'code';

        canvasStore.openTab({
          id: data.block.id,
          title: data.block.title,
          type: tabType,
          content: data.block.content,
          language: data.block.metadata.language,
          mimeType: data.block.metadata.mime_type,
          ...(tabType === 'a2ui-surface'
            ? {
                a2uiSurfaceId:
                  typeof data.block.metadata.surface_id === 'string'
                    ? data.block.metadata.surface_id
                    : data.block.id,
                a2uiMessages: data.block.content,
              }
            : {}),
        });

        // Auto-switch to canvas layout
        if (layoutStore.mode !== 'canvas') {
          layoutStore.setMode('canvas');
        }
      } else if (data.action === 'updated' && data.block) {
        const existingTab = canvasStore.tabs.find((t) => t.id === data.block_id);
        if (existingTab) {
          if (existingTab.type === 'a2ui-surface') {
            const mergedA2UI = mergeA2UIMessageStream(
              existingTab.a2uiMessages ?? existingTab.content,
              data.block.content
            );
            canvasStore.updateContent(data.block_id, mergedA2UI);
            canvasStore.updateTab(data.block_id, {
              a2uiMessages: mergedA2UI,
              a2uiSurfaceId:
                (typeof data.block.metadata.surface_id === 'string'
                  ? data.block.metadata.surface_id
                  : undefined) ??
                existingTab.a2uiSurfaceId ??
                data.block.id,
            });
          } else {
            canvasStore.updateContent(data.block_id, data.block.content);
          }
          // Also update title if changed
          if (existingTab.title !== data.block.title) {
            canvasStore.updateTab(data.block_id, { title: data.block.title });
          }
        } else {
          // Tab not open yet — open it
          const typeMap: Record<string, 'code' | 'markdown' | 'preview' | 'data' | 'a2ui-surface'> =
            {
              code: 'code',
              markdown: 'markdown',
              image: 'preview',
              table: 'data',
              chart: 'data',
              form: 'data',
              widget: 'preview',
              a2ui_surface: 'a2ui-surface',
            };
          const fallbackTabType = typeMap[data.block.block_type] ?? 'code';
          canvasStore.openTab({
            id: data.block.id,
            title: data.block.title,
            type: fallbackTabType,
            content: data.block.content,
            language: data.block.metadata.language,
            mimeType: data.block.metadata.mime_type,
            ...(fallbackTabType === 'a2ui-surface'
              ? {
                  a2uiSurfaceId:
                    typeof data.block.metadata.surface_id === 'string'
                      ? data.block.metadata.surface_id
                      : data.block.id,
                  a2uiMessages: data.block.content,
                }
              : {}),
          });
        }

        if (layoutStore.mode !== 'canvas') {
          layoutStore.setMode('canvas');
        }
      } else if (data.action === 'deleted') {
        canvasStore.closeTab(data.block_id, true);

        // If no more tabs, switch back to chat mode
        if (useCanvasStore.getState().tabs.length === 0) {
          layoutStore.setMode('chat');
        }
      }

      // Add to timeline
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });
    },

    // A2UI interactive action handler
    onA2UIActionAsked: (event: AgentEvent<A2UIActionAskedEventData>) => {
      const blockId = event.data.block_id;
      const requestId = event.data.request_id;
      if (!blockId || !requestId) return;

      // Store the server-assigned request_id into the canvas tab so the
      // A2UISurfaceRenderer can use it when dispatching user actions back.
      const canvasStore = useCanvasStore.getState();
      canvasStore.updateTab(blockId, { a2uiHitlRequestId: requestId });

      // Add to timeline
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState) return;
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
      });
    },

    // Memory recall/capture handlers
    onMemoryRecalled: (event: AgentEvent<MemoryRecalledEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState) return;
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      updateConversationState(handlerConversationId, {
        recalledMemories: event.data.memories ?? null,
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

    // ===== Multi-Agent Spawn Tree Handlers =====

    onAgentSpawned: (event: AgentEvent<AgentSpawnedEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState) return;
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      const data = event.data;
      const agentNodes = new Map(convState.agentNodes);
      const node: AgentNode = {
        agentId: data.agent_id,
        name: data.agent_name ?? null,
        parentAgentId: data.parent_agent_id ?? null,
        sessionId: data.child_session_id ?? null,
        status: 'running',
        taskSummary: data.task_summary ?? null,
        result: null,
        success: null,
        artifacts: [],
        children: [],
        createdAt: Date.now(),
        lastUpdateAt: Date.now(),
      };
      agentNodes.set(data.agent_id, node);
      if (data.parent_agent_id && agentNodes.has(data.parent_agent_id)) {
        const parent = agentNodes.get(data.parent_agent_id);
        if (parent) {
          agentNodes.set(data.parent_agent_id, {
            ...parent,
            children: [...parent.children, data.agent_id],
            lastUpdateAt: Date.now(),
          });
        }
      }
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        agentNodes,
      });
    },

    onAgentCompleted: (event: AgentEvent<AgentCompletedEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState) return;
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      const data = event.data;
      const agentNodes = new Map(convState.agentNodes);
      const existing = agentNodes.get(data.agent_id);
      if (existing) {
        agentNodes.set(data.agent_id, {
          ...existing,
          status: data.success ? 'completed' : 'failed',
          result: data.result ?? null,
          success: data.success ?? null,
          artifacts: data.artifacts ?? [],
          lastUpdateAt: Date.now(),
        });
      }
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        agentNodes,
      });
    },

    onAgentStopped: (event: AgentEvent<AgentStoppedEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState) return;
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      const data = event.data;
      const agentNodes = new Map(convState.agentNodes);
      const existing = agentNodes.get(data.agent_id);
      if (existing) {
        agentNodes.set(data.agent_id, {
          ...existing,
          status: 'stopped',
          lastUpdateAt: Date.now(),
        });
      }
      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        agentNodes,
      });
    },

    onGraphRunStarted: (event: AgentEvent<GraphRunStartedEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState) return;
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      const d = event.data;
      useGraphStore
        .getState()
        .runStarted(d.graph_run_id, d.graph_id, d.graph_name, d.pattern, d.entry_node_ids);
      updateConversationState(handlerConversationId, { timeline: updatedTimeline });
    },

    onGraphRunCompleted: (event: AgentEvent<GraphRunCompletedEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState) return;
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      const d = event.data;
      useGraphStore
        .getState()
        .runCompleted(d.graph_run_id, d.total_steps, d.duration_seconds ?? null);
      updateConversationState(handlerConversationId, { timeline: updatedTimeline });
    },

    onGraphRunFailed: (event: AgentEvent<GraphRunFailedEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState) return;
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      const d = event.data;
      useGraphStore.getState().runFailed(d.graph_run_id, d.error_message, d.failed_node_id ?? null);
      updateConversationState(handlerConversationId, { timeline: updatedTimeline });
    },

    onGraphRunCancelled: (event: AgentEvent<GraphRunCancelledEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState) return;
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      const d = event.data;
      useGraphStore.getState().runCancelled(d.graph_run_id, d.reason);
      updateConversationState(handlerConversationId, { timeline: updatedTimeline });
    },

    onGraphNodeStarted: (event: AgentEvent<GraphNodeStartedEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState) return;
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      const d = event.data;
      useGraphStore
        .getState()
        .nodeStarted(
          d.graph_run_id,
          d.node_id,
          d.node_label,
          d.agent_definition_id,
          d.agent_session_id ?? null
        );
      updateConversationState(handlerConversationId, { timeline: updatedTimeline });
    },

    onGraphNodeCompleted: (event: AgentEvent<GraphNodeCompletedEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState) return;
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      const d = event.data;
      useGraphStore
        .getState()
        .nodeCompleted(d.graph_run_id, d.node_id, d.output_keys, d.duration_seconds ?? null);
      updateConversationState(handlerConversationId, { timeline: updatedTimeline });
    },

    onGraphNodeFailed: (event: AgentEvent<GraphNodeFailedEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState) return;
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      const d = event.data;
      useGraphStore.getState().nodeFailed(d.graph_run_id, d.node_id, d.error_message);
      updateConversationState(handlerConversationId, { timeline: updatedTimeline });
    },

    onGraphNodeSkipped: (event: AgentEvent<GraphNodeSkippedEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState) return;
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      const d = event.data;
      useGraphStore.getState().nodeSkipped(d.graph_run_id, d.node_id, d.reason);
      updateConversationState(handlerConversationId, { timeline: updatedTimeline });
    },

    onGraphHandoff: (event: AgentEvent<GraphHandoffEventData>) => {
      const { updateConversationState, getConversationState } = get();
      const convState = getConversationState(handlerConversationId);
      if (!convState) return;
      const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);
      const d = event.data;
      useGraphStore
        .getState()
        .handoff(
          d.graph_run_id,
          d.from_node_id,
          d.to_node_id,
          d.from_label,
          d.to_label,
          d.context_summary
        );
      updateConversationState(handlerConversationId, { timeline: updatedTimeline });
    },

    onComplete: (event) => {
      const { updateConversationState, getConversationState } = get();

      clearThoughtIdleResetTimer();
      clearAllDeltaBuffers();

      const convState = getConversationState(handlerConversationId);

      // Remove transient streaming control events.
      // Keep text_end events intact so their IDs stay stable and avoid
      // text_end -> assistant_message remount flicker at stream completion.
      interface TextEndTimelineEvent {
        type: string;
        fullText?: string;
      }
      const hasTextEndMessages = convState.timeline.some(
        (e) => e.type === 'text_end' && !!(e as TextEndTimelineEvent).fullText?.trim()
      );
      const cleanedTimeline = convState.timeline.filter((e) => {
        if (e.type === 'text_start' || e.type === 'text_delta') {
          return false;
        }
        if (e.type === 'text_end') {
          return !!(e as TextEndTimelineEvent).fullText?.trim();
        }
        return true;
      });

      // Only add assistant_message from complete event when no text_end segment exists,
      // to avoid duplicating final output.
      const completeEvent: AgentEvent<CompleteEventData> = event;
      interface CompleteEventWithContent {
        content?: string;
      }
      const hasContent = !!(completeEvent.data as CompleteEventWithContent).content?.trim();
      const updatedTimeline =
        hasContent && !hasTextEndMessages
          ? appendSSEEventToTimeline(cleanedTimeline, completeEvent)
          : cleanedTimeline;

      const newMessages = timelineToMessages(updatedTimeline);

      updateConversationState(handlerConversationId, {
        timeline: updatedTimeline,
        streamingAssistantContent: '',
        streamingThought: '',
        isThinkingStreaming: false,
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
      void (async () => {
        try {
          const { httpClient } = await import('../../services/client/httpClient');
          interface TaskResponse {
            tasks?: unknown[];
          }
          const res = await httpClient.get<TaskResponse>(`/agent/plan/tasks/${handlerConversationId}`);
          if (res && Array.isArray(res.tasks) && res.tasks.length > 0) {
            const { updateConversationState } = get();
            updateConversationState(handlerConversationId, {
              tasks: res.tasks as import('../../types/agent').AgentTask[],
            });
            console.log(
              '[TaskSync] onComplete fallback: fetched',
              String(res.tasks.length),
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

      clearThoughtIdleResetTimer();
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

      clearThoughtIdleResetTimer();
      clearDeltaBuffers(handlerConversationId);

      updateConversationState(handlerConversationId, {
        streamingThought: '',
        isThinkingStreaming: false,
        isStreaming: false,
        streamStatus: 'idle',
      });
    },
  };
}
