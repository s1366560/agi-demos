/**
 * Message loading actions extracted from agentV3.ts.
 *
 * Contains loadMessages and loadEarlierMessages which handle
 * fetching conversation history from the API, IndexedDB caching,
 * and WebSocket subscription for live streaming.
 */

import { agentService } from '../../services/agentService';
import { httpClient } from '../../services/client/httpClient';
import {
  type ConversationState,
  createDefaultConversationState,
} from '../../types/conversationState';
import { loadConversationState, saveConversationState } from '../../utils/conversationDB';
import { logger } from '../../utils/logger';
import { useContextStore } from '../contextStore';

import { replayCanvasEventsFromTimeline } from './canvasReplay';
import {
  TOKEN_BATCH_INTERVAL_MS,
  THOUGHT_BATCH_INTERVAL_MS,
  getDeltaBuffer,
  clearDeltaBuffers,
  clearAllDeltaBuffers,
  queueTimelineEvent as queueTimelineEventRaw,
  flushTimelineBufferSync as flushTimelineBufferSyncRaw,
  bindTimelineBufferDeps,
} from './deltaBuffers';
import { useExecutionStore } from './executionStore';
import { useAgentHITLStore } from './hitlStore';
import { createStreamEventHandlers, type StreamHandlerDeps } from './streamEventHandlers';
import { useStreamingStore } from './streamingStore';
import { useTimelineStore } from './timelineStore';
import { mergeHITLResponseEvents, timelineToMessages } from './timelineUtils';

import type { AgentV3State } from './types';
import type {
  AgentStreamHandler,
  AgentTask,
  Message,
  SubscribeOptions,
  TimelineEvent,
} from '../../types/agent';
import type { StoreApi } from 'zustand';

export interface MessageLoadActionDeps {
  get: () => {
    activeConversationId: string | null;
    conversations: AgentV3State['conversations'];
    conversationStates: Map<string, ConversationState>;
    getConversationState: (conversationId: string) => ConversationState;
    updateConversationState: (conversationId: string, updates: Partial<ConversationState>) => void;
    setLlmModelOverride: (conversationId: string, modelName: string | null) => void;
  };
  set: StoreApi<AgentV3State>['setState'];
}

type ExecutionStatusWithCursor = Awaited<ReturnType<typeof agentService.getExecutionStatus>> & {
  current_message_id?: string;
};

const compareTimelineEvents = (a: TimelineEvent, b: TimelineEvent): number => {
  const timeDiff = a.eventTimeUs - b.eventTimeUs;
  if (timeDiff !== 0) return timeDiff;
  return a.eventCounter - b.eventCounter;
};

export function createMessageLoadActions(deps: MessageLoadActionDeps) {
  const { get, set } = deps;

  return {
    loadMessages: async (conversationId: string, projectId: string): Promise<void> => {
      const isStillActive = () => get().activeConversationId === conversationId;
      // Get last known time from localStorage for recovery
      const lastKnownTimeUs = parseInt(
        localStorage.getItem(`agent_time_us_${conversationId}`) || '0',
        10
      );

      // DEBUG: Log recovery attempt parameters
      logger.debug(
        `[AgentV3] loadMessages starting for ${conversationId}, lastKnownTimeUs=${String(lastKnownTimeUs)}`
      );

      // Try to load from IndexedDB first
      const cachedState = await loadConversationState(conversationId);
      if (!isStillActive()) {
        logger.debug('Conversation changed during cached history load, ignoring result');
        return;
      }

      // Only replace timeline/messages if current state is empty
      const currentTimeline = useTimelineStore.getState().agentTimeline;
      const hasExistingData = currentTimeline.length > 0;
      const existingConversationState = get().conversationStates.get(conversationId);
      const isFreshConversationShell =
        !hasExistingData &&
        !cachedState &&
        existingConversationState !== undefined &&
        existingConversationState.timeline.length === 0 &&
        !existingConversationState.isStreaming;

      {
        const tls = useTimelineStore.getState();
        // A newly created blank conversation already has a local shell in memory.
        // Keep the composer interactive while we hydrate server state so automation
        // and fast user input do not race against a transient disabled window.
        tls.setAgentIsLoadingHistory(!hasExistingData && !isFreshConversationShell);
        tls.setAgentHasEarlier(cachedState?.hasEarlier || false);
        tls.setAgentEarliestPointers(
          cachedState?.earliestTimeUs || null,
          cachedState?.earliestCounter || null
        );
        if (!hasExistingData) {
          tls.setAgentTimeline(cachedState?.timeline || []);
          tls.setAgentMessages(
            cachedState?.timeline ? timelineToMessages(cachedState.timeline) : []
          );
        }

        const ss = useStreamingStore.getState();
        ss.setAgentCurrentThought(cachedState?.currentThought || '');
        ss.setAgentStreamingThought('');
        ss.setAgentIsThinkingStreaming(false);

        const es = useExecutionStore.getState();
        es.setAgentIsPlanMode(cachedState?.isPlanMode || false);
        es.setAgentExecutionState(cachedState?.agentState || 'idle');

        const hs = useAgentHITLStore.getState();
        hs.setPendingClarification(cachedState?.pendingClarification || null);
        hs.setPendingDecision(cachedState?.pendingDecision || null);
        hs.setPendingEnvVarRequest(cachedState?.pendingEnvVarRequest || null);
      }

      try {
        // Parallelize independent API calls (async-parallel)
        const [response, execStatus, _contextStatusResult, planModeResult, taskListResult] =
          await Promise.all([
            agentService.getConversationMessages(conversationId, projectId, 200),
            agentService
              .getExecutionStatus(conversationId, true, lastKnownTimeUs)
              .catch((_err: unknown) => {
                logger.warn(`[AgentV3] getExecutionStatus failed:`, _err);
                return null;
              }),
            // Restore context status indicator on conversation switch / page refresh
            (async () => {
              await useContextStore
                .getState()
                .fetchContextStatus(conversationId, projectId, isStillActive);
            })().catch((_err: unknown) => {
              logger.warn(`[AgentV3] fetchContextStatus failed:`, _err);
              return null;
            }),
            // Fetch plan mode status from API
            (async () => {
              const { planService } = await import('../../services/planService');
              return planService.getMode(conversationId);
            })().catch((_err: unknown) => {
              logger.debug(`[AgentV3] getMode failed:`, _err);
              return null;
            }),
            // Fetch tasks for conversation
            (async () => {
              const res = await httpClient.get<{ tasks?: AgentTask[] }>(
                `/agent/plan/tasks/${conversationId}`
              );
              return res;
            })().catch((_err: unknown) => {
              logger.debug(`[AgentV3] fetchTasks failed:`, _err);
              return null;
            }),
          ]);

        if (!isStillActive()) {
          logger.debug('Conversation changed during load, ignoring result');
          return;
        }

        // Update plan mode from API response
        if (planModeResult !== null) {
          const isPlan = planModeResult.mode === 'plan';
          useExecutionStore.getState().setAgentIsPlanMode(isPlan);
          get().updateConversationState(conversationId, { isPlanMode: isPlan });
        }

        // Update tasks from API response
        if (taskListResult && Array.isArray(taskListResult.tasks)) {
          get().updateConversationState(conversationId, { tasks: taskListResult.tasks });
        }

        // Restore persisted model override from conversation's agent_config
        const conversations = get().conversations;
        const conv = conversations.find((c) => c.id === conversationId);
        const persistedOverride = conv?.agent_config?.llm_model_override;
        if (typeof persistedOverride === 'string' && persistedOverride.trim()) {
          const convState = get().conversationStates.get(conversationId);
          const currentOverride = (
            convState?.appModelContext as Record<string, unknown> | undefined
          )?.llm_model_override;
          if (!currentOverride) {
            get().setLlmModelOverride(conversationId, persistedOverride);
          }
        }

        // DEBUG: Log full timeline analysis for diagnosing missing/disordered messages
        const eventTypeCounts: Record<string, number> = {};
        let isOrdered = true;
        let prevTimeUs = -1;
        let prevCounter = -1;
        for (const event of response.timeline) {
          eventTypeCounts[event.type] = (eventTypeCounts[event.type] || 0) + 1;
          if (
            event.eventTimeUs < prevTimeUs ||
            (event.eventTimeUs === prevTimeUs && event.eventCounter <= prevCounter)
          ) {
            isOrdered = false;
            console.error(
              `[AgentV3] Timeline out of order! timeUs=${String(event.eventTimeUs)},counter=${String(event.eventCounter)} <= prev timeUs=${String(prevTimeUs)},counter=${String(prevCounter)}`,
              event
            );
          }
          prevTimeUs = event.eventTimeUs;
          prevCounter = event.eventCounter;
        }
        logger.debug(`[AgentV3] loadMessages API response:`, {
          conversationId,
          totalEvents: response.timeline.length,
          eventTypeCounts,
          isOrdered,
          has_more: response.has_more,
          first_time_us: response.first_time_us,
          first_counter: response.first_counter,
          last_time_us: response.last_time_us,
          last_counter: response.last_counter,
        });

        // Ensure timeline is sorted by eventTimeUs + eventCounter (defensive fix)
        const sortedTimeline = [...response.timeline].sort(compareTimelineEvents);

        // Merge HITL response events into request events for single-card rendering
        const mergedTimeline = mergeHITLResponseEvents(sortedTimeline);

        // Store the raw timeline and derive messages (no merging)
        const messages = timelineToMessages(mergedTimeline);
        const firstTimeUs = response.first_time_us ?? null;
        const firstCounter = response.first_counter ?? null;
        const lastTimeUs = response.last_time_us ?? null;

        // DEBUG: Log assistant_message events
        const assistantMsgs = mergedTimeline.filter(
          (e: TimelineEvent) => e.type === 'assistant_message'
        );
        logger.debug(
          `[AgentV3] loadMessages: Found ${String(assistantMsgs.length)} assistant_message events`,
          assistantMsgs
        );

        // DEBUG: Log artifact events in timeline
        const artifactEvents = mergedTimeline.filter(
          (e: TimelineEvent) => e.type === 'artifact_created'
        );
        logger.debug(
          `[AgentV3] loadMessages: Found ${String(artifactEvents.length)} artifact_created events in timeline`,
          artifactEvents
        );

        // Update localStorage with latest time
        if (lastTimeUs && lastTimeUs > 0) {
          localStorage.setItem(`agent_time_us_${conversationId}`, String(lastTimeUs));
        }

        // Update both global state and conversation-specific state
        const newConvState: Partial<ConversationState> = {
          hasEarlier: response.has_more,
          earliestTimeUs: firstTimeUs,
          earliestCounter: firstCounter,
        };

        const isCurrentlyStreaming = useStreamingStore.getState().agentIsStreaming;
        const isActiveConversation = get().activeConversationId === conversationId;
        const currentAgentTimeline = useTimelineStore.getState().agentTimeline;

        let finalTimeline: TimelineEvent[];
        let finalMessages: Message[];

        if (isCurrentlyStreaming && isActiveConversation && currentAgentTimeline.length > 0) {
          const eventMap = new Map<string, TimelineEvent>();
          for (const event of mergedTimeline) {
            eventMap.set(event.id, event);
          }
          for (const event of currentAgentTimeline) {
            const existing = eventMap.get(event.id);
            if (!existing || event.eventTimeUs >= existing.eventTimeUs) {
              eventMap.set(event.id, event);
            }
          }
          finalTimeline = Array.from(eventMap.values()).sort(compareTimelineEvents);
          finalMessages = timelineToMessages(finalTimeline);
        } else {
          finalTimeline = mergedTimeline;
          finalMessages = messages;
        }
        newConvState.timeline = finalTimeline;

        set((state) => {
          const newStates = new Map(state.conversationStates);
          const currentConvState =
            newStates.get(conversationId) || createDefaultConversationState();
          newStates.set(conversationId, {
            ...currentConvState,
            ...newConvState,
          } as ConversationState);

          return { conversationStates: newStates };
        });

        {
          const tls = useTimelineStore.getState();
          tls.setAgentTimeline(finalTimeline);
          tls.setAgentMessages(finalMessages);
          tls.setAgentIsLoadingHistory(false);
          tls.setAgentHasEarlier(response.has_more);
          tls.setAgentEarliestPointers(firstTimeUs, firstCounter);
        }

        // Persist to IndexedDB
        saveConversationState(conversationId, newConvState).catch(console.error);

        // Replay canvas_updated events to rebuild canvas tabs from server history.
        replayCanvasEventsFromTimeline(finalTimeline);

        // DEBUG: Log execution status for recovery debugging
        logger.debug(`[AgentV3] execStatus for ${conversationId}:`, {
          execStatus,
          is_running: execStatus?.is_running,
          lastKnownTimeUs,
          lastTimeUs,
        });
        const recoveredExecStatus = execStatus as ExecutionStatusWithCursor | null;

        // If agent is already running, recover streaming state before subscribing.
        if (recoveredExecStatus?.is_running) {
          logger.debug(
            `[AgentV3] Conversation ${conversationId} is running, recovering live stream...`
          );

          // CRITICAL: Clear any stale delta buffers before attaching to running session
          clearAllDeltaBuffers();

          useStreamingStore.getState().setAgentIsStreaming(true);
          useStreamingStore.getState().setAgentStreamStatus('streaming');
          useExecutionStore.getState().setAgentExecutionState('thinking');
          get().updateConversationState(conversationId, {
            isStreaming: true,
            streamStatus: 'streaming',
            agentState: 'thinking',
          });
        }

        // Always subscribe active conversation to WebSocket so externally-triggered
        // executions (e.g. channel ingress) can stream into the workspace in real time.
        if (get().activeConversationId === conversationId) {
          if (!agentService.isConnected()) {
            logger.debug(`[AgentV3] Connecting WebSocket...`);
            await agentService.connect();
            if (!isStillActive()) {
              logger.debug('Conversation changed during WebSocket connect, skipping subscribe');
              return;
            }
          }

          // Bind timeline buffer deps for this conversation
          bindTimelineBufferDeps(conversationId, {
            getConversationState: get().getConversationState,
            updateConversationState: get().updateConversationState,
          });

          const streamHandlerDeps: StreamHandlerDeps = {
            get,
            set: set as StreamHandlerDeps['set'],
            getDeltaBuffer,
            clearDeltaBuffers,
            clearAllDeltaBuffers,
            timelineToMessages,
            tokenBatchIntervalMs: TOKEN_BATCH_INTERVAL_MS,
            thoughtBatchIntervalMs: THOUGHT_BATCH_INTERVAL_MS,
            queueTimelineEvent: (event, stateUpdates) => {
              queueTimelineEventRaw(conversationId, event, stateUpdates);
            },
            flushTimelineBufferSync: () => {
              flushTimelineBufferSyncRaw(conversationId);
            },
          };
          const streamHandler: AgentStreamHandler = createStreamEventHandlers(
            conversationId,
            undefined,
            streamHandlerDeps
          );

          const subscribeOpts: SubscribeOptions = {};
          const currentMsgId = recoveredExecStatus?.current_message_id;
          if (typeof currentMsgId === 'string') {
            subscribeOpts.message_id = currentMsgId;
          } else if (typeof response.last_time_us === 'number') {
            subscribeOpts.from_time_us = response.last_time_us;
            if (typeof response.last_counter === 'number') {
              subscribeOpts.from_counter = response.last_counter;
            }
          } else if (typeof recoveredExecStatus?.last_event_time_us === 'number') {
            subscribeOpts.from_time_us = recoveredExecStatus.last_event_time_us;
            if (typeof recoveredExecStatus.last_event_counter === 'number') {
              subscribeOpts.from_counter = recoveredExecStatus.last_event_counter;
            }
          }
          agentService.subscribe(conversationId, streamHandler, subscribeOpts);
          logger.debug(`[AgentV3] Subscribed to conversation ${conversationId}`);
        }
      } catch (error) {
        if (get().activeConversationId !== conversationId) return;
        console.error('Failed to load messages', error);
        useTimelineStore.getState().setAgentIsLoadingHistory(false);
      }
    },

    loadEarlierMessages: async (conversationId: string, projectId: string): Promise<boolean> => {
      const { activeConversationId } = get();
      const tls = useTimelineStore.getState();
      const earliestTimeUs = tls.agentEarliestTimeUs;
      const earliestCounter = tls.agentEarliestCounter;
      const timeline = tls.agentTimeline;
      const isLoadingEarlier = tls.agentIsLoadingEarlier;

      // Guard: Don't load if already loading or no pagination point exists
      if (activeConversationId !== conversationId) return false;
      if (!earliestTimeUs || isLoadingEarlier) {
        logger.debug(
          '[AgentV3] Cannot load earlier messages: no pagination point or already loading'
        );
        return false;
      }

      logger.debug(
        '[AgentV3] Loading earlier messages before timeUs:',
        earliestTimeUs,
        'counter:',
        earliestCounter
      );
      useTimelineStore.getState().setAgentIsLoadingEarlier(true);

      try {
        const response = await agentService.getConversationMessages(
          conversationId,
          projectId,
          200,
          undefined,
          undefined,
          earliestTimeUs,
          earliestCounter ?? undefined
        );

        if (get().activeConversationId !== conversationId) {
          logger.debug(
            '[AgentV3] Conversation changed during load earlier messages, ignoring result'
          );
          return false;
        }

        // Prepend new events to existing timeline and sort by eventTimeUs + eventCounter
        const combinedTimeline = [...response.timeline, ...timeline];
        const sortedTimeline = combinedTimeline.sort(compareTimelineEvents);
        // Merge HITL response events into request events for single-card rendering
        const mergedTimeline = mergeHITLResponseEvents(sortedTimeline);
        const newMessages = timelineToMessages(mergedTimeline);
        const newFirstTimeUs = response.first_time_us ?? null;
        const newFirstCounter = response.first_counter ?? null;

        // Write to sub-store (sole owner of timeline state)
        {
          const tlsWrite = useTimelineStore.getState();
          tlsWrite.setAgentTimeline(mergedTimeline);
          tlsWrite.setAgentMessages(newMessages);
          tlsWrite.setAgentIsLoadingEarlier(false);
          tlsWrite.setAgentHasEarlier(response.has_more);
          tlsWrite.setAgentEarliestPointers(newFirstTimeUs, newFirstCounter);
        }

        logger.debug(
          '[AgentV3] Loaded earlier messages, total timeline length:',
          mergedTimeline.length
        );
        return true;
      } catch (error) {
        console.error('[AgentV3] Failed to load earlier messages:', error);
        useTimelineStore.getState().setAgentIsLoadingEarlier(false);
        return false;
      }
    },
  };
}
