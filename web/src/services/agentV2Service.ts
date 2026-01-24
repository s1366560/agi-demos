/**
 * Agent V2 Service
 *
 * API service for Agent Chat with SSE streaming support.
 * Handles all 31 SSE event types and provides conversation management.
 */

import axios, { type AxiosInstance } from 'axios';
import type {
  // Request types
  ChatRequest,
  CreateConversationRequest,
  UpdateConversationTitleRequest,
  // Response types
  Conversation,
  ConversationMessagesResponse,
  ExecutionHistoryResponse,
  ExecutionStatsResponse,
  ToolExecutionsResponse,
  ToolsListResponse,
  PlanDocument,
  PlanModeStatus,
  EnterPlanModeRequest,
  ExitPlanModeRequest,
  UpdatePlanRequest,
  // Event types
  SSEEventType,
  // Event data types
  StartEventData,
  CompleteEventData,
  ErrorEventData,
  StatusEventData,
  TextDeltaEventData,
  TextEndEventData,
  ThoughtEventData,
  ThoughtDeltaEventData,
  WorkPlanEventData,
  StepStartEventData,
  StepEndEventData,
  StepFinishEventData,
  ActEventData,
  ObserveEventData,
  ClarificationAskedEventData,
  ClarificationAnsweredEventData,
  DecisionAskedEventData,
  DecisionAnsweredEventData,
  PermissionAskedEventData,
  PermissionRepliedEventData,
  DoomLoopDetectedEventData,
  DoomLoopIntervenedEventData,
  CostUpdateEventData,
  SkillMatchedEventData,
  SkillExecutionStartEventData,
  SkillToolStartEventData,
  SkillToolResultEventData,
  SkillExecutionCompleteEventData,
  SkillFallbackEventData,
  PlanModeEnterEventData,
  PlanModeExitEventData,
  PlanCreatedEventData,
  PlanUpdatedEventData,
  PlanStatusChangedEventData,
  PatternMatchEventData,
  RetryEventData,
  MessageEventData,
} from '../types/agentV2';

// ============================================================================
// SSE Stream Handler Interface
// ============================================================================

/**
 * Handler interface for SSE events
 * All handlers are optional - only implement what you need
 */
export interface SSEStreamHandler {
  // Connection events
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (data: ErrorEventData) => void;

  // Status events
  onStart?: (data: StartEventData) => void;
  onComplete?: (data: CompleteEventData) => void;
  onStatus?: (data: StatusEventData) => void;

  // Text streaming
  onTextStart?: () => void;
  onTextDelta?: (data: TextDeltaEventData) => void;
  onTextEnd?: (data: TextEndEventData) => void;

  // Thinking (multi-level)
  onThought?: (data: ThoughtEventData) => void;
  onThoughtDelta?: (data: ThoughtDeltaEventData) => void;

  // Work plan
  onWorkPlan?: (data: WorkPlanEventData) => void;
  onStepStart?: (data: StepStartEventData) => void;
  onStepEnd?: (data: StepEndEventData) => void;
  onStepFinish?: (data: StepFinishEventData) => void;

  // Tool execution
  onAct?: (data: ActEventData) => void;
  onObserve?: (data: ObserveEventData) => void;

  // Message
  onMessage?: (data: MessageEventData) => void;

  // Human interactions - clarification
  onClarificationAsked?: (data: ClarificationAskedEventData) => void;
  onClarificationAnswered?: (data: ClarificationAnsweredEventData) => void;

  // Human interactions - decision
  onDecisionAsked?: (data: DecisionAskedEventData) => void;
  onDecisionAnswered?: (data: DecisionAnsweredEventData) => void;

  // Human interactions - permission
  onPermissionAsked?: (data: PermissionAskedEventData) => void;
  onPermissionReplied?: (data: PermissionRepliedEventData) => void;

  // Human interactions - doom loop
  onDoomLoopDetected?: (data: DoomLoopDetectedEventData) => void;
  onDoomLoopIntervened?: (data: DoomLoopIntervenedEventData) => void;

  // Cost tracking
  onCostUpdate?: (data: CostUpdateEventData) => void;

  // Skill system
  onSkillMatched?: (data: SkillMatchedEventData) => void;
  onSkillExecutionStart?: (data: SkillExecutionStartEventData) => void;
  onSkillToolStart?: (data: SkillToolStartEventData) => void;
  onSkillToolResult?: (data: SkillToolResultEventData) => void;
  onSkillExecutionComplete?: (data: SkillExecutionCompleteEventData) => void;
  onSkillFallback?: (data: SkillFallbackEventData) => void;

  // Plan mode
  onPlanModeEnter?: (data: PlanModeEnterEventData) => void;
  onPlanModeExit?: (data: PlanModeExitEventData) => void;
  onPlanCreated?: (data: PlanCreatedEventData) => void;
  onPlanUpdated?: (data: PlanUpdatedEventData) => void;
  onPlanStatusChanged?: (data: PlanStatusChangedEventData) => void;

  // Other
  onPatternMatch?: (data: PatternMatchEventData) => void;
  onRetry?: (data: RetryEventData) => void;
}

// ============================================================================
// SSE Stream State
// ============================================================================

interface SSEStreamState {
  reader: ReadableStreamDefaultReader<Uint8Array> | null;
  controller: AbortController | null;
  isDisconnected: boolean;
}

// ============================================================================
// Agent V2 Service Implementation
// ============================================================================

class AgentV2ServiceImpl {
  private api: AxiosInstance;
  private streamStates: Map<string, SSEStreamState> = new Map();
  private baseURL: string;

  constructor() {
    this.baseURL = import.meta.env.VITE_API_URL || '/api/v1';

    this.api = axios.create({
      baseURL: this.baseURL,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Request interceptor - add auth token
    this.api.interceptors.request.use((config) => {
      const token = localStorage.getItem('token');
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
      return config;
    });

    // Response interceptor - handle auth errors
    this.api.interceptors.response.use(
      (response) => response,
      (error) => {
        if (error.response?.status === 401) {
          localStorage.removeItem('token');
          localStorage.removeItem('user');
          if (window.location.pathname !== '/login') {
            window.location.href = '/login';
          }
        }
        return Promise.reject(error);
      }
    );
  }

  // ==========================================================================
  // Conversation Management
  // ==========================================================================

  /**
   * Create a new conversation
   */
  async createConversation(request: CreateConversationRequest): Promise<Conversation> {
    const response = await this.api.post<Conversation>('/agent/conversations', request);
    return response.data;
  }

  /**
   * List conversations for a project
   */
  async listConversations(
    projectId: string,
    params?: {
      status?: 'active' | 'archived' | 'deleted';
      limit?: number;
      offset?: number;
    }
  ): Promise<Conversation[]> {
    const response = await this.api.get<Conversation[]>('/agent/conversations', {
      params: { project_id: projectId, ...params },
    });
    return response.data;
  }

  /**
   * Get a conversation by ID
   */
  async getConversation(
    id: string,
    projectId: string
  ): Promise<Conversation | null> {
    try {
      const response = await this.api.get<Conversation>(
        `/agent/conversations/${id}`,
        { params: { project_id: projectId } }
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 404) {
        return null;
      }
      throw error;
    }
  }

  /**
   * Delete a conversation
   */
  async deleteConversation(id: string, projectId: string): Promise<void> {
    await this.api.delete(`/agent/conversations/${id}`, {
      params: { project_id: projectId },
    });
  }

  /**
   * Update conversation title
   */
  async updateConversationTitle(
    id: string,
    projectId: string,
    request: UpdateConversationTitleRequest
  ): Promise<Conversation> {
    const response = await this.api.patch<Conversation>(
      `/agent/conversations/${id}/title`,
      request,
      { params: { project_id: projectId } }
    );
    return response.data;
  }

  /**
   * Generate conversation title using AI
   */
  async generateConversationTitle(
    id: string,
    projectId: string
  ): Promise<Conversation> {
    const response = await this.api.post<Conversation>(
      `/agent/conversations/${id}/generate-title`,
      {},
      { params: { project_id: projectId } }
    );
    return response.data;
  }

  // ==========================================================================
  // Messages
  // ==========================================================================

  /**
   * Get messages for a conversation
   */
  async getMessages(
    conversationId: string,
    projectId: string,
    params?: {
      limit?: number;
      before?: string;
      after?: string;
    }
  ): Promise<ConversationMessagesResponse> {
    const response = await this.api.get<ConversationMessagesResponse>(
      `/agent/conversations/${conversationId}/messages`,
      { params: { project_id: projectId, ...params } }
    );
    return response.data;
  }

  // ==========================================================================
  // SSE Chat (Core Feature)
  // ==========================================================================

  /**
   * Send a chat message and stream the response via SSE
   *
   * @param request - Chat request with conversation_id and message
   * @param handler - Event handlers for SSE events
   * @returns Promise that resolves when the stream completes
   */
  async chat(request: ChatRequest, handler: SSEStreamHandler): Promise<void> {
    const { conversation_id } = request;
    const MAX_RETRIES = 3;
    const BASE_DELAY = 1000;

    // Clean up any existing stream for this conversation
    this.stopChat(conversation_id);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => {
      controller.abort();
      handler.onError?.({
        message: 'Request timeout after 2 minutes. Please try again.',
        code: 'TIMEOUT',
        isReconnectable: false,
      });
    }, 120000);

    let lastError: Error | null = null;

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      try {
        const success = await this.chatWithStream(
          request,
          handler,
          controller,
          attempt
        );

        clearTimeout(timeoutId);

        if (success) {
          this.streamStates.delete(conversation_id);
          return;
        }

        // Stream returned false - user cancelled
        this.streamStates.delete(conversation_id);
        return;
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));

        if (lastError.name === 'AbortError') {
          clearTimeout(timeoutId);
          this.streamStates.delete(conversation_id);
          handler.onClose?.();
          return;
        }

        if (attempt === MAX_RETRIES) {
          break;
        }

        const delay = BASE_DELAY * Math.pow(2, attempt);
        console.log(
          `[AgentV2Service] SSE connection failed (attempt ${attempt + 1}/${MAX_RETRIES + 1}), retrying in ${delay}ms...`
        );

        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    }

    // All retries exhausted
    clearTimeout(timeoutId);
    this.streamStates.delete(conversation_id);

    console.error('[AgentV2Service] SSE connection failed after all retries:', lastError);
    handler.onError?.({
      message: lastError?.message || 'Connection failed after multiple retries. Please try again.',
      code: 'CONNECTION_FAILED',
      isReconnectable: false,
    });
    throw lastError;
  }

  /**
   * Internal method to establish SSE stream and process events
   */
  private async chatWithStream(
    request: ChatRequest,
    handler: SSEStreamHandler,
    controller: AbortController,
    _retryCount: number
  ): Promise<boolean> {
    const { conversation_id } = request;
    const token = localStorage.getItem('token');
    const url = `${this.baseURL}/agent/chat`;

    // Initialize stream state
    this.streamStates.set(conversation_id, {
      reader: null,
      controller,
      isDisconnected: false,
    });

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(request),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body?.getReader();
    const decoder = new TextDecoder();

    if (!reader) {
      throw new Error('Response body is null');
    }

    // Update stream state with reader
    const state = this.streamStates.get(conversation_id);
    if (state) {
      state.reader = reader;
    }

    handler.onOpen?.();

    try {
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();

        if (done) {
          handler.onClose?.();
          return true;
        }

        // Check if we were told to disconnect
        const currentState = this.streamStates.get(conversation_id);
        if (currentState?.isDisconnected) {
          return false;
        }

        // Decode and buffer the chunk
        buffer += decoder.decode(value, { stream: true });

        // Process complete events (ending with \n\n or \r\n\r\n)
        const normalizedBuffer = buffer.replace(/\r\n/g, '\n');
        const events = normalizedBuffer.split('\n\n');
        buffer = events.pop()?.replace(/\n/g, '\r\n') || '';

        for (const eventStr of events) {
          if (!eventStr.trim()) continue;

          const lines = eventStr.split('\n');
          let currentEvent: string | null = null;
          let currentData: string | null = null;

          for (const line of lines) {
            if (line.startsWith('event: ')) {
              currentEvent = line.substring(7).trim();
            } else if (line.startsWith('data: ')) {
              currentData = line.substring(6).trim();
            }
          }

          if (currentEvent && currentData) {
            this.dispatchSSEEvent(currentEvent as SSEEventType, currentData, handler);
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  /**
   * Dispatch SSE event to appropriate handler
   */
  private dispatchSSEEvent(
    eventType: SSEEventType,
    eventData: string,
    handler: SSEStreamHandler
  ): void {
    try {
      const data = JSON.parse(eventData);

      // Debug logging
      console.log(`[AgentV2Service] SSE event: ${eventType}`, data);

      switch (eventType) {
        // Connection events
        case 'start':
          handler.onStart?.(data as StartEventData);
          break;
        case 'complete':
          handler.onComplete?.(data as CompleteEventData);
          break;
        case 'error':
          handler.onError?.(data as ErrorEventData);
          break;
        case 'status':
          handler.onStatus?.(data as StatusEventData);
          break;

        // Text streaming
        case 'text_start':
          handler.onTextStart?.();
          break;
        case 'text_delta':
          handler.onTextDelta?.(data as TextDeltaEventData);
          break;
        case 'text_end':
          handler.onTextEnd?.(data as TextEndEventData);
          break;

        // Thinking
        case 'thought':
          handler.onThought?.(data as ThoughtEventData);
          break;
        case 'thought_delta':
          handler.onThoughtDelta?.(data as ThoughtDeltaEventData);
          break;

        // Work plan
        case 'work_plan':
          handler.onWorkPlan?.(data as WorkPlanEventData);
          break;
        case 'step_start':
          handler.onStepStart?.(data as StepStartEventData);
          break;
        case 'step_end':
          handler.onStepEnd?.(data as StepEndEventData);
          break;
        case 'step_finish':
          handler.onStepFinish?.(data as StepFinishEventData);
          break;

        // Tool execution
        case 'act':
          handler.onAct?.(data as ActEventData);
          break;
        case 'observe':
          handler.onObserve?.(data as ObserveEventData);
          break;

        // Message
        case 'message':
          handler.onMessage?.(data as MessageEventData);
          break;

        // Human interactions - clarification
        case 'clarification_asked':
          handler.onClarificationAsked?.(data as ClarificationAskedEventData);
          break;
        case 'clarification_answered':
          handler.onClarificationAnswered?.(data as ClarificationAnsweredEventData);
          break;

        // Human interactions - decision
        case 'decision_asked':
          handler.onDecisionAsked?.(data as DecisionAskedEventData);
          break;
        case 'decision_answered':
          handler.onDecisionAnswered?.(data as DecisionAnsweredEventData);
          break;

        // Human interactions - permission
        case 'permission_asked':
          handler.onPermissionAsked?.(data as PermissionAskedEventData);
          break;
        case 'permission_replied':
          handler.onPermissionReplied?.(data as PermissionRepliedEventData);
          break;

        // Human interactions - doom loop
        case 'doom_loop_detected':
          handler.onDoomLoopDetected?.(data as DoomLoopDetectedEventData);
          break;
        case 'doom_loop_intervened':
          handler.onDoomLoopIntervened?.(data as DoomLoopIntervenedEventData);
          break;

        // Cost tracking
        case 'cost_update':
          handler.onCostUpdate?.(data as CostUpdateEventData);
          break;

        // Skill system
        case 'skill_matched':
          handler.onSkillMatched?.(data as SkillMatchedEventData);
          break;
        case 'skill_execution_start':
          handler.onSkillExecutionStart?.(data as SkillExecutionStartEventData);
          break;
        case 'skill_tool_start':
          handler.onSkillToolStart?.(data as SkillToolStartEventData);
          break;
        case 'skill_tool_result':
          handler.onSkillToolResult?.(data as SkillToolResultEventData);
          break;
        case 'skill_execution_complete':
          handler.onSkillExecutionComplete?.(data as SkillExecutionCompleteEventData);
          break;
        case 'skill_fallback':
          handler.onSkillFallback?.(data as SkillFallbackEventData);
          break;

        // Plan mode
        case 'plan_mode_enter':
          handler.onPlanModeEnter?.(data as PlanModeEnterEventData);
          break;
        case 'plan_mode_exit':
          handler.onPlanModeExit?.(data as PlanModeExitEventData);
          break;
        case 'plan_created':
          handler.onPlanCreated?.(data as PlanCreatedEventData);
          break;
        case 'plan_updated':
          handler.onPlanUpdated?.(data as PlanUpdatedEventData);
          break;
        case 'plan_status_changed':
          handler.onPlanStatusChanged?.(data as PlanStatusChangedEventData);
          break;

        // Other
        case 'pattern_match':
          handler.onPatternMatch?.(data as PatternMatchEventData);
          break;
        case 'retry':
          handler.onRetry?.(data as RetryEventData);
          break;

        default:
          console.warn(`[AgentV2Service] Unknown event type: ${eventType}`);
      }
    } catch (parseError) {
      console.error('[AgentV2Service] Failed to parse SSE data:', parseError);
    }
  }

  /**
   * Stop the SSE stream for a conversation
   */
  stopChat(conversationId: string): void {
    const state = this.streamStates.get(conversationId);
    if (state) {
      state.isDisconnected = true;
      if (state.controller) {
        state.controller.abort();
      }
      if (state.reader) {
        state.reader.cancel().catch(() => {
          // Ignore cancellation errors
        });
      }
      this.streamStates.delete(conversationId);
    }
  }

  // ==========================================================================
  // Human Interaction Responses
  // ==========================================================================

  /**
   * Respond to a clarification request
   */
  async respondToClarification(
    conversationId: string,
    requestId: string,
    answer: string
  ): Promise<void> {
    const token = localStorage.getItem('token');
    const url = `${this.baseURL}/agent/clarification/respond`;

    await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        conversation_id: conversationId,
        request_id: requestId,
        answer,
      }),
    });
  }

  /**
   * Respond to a decision request
   */
  async respondToDecision(
    conversationId: string,
    requestId: string,
    decision: string
  ): Promise<void> {
    const token = localStorage.getItem('token');
    const url = `${this.baseURL}/agent/decision/respond`;

    await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        conversation_id: conversationId,
        request_id: requestId,
        decision,
      }),
    });
  }

  /**
   * Respond to a permission request
   */
  async respondToPermission(
    conversationId: string,
    requestId: string,
    allow: boolean
  ): Promise<void> {
    const token = localStorage.getItem('token');
    const url = `${this.baseURL}/agent/permission/respond`;

    await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        conversation_id: conversationId,
        request_id: requestId,
        allow,
      }),
    });
  }

  /**
   * Respond to a doom loop intervention
   */
  async respondToDoomLoop(
    conversationId: string,
    requestId: string,
    action: 'continue' | 'stop'
  ): Promise<void> {
    const token = localStorage.getItem('token');
    const url = `${this.baseURL}/agent/doom-loop/respond`;

    await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        conversation_id: conversationId,
        request_id: requestId,
        action,
      }),
    });
  }

  // ==========================================================================
  // Execution History & Stats
  // ==========================================================================

  /**
   * Get execution history for a conversation
   */
  async getExecutionHistory(
    conversationId: string,
    projectId: string,
    params?: {
      limit?: number;
      status_filter?: string;
      tool_filter?: string;
    }
  ): Promise<ExecutionHistoryResponse> {
    const response = await this.api.get<ExecutionHistoryResponse>(
      `/agent/conversations/${conversationId}/execution`,
      { params: { project_id: projectId, ...params } }
    );
    return response.data;
  }

  /**
   * Get execution statistics for a conversation
   */
  async getExecutionStats(
    conversationId: string,
    projectId: string
  ): Promise<ExecutionStatsResponse> {
    const response = await this.api.get<ExecutionStatsResponse>(
      `/agent/conversations/${conversationId}/execution/stats`,
      { params: { project_id: projectId } }
    );
    return response.data;
  }

  /**
   * Get tool execution records for a conversation
   */
  async getToolExecutions(
    conversationId: string,
    projectId: string,
    params?: {
      message_id?: string;
      limit?: number;
    }
  ): Promise<ToolExecutionsResponse> {
    const requestParams: Record<string, string | number> = {
      project_id: projectId,
    };
    if (params?.message_id) requestParams.message_id = params.message_id;
    if (params?.limit) requestParams.limit = params.limit;

    const response = await this.api.get<ToolExecutionsResponse>(
      `/agent/conversations/${conversationId}/tool-executions`,
      { params: requestParams }
    );
    return response.data;
  }

  // ==========================================================================
  // Tools
  // ==========================================================================

  /**
   * List available tools
   */
  async listTools(): Promise<ToolsListResponse> {
    const response = await this.api.get<ToolsListResponse>('/agent/tools');
    return response.data;
  }

  // ==========================================================================
  // Plan Mode
  // ==========================================================================

  /**
   * Enter plan mode
   */
  async enterPlanMode(request: EnterPlanModeRequest): Promise<PlanDocument> {
    const response = await this.api.post<PlanDocument>('/agent/plan/enter', request);
    return response.data;
  }

  /**
   * Exit plan mode
   */
  async exitPlanMode(request: ExitPlanModeRequest): Promise<PlanDocument> {
    const response = await this.api.post<PlanDocument>('/agent/plan/exit', request);
    return response.data;
  }

  /**
   * Get plan mode status for a conversation
   */
  async getPlanModeStatus(conversationId: string): Promise<PlanModeStatus> {
    const response = await this.api.get<PlanModeStatus>(
      `/agent/conversations/${conversationId}/plan-mode`
    );
    return response.data;
  }

  /**
   * Get a plan by ID
   */
  async getPlan(planId: string): Promise<PlanDocument> {
    const response = await this.api.get<PlanDocument>(`/agent/plan/${planId}`);
    return response.data;
  }

  /**
   * Update a plan
   */
  async updatePlan(planId: string, request: UpdatePlanRequest): Promise<PlanDocument> {
    const response = await this.api.put<PlanDocument>(`/agent/plan/${planId}`, request);
    return response.data;
  }
}

// Export singleton instance
export const agentV2Service = new AgentV2ServiceImpl();

// Export type for convenience
export type AgentV2Service = AgentV2ServiceImpl;
