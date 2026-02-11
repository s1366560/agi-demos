import { v4 as uuidv4 } from 'uuid';
import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

import { agentService } from '../services/agentService';
import { planService } from '../services/planService';
import {
  Message,
  WorkPlan,
  Conversation,
  AgentStreamHandler,
  ToolCall,
  TimelineEvent,
  AgentEvent,
  ActEventData,
  ObserveEventData,
  UserMessageEvent,
  ExecutionPlan,
  PermissionAskedEventData,
  DoomLoopDetectedEventData,
} from '../types/agent';
import {
  type ConversationState,
  type HITLSummary,
  type CostTrackingState,
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
import { tabSync, type TabSyncMessage } from '../utils/tabSync';


import { createHITLActions } from './agent/hitlActions';
import { createStreamEventHandlers } from './agent/streamEventHandlers';

import type { FileMetadata } from '../services/sandboxUploadService';

/**
 * Token delta batching configuration
 * Batches rapid token updates to reduce re-renders and improve performance
 */
const TOKEN_BATCH_INTERVAL_MS = 50; // Batch tokens every 50ms for smooth streaming
const THOUGHT_BATCH_INTERVAL_MS = 50; // Same for thought deltas

/**
 * Maximum number of conversation states to keep in memory.
 * When exceeded, the least-recently-accessed non-active, non-streaming
 * conversations are evicted to prevent unbounded memory growth.
 * Evicted conversations can be re-loaded from server on demand.
 */
const MAX_CACHED_CONVERSATIONS = 10;

/**
 * Per-conversation delta buffer state
 * Using Map to isolate buffers per conversation, preventing cross-conversation contamination
 */
interface DeltaBufferState {
  textDeltaBuffer: string;
  textDeltaFlushTimer: ReturnType<typeof setTimeout> | null;
  thoughtDeltaBuffer: string;
  thoughtDeltaFlushTimer: ReturnType<typeof setTimeout> | null;
  actDeltaBuffer: import('../types/agent').ActDeltaEventData | null;
  actDeltaFlushTimer: ReturnType<typeof setTimeout> | null;
}

const deltaBuffers = new Map<string, DeltaBufferState>();

/**
 * Get or create delta buffer state for a conversation
 */
function getDeltaBuffer(conversationId: string): DeltaBufferState {
  let buffer = deltaBuffers.get(conversationId);
  if (!buffer) {
    buffer = {
      textDeltaBuffer: '',
      textDeltaFlushTimer: null,
      thoughtDeltaBuffer: '',
      thoughtDeltaFlushTimer: null,
      actDeltaBuffer: null,
      actDeltaFlushTimer: null,
    };
    deltaBuffers.set(conversationId, buffer);
  }
  return buffer;
}

/**
 * Clear delta buffers for a specific conversation
 * IMPORTANT: Call this before starting any new streaming session to prevent
 * stale buffer content from being flushed into the new session
 */
function clearDeltaBuffers(conversationId: string): void {
  const buffer = deltaBuffers.get(conversationId);
  if (buffer) {
    if (buffer.textDeltaFlushTimer) {
      clearTimeout(buffer.textDeltaFlushTimer);
      buffer.textDeltaFlushTimer = null;
    }
    if (buffer.thoughtDeltaFlushTimer) {
      clearTimeout(buffer.thoughtDeltaFlushTimer);
      buffer.thoughtDeltaFlushTimer = null;
    }
    if (buffer.actDeltaFlushTimer) {
      clearTimeout(buffer.actDeltaFlushTimer);
      buffer.actDeltaFlushTimer = null;
    }
    buffer.textDeltaBuffer = '';
    buffer.thoughtDeltaBuffer = '';
    buffer.actDeltaBuffer = null;
  }
}

/**
 * Clear all delta buffers across all conversations
 * Used when switching conversations or on cleanup
 */
function clearAllDeltaBuffers(): void {
  deltaBuffers.forEach((_buffer, conversationId) => {
    clearDeltaBuffers(conversationId);
  });
  deltaBuffers.clear();
}

/**
 * Pending save state for beforeunload flush
 */
const pendingSaves = new Map<string, NodeJS.Timeout>();
const SAVE_DEBOUNCE_MS = 500;

/**
 * LRU access order tracking for conversation state cache eviction.
 * Most recently accessed conversation ID is at the end.
 */
const conversationAccessOrder: string[] = [];

/**
 * Record a conversation as recently accessed (move to end of LRU list)
 */
function touchConversation(conversationId: string): void {
  const idx = conversationAccessOrder.indexOf(conversationId);
  if (idx !== -1) {
    conversationAccessOrder.splice(idx, 1);
  }
  conversationAccessOrder.push(conversationId);
}

/**
 * Evict least-recently-used conversation states when cache exceeds limit.
 * Skips the active conversation and any currently streaming conversations.
 * Evicted conversations are persisted to IndexedDB before removal.
 */
function evictStaleConversationStates(
  states: Map<string, ConversationState>,
  activeId: string | null
): Map<string, ConversationState> {
  if (states.size <= MAX_CACHED_CONVERSATIONS) {
    return states;
  }

  const newStates = new Map(states);
  const evictCount = newStates.size - MAX_CACHED_CONVERSATIONS;
  let evicted = 0;

  // Walk LRU list from oldest (front) to newest
  for (let i = 0; i < conversationAccessOrder.length && evicted < evictCount; i++) {
    const id = conversationAccessOrder[i];
    if (id === activeId) continue;
    const convState = newStates.get(id);
    if (convState?.isStreaming) continue;

    // Persist to IndexedDB before eviction
    saveConversationState(id, convState!).catch(console.error);
    newStates.delete(id);
    conversationAccessOrder.splice(i, 1);
    i--;
    evicted++;
  }

  return newStates;
}

/**
 * Schedule a debounced save for a conversation
 */
function scheduleSave(conversationId: string, state: ConversationState): void {
  // Clear existing timer
  const existingTimer = pendingSaves.get(conversationId);
  if (existingTimer) {
    clearTimeout(existingTimer);
  }

  // Schedule new save
  const timer = setTimeout(() => {
    saveConversationState(conversationId, state).catch(console.error);
    pendingSaves.delete(conversationId);
  }, SAVE_DEBOUNCE_MS);

  pendingSaves.set(conversationId, timer);
}

/**
 * Flush all pending saves immediately (for beforeunload)
 */
async function flushPendingSaves(): Promise<void> {
  // Clear all timers
  pendingSaves.forEach((timer) => clearTimeout(timer));
  pendingSaves.clear();

  // Get current store state and save all conversation states
  const state = useAgentV3Store.getState();
  const savePromises: Promise<void>[] = [];

  state.conversationStates.forEach((convState, conversationId) => {
    savePromises.push(saveConversationState(conversationId, convState).catch(console.error));
  });

  await Promise.all(savePromises);
}

// Register beforeunload handler for reliable persistence
if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', () => {
    // Use synchronous approach for beforeunload
    // Note: IndexedDB operations may not complete, but we try our best
    flushPendingSaves();
  });

  // Also handle visibilitychange for mobile browsers
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      flushPendingSaves();
    }
  });
}

/**
 * Additional handlers that can be injected into sendMessage
 * for external integrations (e.g., sandbox tool detection)
 */
export interface AdditionalAgentHandlers {
  onAct?: (event: AgentEvent<ActEventData>) => void;
  onObserve?: (event: AgentEvent<ObserveEventData>) => void;
  /** File metadata for files uploaded to sandbox */
  fileMetadata?: FileMetadata[];
  /** Force execution of a specific skill by name */
  forcedSkillName?: string;
}

/**
 * Update HITL event in timeline when user responds
 * Finds the matching event by requestId and updates its answered state
 *
 * @param timeline - Current timeline array
 * @param requestId - The HITL request ID to find
 * @param eventType - Type of HITL event to match
 * @param updates - Fields to update (answered, answer/decision/values)
 * @returns Updated timeline with the HITL event marked as answered
 */
function updateHITLEventInTimeline(
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
): TimelineEvent[] {
  return timeline.map((event) => {
    if (event.type === eventType && (event as any).requestId === requestId) {
      return { ...event, ...updates };
    }
    return event;
  });
}

/**
 * Merge HITL response events (_answered/_provided/_replied/_granted) into their
 * corresponding request events (_asked/_requested) so only one card renders.
 *
 * For each response event, find the matching request event by requestId,
 * mark it as answered with the response value, then remove the response event.
 */
function mergeHITLResponseEvents(timeline: TimelineEvent[]): TimelineEvent[] {
  // Map from response type to { requestType, field to copy }
  const responseTypeMap: Record<
    string,
    { requestType: string; mapFn: (resp: any) => Record<string, unknown> }
  > = {
    clarification_answered: {
      requestType: 'clarification_asked',
      mapFn: (r) => ({ answered: true, answer: r.answer }),
    },
    decision_answered: {
      requestType: 'decision_asked',
      mapFn: (r) => ({ answered: true, decision: r.decision }),
    },
    env_var_provided: {
      requestType: 'env_var_requested',
      mapFn: (r) => ({ answered: true, variableNames: r.variableNames, values: r.values }),
    },
    permission_replied: {
      requestType: 'permission_asked',
      mapFn: (r) => ({ answered: true, granted: r.granted }),
    },
    permission_granted: {
      requestType: 'permission_asked',
      mapFn: (r) => ({ answered: true, granted: r.granted !== undefined ? r.granted : true }),
    },
  };

  // Collect response events keyed by requestId
  const responsesByRequestId = new Map<string, Record<string, unknown>>();
  const responseEventIds = new Set<string>();

  for (const event of timeline) {
    const mapping = responseTypeMap[event.type];
    if (mapping) {
      const requestId = (event as any).requestId;
      if (requestId) {
        responsesByRequestId.set(requestId, mapping.mapFn(event));
        responseEventIds.add(event.id);
      }
    }
  }

  if (responsesByRequestId.size === 0) return timeline;

  // Merge into request events and filter out response events
  return timeline
    .map((event) => {
      const requestId = (event as any).requestId;
      if (requestId && responsesByRequestId.has(requestId)) {
        const requestTypes = [
          'clarification_asked',
          'decision_asked',
          'env_var_requested',
          'permission_asked',
        ];
        if (requestTypes.includes(event.type)) {
          return { ...event, ...responsesByRequestId.get(requestId) };
        }
      }
      return event;
    })
    .filter((event) => !responseEventIds.has(event.id));
}

/**
 * Convert TimelineEvent[] to Message[] - Simple 1:1 conversion without merging
 * Each timeline event maps directly to a message for natural ordering
 */
function timelineToMessages(timeline: TimelineEvent[]): Message[] {
  const messages: Message[] = [];

  for (const event of timeline) {
    switch (event.type) {
      case 'user_message':
        messages.push({
          id: event.id,
          conversation_id: '',
          role: 'user',
          content: (event as any).content || '',
          message_type: 'text' as const,
          created_at: new Date(event.timestamp).toISOString(),
        });
        break;

      case 'assistant_message':
        messages.push({
          id: event.id,
          conversation_id: '',
          role: 'assistant',
          content: (event as any).content || '',
          message_type: 'text' as const,
          created_at: new Date(event.timestamp).toISOString(),
        });
        break;

      // Other event types are rendered directly from timeline, not as messages
      default:
        break;
    }
  }

  return messages;
}

interface AgentV3State {
  // Conversation State
  conversations: Conversation[];
  activeConversationId: string | null;
  hasMoreConversations: boolean;
  conversationsTotal: number;

  // Per-conversation state (isolated for multi-conversation support)
  conversationStates: Map<string, ConversationState>;

  // Timeline State (for active conversation - backward compatibility)
  timeline: TimelineEvent[];

  // Messages State (Derived from timeline for backward compatibility)
  messages: Message[];
  isLoadingHistory: boolean; // For initial message load (shows loading in sidebar)
  isLoadingEarlier: boolean; // For pagination (does NOT show loading in sidebar)
  hasEarlier: boolean; // Whether there are earlier messages to load
  earliestTimeUs: number | null; // For pagination
  earliestCounter: number | null; // For pagination

  // Stream State (for active conversation - backward compatibility)
  isStreaming: boolean;
  streamStatus: 'idle' | 'connecting' | 'streaming' | 'error';
  error: string | null;
  streamingAssistantContent: string; // Streaming content (used for real-time display)

  // Agent Execution State (for active conversation - backward compatibility)
  agentState:
    | 'idle'
    | 'thinking'
    | 'preparing'
    | 'acting'
    | 'observing'
    | 'awaiting_input'
    | 'retrying';
  currentThought: string;
  streamingThought: string; // For streaming thought_delta content
  isThinkingStreaming: boolean; // Whether thought is currently streaming
  activeToolCalls: Map<
    string,
    ToolCall & {
      status: 'preparing' | 'running' | 'success' | 'failed';
      startTime: number;
      partialArguments?: string;
    }
  >;
  pendingToolsStack: string[]; // Track order of tool executions

  // Plan State (for active conversation - backward compatibility)
  workPlan: WorkPlan | null;
  isPlanMode: boolean;
  executionPlan: ExecutionPlan | null;

  // UI State
  showPlanPanel: boolean;
  showHistorySidebar: boolean;
  leftSidebarWidth: number;
  rightPanelWidth: number;

  // Interactivity (for active conversation - backward compatibility)
  pendingClarification: any; // Pending clarification request from agent
  pendingDecision: any; // Using any for brevity in this update
  pendingEnvVarRequest: any; // Pending environment variable request from agent
  pendingPermission: PermissionAskedEventData | null; // Pending permission request
  doomLoopDetected: DoomLoopDetectedEventData | null;
  costTracking: CostTrackingState | null; // Cost tracking state
  suggestions: string[]; // Follow-up suggestions from agent
  pinnedEventIds: Set<string>; // Pinned message event IDs (per-conversation, local only)

  // Multi-conversation state helpers
  getConversationState: (conversationId: string) => ConversationState;
  updateConversationState: (conversationId: string, updates: Partial<ConversationState>) => void;
  getStreamingConversationCount: () => number;
  getConversationsWithPendingHITL: () => Array<{ conversationId: string; summary: HITLSummary }>;
  syncActiveConversationState: () => void;

  // Actions
  setActiveConversation: (id: string | null) => void;
  loadConversations: (projectId: string) => Promise<void>;
  loadMoreConversations: (projectId: string) => Promise<void>;
  loadMessages: (conversationId: string, projectId: string) => Promise<void>;
  loadEarlierMessages: (conversationId: string, projectId: string) => Promise<boolean>;
  createNewConversation: (projectId: string) => Promise<string | null>;
  sendMessage: (
    content: string,
    projectId: string,
    additionalHandlers?: AdditionalAgentHandlers
  ) => Promise<string | null>;
  deleteConversation: (conversationId: string, projectId: string) => Promise<void>;
  renameConversation: (conversationId: string, projectId: string, title: string) => Promise<void>;
  abortStream: (conversationId?: string) => void;
  togglePlanPanel: () => void;
  toggleHistorySidebar: () => void;
  setLeftSidebarWidth: (width: number) => void;
  setRightPanelWidth: (width: number) => void;
  respondToClarification: (requestId: string, answer: string) => Promise<void>;
  respondToDecision: (requestId: string, decision: string) => Promise<void>;
  respondToEnvVar: (requestId: string, values: Record<string, string>) => Promise<void>;
  respondToPermission: (requestId: string, granted: boolean) => Promise<void>;
  loadPendingHITL: (conversationId: string) => Promise<void>;
  togglePlanMode: () => Promise<void>;
  clearError: () => void;
  togglePinEvent: (eventId: string) => void;
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

        workPlan: null,
        isPlanMode: false,
        executionPlan: null,

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
                ...(updates.workPlan !== undefined && { workPlan: updates.workPlan }),
                ...(updates.isPlanMode !== undefined && { isPlanMode: updates.isPlanMode }),
                ...(updates.executionPlan !== undefined && {
                  executionPlan: updates.executionPlan,
                }),
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
            workPlan: convState.workPlan,
            isPlanMode: convState.isPlanMode,
            executionPlan: convState.executionPlan,
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
            workPlan,
            isPlanMode,
            executionPlan,
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

          // Reset context status for the new conversation (async import for browser compatibility)
          import('../stores/contextStore').then(({ useContextStore }) => {
            useContextStore.getState().reset();
          }).catch(console.error);

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
              workPlan,
              isPlanMode,
              executionPlan,
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
                workPlan: newState.workPlan,
                isPlanMode: newState.isPlanMode,
                executionPlan: newState.executionPlan,
                pendingClarification: newState.pendingClarification,
                pendingDecision: newState.pendingDecision,
                pendingEnvVarRequest: newState.pendingEnvVarRequest,
                doomLoopDetected: newState.doomLoopDetected,
                pinnedEventIds: new Set(),
              });
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
            workPlan: null,
            isPlanMode: false,
            executionPlan: null,
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
            const response = await agentService.listConversations(
              projectId,
              undefined,
              10,
              offset
            );
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
            deltaBuffers.delete(conversationId);

            // Cancel any pending save for this conversation
            const pendingTimer = pendingSaves.get(conversationId);
            if (pendingTimer) {
              clearTimeout(pendingTimer);
              pendingSaves.delete(conversationId);
            }

            // Remove from LRU tracking
            const lruIdx = conversationAccessOrder.indexOf(conversationId);
            if (lruIdx !== -1) conversationAccessOrder.splice(lruIdx, 1);

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
                workPlan: null,
                executionPlan: null,
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
            workPlan: cachedState?.workPlan || null,
            executionPlan: cachedState?.executionPlan || null,
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
            const [response, planStatus, execStatus, _contextStatusResult] = await Promise.all([
              agentService.getConversationMessages(
                conversationId,
                projectId,
                200 // Load latest 200 messages
              ) as Promise<any>,
              // Use catch to prevent one failure from blocking others
              planService.getPlanModeStatus(conversationId).catch((e) => {
                logger.warn(`[AgentV3] getPlanModeStatus failed:`, e);
                return null;
              }),
              agentService.getExecutionStatus(conversationId, true, lastKnownTimeUs).catch((e) => {
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
            ]);

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
              isPlanMode: planStatus?.is_in_plan_mode ?? false,
            };

            set((state) => {
              const newStates = new Map(state.conversationStates);
              const currentConvState =
                newStates.get(conversationId) || createDefaultConversationState();
              newStates.set(conversationId, {
                ...currentConvState,
                ...newConvState,
              } as ConversationState);

              // Skip timeline replacement if streaming is active — sendMessage
              // may have already appended a user message that the API response
              // doesn't include, so overwriting would cause it to disappear.
              // Also skip if data hasn't changed to avoid unnecessary re-renders.
              const isCurrentlyStreaming = state.isStreaming;
              const timelineChanged =
                !isCurrentlyStreaming &&
                (state.timeline.length !== mergedTimeline.length ||
                  (mergedTimeline.length > 0 &&
                    state.timeline[state.timeline.length - 1]?.id !==
                      mergedTimeline[mergedTimeline.length - 1]?.id));

              return {
                conversationStates: newStates,
                ...(timelineChanged
                  ? { timeline: mergedTimeline, messages: messages }
                  : {}),
                isLoadingHistory: false,
                hasEarlier: response.has_more ?? false,
                earliestTimeUs: firstTimeUs,
                earliestCounter: firstCounter,
                // Set plan mode if successfully fetched
                ...(planStatus ? { isPlanMode: planStatus.is_in_plan_mode } : {}),
              };
            });

            // Persist to IndexedDB
            saveConversationState(conversationId, newConvState).catch(console.error);

            // DEBUG: Log execution status for recovery debugging
            logger.debug(`[AgentV3] execStatus for ${conversationId}:`, {
              execStatus,
              is_running: execStatus?.is_running,
              lastKnownTimeUs,
              lastTimeUs,
            });

            // If agent is running, set up streaming state and subscribe to WebSocket
            // The normal WebSocket event flow will handle incoming events
            // No special recovery logic needed - just subscribe and wait for events
            if (execStatus?.is_running) {
              logger.debug(
                `[AgentV3] Conversation ${conversationId} is running, ` +
                  `subscribing to WebSocket for live events...`
              );

              // CRITICAL: Clear any stale delta buffers before subscribing to running session
              // This prevents duplicate content from previous page loads
              clearAllDeltaBuffers();

              // Set streaming state
              set({ isStreaming: true, agentState: 'thinking' });

              // Ensure WebSocket is connected
              if (!agentService.isConnected()) {
                logger.debug(`[AgentV3] Connecting WebSocket...`);
                await agentService.connect();
              }

              // Reuse the same full handler used by sendMessage so that
              // recovery events are appended to the timeline via appendSSEEventToTimeline.
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

              // Subscribe to conversation - WebSocket will forward events from Redis Stream
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
          const { earliestTimeUs, earliestCounter, timeline, isLoadingEarlier, activeConversationId } =
            get();

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
            conversation_id: conversationId!,
            role: 'user',
            content,
            message_type: 'text',
            created_at: new Date().toISOString(),
          };

          // Create user message TimelineEvent and append to timeline
          const userMessageEvent: UserMessageEvent = {
            id: userMsgId,
            type: 'user_message',
            eventTimeUs: Date.now() * 1000,
            eventCounter: 0,
            timestamp: Date.now(),
            content,
            role: 'user',
          };

          // Update both global state and conversation-specific state
          const newTimeline = [...timeline, userMessageEvent];
          set((state) => {
            const newStates = new Map(state.conversationStates);
            const convState = newStates.get(conversationId!) || createDefaultConversationState();
            newStates.set(conversationId!, {
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
          const handlerConversationId = conversationId!;

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
            agentService
              .chat(
                {
                  conversation_id: conversationId!,
                  message: content,
                  project_id: projectId,
                  file_metadata: additionalHandlers?.fileMetadata,
                  forced_skill_name: additionalHandlers?.forcedSkillName,
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
            return conversationId!;
          }

          // For existing conversations, wait for stream to complete
          try {
            await agentService.chat(
              {
                conversation_id: conversationId!,
                message: content,
                project_id: projectId,
                file_metadata: additionalHandlers?.fileMetadata,
                forced_skill_name: additionalHandlers?.forcedSkillName,
              },
              handler
            );
            return conversationId!;
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
            agentService.stopChat(targetConvId);

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

                case 'env_var':
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

        togglePlanMode: async () => {
          const { isPlanMode, activeConversationId } = get();
          if (!activeConversationId) return;

          try {
            if (isPlanMode) {
              const status = await planService.getPlanModeStatus(activeConversationId);
              if (status.current_plan_id) {
                await planService.exitPlanMode({
                  conversation_id: activeConversationId,
                  plan_id: status.current_plan_id,
                });
              }
              set({ isPlanMode: false });
            } else {
              await planService.enterPlanMode({
                conversation_id: activeConversationId,
                title: 'Plan',
              });
              set({ isPlanMode: true });
            }
          } catch (error) {
            console.error('Failed to toggle plan mode', error);
          }
        },

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

// ===== Cross-Tab Synchronization =====
// Subscribe to tab sync messages to keep state consistent across browser tabs

/**
 * Initialize cross-tab synchronization
 * This runs once when the module is loaded
 */
function initTabSync(): void {
  if (!tabSync.isSupported()) {
    logger.info('[AgentV3] Cross-tab sync not supported in this browser');
    return;
  }

  logger.info('[AgentV3] Initializing cross-tab sync');

  tabSync.subscribe((message: TabSyncMessage) => {
    const state = useAgentV3Store.getState();

    switch (message.type) {
      case 'STREAMING_STATE_CHANGED': {
        const msg = message as TabSyncMessage & {
          conversationId: string;
          isStreaming: boolean;
          streamStatus: string;
        };
        // Update conversation state if we have it
        const convState = state.conversationStates.get(msg.conversationId);
        if (convState) {
          state.updateConversationState(msg.conversationId, {
            isStreaming: msg.isStreaming,
            streamStatus: msg.streamStatus as 'idle' | 'connecting' | 'streaming' | 'error',
          });
          logger.debug(`[TabSync] Updated streaming state for ${msg.conversationId}`);
        }
        break;
      }

      case 'CONVERSATION_COMPLETED': {
        const msg = message as TabSyncMessage & { conversationId: string };
        // If this is our active conversation, reload messages to get the latest
        if (state.activeConversationId === msg.conversationId) {
          // Trigger a refresh of messages
          logger.info(
            `[TabSync] Conversation ${msg.conversationId} completed in another tab, reloading...`
          );
          // Find the project ID from conversations list
          const conv = state.conversations.find((c) => c.id === msg.conversationId);
          if (conv) {
            state.loadMessages(msg.conversationId, conv.project_id);
          }
        }
        break;
      }

      case 'HITL_STATE_CHANGED': {
        const msg = message as TabSyncMessage & {
          conversationId: string;
          hasPendingHITL: boolean;
          hitlType?: string;
        };
        // Update HITL state for this conversation
        const convState = state.conversationStates.get(msg.conversationId);
        if (convState) {
          // If HITL was resolved in another tab, clear our local pending state
          if (!msg.hasPendingHITL) {
            state.updateConversationState(msg.conversationId, {
              pendingClarification: null,
              pendingDecision: null,
              pendingEnvVarRequest: null,
            });
          }
          logger.debug(`[TabSync] Updated HITL state for ${msg.conversationId}`);
        }
        break;
      }

      case 'CONVERSATION_DELETED': {
        const msg = message as TabSyncMessage & { conversationId: string };
        // Remove from conversations list
        useAgentV3Store.setState((s) => ({
          conversations: s.conversations.filter((c) => c.id !== msg.conversationId),
        }));
        // Clean up conversation state
        const newStates = new Map(state.conversationStates);
        newStates.delete(msg.conversationId);
        useAgentV3Store.setState({ conversationStates: newStates });
        // Clear active conversation if it was deleted
        if (state.activeConversationId === msg.conversationId) {
          useAgentV3Store.setState({ activeConversationId: null });
        }
        logger.info(`[TabSync] Removed deleted conversation ${msg.conversationId}`);
        break;
      }

      case 'CONVERSATION_RENAMED': {
        const msg = message as TabSyncMessage & { conversationId: string; newTitle: string };
        // Update title in conversations list
        useAgentV3Store.setState((s) => ({
          conversations: s.conversations.map((c) =>
            c.id === msg.conversationId ? { ...c, title: msg.newTitle } : c
          ),
        }));
        logger.debug(`[TabSync] Updated title for ${msg.conversationId}`);
        break;
      }
    }
  });
}

// Initialize tab sync on module load
initTabSync();

// Selector for derived messages (rerender-derived-state)
// Messages are computed from timeline to avoid duplicate state
export const useMessages = () =>
  useAgentV3Store((state) => {
    // For now, return stored messages for backward compatibility
    // TODO: Switch to computed derivation after verifying all consumers work correctly
    return state.messages;
  });
