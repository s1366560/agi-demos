import { v4 as uuidv4 } from 'uuid';
import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

import { agentService } from '../services/agentService';
import {
  Message,
  AgentStreamHandler,
  TimelineEvent,
  UserMessageEvent,
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

import {
  TOKEN_BATCH_INTERVAL_MS,
  THOUGHT_BATCH_INTERVAL_MS,
  getDeltaBuffer,
  clearDeltaBuffers,
  clearAllDeltaBuffers,
  deleteDeltaBuffer,
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
import { replayCanvasEventsFromTimeline } from './agent/canvasReplay';
import { useCanvasStore } from './canvasStore';
import { useLayoutModeStore } from './layoutMode';

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
    persist(
      (set, get) => ({
        conversations: [],
        activeConversationId: null,
        hasMoreConversations: false,
        conversationsTotal: 0,

        // Per-conversation state map
        conversationStates: new Map<string, ConversationState>(),

        // Timeline: Primary data source (stores raw events from API and streaming)
        timeline: [],

        // Messages: Derived from timeline (for backward compatibility)
        messages: [],
        isLoadingHistory: false,
        isLoadingEarlier: false,
        hasEarlier: false,
        earliestTimeUs: null,
        earliestCounter: null,

        isStreaming: false,
        streamStatus: 'idle',
        error: null,
        streamingAssistantContent: '', // Real-time streaming content

        agentState: 'idle',
        currentThought: '',
        streamingThought: '',
        isThinkingStreaming: false,
        activeToolCalls: new Map(),
        pendingToolsStack: [],

        isPlanMode: false,

        showPlanPanel: false,
        showHistorySidebar: false,
        leftSidebarWidth: 280,
        rightPanelWidth: 400,

        pendingClarification: null,
        pendingDecision: null,
        pendingEnvVarRequest: null,
        pendingPermission: null,
        doomLoopDetected: null,
        costTracking: null,
        suggestions: [],
        pinnedEventIds: new Set(),

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

            // Also update global state if this is the active conversation
            const isActive = state.activeConversationId === conversationId;
            if (isActive) {
              return {
                conversationStates: newStates,
                // Sync to global state for backward compatibility
                ...(updates.timeline !== undefined && { timeline: updates.timeline }),
                ...(updates.isStreaming !== undefined && { isStreaming: updates.isStreaming }),
                ...(updates.streamStatus !== undefined && { streamStatus: updates.streamStatus }),
                ...(updates.streamingAssistantContent !== undefined && {
                  streamingAssistantContent: updates.streamingAssistantContent,
                }),
                ...(updates.error !== undefined && { error: updates.error }),
                ...(updates.agentState !== undefined && { agentState: updates.agentState }),
                ...(updates.currentThought !== undefined && {
                  currentThought: updates.currentThought,
                }),
                ...(updates.streamingThought !== undefined && {
                  streamingThought: updates.streamingThought,
                }),
                ...(updates.isThinkingStreaming !== undefined && {
                  isThinkingStreaming: updates.isThinkingStreaming,
                }),
                ...(updates.activeToolCalls !== undefined && {
                  activeToolCalls: updates.activeToolCalls,
                }),
                ...(updates.pendingToolsStack !== undefined && {
                  pendingToolsStack: updates.pendingToolsStack,
                }),
                ...(updates.isPlanMode !== undefined && { isPlanMode: updates.isPlanMode }),
                ...(updates.pendingClarification !== undefined && {
                  pendingClarification: updates.pendingClarification,
                }),
                ...(updates.pendingDecision !== undefined && {
                  pendingDecision: updates.pendingDecision,
                }),
                ...(updates.pendingEnvVarRequest !== undefined && {
                  pendingEnvVarRequest: updates.pendingEnvVarRequest,
                }),
                ...(updates.pendingPermission !== undefined && {
                  pendingPermission: updates.pendingPermission,
                }),
                ...(updates.doomLoopDetected !== undefined && {
                  doomLoopDetected: updates.doomLoopDetected,
                }),
                ...(updates.costTracking !== undefined && { costTracking: updates.costTracking }),
                ...(updates.suggestions !== undefined && { suggestions: updates.suggestions }),
                ...(updates.hasEarlier !== undefined && { hasEarlier: updates.hasEarlier }),
                ...(updates.earliestTimeUs !== undefined && {
                  earliestTimeUs: updates.earliestTimeUs,
                }),
                ...(updates.earliestCounter !== undefined && {
                  earliestCounter: updates.earliestCounter,
                }),
              };
            }

            return { conversationStates: newStates };
          });

          // Persist to IndexedDB (debounced with beforeunload flush support)
          const fullState = get().conversationStates.get(conversationId);
          if (fullState) {
            scheduleSave(conversationId, fullState);
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

          set({
            timeline: convState.timeline,
            messages: timelineToMessages(convState.timeline),
            hasEarlier: convState.hasEarlier,
            earliestTimeUs: convState.earliestTimeUs,
            earliestCounter: convState.earliestCounter,
            isStreaming: convState.isStreaming,
            streamStatus: convState.streamStatus,
            streamingAssistantContent: convState.streamingAssistantContent,
            error: convState.error,
            agentState: convState.agentState,
            currentThought: convState.currentThought,
            streamingThought: convState.streamingThought,
            isThinkingStreaming: convState.isThinkingStreaming,
            activeToolCalls: convState.activeToolCalls,
            pendingToolsStack: convState.pendingToolsStack,
            isPlanMode: convState.isPlanMode,
            pendingClarification: convState.pendingClarification,
            pendingDecision: convState.pendingDecision,
            pendingEnvVarRequest: convState.pendingEnvVarRequest,
            doomLoopDetected: convState.doomLoopDetected,
            suggestions: convState.suggestions,
          });
        },

        setActiveConversation: (id) => {
          const {
            activeConversationId,
            conversationStates,
            timeline,
            isStreaming,
            streamStatus,
            streamingAssistantContent,
            error,
            agentState,
            currentThought,
            streamingThought,
            isThinkingStreaming,
            activeToolCalls,
            pendingToolsStack,
            isPlanMode,
            pendingClarification,
            pendingDecision,
            pendingEnvVarRequest,
            doomLoopDetected,
            hasEarlier,
            earliestTimeUs,
            earliestCounter,
          } = get();

          // Skip if already on this conversation — avoids clearing delta buffers
          // and re-triggering state updates during active streaming.
          if (activeConversationId === id) return;

          // CRITICAL: Clear delta buffers when switching conversations
          // Prevents stale streaming content from previous conversation
          clearAllDeltaBuffers();
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
            newStates.set(activeConversationId, {
              ...currentState,
              timeline,
              hasEarlier,
              earliestTimeUs,
              earliestCounter,
              isStreaming,
              streamStatus,
              streamingAssistantContent,
              error,
              agentState,
              currentThought,
              streamingThought,
              isThinkingStreaming,
              activeToolCalls,
              pendingToolsStack,
              isPlanMode,
              pendingClarification,
              pendingDecision,
              pendingEnvVarRequest,
              doomLoopDetected,
              pendingHITLSummary: getHITLSummaryFromState({
                ...currentState,
                pendingClarification,
                pendingDecision,
                pendingEnvVarRequest,
              } as ConversationState),
            });
            set({ conversationStates: newStates });

            // Persist to IndexedDB
            saveConversationState(activeConversationId, newStates.get(activeConversationId)!).catch(
              console.error
            );
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
                const timeDiff = (a.eventTimeUs ?? 0) - (b.eventTimeUs ?? 0);
                if (timeDiff !== 0) return timeDiff;
                return (a.eventCounter ?? 0) - (b.eventCounter ?? 0);
              });
              set({
                activeConversationId: id,
                timeline: sortedTimeline,
                messages: timelineToMessages(sortedTimeline),
                hasEarlier: newState.hasEarlier,
                earliestTimeUs: newState.earliestTimeUs,
                earliestCounter: newState.earliestCounter,
                isStreaming: newState.isStreaming,
                streamStatus: newState.streamStatus,
                streamingAssistantContent: newState.streamingAssistantContent,
                error: newState.error,
                agentState: newState.agentState,
                currentThought: newState.currentThought,
                streamingThought: newState.streamingThought,
                isThinkingStreaming: newState.isThinkingStreaming,
                activeToolCalls: newState.activeToolCalls,
                pendingToolsStack: newState.pendingToolsStack,
                isPlanMode: newState.isPlanMode,
                pendingClarification: newState.pendingClarification,
                pendingDecision: newState.pendingDecision,
                pendingEnvVarRequest: newState.pendingEnvVarRequest,
                doomLoopDetected: newState.doomLoopDetected,
                pinnedEventIds: new Set(),
              });
              replayCanvasEventsFromTimeline(sortedTimeline);
              return;
            }
          }

          // Default state for new/unloaded conversation
          // IMPORTANT: Reset all streaming and state flags to prevent state leakage from previous conversation
          set({
            activeConversationId: id,
            timeline: [],
            messages: [],
            hasEarlier: false,
            earliestTimeUs: null,
            earliestCounter: null,
            isStreaming: false,
            streamStatus: 'idle',
            streamingAssistantContent: '',
            error: null,
            agentState: 'idle',
            currentThought: '',
            streamingThought: '',
            isThinkingStreaming: false,
            activeToolCalls: new Map(),
            pendingToolsStack: [],
            isPlanMode: false,
            pendingClarification: null,
            pendingDecision: null,
            pendingEnvVarRequest: null,
            doomLoopDetected: null,
            pinnedEventIds: new Set(),
          });
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
            const response = await agentService.listConversations(projectId);
            logger.debug(`[agentV3] Loaded ${response.items.length} conversations`);
            set({
              conversations: response.items,
              hasMoreConversations: response.has_more,
              conversationsTotal: response.total,
            });
          } catch (error) {
            console.error('[agentV3] Failed to list conversations', error);
          }
        },

        loadMoreConversations: async (projectId) => {
          const state = get();
          if (!state.hasMoreConversations) return;

          try {
            const offset = state.conversations.length;
            const response = await agentService.listConversations(projectId, undefined, 10, offset);
            logger.debug(`[agentV3] Loaded ${response.items.length} more conversations`);
            set({
              conversations: [...state.conversations, ...response.items],
              hasMoreConversations: response.has_more,
              conversationsTotal: response.total,
            });
          } catch (error) {
            console.error('[agentV3] Failed to load more conversations', error);
          }
        },

        deleteConversation: async (conversationId, projectId) => {
          try {
            await agentService.deleteConversation(conversationId, projectId);

            // Unsubscribe handler to prevent memory leaks
            agentService.unsubscribe(conversationId);

            // Clear delta buffers for this conversation
            clearDeltaBuffers(conversationId);
            deleteDeltaBuffer(conversationId);

            // Cancel any pending save for this conversation
            cancelPendingSave(conversationId);

            // Remove from LRU tracking
            removeFromAccessOrder(conversationId);

            // Remove from local state and conversation states map
            set((state) => {
              const newStates = new Map(state.conversationStates);
              newStates.delete(conversationId);

              return {
                conversations: state.conversations.filter((c) => c.id !== conversationId),
                conversationStates: newStates,
                // Clear active conversation if it was the deleted one
                activeConversationId:
                  state.activeConversationId === conversationId ? null : state.activeConversationId,
                // Clear messages and timeline if the deleted conversation was active
                messages: state.activeConversationId === conversationId ? [] : state.messages,
                timeline: state.activeConversationId === conversationId ? [] : state.timeline,
              };
            });

            // Remove from IndexedDB
            deleteConversationState(conversationId).catch(console.error);

            // Broadcast to other tabs
            tabSync.broadcastConversationDeleted(conversationId);
          } catch (error) {
            console.error('Failed to delete conversation', error);
            set({ error: 'Failed to delete conversation' });
          }
        },

        renameConversation: async (conversationId, projectId, title) => {
          try {
            const updatedConversation = await agentService.updateConversationTitle(
              conversationId,
              projectId,
              title
            );
            // Update in local state
            set((state) => ({
              conversations: state.conversations.map((c) =>
                c.id === conversationId ? updatedConversation : c
              ),
            }));

            // Broadcast to other tabs
            tabSync.broadcastConversationRenamed(conversationId, title);
          } catch (error) {
            console.error('Failed to rename conversation', error);
            set({ error: 'Failed to rename conversation' });
          }
        },

        createNewConversation: async (projectId) => {
          try {
            const newConv = await agentService.createConversation({
              project_id: projectId,
              title: 'New Conversation',
            });
            resetCanvasForConversationScope();

            // Create fresh state for new conversation
            const newConvState = createDefaultConversationState();

            // Add to conversations list and set as active
            touchConversation(newConv.id);
            set((state) => {
              const newStates = new Map(state.conversationStates);
              newStates.set(newConv.id, newConvState);

              return {
                conversations: [newConv, ...state.conversations],
                conversationStates: newStates,
                activeConversationId: newConv.id,
                // Clear messages and timeline for new conversation
                messages: [],
                timeline: [],
                currentThought: '',
                streamingThought: '',
                isThinkingStreaming: false,
                isPlanMode: false,
                agentState: 'idle',
                isStreaming: false,
                error: null,
                pendingClarification: null,
                pendingDecision: null,
                pendingEnvVarRequest: null,
              };
            });
            return newConv.id;
          } catch (error) {
            console.error('Failed to create conversation', error);
            set({ error: 'Failed to create conversation' });
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
            `[AgentV3] loadMessages starting for ${conversationId}, lastKnownTimeUs=${lastKnownTimeUs}`
          );

          // Try to load from IndexedDB first
          const cachedState = await loadConversationState(conversationId);

          // Only replace timeline/messages if current state is empty —
          // setActiveConversation already restores from in-memory cache,
          // so overwriting with IndexedDB data causes a visible flash.
          const currentTimeline = get().timeline;
          const hasExistingData = currentTimeline.length > 0;

          const stateUpdate: Record<string, any> = {
            // Only show loading state when there's no cached data to display —
            // when data exists, keep UI interactive during background refresh.
            isLoadingHistory: !hasExistingData,
            currentThought: cachedState?.currentThought || '',
            streamingThought: '',
            isThinkingStreaming: false,
            isPlanMode: cachedState?.isPlanMode || false,
            agentState: cachedState?.agentState || 'idle',
            hasEarlier: cachedState?.hasEarlier || false,
            earliestTimeUs: cachedState?.earliestTimeUs || null,
            earliestCounter: cachedState?.earliestCounter || null,
            // Restore HITL state if any
            pendingClarification: cachedState?.pendingClarification || null,
            pendingDecision: cachedState?.pendingDecision || null,
            pendingEnvVarRequest: cachedState?.pendingEnvVarRequest || null,
          };

          if (!hasExistingData) {
            stateUpdate.timeline = cachedState?.timeline || [];
            stateUpdate.messages = cachedState?.timeline
              ? timelineToMessages(cachedState.timeline)
              : [];
          }

          set(stateUpdate);

          try {
            // Parallelize independent API calls (async-parallel)
            // Include recovery info in execution status check
            const [response, execStatus, _contextStatusResult, planModeResult, taskListResult] =
              await Promise.all([
                agentService.getConversationMessages(
                  conversationId,
                  projectId,
                  200 // Load latest 200 messages
                ) as Promise<any>,
                agentService
                  .getExecutionStatus(conversationId, true, lastKnownTimeUs)
                  .catch((e) => {
                    logger.warn(`[AgentV3] getExecutionStatus failed:`, e);
                    return null;
                  }),
                // Restore context status indicator on conversation switch / page refresh
                (async () => {
                  const { useContextStore } = await import('../stores/contextStore');
                  await useContextStore.getState().fetchContextStatus(conversationId, projectId);
                })().catch((e) => {
                  logger.warn(`[AgentV3] fetchContextStatus failed:`, e);
                  return null;
                }),
                // Fetch plan mode status from API
                (async () => {
                  const { planService } = await import('../services/planService');
                  return planService.getMode(conversationId);
                })().catch((e) => {
                  logger.debug(`[AgentV3] getMode failed:`, e);
                  return null;
                }),
                // Fetch tasks for conversation
                (async () => {
                  const { httpClient } = await import('../services/client/httpClient');
                  const res = await httpClient.get(`/agent/plan/tasks/${conversationId}`);
                  return res as any;
                })().catch((e) => {
                  logger.debug(`[AgentV3] fetchTasks failed:`, e);
                  return null;
                }),
              ]);

            // Update plan mode from API response
            if (planModeResult && planModeResult.mode) {
              const isPlan = planModeResult.mode === 'plan';
              set({ isPlanMode: isPlan });
              get().updateConversationState(conversationId, { isPlanMode: isPlan });
            }

            // Update tasks from API response
            if (taskListResult && Array.isArray(taskListResult.tasks)) {
              get().updateConversationState(conversationId, { tasks: taskListResult.tasks });
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
                  `[AgentV3] Timeline out of order! timeUs=${event.eventTimeUs},counter=${event.eventCounter} <= prev timeUs=${prevTimeUs},counter=${prevCounter}`,
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
              const timeDiff = (a.eventTimeUs ?? 0) - (b.eventTimeUs ?? 0);
              if (timeDiff !== 0) return timeDiff;
              return (a.eventCounter ?? 0) - (b.eventCounter ?? 0);
            });

            // Merge HITL response events into request events for single-card rendering
            const mergedTimeline = mergeHITLResponseEvents(sortedTimeline);

            // Store the raw timeline and derive messages (no merging)
            const messages = timelineToMessages(mergedTimeline);
            const firstTimeUs = response.first_time_us ?? null;
            const firstCounter = response.first_counter ?? null;
            const lastTimeUs = response.last_time_us ?? null;

            // DEBUG: Log assistant_message events
            const assistantMsgs = mergedTimeline.filter((e: any) => e.type === 'assistant_message');
            logger.debug(
              `[AgentV3] loadMessages: Found ${assistantMsgs.length} assistant_message events`,
              assistantMsgs
            );

            // DEBUG: Log artifact events in timeline
            const artifactEvents = mergedTimeline.filter((e: any) => e.type === 'artifact_created');
            logger.debug(
              `[AgentV3] loadMessages: Found ${artifactEvents.length} artifact_created events in timeline`,
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

            set((state) => {
              const newStates = new Map(state.conversationStates);
              const currentConvState =
                newStates.get(conversationId) || createDefaultConversationState();
              newStates.set(conversationId, {
                ...currentConvState,
                ...newConvState,
              } as ConversationState);

              // FIX: Use incremental merge during streaming to preserve local events
              // while still incorporating server events.
              // Previously, we completely skipped timeline updates when streaming,
              // which caused events to be invisible.
              // IMPORTANT: Only merge when loading the SAME conversation that's active and streaming.
              // If loading a different conversation, use the API response directly.
              const isCurrentlyStreaming = state.isStreaming;
              const isActiveConversation = state.activeConversationId === conversationId;

              let finalTimeline: TimelineEvent[];
              let finalMessages: Message[];

              if (isCurrentlyStreaming && isActiveConversation && state.timeline.length > 0) {
                // During streaming of active conversation: merge API events with local events
                // Use a Map keyed by event ID for deduplication
                const eventMap = new Map<string, TimelineEvent>();

                // First, add all API events
                for (const event of mergedTimeline) {
                  eventMap.set(event.id, event);
                }

                // Then, add local events (they may override API events with same ID,
                // or add new events that haven't been persisted yet)
                for (const event of state.timeline) {
                  // Only add local event if it's newer than what's in the map
                  // or if it's not in the map at all
                  const existing = eventMap.get(event.id);
                  if (!existing || (event.eventTimeUs ?? 0) >= (existing.eventTimeUs ?? 0)) {
                    eventMap.set(event.id, event);
                  }
                }

                // Convert back to array and sort by eventTimeUs + eventCounter
                finalTimeline = Array.from(eventMap.values()).sort((a, b) => {
                  const timeDiff = (a.eventTimeUs ?? 0) - (b.eventTimeUs ?? 0);
                  if (timeDiff !== 0) return timeDiff;
                  return (a.eventCounter ?? 0) - (b.eventCounter ?? 0);
                });
                finalMessages = timelineToMessages(finalTimeline);
              } else {
                // Not streaming, different conversation, or empty local timeline: use API response directly
                finalTimeline = mergedTimeline;
                finalMessages = messages;
              }

              // Check if timeline actually changed to avoid unnecessary re-renders
              const timelineChanged =
                state.timeline.length !== finalTimeline.length ||
                (finalTimeline.length > 0 &&
                  state.timeline[state.timeline.length - 1]?.id !==
                    finalTimeline[finalTimeline.length - 1]?.id);

              return {
                conversationStates: newStates,
                ...(timelineChanged ? { timeline: finalTimeline, messages: finalMessages } : {}),
                isLoadingHistory: false,
                hasEarlier: response.has_more ?? false,
                earliestTimeUs: firstTimeUs,
                earliestCounter: firstCounter,
              };
            });

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
            if (execStatus?.is_running) {
              logger.debug(
                `[AgentV3] Conversation ${conversationId} is running, recovering live stream...`
              );

              // CRITICAL: Clear any stale delta buffers before attaching to running session
              // This prevents duplicate content from previous page loads
              clearAllDeltaBuffers();

              set({ isStreaming: true, agentState: 'thinking' });
            }

            // Always subscribe active conversation to WebSocket so externally-triggered
            // executions (e.g. channel ingress) can stream into the workspace in real time.
            if (get().activeConversationId === conversationId) {
              if (!agentService.isConnected()) {
                logger.debug(`[AgentV3] Connecting WebSocket...`);
                await agentService.connect();
              }

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
                }
              );

              agentService.subscribe(conversationId, streamHandler);
              logger.debug(`[AgentV3] Subscribed to conversation ${conversationId}`);
            }
          } catch (error) {
            if (get().activeConversationId !== conversationId) return;
            console.error('Failed to load messages', error);
            set({ isLoadingHistory: false });
          }
        },

        loadEarlierMessages: async (conversationId, projectId) => {
          const {
            earliestTimeUs,
            earliestCounter,
            timeline,
            isLoadingEarlier,
            activeConversationId,
          } = get();

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
          set({ isLoadingEarlier: true });

          try {
            const response = (await agentService.getConversationMessages(
              conversationId,
              projectId,
              200, // Load 200 more messages (increased from 50)
              undefined, // fromTimeUs
              undefined, // fromCounter
              earliestTimeUs, // beforeTimeUs
              earliestCounter ?? undefined // beforeCounter
            )) as any;

            // Check if conversation is still active
            if (get().activeConversationId !== conversationId) {
              logger.debug(
                '[AgentV3] Conversation changed during load earlier messages, ignoring result'
              );
              return false;
            }

            // Prepend new events to existing timeline and sort by eventTimeUs + eventCounter
            const combinedTimeline = [...response.timeline, ...timeline];
            const sortedTimeline = combinedTimeline.sort((a: any, b: any) => {
              const timeDiff = (a.eventTimeUs ?? 0) - (b.eventTimeUs ?? 0);
              if (timeDiff !== 0) return timeDiff;
              return (a.eventCounter ?? 0) - (b.eventCounter ?? 0);
            });
            // Merge HITL response events into request events for single-card rendering
            const mergedTimeline = mergeHITLResponseEvents(sortedTimeline);
            const newMessages = timelineToMessages(mergedTimeline);
            const newFirstTimeUs = response.first_time_us ?? null;
            const newFirstCounter = response.first_counter ?? null;

            set({
              timeline: mergedTimeline,
              messages: newMessages,
              isLoadingEarlier: false,
              hasEarlier: response.has_more ?? false,
              earliestTimeUs: newFirstTimeUs,
              earliestCounter: newFirstCounter,
            });

            logger.debug(
              '[AgentV3] Loaded earlier messages, total timeline length:',
              mergedTimeline.length
            );
            return true;
          } catch (error) {
            console.error('[AgentV3] Failed to load earlier messages:', error);
            set({ isLoadingEarlier: false });
            return false;
          }
        },

        sendMessage: async (content, projectId, additionalHandlers) => {
          const { activeConversationId, messages, timeline, getStreamingConversationCount } = get();

          // CRITICAL: Clear any stale delta buffers before starting new stream
          // This prevents duplicate content from previous sessions being flushed
          clearAllDeltaBuffers();

          // Check concurrent streaming limit
          const streamingCount = getStreamingConversationCount();
          if (streamingCount >= MAX_CONCURRENT_STREAMING_CONVERSATIONS) {
            set({
              error: `Maximum ${MAX_CONCURRENT_STREAMING_CONVERSATIONS} concurrent conversations reached. Please wait for one to complete.`,
            });
            return null;
          }

          let conversationId = activeConversationId;
          let isNewConversation = false;

          if (!conversationId) {
            try {
              const newConv = await agentService.createConversation({
                project_id: projectId,
                title: content.slice(0, 30) + '...',
              });
              conversationId = newConv.id;
              isNewConversation = true;
              resetCanvasForConversationScope();

              // Create fresh state for new conversation
              const newConvState = createDefaultConversationState();

              set((state) => {
                const newStates = new Map(state.conversationStates);
                newStates.set(conversationId!, newConvState);
                return {
                  activeConversationId: conversationId,
                  conversations: [newConv, ...state.conversations],
                  conversationStates: newStates,
                };
              });
            } catch (error) {
              const msg = error instanceof Error ? error.message : String(error);
              set({ error: `Failed to create conversation: ${msg}` });
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

            return {
              conversationStates: newStates,
              messages: [...messages, userMsg],
              timeline: newTimeline,
              isStreaming: true,
              streamStatus: 'connecting',
              streamingAssistantContent: '', // Reset streaming content
              error: null,
              currentThought: '',
              streamingThought: '',
              isThinkingStreaming: false,
              activeToolCalls: new Map(),
              pendingToolsStack: [],
              agentState: 'thinking',
              suggestions: [],
            };
          });

          // Capture conversationId in closure for event handler isolation
          // This is critical for multi-conversation support - events must only update
          // the conversation they belong to, not the currently active one
          const handlerConversationId = conversationId;

          // Define handler first (needed for both new and existing conversations)
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
                set({
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
            set({
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
              const { updateConversationState, activeConversationId } = get();
              updateConversationState(targetConvId, {
                error: 'Failed to send stop request',
                isStreaming: false,
                streamStatus: 'error',
              });
              if (targetConvId === activeConversationId) {
                set({
                  error: 'Failed to send stop request',
                  isStreaming: false,
                  streamStatus: 'error',
                });
              }
              return;
            }

            // Clean up delta buffers to prevent stale timers from firing
            clearDeltaBuffers(targetConvId);

            // Update conversation-specific state
            const { updateConversationState, activeConversationId } = get();
            updateConversationState(targetConvId, {
              isStreaming: false,
              streamStatus: 'idle',
              agentState: 'idle',
              streamingThought: '',
              isThinkingStreaming: false,
              streamingAssistantContent: '',
              pendingToolsStack: [],
            });

            // Also update global state if this is active conversation
            if (targetConvId === activeConversationId) {
              set({
                isStreaming: false,
                streamStatus: 'idle',
                agentState: 'idle',
                streamingThought: '',
                isThinkingStreaming: false,
                streamingAssistantContent: '',
                pendingToolsStack: [],
              });
            }
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
          logger.debug('[agentV3] Loading pending HITL requests for conversation:', conversationId);
          try {
            const response = await agentService.getPendingHITLRequests(conversationId);
            logger.debug('[agentV3] Pending HITL response:', response);

            if (response.requests.length === 0) {
              logger.debug('[agentV3] No pending HITL requests');
              return;
            }

            // Process each pending request and restore dialog state
            for (const request of response.requests) {
              logger.debug(
                '[agentV3] Restoring pending HITL request:',
                request.request_type,
                request.id
              );

              switch (request.request_type) {
                case 'clarification':
                  set({
                    pendingClarification: {
                      request_id: request.id,
                      question: request.question,
                      clarification_type: request.metadata?.clarification_type || 'custom',
                      options: request.options || [],
                      allow_custom: request.metadata?.allow_custom ?? true,
                      context: request.context || {},
                    },
                    agentState: 'awaiting_input',
                  });
                  break;

                case 'decision':
                  set({
                    pendingDecision: {
                      request_id: request.id,
                      question: request.question,
                      decision_type: request.metadata?.decision_type || 'custom',
                      options: request.options || [],
                      allow_custom: request.metadata?.allow_custom ?? true,
                      context: request.context || {},
                    },
                    agentState: 'awaiting_input',
                  });
                  break;

                case 'env_var': {
                  // Use new format directly: name, label, required
                  // Data comes from request.options (stored in DB)
                  const fields = request.options || [];

                  set({
                    pendingEnvVarRequest: {
                      request_id: request.id,
                      tool_name: request.metadata?.tool_name || 'unknown',
                      fields: fields,
                      message: request.question,
                      context: request.context || {},
                    },
                    agentState: 'awaiting_input',
                  });
                  break;
                }
              }

              // Only restore the first pending request
              // (user should answer one at a time)
              break;
            }
          } catch (error) {
            console.error('[agentV3] Failed to load pending HITL requests:', error);
            // Don't throw - this is a recovery mechanism, not critical
          }
        },

        togglePlanPanel: () => set((state) => ({ showPlanPanel: !state.showPlanPanel })),
        toggleHistorySidebar: () =>
          set((state) => ({ showHistorySidebar: !state.showHistorySidebar })),

        setLeftSidebarWidth: (width: number) => set({ leftSidebarWidth: width }),
        setRightPanelWidth: (width: number) => set({ rightPanelWidth: width }),

        clearError: () => set({ error: null }),

        togglePinEvent: (eventId: string) => {
          const { pinnedEventIds } = get();
          const next = new Set(pinnedEventIds);
          if (next.has(eventId)) {
            next.delete(eventId);
          } else {
            next.add(eventId);
          }
          set({ pinnedEventIds: next });
        },
      }),
      {
        name: 'agent-v3-storage',
        partialize: (state) => ({
          // Only persist UI preferences, not conversation/message data
          showHistorySidebar: state.showHistorySidebar,
          leftSidebarWidth: state.leftSidebarWidth,
          rightPanelWidth: state.rightPanelWidth,
        }),
      }
    )
  )
);

// Initialize tab sync on module load
initTabSync();

// Selector for messages (backward compatible with timeline-based rendering)
export const useMessages = () =>
  useAgentV3Store((state) => state.messages);
