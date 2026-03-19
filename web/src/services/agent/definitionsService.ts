import { httpClient } from '../client/httpClient';

import type {
  AgentDefinition,
  CreateDefinitionRequest,
  UpdateDefinitionRequest,
  DeleteDefinitionResponse,
} from '../../types/multiAgent';

const api = httpClient;

export interface DefinitionListParams {
  project_id?: string | undefined;
  enabled_only?: boolean | undefined;
  limit?: number | undefined;
  offset?: number | undefined;
}

export const definitionsService = {
  list: async (params: DefinitionListParams = {}): Promise<AgentDefinition[]> => {
    return await api.get<AgentDefinition[]>('/agent/definitions', { params });
  },

  getById: async (id: string): Promise<AgentDefinition> => {
    return await api.get<AgentDefinition>(`/agent/definitions/${id}`);
  },

  create: async (data: CreateDefinitionRequest): Promise<AgentDefinition> => {
    return await api.post<AgentDefinition>('/agent/definitions', data);
  },

  update: async (id: string, data: UpdateDefinitionRequest): Promise<AgentDefinition> => {
    return await api.put<AgentDefinition>(`/agent/definitions/${id}`, data);
  },

  delete: async (id: string): Promise<DeleteDefinitionResponse> => {
    return await api.delete<DeleteDefinitionResponse>(`/agent/definitions/${id}`);
  },

  setEnabled: async (id: string, enabled: boolean): Promise<AgentDefinition> => {
    return await api.patch<AgentDefinition>(`/agent/definitions/${id}/enabled`, { enabled });
  },
};
