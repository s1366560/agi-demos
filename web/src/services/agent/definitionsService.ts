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
  tenant_id?: string | null | undefined;
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

interface TenantScopedOptions {
  tenant_id?: string | null | undefined;
}

const tenantConfig = (options: TenantScopedOptions = {}) =>
  options.tenant_id ? { params: { tenant_id: options.tenant_id } } : undefined;

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

  getById: async (
    id: string,
    options: TenantScopedOptions = {}
  ): Promise<AgentDefinition> => {
    return await api.get<AgentDefinition>(`/agent/definitions/${id}`, tenantConfig(options));
  },

  create: async (
    data: CreateDefinitionRequest,
    options: TenantScopedOptions = {}
  ): Promise<AgentDefinition> => {
    return await api.post<AgentDefinition>('/agent/definitions', data, tenantConfig(options));
  },

  update: async (
    id: string,
    data: UpdateDefinitionRequest,
    options: TenantScopedOptions = {}
  ): Promise<AgentDefinition> => {
    return await api.put<AgentDefinition>(
      `/agent/definitions/${id}`,
      data,
      tenantConfig(options)
    );
  },

  delete: async (
    id: string,
    options: TenantScopedOptions = {}
  ): Promise<DeleteDefinitionResponse> => {
    return await api.delete<DeleteDefinitionResponse>(
      `/agent/definitions/${id}`,
      tenantConfig(options)
    );
  },

  setEnabled: async (
    id: string,
    enabled: boolean,
    options: TenantScopedOptions = {}
  ): Promise<AgentDefinition> => {
    return await api.patch<AgentDefinition>(
      `/agent/definitions/${id}/enabled`,
      { enabled },
      tenantConfig(options)
    );
  },
};
