/**
 * Agent V2 Store
 *
 * Zustand store for Agent Chat state management.
 * Handles all 31 SSE event types and manages conversation state.
 */

import { create } from "zustand";
import { devtools } from "zustand/middleware";
import { agentV2Service } from "../services/agentV2Service";
import type {
  // Core types
  Conversation,
  Message,
  WorkPlan,
  PlanStep,
  ToolExecution,
  Thought,
  PlanDocument,
  PlanModeStatus,
  // Event types
  ClarificationRequest,
  DecisionRequest,
  PermissionRequest,
  DoomLoopRequest,
  SkillExecution,
  // Request types
  CreateConversationRequest,
  // Response types
  ExecutionHistoryResponse,
  ExecutionStatsResponse,
  ToolsListResponse,
  TokenBreakdown,
  // SSE Event data types
  DoomLoopDetectedEventData,
  SkillMatchedEventData,
} from "../types/agentV2";

// ============================================================================
// State Slices
// ============================================================================

/**
 * Conversation state
 */
interface ConversationState {
  conversations: Conversation[];
  currentConversation: Conversation | null;
  sidebarOpen: boolean;
  searchQuery: string;
  filterStatus: "all" | "active" | "archived";
  conversationsLoading: boolean;
  conversationsError: string | null;
}

/**
 * Message state
 */
interface MessageState {
  messages: Message[];
  streamingContent: string;
  isStreamingText: boolean;
  messagesLoading: boolean;
  isLoadingMore: boolean;
  hasMore: boolean;
  messagesError: string | null;
}

/**
 * Execution state
 */
interface ExecutionState {
  workPlan: WorkPlan | null;
  currentStepIndex: number;
  stepStatuses: Map<number, "pending" | "running" | "completed" | "failed">;
  thoughts: Thought[];
  currentThoughtLevel: "work" | "task" | null;
  toolExecutions: ToolExecution[];
  currentToolExecution: ToolExecution | null;
}

/**
 * Human interaction state
 */
interface InteractionState {
  pendingClarification: ClarificationRequest | null;
  pendingDecision: DecisionRequest | null;
  pendingPermission: PermissionRequest | null;
  pendingDoomLoop: DoomLoopRequest | null;
  interactionHistory: Array<{
    type: "clarification" | "decision" | "permission" | "doom_loop";
    timestamp: string;
    resolved: boolean;
  }>;
}

/**
 * Skill system state
 */
interface SkillState {
  matchedSkill: SkillExecution | null;
  skillHistory: SkillExecution[];
}

/**
 * Cost tracking state
 */
interface CostState {
  totalTokens: number;
  totalCost: number;
  tokenBreakdown: TokenBreakdown;
  stepCosts: Map<number, { tokens: TokenBreakdown; cost: number }>;
  isTracking: boolean;
}

/**
 * Plan mode state
 */
interface PlanModeState {
  isInPlanMode: boolean;
  currentPlan: PlanDocument | null;
  planModeStatus: PlanModeStatus | null;
  isEditing: boolean;
  unsavedChanges: boolean;
  planLoading: boolean;
  planError: string | null;
}

/**
 * Streaming state
 */
interface StreamingState {
  isStreaming: boolean;
  streamingPhase: "idle" | "thinking" | "planning" | "executing" | "responding";
}

// ============================================================================
// Complete Store Interface
// ============================================================================

interface AgentV2Store
  extends ConversationState,
    MessageState,
    ExecutionState,
    InteractionState,
    SkillState,
    CostState,
    PlanModeState,
    StreamingState {
  // ========================================================================
  // Conversation Actions
  // ========================================================================

  listConversations: (
    projectId: string,
    status?: "all" | "active" | "archived"
  ) => Promise<void>;
  createConversation: (
    projectId: string,
    title?: string
  ) => Promise<Conversation>;
  selectConversation: (conversation: Conversation | null) => void;
  getConversation: (id: string, projectId: string) => Promise<void>;
  deleteConversation: (id: string, projectId: string) => Promise<void>;
  updateConversationTitle: (
    id: string,
    projectId: string,
    title: string
  ) => Promise<void>;
  generateConversationTitle: (id: string, projectId: string) => Promise<void>;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  setSearchQuery: (query: string) => void;
  setFilterStatus: (status: "all" | "active" | "archived") => void;

  // ========================================================================
  // Message Actions
  // ========================================================================

  getMessages: (conversationId: string, projectId: string) => Promise<void>;
  loadMoreMessages: () => Promise<void>;
  addMessage: (message: Message) => void;
  clearMessages: () => void;

  // ========================================================================
  // Chat Actions
  // ========================================================================

  sendMessage: (conversationId: string, content: string) => Promise<void>;
  stopGeneration: (conversationId: string) => void;

  // ========================================================================
  // SSE Event Handlers (Core)
  // ========================================================================

  // Status events
  handleStart: (data: { conversation_id: string }) => void;
  handleComplete: (data: {
    content?: string;
    format?: string;
    id?: string;
    created_at?: string;
  }) => void;
  handleError: (data: {
    message: string;
    code?: string;
    isReconnectable?: boolean;
  }) => void;

  // Text streaming
  handleTextStart: () => void;
  handleTextDelta: (data: { delta: string }) => void;
  handleTextEnd: (data: { full_text?: string }) => void;

  // Thinking (multi-level)
  handleThought: (data: {
    content: string;
    thought_level?: "work" | "task";
    step_index?: number;
  }) => void;
  handleThoughtDelta: (data: { delta: string; step_index?: number }) => void;

  // Work plan
  handleWorkPlan: (data: {
    plan_id: string;
    conversation_id: string;
    status: string;
    steps: PlanStep[];
    current_step: number;
    workflow_pattern_id?: string;
  }) => void;
  handleStepStart: (data: {
    step_index: number;
    step_number: number;
    description: string;
  }) => void;
  handleStepEnd: (data: {
    step_index: number;
    step_number: number;
    success: boolean;
    current_step: number;
  }) => void;
  handleStepFinish: (data: {
    tokens: TokenBreakdown;
    cost: number;
    finish_reason: string;
    step_number?: number;
  }) => void;

  // Tool execution
  handleAct: (data: {
    tool_name: string;
    tool_input: Record<string, unknown>;
    call_id: string;
    status: string;
    step_number?: number;
  }) => void;
  handleObserve: (data: {
    tool_name: string;
    result?: string;
    observation?: string;
    status: string;
    duration_ms?: number;
    call_id: string;
    step_number?: number;
  }) => void;

  // Message
  handleMessage: (data: {
    id?: string;
    role: string;
    content: string;
    created_at?: string;
  }) => void;

  // Human interactions
  handleClarificationAsked: (data: ClarificationRequest) => void;
  handleClarificationAnswered: () => void;
  respondToClarification: (requestId: string, answer: string) => Promise<void>;

  handleDecisionAsked: (data: DecisionRequest) => void;
  handleDecisionAnswered: () => void;
  respondToDecision: (requestId: string, decision: string) => Promise<void>;

  handlePermissionAsked: (data: PermissionRequest) => void;
  handlePermissionReplied: () => void;
  respondToPermission: (allow: boolean) => Promise<void>;

  handleDoomLoopDetected: (data: DoomLoopDetectedEventData) => void;
  handleDoomLoopIntervened: () => void;
  respondToDoomLoop: (
    requestId: string,
    action: "continue" | "stop"
  ) => Promise<void>;

  // Cost tracking
  handleCostUpdate: (data: {
    total_tokens: number;
    total_cost: number;
    token_breakdown: TokenBreakdown;
  }) => void;

  // Skill system
  handleSkillMatched: (data: SkillMatchedEventData) => void;
  handleSkillExecutionStart: (data: {
    skill_id: string;
    skill_name: string;
    tools: string[];
    total_steps: number;
  }) => void;
  handleSkillToolStart: (data: {
    skill_id: string;
    tool_name: string;
    tool_input: Record<string, unknown>;
    step_index: number;
  }) => void;
  handleSkillToolResult: (data: {
    skill_id: string;
    tool_name: string;
    step_index: number;
    result?: string;
    error?: string;
    status: string;
    duration_ms?: number;
  }) => void;
  handleSkillExecutionComplete: (data: {
    skill_id: string;
    skill_name: string;
    success: boolean;
    tool_results: Array<{ tool_name: string; result: string }>;
    execution_time_ms: number;
    summary?: string;
    error?: string;
  }) => void;
  handleSkillFallback: (data: {
    skill_name: string;
    reason: string;
    error?: string;
  }) => void;

  // Plan mode
  handlePlanModeEnter: (data: {
    conversation_id: string;
    plan_id: string;
    plan_title: string;
  }) => void;
  handlePlanModeExit: (data: {
    conversation_id: string;
    plan_id: string;
    plan_status: string;
    approved: boolean;
  }) => void;
  handlePlanCreated: (data: {
    plan_id: string;
    title: string;
    conversation_id: string;
  }) => void;
  handlePlanUpdated: (data: {
    plan_id: string;
    content: string;
    version: number;
  }) => void;
  handlePlanStatusChanged: (data: {
    plan_id: string;
    old_status: string;
    new_status: string;
  }) => void;

  // Other
  handlePatternMatch: (data: {
    pattern_id: string;
    pattern_name: string;
    confidence: number;
  }) => void;
  handleRetry: (data: {
    attempt: number;
    delay_ms: number;
    message: string;
  }) => void;

  // ========================================================================
  // Plan Mode Actions
  // ========================================================================

  enterPlanMode: (
    conversationId: string,
    title: string,
    description?: string
  ) => Promise<void>;
  exitPlanMode: (
    conversationId: string,
    planId: string,
    approved: boolean,
    summary?: string
  ) => Promise<void>;
  getPlan: (planId: string) => Promise<void>;
  updatePlan: (planId: string, content: string) => Promise<void>;
  getPlanModeStatus: (conversationId: string) => Promise<void>;

  // ========================================================================
  // Execution History Actions
  // ========================================================================

  getExecutionHistory: (
    conversationId: string,
    projectId: string
  ) => Promise<ExecutionHistoryResponse>;
  getExecutionStats: (
    conversationId: string,
    projectId: string
  ) => Promise<ExecutionStatsResponse>;

  // ========================================================================
  // Tools Actions
  // ========================================================================

  listTools: () => Promise<ToolsListResponse>;
  tools: ToolsListResponse["tools"];

  // ========================================================================
  // Reset Actions
  // ========================================================================

  clearExecutionState: () => void;
  clearInteractionState: () => void;
  reset: () => void;
}

// ============================================================================
// Initial State
// ============================================================================

const initialState: Omit<
  AgentV2Store,
  | "listConversations"
  | "createConversation"
  | "selectConversation"
  | "getConversation"
  | "deleteConversation"
  | "updateConversationTitle"
  | "generateConversationTitle"
  | "toggleSidebar"
  | "setSidebarOpen"
  | "setSearchQuery"
  | "setFilterStatus"
  | "getMessages"
  | "loadMoreMessages"
  | "addMessage"
  | "clearMessages"
  | "sendMessage"
  | "stopGeneration"
  | "handleStart"
  | "handleComplete"
  | "handleError"
  | "handleTextStart"
  | "handleTextDelta"
  | "handleTextEnd"
  | "handleThought"
  | "handleThoughtDelta"
  | "handleWorkPlan"
  | "handleStepStart"
  | "handleStepEnd"
  | "handleStepFinish"
  | "handleAct"
  | "handleObserve"
  | "handleMessage"
  | "handleClarificationAsked"
  | "handleClarificationAnswered"
  | "respondToClarification"
  | "handleDecisionAsked"
  | "handleDecisionAnswered"
  | "respondToDecision"
  | "handlePermissionAsked"
  | "handlePermissionReplied"
  | "respondToPermission"
  | "handleDoomLoopDetected"
  | "handleDoomLoopIntervened"
  | "respondToDoomLoop"
  | "handleCostUpdate"
  | "handleSkillMatched"
  | "handleSkillExecutionStart"
  | "handleSkillToolStart"
  | "handleSkillToolResult"
  | "handleSkillExecutionComplete"
  | "handleSkillFallback"
  | "handlePlanModeEnter"
  | "handlePlanModeExit"
  | "handlePlanCreated"
  | "handlePlanUpdated"
  | "handlePlanStatusChanged"
  | "handlePatternMatch"
  | "handleRetry"
  | "enterPlanMode"
  | "exitPlanMode"
  | "getPlan"
  | "updatePlan"
  | "getPlanModeStatus"
  | "getExecutionHistory"
  | "getExecutionStats"
  | "listTools"
  | "clearExecutionState"
  | "clearInteractionState"
  | "reset"
> = {
  // Conversation state
  conversations: [],
  currentConversation: null,
  sidebarOpen: true,
  searchQuery: "",
  filterStatus: "all",
  conversationsLoading: false,
  conversationsError: null,

  // Message state
  messages: [],
  streamingContent: "",
  isStreamingText: false,
  messagesLoading: false,
  isLoadingMore: false,
  hasMore: true,
  messagesError: null,

  // Execution state
  workPlan: null,
  currentStepIndex: 0,
  stepStatuses: new Map(),
  thoughts: [],
  currentThoughtLevel: null,
  toolExecutions: [],
  currentToolExecution: null,

  // Interaction state
  pendingClarification: null,
  pendingDecision: null,
  pendingPermission: null,
  pendingDoomLoop: null,
  interactionHistory: [],

  // Skill state
  matchedSkill: null,
  skillHistory: [],

  // Cost state
  totalTokens: 0,
  totalCost: 0,
  tokenBreakdown: { input: 0, output: 0, total: 0 },
  stepCosts: new Map(),
  isTracking: false,

  // Plan mode state
  isInPlanMode: false,
  currentPlan: null,
  planModeStatus: null,
  isEditing: false,
  unsavedChanges: false,
  planLoading: false,
  planError: null,

  // Streaming state
  isStreaming: false,
  streamingPhase: "idle",

  // Tools
  tools: [],
};

// ============================================================================
// Store Creation
// ============================================================================

export const useAgentV2Store = create<AgentV2Store>()(
  devtools(
    (set, get) => ({
      ...initialState,

      // ========================================================================
      // Conversation Actions
      // ========================================================================

      listConversations: async (projectId, status = "all") => {
        set({ conversationsLoading: true, conversationsError: null });
        try {
          const conversations = await agentV2Service.listConversations(
            projectId,
            status === "all"
              ? undefined
              : { status: status as "active" | "archived" }
          );
          set({ conversations, conversationsLoading: false });
        } catch (error: any) {
          set({
            conversationsError:
              error.response?.data?.detail || "Failed to load conversations",
            conversationsLoading: false,
          });
          throw error;
        }
      },

      createConversation: async (projectId, title = "New Conversation") => {
        set({ conversationsLoading: true, conversationsError: null });
        try {
          const request: CreateConversationRequest = {
            project_id: projectId,
            title,
          };
          const conversation = await agentV2Service.createConversation(request);
          set((state) => ({
            conversations: [conversation, ...state.conversations],
            currentConversation: conversation,
            conversationsLoading: false,
          }));
          return conversation;
        } catch (error: any) {
          set({
            conversationsError:
              error.response?.data?.detail || "Failed to create conversation",
            conversationsLoading: false,
          });
          throw error;
        }
      },

      selectConversation: (conversation) => {
        set({
          currentConversation: conversation,
          // Reset state when switching conversations
          messages: [],
          streamingContent: "",
          workPlan: null,
          currentStepIndex: 0,
          stepStatuses: new Map(),
          thoughts: [],
          toolExecutions: [],
          currentToolExecution: null,
          matchedSkill: null,
          isStreaming: false,
          streamingPhase: "idle",
        });

        if (conversation) {
          get().getMessages(conversation.id, conversation.project_id);
        }
      },

      getConversation: async (id, projectId) => {
        set({ conversationsLoading: true, conversationsError: null });
        try {
          const conversation = await agentV2Service.getConversation(
            id,
            projectId
          );
          set({
            currentConversation: conversation || null,
            conversationsLoading: false,
          });
        } catch (error: any) {
          set({
            conversationsError:
              error.response?.data?.detail || "Failed to load conversation",
            conversationsLoading: false,
          });
          throw error;
        }
      },

      deleteConversation: async (id, projectId) => {
        set({ conversationsLoading: true, conversationsError: null });
        try {
          await agentV2Service.deleteConversation(id, projectId);
          set((state) => ({
            conversations: state.conversations.filter((c) => c.id !== id),
            currentConversation:
              state.currentConversation?.id === id
                ? null
                : state.currentConversation,
            conversationsLoading: false,
          }));
        } catch (error: any) {
          set({
            conversationsError:
              error.response?.data?.detail || "Failed to delete conversation",
            conversationsLoading: false,
          });
          throw error;
        }
      },

      updateConversationTitle: async (id, projectId, title) => {
        set({ conversationsLoading: true, conversationsError: null });
        try {
          const updated = await agentV2Service.updateConversationTitle(
            id,
            projectId,
            { title }
          );
          set((state) => ({
            conversations: state.conversations.map((c) =>
              c.id === id ? updated : c
            ),
            currentConversation:
              state.currentConversation?.id === id
                ? updated
                : state.currentConversation,
            conversationsLoading: false,
          }));
        } catch (error: any) {
          set({
            conversationsError:
              error.response?.data?.detail || "Failed to update title",
            conversationsLoading: false,
          });
          throw error;
        }
      },

      generateConversationTitle: async (id, projectId) => {
        try {
          const updated = await agentV2Service.generateConversationTitle(
            id,
            projectId
          );
          set((state) => ({
            conversations: state.conversations.map((c) =>
              c.id === id ? updated : c
            ),
            currentConversation:
              state.currentConversation?.id === id
                ? updated
                : state.currentConversation,
          }));
        } catch (error: any) {
          console.error("[AgentV2] Failed to generate title:", error);
        }
      },

      toggleSidebar: () =>
        set((state) => ({ sidebarOpen: !state.sidebarOpen })),
      setSidebarOpen: (open) => set({ sidebarOpen: open }),
      setSearchQuery: (query) => set({ searchQuery: query }),
      setFilterStatus: (status) => set({ filterStatus: status }),

      // ========================================================================
      // Message Actions
      // ========================================================================

      getMessages: async (conversationId, projectId) => {
        set({ messagesLoading: true, messagesError: null });
        try {
          const response = await agentV2Service.getMessages(
            conversationId,
            projectId
          );
          set({
            messages: response.messages,
            hasMore: response.has_more,
            messagesLoading: false,
          });
        } catch (error: any) {
          set({
            messagesError:
              error.response?.data?.detail || "Failed to load messages",
            messagesLoading: false,
          });
          throw error;
        }
      },

      loadMoreMessages: async () => {
        const { messages, currentConversation } = get();
        if (!currentConversation || !get().hasMore || get().isLoadingMore)
          return;

        set({ isLoadingMore: true });
        try {
          const lastMessage = messages[messages.length - 1];
          const response = await agentV2Service.getMessages(
            currentConversation.id,
            currentConversation.project_id,
            { before: lastMessage.id }
          );
          set((state) => ({
            messages: [...state.messages, ...response.messages],
            hasMore: response.has_more,
            isLoadingMore: false,
          }));
        } catch (error: any) {
          set({
            messagesError:
              error.response?.data?.detail || "Failed to load more messages",
            isLoadingMore: false,
          });
        }
      },

      addMessage: (message) => {
        set((state) => {
          // Check for duplicates
          const lastMessage = state.messages[state.messages.length - 1];
          if (lastMessage?.id === message.id) {
            return state;
          }
          return { messages: [...state.messages, message] };
        });
      },

      clearMessages: () => set({ messages: [], streamingContent: "" }),

      // ========================================================================
      // Chat Actions
      // ========================================================================

      sendMessage: async (conversationId, content) => {
        const { isStreaming } = get();
        if (isStreaming) return;

        // Clear previous execution state
        get().clearExecutionState();

        // Add user message
        const userMessage: Message = {
          id: `temp-${Date.now()}`,
          conversation_id: conversationId,
          role: "user",
          content,
          message_type: "text",
          created_at: new Date().toISOString(),
        };
        get().addMessage(userMessage);

        set({ isStreaming: true, streamingPhase: "thinking" });

        // Create SSE handler
        agentV2Service.chat(
          { conversation_id: conversationId, message: content },
          {
            onOpen: () => console.log("[AgentV2] SSE connection opened"),
            onClose: () => {
              set({ isStreaming: false, streamingPhase: "idle" });
            },

            // Status events
            onStart: get().handleStart,
            onComplete: get().handleComplete,
            onError: get().handleError,

            // Text streaming
            onTextStart: get().handleTextStart,
            onTextDelta: get().handleTextDelta,
            onTextEnd: get().handleTextEnd,

            // Thinking
            onThought: get().handleThought,
            onThoughtDelta: get().handleThoughtDelta,

            // Work plan
            onWorkPlan: get().handleWorkPlan,
            onStepStart: get().handleStepStart,
            onStepEnd: get().handleStepEnd,
            onStepFinish: get().handleStepFinish,

            // Tool execution
            onAct: get().handleAct,
            onObserve: get().handleObserve,

            // Message
            onMessage: get().handleMessage,

            // Human interactions
            onClarificationAsked: get().handleClarificationAsked,
            onClarificationAnswered: get().handleClarificationAnswered,
            onDecisionAsked: get().handleDecisionAsked,
            onDecisionAnswered: get().handleDecisionAnswered,
            onPermissionAsked: get().handlePermissionAsked,
            onPermissionReplied: get().handlePermissionReplied,
            onDoomLoopDetected: get().handleDoomLoopDetected,
            onDoomLoopIntervened: get().handleDoomLoopIntervened,

            // Cost tracking
            onCostUpdate: get().handleCostUpdate,

            // Skill system
            onSkillMatched: get().handleSkillMatched,
            onSkillExecutionStart: get().handleSkillExecutionStart,
            onSkillToolStart: get().handleSkillToolStart,
            onSkillToolResult: get().handleSkillToolResult,
            onSkillExecutionComplete: get().handleSkillExecutionComplete,
            onSkillFallback: get().handleSkillFallback,

            // Plan mode
            onPlanModeEnter: get().handlePlanModeEnter,
            onPlanModeExit: get().handlePlanModeExit,
            onPlanCreated: get().handlePlanCreated,
            onPlanUpdated: get().handlePlanUpdated,
            onPlanStatusChanged: get().handlePlanStatusChanged,

            // Other
            onPatternMatch: get().handlePatternMatch,
            onRetry: get().handleRetry,
          }
        );
      },

      stopGeneration: (conversationId) => {
        agentV2Service.stopChat(conversationId);
        set({ isStreaming: false, streamingPhase: "idle" });
      },

      // ========================================================================
      // SSE Event Handlers
      // ========================================================================

      handleStart: (data) => {
        console.log("[AgentV2] Stream started:", data);
      },

      handleComplete: (data) => {
        if (data.content) {
          const assistantMessage: Message = {
            id: data.id || `msg-${Date.now()}`,
            conversation_id: get().currentConversation?.id || "",
            role: "assistant",
            content: data.content,
            message_type: "text",
            created_at: data.created_at || new Date().toISOString(),
          };
          get().addMessage(assistantMessage);
        }
        set({ isStreaming: false, streamingPhase: "idle" });

        // Generate title if needed - moved here from sendMessage to ensure all messages are counted
        const { currentConversation, messages } = get();
        if (
          currentConversation?.title === "New Conversation" &&
          messages.length <= 4  // Only trigger when there are few messages
        ) {
          get().generateConversationTitle(
            currentConversation.id,
            currentConversation.project_id
          );
        }
      },

      handleError: (data) => {
        set({
          conversationsError: data.message,
          isStreaming: false,
          streamingPhase: "idle",
        });
      },

      handleTextStart: () => {
        set({
          streamingContent: "",
          isStreamingText: true,
          streamingPhase: "responding",
        });
      },

      handleTextDelta: (data) => {
        set((state) => ({
          streamingContent: state.streamingContent + data.delta,
        }));
      },

      handleTextEnd: (data) => {
        set((state) => ({
          streamingContent: data?.full_text || state.streamingContent,
          isStreamingText: false,
        }));
      },

      handleThought: (data) => {
        const thought: Thought = {
          id: `thought-${Date.now()}`,
          content: data.content,
          level: data.thought_level || "task",
          step_number: data.step_index,
          timestamp: new Date().toISOString(),
        };
        set((state) => ({
          thoughts: [...state.thoughts, thought],
          currentThoughtLevel: data.thought_level || "task",
          streamingPhase: "thinking",
        }));
      },

      handleThoughtDelta: (data) => {
        set((state) => {
          const thoughts = [...state.thoughts];
          const lastThought = thoughts[thoughts.length - 1];
          if (lastThought) {
            lastThought.content += data.delta;
          }
          return { thoughts };
        });
      },

      handleWorkPlan: (data) => {
        const workPlan: WorkPlan = {
          id: data.plan_id,
          conversation_id: data.conversation_id,
          status: data.status as WorkPlan["status"],
          steps: data.steps,
          current_step_index: data.current_step,
          workflow_pattern_id: data.workflow_pattern_id,
          created_at: new Date().toISOString(),
        };

        // Initialize step statuses
        const stepStatuses = new Map<
          number,
          "pending" | "running" | "completed" | "failed"
        >();
        data.steps.forEach((step) => {
          stepStatuses.set(step.step_number, "pending");
        });

        set({
          workPlan,
          stepStatuses,
          currentStepIndex: data.current_step,
          streamingPhase: "planning",
        });
      },

      handleStepStart: (data) => {
        set((state) => {
          const stepStatuses = new Map(state.stepStatuses);
          stepStatuses.set(data.step_number, "running");
          return {
            stepStatuses,
            currentStepIndex: data.step_number,
            streamingPhase: "executing",
          };
        });
      },

      handleStepEnd: (data) => {
        set((state) => {
          const stepStatuses = new Map(state.stepStatuses);
          stepStatuses.set(
            data.step_number,
            data.success ? "completed" : "failed"
          );
          return {
            stepStatuses,
            currentStepIndex: data.current_step,
          };
        });
      },

      handleStepFinish: (data) => {
        set((state) => {
          const stepCosts = new Map(state.stepCosts);
          if (data.step_number !== undefined) {
            stepCosts.set(data.step_number, {
              tokens: data.tokens,
              cost: data.cost,
            });
          }
          return {
            stepCosts,
            totalTokens: state.totalTokens + data.tokens.total,
            totalCost: state.totalCost + data.cost,
            tokenBreakdown: {
              input: state.tokenBreakdown.input + data.tokens.input,
              output: state.tokenBreakdown.output + data.tokens.output,
              total: state.tokenBreakdown.total + data.tokens.total,
            },
          };
        });
      },

      handleAct: (data) => {
        const toolExecution: ToolExecution = {
          id: data.call_id,
          tool_name: data.tool_name,
          input: data.tool_input,
          status: "running",
          start_time: new Date().toISOString(),
          step_number: data.step_number,
          call_id: data.call_id,
        };

        set((state) => ({
          toolExecutions: [...state.toolExecutions, toolExecution],
          currentToolExecution: toolExecution,
          streamingPhase: "executing",
        }));
      },

      handleObserve: (data) => {
        const result = data.result || data.observation;
        const isError =
          data.status === "failed" ||
          result?.toLowerCase().startsWith("error:");

        set((state) => ({
          toolExecutions: state.toolExecutions.map((exec) =>
            exec.id === data.call_id || exec.call_id === data.call_id
              ? {
                  ...exec,
                  status: isError ? "failed" : "success",
                  result: isError ? undefined : result,
                  error: isError ? result : undefined,
                  end_time: new Date().toISOString(),
                }
              : exec
          ),
          currentToolExecution: null,
        }));
      },

      handleMessage: (data) => {
        // Skip user messages (already added client-side)
        if (data.role === "user") return;

        const message: Message = {
          id: data.id || `msg-${Date.now()}`,
          conversation_id: get().currentConversation?.id || "",
          role: data.role as Message["role"],
          content: data.content,
          message_type: "text",
          created_at: data.created_at || new Date().toISOString(),
        };
        get().addMessage(message);
      },

      handleClarificationAsked: (data) => {
        set({
          pendingClarification: data,
          interactionHistory: [
            ...get().interactionHistory,
            {
              type: "clarification",
              timestamp: new Date().toISOString(),
              resolved: false,
            },
          ],
        });
      },

      handleClarificationAnswered: () => {
        set({
          pendingClarification: null,
        });
      },

      respondToClarification: async (requestId, answer) => {
        const { currentConversation } = get();
        if (!currentConversation) return;

        await agentV2Service.respondToClarification(
          currentConversation.id,
          requestId,
          answer
        );
        get().handleClarificationAnswered();
      },

      handleDecisionAsked: (data) => {
        set({
          pendingDecision: data,
          interactionHistory: [
            ...get().interactionHistory,
            {
              type: "decision",
              timestamp: new Date().toISOString(),
              resolved: false,
            },
          ],
        });
      },

      handleDecisionAnswered: () => {
        set({
          pendingDecision: null,
        });
      },

      respondToDecision: async (requestId, decision) => {
        const { currentConversation } = get();
        if (!currentConversation) return;

        await agentV2Service.respondToDecision(
          currentConversation.id,
          requestId,
          decision
        );
        get().handleDecisionAnswered();
      },

      handlePermissionAsked: (data) => {
        set({
          pendingPermission: data,
        });
      },

      handlePermissionReplied: () => {
        set({
          pendingPermission: null,
        });
      },

      respondToPermission: async (allow) => {
        const { currentConversation, pendingPermission } = get();
        if (!currentConversation || !pendingPermission) return;

        await agentV2Service.respondToPermission(
          currentConversation.id,
          pendingPermission.request_id,
          allow
        );
        get().handlePermissionReplied();
      },

      handleDoomLoopDetected: (data) => {
        const doomLoopRequest: DoomLoopRequest = {
          request_id: data.request_id || `doom-${Date.now()}`,
          tool: data.tool,
          input: data.input,
          count: data.count,
          suggested_actions: ["continue", "stop"],
        };
        set({
          pendingDoomLoop: doomLoopRequest,
        });
      },

      handleDoomLoopIntervened: () => {
        set({
          pendingDoomLoop: null,
        });
      },

      respondToDoomLoop: async (requestId, action) => {
        const { currentConversation } = get();
        if (!currentConversation) return;

        await agentV2Service.respondToDoomLoop(
          currentConversation.id,
          requestId,
          action
        );
        get().handleDoomLoopIntervened();
      },

      handleCostUpdate: (data) => {
        set({
          totalTokens: data.total_tokens,
          totalCost: data.total_cost,
          tokenBreakdown: data.token_breakdown,
        });
      },

      handleSkillMatched: (data) => {
        const skillExecution: SkillExecution = {
          skill_id: data.skill_id,
          skill_name: data.skill_name,
          execution_mode: data.execution_mode,
          match_score: data.match_score,
          status: "matched",
          tools: data.tools,
          tool_executions: [],
          current_step: 0,
          total_steps: data.tools.length,
          started_at: new Date().toISOString(),
        };
        set({ matchedSkill: skillExecution });
      },

      handleSkillExecutionStart: (data) => {
        set((state) => ({
          matchedSkill: state.matchedSkill
            ? {
                ...state.matchedSkill,
                status: "executing",
                total_steps: data.total_steps,
              }
            : null,
        }));
      },

      handleSkillToolStart: (data) => {
        set((state) => ({
          matchedSkill: state.matchedSkill
            ? {
                ...state.matchedSkill,
                tool_executions: [
                  ...state.matchedSkill.tool_executions,
                  {
                    tool_name: data.tool_name,
                    tool_input: data.tool_input,
                    status: "running",
                    step_index: data.step_index,
                  },
                ],
                current_step: data.step_index,
              }
            : null,
        }));
      },

      handleSkillToolResult: (data) => {
        set((state) => ({
          matchedSkill: state.matchedSkill
            ? {
                ...state.matchedSkill,
                tool_executions: state.matchedSkill.tool_executions.map(
                  (exec) =>
                    exec.step_index === data.step_index
                      ? {
                          ...exec,
                          status: data.status as "success" | "failed",
                          result: data.result,
                          error: data.error,
                          duration_ms: data.duration_ms,
                        }
                      : exec
                ),
              }
            : null,
        }));
      },

      handleSkillExecutionComplete: (data) => {
        set((state) => {
          if (!state.matchedSkill) return state;

          const completedSkill: SkillExecution = {
            ...state.matchedSkill,
            status: data.success ? "completed" : "failed",
            summary: data.summary,
            error: data.error,
            execution_time_ms: data.execution_time_ms,
            completed_at: new Date().toISOString(),
          };

          return {
            matchedSkill: completedSkill,
            skillHistory: [...state.skillHistory, completedSkill],
          };
        });
      },

      handleSkillFallback: (data) => {
        set((state) => ({
          matchedSkill: state.matchedSkill
            ? {
                ...state.matchedSkill,
                status: "fallback",
                error: data.error || `Fallback: ${data.reason}`,
              }
            : null,
        }));
      },

      handlePlanModeEnter: (data) => {
        set({
          isInPlanMode: true,
          currentPlan: {
            id: data.plan_id,
            conversation_id: data.conversation_id,
            title: data.plan_title,
            content: "",
            status: "draft",
            version: 1,
            metadata: {},
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        });
      },

      handlePlanModeExit: (data) => {
        set({
          isInPlanMode: false,
          currentPlan: get().currentPlan
            ? {
                ...get().currentPlan!,
                status: data.plan_status as PlanDocument["status"],
              }
            : null,
        });
      },

      handlePlanCreated: (data) => {
        set({
          currentPlan: {
            id: data.plan_id,
            conversation_id: data.conversation_id,
            title: data.title,
            content: "",
            status: "draft",
            version: 1,
            metadata: {},
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        });
      },

      handlePlanUpdated: (data) => {
        set((state) => ({
          currentPlan: state.currentPlan
            ? {
                ...state.currentPlan,
                content: data.content,
                version: data.version,
                updated_at: new Date().toISOString(),
              }
            : null,
        }));
      },

      handlePlanStatusChanged: (data) => {
        set((state) => ({
          currentPlan: state.currentPlan
            ? {
                ...state.currentPlan,
                status: data.new_status as PlanDocument["status"],
              }
            : null,
        }));
      },

      handlePatternMatch: (data) => {
        console.log("[AgentV2] Pattern matched:", data);
      },

      handleRetry: (data) => {
        console.log("[AgentV2] Retry:", data);
      },

      // ========================================================================
      // Plan Mode Actions
      // ========================================================================

      enterPlanMode: async (conversationId, title, description) => {
        set({ planLoading: true, planError: null });
        try {
          const plan = await agentV2Service.enterPlanMode({
            conversation_id: conversationId,
            title,
            description,
          });
          set({
            currentPlan: plan,
            isInPlanMode: true,
            planLoading: false,
          });
        } catch (error: any) {
          set({
            planError:
              error.response?.data?.detail || "Failed to enter plan mode",
            planLoading: false,
          });
          throw error;
        }
      },

      exitPlanMode: async (conversationId, planId, approved, summary) => {
        set({ planLoading: true, planError: null });
        try {
          const plan = await agentV2Service.exitPlanMode({
            conversation_id: conversationId,
            plan_id: planId,
            approved,
            summary,
          });
          set({
            currentPlan: plan,
            isInPlanMode: false,
            planLoading: false,
          });
        } catch (error: any) {
          set({
            planError:
              error.response?.data?.detail || "Failed to exit plan mode",
            planLoading: false,
          });
          throw error;
        }
      },

      getPlan: async (planId) => {
        set({ planLoading: true, planError: null });
        try {
          const plan = await agentV2Service.getPlan(planId);
          set({ currentPlan: plan, planLoading: false });
        } catch (error: any) {
          set({
            planError: error.response?.data?.detail || "Failed to load plan",
            planLoading: false,
          });
          throw error;
        }
      },

      updatePlan: async (planId, content) => {
        set({ planLoading: true, planError: null });
        try {
          const plan = await agentV2Service.updatePlan(planId, { content });
          set({ currentPlan: plan, planLoading: false });
        } catch (error: any) {
          set({
            planError: error.response?.data?.detail || "Failed to update plan",
            planLoading: false,
          });
          throw error;
        }
      },

      getPlanModeStatus: async (conversationId) => {
        set({ planLoading: true, planError: null });
        try {
          const status = await agentV2Service.getPlanModeStatus(conversationId);
          set({
            planModeStatus: status,
            isInPlanMode: status.is_in_plan_mode,
            currentPlan: status.plan || null,
            planLoading: false,
          });
        } catch (error: any) {
          set({
            planError:
              error.response?.data?.detail || "Failed to get plan mode status",
            planLoading: false,
          });
          throw error;
        }
      },

      // ========================================================================
      // Execution History Actions
      // ========================================================================

      getExecutionHistory: async (conversationId, projectId) => {
        return await agentV2Service.getExecutionHistory(
          conversationId,
          projectId
        );
      },

      getExecutionStats: async (conversationId, projectId) => {
        return await agentV2Service.getExecutionStats(
          conversationId,
          projectId
        );
      },

      // ========================================================================
      // Tools Actions
      // ========================================================================

      listTools: async () => {
        const response = await agentV2Service.listTools();
        set({ tools: response.tools });
        return response;
      },

      // ========================================================================
      // Reset Actions
      // ========================================================================

      clearExecutionState: () => {
        set({
          workPlan: null,
          currentStepIndex: 0,
          stepStatuses: new Map(),
          thoughts: [],
          currentThoughtLevel: null,
          toolExecutions: [],
          currentToolExecution: null,
          matchedSkill: null,
          streamingContent: "",
          isStreamingText: false,
        });
      },

      clearInteractionState: () => {
        set({
          pendingClarification: null,
          pendingDecision: null,
          pendingPermission: null,
          pendingDoomLoop: null,
        });
      },

      reset: () => {
        set({
          ...initialState,
          stepStatuses: new Map(),
          stepCosts: new Map(),
        });
      },
    }),
    { name: "AgentV2Store" }
  )
);

// ============================================================================
// Selectors for fine-grained subscriptions
// ============================================================================

// Conversation selectors
export const useConversations = () => useAgentV2Store((s) => s.conversations);
export const useCurrentConversation = () =>
  useAgentV2Store((s) => s.currentConversation);
export const useSidebarOpen = () => useAgentV2Store((s) => s.sidebarOpen);
export const useSearchQuery = () => useAgentV2Store((s) => s.searchQuery);
export const useFilterStatus = () => useAgentV2Store((s) => s.filterStatus);

// Message selectors
export const useMessages = () => useAgentV2Store((s) => s.messages);
export const useStreamingContent = () =>
  useAgentV2Store((s) => s.streamingContent);
export const useIsStreamingText = () =>
  useAgentV2Store((s) => s.isStreamingText);

// Execution selectors
export const useWorkPlan = () => useAgentV2Store((s) => s.workPlan);
export const useCurrentStepIndex = () =>
  useAgentV2Store((s) => s.currentStepIndex);
export const useStepStatuses = () => useAgentV2Store((s) => s.stepStatuses);
export const useThoughts = () => useAgentV2Store((s) => s.thoughts);
export const useCurrentThoughtLevel = () =>
  useAgentV2Store((s) => s.currentThoughtLevel);
export const useToolExecutions = () => useAgentV2Store((s) => s.toolExecutions);
export const useCurrentToolExecution = () =>
  useAgentV2Store((s) => s.currentToolExecution);

// Interaction selectors
export const usePendingClarification = () =>
  useAgentV2Store((s) => s.pendingClarification);
export const usePendingDecision = () =>
  useAgentV2Store((s) => s.pendingDecision);
export const usePendingPermission = () =>
  useAgentV2Store((s) => s.pendingPermission);
export const usePendingDoomLoop = () =>
  useAgentV2Store((s) => s.pendingDoomLoop);

// Skill selectors
export const useMatchedSkill = () => useAgentV2Store((s) => s.matchedSkill);
export const useSkillHistory = () => useAgentV2Store((s) => s.skillHistory);

// Cost selectors
export const useTotalTokens = () => useAgentV2Store((s) => s.totalTokens);
export const useTotalCost = () => useAgentV2Store((s) => s.totalCost);
export const useTokenBreakdown = () => useAgentV2Store((s) => s.tokenBreakdown);
export const useStepCosts = () => useAgentV2Store((s) => s.stepCosts);

// Plan mode selectors
export const useIsInPlanMode = () => useAgentV2Store((s) => s.isInPlanMode);
export const useCurrentPlan = () => useAgentV2Store((s) => s.currentPlan);
export const usePlanModeStatus = () => useAgentV2Store((s) => s.planModeStatus);

// Streaming selectors
export const useIsStreaming = () => useAgentV2Store((s) => s.isStreaming);
export const useStreamingPhase = () => useAgentV2Store((s) => s.streamingPhase);

// Loading/Error selectors
export const useConversationsLoading = () =>
  useAgentV2Store((s) => s.conversationsLoading);
export const useConversationsError = () =>
  useAgentV2Store((s) => s.conversationsError);
export const useMessagesLoading = () =>
  useAgentV2Store((s) => s.messagesLoading);
export const useMessagesError = () => useAgentV2Store((s) => s.messagesError);
export const usePlanLoading = () => useAgentV2Store((s) => s.planLoading);
export const usePlanError = () => useAgentV2Store((s) => s.planError);
