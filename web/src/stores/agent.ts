/**
 * Agent Store - Agent conversation and execution state management
 *
 * This store manages conversations, messages, timeline events, and agent execution state.
 * Supports multi-level thinking, work plans, tool execution, and Plan Mode.
 *
 * @module stores/agent
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
 * - Execution timeline visualization
 * - Tool execution history
 *
 * Timeline Events:
 * - Unified event stream (user/assistant messages, thoughts, tool calls)
 * - Pagination support for loading earlier messages
 * - Per-conversation state caching for concurrent conversations
 *
 * Human Interaction:
 * - Clarification requests/responses
 * - Decision requests/responses
 * - Doom loop detection and intervention
 *
 * @example
 * const {
 *   conversations,
 *   currentConversation,
 *   timeline,
 *   isStreaming,
 *   sendMessage,
 *   createConversation
 * } = useAgentStore();
 */

import { create } from "zustand";
import { devtools } from "zustand/middleware";
import { logger } from "../utils/logger";
import { agentService } from "../services/agentService";
import { planService } from "../services/planService";
import {
  
  isConversationLocked,
  setConversationLock,
  type ConversationLocks,
  type ConversationState,
} from "./agent/conversationState";
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
  ExecutionPlan,
  ExecutionStep,
  ExecutionStepStatus,
  MessageRole,
  PlanDocument,
  PlanModeEnterEventData,
  PlanModeExitEventData,
  PlanCreatedEventData,
  PlanModeStatus,
  PlanUpdatedEventData,
  PlanStatus,
  ReflectionResult,
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

// Per-conversation locks to prevent simultaneous message sends per conversation
let conversationLocks: ConversationLocks = new Map();

/**
 * Execution Plan Status for Plan Mode v2
 */
export type ExecutionPlanStatus =
  | "idle"
  | "planning"
  | "executing"
  | "reflecting"
  | "complete"
  | "failed";

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

  // Execution Plan state (Plan Mode v2)
  executionPlan: ExecutionPlan | null;
  reflectionResult: ReflectionResult | null;
  executionPlanStatus: ExecutionPlanStatus;
  detectionMethod: string | null;
  detectionConfidence: number | null;

  // Agent execution state
  isStreaming: boolean;
  streamStatus: 'idle' | 'connecting' | 'streaming' | 'error';
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

  // Per-conversation state map (for concurrent conversation switching)
  conversationStates: Map<string, ConversationState>;

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

  // Execution Plan actions (Plan Mode v2)
  updateExecutionPlanStatus: (status: ExecutionPlanStatus) => void;
  updateDetectionInfo: (method: string, confidence: number) => void;
  updateExecutionPlan: (plan: ExecutionPlan) => void;
  updateReflectionResult: (result: ReflectionResult) => void;
  updatePlanStepStatus: (
    stepId: string,
    status: ExecutionStepStatus,
    result?: string,
    error?: string
  ) => void;
  clearExecutionPlanState: () => void;

  // State management
  clearErrors: () => void;
  reset: () => void;

  // Per-conversation state actions (for concurrent conversation switching)
  getConversationState: (conversationId: string) => ConversationState | undefined;
  saveConversationState: (conversationId: string) => void;
  restoreConversationState: (conversationId: string) => void;
  deleteConversationState: (conversationId: string) => void;
  isConversationStreaming: (conversationId: string) => boolean;
  getStreamingStatuses: () => Map<string, boolean>;
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
  streamStatus: 'idle' as const,
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
  // Execution Plan state (Plan Mode v2)
  executionPlan: null as ExecutionPlan | null,
  reflectionResult: null as ReflectionResult | null,
  executionPlanStatus: 'idle' as const,
  detectionMethod: null as string | null,
  detectionConfidence: null as number | null,
  // New conversation pending state
  isNewConversationPending: false,
  // Title generation state
  isGeneratingTitle: false,
  titleGenerationError: null,

  // Per-conversation state map
  conversationStates: new Map<string, ConversationState>(),
};

export const useAgentStore = create<AgentState>()(
  devtools((set, get) => ({
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
    } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
      set({
        conversationsError:
          err?.response?.data?.detail || "Failed to list conversations",
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
    } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
      set({
        conversationsError:
          err?.response?.data?.detail || "Failed to create conversation",
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
    } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
      set({
        conversationsError:
          err?.response?.data?.detail || "Failed to get conversation",
        conversationsLoading: false,
      });
      return null;
    }
  },

  deleteConversation: async (conversationId: string, projectId: string) => {
    set({ conversationsLoading: true, conversationsError: null });
    try {
      await agentService.deleteConversation(conversationId, projectId);
      const { conversations, currentConversation, deleteConversationState } = get();
      set({
        conversations: conversations.filter((c) => c.id !== conversationId),
        currentConversation:
          currentConversation?.id === conversationId
            ? null
            : currentConversation,
        conversationsLoading: false,
      });
      // Also clean up saved conversation state
      deleteConversationState(conversationId);
    } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
      set({
        conversationsError:
          err?.response?.data?.detail || "Failed to delete conversation",
        conversationsLoading: false,
      });
      throw error;
    }
  },

  setCurrentConversation: (
    conversation: Conversation | null,
    skipLoadMessages = false
  ) => {
    logger.debug(
      "[Agent] setCurrentConversation called:",
      conversation?.id,
      "skipLoadMessages:",
      skipLoadMessages
    );

    const { currentConversation: current, isNewConversationPending, saveConversationState, restoreConversationState } = get();

    // Save current conversation state before switching (for concurrent conversation support)
    if (current?.id && current.id !== conversation?.id) {
      logger.debug("[Agent] Saving state for conversation:", current.id);
      saveConversationState(current.id);
    }

    // Defensive check: Skip if same conversation and not a new conversation scenario
    // This prevents URL sync effect from triggering unnecessary state resets
    if (
      conversation &&
      current?.id === conversation.id &&
      !isNewConversationPending &&
      !skipLoadMessages
    ) {
      logger.debug(
        "[Agent] Same conversation, skipping redundant setCurrentConversation"
      );
      return;
    }

    // Set the new conversation first
    set({ currentConversation: conversation });

    if (conversation) {
      // Try to restore saved state for this conversation (concurrent conversation support)
      const savedState = get().conversationStates.get(conversation.id);
      if (savedState) {
        logger.debug("[Agent] Restoring saved state for conversation:", conversation.id);
        restoreConversationState(conversation.id);
        set({ timelineLoading: false }); // Already have data
      } else {
        // No saved state - clear and load fresh
        set({
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

        // Auto-load timeline for this conversation (unless skipLoadMessages is true)
        if (!skipLoadMessages) {
          logger.debug(
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
      }
    } else {
      // No conversation selected - clear state
      set({
        timeline: [],
        timelineLoading: false,
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
        currentSkillExecution: null,
      });
    }
  },

  getTimeline: async (
    conversationId: string,
    projectId: string,
    limit = 100
  ) => {
    logger.debug("[Agent] getTimeline called:", conversationId, projectId);
    set({ timelineLoading: true, timelineError: null });
    try {
      const response = await agentService.getConversationMessages(
        conversationId,
        projectId,
        limit
      );

      logger.debug(
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
    } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
      logger.error("[Agent] getTimeline error:", error);
      set({
        timelineError: err?.response?.data?.detail || "Failed to get timeline",
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
      logger.debug("[Agent] Skipping duplicate event:", event.type, event.id);
      return;
    }

    // Assign next sequence number if not provided or is 0
    const maxSeq = Math.max(0, ...timeline.map((e) => e.sequenceNumber));
    const newEvent = {
      ...event,
      sequenceNumber: event.sequenceNumber > 0 ? event.sequenceNumber : maxSeq + 1,
    };

    logger.debug(
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
      logger.debug("[Agent] Cannot load earlier messages: no pagination point or already loading");
      return;
    }

    logger.debug("[Agent] Loading earlier messages before sequence:", earliestLoadedSequence);
    set({ timelineLoading: true, timelineError: null });

    try {
      const response = await agentService.getConversationMessages(
        conversationId,
        projectId,
        limit,
        undefined,  // from_sequence
        earliestLoadedSequence  // before_sequence
      );

      // Prepend new events to existing timeline
      const { timeline } = get();
      const newTimeline = [...response.timeline, ...timeline];

      set({
        timeline: newTimeline,
        timelineLoading: false,
        earliestLoadedSequence: response.timeline[0]?.sequenceNumber ?? null,
        hasEarlierMessages: response.has_more ?? false,
      });
    } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
      logger.error("[Agent] Failed to load earlier messages:", error);
      set({
        timelineError: err?.response?.data?.detail || "Failed to load earlier messages",
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
    // Prevent sending multiple messages simultaneously for the SAME conversation using per-conversation locks
    // This allows concurrent conversations to stream independently
    if (isConversationLocked(conversationLocks, conversationId)) {
      logger.warn(
        `[Agent] Message send already in progress for conversation ${conversationId}, ignoring duplicate request`
      );
      return;
    }

    // Set the lock for this conversation
    conversationLocks = setConversationLock(conversationLocks, conversationId, true);

    // Note: We don't check global isStreaming anymore - each conversation has its own lock
    // This allows multiple conversations to stream concurrently

    // Clear previous execution state before starting new message
    set({
      isStreaming: true,
      streamStatus: 'connecting',
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

    // Helper function to release the lock
    const releaseLock = () => {
      conversationLocks = setConversationLock(conversationLocks, conversationId, false);
    };

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
    logger.debug("[Agent] sendMessage: calling addTimelineEvent for user message", messageText);
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
          logger.debug(
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
        logger.debug(
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
        logger.debug("[Agent] TEXT_START received - starting typewriter effect");
        receivedServerEvent = true;
        get().onTextStart();
      },

      onTextDelta: (event: any) => {
        receivedServerEvent = true;
        const delta = event.data?.delta as string;
        
        if (!delta) {
          logger.warn("[Agent] TEXT_DELTA received with empty delta:", event);
          return;
        }

        // Buffer the delta instead of updating state immediately
        textDeltaBuffer += delta;
        
        // Log every 5th delta or when buffer is about to flush
        if (textDeltaBuffer.length <= delta.length || textDeltaBuffer.length >= TEXT_DELTA_BUFFER_SIZE) {
          logger.debug(
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
        logger.debug(
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
        logger.debug("[Agent] Context compressed:", data);
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

      // Plan Mode event handlers
      onPlanModeEnter: (event: any) => {
        receivedServerEvent = true;
        const data = event.data as PlanModeEnterEventData;
        logger.debug("[Agent] Plan mode entered:", data);
        set({
          planModeStatus: {
            is_in_plan_mode: true,
            current_mode: "plan",
            current_plan_id: data.plan_id,
            plan: null, // Will be loaded via onPlanCreated
          },
        });
      },

      onPlanModeExit: (event: any) => {
        receivedServerEvent = true;
        const data = event.data as PlanModeExitEventData;
        logger.debug("[Agent] Plan mode exited:", data);
        set({
          planModeStatus: {
            is_in_plan_mode: false,
            current_mode: "build",
            current_plan_id: null,
            plan: null,
          },
        });
      },

      onPlanCreated: (event: any) => {
        receivedServerEvent = true;
        const data = event.data as PlanCreatedEventData;
        logger.debug("[Agent] Plan created:", data);
        // Load the full plan document
        const { getPlan } = get();
        if (data.plan_id) {
          getPlan(data.plan_id).catch((err) => {
            logger.error("[Agent] Failed to load plan after creation:", err);
          });
        }
      },

      onPlanUpdated: (event: any) => {
        receivedServerEvent = true;
        const data = event.data as PlanUpdatedEventData;
        logger.debug("[Agent] Plan updated:", data);
        // Update current plan if it matches
        const { currentPlan, planModeStatus } = get();
        if (currentPlan?.id === data.plan_id) {
          set({
            currentPlan: {
              ...currentPlan,
              content: data.content ?? currentPlan.content,
              version: data.version ?? currentPlan.version,
              updated_at: new Date().toISOString(),
            },
          });
        } else if (planModeStatus?.current_plan_id === data.plan_id) {
          // Reload the plan if we don't have it but should
          const { getPlan } = get();
          getPlan(data.plan_id).catch((err) => {
            logger.error("[Agent] Failed to load plan after update:", err);
          });
        }
      },

      onTitleGenerated: (event: any) => {
        // Handle title_generated event from backend
        const data = event.data as {
          conversation_id: string;
          title: string;
          generated_at: string;
          message_id?: string;
          generated_by?: string;
        };
        logger.debug("[Agent] Title generated event:", data);

        const { currentConversation, conversations } = get();

        // Update current conversation if it matches
        if (currentConversation?.id === data.conversation_id) {
          set({
            currentConversation: {
              ...currentConversation,
              title: data.title,
            },
          });
        }

        // Update in conversations list
        const updatedList = conversations.map((c) =>
          c.id === data.conversation_id ? { ...c, title: data.title } : c
        );
        set({ conversations: updatedList });
      },

      onComplete: async (event: any) => {
        receivedServerEvent = true;
        // Flush any remaining buffered text
        flushTextDeltaBuffer();

        // Complete event contains the final response - add it as a message
        const { data } = event;
        logger.debug("[Agent] onComplete received:", {
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
          logger.debug("[Agent] onComplete calling addTimelineEvent with:", {
            id: assistantEvent.id,
            type: assistantEvent.type,
            contentPreview: (assistantEvent as any).content?.substring(0, 50),
          });
          get().addTimelineEvent(assistantEvent);
        }

        releaseLock();
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

        releaseLock();
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

        releaseLock();
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
    } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
      releaseLock();
      // Rollback: remove the temporary user message event on error
      const { timeline } = get();
      set({
        timeline: timeline.filter((e) => e.id !== tempId),
        timelineError: err?.response?.data?.detail || "Failed to send message",
        isStreaming: false,
        isNewConversationPending: false, // Clear pending flag on catch error
      });
      throw error;
    }
  },

  stopChat: (conversationId: string) => {
    agentService.stopChat(conversationId);
    // Release the lock for this conversation
    conversationLocks = setConversationLock(conversationLocks, conversationId, false);
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
      logger.debug("[Agent] Title generation already in progress, skipping");
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
      logger.debug(
        "[Agent] Generated conversation title:",
        updatedConversation.title
      );
    } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
      const errorMsg = err?.response?.data?.detail || "Failed to generate title";
      logger.error("[Agent] Failed to generate conversation title:", error);
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
    } catch (error: unknown) {
      logger.error("Failed to get execution history:", error);
      set({ executionHistoryLoading: false });
      throw error;
    }
  },

  listTools: async () => {
    set({ toolsLoading: true });
    try {
      const response = await agentService.listTools();
      set({ tools: response.tools, toolsLoading: false });
    } catch (error: unknown) {
      logger.error("Failed to list tools:", error);
      set({ toolsLoading: false });
    }
  },

  // Typewriter effect actions
  onTextStart: () => {
    logger.debug("[Agent] onTextStart: setting isTextStreaming=true");
    set({
      assistantDraftContent: "",
      isTextStreaming: true,
    });
  },

  onTextDelta: (delta: string) => {
    logger.debug("[Agent] onTextDelta: received delta length=", delta.length, "content=", delta.substring(0, 50));
    set((state) => {
      const newContent = state.assistantDraftContent + delta;
      logger.debug("[Agent] onTextDelta: new content length=", newContent.length);
      return { assistantDraftContent: newContent };
    });
  },

  onTextEnd: (fullText?: string) => {
    logger.debug("[Agent] onTextEnd: fullText length=", fullText?.length, "setting isTextStreaming=false");
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
    const { apiFetch } = await import("../services/client/urlUtils");

    await apiFetch.post("/agent/clarification/respond", {
      request_id: requestId,
      answer: answer,
    });

    // Clear pending clarification
    set({ pendingClarification: null });
  },

  respondToDecision: async (requestId: string, decision: string) => {
    // Send decision response to backend via POST
    const { apiFetch } = await import("../services/client/urlUtils");

    await apiFetch.post("/agent/decision/respond", {
      request_id: requestId,
      decision: decision,
    });

    // Clear pending decision
    set({ pendingDecision: null });
  },

  respondToDoomLoop: async (requestId: string, action: string) => {
    // Send doom loop intervention response to backend via POST
    const { apiFetch } = await import("../services/client/urlUtils");

    await apiFetch.post("/agent/doom-loop/respond", {
      request_id: requestId,
      action: action,
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
    } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
      set({
        planError: err?.response?.data?.detail || "Failed to enter Plan Mode",
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
    } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
      set({
        planError: err?.response?.data?.detail || "Failed to exit Plan Mode",
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
    } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
      set({
        planError: err?.response?.data?.detail || "Failed to get plan",
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
    } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
      set({
        planError: err?.response?.data?.detail || "Failed to update plan",
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
    } catch (error: unknown) {
    const err = error as { response?: { data?: { detail?: string } }; message?: string };
      set({
        planError:
          err?.response?.data?.detail || "Failed to get Plan Mode status",
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

  // Execution Plan actions (Plan Mode v2)

  /**
   * Update execution plan status
   * @param status - The new status
   */
  updateExecutionPlanStatus: (status: ExecutionPlanStatus) => {
    set({ executionPlanStatus: status });
  },

  /**
   * Update detection info for plan mode trigger
   * @param method - Detection method (llm, heuristic, cache)
   * @param confidence - Confidence score (0-1)
   */
  updateDetectionInfo: (method: string, confidence: number) => {
    set({
      detectionMethod: method,
      detectionConfidence: confidence,
    });
  },

  /**
   * Store execution plan
   * @param plan - The execution plan to store
   */
  updateExecutionPlan: (plan: ExecutionPlan) => {
    set({ executionPlan: plan });
  },

  /**
   * Store reflection result
   * @param result - The reflection result to store
   */
  updateReflectionResult: (result: ReflectionResult) => {
    set({ reflectionResult: result });
  },

  /**
   * Update status of a specific step in the execution plan
   * @param stepId - The step ID to update
   * @param status - The new status
   * @param result - Optional result of the step
   * @param error - Optional error message
   */
  updatePlanStepStatus: (
    stepId: string,
    status: ExecutionStepStatus,
    result?: string,
    error?: string
  ) => {
    const { executionPlan } = get();
    if (!executionPlan) {
      return;
    }

    const updatedSteps = executionPlan.steps.map((step) => {
      if (step.step_id !== stepId) {
        return step;
      }

      const updatedStep: ExecutionStep = {
        ...step,
        status,
      };

      // Set timestamps based on status
      if (status === "running" && !step.started_at) {
        updatedStep.started_at = new Date().toISOString();
      } else if (
        status === "completed" ||
        status === "failed" ||
        status === "skipped" ||
        status === "cancelled"
      ) {
        updatedStep.completed_at = new Date().toISOString();
      }

      // Set result or error
      if (result !== undefined) {
        updatedStep.result = result;
      }
      if (error !== undefined) {
        updatedStep.error = error;
      }

      return updatedStep;
    });

    set({
      executionPlan: {
        ...executionPlan,
        steps: updatedSteps,
      },
    });
  },

  /**
   * Clear all execution plan state
   */
  clearExecutionPlanState: () => {
    set({
      executionPlan: null,
      reflectionResult: null,
      executionPlanStatus: "idle",
      detectionMethod: null,
      detectionConfidence: null,
    });
  },

  clearErrors: () => {
    set({
      conversationsError: null,
      timelineError: null,
      planError: null,
    });
  },

  // Per-conversation state methods (for concurrent conversation switching)
  getConversationState: (conversationId: string) => {
    const { conversationStates } = get();
    return conversationStates.get(conversationId);
  },

  saveConversationState: (conversationId: string) => {
    const state = get();
    const { conversationStates } = state;

    // Create a snapshot of the current conversation's state
    const convState: ConversationState = {
      id: conversationId,
      streaming: {
        isStreaming: state.isStreaming,
        streamStatus: state.streamStatus as 'idle' | 'connecting' | 'streaming' | 'error',
      },
      execution: {
        currentThought: state.currentThought,
        currentThoughtLevel: state.currentThoughtLevel,
        currentToolCall: state.currentToolCall,
        currentObservation: state.currentObservation,
        currentToolExecution: state.currentToolExecution,
        toolExecutionHistory: state.toolExecutionHistory,
        executionTimeline: state.executionTimeline as Array<{
          stepNumber: number;
          description: string;
          status: 'pending' | 'running' | 'completed' | 'failed';
          thoughts: string[];
          toolExecutions: ToolExecution[];
          startTime?: string;
          endTime?: string;
          duration?: number;
        }>,
        currentSkillExecution: state.currentSkillExecution,
      },
      workPlan: state.currentWorkPlan,
      currentStepNumber: state.currentStepNumber,
      currentStepStatus: state.currentStepStatus,
      timeline: state.timeline,
      earliestLoadedSequence: state.earliestLoadedSequence,
      latestLoadedSequence: state.latestLoadedSequence,
      hasEarlierMessages: state.hasEarlierMessages,
      assistantDraftContent: state.assistantDraftContent,
      isTextStreaming: state.isTextStreaming,
      lastAccessedAt: Date.now(),
    };

    const newStates = new Map(conversationStates);
    newStates.set(conversationId, convState);
    set({ conversationStates: newStates });
  },

  restoreConversationState: (conversationId: string) => {
    const { conversationStates } = get();
    const savedState = conversationStates.get(conversationId);

    if (savedState) {
      // Restore the saved conversation's state
      set({
        // Streaming state
        isStreaming: savedState.streaming.isStreaming,
        streamStatus: savedState.streaming.streamStatus,
        // Execution state
        currentThought: savedState.execution.currentThought,
        currentThoughtLevel: savedState.execution.currentThoughtLevel,
        currentToolCall: savedState.execution.currentToolCall,
        currentObservation: savedState.execution.currentObservation,
        currentToolExecution: savedState.execution.currentToolExecution,
        toolExecutionHistory: savedState.execution.toolExecutionHistory,
        executionTimeline: savedState.execution.executionTimeline,
        currentSkillExecution: savedState.execution.currentSkillExecution,
        // Work plan state
        currentWorkPlan: savedState.workPlan,
        currentStepNumber: savedState.currentStepNumber,
        currentStepStatus: savedState.currentStepStatus,
        // Timeline state
        timeline: savedState.timeline,
        earliestLoadedSequence: savedState.earliestLoadedSequence,
        latestLoadedSequence: savedState.latestLoadedSequence,
        hasEarlierMessages: savedState.hasEarlierMessages,
        // Typewriter state
        assistantDraftContent: savedState.assistantDraftContent,
        isTextStreaming: savedState.isTextStreaming,
      });

      // Update last accessed time
      const newStates = new Map(conversationStates);
      const updated = { ...savedState, lastAccessedAt: Date.now() };
      newStates.set(conversationId, updated);
      set({ conversationStates: newStates });
    }
  },

  deleteConversationState: (conversationId: string) => {
    const { conversationStates } = get();
    const newStates = new Map(conversationStates);
    newStates.delete(conversationId);
    set({ conversationStates: newStates });
  },

  isConversationStreaming: (conversationId: string) => {
    const { conversationStates, isStreaming, currentConversation } = get();
    // If this is the current conversation, use the live state
    if (currentConversation?.id === conversationId) {
      return isStreaming;
    }
    // Otherwise check the saved state
    return conversationStates.get(conversationId)?.streaming.isStreaming ?? false;
  },

  getStreamingStatuses: () => {
    const { conversationStates, isStreaming, currentConversation } = get();
    const statuses = new Map<string, boolean>();

    // Add all saved conversation states
    for (const [id, state] of conversationStates.entries()) {
      statuses.set(id, state.streaming.isStreaming);
    }

    // Override current conversation with live state
    if (currentConversation) {
      statuses.set(currentConversation.id, isStreaming);
    }

    return statuses;
  },

  reset: () => {
    set(initialState);
  },
}),
{
  name: "AgentStore",
  enabled: import.meta.env.DEV,
}
)
);

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

/**
 * Get all conversations
 *
 * @returns Array of conversations
 * @example
 * const conversations = useConversations();
 */
export const useConversations = () =>
  useAgentStore((state) => state.conversations);

/**
 * Get current active conversation
 *
 * @returns Current conversation or null
 * @example
 * const conversation = useCurrentConversation();
 */
export const useCurrentConversation = () =>
  useAgentStore((state) => state.currentConversation);

/**
 * Get conversations loading state
 *
 * @returns True if conversations are loading
 * @example
 * const isLoading = useConversationsLoading();
 */
export const useConversationsLoading = () =>
  useAgentStore((state) => state.conversationsLoading);

/**
 * Get conversations error message
 *
 * @returns Error message or null
 * @example
 * const error = useConversationsError();
 */
export const useConversationsError = () =>
  useAgentStore((state) => state.conversationsError);

// Timeline selectors (unified event stream)

/**
 * Get timeline events (unified event stream)
 *
 * @returns Array of timeline events
 * @example
 * const timeline = useTimeline();
 */
export const useTimeline = () => useAgentStore((state) => state.timeline);

/**
 * Get timeline loading state
 *
 * @returns True if timeline is loading
 * @example
 * const isLoading = useTimelineLoading();
 */
export const useTimelineLoading = () =>
  useAgentStore((state) => state.timelineLoading);

/**
 * Get timeline error message
 *
 * @returns Error message or null
 * @example
 * const error = useTimelineError();
 */
export const useTimelineError = () =>
  useAgentStore((state) => state.timelineError);

// Unified TimelineEvent selector for consistent rendering
// Returns the raw timeline events for direct consumption by TimelineEventRenderer
export const useTimelineEvents = () =>
  useAgentStore((state) => state.timeline);

// Derived selectors for backward compatibility
// @deprecated Use useTimelineEvents and TimelineEventRenderer instead
// This selector converts TimelineEvents to Message format for legacy code
// It will be removed in a future version once all consumers are migrated
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

/**
 * Get timeline loading state
 * @returns True if timeline is currently loading
 */
export const useMessagesLoading = () =>
  useAgentStore((state) => state.timelineLoading);

/**
 * Get timeline error state
 * @returns Timeline error message or null
 */
export const useMessagesError = () =>
  useAgentStore((state) => state.timelineError);

// Streaming state selectors

/**
 * Check if agent is currently streaming
 *
 * @returns True if streaming is active
 * @example
 * const isStreaming = useIsStreaming();
 */
export const useIsStreaming = () => useAgentStore((state) => state.isStreaming);

/**
 * Get current agent thought
 *
 * @returns Current thought content or null
 * @example
 * const thought = useCurrentThought();
 */
export const useCurrentThought = () =>
  useAgentStore((state) => state.currentThought);

/**
 * Get current thought level (L1/L2/L3/L4)
 *
 * @returns Thought level or null
 * @example
 * const level = useCurrentThoughtLevel();
 */
export const useCurrentThoughtLevel = () =>
  useAgentStore((state) => state.currentThoughtLevel);

/**
 * Get current tool call
 *
 * @returns Current tool call info or null
 * @example
 * const toolCall = useCurrentToolCall();
 */
export const useCurrentToolCall = () =>
  useAgentStore((state) => state.currentToolCall);

/**
 * Get current tool observation
 *
 * @returns Current observation or null
 * @example
 * const observation = useCurrentObservation();
 */
export const useCurrentObservation = () =>
  useAgentStore((state) => state.currentObservation);

// Typewriter effect selectors
export const useAssistantDraftContent = () =>
  useAgentStore((state) => state.assistantDraftContent);
export const useIsTextStreaming = () =>
  useAgentStore((state) => state.isTextStreaming);

// Multi-level thinking selectors

/**
 * Get current work plan
 *
 * @returns Current work plan or null
 * @example
 * const workPlan = useCurrentWorkPlan();
 */
export const useCurrentWorkPlan = () =>
  useAgentStore((state) => state.currentWorkPlan);

/**
 * Get current step number
 *
 * @returns Current step number or null
 * @example
 * const stepNumber = useCurrentStepNumber();
 */
export const useCurrentStepNumber = () =>
  useAgentStore((state) => state.currentStepNumber);

/**
 * Get current step status
 *
 * @returns Current step status or null
 * @example
 * const stepStatus = useCurrentStepStatus();
 */
export const useCurrentStepStatus = () =>
  useAgentStore((state) => state.currentStepStatus);

/**
 * Get matched pattern info
 *
 * @returns Matched pattern or null
 * @example
 * const pattern = useMatchedPattern();
 */
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

/**
 * Get current Plan Mode document
 *
 * @returns Current plan or null
 * @example
 * const plan = useCurrentPlan();
 */
export const useCurrentPlan = () => useAgentStore((state) => state.currentPlan);

/**
 * Get Plan Mode status
 *
 * @returns Plan mode status or null
 * @example
 * const status = usePlanModeStatus();
 */
export const usePlanModeStatus = () =>
  useAgentStore((state) => state.planModeStatus);

// Execution Plan selectors (Plan Mode v2)

/**
 * Get current execution plan
 *
 * @returns Current execution plan or null
 * @example
 * const executionPlan = useExecutionPlan();
 */
export const useExecutionPlan = () =>
  useAgentStore((state) => state.executionPlan);

/**
 * Get execution plan status
 *
 * @returns Execution plan status
 * @example
 * const status = useExecutionPlanStatus();
 */
export const useExecutionPlanStatus = () =>
  useAgentStore((state) => state.executionPlanStatus);

/**
 * Get reflection result
 *
 * @returns Latest reflection result or null
 * @example
 * const reflection = useReflectionResult();
 */
export const useReflectionResult = () =>
  useAgentStore((state) => state.reflectionResult);

/**
 * Get detection method
 *
 * @returns Detection method used to trigger plan mode
 * @example
 * const method = useDetectionMethod();
 */
export const useDetectionMethod = () =>
  useAgentStore((state) => state.detectionMethod);

/**
 * Get detection confidence
 *
 * @returns Confidence score of detection (0-1)
 * @example
 * const confidence = useDetectionConfidence();
 */
export const useDetectionConfidence = () =>
  useAgentStore((state) => state.detectionConfidence);

/**
 * Get Plan Mode loading state
 *
 * @returns True if plan is loading
 * @example
 * const isLoading = usePlanLoading();
 */
export const usePlanLoading = () => useAgentStore((state) => state.planLoading);

/**
 * Get Plan Mode error message
 *
 * @returns Error message or null
 * @example
 * const error = usePlanError();
 */
export const usePlanError = () => useAgentStore((state) => state.planError);

/**
 * Check if currently in Plan Mode
 *
 * @returns True if in Plan Mode
 * @example
 * const isInPlanMode = useIsInPlanMode();
 */
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

// Per-conversation state selectors (for concurrent conversation switching)
export const useConversationStates = () =>
  useAgentStore((state) => state.conversationStates);
export const useIsConversationStreaming = (conversationId: string) =>
  useAgentStore((state) => state.isConversationStreaming(conversationId));
export const useStreamingStatuses = () =>
  useAgentStore((state) => state.getStreamingStatuses());
export const useConversationState = (conversationId: string) =>
  useAgentStore((state) => state.getConversationState(conversationId));

// Action selectors (for components that need to call actions)

/**
 * Get all agent actions
 *
 * @returns Object containing all agent actions
 * @example
 * const { sendMessage, createConversation, stopChat } = useAgentActions();
 */
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
    // Execution Plan actions (Plan Mode v2)
    updateExecutionPlanStatus: state.updateExecutionPlanStatus,
    updateDetectionInfo: state.updateDetectionInfo,
    updateExecutionPlan: state.updateExecutionPlan,
    updateReflectionResult: state.updateReflectionResult,
    updatePlanStepStatus: state.updatePlanStepStatus,
    clearExecutionPlanState: state.clearExecutionPlanState,
    clearErrors: state.clearErrors,
    reset: state.reset,
  }));
