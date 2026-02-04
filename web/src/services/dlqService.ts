/**
 * DLQ Service
 * 
 * API client for Dead Letter Queue management.
 */

import { httpClient } from './client/httpClient';

// =============================================================================
// Types
// =============================================================================

export type DLQMessageStatus = 
  | 'pending' 
  | 'retrying' 
  | 'discarded' 
  | 'expired' 
  | 'resolved';

export interface DLQMessage {
  id: string;
  event_id: string;
  event_type: string;
  event_data: string;
  routing_key: string;
  error: string;
  error_type: string;
  error_traceback: string | null;
  retry_count: number;
  max_retries: number;
  first_failed_at: string;
  last_failed_at: string;
  next_retry_at: string | null;
  status: DLQMessageStatus;
  metadata: Record<string, unknown>;
  can_retry: boolean;
  age_seconds: number;
}

export interface DLQListResponse {
  messages: DLQMessage[];
  total: number;
  limit: number;
  offset: number;
}

export interface DLQStats {
  total_messages: number;
  pending_count: number;
  retrying_count: number;
  discarded_count: number;
  expired_count: number;
  resolved_count: number;
  oldest_message_age_seconds: number;
  error_type_counts: Record<string, number>;
  event_type_counts: Record<string, number>;
}

export interface RetryResponse {
  results: Record<string, boolean>;
  success_count: number;
  failure_count: number;
}

export interface DiscardResponse {
  results: Record<string, boolean>;
  success_count: number;
  failure_count: number;
}

export interface CleanupResponse {
  cleaned_count: number;
}

export interface ListMessagesParams {
  status?: DLQMessageStatus;
  event_type?: string;
  error_type?: string;
  routing_key?: string;
  limit?: number;
  offset?: number;
}

// =============================================================================
// API Client
// =============================================================================

const BASE_URL = '/admin/dlq';

export const dlqService = {
  /**
   * List DLQ messages with optional filtering
   */
  async listMessages(params?: ListMessagesParams): Promise<DLQListResponse> {
    return await httpClient.get<DLQListResponse>(`${BASE_URL}/messages`, {
      params,
    });
  },

  /**
   * Get a specific DLQ message by ID
   */
  async getMessage(messageId: string): Promise<DLQMessage> {
    return await httpClient.get<DLQMessage>(
      `${BASE_URL}/messages/${messageId}`
    );
  },

  /**
   * Retry a single message
   */
  async retryMessage(messageId: string): Promise<{ success: boolean }> {
    return await httpClient.post<{ success: boolean }>(
      `${BASE_URL}/messages/${messageId}/retry`
    );
  },

  /**
   * Retry multiple messages in batch
   */
  async retryMessages(messageIds: string[]): Promise<RetryResponse> {
    return await httpClient.post<RetryResponse>(
      `${BASE_URL}/messages/retry`,
      { message_ids: messageIds }
    );
  },

  /**
   * Discard a single message
   */
  async discardMessage(
    messageId: string,
    reason: string
  ): Promise<{ success: boolean }> {
    return await httpClient.delete<{ success: boolean }>(
      `${BASE_URL}/messages/${messageId}`,
      { params: { reason } }
    );
  },

  /**
   * Discard multiple messages in batch
   */
  async discardMessages(
    messageIds: string[],
    reason: string
  ): Promise<DiscardResponse> {
    return await httpClient.post<DiscardResponse>(
      `${BASE_URL}/messages/discard`,
      { message_ids: messageIds, reason }
    );
  },

  /**
   * Get DLQ statistics
   */
  async getStats(): Promise<DLQStats> {
    return await httpClient.get<DLQStats>(`${BASE_URL}/stats`);
  },

  /**
   * Clean up expired messages
   */
  async cleanupExpired(olderThanHours: number = 168): Promise<CleanupResponse> {
    return await httpClient.post<CleanupResponse>(
      `${BASE_URL}/cleanup/expired`,
      null,
      { params: { older_than_hours: olderThanHours } }
    );
  },

  /**
   * Clean up resolved messages
   */
  async cleanupResolved(olderThanHours: number = 24): Promise<CleanupResponse> {
    return await httpClient.post<CleanupResponse>(
      `${BASE_URL}/cleanup/resolved`,
      null,
      { params: { older_than_hours: olderThanHours } }
    );
  },
};

export default dlqService;
