/**
 * Agent service for interacting with the React-mode Agent API.
 *
 * This service provides methods for managing conversations and
 * streaming agent responses using WebSocket (replacing SSE).
 *
 * Supports multiple browser tabs per user via unique session_id.
 */

import axios from "axios";
import { httpClient } from "./client/httpClient";
import { createWebSocketUrl } from "./client/urlUtils";
import type {
  AgentEvent,
  AgentEventType,
  AgentService,
  AgentStreamHandler,
  ChatRequest,
  Conversation,
  CreateConversationRequest,
  CreateConversationResponse,
  ConversationMessagesResponse,
  ExecutionHistoryResponse,
  ExecutionStatsResponse,
  ToolExecutionsResponse,
  ToolsListResponse,
  MessageEventData,
  ThoughtEventData,
  WorkPlanEventData,
  PatternMatchEventData,
  StepStartEventData,
  StepEndEventData,
  ActEventData,
  ObserveEventData,
  TextDeltaEventData,
  TextEndEventData,
  ClarificationAskedEventData,
  ClarificationAnsweredEventData,
  DecisionAskedEventData,
  DecisionAnsweredEventData,
  CompleteEventData,
  TitleGeneratedEventData,
  ErrorEventData,
  SkillMatchedEventData,
  SkillExecutionStartEventData,
  SkillToolStartEventData,
  SkillToolResultEventData,
  SkillExecutionCompleteEventData,
  SkillFallbackEventData,
  ContextCompressedEventData,
} from "../types/agent";

// Use centralized HTTP client for REST API calls
const api = httpClient;

/**
 * Generate a unique session ID for this browser tab.
 * Uses crypto.randomUUID if available, falls back to timestamp + random.
 */
function generateSessionId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  // Fallback for older browsers
  return `${Date.now()}-${Math.random().toString(36).substring(2, 15)}`;
}

/**
 * WebSocket connection status
 */
export type WebSocketStatus =
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";

/**
 * WebSocket message from server
 */
interface ServerMessage {
  type: string;
  conversation_id?: string;
  data?: unknown;
  seq?: number;
  timestamp?: string;
  action?: string;
}

/**
 * Agent service implementation with WebSocket support
 * 
 * Each instance has a unique session_id to support multiple browser tabs.
 */
class AgentServiceImpl implements AgentService {
  private ws: WebSocket | null = null;
  private status: WebSocketStatus = "disconnected";
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private isManualClose = false;

  // Unique session ID for this browser tab (generated once per page load)
  private sessionId: string = generateSessionId();

  // Heartbeat interval to keep WebSocket connection alive
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  private readonly HEARTBEAT_INTERVAL_MS = 30000; // 30 seconds

  // Handler maps by conversation_id
  private handlers: Map<string, AgentStreamHandler> = new Map();

  // Status change listeners
  private statusListeners: Set<(status: WebSocketStatus) => void> = new Set();

  // Pending subscriptions (to restore after reconnect)
  private subscriptions: Set<string> = new Set();

  // Performance tracking: Track event receive times for diagnostics
  private performanceMetrics: Map<string, number[]> = new Map();
  private readonly MAX_METRICS_SAMPLES = 100;

  /**
   * Get the session ID for this instance
   */
  getSessionId(): string {
    return this.sessionId;
  }

  /**
   * Connect to WebSocket server
   */
  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        console.log("[AgentWS] Already connected");
        resolve();
        return;
      }

      this.isManualClose = false;
      this.setStatus("connecting");

      const token = localStorage.getItem("token");
      if (!token) {
        this.setStatus("error");
        reject(new Error("No authentication token"));
        return;
      }

      // Include session_id in WebSocket URL for multi-tab support
      const wsUrl = createWebSocketUrl('/agent/ws', {
        token,
        session_id: this.sessionId,
      });

      try {
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
          console.log(`[AgentWS] Connected (session: ${this.sessionId.substring(0, 8)}...)`);
          this.setStatus("connected");
          this.reconnectAttempts = 0;
          this.reconnectDelay = 1000;

          // Start heartbeat to keep connection alive
          this.startHeartbeat();

          // Resubscribe to previous conversations
          this.resubscribe();
          resolve();
        };

        this.ws.onmessage = (event) => {
          try {
            const message: ServerMessage = JSON.parse(event.data);
            this.handleMessage(message);
          } catch (err) {
            console.error("[AgentWS] Failed to parse message:", err);
          }
        };

        this.ws.onclose = (event) => {
          console.log("[AgentWS] Disconnected", event.code, event.reason);
          this.setStatus("disconnected");

          if (
            !this.isManualClose &&
            this.reconnectAttempts < this.maxReconnectAttempts
          ) {
            this.scheduleReconnect();
          }
        };

        this.ws.onerror = (error) => {
          console.error("[AgentWS] Error:", error);
          this.setStatus("error");
          this.stopHeartbeat();
          reject(error);
        };
      } catch (err) {
        console.error("[AgentWS] Connection error:", err);
        this.setStatus("error");
        this.scheduleReconnect();
        reject(err);
      }
    });
  }

  /**
   * Disconnect from WebSocket server
   */
  disconnect(): void {
    this.isManualClose = true;

    // Stop heartbeat
    this.stopHeartbeat();

    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }

    this.setStatus("disconnected");
  }

  /**
   * Get current connection status
   */
  getStatus(): WebSocketStatus {
    return this.status;
  }

  /**
   * Check if connected
   */
  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  /**
   * Register a status change listener
   */
  onStatusChange(listener: (status: WebSocketStatus) => void): () => void {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => this.statusListeners.delete(listener);
  }

  /**
   * Send a message through WebSocket
   */
  private send(message: Record<string, unknown>): boolean {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
      return true;
    }
    return false;
  }

  /**
   * Handle incoming WebSocket message
   */
  private handleMessage(message: ServerMessage): void {
    const { type, conversation_id, data, seq } = message;

    // Performance tracking: Record event receive timestamp
    const receiveTime = performance.now();
    this.recordEventMetric(type, receiveTime);

    // Enhanced logging for debugging TEXT_DELTA issues
    if (type === "text_delta") {
      const delta = (data as { delta?: string } | undefined)?.delta || "";
      console.log(
        `[AgentWS] TEXT_DELTA: seq=${seq}, len=${delta.length}, preview="${delta.substring(0, 30)}..."`
      );
    } else if (type === "text_start" || type === "text_end" || type === "complete" || type === "error") {
      console.log(`[AgentWS] ${type.toUpperCase()}: seq=${seq}, conversation=${conversation_id}`);
    } else {
      console.log("[AgentWS] handleMessage:", { type, conversation_id, seq, hasData: !!data });
    }

    // Handle non-conversation-specific messages
    if (type === "connected") {
      console.log("[AgentWS] Connection confirmed:", data);
      return;
    }

    if (type === "pong") {
      // Heartbeat response
      return;
    }

    if (type === "ack") {
      console.log(`[AgentWS] Ack for ${message.action} on ${conversation_id}`);
      return;
    }

    // Route conversation-specific messages to handlers
    if (conversation_id) {
      const handler = this.handlers.get(conversation_id);
      console.log("[AgentWS] Looking for handler:", { conversation_id, hasHandler: !!handler, handlersSize: this.handlers.size });
      if (handler) {
        this.routeToHandler(type as AgentEventType, data, handler);
      } else {
        console.warn("[AgentWS] No handler found for conversation:", conversation_id);
      }
    }
  }

  /**
   * Route event to appropriate handler method
   *
   * Type assertion is safe here because the eventType determines the expected data shape.
   * The backend ensures that data matches the event type.
   */
  private routeToHandler(
    eventType: AgentEventType,
    data: unknown,
    handler: AgentStreamHandler
  ): void {
    console.log("[AgentWS] routeToHandler:", { eventType, hasData: !!data });
    const event = { type: eventType, data };

    switch (eventType) {
      case "message":
        handler.onMessage?.(event as AgentEvent<MessageEventData>);
        break;
      case "thought":
        handler.onThought?.(event as AgentEvent<ThoughtEventData>);
        break;
      case "work_plan":
        handler.onWorkPlan?.(event as AgentEvent<WorkPlanEventData>);
        break;
      case "pattern_match":
        handler.onPatternMatch?.(event as AgentEvent<PatternMatchEventData>);
        break;
      case "step_start":
        handler.onStepStart?.(event as AgentEvent<StepStartEventData>);
        break;
      case "step_end":
        handler.onStepEnd?.(event as AgentEvent<StepEndEventData>);
        break;
      case "act":
        handler.onAct?.(event as AgentEvent<ActEventData>);
        break;
      case "observe":
        handler.onObserve?.(event as AgentEvent<ObserveEventData>);
        break;
      case "text_start":
        handler.onTextStart?.();
        break;
      case "text_delta":
        handler.onTextDelta?.(event as AgentEvent<TextDeltaEventData>);
        break;
      case "text_end":
        handler.onTextEnd?.(event as AgentEvent<TextEndEventData>);
        break;
      case "clarification_asked":
        handler.onClarificationAsked?.(event as AgentEvent<ClarificationAskedEventData>);
        break;
      case "clarification_answered":
        handler.onClarificationAnswered?.(event as AgentEvent<ClarificationAnsweredEventData>);
        break;
      case "decision_asked":
        handler.onDecisionAsked?.(event as AgentEvent<DecisionAskedEventData>);
        break;
      case "decision_answered":
        handler.onDecisionAnswered?.(event as AgentEvent<DecisionAnsweredEventData>);
        break;
      case "complete":
        handler.onComplete?.(event as AgentEvent<CompleteEventData>);
        // Clean up handler after completion
        // Note: Don't remove immediately, some events might still come
        break;
      case "title_generated":
        handler.onTitleGenerated?.(event as AgentEvent<TitleGeneratedEventData>);
        break;
      case "error":
        handler.onError?.(event as AgentEvent<ErrorEventData>);
        break;
      // Skill execution events (L2 layer)
      case "skill_matched":
        handler.onSkillMatched?.(event as AgentEvent<SkillMatchedEventData>);
        break;
      case "skill_execution_start":
        handler.onSkillExecutionStart?.(event as AgentEvent<SkillExecutionStartEventData>);
        break;
      case "skill_tool_start":
        handler.onSkillToolStart?.(event as AgentEvent<SkillToolStartEventData>);
        break;
      case "skill_tool_result":
        handler.onSkillToolResult?.(event as AgentEvent<SkillToolResultEventData>);
        break;
      case "skill_execution_complete":
        handler.onSkillExecutionComplete?.(event as AgentEvent<SkillExecutionCompleteEventData>);
        break;
      case "skill_fallback":
        handler.onSkillFallback?.(event as AgentEvent<SkillFallbackEventData>);
        break;
      // Context management events
      case "context_compressed":
        handler.onContextCompressed?.(event as AgentEvent<ContextCompressedEventData>);
        break;
    }
  }

  private setStatus(status: WebSocketStatus): void {
    this.status = status;
    this.statusListeners.forEach((listener) => {
      try {
        listener(status);
      } catch (err) {
        console.error("[AgentWS] Status listener error:", err);
      }
    });
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimeout) {
      return;
    }

    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

    console.log(
      `[AgentWS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`
    );

    this.reconnectTimeout = setTimeout(() => {
      this.reconnectTimeout = null;
      this.connect().catch((err) => {
        console.error("[AgentWS] Reconnect failed:", err);
      });
    }, delay);
  }

  private resubscribe(): void {
    this.subscriptions.forEach((conversationId) => {
      this.send({
        type: "subscribe",
        conversation_id: conversationId,
      });
    });
  }

  private startHeartbeat(): void {
    // Clear any existing heartbeat
    this.stopHeartbeat();

    // Send heartbeat every 30 seconds to keep connection alive
    this.heartbeatInterval = setInterval(() => {
      if (this.isConnected()) {
        this.send({ type: "heartbeat" });
      }
    }, this.HEARTBEAT_INTERVAL_MS);

    console.log("[AgentWS] Heartbeat started");
  }

  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }

  /**
   * Create a new conversation
   */
  async createConversation(
    request: CreateConversationRequest
  ): Promise<CreateConversationResponse> {
    const response = await api.post<CreateConversationResponse>(
      "/agent/conversations",
      request
    );
    return response;
  }

  /**
   * List conversations for a project
   */
  async listConversations(
    projectId: string,
    status?: "active" | "archived" | "deleted",
    limit = 50
  ): Promise<Conversation[]> {
    const params: Record<string, string | number> = {
      project_id: projectId,
      limit,
    };
    if (status) {
      params.status = status;
    }
    const response = await api.get<Conversation[]>(
      "/agent/conversations",
      { params }
    );
    return response;
  }

  /**
   * Get a conversation by ID
   */
  async getConversation(
    conversationId: string,
    projectId: string
  ): Promise<Conversation | null> {
    try {
      const response = await api.get<Conversation>(
        `/agent/conversations/${conversationId}`,
        {
          params: { project_id: projectId },
        }
      );
      return response;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 404) {
        return null;
      }
      throw error;
    }
  }

  /**
   * Stop the chat/agent execution for a conversation
   *
   * This is a key advantage of WebSocket - we can send stop signal immediately
   */
  stopChat(conversationId: string): void {
    // Send stop signal through WebSocket
    const sent = this.send({
      type: "stop_session",
      conversation_id: conversationId,
    });

    if (sent) {
      console.log(
        `[AgentWS] Stop signal sent for conversation ${conversationId}`
      );
    }

    // Clean up handler
    this.handlers.delete(conversationId);
    this.subscriptions.delete(conversationId);
  }

  /**
   * Chat with the agent using WebSocket
   *
   * Replaces SSE-based chat with bidirectional WebSocket communication.
   */
  async chat(request: ChatRequest, handler: AgentStreamHandler): Promise<void> {
    const { conversation_id, message, project_id } = request;

    // Ensure WebSocket is connected
    if (!this.isConnected()) {
      await this.connect();
    }

    // Register handler for this conversation
    this.handlers.set(conversation_id, handler);
    this.subscriptions.add(conversation_id);

    // Send message through WebSocket
    const sent = this.send({
      type: "send_message",
      conversation_id,
      message,
      project_id,
    });

    if (!sent) {
      handler.onError?.({
        type: "error",
        data: {
          message: "Failed to send message - WebSocket not connected",
          isReconnectable: true,
        },
      });
      throw new Error("WebSocket not connected");
    }
  }

  /**
   * Subscribe to a conversation's events
   */
  subscribe(conversationId: string, handler: AgentStreamHandler): void {
    this.handlers.set(conversationId, handler);
    this.subscriptions.add(conversationId);

    if (this.isConnected()) {
      this.send({
        type: "subscribe",
        conversation_id: conversationId,
      });
    }
  }

  /**
   * Unsubscribe from a conversation's events
   */
  unsubscribe(conversationId: string): void {
    this.handlers.delete(conversationId);
    this.subscriptions.delete(conversationId);

    if (this.isConnected()) {
      this.send({
        type: "unsubscribe",
        conversation_id: conversationId,
      });
    }
  }

  /**
   * Send heartbeat to keep connection alive
   */
  sendHeartbeat(): void {
    this.send({ type: "heartbeat" });
  }

  /**
   * Delete a conversation
   */
  async deleteConversation(
    conversationId: string,
    projectId: string
  ): Promise<void> {
    await api.delete(`/agent/conversations/${conversationId}`, {
      params: { project_id: projectId },
    });
  }

  /**
   * Generate and update conversation title based on first message
   */
  async generateConversationTitle(
    conversationId: string,
    projectId: string
  ): Promise<Conversation> {
    const response = await api.post<Conversation>(
      `/agent/conversations/${conversationId}/generate-title`,
      {},
      {
        params: { project_id: projectId },
      }
    );
    return response;
  }

  /**
   * Get messages in a conversation
   */
  async getConversationMessages(
    conversationId: string,
    projectId: string,
    limit = 100,
    fromSequence?: number,
    beforeSequence?: number
  ): Promise<ConversationMessagesResponse & {
    has_more: boolean;
    first_sequence: number | null;
    last_sequence: number | null;
  }> {
    const params: Record<string, string | number> = {
      project_id: projectId,
      limit,
    };
    if (fromSequence !== undefined) {
      params.from_sequence = fromSequence;
    }
    if (beforeSequence !== undefined) {
      params.before_sequence = beforeSequence;
    }

    const response = await api.get<{
      has_more?: boolean;
      first_sequence?: number | null;
      last_sequence?: number | null;
    } & ConversationMessagesResponse>(
      `/agent/conversations/${conversationId}/messages`,
      { params }
    );
    // Normalize optional fields to required fields with defaults
    return {
      ...response,
      has_more: response.has_more ?? false,
      first_sequence: response.first_sequence ?? null,
      last_sequence: response.last_sequence ?? null,
    };
  }

  /**
   * List available tools
   */
  async listTools(): Promise<ToolsListResponse> {
    const response = await api.get<ToolsListResponse>("/agent/tools");
    return response;
  }

  /**
   * Get execution history for a conversation
   */
  async getExecutionHistory(
    conversationId: string,
    projectId: string,
    limit = 50,
    statusFilter?: string,
    toolFilter?: string
  ): Promise<ExecutionHistoryResponse> {
    const response = await api.get<ExecutionHistoryResponse>(
      `/agent/conversations/${conversationId}/execution`,
      {
        params: {
          project_id: projectId,
          limit,
          status_filter: statusFilter,
          tool_filter: toolFilter,
        },
      }
    );
    return response;
  }

  /**
   * Get execution statistics for a conversation
   */
  async getExecutionStats(
    conversationId: string,
    projectId: string
  ): Promise<ExecutionStatsResponse> {
    const response = await api.get<ExecutionStatsResponse>(
      `/agent/conversations/${conversationId}/execution/stats`,
      {
        params: { project_id: projectId },
      }
    );
    return response;
  }

  /**
   * Get tool execution records for a conversation
   */
  async getToolExecutions(
    conversationId: string,
    projectId: string,
    messageId?: string,
    limit = 100
  ): Promise<ToolExecutionsResponse> {
    const params: Record<string, string | number> = {
      project_id: projectId,
      limit,
    };
    if (messageId) {
      params.message_id = messageId;
    }
    const response = await api.get<ToolExecutionsResponse>(
      `/agent/conversations/${conversationId}/tool-executions`,
      { params }
    );
    return response;
  }

  /**
   * Get conversation events for replay
   *
   * @param conversationId - The conversation ID
   * @param fromSequence - Starting sequence number (default: 0)
   * @param limit - Maximum events to return (default: 1000)
   * @returns Promise resolving to events and whether more exist
   */
  async getConversationEvents(
    conversationId: string,
    fromSequence = 0,
    limit = 1000
  ): Promise<{
    events: Array<{ type: string; data: unknown; timestamp: string | null }>;
    has_more: boolean;
  }> {
    const response = await api.get<{
      events: Array<{ type: string; data: unknown; timestamp: string | null }>;
      has_more: boolean;
    }>(`/agent/conversations/${conversationId}/events`, {
      params: {
        from_sequence: fromSequence,
        limit,
      },
    });
    return response;
  }

  /**
   * Get execution status for a conversation
   *
   * @param conversationId - The conversation ID
   * @returns Promise resolving to execution status
   */
  async getExecutionStatus(conversationId: string): Promise<{
    is_running: boolean;
    last_sequence: number;
    current_message_id: string | null;
    conversation_id: string;
  }> {
    const response = await api.get<{
      is_running: boolean;
      last_sequence: number;
      current_message_id: string | null;
      conversation_id: string;
    }>(`/agent/conversations/${conversationId}/execution-status`);
    return response;
  }

  /**
   * Record performance metric for an event type
   * @private
   */
  private recordEventMetric(eventType: string, timestamp: number): void {
    if (!this.performanceMetrics.has(eventType)) {
      this.performanceMetrics.set(eventType, []);
    }
    const metrics = this.performanceMetrics.get(eventType)!;
    metrics.push(timestamp);

    // Keep only the most recent samples
    if (metrics.length > this.MAX_METRICS_SAMPLES) {
      metrics.shift();
    }
  }

  /**
   * Get performance metrics for diagnostics
   * Returns event timing statistics for monitoring WebSocket event latency
   */
  getPerformanceMetrics(): Record<string, { count: number; lastSeen: number }> {
    const result: Record<string, { count: number; lastSeen: number }> = {};
    for (const [eventType, timestamps] of this.performanceMetrics.entries()) {
      result[eventType] = {
        count: timestamps.length,
        lastSeen: timestamps[timestamps.length - 1] || 0,
      };
    }
    return result;
  }

  /**
   * Clear performance metrics
   */
  clearPerformanceMetrics(): void {
    this.performanceMetrics.clear();
  }
}

// Export singleton instance
export const agentService = new AgentServiceImpl();

// Export type for convenience
export type { AgentService };
