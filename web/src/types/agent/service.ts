import type {
  CreateConversationRequest,
  CreateConversationResponse,
  ConversationStatus,
  PaginatedConversationsResponse,
  Conversation,
  ChatRequest,
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
/**
 * Agent service interface (extended for multi-level thinking)
 */
export interface AgentService {
  createConversation(request: CreateConversationRequest): Promise<CreateConversationResponse>;
  listConversations(
    projectId: string,
    status?: ConversationStatus,
    limit?: number,
    offset?: number
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
  killSubAgent(conversationId: string, subagentId: string): boolean;
  steerSubAgent(conversationId: string, subagentId: string, instruction: string): boolean;
}
