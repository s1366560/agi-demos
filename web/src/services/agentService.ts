/**
 * Agent Service - Agent chat and conversation management
 *
 * Provides methods for interacting with the React-mode Agent backend API, including:
 * - Creating and managing conversations
 * - Sending messages and receiving streaming responses via WebSocket
 * - Getting conversation history and message lists
 * - Listing available tools and execution history
 *
 * @packageDocumentation
 */

import { logger } from '../utils/logger';

import { parseLifecycleStateData, parseSandboxStateData } from './agent/messageParsers';
import { routeToHandler, routeSubagentLifecycleMessage } from './agent/messageRouter';
import { restApi } from './agent/restApi';
import { WebSocketConnection } from './agent/wsConnection';

import type { ServerMessage, WebSocketStatus } from './agent/types';
import type {
  AgentEventType,
  AgentService,
  AgentStreamHandler,
  ChatRequest,
  Conversation,
  CreateConversationRequest,
  CreateConversationResponse,
  ConversationMessagesResponse,
  PaginatedConversationsResponse,
  ExecutionHistoryResponse,
  ExecutionStatsResponse,
  ToolExecutionsResponse,
  ToolsListResponse,
  LifecycleStateData,
  SandboxStateData,
  PendingHITLResponse,
} from '../types/agent';

function generateSessionId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).substring(2, 15)}`;
}

class AgentServiceImpl implements AgentService {
  private sessionId: string = generateSessionId();
  private wsConnection: WebSocketConnection;

  // Handler maps by conversation_id
  private handlers: Map<string, AgentStreamHandler> = new Map();

  // Pending subscriptions (to restore after reconnect)
  private subscriptions: Set<string> = new Set();

  // Status subscription for Agent session monitoring
  private statusSubscriber: { projectId: string; callback: (status: unknown) => void } | null = null;

  // Lifecycle state subscription for Agent lifecycle monitoring
  private lifecycleStateSubscriber: {
    projectId: string;
    tenantId: string;
    callback: (state: LifecycleStateData) => void;
  } | null = null;

  // Sandbox state subscription for real-time sandbox status sync
  private sandboxStateSubscriber: {
    projectId: string;
    tenantId: string;
    callback: (state: SandboxStateData) => void;
  } | null = null;

  // Performance tracking: Track event receive times for diagnostics
  private performanceMetrics: Map<string, number[]> = new Map();
  private readonly MAX_METRICS_SAMPLES = 100;

  constructor() {
    this.wsConnection = new WebSocketConnection({
      sessionId: this.sessionId,
      onMessage: (msg) => { this.handleMessage(msg); },
      onReconnect: () => { this.resubscribe(); },
    });
  }

  getSessionId(): string {
    return this.sessionId;
  }

  connect(): Promise<void> {
    return this.wsConnection.connect();
  }

  disconnect(): void {
    this.wsConnection.disconnect();
  }

  getStatus(): WebSocketStatus {
    return this.wsConnection.getStatus();
  }

  isConnected(): boolean {
    return this.wsConnection.isConnected();
  }

  onStatusChange(listener: (status: WebSocketStatus) => void): () => void {
    return this.wsConnection.onStatusChange(listener);
  }

  private send(message: Record<string, unknown>): boolean {
    return this.wsConnection.send(message);
  }

  private handleMessage(message: ServerMessage): void {
    const { type, conversation_id, data } = message;

    // Performance tracking
    const receiveTime = performance.now();
    this.recordEventMetric(type, receiveTime);

    // Filter out high-frequency noise from logs unless it's a structural event
    if (type !== 'text_delta' && type !== 'thought_delta' && type !== 'act_delta') {
      logger.debug('[AgentWS] handleMessage:', {
        type,
        conversation_id,
        hasData: !!data,
        eventTimeUs: message.event_time_us,
        counter: message.event_counter,
      });
    }

    if (type === 'connected') {
      logger.debug('[AgentWS] Connection confirmed:', data);
      return;
    }

    if (type === 'pong') {
      return;
    }

    if (type === 'ack') {
      logger.debug(`[AgentWS] Ack for ${message.action} on ${conversation_id}`);
      return;
    }

    if (type === 'status_update') {
      const projectId = (message as { project_id?: string | undefined }).project_id;
      if (this.statusSubscriber && projectId === this.statusSubscriber.projectId) {
        this.statusSubscriber.callback(data);
      }
      return;
    }

    if (type === 'lifecycle_state') {
      const projectId = (message as { project_id?: string | undefined }).project_id;
      if (this.lifecycleStateSubscriber && projectId === this.lifecycleStateSubscriber.projectId) {
        this.lifecycleStateSubscriber.callback(parseLifecycleStateData(message));
      }
      return;
    }

    if (type === 'sandbox_state_change' || type === 'sandbox_event') {
      const projectId = (message as { project_id?: string | undefined }).project_id;
      if (this.sandboxStateSubscriber && projectId === this.sandboxStateSubscriber.projectId) {
        this.sandboxStateSubscriber.callback(parseSandboxStateData(message));
      }
      return;
    }

    if (type === 'subagent_lifecycle') {
      routeSubagentLifecycleMessage(message, (id) => this.handlers.get(id));
      return;
    }

    if (conversation_id) {
      const handler = this.handlers.get(conversation_id);
      if (handler) {
        routeToHandler(type as AgentEventType, data, handler);
      } else {
        console.warn('[AgentWS] No handler found for conversation:', conversation_id);
      }
    }
  }

  private resubscribe(): void {
    this.subscriptions.forEach((conversationId) => {
      this.send({
        type: 'subscribe',
        conversation_id: conversationId,
      });
    });

    if (this.statusSubscriber) {
      this.send({
        type: 'subscribe_status',
        project_id: this.statusSubscriber.projectId,
      });
    }

    if (this.lifecycleStateSubscriber) {
      this.send({
        type: 'subscribe_lifecycle_state',
        project_id: this.lifecycleStateSubscriber.projectId,
        tenant_id: this.lifecycleStateSubscriber.tenantId,
      });
    }

    if (this.sandboxStateSubscriber) {
      this.send({
        type: 'subscribe_sandbox',
        project_id: this.sandboxStateSubscriber.projectId,
        tenant_id: this.sandboxStateSubscriber.tenantId,
      });
    }
  }

  // ---- REST API Wrappers ----

  createConversation(request: CreateConversationRequest): Promise<CreateConversationResponse> {
    return restApi.createConversation(request);
  }

  listConversations(
    projectId: string,
    status?: 'active' | 'archived' | 'deleted',
    limit?: number,
    offset?: number
  ): Promise<PaginatedConversationsResponse> {
    return restApi.listConversations(projectId, status, limit, offset);
  }

  getConversation(conversationId: string, projectId: string): Promise<Conversation | null> {
    return restApi.getConversation(conversationId, projectId);
  }

  getContextStatus(
    conversationId: string,
    projectId: string
  ): Promise<{
    conversation_id: string;
    token_usage: {
      input_tokens: number;
      output_tokens: number;
      total_tokens: number;
      estimated_cost_usd: number;
    };
    compression_level: string;
    last_compressed_time?: string;
  } & Partial<{
    from_cache: boolean;
    messages_in_summary: number;
    summary_tokens: number;
  }>> {
    return restApi.getContextStatus(conversationId, projectId);
  }

  deleteConversation(conversationId: string, projectId: string): Promise<void> {
    return restApi.deleteConversation(conversationId, projectId);
  }

  updateConversationTitle(
    conversationId: string,
    projectId: string,
    title: string
  ): Promise<Conversation> {
    return restApi.updateConversationTitle(conversationId, projectId, title);
  }

  generateConversationTitle(
    conversationId: string,
    projectId: string
  ): Promise<Conversation> {
    return restApi.generateConversationTitle(conversationId, projectId);
  }

  generateConversationSummary(
    conversationId: string,
    projectId: string
  ): Promise<Conversation> {
    return restApi.generateConversationSummary(conversationId, projectId);
  }

  requestToolUndo(
    conversationId: string,
    executionId: string
  ): Promise<{ status: string; message_id: string; tool_name: string }> {
    return restApi.requestToolUndo(conversationId, executionId);
  }

  getConversationMessages(
    conversationId: string,
    projectId: string,
    limit?: number,
    fromTimeUs?: number,
    fromCounter?: number,
    beforeTimeUs?: number,
    beforeCounter?: number
  ): Promise<ConversationMessagesResponse> {
    return restApi.getConversationMessages(
      conversationId,
      projectId,
      limit,
      fromTimeUs,
      fromCounter,
      beforeTimeUs,
      beforeCounter
    );
  }

  listTools(): Promise<ToolsListResponse> {
    return restApi.listTools();
  }

  getPendingHITLRequests(
    conversationId: string,
    requestType?: 'clarification' | 'decision' | 'env_var'
  ): Promise<PendingHITLResponse> {
    return restApi.getPendingHITLRequests(conversationId, requestType);
  }

  getExecutionHistory(
    conversationId: string,
    projectId: string,
    limit?: number,
    statusFilter?: string,
    toolFilter?: string
  ): Promise<ExecutionHistoryResponse> {
    return restApi.getExecutionHistory(conversationId, projectId, limit, statusFilter, toolFilter);
  }

  getExecutionStats(
    conversationId: string,
    projectId: string
  ): Promise<ExecutionStatsResponse> {
    return restApi.getExecutionStats(conversationId, projectId);
  }

  getToolExecutions(
    conversationId: string,
    projectId: string,
    messageId?: string,
    limit?: number
  ): Promise<ToolExecutionsResponse> {
    return restApi.getToolExecutions(conversationId, projectId, messageId, limit);
  }

  getConversationEvents(
    conversationId: string,
    limit?: number,
    beforeTimeUs?: number,
    beforeCounter?: number
  ): Promise<{ events: Array<Record<string, unknown>>; has_more: boolean }> {
    return restApi.getConversationEvents(conversationId, limit, beforeTimeUs, beforeCounter);
  }

  getExecutionStatus(
    conversationId: string,
    checkRecovery = false,
    sinceTimeUs?: number,
    sinceCounter?: number
  ): Promise<{
    status: 'running' | 'completed' | 'failed' | 'paused' | 'unknown';
    is_active: boolean;
    is_running?: boolean;
    last_event_time_us?: number;
    last_event_counter?: number;
    conversation_id: string;
    can_recover?: boolean;
    recovery_events_count?: number;
    latest_event?: {
      type: string;
      time_us: number;
      counter: number;
    };
  }> {
    return restApi.getExecutionStatus(conversationId, checkRecovery, sinceTimeUs, sinceCounter);
  }

  // ---- Interactive Actions ----

  respondToEnvVar(requestId: string, values: Record<string, string>): Promise<void> {
    if (this.isConnected()) {
      this.send({
        type: 'env_var_respond',
        request_id: requestId,
        values,
      });
      return Promise.resolve();
    }
    return restApi.respondToEnvVarHttp(requestId, values);
  }

  respondToClarification(requestId: string, answer: string): Promise<void> {
    if (this.isConnected()) {
      this.send({
        type: 'clarification_respond',
        request_id: requestId,
        answer,
      });
      return Promise.resolve();
    }
    return restApi.respondToClarificationHttp(requestId, answer);
  }

  respondToDecision(requestId: string, decision: string | string[]): Promise<void> {
    if (this.isConnected()) {
      this.send({
        type: 'decision_respond',
        request_id: requestId,
        decision,
      });
      return Promise.resolve();
    }
    return restApi.respondToDecisionHttp(requestId, decision);
  }

  respondToPermission(requestId: string, granted: boolean): Promise<void> {
    if (this.isConnected()) {
      this.send({
        type: 'permission_respond',
        request_id: requestId,
        granted,
      });
      return Promise.resolve();
    }
    return restApi.respondToPermissionHttp(requestId, granted);
  }

  stopChat(conversationId: string): boolean {
    const sent = this.send({
      type: 'stop_session',
      conversation_id: conversationId,
    });
    if (!sent) {
      logger.warn('[AgentWS] Failed to send stop signal - WebSocket not connected');
    }
    return sent;
  }

  startAgent(projectId: string): boolean {
    const sent = this.send({
      type: 'start_agent',
      project_id: projectId,
    });
    if (!sent) {
      logger.warn(`[AgentWS] Failed to send start agent signal - WebSocket not connected`);
    }
    return sent;
  }

  stopAgent(projectId: string): boolean {
    const sent = this.send({
      type: 'stop_agent',
      project_id: projectId,
    });
    if (!sent) {
      logger.warn(`[AgentWS] Failed to send stop agent signal - WebSocket not connected`);
    }
    return sent;
  }

  restartAgent(projectId: string): boolean {
    const sent = this.send({
      type: 'restart_agent',
      project_id: projectId,
    });
    if (!sent) {
      logger.warn(`[AgentWS] Failed to send restart agent signal - WebSocket not connected`);
    }
    return sent;
  }

  async chat(request: ChatRequest, handler: AgentStreamHandler): Promise<void> {
    const { conversation_id, message, project_id, file_metadata } = request;

    if (!this.isConnected()) {
      await this.connect();
    }

    this.handlers.set(conversation_id, handler);
    this.subscriptions.add(conversation_id);

    const sent = this.send({
      type: 'send_message',
      conversation_id,
      message,
      project_id,
      file_metadata,
    });

    if (!sent) {
      handler.onError?.({
        type: 'error',
        data: {
          message: 'Failed to send message - WebSocket not connected',
          isReconnectable: true,
        },
      });
      throw new Error('WebSocket not connected');
    }
  }

  subscribe(conversationId: string, handler: AgentStreamHandler): void {
    const alreadySubscribed = this.subscriptions.has(conversationId);
    this.handlers.set(conversationId, handler);
    this.subscriptions.add(conversationId);

    if (this.isConnected() && !alreadySubscribed) {
      this.send({
        type: 'subscribe',
        conversation_id: conversationId,
      });
    }
  }

  unsubscribe(conversationId: string): void {
    this.handlers.delete(conversationId);
    this.subscriptions.delete(conversationId);

    if (this.isConnected()) {
      this.send({
        type: 'unsubscribe',
        conversation_id: conversationId,
      });
    }
  }

  private recordEventMetric(eventType: string, timestamp: number): void {
    if (!this.performanceMetrics.has(eventType)) {
      this.performanceMetrics.set(eventType, []);
    }
    const metrics = this.performanceMetrics.get(eventType)!;
    metrics.push(timestamp);

    if (metrics.length > this.MAX_METRICS_SAMPLES) {
      metrics.shift();
    }
  }

  getPerformanceMetrics(): Record<string, { count: number; lastSeen: number }> {
    const result: Record<string, { count: number; lastSeen: number }> = {};
    for (const [eventType, timestamps] of this.performanceMetrics.entries()) {
      result[eventType] = {
        count: timestamps.length,
        lastSeen: timestamps[timestamps.length - 1] ?? 0,
      };
    }
    return result;
  }

  clearPerformanceMetrics(): void {
    this.performanceMetrics.clear();
  }

  subscribeStatus(projectId: string, callback: (status: unknown) => void): void {
    this.statusSubscriber = { projectId, callback };

    if (this.isConnected()) {
      this.send({
        type: 'subscribe_status',
        project_id: projectId,
      });
      logger.debug(`[AgentWS] Subscribed to status updates for project: ${projectId}`);
    }
  }

  unsubscribeStatus(): void {
    if (this.statusSubscriber && this.isConnected()) {
      this.send({
        type: 'unsubscribe_status',
        project_id: this.statusSubscriber.projectId,
      });
      logger.debug(
        `[AgentWS] Unsubscribed from status updates for project: ${this.statusSubscriber.projectId}`
      );
    }
    this.statusSubscriber = null;
  }

  subscribeLifecycleState(
    projectId: string,
    tenantId: string,
    callback: (state: LifecycleStateData) => void
  ): void {
    this.lifecycleStateSubscriber = { projectId, tenantId, callback };

    if (this.isConnected()) {
      this.send({
        type: 'subscribe_lifecycle_state',
        project_id: projectId,
        tenant_id: tenantId,
      });
    }
  }

  unsubscribeLifecycleState(): void {
    if (this.lifecycleStateSubscriber && this.isConnected()) {
      this.send({
        type: 'unsubscribe_lifecycle_state',
        project_id: this.lifecycleStateSubscriber.projectId,
        tenant_id: this.lifecycleStateSubscriber.tenantId,
      });
    }
    this.lifecycleStateSubscriber = null;
  }

  subscribeSandboxState(
    projectId: string,
    tenantId: string,
    callback: (state: SandboxStateData) => void
  ): void {
    this.sandboxStateSubscriber = { projectId, tenantId, callback };

    if (this.isConnected()) {
      this.send({
        type: 'subscribe_sandbox',
        project_id: projectId,
        tenant_id: tenantId,
      });
    }
  }

  unsubscribeSandboxState(): void {
    if (this.sandboxStateSubscriber) {
      if (this.isConnected()) {
        this.send({
          type: 'unsubscribe_sandbox',
          project_id: this.sandboxStateSubscriber.projectId,
        });
      }
    }
    this.sandboxStateSubscriber = null;
  }
}

// Export singleton instance
export const agentService = new AgentServiceImpl();

// Export type for convenience
export type { AgentService };
export type { WebSocketStatus, ServerMessage } from './agent/types';
