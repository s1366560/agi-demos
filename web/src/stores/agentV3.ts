import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
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
} from "../types/agent";
import { agentService } from "../services/agentService";
import { agentEventReplayService } from "../services/agentEventReplayService";
import { planService } from "../services/planService";
import { v4 as uuidv4 } from "uuid";
import { appendSSEEventToTimeline } from "../utils/sseEventAdapter";

/**
 * Token delta batching configuration
 * Batches rapid token updates to reduce re-renders and improve performance
 */
const TOKEN_BATCH_INTERVAL_MS = 50; // Batch tokens every 50ms for smooth streaming
const THOUGHT_BATCH_INTERVAL_MS = 50; // Same for thought deltas

// Token batching state (outside store to avoid triggering renders)
let textDeltaBuffer = '';
let textDeltaFlushTimer: ReturnType<typeof setTimeout> | null = null;
let thoughtDeltaBuffer = '';
let thoughtDeltaFlushTimer: ReturnType<typeof setTimeout> | null = null;

/**
 * Additional handlers that can be injected into sendMessage
 * for external integrations (e.g., sandbox tool detection)
 */
export interface AdditionalAgentHandlers {
    onAct?: (event: AgentEvent<ActEventData>) => void;
    onObserve?: (event: AgentEvent<ObserveEventData>) => void;
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

    // Timeline State (Primary data source - events rendered in natural order)
    timeline: TimelineEvent[];

    // Messages State (Derived from timeline for backward compatibility)
    messages: Message[];
    isLoadingHistory: boolean;  // For initial message load (shows loading in sidebar)
    isLoadingEarlier: boolean;  // For pagination (does NOT show loading in sidebar)
    hasEarlier: boolean;  // Whether there are earlier messages to load
    earliestLoadedSequence: number | null;  // For pagination

    // Stream State
    isStreaming: boolean;
    streamStatus: "idle" | "connecting" | "streaming" | "error";
    error: string | null;
    streamingAssistantContent: string; // Streaming content (used for real-time display)

    // Agent Execution State
    agentState: "idle" | "thinking" | "acting" | "observing" | "awaiting_input";
    currentThought: string;
    streamingThought: string; // For streaming thought_delta content
    isThinkingStreaming: boolean; // Whether thought is currently streaming
    activeToolCalls: Map<
        string,
        ToolCall & { status: "running" | "success" | "failed"; startTime: number }
    >;
    pendingToolsStack: string[]; // Track order of tool executions

    // Plan State
    workPlan: WorkPlan | null;
    isPlanMode: boolean;
    executionPlan: ExecutionPlan | null;

    // UI State
    showPlanPanel: boolean;
    showHistorySidebar: boolean;
    leftSidebarWidth: number;
    rightPanelWidth: number;

    // Interactivity
    pendingClarification: any; // Pending clarification request from agent
    pendingDecision: any; // Using any for brevity in this update
    doomLoopDetected: any;
    pendingEnvVarRequest: any; // Pending environment variable request from agent

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
    abortStream: () => void;
    togglePlanPanel: () => void;
    toggleHistorySidebar: () => void;
    setLeftSidebarWidth: (width: number) => void;
    setRightPanelWidth: (width: number) => void;
    respondToClarification: (requestId: string, answer: string) => Promise<void>;
    respondToDecision: (requestId: string, decision: string) => Promise<void>;
    respondToEnvVar: (requestId: string, values: Record<string, string>) => Promise<void>;
    togglePlanMode: () => Promise<void>;
    clearError: () => void;
}

export const useAgentV3Store = create<AgentV3State>()(
    devtools(
        persist(
            (set, get) => ({
                conversations: [],
                activeConversationId: null,

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
                doomLoopDetected: null,
                pendingEnvVarRequest: null,

                setActiveConversation: (id) => set({ activeConversationId: id }),

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
                        // Remove from local state
                        set((state) => ({
                            conversations: state.conversations.filter(
                                (c) => c.id !== conversationId
                            ),
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
                        }));
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
                        // Add to conversations list and set as active
                        set((state) => ({
                            conversations: [newConv, ...state.conversations],
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
                        }));
                        return newConv.id;
                    } catch (error) {
                        console.error("Failed to create conversation", error);
                        set({ error: "Failed to create conversation" });
                        return null;
                    }
                },

                loadMessages: async (conversationId, projectId) => {
                    set({
                        isLoadingHistory: true,
                        timeline: [],      // Clear timeline
                        messages: [],
                        currentThought: "",
                        streamingThought: "",
                        isThinkingStreaming: false,
                        workPlan: null,
                        executionPlan: null,
                        agentState: "idle",
                        hasEarlier: false,
                        earliestLoadedSequence: null,
                    });
                    try {
                        // Parallelize independent API calls (async-parallel)
                        const [response, planStatus, execStatus] = await Promise.all([
                            agentService.getConversationMessages(
                                conversationId,
                                projectId,
                                200  // Load latest 200 messages (increased from 50 to show more assistant_message events)
                            ) as Promise<any>,
                            // Use catch to prevent one failure from blocking others
                            planService.getPlanModeStatus(conversationId).catch(() => null),
                            agentService.getExecutionStatus(conversationId).catch(() => null),
                        ]);

                        if (get().activeConversationId !== conversationId) {
                            console.log("Conversation changed during load, ignoring result");
                            return;
                        }

                        // Store the raw timeline and derive messages (no merging)
                        const messages = timelineToMessages(response.timeline);
                        const firstSequence = response.timeline[0]?.sequenceNumber ?? null;

                        set({
                            timeline: response.timeline,
                            messages: messages,
                            isLoadingHistory: false,
                            hasEarlier: response.has_more ?? false,
                            earliestLoadedSequence: firstSequence,
                            // Set plan mode if successfully fetched
                            ...(planStatus ? { isPlanMode: planStatus.is_in_plan_mode } : {}),
                        });

                        // Check execution status and replay events if needed
                        if (execStatus && execStatus.is_running && execStatus.last_sequence > 0) {
                            console.log(
                                `Conversation ${conversationId} is running, replaying events...`
                            );

                            // Create a temporary handler for replay
                            const replayHandler: AgentStreamHandler = {
                                onThought: (event) => {
                                    const thought = event.data.thought;
                                    // Skip empty thoughts (REASONING_START events)
                                    if (!thought || thought.trim() === "") return;
                                    set((state) => {
                                        const lastMsg = state.messages[state.messages.length - 1];
                                        if (!lastMsg || lastMsg.role !== "assistant") return state;
                                        const thoughts =
                                            (lastMsg.metadata?.thoughts as string[]) || [];
                                        return {
                                            currentThought: state.currentThought + "\n" + thought,
                                            messages: state.messages.map((m, i) =>
                                                i === state.messages.length - 1
                                                    ? {
                                                        ...m,
                                                        metadata: {
                                                            ...m.metadata,
                                                            thoughts: [...thoughts, thought],
                                                        },
                                                    }
                                                    : m
                                            ),
                                        };
                                    });
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
                                onObserve: (_event) => {
                                    set((state) => {
                                        const stack = [...state.pendingToolsStack];
                                        stack.pop(); // Remove processed tool from stack
                                        return { pendingToolsStack: stack, agentState: "observing" };
                                    });
                                },
                                onComplete: () => {
                                    set({
                                        isStreaming: false,
                                        agentState: "idle",
                                        activeToolCalls: new Map(),
                                    });
                                },
                                onError: (event) => {
                                    set({ error: event.data.message });
                                },
                            };

                            // Replay events
                            await agentEventReplayService.replayEvents(
                                conversationId,
                                replayHandler,
                                0
                            );

                            set({ isStreaming: true, agentState: "thinking" });
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

                        // Prepend new events to existing timeline (no merging)
                        const newTimeline = [...response.timeline, ...timeline];
                        const newMessages = timelineToMessages(newTimeline);
                        const newFirstSequence = response.timeline[0]?.sequenceNumber ?? null;

                        set({
                            timeline: newTimeline,
                            messages: newMessages,
                            isLoadingEarlier: false,
                            hasEarlier: response.has_more ?? false,
                            earliestLoadedSequence: newFirstSequence,
                        });

                        console.log('[AgentV3] Loaded earlier messages, total timeline length:', newTimeline.length);
                        return true;
                    } catch (error) {
                        console.error('[AgentV3] Failed to load earlier messages:', error);
                        set({ isLoadingEarlier: false });
                        return false;
                    }
                },

                sendMessage: async (content, projectId, additionalHandlers) => {
                    const { activeConversationId, messages, timeline } = get();

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
                            set({
                                activeConversationId: conversationId,
                                conversations: [newConv, ...get().conversations],
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

                    set({
                        messages: [...messages, userMsg],
                        timeline: [...timeline, userMessageEvent],
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
                    });

                    // Define handler first (needed for both new and existing conversations)
                    const handler: AgentStreamHandler = {
                        onMessage: (_event) => { },
                        onThoughtDelta: (event) => {
                            // Streaming thought - batch updates for performance
                            const delta = event.data.delta;
                            if (!delta) return;

                            // Accumulate deltas in buffer
                            thoughtDeltaBuffer += delta;

                            // Flush buffer on timer to batch rapid updates
                            if (!thoughtDeltaFlushTimer) {
                                thoughtDeltaFlushTimer = setTimeout(() => {
                                    const bufferedContent = thoughtDeltaBuffer;
                                    thoughtDeltaBuffer = '';
                                    thoughtDeltaFlushTimer = null;

                                    if (bufferedContent) {
                                        set((state) => ({
                                            streamingThought: state.streamingThought + bufferedContent,
                                            isThinkingStreaming: true,
                                            agentState: "thinking",
                                        }));
                                    }
                                }, THOUGHT_BATCH_INTERVAL_MS);
                            }
                        },
                        onThought: (event) => {
                            const newThought = event.data.thought;

                            // Complete thought - add to timeline and reset streaming state
                            set((state) => {
                                // Append thought event to timeline using SSE adapter
                                const thoughtEvent: AgentEvent<ThoughtEventData> = event as AgentEvent<ThoughtEventData>;
                                const updatedTimeline = appendSSEEventToTimeline(state.timeline, thoughtEvent);

                                // Skip empty thoughts (REASONING_START events)
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
                        },
                        onWorkPlan: (event) => {
                            set((state) => {
                                // Append work_plan event to timeline using SSE adapter
                                const workPlanEvent: AgentEvent<WorkPlanEventData> = event as AgentEvent<WorkPlanEventData>;
                                const updatedTimeline = appendSSEEventToTimeline(state.timeline, workPlanEvent);

                                return {
                                    workPlan: {
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
                                    },
                                    timeline: updatedTimeline,
                                };
                            });
                        },
                        onStepStart: (event) => {
                            set((state) => {
                                // Append step_start event to timeline using SSE adapter
                                const stepStartEvent: AgentEvent<StepStartEventData> = event as AgentEvent<StepStartEventData>;
                                const updatedTimeline = appendSSEEventToTimeline(state.timeline, stepStartEvent);

                                if (!state.workPlan) {
                                    return { timeline: updatedTimeline };
                                }
                                const newPlan = { ...state.workPlan };
                                newPlan.current_step_index = event.data.current_step;
                                return { workPlan: newPlan, agentState: "acting", timeline: updatedTimeline };
                            });
                        },
                        onStepEnd: (_event) => { },
                        onPlanExecutionStart: (event) => {
                            set((state) => {
                                const executionPlanEvent: AgentEvent<PlanExecutionStartEvent> = event;
                                const updatedTimeline = appendSSEEventToTimeline(state.timeline, executionPlanEvent);
                                // Access data from event.data.data (nested structure)
                                const eventData = (event as any).data || {};
                                // Create a minimal execution plan from the event data
                                const newExecutionPlan: ExecutionPlan = {
                                    id: eventData.plan_id || `plan-${Date.now()}`,
                                    conversation_id: state.activeConversationId || "",
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
                                return {
                                    executionPlan: newExecutionPlan,
                                    timeline: updatedTimeline,
                                };
                            });
                        },
                        onPlanExecutionComplete: (event) => {
                            set((state) => {
                                const executionPlanEvent: AgentEvent<PlanExecutionCompleteEvent> = event;
                                const updatedTimeline = appendSSEEventToTimeline(state.timeline, executionPlanEvent);
                                // Access data from event.data
                                const eventData = (event as any).data || {};
                                return {
                                    executionPlan: state.executionPlan
                                        ? {
                                            ...state.executionPlan,
                                            status: eventData.status || state.executionPlan.status,
                                            completed_steps: Array(eventData.completed_steps || 0).fill(""),
                                            failed_steps: Array(eventData.failed_steps || 0).fill(""),
                                            progress_percentage: (eventData.completed_steps || 0) / (state.executionPlan.steps.length || 1),
                                            is_complete: eventData.status === "completed" || eventData.status === "failed",
                                        }
                                        : null,
                                    timeline: updatedTimeline,
                                };
                            });
                        },
                        onReflectionComplete: (event) => {
                            set((state) => {
                                const reflectionEvent: AgentEvent<ReflectionCompleteEvent> = event;
                                const updatedTimeline = appendSSEEventToTimeline(state.timeline, reflectionEvent);
                                return {
                                    timeline: updatedTimeline,
                                };
                            });
                        },

                        onAct: (event) => {
                            set((state) => {
                                // Append act event to timeline using SSE adapter
                                const updatedTimeline = appendSSEEventToTimeline(state.timeline, event);

                                const toolName = event.data.tool_name;
                                const startTime = Date.now();

                                const newCall: ToolCall & { status: "running"; startTime: number } =
                                {
                                    name: toolName,
                                    arguments: event.data.tool_input,
                                    status: "running",
                                    startTime,
                                };

                                const newMap = new Map(state.activeToolCalls);
                                newMap.set(toolName, newCall);

                                const newStack = [...state.pendingToolsStack, toolName];

                                return {
                                    activeToolCalls: newMap,
                                    pendingToolsStack: newStack,
                                    agentState: "acting",
                                    timeline: updatedTimeline,
                                };
                            });

                            // Call additional handler if provided
                            additionalHandlers?.onAct?.(event);
                        },
                        onObserve: (event) => {
                            set((state) => {
                                // Append observe event to timeline using SSE adapter
                                const updatedTimeline = appendSSEEventToTimeline(state.timeline, event);

                                const stack = [...state.pendingToolsStack];
                                stack.pop(); // Remove completed tool from stack

                                return {
                                    pendingToolsStack: stack,
                                    agentState: "observing",
                                    timeline: updatedTimeline,
                                };
                            });

                            // Call additional handler if provided
                            additionalHandlers?.onObserve?.(event);
                        },
                        onTextStart: () => {
                            // Text streaming started - reset stream status to streaming
                            set({ streamStatus: "streaming", streamingAssistantContent: "" });
                        },
                        onTextDelta: (event) => {
                            // Batch rapid token updates for performance (reduces re-renders from 100+/s to ~20/s)
                            const delta = event.data.delta;
                            if (!delta) return;

                            // Accumulate deltas in buffer
                            textDeltaBuffer += delta;

                            // Flush buffer on timer to batch rapid updates
                            if (!textDeltaFlushTimer) {
                                textDeltaFlushTimer = setTimeout(() => {
                                    const bufferedContent = textDeltaBuffer;
                                    textDeltaBuffer = '';
                                    textDeltaFlushTimer = null;

                                    if (bufferedContent) {
                                        set((state) => ({
                                            streamingAssistantContent: state.streamingAssistantContent + bufferedContent,
                                            streamStatus: "streaming"
                                        }));
                                    }
                                }, TOKEN_BATCH_INTERVAL_MS);
                            }
                        },
                        onTextEnd: (event) => {
                            // Flush any remaining buffered content before applying final text
                            if (textDeltaFlushTimer) {
                                clearTimeout(textDeltaFlushTimer);
                                textDeltaFlushTimer = null;
                            }
                            const remainingBuffer = textDeltaBuffer;
                            textDeltaBuffer = '';

                            // Text streaming ended - use full_text for final content (ensures consistency)
                            set((state) => {
                                const fullText = event.data.full_text;
                                const finalContent = fullText || (state.streamingAssistantContent + remainingBuffer);
                                return { streamingAssistantContent: finalContent };
                            });
                        },
                        onClarificationAsked: (event) => {
                            // Add to timeline for inline rendering
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
                            // Add to timeline for inline rendering
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
                        onDoomLoopDetected: (event) => {
                            set({ doomLoopDetected: event.data });
                        },
                        onEnvVarRequested: (event) => {
                            // Add to timeline for inline rendering
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
                            // Clear all delta buffers on completion
                            if (textDeltaFlushTimer) {
                                clearTimeout(textDeltaFlushTimer);
                                textDeltaFlushTimer = null;
                            }
                            if (thoughtDeltaFlushTimer) {
                                clearTimeout(thoughtDeltaFlushTimer);
                                thoughtDeltaFlushTimer = null;
                            }
                            textDeltaBuffer = '';
                            thoughtDeltaBuffer = '';

                            set((state) => {
                                // Append complete event to timeline using SSE adapter
                                // This adds the assistant_message to timeline
                                const completeEvent: AgentEvent<CompleteEventData> = event as AgentEvent<CompleteEventData>;
                                const updatedTimeline = appendSSEEventToTimeline(state.timeline, completeEvent);

                                // Derive messages from updated timeline (no merging)
                                const newMessages = timelineToMessages(updatedTimeline);

                                return {
                                    messages: newMessages,
                                    timeline: updatedTimeline,
                                    streamingAssistantContent: "", // Clear streaming content
                                    isStreaming: false,
                                    streamStatus: "idle",
                                    agentState: "idle",
                                    activeToolCalls: new Map(),
                                    pendingToolsStack: [],
                                };
                            });
                        },
                        onError: (event) => {
                            // Clear all delta buffers on error
                            if (textDeltaFlushTimer) {
                                clearTimeout(textDeltaFlushTimer);
                                textDeltaFlushTimer = null;
                            }
                            if (thoughtDeltaFlushTimer) {
                                clearTimeout(thoughtDeltaFlushTimer);
                                thoughtDeltaFlushTimer = null;
                            }
                            textDeltaBuffer = '';
                            thoughtDeltaBuffer = '';

                            set({
                                error: event.data.message,
                                isStreaming: false,
                                streamStatus: "error",
                            });
                        },
                        onClose: () => {
                            // Clear all delta buffers on close
                            if (textDeltaFlushTimer) {
                                clearTimeout(textDeltaFlushTimer);
                                textDeltaFlushTimer = null;
                            }
                            if (thoughtDeltaFlushTimer) {
                                clearTimeout(thoughtDeltaFlushTimer);
                                thoughtDeltaFlushTimer = null;
                            }
                            textDeltaBuffer = '';
                            thoughtDeltaBuffer = '';

                            set({ isStreaming: false, streamStatus: "idle" });
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
                                },
                                handler
                            )
                            .catch(() => {
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
                            },
                            handler
                        );
                        return conversationId!;
                    } catch (_e) {
                        set({
                            error: "Failed to connect to chat stream",
                            isStreaming: false,
                            streamStatus: "error",
                        });
                        return null;
                    }
                },

                abortStream: () => {
                    const { activeConversationId } = get();
                    if (activeConversationId) {
                        agentService.stopChat(activeConversationId);
                        set({ isStreaming: false, streamStatus: "idle" });
                    }
                },

                respondToClarification: async (requestId, answer) => {
                    console.log("Responding to clarification", requestId, answer);
                    try {
                        await agentService.respondToClarification(requestId, answer);
                        set({ pendingClarification: null, agentState: "thinking" });
                    } catch (error) {
                        console.error("Failed to respond to clarification:", error);
                        set({ agentState: "idle" });
                    }
                },

                respondToDecision: async (requestId, decision) => {
                    console.log("Responding to decision", requestId, decision);
                    try {
                        await agentService.respondToDecision(requestId, decision);
                        set({ pendingDecision: null, agentState: "thinking" });
                    } catch (error) {
                        console.error("Failed to respond to decision:", error);
                        set({ agentState: "idle" });
                    }
                },

                respondToEnvVar: async (requestId, values) => {
                    console.log("Responding to env var request", requestId, values);
                    try {
                        await agentService.respondToEnvVar(requestId, values);
                        set({ pendingEnvVarRequest: null, agentState: "thinking" });
                    } catch (error) {
                        console.error("Failed to respond to env var request:", error);
                        set({ agentState: "idle" });
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

// Selectors for streaming content
export const useStreamingThought = () => useAgentV3Store((state) => state.streamingThought);
export const useIsThinkingStreaming = () => useAgentV3Store((state) => state.isThinkingStreaming);

// Selector for derived messages (rerender-derived-state)
// Messages are computed from timeline to avoid duplicate state
export const useMessages = () => useAgentV3Store((state) => {
    // For now, return stored messages for backward compatibility
    // TODO: Switch to computed derivation after verifying all consumers work correctly
    return state.messages;
});
