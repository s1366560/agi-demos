/**
 * Command API Service
 *
 * Provides API methods for listing available slash commands.
 * Commands are registered on the backend and intercepted before the ReAct loop.
 */

import { httpClient } from './client/httpClient';

import type { CommandsListResponse } from '../types/agent';

const api = httpClient;

export interface CommandListParams {
  category?: string | null | undefined;
  scope?: string | null | undefined;
}

export const commandAPI = {
  /**
   * List all available slash commands
   */
  list: async (params: CommandListParams = {}): Promise<CommandsListResponse> => {
    return await api.get<CommandsListResponse>('/agent/commands', { params });
  },
};

export default commandAPI;
