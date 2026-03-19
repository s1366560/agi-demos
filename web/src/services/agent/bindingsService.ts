import { httpClient } from '../client/httpClient';

import type {
  AgentBinding,
  CreateBindingRequest,
  DeleteBindingResponse,
} from '../../types/multiAgent';

const api = httpClient;

export interface BindingListParams {
  agent_id?: string | undefined;
  enabled_only?: boolean | undefined;
}

export const bindingsService = {
  list: async (params: BindingListParams = {}): Promise<AgentBinding[]> => {
    return await api.get<AgentBinding[]>('/agent/bindings', { params });
  },

  create: async (data: CreateBindingRequest): Promise<AgentBinding> => {
    return await api.post<AgentBinding>('/agent/bindings', data);
  },

  delete: async (bindingId: string): Promise<DeleteBindingResponse> => {
    return await api.delete<DeleteBindingResponse>(`/agent/bindings/${bindingId}`);
  },

  setEnabled: async (bindingId: string, enabled: boolean): Promise<AgentBinding> => {
    return await api.patch<AgentBinding>(`/agent/bindings/${bindingId}/enabled`, { enabled });
  },
};
