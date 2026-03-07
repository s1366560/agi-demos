import { ApiError } from '../client/ApiError';
import { httpClient } from '../client/httpClient';

import type {
  Conversation,
  CreateConversationRequest,
  CreateConversationResponse,
  PaginatedConversationsResponse,
  ConversationMessagesResponse,
  ExecutionHistoryResponse,
  ExecutionStatsResponse,
  ToolExecutionsResponse,
  ToolsListResponse,
  PendingHITLResponse,
} from '../../types/agent';

const api = httpClient;

export const restApi = {
  async createConversation(
    request: CreateConversationRequest
  ): Promise<CreateConversationResponse> {
    return await api.post<CreateConversationResponse>('/agent/conversations', request);
  },

  async listConversations(
    projectId: string,
    status?: 'active' | 'archived' | 'deleted',
    limit = 10,
    offset = 0
  ): Promise<PaginatedConversationsResponse> {
    const params: Record<string, string | number> = {
      project_id: projectId,
      limit,
      offset,
    };
    if (status) {
      params.status = status;
    }
    return await api.get<PaginatedConversationsResponse>('/agent/conversations', { params });
  },

  async getConversation(conversationId: string, projectId: string): Promise<Conversation | null> {
    try {
      return await api.get<Conversation>(`/agent/conversations/${conversationId}`, {
        params: { project_id: projectId },
      });
    } catch (error) {
      if (error instanceof ApiError && error.statusCode === 404) {
        return null;
      }
      throw error;
    }
  },

  async getContextStatus(
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
  }> {
    return await api.get(`/agent/conversations/${conversationId}/context-status`, {
      params: { project_id: projectId },
    });
  },

  async deleteConversation(conversationId: string, projectId: string): Promise<void> {
    await api.delete(`/agent/conversations/${conversationId}`, {
      params: { project_id: projectId },
    });
  },

  async updateConversationTitle(
    conversationId: string,
    projectId: string,
    title: string
  ): Promise<Conversation> {
    return await api.patch<Conversation>(
      `/agent/conversations/${conversationId}`,
      { title },
      { params: { project_id: projectId } }
    );
  },

  async generateConversationTitle(
    conversationId: string,
    projectId: string
  ): Promise<Conversation> {
    return await api.post<Conversation>(
      `/agent/conversations/${conversationId}/generate-title`,
      {},
      { params: { project_id: projectId } }
    );
  },

  async generateConversationSummary(
    conversationId: string,
    projectId: string
  ): Promise<Conversation> {
    return await api.post<Conversation>(
      `/agent/conversations/${conversationId}/summary`,
      {},
      { params: { project_id: projectId } }
    );
  },

  async requestToolUndo(
    conversationId: string,
    executionId: string
  ): Promise<{ status: string; message_id: string; tool_name: string }> {
    return await api.post<{ status: string; message_id: string; tool_name: string }>(
      `/agent/conversations/${conversationId}/tools/${executionId}/undo`,
      {}
    );
  },

  async getConversationMessages(
    conversationId: string,
    projectId: string,
    limit = 50,
    fromTimeUs?: number,
    fromCounter?: number,
    beforeTimeUs?: number,
    beforeCounter?: number
  ): Promise<ConversationMessagesResponse> {
    const params: Record<string, string | number> = {
      project_id: projectId,
      limit,
    };
    if (fromTimeUs !== undefined) params.from_time_us = fromTimeUs;
    if (fromCounter !== undefined) params.from_counter = fromCounter;
    if (beforeTimeUs !== undefined) params.before_time_us = beforeTimeUs;
    if (beforeCounter !== undefined) params.before_counter = beforeCounter;

    const response = await api.get<ConversationMessagesResponse>(
      `/agent/conversations/${conversationId}/messages`,
      { params }
    );

    return {
      ...response,
      has_more: response.has_more ?? false,
      first_time_us: response.first_time_us ?? null,
      first_counter: response.first_counter ?? null,
      last_time_us: response.last_time_us ?? null,
      last_counter: response.last_counter ?? null,
    };
  },

  async listTools(): Promise<ToolsListResponse> {
    return await api.get<ToolsListResponse>('/agent/tools');
  },

  async getPendingHITLRequests(
    conversationId: string,
    requestType?: 'clarification' | 'decision' | 'env_var'
  ): Promise<PendingHITLResponse> {
    const params = new URLSearchParams();
    if (requestType) {
      params.append('request_type', requestType);
    }
    const queryString = params.toString();
    const url = `/agent/hitl/conversations/${conversationId}/pending${queryString ? `?${queryString}` : ''}`;
    return await api.get<PendingHITLResponse>(url);
  },

  async getExecutionHistory(
    conversationId: string,
    projectId: string,
    limit = 50,
    statusFilter?: string,
    toolFilter?: string
  ): Promise<ExecutionHistoryResponse> {
    const params: Record<string, string | number> = {
      project_id: projectId,
      limit,
    };
    if (statusFilter) params.status = statusFilter;
    if (toolFilter) params.tool = toolFilter;

    return await api.get<ExecutionHistoryResponse>(
      `/agent/conversations/${conversationId}/execution`,
      { params }
    );
  },

  async getExecutionStats(
    conversationId: string,
    projectId: string
  ): Promise<ExecutionStatsResponse> {
    return await api.get<ExecutionStatsResponse>(
      `/agent/conversations/${conversationId}/execution/stats`,
      { params: { project_id: projectId } }
    );
  },

  async getToolExecutions(
    conversationId: string,
    projectId: string,
    messageId?: string,
    limit = 50
  ): Promise<ToolExecutionsResponse> {
    const params: Record<string, string | number> = {
      project_id: projectId,
      limit,
    };
    if (messageId) params.message_id = messageId;

    return await api.get<ToolExecutionsResponse>(
      `/agent/conversations/${conversationId}/tool-executions`,
      { params }
    );
  },

  async getConversationEvents(
    conversationId: string,
    limit = 100,
    beforeTimeUs?: number,
    beforeCounter?: number
  ): Promise<{
    events: Array<Record<string, unknown>>;
    has_more: boolean;
  }> {
    const params: Record<string, string | number> = { limit };
    if (beforeTimeUs !== undefined) params.before_time_us = beforeTimeUs;
    if (beforeCounter !== undefined) params.before_counter = beforeCounter;

    return await api.get<{
      events: Array<Record<string, unknown>>;
      has_more: boolean;
    }>(`/agent/conversations/${conversationId}/events`, {
      params,
    });
  },

  async getExecutionStatus(
    conversationId: string,
    checkRecovery = false,
    sinceTimeUs?: number,
    sinceCounter?: number
  ): Promise<{
    status: 'running' | 'completed' | 'failed' | 'paused' | 'unknown';
    is_active: boolean;
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
    const params: Record<string, string | number | boolean> = {
      check_recovery: checkRecovery,
    };
    if (sinceTimeUs !== undefined) params.since_time_us = sinceTimeUs;
    if (sinceCounter !== undefined) params.since_counter = sinceCounter;

    return await api.get<{
      status: 'running' | 'completed' | 'failed' | 'paused' | 'unknown';
      is_active: boolean;
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
    }>(`/agent/conversations/${conversationId}/execution-status`, {
      params,
    });
  },

  async respondToEnvVarHttp(requestId: string, values: Record<string, string>): Promise<void> {
    await api.post<{ status: string }>('/agent/hitl/respond', {
      request_id: requestId,
      hitl_type: 'env_var',
      response_data: { values },
    });
  },

  async respondToClarificationHttp(requestId: string, answer: string): Promise<void> {
    await api.post<{ status: string }>('/agent/hitl/respond', {
      request_id: requestId,
      hitl_type: 'clarification',
      response_data: { answer },
    });
  },

  async respondToDecisionHttp(requestId: string, decision: string | string[]): Promise<void> {
    await api.post<{ status: string }>('/agent/hitl/respond', {
      request_id: requestId,
      hitl_type: 'decision',
      response_data: { decision },
    });
  },

  async respondToPermissionHttp(requestId: string, granted: boolean): Promise<void> {
    await api.post<{ status: string }>('/agent/hitl/respond', {
      request_id: requestId,
      hitl_type: 'permission',
      response_data: { granted, action: granted ? 'allow' : 'deny' },
    });
  },

  async respondToA2UIActionHttp(
    requestId: string,
    actionName: string,
    sourceComponentId: string,
    context: Record<string, unknown>
  ): Promise<void> {
    await api.post<{ status: string }>('/agent/hitl/respond', {
      request_id: requestId,
      hitl_type: 'a2ui_action',
      response_data: {
        action_name: actionName,
        source_component_id: sourceComponentId,
        context,
      },
    });
  },
};
