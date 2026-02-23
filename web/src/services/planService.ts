/**
 * Plan Mode API service.
 *
 * Simple mode switch: Plan Mode (read-only analysis) vs Build Mode (full execution).
 */

import { httpClient } from './client/httpClient';

const BASE_URL = '/agent/plan';

export interface ModeResponse {
  conversation_id: string;
  mode: 'plan' | 'build';
  switched_at: string;
}

export interface ConversationModeResponse {
  conversation_id: string;
  mode: 'plan' | 'build';
}

export const planService = {
  async switchMode(conversationId: string, mode: 'plan' | 'build'): Promise<ModeResponse> {
    return httpClient.post<ModeResponse>(`${BASE_URL}/mode`, {
      conversation_id: conversationId,
      mode,
    });
  },

  async getMode(conversationId: string): Promise<ConversationModeResponse> {
    return httpClient.get<ConversationModeResponse>(`${BASE_URL}/mode/${conversationId}`);
  },
};
