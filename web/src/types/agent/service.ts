import type {
  CreateConversationRequest,
  CreateConversationResponse,
  ConversationStatus,
  PaginatedConversationsResponse,
  Conversation,
  ChatRequest,
  ListConversationsRequestOptions,
  ConversationMessagesResponse,
  ExecutionHistoryResponse,
  ExecutionStatsResponse,
  ToolExecutionsResponse,
  ToolsListResponse,
} from './core';
import type { AgentStreamHandler } from './streaming';

export interface SubscribeOptions {
  message_id?: string;
  from_time_us?: number;
  from_counter?: number;
}

export interface SubAgentControlOptions {
  expectedRunRevision: number;
  idempotencyKey?: string;
}

export interface KillSubAgentOptions extends SubAgentControlOptions {
  cascade: boolean;
}

export interface ControlCommandAck {
  type: 'control_command_ack';
  action: 'kill_run' | 'steer';
  accepted: boolean;
  duplicate: boolean;
  reason_code: string | null;
  conversation_id: string | null;
  project_id: string | null;
  run_id: string | null;
  run_revision: number | null;
  idempotency_key: string;
  cascade?: boolean;
}

/**
 * Agent service interface (extended for multi-level thinking)
 */
export interface AgentService {
  createConversation(request: CreateConversationRequest): Promise<CreateConversationResponse>;
  listConversations(
    projectId: string,
    status?: ConversationStatus,
    limit?: number,
    offset?: number,
    signal?: AbortSignal,
    options?: ListConversationsRequestOptions
  ): Promise<PaginatedConversationsResponse>;
  getConversation(conversationId: string, projectId: string): Promise<Conversation | null>;
  chat(request: ChatRequest, handler: AgentStreamHandler): Promise<void>;
  subscribe(conversationId: string, handler: AgentStreamHandler, options?: SubscribeOptions): void;
  unsubscribe(conversationId: string): void;
  stopChat(conversationId: string): boolean;
  connect(): Promise<void>;
  disconnect(): void;
  isConnected(): boolean;
  deleteConversation(conversationId: string, projectId: string): Promise<void>;
  getConversationMessages(
    conversationId: string,
    projectId: string,
    limit?: number
  ): Promise<ConversationMessagesResponse>;
  getExecutionHistory(
    conversationId: string,
    projectId: string,
    limit?: number,
    statusFilter?: string,
    toolFilter?: string
  ): Promise<ExecutionHistoryResponse>;
  getExecutionStats(conversationId: string, projectId: string): Promise<ExecutionStatsResponse>;
  getToolExecutions(
    conversationId: string,
    projectId: string,
    messageId?: string,
    limit?: number
  ): Promise<ToolExecutionsResponse>;
  listTools(): Promise<ToolsListResponse>;
  killSubAgent(
    conversationId: string,
    subagentId: string,
    options: KillSubAgentOptions
  ): Promise<ControlCommandAck>;
  steerSubAgent(
    conversationId: string,
    subagentId: string,
    instruction: string,
    options: SubAgentControlOptions
  ): Promise<ControlCommandAck>;
}
