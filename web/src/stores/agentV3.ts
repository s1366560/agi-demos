import { v4 as uuidv4 } from 'uuid';
import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

import { agentService } from '../services/agentService';
import type {
  Message, AgentStreamHandler, TimelineEvent, UserMessageEvent, AgentTask, SubscribeOptions,
} from '../types/agent';
import {
  type ConversationState,
  type HITLSummary,
  createDefaultConversationState,
  getHITLSummaryFromState,
  MAX_CONCURRENT_STREAMING_CONVERSATIONS,
} from '../types/conversationState';
import {
  saveConversationState,
  loadConversationState,
  deleteConversationState,
} from '../utils/conversationDB';
import { logger } from '../utils/logger';
import { tabSync } from '../utils/tabSync';

import { replayCanvasEventsFromTimeline } from './agent/canvasReplay';
import {
  TOKEN_BATCH_INTERVAL_MS,
  THOUGHT_BATCH_INTERVAL_MS,
  getDeltaBuffer,
  clearDeltaBuffers,
  clearAllDeltaBuffers,
  deleteDeltaBuffer,
  queueTimelineEvent as queueTimelineEventRaw,
  flushTimelineBufferSync as flushTimelineBufferSyncRaw,
  bindTimelineBufferDeps,
  clearAllTimelineBuffers,
} from './agent/deltaBuffers';
import { createHITLActions } from './agent/hitlActions';
import {
  touchConversation,
  evictStaleConversationStates,
  scheduleSave,
  cancelPendingSave,
  removeFromAccessOrder,
} from './agent/persistence';
import { createStreamEventHandlers } from './agent/streamEventHandlers';

// Extracted modules
import { initTabSync } from './agent/tabSync';
import {
  updateHITLEventInTimeline,
  mergeHITLResponseEvents,
  timelineToMessages,
} from './agent/timelineUtils';
import { useConversationsStore } from './agent/conversationsStore';
import { useExecutionStore } from './agent/executionStore';
import { useAgentHITLStore } from './agent/hitlStore';
import { useStreamingStore } from './agent/streamingStore';
import { useTimelineStore } from './agent/timelineStore';
import { useCanvasStore } from './canvasStore';
import { useLayoutModeStore } from './layoutMode';

import type { LLMConfigOverrides } from '../types/memory';

// API Response types for type safety

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
  devtools(
    (set, get) => ({
        conversations: [],
        activeConversationId: null,
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
            if (updates.pendingClarification !== undefined) hs.setPendingClarification(updates.pendingClarification);
            if (updates.pendingDecision !== undefined) hs.setPendingDecision(updates.pendingDecision);
            if (updates.pendingEnvVarRequest !== undefined) hs.setPendingEnvVarRequest(updates.pendingEnvVarRequest);
            if (updates.pendingPermission !== undefined) hs.setPendingPermission(updates.pendingPermission);
            if (updates.doomLoopDetected !== undefined) hs.setDoomLoopDetected(updates.doomLoopDetected);
            if (updates.costTracking !== undefined) hs.setCostTracking(updates.costTracking);
            if (updates.suggestions !== undefined) hs.setSuggestions(updates.suggestions);

            // Bridge timeline fields to timelineStore
            const ts = useTimelineStore.getState();
            if (updates.timeline !== undefined) ts.setAgentTimeline(updates.timeline);
            if (updates.hasEarlier !== undefined) ts.setAgentHasEarlier(updates.hasEarlier);
            if (updates.earliestTimeUs !== undefined || updates.earliestCounter !== undefined) {
              const convState = get().conversationStates.get(conversationId);
              ts.setAgentEarliestPointers(
                updates.earliestTimeUs !== undefined ? updates.earliestTimeUs : (convState?.earliestTimeUs ?? null),
                updates.earliestCounter !== undefined ? updates.earliestCounter : (convState?.earliestCounter ?? null),
              );
            }

            // Bridge streaming fields to streamingStore
            const ss = useStreamingStore.getState();
            if (updates.isStreaming !== undefined) ss.setAgentIsStreaming(updates.isStreaming);
            if (updates.streamStatus !== undefined) ss.setAgentStreamStatus(updates.streamStatus);
            if (updates.error !== undefined) ss.setAgentError(updates.error);
            if (updates.streamingAssistantContent !== undefined) ss.setAgentStreamingAssistantContent(updates.streamingAssistantContent);
            if (updates.streamingThought !== undefined) ss.setAgentStreamingThought(updates.streamingThought);
            if (updates.isThinkingStreaming !== undefined) ss.setAgentIsThinkingStreaming(updates.isThinkingStreaming);
            if (updates.currentThought !== undefined) ss.setAgentCurrentThought(updates.currentThought);

            // Bridge execution fields to executionStore
            const es = useExecutionStore.getState();
            if (updates.agentState !== undefined) es.setAgentExecutionState(updates.agentState);
            if (updates.activeToolCalls !== undefined) es.setAgentActiveToolCalls(updates.activeToolCalls);
            if (updates.pendingToolsStack !== undefined) es.setAgentPendingToolsStack(updates.pendingToolsStack);
            if (updates.isPlanMode !== undefined) es.setAgentIsPlanMode(updates.isPlanMode);
          }
        },

        /**
         * Set LLM parameter overrides for a conversation.
         * Stored inside appModelContext.llm_overrides so it flows via the existing
         * app_model_context WebSocket field to the backend.
         */
        setLlmOverrides: (conversationId: string, overrides: LLMConfigOverrides | null) => {
          const { updateConversationState, conversationStates } = get();
          const convState = conversationStates.get(conversationId);
          const currentCtx = convState?.appModelContext ?? {};
          if (overrides) {
            updateConversationState(conversationId, {
              appModelContext: { ...currentCtx, llm_overrides: overrides },
            });
          } else {
            // Remove llm_overrides key
            const { llm_overrides: _, ...rest } = currentCtx;
            updateConversationState(conversationId, {
              appModelContext: Object.keys(rest).length > 0 ? rest : null,
            });
          }
        },

        /**
         * Set per-conversation LLM model override.
         * Stored inside appModelContext.llm_model_override and sent via app_model_context.
         */
        setLlmModelOverride: (conversationId: string, modelName: string | null) => {
          const { updateConversationState, conversationStates } = get();
          const convState = conversationStates.get(conversationId);
          const currentCtx = convState?.appModelContext ?? {};

          const normalizedModel = modelName?.trim() || null;
          if (normalizedModel) {
            updateConversationState(conversationId, {
              appModelContext: { ...currentCtx, llm_model_override: normalizedModel },
            });
          } else {
            const { llm_model_override: _removed, ...rest } = currentCtx;
            updateConversationState(conversationId, {
              appModelContext: Object.keys(rest).length > 0 ? rest : null,
            });
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
            suggestions: convState.suggestions ?? [],
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

        setActiveConversation: (id) => {
          const {
            activeConversationId,
            conversationStates,
          } = get();

          // Skip if already on this conversation — avoids clearing delta buffers
          // and re-triggering state updates during active streaming.
          if (activeConversationId === id) return;

          // CRITICAL: Clear delta buffers when switching conversations
          // Prevents stale streaming content from previous conversation
          clearAllDeltaBuffers();
          clearAllTimelineBuffers();
          resetCanvasForConversationScope();

          // Reset context status for the new conversation (async import for browser compatibility)
          import('../stores/contextStore')
            .then(({ useContextStore }) => {
              useContextStore.getState().reset();
            })
            .catch(console.error);

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
                const timeDiff = a.eventTimeUs - (b.eventTimeUs ?? 0);
                if (timeDiff !== 0) return timeDiff;
                return a.eventCounter - b.eventCounter;
              });
              set({
                activeConversationId: id,
              });

              // Sync sub-stores from loaded conversation state
              useTimelineStore.getState().setAgentTimeline(sortedTimeline);
              useTimelineStore.getState().setAgentHasEarlier(newState.hasEarlier);
              useTimelineStore.getState().setAgentEarliestPointers(newState.earliestTimeUs, newState.earliestCounter);

              useStreamingStore.getState().setAgentIsStreaming(newState.isStreaming);
              useStreamingStore.getState().setAgentStreamStatus(newState.streamStatus);
              useStreamingStore.getState().setAgentStreamingAssistantContent(newState.streamingAssistantContent);
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
                suggestions: newState.suggestions ?? [],
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
            ? useConversationsStore.getState().conversations.find((c) => c.id === id) ?? null
            : null;
          useConversationsStore.getState().setCurrentConversation(convForDefault);
        },

        loadConversations: async (projectId) => {
          logger.debug(`[agentV3] loadConversations called for project: ${projectId}`);

          // Prevent duplicate calls for the same project
          const currentConvos = get().conversations;
          const firstConvoProject = currentConvos[0]?.project_id;
          if (currentConvos.length > 0 && firstConvoProject === projectId) {
            logger.debug(
              `[agentV3] Conversations already loaded for project ${projectId}, skipping`
            );
            return;
          }

          try {
            // Delegate to conversationsStore for API call + list management
            await useConversationsStore.getState().listConversations(projectId);
            // Sync back to agentV3 state (strangler fig dual-write)
            const convState = useConversationsStore.getState();
            set({
              conversations: convState.conversations,
              hasMoreConversations: convState.hasMoreConversations,
              conversationsTotal: convState.conversationsTotal,
            });
            logger.debug(`[agentV3] Loaded ${String(convState.conversations.length)} conversations via conversationsStore`);
          } catch (error) {
            console.error('[agentV3] Failed to list conversations', error);
          }
        },

        loadMoreConversations: async (projectId) => {
          const state = get();
          if (!state.hasMoreConversations) return;

          try {
            await useConversationsStore.getState().loadMoreConversations(projectId);
            const convState = useConversationsStore.getState();
            set({
              conversations: convState.conversations,
              hasMoreConversations: convState.hasMoreConversations,
              conversationsTotal: convState.conversationsTotal,
            });
            logger.debug(`[agentV3] Loaded more conversations via conversationsStore`);
          } catch (error) {
            console.error('[agentV3] Failed to load more conversations', error);
          }
        },

        deleteConversation: async (conversationId, projectId) => {
          try {
            // Delegate API call + list filtering to conversationsStore
            await useConversationsStore.getState().deleteConversation(conversationId, projectId);

            agentService.unsubscribe(conversationId);
            clearDeltaBuffers(conversationId);
            deleteDeltaBuffer(conversationId);
            cancelPendingSave(conversationId);
            removeFromAccessOrder(conversationId);

            const wasActive = get().activeConversationId === conversationId;
            set((state) => {
              const newStates = new Map(state.conversationStates);
              newStates.delete(conversationId);

              return {
                conversations: useConversationsStore.getState().conversations,
                conversationStates: newStates,
                activeConversationId:
                  state.activeConversationId === conversationId ? null : state.activeConversationId,
              };
            });

            // Reset sub-stores if we deleted the active conversation
            if (wasActive) {
              useTimelineStore.getState().setAgentTimeline([]);
              useTimelineStore.getState().setAgentMessages([]);
              useStreamingStore.getState().resetAgentStreaming();
              useExecutionStore.getState().resetAgentExecution();
            }

            deleteConversationState(conversationId).catch(console.error);
            tabSync.broadcastConversationDeleted(conversationId);
          } catch (error) {
            console.error('Failed to delete conversation', error);
            useStreamingStore.getState().setAgentError('Failed to delete conversation');
          }
        },

        renameConversation: async (conversationId, projectId, title) => {
          try {
            await useConversationsStore.getState().renameConversation(conversationId, projectId, title);
            set({ conversations: useConversationsStore.getState().conversations });
            tabSync.broadcastConversationRenamed(conversationId, title);
          } catch (error) {
            console.error('Failed to rename conversation', error);
            useStreamingStore.getState().setAgentError('Failed to rename conversation');
          }
        },

        createNewConversation: async (projectId) => {
          try {
            const newConv = await useConversationsStore.getState().createConversation(projectId, 'New Conversation');
            resetCanvasForConversationScope();

            const newConvState = createDefaultConversationState();

            touchConversation(newConv.id);
            set((state) => {
              const newStates = new Map(state.conversationStates);
              newStates.set(newConv.id, newConvState);

              return {
                conversations: useConversationsStore.getState().conversations,
                conversationStates: newStates,
                activeConversationId: newConv.id,
              };
            });

            useTimelineStore.getState().setAgentTimeline([]);
            useTimelineStore.getState().setAgentMessages([]);
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

            return newConv.id;
          } catch (error) {
            console.error('Failed to create conversation', error);
            useStreamingStore.getState().setAgentError('Failed to create conversation');
            return null;
          }
        },

        loadMessages: async (conversationId, projectId) => {
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

          // Only replace timeline/messages if current state is empty —
          // setActiveConversation already restores from in-memory cache,
          // so overwriting with IndexedDB data causes a visible flash.
          const currentTimeline = useTimelineStore.getState().agentTimeline;
          const hasExistingData = currentTimeline.length > 0;

          {
            const tls = useTimelineStore.getState();
            tls.setAgentIsLoadingHistory(!hasExistingData);
            tls.setAgentHasEarlier(cachedState?.hasEarlier || false);
            tls.setAgentEarliestPointers(
              cachedState?.earliestTimeUs || null,
              cachedState?.earliestCounter || null,
            );
            if (!hasExistingData) {
              tls.setAgentTimeline(cachedState?.timeline || []);
              tls.setAgentMessages(
                cachedState?.timeline ? timelineToMessages(cachedState.timeline) : [],
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
            // Include recovery info in execution status check
            const [response, execStatus, _contextStatusResult, planModeResult, taskListResult] =
              await Promise.all([
                agentService.getConversationMessages(
                  conversationId,
                  projectId,
                  200 // Load latest 200 messages
                ),
                agentService
                  .getExecutionStatus(conversationId, true, lastKnownTimeUs)
                  .catch((_err: unknown) => {
                    logger.warn(`[AgentV3] getExecutionStatus failed:`, _err);
                    return null;
                  }),
                // Restore context status indicator on conversation switch / page refresh
                (async () => {
                  const { useContextStore } = await import('../stores/contextStore');
                  await useContextStore.getState().fetchContextStatus(conversationId, projectId);
                })().catch((_err: unknown) => {
                  logger.warn(`[AgentV3] fetchContextStatus failed:`, _err);
                  return null;
                }),
                // Fetch plan mode status from API
                (async () => {
                  const { planService } = await import('../services/planService');
                  return planService.getMode(conversationId);
                })().catch((_err: unknown) => {
                  logger.debug(`[AgentV3] getMode failed:`, _err);
                  return null;
                }),
                // Fetch tasks for conversation
                (async () => {
                  const { httpClient } = await import('../services/client/httpClient');
                  const res = await httpClient.get<{ tasks?: AgentTask[] }>(`/agent/plan/tasks/${conversationId}`);
                  return res;
                })().catch((_err: unknown) => {
                  logger.debug(`[AgentV3] fetchTasks failed:`, _err);
                  return null;
                }),
              ]);

            // Update plan mode from API response
            if (planModeResult && planModeResult.mode) {
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

            if (get().activeConversationId !== conversationId) {
              logger.debug('Conversation changed during load, ignoring result');
              return;
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
            const sortedTimeline = [...response.timeline].sort((a, b) => {
              const timeDiff = a.eventTimeUs - (b.eventTimeUs ?? 0);
              if (timeDiff !== 0) return timeDiff;
              return a.eventCounter - b.eventCounter;
            });

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
              timeline: mergedTimeline,
              hasEarlier: response.has_more ?? false,
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
                if (!existing || (event.eventTimeUs ?? 0) >= (existing.eventTimeUs ?? 0)) {
                  eventMap.set(event.id, event);
                }
              }
              finalTimeline = Array.from(eventMap.values()).sort((a, b) => {
                const timeDiff = a.eventTimeUs - (b.eventTimeUs ?? 0);
                if (timeDiff !== 0) return timeDiff;
                return a.eventCounter - b.eventCounter;
              });
              finalMessages = timelineToMessages(finalTimeline);
            } else {
              finalTimeline = mergedTimeline;
              finalMessages = messages;
            }

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
              tls.setAgentHasEarlier(response.has_more ?? false);
              tls.setAgentEarliestPointers(firstTimeUs, firstCounter);
            }

            // Persist to IndexedDB
            saveConversationState(conversationId, newConvState).catch(console.error);

            // Replay canvas_updated events to rebuild canvas tabs from server history.
            // This supplements the Zustand persist (localStorage) approach so that
            // canvas state is also recoverable from the backend event store.
            replayCanvasEventsFromTimeline(mergedTimeline);

            // DEBUG: Log execution status for recovery debugging
            logger.debug(`[AgentV3] execStatus for ${conversationId}:`, {
              execStatus,
              is_running: execStatus?.is_running,
              lastKnownTimeUs,
              lastTimeUs,
            });

            // If agent is already running, recover streaming state before subscribing.
            // This avoids clearing freshly-arrived deltas after subscription.
            if ((execStatus as { is_running?: boolean })?.is_running) {
              logger.debug(
                `[AgentV3] Conversation ${conversationId} is running, recovering live stream...`
              );

              // CRITICAL: Clear any stale delta buffers before attaching to running session
              // This prevents duplicate content from previous page loads
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
              }

              // Bind timeline buffer deps for this conversation
              bindTimelineBufferDeps(conversationId, {
                getConversationState: get().getConversationState,
                updateConversationState: get().updateConversationState,
              });

              const streamHandler: AgentStreamHandler = createStreamEventHandlers(
                conversationId,
                undefined, // no additionalHandlers during recovery
                {
                  get: get as any,
                  set: set as any,
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
                }
              );

              const subscribeOpts: SubscribeOptions = {};
              const currentMsgId = (execStatus as { current_message_id?: string })?.current_message_id;
              if (typeof currentMsgId === 'string') {
                subscribeOpts.message_id = currentMsgId;
              }
              if (typeof execStatus?.last_event_time_us === 'number') {
                subscribeOpts.from_time_us = execStatus.last_event_time_us;
              } else if (typeof lastTimeUs === 'number') {
                subscribeOpts.from_time_us = lastTimeUs;
              }
              if (typeof execStatus?.last_event_counter === 'number') {
                subscribeOpts.from_counter = execStatus.last_event_counter;
              } else if (typeof response.last_counter === 'number') {
                subscribeOpts.from_counter = response.last_counter;
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

        loadEarlierMessages: async (conversationId, projectId) => {
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
              200, // Load 200 more messages (increased from 50)
              undefined, // fromTimeUs
              undefined, // fromCounter
              earliestTimeUs, // beforeTimeUs
              earliestCounter ?? undefined // beforeCounter
            );

            // Check if conversation is still active
            if (get().activeConversationId !== conversationId) {
              logger.debug(
                '[AgentV3] Conversation changed during load earlier messages, ignoring result'
              );
              return false;
            }

            // Prepend new events to existing timeline and sort by eventTimeUs + eventCounter
            const combinedTimeline = [...response.timeline, ...timeline];
            const sortedTimeline = combinedTimeline.sort((a: TimelineEvent, b: TimelineEvent) => {
              const timeDiff = a.eventTimeUs - (b.eventTimeUs ?? 0);
              if (timeDiff !== 0) return timeDiff;
              return a.eventCounter - b.eventCounter;
            });
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
              tlsWrite.setAgentHasEarlier(response.has_more ?? false);
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

        sendMessage: async (content, projectId, additionalHandlers) => {
          const { activeConversationId, getStreamingConversationCount } = get();
          const messages = useTimelineStore.getState().agentMessages;
          const timeline = useTimelineStore.getState().agentTimeline;

          // CRITICAL: Clear any stale delta buffers before starting new stream
          clearAllDeltaBuffers();
          clearAllTimelineBuffers();

          // Check concurrent streaming limit
          const streamingCount = getStreamingConversationCount();
          if (streamingCount >= MAX_CONCURRENT_STREAMING_CONVERSATIONS) {
            const concurrentErr = `Maximum ${String(MAX_CONCURRENT_STREAMING_CONVERSATIONS)} concurrent conversations reached. Please wait for one to complete.`;
            useStreamingStore.getState().setAgentError(concurrentErr);
            return null;
          }

          let conversationId = activeConversationId;
          let isNewConversation = false;

          if (!conversationId) {
            try {
              const newConv = await useConversationsStore.getState().createConversation(
                projectId,
                content.slice(0, 30) + '...'
              );
              conversationId = newConv.id;
              isNewConversation = true;
              resetCanvasForConversationScope();

              const newConvState = createDefaultConversationState();
              const newConvId = conversationId;

              set((state) => {
                const newStates = new Map(state.conversationStates);
                newStates.set(newConvId, newConvState);
                return {
                  activeConversationId: newConvId,
                  conversations: useConversationsStore.getState().conversations,
                  conversationStates: newStates,
                };
              });
            } catch (error) {
              const msg = error instanceof Error ? error.message : String(error);
              const createErr = `Failed to create conversation: ${msg}`;
              useStreamingStore.getState().setAgentError(createErr);
              return null;
            }
          }

          const userMsgId = uuidv4();
          const userMsg: Message = {
            id: userMsgId,
            conversation_id: conversationId,
            role: 'user',
            content,
            message_type: 'text',
            created_at: new Date().toISOString(),
          };

          // Create user message TimelineEvent and append to timeline
          const userMessageMetadata: Record<string, unknown> = {};
          if (additionalHandlers?.forcedSkillName) {
            userMessageMetadata.forcedSkillName = additionalHandlers.forcedSkillName;
          }
          if (additionalHandlers?.fileMetadata && additionalHandlers.fileMetadata.length > 0) {
            userMessageMetadata.fileMetadata = additionalHandlers.fileMetadata;
          }
          const userMessageEvent: UserMessageEvent = {
            id: userMsgId,
            type: 'user_message',
            eventTimeUs: Date.now() * 1000,
            eventCounter: 0,
            timestamp: Date.now(),
            content,
            role: 'user',
            ...(Object.keys(userMessageMetadata).length > 0 && { metadata: userMessageMetadata }),
          };

          // Update both global state and conversation-specific state
          const newTimeline = [...timeline, userMessageEvent];
          set((state) => {
            const newStates = new Map(state.conversationStates);
            const convState = newStates.get(conversationId) || createDefaultConversationState();
            newStates.set(conversationId, {
              ...convState,
              timeline: newTimeline,
              isStreaming: true,
              streamStatus: 'connecting',
              streamingAssistantContent: '',
              error: null,
              currentThought: '',
              streamingThought: '',
              isThinkingStreaming: false,
              activeToolCalls: new Map(),
              pendingToolsStack: [],
              agentState: 'thinking',
              suggestions: [],
            });

            return { conversationStates: newStates };
          });

          // Bridge sendMessage reset to sub-stores
          useTimelineStore.getState().setAgentTimeline(newTimeline);
          useTimelineStore.getState().setAgentMessages([...messages, userMsg]);
          useStreamingStore.getState().resetAgentStreaming();
          useStreamingStore.getState().setAgentIsStreaming(true);
          useStreamingStore.getState().setAgentStreamStatus('connecting');
          useExecutionStore.getState().resetAgentExecution();
          useExecutionStore.getState().setAgentExecutionState('thinking');
          useAgentHITLStore.getState().setSuggestions([]);

          // Capture conversationId in closure for event handler isolation
          // This is critical for multi-conversation support - events must only update
          // the conversation they belong to, not the currently active one
          const handlerConversationId = conversationId;

          bindTimelineBufferDeps(handlerConversationId, {
            getConversationState: get().getConversationState,
            updateConversationState: get().updateConversationState,
          });

          const handler: AgentStreamHandler = createStreamEventHandlers(
            handlerConversationId,
            additionalHandlers,
            {
              get: get as any,
              set: set as any,
              getDeltaBuffer,
              clearDeltaBuffers,
              clearAllDeltaBuffers,
              timelineToMessages,
              tokenBatchIntervalMs: TOKEN_BATCH_INTERVAL_MS,
              thoughtBatchIntervalMs: THOUGHT_BATCH_INTERVAL_MS,
              queueTimelineEvent: (event, stateUpdates) => {
                queueTimelineEventRaw(handlerConversationId, event, stateUpdates);
              },
              flushTimelineBufferSync: () => {
                flushTimelineBufferSyncRaw(handlerConversationId);
              },
            }
          );

          // For new conversations, return ID immediately and start stream in background
          // This allows the UI to navigate to the conversation URL right away
          if (isNewConversation) {
            // Get app model context from conversation state (SEP-1865)
            const convState = get().conversationStates.get(conversationId);
            const appCtx = convState?.appModelContext || undefined;

            agentService
              .chat(
                {
                  conversation_id: conversationId,
                  message: content,
                  project_id: projectId,
                  file_metadata: additionalHandlers?.fileMetadata,
                  forced_skill_name: additionalHandlers?.forcedSkillName,
                  app_model_context: appCtx ?? undefined,
                  image_attachments: additionalHandlers?.imageAttachments,
                  agent_id: additionalHandlers?.agentId,
                },
                handler
              )
              .catch(() => {
                const { updateConversationState } = get();
                updateConversationState(handlerConversationId, {
                  error: 'Failed to connect to chat stream',
                  isStreaming: false,
                  streamStatus: 'error',
                });
              });
            return conversationId;
          }

          // For existing conversations, wait for stream to complete
          try {
            // Get app model context from conversation state (SEP-1865)
            const convState2 = get().conversationStates.get(conversationId);
            const appCtx2 = convState2?.appModelContext || undefined;

            await agentService.chat(
              {
                conversation_id: conversationId,
                message: content,
                project_id: projectId,
                file_metadata: additionalHandlers?.fileMetadata,
                forced_skill_name: additionalHandlers?.forcedSkillName,
                app_model_context: appCtx2 ?? undefined,
                image_attachments: additionalHandlers?.imageAttachments,
                agent_id: additionalHandlers?.agentId,
              },
              handler
            );
            return conversationId;
          } catch (_e) {
            const { updateConversationState } = get();
            updateConversationState(handlerConversationId, {
              error: 'Failed to connect to chat stream',
              isStreaming: false,
              streamStatus: 'error',
            });
            return null;
          }
        },

        abortStream: (conversationId?: string) => {
          const targetConvId = conversationId || get().activeConversationId;
          if (targetConvId) {
            const stopSent = agentService.stopChat(targetConvId);

            if (!stopSent) {
              const { updateConversationState } = get();
              updateConversationState(targetConvId, {
                error: 'Failed to send stop request',
                isStreaming: false,
                streamStatus: 'error',
              });
              return;
            }

            // Clean up delta buffers to prevent stale timers from firing
            clearDeltaBuffers(targetConvId);

            const { updateConversationState } = get();
            updateConversationState(targetConvId, {
              isStreaming: false,
              streamStatus: 'idle',
              agentState: 'idle',
              streamingThought: '',
              isThinkingStreaming: false,
              streamingAssistantContent: '',
              pendingToolsStack: [],
            });
          }
        },

        ...createHITLActions({
          get: get as any,
          set: set as any,
          timelineToMessages,
          clearAllDeltaBuffers,
          getDeltaBuffer,
          clearDeltaBuffers,
          updateHITLEventInTimeline,
        }),

        /**
         * Load pending HITL (Human-In-The-Loop) requests for a conversation
         * This is used to restore dialog state after page refresh
         *
         * Shows dialogs for all pending requests. If Agent crashed/restarted,
         * the recovery service will handle it when Worker restarts.
         */
        loadPendingHITL: async (conversationId) => {
          await useAgentHITLStore.getState().loadPendingHITL(conversationId);
          const hs = useAgentHITLStore.getState();
          if (hs.pendingClarification || hs.pendingDecision || hs.pendingEnvVarRequest) {
            useExecutionStore.getState().setAgentExecutionState('awaiting_input');
          }
        },

        clearError: () => useStreamingStore.getState().setAgentError(null),

        togglePinEvent: (eventId: string) => {
          useAgentHITLStore.getState().togglePinEvent(eventId);
        },
    })
  )
);

// Initialize tab sync on module load
initTabSync();
