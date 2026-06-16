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
  scope?: 'all' | 'tenant' | undefined;
  search?: string | undefined;
  sort?: 'name' | 'recent' | 'invocations' | undefined;
  enabled_only?: boolean | undefined;
  enabled?: boolean | undefined;
  limit?: number | undefined;
  offset?: number | undefined;
  include_total?: boolean | undefined;
}

export interface DefinitionListResponse {
  definitions: AgentDefinition[];
  total: number;
  limit: number;
  offset: number;
}

type RawDefinitionListResponse = AgentDefinition[] | DefinitionListResponse;

function normalizeDefinitionListResponse(
  response: RawDefinitionListResponse,
  params: DefinitionListParams
): DefinitionListResponse {
  if (Array.isArray(response)) {
    return {
      definitions: response,
      total: response.length,
      limit: params.limit ?? response.length,
      offset: params.offset ?? 0,
    };
  }
  return response;
}

export const definitionsService = {
  list: async (params: DefinitionListParams = {}): Promise<AgentDefinition[]> => {
    const response = await api.get<RawDefinitionListResponse>('/agent/definitions', { params });
    return normalizeDefinitionListResponse(response, params).definitions;
  },

  listPage: async (params: DefinitionListParams = {}): Promise<DefinitionListResponse> => {
    const queryParams = { ...params, include_total: true };
    const response = await api.get<RawDefinitionListResponse>('/agent/definitions', {
      params: queryParams,
    });
    return normalizeDefinitionListResponse(response, queryParams);
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
