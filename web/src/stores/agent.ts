/**
 * Agent store for managing agent state using Zustand.
 *
 * This store manages conversations, messages, and agent execution state.
 *
 * Project-Scoped Conversations (FR-017):
 * - All conversations are scoped to a specific project_id
 * - listConversations() filters by project_id
 * - createConversation() requires a project_id
 * - Switching projects clears the current conversation context
 *
 * Multi-Level Thinking Support:
 * - Work plans for complex queries
 * - Step tracking for plan execution
 * - Execution history retrieval
 */

import { create } from "zustand";
import { agentService } from "../services/agentService";
import { planService } from "../services/planService";
import type {
  AgentExecutionWithDetails,
  AgentStreamHandler,
  ArtifactReference,
  ClarificationAskedEventData,
  ContextCompressedEventData,
  Conversation,
  ConversationStatus,
  CreateConversationRequest,
  DecisionAskedEventData,
  DoomLoopDetectedEventData,
  EnterPlanModeRequest,
  ExitPlanModeRequest,
  MessageRole,
  PlanDocument,
  PlanModeStatus,
  PlanStatus,
  SkillExecutionState,
  SkillMatchedEventData,
  SkillExecutionStartEventData,
  SkillToolStartEventData,
  SkillToolResultEventData,
  SkillExecutionCompleteEventData,
  SkillFallbackEventData,
  SkillToolExecution,
  ThoughtLevel,
  TimelineEvent,
  TimelineStep,
  ToolExecution,
  ToolInfo,
  UpdatePlanRequest,
  WorkPlan,
} from "../types/agent";

// Global lock to prevent simultaneous message sends
let sendMessageLock = false;

interface AgentState {
  // Conversations
  conversations: Conversation[];
  currentConversation: Conversation | null;
  conversationsLoading: boolean;
  conversationsError: string | null;

  // Timeline (unified event stream) in current conversation
  timeline: TimelineEvent[];
  timelineLoading: boolean;
  timelineError: string | null;

  // Pagination state for backward loading
  earliestLoadedSequence: number | null;
  latestLoadedSequence: number | null;
  hasEarlierMessages: boolean;

  // Agent execution state
  isStreaming: boolean;
  currentThought: string | null;
  currentThoughtLevel: ThoughtLevel | null;
  currentToolCall: {
    name: string;
    input: Record<string, unknown>;
    stepNumber?: number;
  } | null;
  currentObservation: string | null;

  // Typewriter effect state (streaming draft content)
  assistantDraftContent: string;
  isTextStreaming: boolean;

  // Multi-level thinking state
  currentWorkPlan: WorkPlan | null;
  currentStepNumber: number | null;
  currentStepStatus: "pending" | "running" | "completed" | "failed" | null;

  // Pattern matching state (T079)
  matchedPattern: { id: string; similarity: number; query: string } | null;

  // Execution timeline state (new)
  executionTimeline: TimelineStep[];
  currentToolExecution: {
    id: string;
    toolName: string;
    input: Record<string, unknown>;
    stepNumber?: number;
    startTime: string;
  } | null;
  toolExecutionHistory: ToolExecution[];

  // Execution history
  executionHistory: AgentExecutionWithDetails[];
  executionHistoryLoading: boolean;

  // Available tools
  tools: ToolInfo[];
  toolsLoading: boolean;

  // Human interaction state
  pendingClarification: ClarificationAskedEventData | null;
  pendingDecision: DecisionAskedEventData | null;
  pendingDoomLoopIntervention: DoomLoopDetectedEventData | null;

  // Skill execution state (L2 layer)
  currentSkillExecution: SkillExecutionState | null;

  // Context compression state
  contextCompressionInfo: {
    wasCompressed: boolean;
    compressionStrategy: "none" | "truncate" | "summarize";
    originalMessageCount: number;
    finalMessageCount: number;
    estimatedTokens: number;
    tokenBudget: number;
    budgetUtilizationPct: number;
    summarizedMessageCount: number;
  } | null;

  // Plan Mode state
  currentPlan: PlanDocument | null;
  planModeStatus: PlanModeStatus | null;
  planLoading: boolean;
  planError: string | null;

  // New conversation pending state (to prevent race condition)
  isNewConversationPending: boolean;

  // Title generation state
  isGeneratingTitle: boolean;
  titleGenerationError: string | null;

  // Actions
  listConversations: (
    projectId: string,
    status?: ConversationStatus,
    limit?: number
  ) => Promise<void>;
  createConversation: (
    projectId: string,
    title?: string
  ) => Promise<Conversation>;
  getConversation: (
    conversationId: string,
    projectId: string
  ) => Promise<Conversation | null>;
  deleteConversation: (
    conversationId: string,
    projectId: string
  ) => Promise<void>;
  setCurrentConversation: (
    conversation: Conversation | null,
    skipLoadMessages?: boolean
  ) => void;

  // Timeline (unified event stream)
  getTimeline: (
    conversationId: string,
    projectId: string,
    limit?: number
  ) => Promise<void>;
  addTimelineEvent: (event: TimelineEvent) => void;
  clearTimeline: () => void;
  prependTimelineEvents: (events: TimelineEvent[]) => void;

  // Pagination
  loadEarlierMessages: (
    conversationId: string,
    projectId: string,
    limit?: number
  ) => Promise<void>;

  // Chat
  sendMessage: (
    conversationId: string,
    message: string,
    projectId: string
  ) => Promise<void>;
  stopChat: (conversationId: string) => void;
  generateConversationTitle: (
    conversationId: string,
    projectId: string
  ) => Promise<void>;

  // Typewriter effect actions
  onTextStart: () => void;
  onTextDelta: (delta: string) => void;
  onTextEnd: (fullText?: string) => void;
  clearDraft: () => void;

  // Human interaction actions
  respondToClarification: (requestId: string, answer: string) => Promise<void>;
  respondToDecision: (requestId: string, decision: string) => Promise<void>;
  respondToDoomLoop: (requestId: string, action: string) => Promise<void>;
  clearPendingInteraction: () => void;

  // Execution history
  getExecutionHistory: (
    conversationId: string,
    projectId: string,
    limit?: number
  ) => Promise<void>;

  // Tools
  listTools: () => Promise<void>;

  // Plan Mode actions
  enterPlanMode: (
    conversationId: string,
    title: string,
    description?: string
  ) => Promise<PlanDocument>;
  exitPlanMode: (
    conversationId: string,
    planId: string,
    approve?: boolean,
    summary?: string
  ) => Promise<PlanDocument>;
  getPlan: (planId: string) => Promise<PlanDocument>;
  updatePlan: (
    planId: string,
    request: UpdatePlanRequest
  ) => Promise<PlanDocument>;
  getPlanModeStatus: (conversationId: string) => Promise<PlanModeStatus>;
  clearPlanState: () => void;

  // State management
  clearErrors: () => void;
  reset: () => void;
}

const initialState = {
  conversations: [],
  currentConversation: null,
  conversationsLoading: false,
  conversationsError: null,
  timeline: [] as TimelineEvent[],
  timelineLoading: false,
  timelineError: null,
  // Pagination state for backward loading
  earliestLoadedSequence: null,
  latestLoadedSequence: null,
  hasEarlierMessages: false,
  isStreaming: false,
  currentThought: null,
  currentThoughtLevel: null,
  currentToolCall: null,
  currentObservation: null,
  assistantDraftContent: "",
  isTextStreaming: false,
  currentWorkPlan: null,
  currentStepNumber: null,
  currentStepStatus: null,
  matchedPattern: null,
  // Execution timeline state (new)
  executionTimeline: [],
  currentToolExecution: null,
  toolExecutionHistory: [],
  // Execution history
  executionHistory: [],
  executionHistoryLoading: false,
  tools: [],
  toolsLoading: false,
  // Human interaction state
  pendingClarification: null,
  pendingDecision: null,
  pendingDoomLoopIntervention: null,
  // Skill execution state (L2 layer)
  currentSkillExecution: null,
  // Context compression state
  contextCompressionInfo: null,
  // Plan Mode state
  currentPlan: null,
  planModeStatus: null,
  planLoading: false,
  planError: null,
  // New conversation pending state
  isNewConversationPending: false,
  // Title generation state
  isGeneratingTitle: false,
  titleGenerationError: null,
};

export const useAgentStore = create<AgentState>((set, get) => ({
  ...initialState,

  listConversations: async (
    projectId: string,
    status?: ConversationStatus,
    limit = 50
  ) => {
    set({ conversationsLoading: true, conversationsError: null });
    try {
      const conversations = await agentService.listConversations(
        projectId,
        status,
        limit
      );
      set({ conversations, conversationsLoading: false });
    } catch (error: any) {
      set({
        conversationsError:
          error.response?.data?.detail || "Failed to list conversations",
        conversationsLoading: false,
      });
      throw error;
    }
  },

  createConversation: async (projectId: string, title = "New Conversation") => {
    set({ conversationsLoading: true, conversationsError: null });
    try {
      const request: CreateConversationRequest = {
        project_id: projectId,
        title,
      };
      const conversation = await agentService.createConversation(request);
      const { conversations } = get();
      set({
        conversations: [conversation, ...conversations],
        currentConversation: conversation,
        conversationsLoading: false,
        isNewConversationPending: true, // Mark as pending to prevent URL sync effect race condition
      });
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

  getConversation: async (conversationId: string, projectId: string) => {
    set({ conversationsLoading: true, conversationsError: null });
    try {
      const conversation = await agentService.getConversation(
        conversationId,
        projectId
      );
      set({ currentConversation: conversation, conversationsLoading: false });
      return conversation;
    } catch (error: any) {
      set({
        conversationsError:
          error.response?.data?.detail || "Failed to get conversation",
        conversationsLoading: false,
      });
      return null;
    }
  },

  deleteConversation: async (conversationId: string, projectId: string) => {
    set({ conversationsLoading: true, conversationsError: null });
    try {
      await agentService.deleteConversation(conversationId, projectId);
      const { conversations, currentConversation } = get();
      set({
        conversations: conversations.filter((c) => c.id !== conversationId),
        currentConversation:
          currentConversation?.id === conversationId
            ? null
            : currentConversation,
        conversationsLoading: false,
      });
    } catch (error: any) {
      set({
        conversationsError:
          error.response?.data?.detail || "Failed to delete conversation",
        conversationsLoading: false,
      });
      throw error;
    }
  },

  setCurrentConversation: (
    conversation: Conversation | null,
    skipLoadMessages = false
  ) => {
    console.log(
      "[Agent] setCurrentConversation called:",
      conversation?.id,
      "skipLoadMessages:",
      skipLoadMessages
    );

    const { currentConversation: current, isNewConversationPending } = get();

    // Defensive check: Skip if same conversation and not a new conversation scenario
    // This prevents URL sync effect from triggering unnecessary state resets
    if (
      conversation &&
      current?.id === conversation.id &&
      !isNewConversationPending &&
      !skipLoadMessages
    ) {
      console.log(
        "[Agent] Same conversation, skipping redundant setCurrentConversation"
      );
      return;
    }

    // Always clear execution state and timeline when switching conversations
    // This prevents stale data from showing for different conversations
    set({
      currentConversation: conversation,
      // Clear timeline to prevent stale data from showing during load
      timeline: [],
      timelineLoading: true,
      // Clear pagination state
      earliestLoadedSequence: null,
      latestLoadedSequence: null,
      hasEarlierMessages: false,
      // Clear all execution-related state
      executionTimeline: [],
      currentToolExecution: null,
      toolExecutionHistory: [],
      currentWorkPlan: null,
      currentStepNumber: null,
      currentStepStatus: null,
      matchedPattern: null,
      currentThought: null,
      currentThoughtLevel: null,
      currentToolCall: null,
      currentObservation: null,
      assistantDraftContent: "",
      isTextStreaming: false,
      // Clear skill execution state
      currentSkillExecution: null,
    });

    if (conversation) {
      // Auto-load timeline for this conversation (unless skipLoadMessages is true)
      if (!skipLoadMessages) {
        console.log(
          "[Agent] Calling getTimeline for conversation:",
          conversation.id,
          "project:",
          conversation.project_id
        );
        get().getTimeline(conversation.id, conversation.project_id);
      } else {
        // skipLoadMessages is true (e.g., new conversation) - timeline already cleared above
        set({ timelineLoading: false });
      }
    } else {
      set({ timelineLoading: false });
    }
  },

  getTimeline: async (
    conversationId: string,
    projectId: string,
    limit = 100
  ) => {
    console.log("[Agent] getTimeline called:", conversationId, projectId);
    set({ timelineLoading: true, timelineError: null });
    try {
      const response = await agentService.getConversationMessages(
        conversationId,
        projectId,
        limit
      ) as any;  // Type cast to access pagination metadata

      console.log(
        "[Agent] getTimeline response:",
        response.timeline.length,
        "events"
      );

      // Extract pagination metadata from response
      const firstSequence = response.timeline[0]?.sequenceNumber ?? null;
      const lastSequence = response.timeline[response.timeline.length - 1]?.sequenceNumber ?? null;

      set({
        timeline: response.timeline,
        timelineLoading: false,
        earliestLoadedSequence: firstSequence,
        latestLoadedSequence: lastSequence,
        hasEarlierMessages: response.has_more ?? false,
      });
    } catch (error: any) {
      console.error("[Agent] getTimeline error:", error);
      set({
        timelineError: error.response?.data?.detail || "Failed to get timeline",
        timelineLoading: false,
      });
      throw error;
    }
  },

  addTimelineEvent: (event: TimelineEvent) => {
    const { timeline } = get();
    // Prevent duplicate events - check by sequenceNumber
    const lastEvent = timeline[timeline.length - 1];
    if (lastEvent && lastEvent.sequenceNumber >= event.sequenceNumber) {
      console.log("[Agent] Skipping duplicate event:", event.type, event.id);
      return;
    }

    // Assign next sequence number if not provided or is 0
    const maxSeq = Math.max(0, ...timeline.map((e) => e.sequenceNumber));
    const newEvent = {
      ...event,
      sequenceNumber: event.sequenceNumber > 0 ? event.sequenceNumber : maxSeq + 1,
    };

    console.log(
      "[Agent] Adding timeline event:",
      newEvent.type,
      "seq:",
      newEvent.sequenceNumber
    );
    set({ timeline: [...timeline, newEvent] });
  },

  clearTimeline: () => set({ timeline: [] }),

  prependTimelineEvents: (events: TimelineEvent[]) => {
    const { timeline } = get();
    // Add new events at the beginning of the timeline
    set({ timeline: [...events, ...timeline] });
  },

  loadEarlierMessages: async (
    conversationId: string,
    projectId: string,
    limit = 50
  ) => {
    const { earliestLoadedSequence, timelineLoading } = get();

    // Guard: Don't load if already loading or no pagination point exists
    if (!earliestLoadedSequence || timelineLoading) {
      console.log("[Agent] Cannot load earlier messages: no pagination point or already loading");
      return;
    }

    console.log("[Agent] Loading earlier messages before sequence:", earliestLoadedSequence);
    set({ timelineLoading: true, timelineError: null });

    try {
      const response = await agentService.getConversationMessages(
        conversationId,
        projectId,
        limit,
        undefined,  // from_sequence
        earliestLoadedSequence  // before_sequence
      ) as any;

      // Prepend new events to existing timeline
      const { timeline } = get();
      const newTimeline = [...response.timeline, ...timeline];

      set({
        timeline: newTimeline,
        timelineLoading: false,
        earliestLoadedSequence: response.timeline[0]?.sequenceNumber ?? null,
        hasEarlierMessages: response.has_more ?? false,
      });
    } catch (error: any) {
      console.error("[Agent] Failed to load earlier messages:", error);
      set({
        timelineError: error.response?.data?.detail || "Failed to load earlier messages",
        timelineLoading: false,
      });
      throw error;
    }
  },

  sendMessage: async (
    conversationId: string,
    messageText: string,
    _projectId: string
  ) => {
    // Prevent sending multiple messages simultaneously using a lock
    if (sendMessageLock) {
      console.warn(
        "[Agent] Message send already in progress, ignoring duplicate request"
      );
      return;
    }

    const { isStreaming } = get();
    if (isStreaming) {
      console.warn(
        "[Agent] Already streaming, ignoring duplicate send request"
      );
      return;
    }

    sendMessageLock = true;
    // Clear previous execution state before starting new message
    set({
      isStreaming: true,
      timelineError: null,
      // Clear execution timeline for new message
      executionTimeline: [],
      currentToolExecution: null,
      toolExecutionHistory: [],
      currentWorkPlan: null,
      currentStepNumber: null,
      currentStepStatus: null,
      matchedPattern: null,
      // Clear skill execution state
      currentSkillExecution: null,
    });

    // Generate temporary ID for rollback on error
    const tempId = `temp-${Date.now()}-${Math.random()
      .toString(36)
      .substr(2, 9)}`;
    
    // Create user message as TimelineEvent
    const userMessageEvent: TimelineEvent = {
      id: tempId,
      type: "user_message",
      sequenceNumber: 0, // Will be assigned by addTimelineEvent
      timestamp: Date.now(),
      content: messageText,
      role: "user",
    } as TimelineEvent;
    console.log("[Agent] sendMessage: calling addTimelineEvent for user message", messageText);
    get().addTimelineEvent(userMessageEvent);

    // Track if we received the first event from server (success signal)
    let receivedServerEvent = false;

    // Text delta buffering for performance optimization
    // Instead of updating state on every character, we batch updates
    let textDeltaBuffer = "";
    let textDeltaFlushTimer: ReturnType<typeof setTimeout> | null = null;
    // Performance optimization: Reduced buffering for faster perceived responsiveness
    // 16ms = 1 frame at 60fps (imperceptible delay)
    // 50 chars = balance between update frequency and render performance
    const TEXT_DELTA_FLUSH_INTERVAL = 16; // ms - flush every 16ms for 60fps updates
    const TEXT_DELTA_BUFFER_SIZE = 50; // chars - flush if buffer exceeds this size

    const flushTextDeltaBuffer = () => {
      if (textDeltaBuffer) {
        get().onTextDelta(textDeltaBuffer);
        textDeltaBuffer = "";
      }
      if (textDeltaFlushTimer) {
        clearTimeout(textDeltaFlushTimer);
        textDeltaFlushTimer = null;
      }
    };

    // Create stream handler with multi-level thinking support
    const handler: AgentStreamHandler = {
      onMessage: (event: any) => {
        receivedServerEvent = true;
        const { data } = event;
        const messageRole = data.role as MessageRole;
        const artifacts = data.artifacts as ArtifactReference[] | undefined;

        // Skip user messages from SSE - we already added them client-side
        // The backend echoes user messages in the stream, but we don't want duplicates
        if (messageRole === "user") {
          console.log(
            "[Agent] onMessage: skipping user message from SSE (already added client-side)"
          );
          return;
        }

        // Create assistant message as TimelineEvent
        const assistantEvent: TimelineEvent = {
          id: data.id || `assistant-${Date.now()}`,
          type: "assistant_message",
          sequenceNumber: 0, // Will be assigned by addTimelineEvent
          timestamp: Date.now(),
          content: data.content as string,
          role: "assistant",
          artifacts,
          metadata: artifacts ? { artifacts } : undefined,
        } as TimelineEvent;
        console.log(
          "[Agent] onMessage: adding assistant event",
          assistantEvent.type,
          (assistantEvent as any).content?.substring(0, 50),
          "ID:",
          assistantEvent.id
        );
        get().addTimelineEvent(assistantEvent);
      },

      onThought: (event: any) => {
        receivedServerEvent = true;
        const thought = event.data.thought as string;
        const thoughtLevel = (event.data.thought_level as ThoughtLevel) || null;
        const stepNumber = event.data.step_number as number | undefined;

        // Append thought to current step in timeline
        const { executionTimeline, currentStepNumber } = get();
        const targetStepNumber = stepNumber ?? currentStepNumber;

        if (targetStepNumber !== null && targetStepNumber !== undefined) {
          const updatedTimeline = executionTimeline.map((step) =>
            step.stepNumber === targetStepNumber
              ? { ...step, thoughts: [...step.thoughts, thought] }
              : step
          );
          set({
            currentThought: thought,
            currentThoughtLevel: thoughtLevel,
            executionTimeline: updatedTimeline,
          });
        } else {
          set({
            currentThought: thought,
            currentThoughtLevel: thoughtLevel,
          });
        }
      },

      onWorkPlan: (event: any) => {
        receivedServerEvent = true;
        const { data } = event;
        const workPlan: WorkPlan = {
          id: data.plan_id as string,
          conversation_id: data.conversation_id as string,
          status: data.status as PlanStatus,
          steps: (data.steps as any[]).map((s: any) => ({
            step_number: s.step_number,
            description: s.description,
            thought_prompt: "",
            required_tools: s.required_tools || [],
            expected_output: s.expected_output,
            dependencies: [],
          })),
          current_step_index: data.current_step as number,
          workflow_pattern_id: data.workflow_pattern_id as string | undefined,
          created_at: new Date().toISOString(),
        };

        // Build execution timeline skeleton from work plan
        const timelineSteps: TimelineStep[] = (data.steps as any[]).map(
          (s: any) => ({
            stepNumber: s.step_number as number,
            description: s.description as string,
            status: "pending" as const,
            thoughts: [],
            toolExecutions: [],
          })
        );

        set({
          currentWorkPlan: workPlan,
          executionTimeline: timelineSteps,
          toolExecutionHistory: [],
        });
      },

      onPatternMatch: (event: any) => {
        receivedServerEvent = true;
        const { data } = event;
        set({
          matchedPattern: {
            id: data.pattern_id as string,
            similarity: data.similarity_score as number,
            query: data.query as string,
          },
        });
      },

      onStepStart: (event: any) => {
        receivedServerEvent = true;
        const stepNumber = event.data.step_number as number;
        const description = event.data.description as string;

        // Update execution timeline step status
        const { executionTimeline } = get();
        const updatedTimeline = executionTimeline.map((step) =>
          step.stepNumber === stepNumber
            ? {
                ...step,
                status: "running" as const,
                startTime: new Date().toISOString(),
              }
            : step
        );

        set({
          currentStepNumber: stepNumber,
          currentStepStatus: "running" as const,
          currentThought: `Executing step ${stepNumber}: ${description}`,
          executionTimeline: updatedTimeline,
        });
      },

      onStepEnd: (event: any) => {
        receivedServerEvent = true;
        const stepNumber = event.data.step_number as number;
        const success = event.data.success as boolean;
        const currentStep = event.data.current_step as number;
        const endTime = new Date().toISOString();

        const {
          currentWorkPlan: prev,
          executionTimeline,
          toolExecutionHistory,
        } = get();

        // Update execution timeline step status AND tool executions within the step
        const updatedTimeline = executionTimeline.map((step) => {
          if (step.stepNumber === stepNumber) {
            const startTimeMs = step.startTime
              ? new Date(step.startTime).getTime()
              : 0;
            const endTimeMs = new Date(endTime).getTime();
            const duration = startTimeMs ? endTimeMs - startTimeMs : undefined;

            // Also update any "running" tool executions to match step status
            const updatedToolExecutions = step.toolExecutions.map((exec) =>
              exec.status === "running"
                ? {
                    ...exec,
                    status: success
                      ? ("success" as const)
                      : ("failed" as const),
                    endTime,
                  }
                : exec
            );

            return {
              ...step,
              status: success ? ("completed" as const) : ("failed" as const),
              endTime,
              duration,
              toolExecutions: updatedToolExecutions,
            };
          }
          return step;
        });

        // Also update tool execution history for consistency
        const toolIdsInStep =
          executionTimeline
            .find((s) => s.stepNumber === stepNumber)
            ?.toolExecutions.map((t) => t.id) ?? [];

        const updatedHistory = toolExecutionHistory.map((exec) =>
          toolIdsInStep.includes(exec.id) && exec.status === "running"
            ? {
                ...exec,
                status: success ? ("success" as const) : ("failed" as const),
                endTime,
              }
            : exec
        );

        set({
          currentStepStatus: success
            ? ("completed" as const)
            : ("failed" as const),
          currentWorkPlan: prev
            ? {
                ...prev,
                current_step_index: currentStep,
              }
            : null,
          executionTimeline: updatedTimeline,
          toolExecutionHistory: updatedHistory,
        });
      },

      onAct: (event: any) => {
        receivedServerEvent = true;
        const toolName = event.data.tool_name as string;
        const toolInput = event.data.tool_input as Record<string, unknown>;
        const stepNumber = event.data.step_number as number | undefined;
        const callId = event.data.call_id as string | undefined;
        const startTime = new Date().toISOString();
        const toolId =
          callId ||
          `tool-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

        const { toolExecutionHistory, executionTimeline, currentStepNumber } =
          get();
        const existingTool = toolExecutionHistory.find(
          (exec) => exec.id === toolId
        );
        const targetStepNumber = stepNumber ?? currentStepNumber;

        // Prepare all state updates
        let updatedHistory = toolExecutionHistory;
        let updatedTimeline = executionTimeline;
        let effectiveStartTime = startTime;

        if (existingTool) {
          // Update existing tool
          effectiveStartTime = existingTool.startTime || startTime;
          updatedHistory = toolExecutionHistory.map((exec) =>
            exec.id === toolId
              ? { ...exec, input: toolInput, status: "running" as const }
              : exec
          );
        } else {
          // Create new tool execution record
          const toolExecution: ToolExecution = {
            id: toolId,
            toolName,
            input: toolInput,
            status: "running",
            startTime,
            stepNumber,
          };
          updatedHistory = [...toolExecutionHistory, toolExecution];

          // Add to timeline if we have a step number
          if (targetStepNumber !== null && targetStepNumber !== undefined) {
            updatedTimeline = executionTimeline.map((step) =>
              step.stepNumber === targetStepNumber
                ? {
                    ...step,
                    toolExecutions: [...step.toolExecutions, toolExecution],
                  }
                : step
            );
          }
        }

        // Single set() call with all updates
        set({
          currentToolCall: {
            name: toolName,
            input: toolInput,
            stepNumber,
          },
          currentThought: null,
          currentToolExecution: {
            id: toolId,
            toolName,
            input: toolInput,
            stepNumber,
            startTime: effectiveStartTime,
          },
          executionTimeline: updatedTimeline,
          toolExecutionHistory: updatedHistory,
        });
      },

      onObserve: (event: any) => {
        receivedServerEvent = true;
        const observation = event.data.observation as string;
        const callId = event.data.call_id as string | undefined;
        const endTime = new Date().toISOString();

        const {
          currentToolExecution,
          executionTimeline,
          toolExecutionHistory,
        } = get();

        // Try to match by call_id first, then fall back to currentToolExecution
        const targetToolId = callId || currentToolExecution?.id;

        // Prepare state updates
        let updatedHistory = toolExecutionHistory;
        let updatedTimeline = executionTimeline;
        let shouldClearToolExecution = false;

        if (targetToolId) {
          const targetExecution = toolExecutionHistory.find(
            (exec) => exec.id === targetToolId
          );
          const startTimeMs = targetExecution?.startTime
            ? new Date(targetExecution.startTime).getTime()
            : currentToolExecution
            ? new Date(currentToolExecution.startTime).getTime()
            : 0;
          const endTimeMs = new Date(endTime).getTime();
          const duration = startTimeMs ? endTimeMs - startTimeMs : undefined;

          // Determine if it's an error (simple heuristic)
          const isError =
            observation?.toLowerCase().startsWith("error:") ||
            observation?.toLowerCase().includes("failed");

          // Update tool execution in history
          updatedHistory = toolExecutionHistory.map((exec) =>
            exec.id === targetToolId
              ? {
                  ...exec,
                  status: isError ? ("failed" as const) : ("success" as const),
                  result: isError ? undefined : observation,
                  error: isError ? observation : undefined,
                  endTime,
                  duration,
                }
              : exec
          );

          // Update tool execution in timeline
          const targetStepNumber =
            targetExecution?.stepNumber ?? currentToolExecution?.stepNumber;

          if (targetStepNumber !== null && targetStepNumber !== undefined) {
            updatedTimeline = executionTimeline.map((step) =>
              step.stepNumber === targetStepNumber
                ? {
                    ...step,
                    toolExecutions: step.toolExecutions.map((exec) =>
                      exec.id === targetToolId
                        ? {
                            ...exec,
                            status: isError
                              ? ("failed" as const)
                              : ("success" as const),
                            result: isError ? undefined : observation,
                            error: isError ? observation : undefined,
                            endTime,
                            duration,
                          }
                        : exec
                    ),
                  }
                : step
            );
          }

          shouldClearToolExecution = true;
        }

        // Single set() call with all updates
        set({
          currentObservation: observation,
          currentToolExecution: shouldClearToolExecution
            ? null
            : currentToolExecution,
          executionTimeline: updatedTimeline,
          toolExecutionHistory: updatedHistory,
        });
      },

      // Typewriter effect handlers
      onTextStart: () => {
        console.log("[Agent] TEXT_START received - starting typewriter effect");
        receivedServerEvent = true;
        get().onTextStart();
      },

      onTextDelta: (event: any) => {
        receivedServerEvent = true;
        const delta = event.data?.delta as string;
        
        if (!delta) {
          console.warn("[Agent] TEXT_DELTA received with empty delta:", event);
          return;
        }

        // Buffer the delta instead of updating state immediately
        textDeltaBuffer += delta;
        
        // Log every 5th delta or when buffer is about to flush
        if (textDeltaBuffer.length <= delta.length || textDeltaBuffer.length >= TEXT_DELTA_BUFFER_SIZE) {
          console.log(
            `[Agent] TEXT_DELTA: +${delta.length} chars, buffer=${textDeltaBuffer.length}, ` +
            `preview="${delta.substring(0, 20)}..."`
          );
        }

        // Flush if buffer is large enough
        if (textDeltaBuffer.length >= TEXT_DELTA_BUFFER_SIZE) {
          flushTextDeltaBuffer();
        } else if (!textDeltaFlushTimer) {
          // Schedule a flush if none pending
          textDeltaFlushTimer = setTimeout(
            flushTextDeltaBuffer,
            TEXT_DELTA_FLUSH_INTERVAL
          );
        }
      },

      onTextEnd: (event: any) => {
        const fullText = event.data?.full_text;
        console.log(
          `[Agent] TEXT_END received - fullText=${fullText?.length || 0} chars, ` +
          `buffered=${textDeltaBuffer.length} chars`
        );
        receivedServerEvent = true;
        // Flush any remaining buffered text before ending
        flushTextDeltaBuffer();
        get().onTextEnd(fullText as string | undefined);
      },

      // Human interaction handlers
      onClarificationAsked: (event: any) => {
        receivedServerEvent = true;
        const { data } = event;
        set({
          pendingClarification: data as ClarificationAskedEventData,
        });
      },

      onClarificationAnswered: () => {
        receivedServerEvent = true;
        set({
          pendingClarification: null,
        });
      },

      onDecisionAsked: (event: any) => {
        receivedServerEvent = true;
        const { data } = event;
        set({
          pendingDecision: data as DecisionAskedEventData,
        });
      },

      onDecisionAnswered: () => {
        receivedServerEvent = true;
        set({
          pendingDecision: null,
        });
      },

      onDoomLoopDetected: (event: any) => {
        receivedServerEvent = true;
        const { data } = event;
        set({
          pendingDoomLoopIntervention: data as DoomLoopDetectedEventData,
        });
      },

      onDoomLoopIntervened: () => {
        receivedServerEvent = true;
        set({
          pendingDoomLoopIntervention: null,
        });
      },

      // Skill execution handlers (L2 layer)
      onSkillMatched: (event: any) => {
        receivedServerEvent = true;
        const data = event.data as SkillMatchedEventData;
        const skillExecution: SkillExecutionState = {
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
        set({ currentSkillExecution: skillExecution });
      },

      onSkillExecutionStart: (event: any) => {
        receivedServerEvent = true;
        const data = event.data as SkillExecutionStartEventData;
        const { currentSkillExecution } = get();
        if (currentSkillExecution) {
          set({
            currentSkillExecution: {
              ...currentSkillExecution,
              status: "executing",
              total_steps: data.total_steps,
            },
          });
        }
      },

      onSkillToolStart: (event: any) => {
        receivedServerEvent = true;
        const data = event.data as SkillToolStartEventData;
        const { currentSkillExecution } = get();
        if (currentSkillExecution) {
          const toolExecution: SkillToolExecution = {
            tool_name: data.tool_name,
            tool_input: data.tool_input,
            status: "running",
            step_index: data.step_index,
          };
          set({
            currentSkillExecution: {
              ...currentSkillExecution,
              current_step: data.step_index,
              tool_executions: [
                ...currentSkillExecution.tool_executions,
                toolExecution,
              ],
            },
          });
        }
      },

      onSkillToolResult: (event: any) => {
        receivedServerEvent = true;
        const data = event.data as SkillToolResultEventData;
        const { currentSkillExecution } = get();
        if (currentSkillExecution) {
          const updatedToolExecutions =
            currentSkillExecution.tool_executions.map((exec) =>
              exec.step_index === data.step_index
                ? {
                    ...exec,
                    result: data.result,
                    error: data.error,
                    status: data.status,
                    duration_ms: data.duration_ms,
                  }
                : exec
            );
          set({
            currentSkillExecution: {
              ...currentSkillExecution,
              tool_executions: updatedToolExecutions,
            },
          });
        }
      },

      onSkillExecutionComplete: (event: any) => {
        receivedServerEvent = true;
        const data = event.data as SkillExecutionCompleteEventData;
        const { currentSkillExecution } = get();
        if (currentSkillExecution) {
          set({
            currentSkillExecution: {
              ...currentSkillExecution,
              status: data.success ? "completed" : "failed",
              summary: data.summary,
              error: data.error,
              execution_time_ms: data.execution_time_ms,
              completed_at: new Date().toISOString(),
            },
          });
        }
      },

      onSkillFallback: (event: any) => {
        receivedServerEvent = true;
        const data = event.data as SkillFallbackEventData;
        const { currentSkillExecution } = get();
        if (currentSkillExecution) {
          set({
            currentSkillExecution: {
              ...currentSkillExecution,
              status: "fallback",
              error: data.error || `Fallback: ${data.reason}`,
            },
          });
        }
      },

      onContextCompressed: (event: any) => {
        receivedServerEvent = true;
        const data = event.data as ContextCompressedEventData;
        console.log("[Agent] Context compressed:", data);
        set({
          contextCompressionInfo: {
            wasCompressed: data.was_compressed,
            compressionStrategy: data.compression_strategy,
            originalMessageCount: data.original_message_count,
            finalMessageCount: data.final_message_count,
            estimatedTokens: data.estimated_tokens,
            tokenBudget: data.token_budget,
            budgetUtilizationPct: data.budget_utilization_pct,
            summarizedMessageCount: data.summarized_message_count,
          },
        });
      },

      onComplete: async (event: any) => {
        receivedServerEvent = true;
        // Flush any remaining buffered text
        flushTextDeltaBuffer();

        // Complete event contains the final response - add it as a message
        const { data } = event;
        console.log("[Agent] onComplete received:", {
          hasContent: !!data.content,
          contentLength: data.content?.length,
          dataId: data.id,
          messageId: data.message_id,
        });
        if (data.content) {
          const artifacts = data.artifacts as ArtifactReference[] | undefined;
          // Create assistant message as TimelineEvent
          const assistantEvent: TimelineEvent = {
            id: data.id || `assistant-complete-${Date.now()}`,
            type: "assistant_message",
            sequenceNumber: 0, // Will be assigned by addTimelineEvent
            timestamp: Date.now(),
            content: data.content as string,
            role: "assistant",
            artifacts,
            metadata: artifacts ? { artifacts } : undefined,
          } as TimelineEvent;
          console.log("[Agent] onComplete calling addTimelineEvent with:", {
            id: assistantEvent.id,
            type: assistantEvent.type,
            contentPreview: (assistantEvent as any).content?.substring(0, 50),
          });
          get().addTimelineEvent(assistantEvent);
        }

        // Generate friendly title if conversation still has default title
        const { currentConversation, timeline, isGeneratingTitle } = get();

        // Only count message events (user_message and assistant_message), not all timeline events
        // This prevents the condition from being too restrictive when there are many thought/act/observe events
        const messageCount = timeline.filter(
          (e) => e.type === "user_message" || e.type === "assistant_message"
        ).length;

        // Debug logging to diagnose title generation issues
        console.log("[Agent] Title generation check:", {
          conversationId,
          currentConversationId: currentConversation?.id,
          title: currentConversation?.title,
          messageCount,
          timelineLength: timeline.length,
          isGeneratingTitle,
          shouldTrigger:
            currentConversation?.title === "New Conversation" &&
            messageCount <= 4 &&
            !isGeneratingTitle,
        });

        if (
          currentConversation?.title === "New Conversation" &&
          messageCount <= 4 &&  // Only trigger when there are few messages (not events)
          !isGeneratingTitle  // Prevent concurrent generation
        ) {
          // Only generate title for the first few messages to avoid unnecessary API calls
          const projectId = currentConversation?.project_id;
          const targetConversationId = currentConversation?.id || conversationId;

          if (projectId && targetConversationId) {
            console.log(
              "[Agent] Triggering title generation for conversation:",
              targetConversationId,
              `messageCount=${messageCount}`
            );
            get().generateConversationTitle(targetConversationId, projectId);
          } else {
            console.warn(
              "[Agent] Skipping title generation - missing data:",
              { projectId, targetConversationId, currentConversation }
            );
          }
        }

        sendMessageLock = false;
        set({
          isStreaming: false,
          isNewConversationPending: false, // Clear pending flag after SSE completes
          currentThought: null,
          currentThoughtLevel: null,
          currentToolCall: null,
          currentObservation: null,
          // Keep execution timeline visible after completion
          // currentWorkPlan, executionTimeline, toolExecutionHistory are preserved
          // They will be cleared when sending next message
          currentToolExecution: null,
          assistantDraftContent: "",
          isTextStreaming: false,
        });
      },

      onError: (event: any) => {
        // Clean up text delta buffer
        if (textDeltaFlushTimer) {
          clearTimeout(textDeltaFlushTimer);
          textDeltaFlushTimer = null;
        }
        textDeltaBuffer = "";

        sendMessageLock = false;
        set({
          timelineError: event.data.message as string,
          isStreaming: false,
          isNewConversationPending: false, // Clear pending flag on error
          currentThought: null,
          currentThoughtLevel: null,
          currentToolCall: null,
          currentObservation: null,
          // Keep execution timeline visible after error for debugging
          currentToolExecution: null,
          assistantDraftContent: "",
          isTextStreaming: false,
        });
      },

      onClose: () => {
        // Clean up text delta buffer
        if (textDeltaFlushTimer) {
          clearTimeout(textDeltaFlushTimer);
          textDeltaFlushTimer = null;
        }
        textDeltaBuffer = "";

        sendMessageLock = false;
        // If we never received any server event before close, remove the temp message event
        if (!receivedServerEvent) {
          const { timeline } = get();
          set({ timeline: timeline.filter((e) => e.id !== tempId) });
        }
        set({
          isStreaming: false,
          isNewConversationPending: false, // Clear pending flag on close
          currentThought: null,
          currentThoughtLevel: null,
          currentToolCall: null,
          currentObservation: null,
          // Keep execution timeline visible after close
          currentToolExecution: null,
          assistantDraftContent: "",
          isTextStreaming: false,
        });
      },
    };

    try {
      await agentService.chat(
        { conversation_id: conversationId, message: messageText, project_id: _projectId },
        handler
      );
    } catch (error: any) {
      sendMessageLock = false;
      // Rollback: remove the temporary user message event on error
      const { timeline } = get();
      set({
        timeline: timeline.filter((e) => e.id !== tempId),
        timelineError: error.response?.data?.detail || "Failed to send message",
        isStreaming: false,
        isNewConversationPending: false, // Clear pending flag on catch error
      });
      throw error;
    }
  },

  stopChat: (conversationId: string) => {
    agentService.stopChat(conversationId);
    set({
      isStreaming: false,
      isNewConversationPending: false, // Clear pending flag on stop
      currentThought: null,
      currentThoughtLevel: null,
      currentToolCall: null,
      currentObservation: null,
      currentWorkPlan: null,
      currentStepNumber: null,
      currentStepStatus: null,
      matchedPattern: null,
      // Clear execution timeline state
      executionTimeline: [],
      currentToolExecution: null,
      toolExecutionHistory: [],
      // Clear skill execution state
      currentSkillExecution: null,
    });
  },

  generateConversationTitle: async (
    conversationId: string,
    projectId: string
  ) => {
    // Prevent concurrent title generation
    const { isGeneratingTitle } = get();
    if (isGeneratingTitle) {
      console.log("[Agent] Title generation already in progress, skipping");
      return;
    }

    set({ isGeneratingTitle: true, titleGenerationError: null });

    try {
      const updatedConversation = await agentService.generateConversationTitle(
        conversationId,
        projectId
      );
      // Update the conversation in the list
      const { conversations, currentConversation } = get();
      if (currentConversation?.id === conversationId) {
        set({ currentConversation: updatedConversation });
      }
      // Update in conversations list
      const updatedList = conversations.map((c) =>
        c.id === conversationId ? updatedConversation : c
      );
      set({ conversations: updatedList });
      console.log(
        "[Agent] Generated conversation title:",
        updatedConversation.title
      );
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || "Failed to generate title";
      console.error("[Agent] Failed to generate conversation title:", error);
      set({ titleGenerationError: errorMsg });
    } finally {
      set({ isGeneratingTitle: false });
    }
  },

  getExecutionHistory: async (
    conversationId: string,
    projectId: string,
    limit = 50
  ) => {
    set({ executionHistoryLoading: true });
    try {
      const response = await agentService.getExecutionHistory(
        conversationId,
        projectId,
        limit
      );
      set({
        executionHistory: response.executions,
        executionHistoryLoading: false,
      });
    } catch (error: any) {
      console.error("Failed to get execution history:", error);
      set({ executionHistoryLoading: false });
      throw error;
    }
  },

  listTools: async () => {
    set({ toolsLoading: true });
    try {
      const response = await agentService.listTools();
      set({ tools: response.tools, toolsLoading: false });
    } catch (error: any) {
      console.error("Failed to list tools:", error);
      set({ toolsLoading: false });
    }
  },

  // Typewriter effect actions
  onTextStart: () => {
    console.log("[Agent] onTextStart: setting isTextStreaming=true");
    set({
      assistantDraftContent: "",
      isTextStreaming: true,
    });
  },

  onTextDelta: (delta: string) => {
    console.log("[Agent] onTextDelta: received delta length=", delta.length, "content=", delta.substring(0, 50));
    set((state) => {
      const newContent = state.assistantDraftContent + delta;
      console.log("[Agent] onTextDelta: new content length=", newContent.length);
      return { assistantDraftContent: newContent };
    });
  },

  onTextEnd: (fullText?: string) => {
    console.log("[Agent] onTextEnd: fullText length=", fullText?.length, "setting isTextStreaming=false");
    set((state) => ({
      assistantDraftContent: fullText || state.assistantDraftContent,
      isTextStreaming: false,
    }));
  },

  clearDraft: () => {
    set({
      assistantDraftContent: "",
      isTextStreaming: false,
    });
  },

  // Human interaction response handlers
  respondToClarification: async (requestId: string, answer: string) => {
    // Send clarification response to backend via POST
    const token = localStorage.getItem("token");
    const baseUrl = import.meta.env.VITE_API_URL || "";

    await fetch(`${baseUrl}/api/v1/agent/clarification/respond`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        request_id: requestId,
        answer: answer,
      }),
    });

    // Clear pending clarification
    set({ pendingClarification: null });
  },

  respondToDecision: async (requestId: string, decision: string) => {
    // Send decision response to backend via POST
    const token = localStorage.getItem("token");
    const baseUrl = import.meta.env.VITE_API_URL || "";

    await fetch(`${baseUrl}/api/v1/agent/decision/respond`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        request_id: requestId,
        decision: decision,
      }),
    });

    // Clear pending decision
    set({ pendingDecision: null });
  },

  respondToDoomLoop: async (requestId: string, action: string) => {
    // Send doom loop intervention response to backend via POST
    const token = localStorage.getItem("token");
    const baseUrl = import.meta.env.VITE_API_URL || "";

    await fetch(`${baseUrl}/api/v1/agent/doom-loop/respond`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        request_id: requestId,
        action: action,
      }),
    });

    // Clear pending doom loop intervention
    set({ pendingDoomLoopIntervention: null });
  },

  clearPendingInteraction: () => {
    set({
      pendingClarification: null,
      pendingDecision: null,
      pendingDoomLoopIntervention: null,
    });
  },

  // Plan Mode actions
  enterPlanMode: async (
    conversationId: string,
    title: string,
    description?: string
  ) => {
    set({ planLoading: true, planError: null });
    try {
      const request: EnterPlanModeRequest = {
        conversation_id: conversationId,
        title,
        description,
      };
      const plan = await planService.enterPlanMode(request);
      set({
        currentPlan: plan,
        planModeStatus: {
          is_in_plan_mode: true,
          current_mode: "plan",
          current_plan_id: plan.id,
          plan: plan,
        },
        planLoading: false,
      });
      return plan;
    } catch (error: any) {
      set({
        planError: error.response?.data?.detail || "Failed to enter Plan Mode",
        planLoading: false,
      });
      throw error;
    }
  },

  exitPlanMode: async (
    conversationId: string,
    planId: string,
    approve = true,
    summary?: string
  ) => {
    set({ planLoading: true, planError: null });
    try {
      const request: ExitPlanModeRequest = {
        conversation_id: conversationId,
        plan_id: planId,
        approve,
        summary,
      };
      const plan = await planService.exitPlanMode(request);
      set({
        currentPlan: plan,
        planModeStatus: {
          is_in_plan_mode: false,
          current_mode: "build",
          current_plan_id: null,
          plan: null,
        },
        planLoading: false,
      });
      return plan;
    } catch (error: any) {
      set({
        planError: error.response?.data?.detail || "Failed to exit Plan Mode",
        planLoading: false,
      });
      throw error;
    }
  },

  getPlan: async (planId: string) => {
    set({ planLoading: true, planError: null });
    try {
      const plan = await planService.getPlan(planId);
      set({ currentPlan: plan, planLoading: false });
      return plan;
    } catch (error: any) {
      set({
        planError: error.response?.data?.detail || "Failed to get plan",
        planLoading: false,
      });
      throw error;
    }
  },

  updatePlan: async (planId: string, request: UpdatePlanRequest) => {
    set({ planLoading: true, planError: null });
    try {
      const plan = await planService.updatePlan(planId, request);
      set({ currentPlan: plan, planLoading: false });
      return plan;
    } catch (error: any) {
      set({
        planError: error.response?.data?.detail || "Failed to update plan",
        planLoading: false,
      });
      throw error;
    }
  },

  getPlanModeStatus: async (conversationId: string) => {
    set({ planLoading: true, planError: null });
    try {
      const status = await planService.getPlanModeStatus(conversationId);
      set({
        planModeStatus: status,
        currentPlan: status.plan,
        planLoading: false,
      });
      return status;
    } catch (error: any) {
      set({
        planError:
          error.response?.data?.detail || "Failed to get Plan Mode status",
        planLoading: false,
      });
      throw error;
    }
  },

  clearPlanState: () => {
    set({
      currentPlan: null,
      planModeStatus: null,
      planLoading: false,
      planError: null,
    });
  },

  clearErrors: () => {
    set({
      conversationsError: null,
      timelineError: null,
      planError: null,
    });
  },

  reset: () => {
    set(initialState);
  },
}));

// ============================================================================
// SELECTORS - Fine-grained subscriptions for performance
// ============================================================================
// Use these hooks in components to subscribe to only the state slices needed.
// This prevents unnecessary re-renders when other parts of the state change.
//
// Usage:
//   import { useCurrentConversation, useIsStreaming } from '@/stores/agent';
//   const conversation = useCurrentConversation(); // Only re-renders when conversation changes
//   const isStreaming = useIsStreaming(); // Only re-renders when streaming state changes
// ============================================================================

// Conversation selectors
export const useConversations = () =>
  useAgentStore((state) => state.conversations);
export const useCurrentConversation = () =>
  useAgentStore((state) => state.currentConversation);
export const useConversationsLoading = () =>
  useAgentStore((state) => state.conversationsLoading);
export const useConversationsError = () =>
  useAgentStore((state) => state.conversationsError);

// Timeline selectors (unified event stream)
export const useTimeline = () => useAgentStore((state) => state.timeline);
export const useTimelineLoading = () =>
  useAgentStore((state) => state.timelineLoading);
export const useTimelineError = () =>
  useAgentStore((state) => state.timelineError);

// Derived selectors for backward compatibility and convenience
export const useMessages = () =>
  useAgentStore((state) =>
    state.timeline
      .filter(
        (e) => e.type === "user_message" || e.type === "assistant_message"
      )
      .map((e) => ({
        id: e.id,
        role: (e as any).role || (e.type === "user_message" ? "user" : "assistant"),
        content: (e as any).content || "",
        created_at: new Date(e.timestamp).toISOString(),
        // These fields may not be present in timeline events but are expected by ChatArea
        tool_calls: (e as any).tool_calls,
        tool_results: (e as any).tool_results,
        artifacts: (e as any).artifacts || (e as any).metadata?.artifacts,
        metadata:
          (e as any).metadata ||
          ((e as any).artifacts
            ? { artifacts: (e as any).artifacts }
            : undefined),
      }))
  );
export const useMessagesLoading = () =>
  useAgentStore((state) => state.timelineLoading);
export const useMessagesError = () =>
  useAgentStore((state) => state.timelineError);

// Streaming state selectors
export const useIsStreaming = () => useAgentStore((state) => state.isStreaming);
export const useCurrentThought = () =>
  useAgentStore((state) => state.currentThought);
export const useCurrentThoughtLevel = () =>
  useAgentStore((state) => state.currentThoughtLevel);
export const useCurrentToolCall = () =>
  useAgentStore((state) => state.currentToolCall);
export const useCurrentObservation = () =>
  useAgentStore((state) => state.currentObservation);

// Typewriter effect selectors
export const useAssistantDraftContent = () =>
  useAgentStore((state) => state.assistantDraftContent);
export const useIsTextStreaming = () =>
  useAgentStore((state) => state.isTextStreaming);

// Multi-level thinking selectors
export const useCurrentWorkPlan = () =>
  useAgentStore((state) => state.currentWorkPlan);
export const useCurrentStepNumber = () =>
  useAgentStore((state) => state.currentStepNumber);
export const useCurrentStepStatus = () =>
  useAgentStore((state) => state.currentStepStatus);
export const useMatchedPattern = () =>
  useAgentStore((state) => state.matchedPattern);

// Execution timeline selectors (new)
export const useExecutionTimeline = () =>
  useAgentStore((state) => state.executionTimeline);
export const useCurrentToolExecution = () =>
  useAgentStore((state) => state.currentToolExecution);
export const useToolExecutionHistory = () =>
  useAgentStore((state) => state.toolExecutionHistory);

// Skill execution selectors (L2 layer)
export const useCurrentSkillExecution = () =>
  useAgentStore((state) => state.currentSkillExecution);

// Execution history selectors
export const useExecutionHistory = () =>
  useAgentStore((state) => state.executionHistory);
export const useExecutionHistoryLoading = () =>
  useAgentStore((state) => state.executionHistoryLoading);

// Tools selectors
export const useTools = () => useAgentStore((state) => state.tools);
export const useToolsLoading = () =>
  useAgentStore((state) => state.toolsLoading);

// Human interaction selectors
export const usePendingClarification = () =>
  useAgentStore((state) => state.pendingClarification);
export const usePendingDecision = () =>
  useAgentStore((state) => state.pendingDecision);
export const usePendingDoomLoopIntervention = () =>
  useAgentStore((state) => state.pendingDoomLoopIntervention);

// Plan Mode selectors
export const useCurrentPlan = () => useAgentStore((state) => state.currentPlan);
export const usePlanModeStatus = () =>
  useAgentStore((state) => state.planModeStatus);
export const usePlanLoading = () => useAgentStore((state) => state.planLoading);
export const usePlanError = () => useAgentStore((state) => state.planError);
export const useIsInPlanMode = () =>
  useAgentStore((state) => state.planModeStatus?.is_in_plan_mode ?? false);

// New conversation pending state selector
export const useIsNewConversationPending = () =>
  useAgentStore((state) => state.isNewConversationPending);

// Title generation state selectors
export const useIsGeneratingTitle = () =>
  useAgentStore((state) => state.isGeneratingTitle);
export const useTitleGenerationError = () =>
  useAgentStore((state) => state.titleGenerationError);

// Pagination state selectors
export const useEarliestLoadedSequence = () =>
  useAgentStore((state) => state.earliestLoadedSequence);
export const useLatestLoadedSequence = () =>
  useAgentStore((state) => state.latestLoadedSequence);
export const useHasEarlierMessages = () =>
  useAgentStore((state) => state.hasEarlierMessages);

// Action selectors (for components that need to call actions)
export const useAgentActions = () =>
  useAgentStore((state) => ({
    listConversations: state.listConversations,
    createConversation: state.createConversation,
    getConversation: state.getConversation,
    deleteConversation: state.deleteConversation,
    setCurrentConversation: state.setCurrentConversation,
    getTimeline: state.getTimeline,
    addTimelineEvent: state.addTimelineEvent,
    clearTimeline: state.clearTimeline,
    prependTimelineEvents: state.prependTimelineEvents,
    loadEarlierMessages: state.loadEarlierMessages,
    sendMessage: state.sendMessage,
    stopChat: state.stopChat,
    generateConversationTitle: state.generateConversationTitle,
    getExecutionHistory: state.getExecutionHistory,
    listTools: state.listTools,
    // Plan Mode actions
    enterPlanMode: state.enterPlanMode,
    exitPlanMode: state.exitPlanMode,
    getPlan: state.getPlan,
    updatePlan: state.updatePlan,
    getPlanModeStatus: state.getPlanModeStatus,
    clearPlanState: state.clearPlanState,
    clearErrors: state.clearErrors,
    reset: state.reset,
  }));
