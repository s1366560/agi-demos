import { v4 as uuidv4 } from "uuid";
import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";

import { agentService } from "../services/agentService";
import { planService } from "../services/planService";
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
    ThoughtEventData,
    WorkPlanEventData,
    StepStartEventData,
    CompleteEventData,
    ExecutionPlan,
    PlanExecutionStartEvent,
    PlanExecutionCompleteEvent,
    ReflectionCompleteEvent,
    ClarificationAskedEventData,
    DecisionAskedEventData,
    EnvVarRequestedEventData,
    PermissionAskedEventData,
    DoomLoopDetectedEventData,
    CostUpdateEventData,
} from "../types/agent";
import {
    type ConversationState,
    type HITLSummary,
    type CostTrackingState,
    createDefaultConversationState,
    getHITLSummaryFromState,
    MAX_CONCURRENT_STREAMING_CONVERSATIONS,
} from "../types/conversationState";
import {
    saveConversationState,
    loadConversationState,
    deleteConversationState,
} from "../utils/conversationDB";
import { logger } from "../utils/logger";
import { appendSSEEventToTimeline } from "../utils/sseEventAdapter";
import { tabSync, type TabSyncMessage } from "../utils/tabSync";

/**
 * Token delta batching configuration
 * Batches rapid token updates to reduce re-renders and improve performance
 */
const TOKEN_BATCH_INTERVAL_MS = 50; // Batch tokens every 50ms for smooth streaming
const THOUGHT_BATCH_INTERVAL_MS = 50; // Same for thought deltas

/**
 * Per-conversation delta buffer state
 * Using Map to isolate buffers per conversation, preventing cross-conversation contamination
 */
interface DeltaBufferState {
    textDeltaBuffer: string;
    textDeltaFlushTimer: ReturnType<typeof setTimeout> | null;
    thoughtDeltaBuffer: string;
    thoughtDeltaFlushTimer: ReturnType<typeof setTimeout> | null;
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
        buffer.textDeltaBuffer = '';
        buffer.thoughtDeltaBuffer = '';
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
        savePromises.push(
            saveConversationState(conversationId, convState).catch(console.error)
        );
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
    /** Attachment IDs to include with the message */
    attachmentIds?: string[];
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
    updates: { answered: boolean; answer?: string; decision?: string; values?: Record<string, string>; granted?: boolean }
): TimelineEvent[] {
    return timeline.map((event) => {
        if (event.type === eventType && (event as any).requestId === requestId) {
            return { ...event, ...updates };
        }
        return event;
    });
}

/**
 * Convert TimelineEvent[] to Message[] - Simple 1:1 conversion without merging
 * Each timeline event maps directly to a message for natural ordering
 */
function timelineToMessages(timeline: TimelineEvent[]): Message[] {
    const messages: Message[] = [];

    for (const event of timeline) {
        switch (event.type) {
            case "user_message":
                messages.push({
                    id: event.id,
                    conversation_id: "",
                    role: "user",
                    content: (event as any).content || "",
                    message_type: "text" as const,
                    created_at: new Date(event.timestamp).toISOString(),
                });
                break;

            case "assistant_message":
                messages.push({
                    id: event.id,
                    conversation_id: "",
                    role: "assistant",
                    content: (event as any).content || "",
                    message_type: "text" as const,
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

    // Per-conversation state (isolated for multi-conversation support)
    conversationStates: Map<string, ConversationState>;

    // Timeline State (for active conversation - backward compatibility)
    timeline: TimelineEvent[];

    // Messages State (Derived from timeline for backward compatibility)
    messages: Message[];
    isLoadingHistory: boolean;  // For initial message load (shows loading in sidebar)
    isLoadingEarlier: boolean;  // For pagination (does NOT show loading in sidebar)
    hasEarlier: boolean;  // Whether there are earlier messages to load
    earliestLoadedSequence: number | null;  // For pagination

    // Stream State (for active conversation - backward compatibility)
    isStreaming: boolean;
    streamStatus: "idle" | "connecting" | "streaming" | "error";
    error: string | null;
    streamingAssistantContent: string; // Streaming content (used for real-time display)

    // Agent Execution State (for active conversation - backward compatibility)
    agentState: "idle" | "thinking" | "acting" | "observing" | "awaiting_input" | "retrying";
    currentThought: string;
    streamingThought: string; // For streaming thought_delta content
    isThinkingStreaming: boolean; // Whether thought is currently streaming
    activeToolCalls: Map<
        string,
        ToolCall & { status: "running" | "success" | "failed"; startTime: number }
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

    // Multi-conversation state helpers
    getConversationState: (conversationId: string) => ConversationState;
    updateConversationState: (conversationId: string, updates: Partial<ConversationState>) => void;
    getStreamingConversationCount: () => number;
    getConversationsWithPendingHITL: () => Array<{ conversationId: string; summary: HITLSummary }>;
    syncActiveConversationState: () => void;

    // Actions
    setActiveConversation: (id: string | null) => void;
    loadConversations: (projectId: string) => Promise<void>;
    loadMessages: (conversationId: string, projectId: string) => Promise<void>;
    loadEarlierMessages: (conversationId: string, projectId: string) => Promise<boolean>;
    createNewConversation: (projectId: string) => Promise<string | null>;
    sendMessage: (
        content: string,
        projectId: string,
        additionalHandlers?: AdditionalAgentHandlers
    ) => Promise<string | null>;
    deleteConversation: (
        conversationId: string,
        projectId: string
    ) => Promise<void>;
    renameConversation: (
        conversationId: string,
        projectId: string,
        title: string
    ) => Promise<void>;
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
}

export const useAgentV3Store = create<AgentV3State>()(
    devtools(
        persist(
            (set, get) => ({
                conversations: [],
                activeConversationId: null,

                // Per-conversation state map
                conversationStates: new Map<string, ConversationState>(),

                // Timeline: Primary data source (stores raw events from API and streaming)
                timeline: [],

                // Messages: Derived from timeline (for backward compatibility)
                messages: [],
                isLoadingHistory: false,
                isLoadingEarlier: false,
                hasEarlier: false,
                earliestLoadedSequence: null,

                isStreaming: false,
                streamStatus: "idle",
                error: null,
                streamingAssistantContent: "", // Real-time streaming content

                agentState: "idle",
                currentThought: "",
                streamingThought: "",
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
                            activeToolCalls: updates.activeToolCalls !== undefined
                                ? updates.activeToolCalls
                                : currentState.activeToolCalls,
                        };

                        // Update HITL summary if HITL state changed
                        if (updates.pendingClarification !== undefined ||
                            updates.pendingDecision !== undefined ||
                            updates.pendingEnvVarRequest !== undefined ||
                            updates.pendingPermission !== undefined) {
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
                                ...(updates.streamingAssistantContent !== undefined && { streamingAssistantContent: updates.streamingAssistantContent }),
                                ...(updates.error !== undefined && { error: updates.error }),
                                ...(updates.agentState !== undefined && { agentState: updates.agentState }),
                                ...(updates.currentThought !== undefined && { currentThought: updates.currentThought }),
                                ...(updates.streamingThought !== undefined && { streamingThought: updates.streamingThought }),
                                ...(updates.isThinkingStreaming !== undefined && { isThinkingStreaming: updates.isThinkingStreaming }),
                                ...(updates.activeToolCalls !== undefined && { activeToolCalls: updates.activeToolCalls }),
                                ...(updates.pendingToolsStack !== undefined && { pendingToolsStack: updates.pendingToolsStack }),
                                ...(updates.workPlan !== undefined && { workPlan: updates.workPlan }),
                                ...(updates.isPlanMode !== undefined && { isPlanMode: updates.isPlanMode }),
                                ...(updates.executionPlan !== undefined && { executionPlan: updates.executionPlan }),
                                ...(updates.pendingClarification !== undefined && { pendingClarification: updates.pendingClarification }),
                                ...(updates.pendingDecision !== undefined && { pendingDecision: updates.pendingDecision }),
                                ...(updates.pendingEnvVarRequest !== undefined && { pendingEnvVarRequest: updates.pendingEnvVarRequest }),
                                ...(updates.pendingPermission !== undefined && { pendingPermission: updates.pendingPermission }),
                                ...(updates.doomLoopDetected !== undefined && { doomLoopDetected: updates.doomLoopDetected }),
                                ...(updates.costTracking !== undefined && { costTracking: updates.costTracking }),
                                ...(updates.hasEarlier !== undefined && { hasEarlier: updates.hasEarlier }),
                                ...(updates.earliestLoadedSequence !== undefined && { earliestLoadedSequence: updates.earliestLoadedSequence }),
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
                        earliestLoadedSequence: convState.earliestLoadedSequence,
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
                    });
                },

                setActiveConversation: (id) => {
                    const { activeConversationId, conversationStates, timeline, isStreaming, streamStatus,
                        streamingAssistantContent, error, agentState, currentThought, streamingThought,
                        isThinkingStreaming, activeToolCalls, pendingToolsStack, workPlan, isPlanMode,
                        executionPlan, pendingClarification, pendingDecision, pendingEnvVarRequest,
                        doomLoopDetected, hasEarlier, earliestLoadedSequence } = get();

                    // CRITICAL: Clear delta buffers when switching conversations
                    // Prevents stale streaming content from previous conversation
                    clearAllDeltaBuffers();

                    // Save current conversation state before switching
                    if (activeConversationId && activeConversationId !== id) {
                        const newStates = new Map(conversationStates);
                        const currentState = newStates.get(activeConversationId) || createDefaultConversationState();
                        newStates.set(activeConversationId, {
                            ...currentState,
                            timeline,
                            hasEarlier,
                            earliestLoadedSequence,
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
                        saveConversationState(activeConversationId, newStates.get(activeConversationId)!).catch(console.error);
                    }

                    // Load new conversation state if exists
                    if (id) {
                        const newState = conversationStates.get(id);
                        if (newState) {
                            set({
                                activeConversationId: id,
                                timeline: newState.timeline,
                                messages: timelineToMessages(newState.timeline),
                                hasEarlier: newState.hasEarlier,
                                earliestLoadedSequence: newState.earliestLoadedSequence,
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
                        earliestLoadedSequence: null,
                        isStreaming: false,
                        streamStatus: "idle",
                        streamingAssistantContent: "",
                        error: null,
                        agentState: "idle",
                        currentThought: "",
                        streamingThought: "",
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
                    });
                },

                loadConversations: async (projectId) => {
                    console.log(`[agentV3] loadConversations called for project: ${projectId}`);

                    // Prevent duplicate calls for the same project
                    const currentConvos = get().conversations;
                    const firstConvoProject = currentConvos[0]?.project_id;
                    if (currentConvos.length > 0 && firstConvoProject === projectId) {
                        console.log(`[agentV3] Conversations already loaded for project ${projectId}, skipping`);
                        return;
                    }

                    try {
                        const conversations = await agentService.listConversations(projectId);
                        console.log(`[agentV3] Loaded ${conversations.length} conversations`);
                        set({ conversations });
                    } catch (error) {
                        console.error("[agentV3] Failed to list conversations", error);
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
                        
                        // Remove from local state and conversation states map
                        set((state) => {
                            const newStates = new Map(state.conversationStates);
                            newStates.delete(conversationId);

                            return {
                                conversations: state.conversations.filter(
                                    (c) => c.id !== conversationId
                                ),
                                conversationStates: newStates,
                                // Clear active conversation if it was the deleted one
                                activeConversationId:
                                    state.activeConversationId === conversationId
                                        ? null
                                        : state.activeConversationId,
                                // Clear messages and timeline if the deleted conversation was active
                                messages:
                                    state.activeConversationId === conversationId ? [] : state.messages,
                                timeline:
                                    state.activeConversationId === conversationId ? [] : state.timeline,
                            };
                        });

                        // Remove from IndexedDB
                        deleteConversationState(conversationId).catch(console.error);

                        // Broadcast to other tabs
                        tabSync.broadcastConversationDeleted(conversationId);
                    } catch (error) {
                        console.error("Failed to delete conversation", error);
                        set({ error: "Failed to delete conversation" });
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
                        console.error("Failed to rename conversation", error);
                        set({ error: "Failed to rename conversation" });
                    }
                },

                createNewConversation: async (projectId) => {
                    try {
                        const newConv = await agentService.createConversation({
                            project_id: projectId,
                            title: "New Conversation",
                        });

                        // Create fresh state for new conversation
                        const newConvState = createDefaultConversationState();

                        // Add to conversations list and set as active
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
                                currentThought: "",
                                streamingThought: "",
                                isThinkingStreaming: false,
                                workPlan: null,
                                executionPlan: null,
                                agentState: "idle",
                                isStreaming: false,
                                error: null,
                                pendingClarification: null,
                                pendingDecision: null,
                                pendingEnvVarRequest: null,
                            };
                        });
                        return newConv.id;
                    } catch (error) {
                        console.error("Failed to create conversation", error);
                        set({ error: "Failed to create conversation" });
                        return null;
                    }
                },

                loadMessages: async (conversationId, projectId) => {
                    // Get last known sequence from localStorage for recovery
                    const lastKnownSeq = parseInt(
                        localStorage.getItem(`agent_seq_${conversationId}`) || "0",
                        10
                    );

                    // DEBUG: Log recovery attempt parameters
                    console.log(`[AgentV3] loadMessages starting for ${conversationId}, lastKnownSeq=${lastKnownSeq}`);

                    // Try to load from IndexedDB first
                    const cachedState = await loadConversationState(conversationId);

                    set({
                        isLoadingHistory: true,
                        timeline: cachedState?.timeline || [],      // Use cached if available
                        messages: cachedState?.timeline ? timelineToMessages(cachedState.timeline) : [],
                        currentThought: cachedState?.currentThought || "",
                        streamingThought: "",
                        isThinkingStreaming: false,
                        workPlan: cachedState?.workPlan || null,
                        executionPlan: cachedState?.executionPlan || null,
                        agentState: cachedState?.agentState || "idle",
                        hasEarlier: cachedState?.hasEarlier || false,
                        earliestLoadedSequence: cachedState?.earliestLoadedSequence || null,
                        // Restore HITL state if any
                        pendingClarification: cachedState?.pendingClarification || null,
                        pendingDecision: cachedState?.pendingDecision || null,
                        pendingEnvVarRequest: cachedState?.pendingEnvVarRequest || null,
                    });

                    try {
                        // Parallelize independent API calls (async-parallel)
                        // Include recovery info in execution status check
                        const [response, planStatus, execStatus] = await Promise.all([
                            agentService.getConversationMessages(
                                conversationId,
                                projectId,
                                200  // Load latest 200 messages
                            ) as Promise<any>,
                            // Use catch to prevent one failure from blocking others
                            planService.getPlanModeStatus(conversationId).catch((e) => {
                                console.warn(`[AgentV3] getPlanModeStatus failed:`, e);
                                return null;
                            }),
                            agentService.getExecutionStatus(conversationId, true, lastKnownSeq).catch((e) => {
                                console.warn(`[AgentV3] getExecutionStatus failed:`, e);
                                return null;
                            }),
                        ]);

                        if (get().activeConversationId !== conversationId) {
                            console.log("Conversation changed during load, ignoring result");
                            return;
                        }

                        // DEBUG: Log full timeline analysis for diagnosing missing/disordered messages
                        const eventTypeCounts: Record<string, number> = {};
                        let isOrdered = true;
                        let prevSeq = -1;
                        for (const event of response.timeline) {
                            eventTypeCounts[event.type] = (eventTypeCounts[event.type] || 0) + 1;
                            if (event.sequenceNumber <= prevSeq) {
                                isOrdered = false;
                                console.error(`[AgentV3] Timeline out of order! seq=${event.sequenceNumber} <= prevSeq=${prevSeq}`, event);
                            }
                            prevSeq = event.sequenceNumber;
                        }
                        console.log(`[AgentV3] loadMessages API response:`, {
                            conversationId,
                            totalEvents: response.timeline.length,
                            eventTypeCounts,
                            isOrdered,
                            has_more: response.has_more,
                            first_sequence: response.first_sequence,
                            last_sequence: response.last_sequence,
                        });

                        // Ensure timeline is sorted by sequence number (defensive fix)
                        const sortedTimeline = [...response.timeline].sort(
                            (a, b) => a.sequenceNumber - b.sequenceNumber
                        );

                        // Store the raw timeline and derive messages (no merging)
                        const messages = timelineToMessages(sortedTimeline);
                        const firstSequence = sortedTimeline[0]?.sequenceNumber ?? null;
                        const lastSequence = sortedTimeline[sortedTimeline.length - 1]?.sequenceNumber ?? 0;

                        // DEBUG: Log assistant_message events
                        const assistantMsgs = sortedTimeline.filter((e: any) => e.type === 'assistant_message');
                        console.log(`[AgentV3] loadMessages: Found ${assistantMsgs.length} assistant_message events`, assistantMsgs);

                        // DEBUG: Log artifact events in timeline
                        const artifactEvents = sortedTimeline.filter((e: any) => e.type === 'artifact_created');
                        console.log(`[AgentV3] loadMessages: Found ${artifactEvents.length} artifact_created events in timeline`, artifactEvents);

                        // Update localStorage with latest sequence
                        if (lastSequence > 0) {
                            localStorage.setItem(`agent_seq_${conversationId}`, String(lastSequence));
                        }

                        // Update both global state and conversation-specific state
                        const newConvState: Partial<ConversationState> = {
                            timeline: sortedTimeline,  // Use sorted timeline
                            hasEarlier: response.has_more ?? false,
                            earliestLoadedSequence: firstSequence,
                            isPlanMode: planStatus?.is_in_plan_mode ?? false,
                        };

                        set((state) => {
                            const newStates = new Map(state.conversationStates);
                            const currentConvState = newStates.get(conversationId) || createDefaultConversationState();
                            newStates.set(conversationId, {
                                ...currentConvState,
                                ...newConvState,
                            } as ConversationState);

                            return {
                                conversationStates: newStates,
                                timeline: sortedTimeline,  // Use sorted timeline
                                messages: messages,
                                isLoadingHistory: false,
                                hasEarlier: response.has_more ?? false,
                                earliestLoadedSequence: firstSequence,
                                // Set plan mode if successfully fetched
                                ...(planStatus ? { isPlanMode: planStatus.is_in_plan_mode } : {}),
                            };
                        });

                        // Persist to IndexedDB
                        saveConversationState(conversationId, newConvState).catch(console.error);

                        // DEBUG: Log execution status for recovery debugging
                        console.log(`[AgentV3] execStatus for ${conversationId}:`, {
                            execStatus,
                            is_running: execStatus?.is_running,
                            lastKnownSeq,
                            lastSequence,
                        });

                        // If agent is running, set up streaming state and subscribe to WebSocket
                        // The normal WebSocket event flow will handle incoming events
                        // No special recovery logic needed - just subscribe and wait for events
                        if (execStatus?.is_running) {
                            console.log(
                                `[AgentV3] Conversation ${conversationId} is running, ` +
                                `subscribing to WebSocket for live events...`
                            );

                            // CRITICAL: Clear any stale delta buffers before subscribing to running session
                            // This prevents duplicate content from previous page loads
                            clearAllDeltaBuffers();

                            // Set streaming state
                            set({ isStreaming: true, agentState: "thinking" });

                            // Ensure WebSocket is connected
                            if (!agentService.isConnected()) {
                                console.log(`[AgentV3] Connecting WebSocket...`);
                                await agentService.connect();
                            }

                            // Simple handler for streaming events - same as normal chat
                            const streamHandler: AgentStreamHandler = {
                                onTextDelta: (event) => {
                                    set((state) => ({
                                        streamingAssistantContent: state.streamingAssistantContent + (event.data.delta || ""),
                                    }));
                                },
                                onThought: (event) => {
                                    const thought = event.data.thought;
                                    if (!thought || thought.trim() === "") return;
                                    set((state) => ({
                                        currentThought: state.currentThought + "\n" + thought,
                                    }));
                                },
                                onThoughtDelta: (event) => {
                                    set((state) => ({
                                        streamingThought: state.streamingThought + (event.data.delta || ""),
                                        isThinkingStreaming: true,
                                    }));
                                },
                                onWorkPlan: (event) => {
                                    set({
                                        workPlan: {
                                            id: event.data.plan_id,
                                            conversation_id: event.data.conversation_id,
                                            status: event.data.status,
                                            steps: event.data.steps.map((s: any) => ({
                                                step_number: s.step_number,
                                                description: s.description,
                                                thought_prompt: "",
                                                required_tools: [],
                                                expected_output: s.expected_output,
                                                dependencies: [],
                                            })),
                                            current_step_index: event.data.current_step,
                                            created_at: new Date().toISOString(),
                                        },
                                    });
                                },
                                onStepStart: (event) => {
                                    set((state) => ({
                                        workPlan: state.workPlan
                                            ? {
                                                ...state.workPlan,
                                                current_step_index: event.data.current_step,
                                            }
                                            : null,
                                        agentState: "acting",
                                    }));
                                },
                                onAct: (event) => {
                                    set((state) => {
                                        const toolName = event.data.tool_name;
                                        const startTime = Date.now();
                                        const newCall: ToolCall & {
                                            status: "running";
                                            startTime: number;
                                        } = {
                                            name: toolName,
                                            arguments: event.data.tool_input,
                                            status: "running",
                                            startTime,
                                        };
                                        const newMap = new Map(state.activeToolCalls);
                                        newMap.set(toolName, newCall);
                                        return { activeToolCalls: newMap, agentState: "acting" };
                                    });
                                },
                                onObserve: () => {
                                    set((state) => {
                                        const stack = [...state.pendingToolsStack];
                                        stack.pop();
                                        return { pendingToolsStack: stack, agentState: "observing" };
                                    });
                                },
                                onComplete: () => {
                                    console.log(`[AgentV3] Stream complete, resetting state`);
                                    // Simply reset streaming state - messages are already loaded
                                    // or will be loaded on next conversation switch
                                    set({
                                        isStreaming: false,
                                        agentState: "idle",
                                        activeToolCalls: new Map(),
                                        streamingAssistantContent: "",
                                        streamingThought: "",
                                        isThinkingStreaming: false,
                                    });
                                },
                                onRetry: (event) => {
                                    // LLM is retrying after a transient error (e.g., rate limit)
                                    // Keep streaming state active, just show a warning
                                    console.warn(
                                        `[AgentV3] LLM retrying: attempt=${event.data.attempt}, ` +
                                        `delay=${event.data.delay_ms}ms, reason=${event.data.message}`
                                    );
                                    // Update state to show retry indicator
                                    set({
                                        agentState: "retrying",
                                        // Keep isStreaming: true so we continue receiving events
                                    });
                                },
                                onError: (event) => {
                                    // Check if this is a recoverable error
                                    const isRateLimitError = event.data.code === "RATE_LIMIT" ||
                                        event.data.message?.includes("rate limit") ||
                                        event.data.message?.includes("限流") ||
                                        event.data.message?.includes("并发数过高");
                                    
                                    if (isRateLimitError) {
                                        // Rate limit error - the backend might retry
                                        // Don't immediately stop streaming
                                        console.warn(`[AgentV3] Rate limit error, waiting for retry: ${event.data.message}`);
                                        set({
                                            error: `限流错误，正在重试: ${event.data.message}`,
                                            agentState: "retrying",
                                            // Keep isStreaming: true
                                        });
                                    } else {
                                        // Fatal error - stop streaming
                                        console.error(`[AgentV3] Fatal error: ${event.data.message}`);
                                        set({
                                            error: event.data.message,
                                            isStreaming: false,
                                            agentState: "idle",
                                        });
                                    }
                                },
                            };

                            // Subscribe to conversation - WebSocket will forward events from Redis Stream
                            agentService.subscribe(conversationId, streamHandler);
                            console.log(`[AgentV3] Subscribed to conversation ${conversationId}`);
                        }

                        set({ isLoadingHistory: false });
                    } catch (error) {
                        if (get().activeConversationId !== conversationId) return;
                        console.error("Failed to load messages", error);
                        set({ isLoadingHistory: false });
                    }
                },

                loadEarlierMessages: async (conversationId, projectId) => {
                    const { earliestLoadedSequence, timeline, isLoadingEarlier, activeConversationId } = get();

                    // Guard: Don't load if already loading or no pagination point exists
                    if (activeConversationId !== conversationId) return false;
                    if (!earliestLoadedSequence || isLoadingEarlier) {
                        console.log('[AgentV3] Cannot load earlier messages: no pagination point or already loading');
                        return false;
                    }

                    console.log('[AgentV3] Loading earlier messages before sequence:', earliestLoadedSequence);
                    set({ isLoadingEarlier: true });

                    try {
                        const response = await agentService.getConversationMessages(
                            conversationId,
                            projectId,
                            200,  // Load 200 more messages (increased from 50)
                            undefined,  // from_sequence
                            earliestLoadedSequence  // before_sequence
                        ) as any;

                        // Check if conversation is still active
                        if (get().activeConversationId !== conversationId) {
                            console.log('[AgentV3] Conversation changed during load earlier messages, ignoring result');
                            return false;
                        }

                        // Prepend new events to existing timeline and sort by sequence number
                        const combinedTimeline = [...response.timeline, ...timeline];
                        const sortedTimeline = combinedTimeline.sort(
                            (a, b) => a.sequenceNumber - b.sequenceNumber
                        );
                        const newMessages = timelineToMessages(sortedTimeline);
                        const newFirstSequence = sortedTimeline[0]?.sequenceNumber ?? null;

                        set({
                            timeline: sortedTimeline,
                            messages: newMessages,
                            isLoadingEarlier: false,
                            hasEarlier: response.has_more ?? false,
                            earliestLoadedSequence: newFirstSequence,
                        });

                        console.log('[AgentV3] Loaded earlier messages, total timeline length:', sortedTimeline.length);
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
                        set({ error: `Maximum ${MAX_CONCURRENT_STREAMING_CONVERSATIONS} concurrent conversations reached. Please wait for one to complete.` });
                        return null;
                    }

                    let conversationId = activeConversationId;
                    let isNewConversation = false;

                    if (!conversationId) {
                        try {
                            const newConv = await agentService.createConversation({
                                project_id: projectId,
                                title: content.slice(0, 30) + "...",
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
                        } catch (_error) {
                            set({ error: "Failed to create conversation" });
                            return null;
                        }
                    }

                    const userMsgId = uuidv4();
                    const userMsg: Message = {
                        id: userMsgId,
                        conversation_id: conversationId!,
                        role: "user",
                        content,
                        message_type: "text",
                        created_at: new Date().toISOString(),
                    };

                    // Create user message TimelineEvent and append to timeline
                    const userMessageEvent: UserMessageEvent = {
                        id: userMsgId,
                        type: "user_message",
                        sequenceNumber: timeline.length > 0 ? timeline[timeline.length - 1].sequenceNumber + 1 : 1,
                        timestamp: Date.now(),
                        content,
                        role: "user",
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
                        });

                        return {
                            conversationStates: newStates,
                            messages: [...messages, userMsg],
                            timeline: newTimeline,
                            isStreaming: true,
                            streamStatus: "connecting",
                            streamingAssistantContent: "", // Reset streaming content
                            error: null,
                            currentThought: "",
                            streamingThought: "",
                            isThinkingStreaming: false,
                            activeToolCalls: new Map(),
                            pendingToolsStack: [],
                            agentState: "thinking",
                        };
                    });

                    // Capture conversationId in closure for event handler isolation
                    // This is critical for multi-conversation support - events must only update
                    // the conversation they belong to, not the currently active one
                    const handlerConversationId = conversationId!;

                    // Define handler first (needed for both new and existing conversations)
                    const handler: AgentStreamHandler = {
                        onMessage: (_event) => { },
                        onThoughtDelta: (event) => {
                            // Streaming thought - batch updates for performance
                            const delta = event.data.delta;
                            if (!delta) return;

                            // Get per-conversation buffer
                            const buffer = getDeltaBuffer(handlerConversationId);
                            
                            // Accumulate deltas in buffer
                            buffer.thoughtDeltaBuffer += delta;

                            // Flush buffer on timer to batch rapid updates
                            if (!buffer.thoughtDeltaFlushTimer) {
                                buffer.thoughtDeltaFlushTimer = setTimeout(() => {
                                    const bufferedContent = buffer.thoughtDeltaBuffer;
                                    buffer.thoughtDeltaBuffer = '';
                                    buffer.thoughtDeltaFlushTimer = null;

                                    if (bufferedContent) {
                                        const { activeConversationId, updateConversationState, getConversationState } = get();

                                        // Always update per-conversation state
                                        const convState = getConversationState(handlerConversationId);
                                        updateConversationState(handlerConversationId, {
                                            streamingThought: convState.streamingThought + bufferedContent,
                                            isThinkingStreaming: true,
                                            agentState: "thinking",
                                        });

                                        // Only update global state if this is the active conversation
                                        if (handlerConversationId === activeConversationId) {
                                            set((state) => ({
                                                streamingThought: state.streamingThought + bufferedContent,
                                                isThinkingStreaming: true,
                                                agentState: "thinking",
                                            }));
                                        }
                                    }
                                }, THOUGHT_BATCH_INTERVAL_MS);
                            }
                        },
                        onThought: (event) => {
                            const newThought = event.data.thought;
                            const { activeConversationId, updateConversationState, getConversationState } = get();

                            // Append thought event to timeline using SSE adapter
                            const thoughtEvent: AgentEvent<ThoughtEventData> = event as AgentEvent<ThoughtEventData>;
                            const convState = getConversationState(handlerConversationId);
                            const updatedTimeline = appendSSEEventToTimeline(convState.timeline, thoughtEvent);

                            // Prepare updates for per-conversation state
                            const stateUpdates: Partial<ConversationState> = {
                                agentState: "thinking",
                                timeline: updatedTimeline,
                                streamingThought: "",
                                isThinkingStreaming: false,
                            };

                            // Skip empty thoughts (REASONING_START events)
                            if (newThought && newThought.trim() !== "") {
                                stateUpdates.currentThought = convState.currentThought + "\n" + newThought;
                            }

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, stateUpdates);

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set((state) => {
                                    if (!newThought || newThought.trim() === "") {
                                        return {
                                            agentState: "thinking",
                                            timeline: updatedTimeline,
                                            streamingThought: "",
                                            isThinkingStreaming: false,
                                        };
                                    }
                                    return {
                                        currentThought: state.currentThought + "\n" + newThought,
                                        streamingThought: "",
                                        isThinkingStreaming: false,
                                        agentState: "thinking",
                                        timeline: updatedTimeline,
                                    };
                                });
                            }
                        },
                        onWorkPlan: (event) => {
                            const { activeConversationId, updateConversationState, getConversationState } = get();

                            // Append work_plan event to timeline using SSE adapter
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
                                    thought_prompt: "",
                                    required_tools: [],
                                    expected_output: s.expected_output,
                                    dependencies: [],
                                })),
                                current_step_index: event.data.current_step,
                                created_at: new Date().toISOString(),
                            };

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, {
                                workPlan: newWorkPlan,
                                timeline: updatedTimeline,
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({
                                    workPlan: newWorkPlan,
                                    timeline: updatedTimeline,
                                });
                            }
                        },
                        onStepStart: (event) => {
                            const { activeConversationId, updateConversationState, getConversationState } = get();

                            // Append step_start event to timeline using SSE adapter
                            const stepStartEvent: AgentEvent<StepStartEventData> = event as AgentEvent<StepStartEventData>;
                            const convState = getConversationState(handlerConversationId);
                            const updatedTimeline = appendSSEEventToTimeline(convState.timeline, stepStartEvent);

                            // Update per-conversation state
                            const updates: Partial<ConversationState> = { timeline: updatedTimeline };
                            if (convState.workPlan) {
                                updates.workPlan = {
                                    ...convState.workPlan,
                                    current_step_index: event.data.current_step,
                                };
                                updates.agentState = "acting";
                            }
                            updateConversationState(handlerConversationId, updates);

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set((state) => {
                                    if (!state.workPlan) {
                                        return { timeline: updatedTimeline };
                                    }
                                    const newPlan = { ...state.workPlan };
                                    newPlan.current_step_index = event.data.current_step;
                                    return { workPlan: newPlan, agentState: "acting", timeline: updatedTimeline };
                                });
                            }
                        },
                        onStepEnd: (_event) => { },
                        onPlanExecutionStart: (event) => {
                            const { activeConversationId, updateConversationState, getConversationState } = get();

                            const executionPlanEvent: AgentEvent<PlanExecutionStartEvent> = event;
                            const convState = getConversationState(handlerConversationId);
                            const updatedTimeline = appendSSEEventToTimeline(convState.timeline, executionPlanEvent);
                            // Access data from event.data.data (nested structure)
                            const eventData = (event as any).data || {};
                            // Create a minimal execution plan from the event data
                            const newExecutionPlan: ExecutionPlan = {
                                id: eventData.plan_id || `plan-${Date.now()}`,
                                conversation_id: handlerConversationId,
                                user_query: eventData.user_query || "",
                                steps: [],
                                status: "executing",
                                reflection_enabled: true,
                                max_reflection_cycles: 3,
                                completed_steps: [],
                                failed_steps: [],
                                progress_percentage: 0,
                                is_complete: false,
                            };

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, {
                                executionPlan: newExecutionPlan,
                                timeline: updatedTimeline,
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({
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
                            // Access data from event.data
                            const eventData = (event as any).data || {};

                            const updatedExecutionPlan = convState.executionPlan
                                ? {
                                    ...convState.executionPlan,
                                    status: eventData.status || convState.executionPlan.status,
                                    completed_steps: Array(eventData.completed_steps || 0).fill(""),
                                    failed_steps: Array(eventData.failed_steps || 0).fill(""),
                                    progress_percentage: (eventData.completed_steps || 0) / (convState.executionPlan.steps.length || 1),
                                    is_complete: eventData.status === "completed" || eventData.status === "failed",
                                }
                                : null;

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, {
                                executionPlan: updatedExecutionPlan,
                                timeline: updatedTimeline,
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({
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

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, {
                                timeline: updatedTimeline,
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({ timeline: updatedTimeline });
                            }
                        },

                        onAct: (event) => {
                            const { activeConversationId, updateConversationState, getConversationState } = get();

                            // Append act event to timeline using SSE adapter
                            const convState = getConversationState(handlerConversationId);
                            const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);

                            const toolName = event.data.tool_name;
                            const startTime = Date.now();

                            const newCall: ToolCall & { status: "running"; startTime: number } = {
                                name: toolName,
                                arguments: event.data.tool_input,
                                status: "running",
                                startTime,
                            };

                            const newMap = new Map(convState.activeToolCalls);
                            newMap.set(toolName, newCall);

                            const newStack = [...convState.pendingToolsStack, toolName];

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, {
                                activeToolCalls: newMap,
                                pendingToolsStack: newStack,
                                agentState: "acting",
                                timeline: updatedTimeline,
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({
                                    activeToolCalls: newMap,
                                    pendingToolsStack: newStack,
                                    agentState: "acting",
                                    timeline: updatedTimeline,
                                });
                            }

                            // Call additional handler if provided
                            additionalHandlers?.onAct?.(event);
                        },
                        onObserve: (event) => {
                            const { activeConversationId, updateConversationState, getConversationState } = get();

                            // Append observe event to timeline using SSE adapter
                            const convState = getConversationState(handlerConversationId);
                            const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);

                            const stack = [...convState.pendingToolsStack];
                            stack.pop(); // Remove completed tool from stack

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, {
                                pendingToolsStack: stack,
                                agentState: "observing",
                                timeline: updatedTimeline,
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({
                                    pendingToolsStack: stack,
                                    agentState: "observing",
                                    timeline: updatedTimeline,
                                });
                            }

                            // Call additional handler if provided
                            additionalHandlers?.onObserve?.(event);
                        },
                        onTextStart: () => {
                            const { activeConversationId, updateConversationState } = get();

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, {
                                streamStatus: "streaming",
                                streamingAssistantContent: "",
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({ streamStatus: "streaming", streamingAssistantContent: "" });
                            }
                        },
                        onTextDelta: (event) => {
                            // Batch rapid token updates for performance (reduces re-renders from 100+/s to ~20/s)
                            const delta = event.data.delta;
                            console.log(`[AgentV3] onTextDelta: delta="${delta?.substring(0, 30)}...", conv=${handlerConversationId}`);
                            if (!delta) return;

                            // Get per-conversation buffer
                            const buffer = getDeltaBuffer(handlerConversationId);

                            // Accumulate deltas in buffer
                            buffer.textDeltaBuffer += delta;

                            // Flush buffer on timer to batch rapid updates
                            if (!buffer.textDeltaFlushTimer) {
                                buffer.textDeltaFlushTimer = setTimeout(() => {
                                    const bufferedContent = buffer.textDeltaBuffer;
                                    buffer.textDeltaBuffer = '';
                                    buffer.textDeltaFlushTimer = null;

                                    if (bufferedContent) {
                                        const { activeConversationId, updateConversationState, getConversationState } = get();
                                        console.log(`[AgentV3] Flushing buffer: len=${bufferedContent.length}, active=${activeConversationId}, handler=${handlerConversationId}`);

                                        // Always update per-conversation state
                                        const convState = getConversationState(handlerConversationId);
                                        updateConversationState(handlerConversationId, {
                                            streamingAssistantContent: convState.streamingAssistantContent + bufferedContent,
                                            streamStatus: "streaming",
                                        });

                                        // Only update global state if this is the active conversation
                                        if (handlerConversationId === activeConversationId) {
                                            console.log(`[AgentV3] Updating global streamingAssistantContent`);
                                            set((state) => ({
                                                streamingAssistantContent: state.streamingAssistantContent + bufferedContent,
                                                streamStatus: "streaming"
                                            }));
                                        } else {
                                            console.log(`[AgentV3] Skipping global update: handler=${handlerConversationId} != active=${activeConversationId}`);
                                        }
                                    }
                                }, TOKEN_BATCH_INTERVAL_MS);
                            }
                        },
                        onTextEnd: (event) => {
                            const { activeConversationId, updateConversationState, getConversationState } = get();

                            // Get per-conversation buffer and flush any remaining buffered content
                            const buffer = getDeltaBuffer(handlerConversationId);
                            if (buffer.textDeltaFlushTimer) {
                                clearTimeout(buffer.textDeltaFlushTimer);
                                buffer.textDeltaFlushTimer = null;
                            }
                            const remainingBuffer = buffer.textDeltaBuffer;
                            buffer.textDeltaBuffer = '';

                            const convState = getConversationState(handlerConversationId);
                            const fullText = event.data.full_text;
                            const finalContent = fullText || (convState.streamingAssistantContent + remainingBuffer);

                            // Add text_end event to timeline for proper rendering
                            const textEndEvent: AgentEvent<any> = {
                                type: "text_end",
                                data: { full_text: finalContent },
                            };
                            const updatedTimeline = appendSSEEventToTimeline(convState.timeline, textEndEvent);

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, {
                                streamingAssistantContent: finalContent,
                                timeline: updatedTimeline,
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({
                                    streamingAssistantContent: finalContent,
                                    timeline: updatedTimeline,
                                });
                            }
                        },
                        onClarificationAsked: (event) => {
                            const { activeConversationId, updateConversationState, getConversationState } = get();

                            // Add to timeline for inline rendering
                            const clarificationEvent: AgentEvent<ClarificationAskedEventData> = {
                                type: "clarification_asked",
                                data: event.data,
                            };
                            const convState = getConversationState(handlerConversationId);
                            const updatedTimeline = appendSSEEventToTimeline(convState.timeline, clarificationEvent);

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, {
                                timeline: updatedTimeline,
                                pendingClarification: event.data,
                                agentState: "awaiting_input",
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({
                                    timeline: updatedTimeline,
                                    pendingClarification: event.data,
                                    agentState: "awaiting_input",
                                });
                            }
                        },
                        onDecisionAsked: (event) => {
                            const { activeConversationId, updateConversationState, getConversationState } = get();

                            // Add to timeline for inline rendering
                            const decisionEvent: AgentEvent<DecisionAskedEventData> = {
                                type: "decision_asked",
                                data: event.data,
                            };
                            const convState = getConversationState(handlerConversationId);
                            const updatedTimeline = appendSSEEventToTimeline(convState.timeline, decisionEvent);

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, {
                                timeline: updatedTimeline,
                                pendingDecision: event.data,
                                agentState: "awaiting_input",
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({
                                    timeline: updatedTimeline,
                                    pendingDecision: event.data,
                                    agentState: "awaiting_input",
                                });
                            }
                        },
                        onDoomLoopDetected: (event) => {
                            const { activeConversationId, updateConversationState } = get();

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, {
                                doomLoopDetected: event.data,
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({ doomLoopDetected: event.data });
                            }
                        },
                        onEnvVarRequested: (event) => {
                            const { activeConversationId, updateConversationState, getConversationState } = get();

                            // Add to timeline for inline rendering
                            const envVarEvent: AgentEvent<EnvVarRequestedEventData> = {
                                type: "env_var_requested",
                                data: event.data,
                            };
                            const convState = getConversationState(handlerConversationId);
                            const updatedTimeline = appendSSEEventToTimeline(convState.timeline, envVarEvent);

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, {
                                timeline: updatedTimeline,
                                pendingEnvVarRequest: event.data,
                                agentState: "awaiting_input",
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({
                                    timeline: updatedTimeline,
                                    pendingEnvVarRequest: event.data,
                                    agentState: "awaiting_input",
                                });
                            }
                        },
                        onPermissionAsked: (event) => {
                            const { activeConversationId, updateConversationState, getConversationState } = get();

                            // Add to timeline for inline rendering
                            const permissionEvent: AgentEvent<PermissionAskedEventData> = {
                                type: "permission_asked",
                                data: event.data,
                            };
                            const convState = getConversationState(handlerConversationId);
                            const updatedTimeline = appendSSEEventToTimeline(convState.timeline, permissionEvent);

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, {
                                timeline: updatedTimeline,
                                pendingPermission: event.data,
                                agentState: "awaiting_input",
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({
                                    timeline: updatedTimeline,
                                    pendingPermission: event.data,
                                    agentState: "awaiting_input",
                                });
                            }
                        },
                        onPermissionReplied: (event) => {
                            const { activeConversationId, updateConversationState, getConversationState } = get();

                            // Add to timeline for inline rendering
                            const convState = getConversationState(handlerConversationId);
                            const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);

                            // Clear pending permission
                            updateConversationState(handlerConversationId, {
                                timeline: updatedTimeline,
                                pendingPermission: null,
                                agentState: event.data.granted ? "thinking" : "idle",
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({
                                    timeline: updatedTimeline,
                                    pendingPermission: null,
                                    agentState: event.data.granted ? "thinking" : "idle",
                                });
                            }
                        },
                        onDoomLoopIntervened: (event) => {
                            const { activeConversationId, updateConversationState, getConversationState } = get();

                            // Add to timeline
                            const convState = getConversationState(handlerConversationId);
                            const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);

                            // Clear doom loop state after intervention
                            updateConversationState(handlerConversationId, {
                                timeline: updatedTimeline,
                                doomLoopDetected: null,
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({
                                    timeline: updatedTimeline,
                                    doomLoopDetected: null,
                                });
                            }
                        },
                        onCostUpdate: (event) => {
                            const { activeConversationId, updateConversationState } = get();

                            // Update cost tracking state
                            const costData = event.data as CostUpdateEventData;
                            const costTracking: CostTrackingState = {
                                inputTokens: costData.input_tokens,
                                outputTokens: costData.output_tokens,
                                totalTokens: costData.total_tokens,
                                costUsd: costData.cost_usd,
                                model: costData.model,
                                lastUpdated: new Date().toISOString(),
                            };

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, {
                                costTracking,
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({ costTracking });
                            }
                        },
                        onArtifactCreated: (event) => {
                            const { activeConversationId, updateConversationState, getConversationState } = get();

                            // Handle artifact created event - add to timeline for rich display
                            console.log("[AgentV3] Artifact created event:", event.data);
                            const convState = getConversationState(handlerConversationId);
                            const updatedTimeline = appendSSEEventToTimeline(convState.timeline, event);

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, {
                                timeline: updatedTimeline,
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({ timeline: updatedTimeline });
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
                            console.log("[AgentV3] Title generated event:", data);

                            set((state) => {
                                // Update in conversations list
                                const updatedList = state.conversations.map((c) =>
                                    c.id === data.conversation_id ? { ...c, title: data.title } : c
                                );
                                return { conversations: updatedList };
                            });
                        },
                        onComplete: (event) => {
                            console.log(`[AgentV3] onComplete: handler=${handlerConversationId}, content preview="${(event.data as any)?.content?.substring(0, 50)}..."`);
                            const { activeConversationId, updateConversationState, getConversationState } = get();

                            // Clear all delta buffers on completion using helper function
                            clearAllDeltaBuffers();

                            const convState = getConversationState(handlerConversationId);

                            // Check if we already have a text_end event with content
                            // If so, skip adding assistant_message to avoid duplicate content
                            const hasTextEndWithContent = convState.timeline.some(
                                (e) => e.type === 'text_end' && 'fullText' in e && e.fullText?.trim()
                            );

                            let updatedTimeline = convState.timeline;
                            if (!hasTextEndWithContent) {
                                // Only add assistant_message if there's no text_end with content
                                const completeEvent: AgentEvent<CompleteEventData> = event as AgentEvent<CompleteEventData>;
                                updatedTimeline = appendSSEEventToTimeline(convState.timeline, completeEvent);
                            }

                            // Derive messages from updated timeline (no merging)
                            const newMessages = timelineToMessages(updatedTimeline);

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, {
                                timeline: updatedTimeline,
                                streamingAssistantContent: "",
                                isStreaming: false,
                                streamStatus: "idle",
                                agentState: "idle",
                                activeToolCalls: new Map(),
                                pendingToolsStack: [],
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({
                                    messages: newMessages,
                                    timeline: updatedTimeline,
                                    streamingAssistantContent: "",
                                    isStreaming: false,
                                    streamStatus: "idle",
                                    agentState: "idle",
                                    activeToolCalls: new Map(),
                                    pendingToolsStack: [],
                                });
                            }

                            // Broadcast completion to other tabs
                            tabSync.broadcastConversationCompleted(handlerConversationId);
                            tabSync.broadcastStreamingStateChanged(handlerConversationId, false, 'idle');
                        },
                        onError: (event) => {
                            const { activeConversationId, updateConversationState, getConversationState } = get();

                            // Clear delta buffers for this conversation on error
                            clearDeltaBuffers(handlerConversationId);

                            // Get current state for cleanup
                            const convState = getConversationState(handlerConversationId);

                            // Always update per-conversation state with full cleanup
                            updateConversationState(handlerConversationId, {
                                error: event.data.message,
                                isStreaming: false,
                                streamStatus: "error",
                                // Clear pending tools and streaming state
                                pendingToolsStack: [],
                                streamingAssistantContent: convState.streamingAssistantContent || '',
                                streamingThought: '',
                                isThinkingStreaming: false,
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({
                                    error: event.data.message,
                                    isStreaming: false,
                                    streamStatus: "error",
                                    pendingToolsStack: [],
                                    streamingThought: '',
                                    isThinkingStreaming: false,
                                });
                            }
                        },
                        onClose: () => {
                            const { activeConversationId, updateConversationState } = get();

                            // Clear delta buffers for this conversation on close
                            clearDeltaBuffers(handlerConversationId);

                            // Always update per-conversation state
                            updateConversationState(handlerConversationId, {
                                isStreaming: false,
                                streamStatus: "idle",
                            });

                            // Only update global state if this is the active conversation
                            if (handlerConversationId === activeConversationId) {
                                set({ isStreaming: false, streamStatus: "idle" });
                            }
                        },
                    };

                    // For new conversations, return ID immediately and start stream in background
                    // This allows the UI to navigate to the conversation URL right away
                    if (isNewConversation) {
                        agentService
                            .chat(
                                {
                                    conversation_id: conversationId!,
                                    message: content,
                                    project_id: projectId,
                                    attachment_ids: additionalHandlers?.attachmentIds,
                                },
                                handler
                            )
                            .catch(() => {
                                const { updateConversationState } = get();
                                updateConversationState(handlerConversationId, {
                                    error: "Failed to connect to chat stream",
                                    isStreaming: false,
                                    streamStatus: "error",
                                });
                                set({
                                    error: "Failed to connect to chat stream",
                                    isStreaming: false,
                                    streamStatus: "error",
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
                                attachment_ids: additionalHandlers?.attachmentIds,
                            },
                            handler
                        );
                        return conversationId!;
                    } catch (_e) {
                        const { updateConversationState } = get();
                        updateConversationState(handlerConversationId, {
                            error: "Failed to connect to chat stream",
                            isStreaming: false,
                            streamStatus: "error",
                        });
                        set({
                            error: "Failed to connect to chat stream",
                            isStreaming: false,
                            streamStatus: "error",
                        });
                        return null;
                    }
                },

                abortStream: (conversationId?: string) => {
                    const targetConvId = conversationId || get().activeConversationId;
                    if (targetConvId) {
                        agentService.stopChat(targetConvId);

                        // Update conversation-specific state
                        const { updateConversationState, activeConversationId } = get();
                        updateConversationState(targetConvId, {
                            isStreaming: false,
                            streamStatus: 'idle',
                        });

                        // Also update global state if this is active conversation
                        if (targetConvId === activeConversationId) {
                            set({ isStreaming: false, streamStatus: "idle" });
                        }
                    }
                },

                respondToClarification: async (requestId, answer) => {
                    console.log("Responding to clarification", requestId, answer);
                    const { activeConversationId } = get();

                    try {
                        // Ensure WebSocket is connected before responding
                        // This is critical for receiving agent responses after page refresh
                        if (!agentService.isConnected()) {
                            console.log("[agentV3] Connecting WebSocket before HITL response...");
                            await agentService.connect();
                        }

                        // Subscribe to the conversation to receive responses
                        if (activeConversationId) {
                            const simpleHandler: AgentStreamHandler = {
                                onTextDelta: (event) => {
                                    const delta = event.data.delta;
                                    if (delta) {
                                        set((state) => ({
                                            streamingAssistantContent: state.streamingAssistantContent + delta,
                                            streamStatus: "streaming"
                                        }));
                                    }
                                },
                                onTextEnd: (event) => {
                                    const fullText = event.data.full_text;
                                    if (fullText) {
                                        set({ streamingAssistantContent: fullText });
                                    }
                                },
                                onComplete: (event) => {
                                    set((state) => {
                                        const completeEvent: AgentEvent<CompleteEventData> = event as AgentEvent<CompleteEventData>;
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, completeEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            messages: timelineToMessages(updatedTimeline),
                                            isStreaming: false,
                                            streamStatus: "idle",
                                            agentState: "idle",
                                        };
                                    });
                                },
                                onError: (event) => {
                                    console.error("[agentV3] HITL response error:", event.data);
                                    set({
                                        error: event.data.message || "Agent error",
                                        isStreaming: false,
                                        streamStatus: "error",
                                        agentState: "idle",
                                    });
                                },
                                onThought: (event) => {
                                    set((state) => {
                                        const thoughtEvent: AgentEvent<ThoughtEventData> = event as AgentEvent<ThoughtEventData>;
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, thoughtEvent);
                                        return {
                                            currentThought: event.data.thought || "",
                                            timeline: updatedTimeline,
                                            agentState: "thinking",
                                        };
                                    });
                                },
                                onAct: (event) => {
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, event);
                                        return {
                                            timeline: updatedTimeline,
                                            agentState: "acting",
                                        };
                                    });
                                },
                                onObserve: (event) => {
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, event);
                                        return {
                                            timeline: updatedTimeline,
                                            agentState: "observing",
                                        };
                                    });
                                },
                                // HITL event handlers for nested requests
                                onClarificationAsked: (event) => {
                                    const clarificationEvent: AgentEvent<ClarificationAskedEventData> = {
                                        type: "clarification_asked",
                                        data: event.data,
                                    };
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, clarificationEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            pendingClarification: event.data,
                                            agentState: "awaiting_input",
                                        };
                                    });
                                },
                                onDecisionAsked: (event) => {
                                    const decisionEvent: AgentEvent<DecisionAskedEventData> = {
                                        type: "decision_asked",
                                        data: event.data,
                                    };
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, decisionEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            pendingDecision: event.data,
                                            agentState: "awaiting_input",
                                        };
                                    });
                                },
                                onEnvVarRequested: (event) => {
                                    const envVarEvent: AgentEvent<EnvVarRequestedEventData> = {
                                        type: "env_var_requested",
                                        data: event.data,
                                    };
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, envVarEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            pendingEnvVarRequest: event.data,
                                            agentState: "awaiting_input",
                                        };
                                    });
                                },
                                onPermissionAsked: (event) => {
                                    const permissionEvent: AgentEvent<PermissionAskedEventData> = {
                                        type: "permission_asked",
                                        data: event.data,
                                    };
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, permissionEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            pendingPermission: event.data,
                                            agentState: "awaiting_input",
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
                                    set({ costTracking });
                                },
                            };
                            agentService.subscribe(activeConversationId, simpleHandler);
                            console.log("[agentV3] Subscribed to conversation:", activeConversationId);
                        }

                        await agentService.respondToClarification(requestId, answer);
                        // CRITICAL: Clear delta buffers before resuming streaming
                        clearAllDeltaBuffers();
                        // Update timeline HITL event status and clear pending state
                        set((state) => ({
                            timeline: updateHITLEventInTimeline(
                                state.timeline,
                                requestId,
                                'clarification_asked',
                                { answered: true, answer }
                            ),
                            pendingClarification: null,
                            agentState: "thinking",
                            isStreaming: true,
                            streamStatus: "streaming",
                            streamingAssistantContent: ""
                        }));

                        // Broadcast HITL state change to other tabs
                        if (activeConversationId) {
                            tabSync.broadcastHITLStateChanged(activeConversationId, false, 'clarification');
                        }
                    } catch (error) {
                        console.error("Failed to respond to clarification:", error);
                        set({ agentState: "idle", isStreaming: false, streamStatus: "idle" });
                    }
                },

                respondToDecision: async (requestId, decision) => {
                    console.log("Responding to decision", requestId, decision);
                    const { activeConversationId } = get();

                    try {
                        // Ensure WebSocket is connected before responding
                        if (!agentService.isConnected()) {
                            console.log("[agentV3] Connecting WebSocket before HITL response...");
                            await agentService.connect();
                        }

                        // Subscribe to the conversation to receive responses
                        if (activeConversationId) {
                            const simpleHandler: AgentStreamHandler = {
                                onTextDelta: (event) => {
                                    const delta = event.data.delta;
                                    if (delta) {
                                        set((state) => ({
                                            streamingAssistantContent: state.streamingAssistantContent + delta,
                                            streamStatus: "streaming"
                                        }));
                                    }
                                },
                                onTextEnd: (event) => {
                                    const fullText = event.data.full_text;
                                    if (fullText) {
                                        set({ streamingAssistantContent: fullText });
                                    }
                                },
                                onComplete: (event) => {
                                    set((state) => {
                                        const completeEvent: AgentEvent<CompleteEventData> = event as AgentEvent<CompleteEventData>;
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, completeEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            messages: timelineToMessages(updatedTimeline),
                                            isStreaming: false,
                                            streamStatus: "idle",
                                            agentState: "idle",
                                        };
                                    });
                                },
                                onError: (event) => {
                                    console.error("[agentV3] HITL response error:", event.data);
                                    set({
                                        error: event.data.message || "Agent error",
                                        isStreaming: false,
                                        streamStatus: "error",
                                        agentState: "idle",
                                    });
                                },
                                onThought: (event) => {
                                    set((state) => {
                                        const thoughtEvent: AgentEvent<ThoughtEventData> = event as AgentEvent<ThoughtEventData>;
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, thoughtEvent);
                                        return {
                                            currentThought: event.data.thought || "",
                                            timeline: updatedTimeline,
                                            agentState: "thinking",
                                        };
                                    });
                                },
                                onAct: (event) => {
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, event);
                                        return {
                                            timeline: updatedTimeline,
                                            agentState: "acting",
                                        };
                                    });
                                },
                                onObserve: (event) => {
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, event);
                                        return {
                                            timeline: updatedTimeline,
                                            agentState: "observing",
                                        };
                                    });
                                },
                                // HITL event handlers for nested requests
                                onClarificationAsked: (event) => {
                                    const clarificationEvent: AgentEvent<ClarificationAskedEventData> = {
                                        type: "clarification_asked",
                                        data: event.data,
                                    };
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, clarificationEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            pendingClarification: event.data,
                                            agentState: "awaiting_input",
                                        };
                                    });
                                },
                                onDecisionAsked: (event) => {
                                    const decisionEvent: AgentEvent<DecisionAskedEventData> = {
                                        type: "decision_asked",
                                        data: event.data,
                                    };
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, decisionEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            pendingDecision: event.data,
                                            agentState: "awaiting_input",
                                        };
                                    });
                                },
                                onEnvVarRequested: (event) => {
                                    const envVarEvent: AgentEvent<EnvVarRequestedEventData> = {
                                        type: "env_var_requested",
                                        data: event.data,
                                    };
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, envVarEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            pendingEnvVarRequest: event.data,
                                            agentState: "awaiting_input",
                                        };
                                    });
                                },
                                onPermissionAsked: (event) => {
                                    const permissionEvent: AgentEvent<PermissionAskedEventData> = {
                                        type: "permission_asked",
                                        data: event.data,
                                    };
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, permissionEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            pendingPermission: event.data,
                                            agentState: "awaiting_input",
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
                                    set({ costTracking });
                                },
                            };
                            agentService.subscribe(activeConversationId, simpleHandler);
                            console.log("[agentV3] Subscribed to conversation:", activeConversationId);
                        }

                        await agentService.respondToDecision(requestId, decision);
                        // CRITICAL: Clear delta buffers before resuming streaming
                        clearAllDeltaBuffers();
                        // Update timeline HITL event status and clear pending state
                        set((state) => ({
                            timeline: updateHITLEventInTimeline(
                                state.timeline,
                                requestId,
                                'decision_asked',
                                { answered: true, decision }
                            ),
                            pendingDecision: null,
                            agentState: "thinking",
                            isStreaming: true,
                            streamStatus: "streaming",
                            streamingAssistantContent: ""
                        }));

                        // Broadcast HITL state change to other tabs
                        if (activeConversationId) {
                            tabSync.broadcastHITLStateChanged(activeConversationId, false, 'decision');
                        }
                    } catch (error) {
                        console.error("Failed to respond to decision:", error);
                        set({ agentState: "idle", isStreaming: false, streamStatus: "idle" });
                    }
                },

                respondToEnvVar: async (requestId, values) => {
                    console.log("Responding to env var request", requestId, values);
                    const { activeConversationId } = get();

                    try {
                        // Ensure WebSocket is connected before responding
                        if (!agentService.isConnected()) {
                            console.log("[agentV3] Connecting WebSocket before HITL response...");
                            await agentService.connect();
                        }

                        // Subscribe to the conversation to receive responses
                        if (activeConversationId) {
                            const simpleHandler: AgentStreamHandler = {
                                onTextDelta: (event) => {
                                    const delta = event.data.delta;
                                    if (delta) {
                                        set((state) => ({
                                            streamingAssistantContent: state.streamingAssistantContent + delta,
                                            streamStatus: "streaming"
                                        }));
                                    }
                                },
                                onTextEnd: (event) => {
                                    const fullText = event.data.full_text;
                                    if (fullText) {
                                        set({ streamingAssistantContent: fullText });
                                    }
                                },
                                onComplete: (event) => {
                                    set((state) => {
                                        const completeEvent: AgentEvent<CompleteEventData> = event as AgentEvent<CompleteEventData>;
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, completeEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            messages: timelineToMessages(updatedTimeline),
                                            isStreaming: false,
                                            streamStatus: "idle",
                                            agentState: "idle",
                                        };
                                    });
                                },
                                onError: (event) => {
                                    console.error("[agentV3] HITL response error:", event.data);
                                    set({
                                        error: event.data.message || "Agent error",
                                        isStreaming: false,
                                        streamStatus: "error",
                                        agentState: "idle",
                                    });
                                },
                                onThought: (event) => {
                                    set((state) => {
                                        const thoughtEvent: AgentEvent<ThoughtEventData> = event as AgentEvent<ThoughtEventData>;
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, thoughtEvent);
                                        return {
                                            currentThought: event.data.thought || "",
                                            timeline: updatedTimeline,
                                            agentState: "thinking",
                                        };
                                    });
                                },
                                onAct: (event) => {
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, event);
                                        return {
                                            timeline: updatedTimeline,
                                            agentState: "acting",
                                        };
                                    });
                                },
                                onObserve: (event) => {
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, event);
                                        return {
                                            timeline: updatedTimeline,
                                            agentState: "observing",
                                        };
                                    });
                                },
                                // HITL event handlers for nested requests
                                onClarificationAsked: (event) => {
                                    const clarificationEvent: AgentEvent<ClarificationAskedEventData> = {
                                        type: "clarification_asked",
                                        data: event.data,
                                    };
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, clarificationEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            pendingClarification: event.data,
                                            agentState: "awaiting_input",
                                        };
                                    });
                                },
                                onDecisionAsked: (event) => {
                                    const decisionEvent: AgentEvent<DecisionAskedEventData> = {
                                        type: "decision_asked",
                                        data: event.data,
                                    };
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, decisionEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            pendingDecision: event.data,
                                            agentState: "awaiting_input",
                                        };
                                    });
                                },
                                onEnvVarRequested: (event) => {
                                    const envVarEvent: AgentEvent<EnvVarRequestedEventData> = {
                                        type: "env_var_requested",
                                        data: event.data,
                                    };
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, envVarEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            pendingEnvVarRequest: event.data,
                                            agentState: "awaiting_input",
                                        };
                                    });
                                },
                                onPermissionAsked: (event) => {
                                    const permissionEvent: AgentEvent<PermissionAskedEventData> = {
                                        type: "permission_asked",
                                        data: event.data,
                                    };
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, permissionEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            pendingPermission: event.data,
                                            agentState: "awaiting_input",
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
                                    set({ costTracking });
                                },
                            };
                            agentService.subscribe(activeConversationId, simpleHandler);
                            console.log("[agentV3] Subscribed to conversation:", activeConversationId);
                        }

                        await agentService.respondToEnvVar(requestId, values);
                        // CRITICAL: Clear delta buffers before resuming streaming
                        clearAllDeltaBuffers();
                        // Update timeline HITL event status and clear pending state
                        set((state) => ({
                            timeline: updateHITLEventInTimeline(
                                state.timeline,
                                requestId,
                                'env_var_requested',
                                { answered: true, values }
                            ),
                            pendingEnvVarRequest: null,
                            agentState: "thinking",
                            isStreaming: true,
                            streamStatus: "streaming",
                            streamingAssistantContent: ""
                        }));

                        // Broadcast HITL state change to other tabs
                        if (activeConversationId) {
                            tabSync.broadcastHITLStateChanged(activeConversationId, false, 'env_var');
                        }
                    } catch (error) {
                        console.error("Failed to respond to env var request:", error);
                        set({ agentState: "idle", isStreaming: false, streamStatus: "idle" });
                    }
                },

                respondToPermission: async (requestId, granted) => {
                    console.log("Responding to permission request", requestId, granted);
                    const { activeConversationId } = get();

                    try {
                        // Ensure WebSocket is connected before responding
                        if (!agentService.isConnected()) {
                            console.log("[agentV3] Connecting WebSocket before permission response...");
                            await agentService.connect();
                        }

                        // Subscribe to the conversation to receive responses
                        if (activeConversationId) {
                            const simpleHandler: AgentStreamHandler = {
                                onTextDelta: (event) => {
                                    const delta = event.data.delta;
                                    if (delta) {
                                        set((state) => ({
                                            streamingAssistantContent: state.streamingAssistantContent + delta,
                                            streamStatus: "streaming"
                                        }));
                                    }
                                },
                                onTextEnd: (event) => {
                                    const fullText = event.data.full_text;
                                    if (fullText) {
                                        set({ streamingAssistantContent: fullText });
                                    }
                                },
                                onComplete: (event) => {
                                    set((state) => {
                                        const completeEvent: AgentEvent<CompleteEventData> = event as AgentEvent<CompleteEventData>;
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, completeEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            messages: timelineToMessages(updatedTimeline),
                                            isStreaming: false,
                                            streamStatus: "idle",
                                            agentState: "idle",
                                        };
                                    });
                                },
                                onError: (event) => {
                                    console.error("[agentV3] Permission response error:", event.data);
                                    set({
                                        error: event.data.message || "Agent error",
                                        isStreaming: false,
                                        streamStatus: "error",
                                        agentState: "idle",
                                    });
                                },
                                onThought: (event) => {
                                    set((state) => {
                                        const thoughtEvent: AgentEvent<ThoughtEventData> = event as AgentEvent<ThoughtEventData>;
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, thoughtEvent);
                                        return {
                                            currentThought: event.data.thought || "",
                                            timeline: updatedTimeline,
                                            agentState: "thinking",
                                        };
                                    });
                                },
                                onAct: (event) => {
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, event);
                                        return {
                                            timeline: updatedTimeline,
                                            agentState: "acting",
                                        };
                                    });
                                },
                                onObserve: (event) => {
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, event);
                                        return {
                                            timeline: updatedTimeline,
                                            agentState: "observing",
                                        };
                                    });
                                },
                                // HITL event handlers for nested requests
                                onClarificationAsked: (event) => {
                                    const clarificationEvent: AgentEvent<ClarificationAskedEventData> = {
                                        type: "clarification_asked",
                                        data: event.data,
                                    };
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, clarificationEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            pendingClarification: event.data,
                                            agentState: "awaiting_input",
                                        };
                                    });
                                },
                                onDecisionAsked: (event) => {
                                    const decisionEvent: AgentEvent<DecisionAskedEventData> = {
                                        type: "decision_asked",
                                        data: event.data,
                                    };
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, decisionEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            pendingDecision: event.data,
                                            agentState: "awaiting_input",
                                        };
                                    });
                                },
                                onEnvVarRequested: (event) => {
                                    const envVarEvent: AgentEvent<EnvVarRequestedEventData> = {
                                        type: "env_var_requested",
                                        data: event.data,
                                    };
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, envVarEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            pendingEnvVarRequest: event.data,
                                            agentState: "awaiting_input",
                                        };
                                    });
                                },
                                onPermissionAsked: (event) => {
                                    const permissionEvent: AgentEvent<PermissionAskedEventData> = {
                                        type: "permission_asked",
                                        data: event.data,
                                    };
                                    set((state) => {
                                        const updatedTimeline = appendSSEEventToTimeline(state.timeline, permissionEvent);
                                        return {
                                            timeline: updatedTimeline,
                                            pendingPermission: event.data,
                                            agentState: "awaiting_input",
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
                                    set({ costTracking });
                                },
                            };
                            agentService.subscribe(activeConversationId, simpleHandler);
                            console.log("[agentV3] Subscribed to conversation:", activeConversationId);
                        }

                        await agentService.respondToPermission(requestId, granted);
                        // CRITICAL: Clear delta buffers before resuming streaming
                        clearAllDeltaBuffers();
                        // Update timeline HITL event status and clear pending state
                        set((state) => ({
                            timeline: updateHITLEventInTimeline(
                                state.timeline,
                                requestId,
                                'permission_asked',
                                { answered: true, granted }
                            ),
                            pendingPermission: null,
                            agentState: granted ? "thinking" : "idle",
                            isStreaming: granted,
                            streamStatus: granted ? "streaming" : "idle",
                            streamingAssistantContent: ""
                        }));

                        // Broadcast HITL state change to other tabs
                        if (activeConversationId) {
                            tabSync.broadcastHITLStateChanged(activeConversationId, false, 'permission');
                        }
                    } catch (error) {
                        console.error("Failed to respond to permission request:", error);
                        set({ agentState: "idle", isStreaming: false, streamStatus: "idle" });
                    }
                },

                /**
                 * Load pending HITL (Human-In-The-Loop) requests for a conversation
                 * This is used to restore dialog state after page refresh
                 * 
                 * Shows dialogs for all pending requests. If Agent crashed/restarted,
                 * the recovery service will handle it when Worker restarts.
                 */
                loadPendingHITL: async (conversationId) => {
                    console.log("[agentV3] Loading pending HITL requests for conversation:", conversationId);
                    try {
                        const response = await agentService.getPendingHITLRequests(conversationId);
                        console.log("[agentV3] Pending HITL response:", response);

                        if (response.requests.length === 0) {
                            console.log("[agentV3] No pending HITL requests");
                            return;
                        }

                        // Process each pending request and restore dialog state
                        for (const request of response.requests) {
                            console.log("[agentV3] Restoring pending HITL request:", request.request_type, request.id);

                            switch (request.request_type) {
                                case "clarification":
                                    set({
                                        pendingClarification: {
                                            request_id: request.id,
                                            question: request.question,
                                            clarification_type: request.metadata?.clarification_type || "custom",
                                            options: request.options || [],
                                            allow_custom: request.metadata?.allow_custom ?? true,
                                            context: request.context || {},
                                        },
                                        agentState: "awaiting_input",
                                    });
                                    break;

                                case "decision":
                                    set({
                                        pendingDecision: {
                                            request_id: request.id,
                                            question: request.question,
                                            decision_type: request.metadata?.decision_type || "custom",
                                            options: request.options || [],
                                            allow_custom: request.metadata?.allow_custom ?? true,
                                            context: request.context || {},
                                        },
                                        agentState: "awaiting_input",
                                    });
                                    break;

                                case "env_var":
                                    // Use new format directly: name, label, required
                                    // Data comes from request.options (stored in DB)
                                    const fields = request.options || [];

                                    set({
                                        pendingEnvVarRequest: {
                                            request_id: request.id,
                                            tool_name: request.metadata?.tool_name || "unknown",
                                            fields: fields,
                                            message: request.question,
                                            context: request.context || {},
                                        },
                                        agentState: "awaiting_input",
                                    });
                                    break;
                            }

                            // Only restore the first pending request
                            // (user should answer one at a time)
                            break;
                        }
                    } catch (error) {
                        console.error("[agentV3] Failed to load pending HITL requests:", error);
                        // Don't throw - this is a recovery mechanism, not critical
                    }
                },

                togglePlanPanel: () =>
                    set((state) => ({ showPlanPanel: !state.showPlanPanel })),
                toggleHistorySidebar: () =>
                    set((state) => ({ showHistorySidebar: !state.showHistorySidebar })),

                setLeftSidebarWidth: (width: number) => set({ leftSidebarWidth: width }),
                setRightPanelWidth: (width: number) => set({ rightPanelWidth: width }),

                togglePlanMode: async () => {
                    const { isPlanMode, activeConversationId } = get();
                    if (!activeConversationId) return;

                    try {
                        if (isPlanMode) {
                            const status = await planService.getPlanModeStatus(
                                activeConversationId
                            );
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
                                title: "Plan",
                            });
                            set({ isPlanMode: true });
                        }
                    } catch (error) {
                        console.error("Failed to toggle plan mode", error);
                    }
                },

                clearError: () => set({ error: null }),
            }),
            {
                name: 'agent-v3-storage',
                partialize: (state) => ({
                    // Only persist UI preferences, not conversation/message data
                    showHistorySidebar: state.showHistorySidebar,
                    leftSidebarWidth: state.leftSidebarWidth,
                    rightPanelWidth: state.rightPanelWidth,
                }),
            }))
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
                    logger.info(`[TabSync] Conversation ${msg.conversationId} completed in another tab, reloading...`);
                    // Find the project ID from conversations list
                    const conv = state.conversations.find(c => c.id === msg.conversationId);
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
                    conversations: s.conversations.filter(c => c.id !== msg.conversationId),
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
                    conversations: s.conversations.map(c =>
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
export const useMessages = () => useAgentV3Store((state) => {
    // For now, return stored messages for backward compatibility
    // TODO: Switch to computed derivation after verifying all consumers work correctly
    return state.messages;
});
