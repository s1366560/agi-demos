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

import type { ExecutionStatusApiResponse } from './agent/restApi';
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
  SubscribeOptions,
  ListConversationsRequestOptions,
} from '../types/agent';

function generateSessionId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `${String(Date.now())}-${Math.random().toString(36).substring(2, 15)}`;
}

const SILENT_AGENT_EVENT_TYPES = new Set<string>([
  'text_delta',
  'thought_delta',
  'act_delta',
  'status_update',
  'lifecycle_state',
  'lifecycle_state_change',
  'sandbox_state_change',
  'sandbox_event',
]);
const CONTROL_AGENT_EVENT_TYPES = new Set<string>(['connected', 'pong', 'ack']);
const IDLE_DISCONNECT_DELAY_MS = 5000;
const SEND_ACK_TIMEOUT_MS = 8000;

interface ProjectTenantSubscriptionKey {
  projectId: string;
  tenantId: string;
}

function matchesProjectTenantSubscription(
  subscriber: ProjectTenantSubscriptionKey,
  expected?: ProjectTenantSubscriptionKey
): boolean {
  return (
    !expected ||
    (subscriber.projectId === expected.projectId && subscriber.tenantId === expected.tenantId)
  );
}

function getAgentErrorMessage(data: unknown): string {
  if (data instanceof Error && data.message.trim()) {
    return data.message;
  }

  if (data && typeof data === 'object') {
    const record = data as Record<string, unknown>;
    for (const key of ['message', 'error', 'detail']) {
      const value = record[key];
      if (typeof value === 'string' && value.trim()) {
        return value;
      }
    }
  }

  if (typeof data === 'string' && data.trim()) {
    return data;
  }

  return 'Agent stream error';
}

class AgentServiceImpl implements AgentService {
  private sessionId: string = generateSessionId();
  private wsConnection: WebSocketConnection;

  // Handler maps by conversation_id
  private handlers: Map<string, AgentStreamHandler> = new Map();

  // Pending subscriptions (to restore after reconnect)
  private subscriptions: Set<string> = new Set();
  private subscriptionOptions: Map<string, SubscribeOptions> = new Map();

  // Status subscription for Agent session monitoring
  private statusSubscriber: { projectId: string; callback: (status: unknown) => void } | null =
    null;

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
  private idleDisconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private pendingSendAcks: Map<
    string,
    { resolve: () => void; reject: (error: Error) => void; timeout: ReturnType<typeof setTimeout> }
  > = new Map();

  constructor() {
    this.wsConnection = new WebSocketConnection({
      sessionId: this.sessionId,
      onMessage: (msg) => {
        this.handleMessage(msg);
      },
      onReconnect: () => {
        this.resubscribe();
      },
    });
  }

  getSessionId(): string {
    return this.sessionId;
  }

  connect(): Promise<void> {
    this.cancelIdleDisconnect();
    return this.wsConnection.connect();
  }

  disconnect(): void {
    this.cancelIdleDisconnect();
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

  private waitForSendAck(conversationId: string): Promise<void> {
    const existing = this.pendingSendAcks.get(conversationId);
    if (existing) {
      clearTimeout(existing.timeout);
      existing.reject(new Error('Superseded by a newer send_message request'));
      this.pendingSendAcks.delete(conversationId);
    }

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pendingSendAcks.delete(conversationId);
        reject(new Error('Timed out waiting for send_message acknowledgment'));
      }, SEND_ACK_TIMEOUT_MS);

      this.pendingSendAcks.set(conversationId, { resolve, reject, timeout });
    });
  }

  private resolveSendAck(message: ServerMessage): void {
    if (message.action !== 'send_message' || !message.conversation_id) {
      return;
    }
    const pending = this.pendingSendAcks.get(message.conversation_id);
    if (!pending) {
      return;
    }
    clearTimeout(pending.timeout);
    this.pendingSendAcks.delete(message.conversation_id);
    pending.resolve();
  }

  private cancelSendAck(conversationId: string): void {
    const pending = this.pendingSendAcks.get(conversationId);
    if (!pending) {
      return;
    }
    clearTimeout(pending.timeout);
    this.pendingSendAcks.delete(conversationId);
  }

  private handleMessage(message: ServerMessage): void {
    const { type, conversation_id, data } = message;

    // Performance tracking
    const receiveTime = performance.now();
    this.recordEventMetric(type, receiveTime);

    if (type === 'connected') {
      return;
    }

    if (type === 'pong') {
      return;
    }

    if (type === 'ack') {
      this.resolveSendAck(message);
      return;
    }

    if (!CONTROL_AGENT_EVENT_TYPES.has(type) && !SILENT_AGENT_EVENT_TYPES.has(type)) {
      logger.debug('[AgentWS] handleMessage:', {
        type,
        conversation_id,
        hasData: !!data,
        eventTimeUs: message.event_time_us,
        counter: message.event_counter,
      });
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

    if (type === 'error' && !conversation_id) {
      logger.warn('[AgentWS] Global error event:', {
        message: getAgentErrorMessage(data),
        hasData: !!data,
      });
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
      const options = this.subscriptionOptions.get(conversationId);
      this.send({
        type: 'subscribe',
        conversation_id: conversationId,
        ...(options?.message_id ? { message_id: options.message_id } : {}),
        ...(options?.from_time_us !== undefined ? { from_time_us: options.from_time_us } : {}),
        ...(options?.from_counter !== undefined ? { from_counter: options.from_counter } : {}),
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
    offset?: number,
    signal?: AbortSignal,
    options?: ListConversationsRequestOptions
  ): Promise<PaginatedConversationsResponse> {
    return restApi.listConversations(projectId, status, limit, offset, signal, options);
  }

  getConversation(conversationId: string, projectId: string): Promise<Conversation | null> {
    return restApi.getConversation(conversationId, projectId);
  }

  getContextStatus(
    conversationId: string,
    projectId: string
  ): Promise<
    {
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
    }>
  > {
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

  updateConversationConfig(
    conversationId: string,
    projectId: string,
    config: {
      selected_agent_id?: string | null;
      llm_model_override?: string | null;
      llm_overrides?: Record<string, unknown> | null;
    }
  ): Promise<Conversation> {
    return restApi.updateConversationConfig(conversationId, projectId, config);
  }

  updateConversationMode(
    conversationId: string,
    projectId: string,
    payload: {
      conversation_mode?: string | null;
      workspace_id?: string | null;
      linked_workspace_task_id?: string | null;
    }
  ): Promise<Conversation> {
    return restApi.updateConversationMode(conversationId, projectId, payload);
  }

  generateConversationTitle(conversationId: string, projectId: string): Promise<Conversation> {
    return restApi.generateConversationTitle(conversationId, projectId);
  }

  generateConversationSummary(conversationId: string, projectId: string): Promise<Conversation> {
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

  getExecutionStats(conversationId: string, projectId: string): Promise<ExecutionStatsResponse> {
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
  ): Promise<ExecutionStatusApiResponse> {
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

  respondToA2UIAction(
    requestId: string,
    actionName: string,
    sourceComponentId: string,
    context: Record<string, unknown>
  ): Promise<void> {
    if (this.isConnected()) {
      this.send({
        type: 'a2ui_action_respond',
        request_id: requestId,
        action_name: actionName,
        source_component_id: sourceComponentId,
        context,
      });
      return Promise.resolve();
    }
    return restApi.respondToA2UIActionHttp(requestId, actionName, sourceComponentId, context);
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

  killSubAgent(conversationId: string, subagentId: string): boolean {
    const sent = this.send({
      type: 'kill_run',
      conversation_id: conversationId,
      run_id: subagentId,
    });
    if (!sent) {
      logger.warn('[AgentWS] Failed to send kill_run signal - WebSocket not connected');
    }
    return sent;
  }

  steerSubAgent(conversationId: string, subagentId: string, instruction: string): boolean {
    const sent = this.send({
      type: 'steer',
      conversation_id: conversationId,
      run_id: subagentId,
      instruction,
    });
    if (!sent) {
      logger.warn('[AgentWS] Failed to send steer signal - WebSocket not connected');
    }
    return sent;
  }

  async chat(request: ChatRequest, handler: AgentStreamHandler): Promise<void> {
    this.cancelIdleDisconnect();
    const {
      conversation_id,
      message,
      project_id,
      preferred_language,
      file_metadata,
      forced_skill_name,
      app_model_context,
      image_attachments,
      agent_id,
      mentions,
    } = request;

    if (!this.isConnected()) {
      await this.connect();
    }

    this.handlers.set(conversation_id, handler);
    this.subscriptions.add(conversation_id);

    const sendAck = this.waitForSendAck(conversation_id);
    const sent = this.send({
      type: 'send_message',
      conversation_id,
      message,
      project_id,
      preferred_language,
      file_metadata,
      forced_skill_name,
      app_model_context,
      image_attachments,
      agent_id,
      mentions,
    });

    if (!sent) {
      this.cancelSendAck(conversation_id);
      handler.onError?.({
        type: 'error',
        data: {
          message: 'Failed to send message - WebSocket not connected',
          isReconnectable: true,
        },
      });
      throw new Error('WebSocket not connected');
    }
    await sendAck;
  }

  subscribe(conversationId: string, handler: AgentStreamHandler, options?: SubscribeOptions): void {
    this.cancelIdleDisconnect();
    const alreadySubscribed = this.subscriptions.has(conversationId);
    const previousOptions = this.subscriptionOptions.get(conversationId);
    this.handlers.set(conversationId, handler);
    this.subscriptions.add(conversationId);
    if (options) {
      this.subscriptionOptions.set(conversationId, options);
    } else if (!this.subscriptionOptions.has(conversationId)) {
      this.subscriptionOptions.set(conversationId, {});
    }
    const effectiveOptions = this.subscriptionOptions.get(conversationId) ?? {};
    const optionsChanged =
      (previousOptions?.message_id ?? null) !== (effectiveOptions.message_id ?? null) ||
      (previousOptions?.from_time_us ?? null) !== (effectiveOptions.from_time_us ?? null) ||
      (previousOptions?.from_counter ?? null) !== (effectiveOptions.from_counter ?? null);

    if (this.isConnected() && (!alreadySubscribed || optionsChanged)) {
      this.send({
        type: 'subscribe',
        conversation_id: conversationId,
        ...(effectiveOptions.message_id ? { message_id: effectiveOptions.message_id } : {}),
        ...(effectiveOptions.from_time_us !== undefined
          ? { from_time_us: effectiveOptions.from_time_us }
          : {}),
        ...(effectiveOptions.from_counter !== undefined
          ? { from_counter: effectiveOptions.from_counter }
          : {}),
      });
    }
  }

  unsubscribe(conversationId: string): void {
    this.handlers.delete(conversationId);
    this.subscriptions.delete(conversationId);
    this.subscriptionOptions.delete(conversationId);

    if (this.isConnected()) {
      this.send({
        type: 'unsubscribe',
        conversation_id: conversationId,
      });
    }
    this.scheduleIdleDisconnectIfUnused();
  }

  private recordEventMetric(eventType: string, timestamp: number): void {
    let metrics = this.performanceMetrics.get(eventType);
    if (metrics === undefined) {
      metrics = [];
      this.performanceMetrics.set(eventType, metrics);
    }

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
    this.cancelIdleDisconnect();
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
    this.scheduleIdleDisconnectIfUnused();
  }

  subscribeLifecycleState(
    projectId: string,
    tenantId: string,
    callback: (state: LifecycleStateData) => void
  ): void {
    this.cancelIdleDisconnect();
    const previousSubscriber = this.lifecycleStateSubscriber;
    const isSameSubscription =
      previousSubscriber?.projectId === projectId && previousSubscriber.tenantId === tenantId;

    if (previousSubscriber && !isSameSubscription && this.isConnected()) {
      this.send({
        type: 'unsubscribe_lifecycle_state',
        project_id: previousSubscriber.projectId,
        tenant_id: previousSubscriber.tenantId,
      });
    }

    this.lifecycleStateSubscriber = { projectId, tenantId, callback };

    if (this.isConnected() && !isSameSubscription) {
      this.send({
        type: 'subscribe_lifecycle_state',
        project_id: projectId,
        tenant_id: tenantId,
      });
    }
  }

  unsubscribeLifecycleState(expected?: ProjectTenantSubscriptionKey): void {
    const subscriber = this.lifecycleStateSubscriber;
    if (!subscriber) {
      return;
    }
    if (!matchesProjectTenantSubscription(subscriber, expected)) {
      return;
    }

    if (this.isConnected()) {
      this.send({
        type: 'unsubscribe_lifecycle_state',
        project_id: subscriber.projectId,
        tenant_id: subscriber.tenantId,
      });
    }
    this.lifecycleStateSubscriber = null;
    this.scheduleIdleDisconnectIfUnused();
  }

  subscribeSandboxState(
    projectId: string,
    tenantId: string,
    callback: (state: SandboxStateData) => void
  ): void {
    this.cancelIdleDisconnect();
    const previousSubscriber = this.sandboxStateSubscriber;
    const isSameSubscription =
      previousSubscriber?.projectId === projectId && previousSubscriber.tenantId === tenantId;

    if (previousSubscriber && !isSameSubscription && this.isConnected()) {
      this.send({
        type: 'unsubscribe_sandbox',
        project_id: previousSubscriber.projectId,
        tenant_id: previousSubscriber.tenantId,
      });
    }

    this.sandboxStateSubscriber = { projectId, tenantId, callback };

    if (this.isConnected() && !isSameSubscription) {
      this.send({
        type: 'subscribe_sandbox',
        project_id: projectId,
        tenant_id: tenantId,
      });
    }
  }

  unsubscribeSandboxState(expected?: ProjectTenantSubscriptionKey): void {
    const subscriber = this.sandboxStateSubscriber;
    if (!subscriber) {
      return;
    }
    if (!matchesProjectTenantSubscription(subscriber, expected)) {
      return;
    }

    if (this.isConnected()) {
      this.send({
        type: 'unsubscribe_sandbox',
        project_id: subscriber.projectId,
        tenant_id: subscriber.tenantId,
      });
    }
    this.sandboxStateSubscriber = null;
    this.scheduleIdleDisconnectIfUnused();
  }

  private hasRealtimeConsumers(): boolean {
    return (
      this.subscriptions.size > 0 ||
      this.statusSubscriber !== null ||
      this.lifecycleStateSubscriber !== null ||
      this.sandboxStateSubscriber !== null
    );
  }

  private cancelIdleDisconnect(): void {
    if (!this.idleDisconnectTimeout) {
      return;
    }
    clearTimeout(this.idleDisconnectTimeout);
    this.idleDisconnectTimeout = null;
  }

  private scheduleIdleDisconnectIfUnused(): void {
    if (this.hasRealtimeConsumers() || this.idleDisconnectTimeout || !this.isConnected()) {
      return;
    }

    this.idleDisconnectTimeout = setTimeout(() => {
      this.idleDisconnectTimeout = null;
      if (!this.hasRealtimeConsumers()) {
        this.disconnect();
      }
    }, IDLE_DISCONNECT_DELAY_MS);
  }
}

// Export singleton instance
export const agentService = new AgentServiceImpl();

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    agentService.disconnect();
  });
}

// Export type for convenience
export type { AgentService };
export type { WebSocketStatus, ServerMessage } from './agent/types';
