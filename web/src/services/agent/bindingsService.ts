import { httpClient } from '../client/httpClient';

import type {
  AgentBinding,
  CreateBindingRequest,
  DeleteBindingResponse,
  TestBindingRequest,
  TestBindingResponse,
} from '../../types/multiAgent';

const api = httpClient;

export interface BindingListParams {
  agent_id?: string | undefined;
  enabled_only?: boolean | undefined;
  tenant_id?: string | null | undefined;
}

interface TenantScopedOptions {
  tenant_id?: string | null | undefined;
}

const tenantConfig = (options: TenantScopedOptions = {}) =>
  options.tenant_id ? { params: { tenant_id: options.tenant_id } } : undefined;

export const bindingsService = {
  list: async (params: BindingListParams = {}): Promise<AgentBinding[]> => {
    return await api.get<AgentBinding[]>('/agent/bindings', { params });
  },

  create: async (
    data: CreateBindingRequest,
    options: TenantScopedOptions = {}
  ): Promise<AgentBinding> => {
    return await api.post<AgentBinding>('/agent/bindings', data, tenantConfig(options));
  },

  delete: async (
    bindingId: string,
    options: TenantScopedOptions = {}
  ): Promise<DeleteBindingResponse> => {
    return await api.delete<DeleteBindingResponse>(
      `/agent/bindings/${bindingId}`,
      tenantConfig(options)
    );
  },

  setEnabled: async (
    bindingId: string,
    enabled: boolean,
    options: TenantScopedOptions = {}
  ): Promise<AgentBinding> => {
    return await api.patch<AgentBinding>(
      `/agent/bindings/${bindingId}/enabled`,
      { enabled },
      tenantConfig(options)
    );
  },

  test: async (
    data: TestBindingRequest,
    options: TenantScopedOptions = {}
  ): Promise<TestBindingResponse> => {
    return await api.post<TestBindingResponse>('/agent/bindings/test', data, tenantConfig(options));
  },
};
