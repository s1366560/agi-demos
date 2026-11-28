/// <reference types="vite/client" />
import { cloudIdentity, type BackendUserResponse } from './client/cloudIdentity';
import { hostControlClient } from './client/hostControlClient';
import { httpClient } from './client/httpClient';

import type {
  ProjectCreate,
  ProjectUpdate,
  BackendStore,
  BackendStoreCreate,
  BackendStoreTestRequest,
  BackendStoreTestResponse,
  BackendStoreTypeInfo,
  BackendStoreUpdate,
  TenantCreate,
  TenantUpdate,
  ProviderCreate,
  ProviderConnectionProbe,
  ProviderUpdate,
  User,
  Project,
  ProjectListResponse,
  Tenant,
  TenantListResponse,
  UserTenant,
  ProviderConfig,
  ProviderHealth,
  ProviderTypeDescriptor,
  DetectedEnvironmentProvider,
  ProviderAutoConfig,
  ProviderType,
  SystemResilienceStatus,
  ProviderUsageStats,
  ModelCatalogEntry,
  UserUpdate,
} from '../types/memory';

// Use centralized HTTP client instead of creating a new axios instance
const api = httpClient;

type TenantMembersApiResponse = UserTenant[] | { members?: UserTenant[] };
// Tenant provider assignment response
interface TenantProviderAssignment {
  id: string;
  provider_id: string;
  tenant_id: string;
  priority: number;
  operation_type: 'llm' | 'embedding' | 'rerank';
  provider?: ProviderConfig;
  created_at: string;
  updated_at: string;
}

interface StoreApiEnvelope<T> {
  success: boolean;
  data?: T | undefined;
  version?: string | null | undefined;
  error?: string | undefined;
  detail?: string | undefined;
}

const unwrapStoreData = <T>(response: StoreApiEnvelope<T>): T => {
  if (!response.success) {
    throw new Error(response.error ?? response.detail ?? 'Store request failed');
  }
  if (response.data === undefined) {
    throw new Error('Store response did not include data');
  }
  return response.data;
};

const unwrapStoreTest = (response: StoreApiEnvelope<unknown>): BackendStoreTestResponse => ({
  success: response.success,
  version: response.version ?? null,
  error: response.error ?? response.detail,
});

const createBackendStoreAPI = (baseUrl: '/graph-stores' | '/retrieval-stores') => ({
  types: async (): Promise<BackendStoreTypeInfo[]> => {
    return unwrapStoreData(
      await api.get<StoreApiEnvelope<BackendStoreTypeInfo[]>>(`${baseUrl}/types`)
    );
  },
  list: async (tenantId: string): Promise<BackendStore[]> => {
    return unwrapStoreData(
      await api.get<StoreApiEnvelope<BackendStore[]>>(baseUrl, { params: { tenant_id: tenantId } })
    );
  },
  create: async (tenantId: string, data: BackendStoreCreate): Promise<BackendStore> => {
    return unwrapStoreData(
      await api.post<StoreApiEnvelope<BackendStore>>(baseUrl, data, {
        params: { tenant_id: tenantId },
      })
    );
  },
  update: async (
    tenantId: string,
    storeId: string,
    data: BackendStoreUpdate
  ): Promise<BackendStore> => {
    return unwrapStoreData(
      await api.put<StoreApiEnvelope<BackendStore>>(`${baseUrl}/${storeId}`, data, {
        params: { tenant_id: tenantId },
      })
    );
  },
  delete: async (tenantId: string, storeId: string): Promise<void> => {
    await api.delete(`${baseUrl}/${storeId}`, { params: { tenant_id: tenantId } });
  },
  testRaw: async (
    tenantId: string,
    data: BackendStoreTestRequest
  ): Promise<BackendStoreTestResponse> => {
    return unwrapStoreTest(
      await api.post<StoreApiEnvelope<unknown>>(`${baseUrl}/test`, data, {
        params: { tenant_id: tenantId },
      })
    );
  },
  testById: async (tenantId: string, storeId: string): Promise<BackendStoreTestResponse> => {
    return unwrapStoreTest(
      await api.post<StoreApiEnvelope<unknown>>(
        `${baseUrl}/${storeId}/test`,
        {},
        { params: { tenant_id: tenantId } }
      )
    );
  },
});

export const authAPI = {
  ...cloudIdentity,
  updateProfile: async (data: Partial<UserUpdate>): Promise<User> => {
    const userResponse = await hostControlClient.put<BackendUserResponse>('/users/me', data);
    return {
      id: userResponse.user_id,
      email: userResponse.email,
      name: userResponse.name,
      roles: userResponse.roles,
      is_active: userResponse.is_active,
      is_superuser: userResponse.is_superuser,
      created_at: userResponse.created_at,
      profile: userResponse.profile,
      preferred_language: userResponse.preferred_language ?? undefined,
    };
  },
  updatePreferredLanguage: async (language: 'en-US' | 'zh-CN'): Promise<User> => {
    const userResponse = await hostControlClient.put<BackendUserResponse>('/users/me', {
      preferred_language: language,
    });
    return {
      id: userResponse.user_id,
      email: userResponse.email,
      name: userResponse.name,
      roles: userResponse.roles,
      is_active: userResponse.is_active,
      is_superuser: userResponse.is_superuser,
      created_at: userResponse.created_at,
      profile: userResponse.profile,
      preferred_language: userResponse.preferred_language ?? undefined,
    };
  },
};

export const graphStoreAPI = createBackendStoreAPI('/graph-stores');
export const retrievalStoreAPI = createBackendStoreAPI('/retrieval-stores');

export const tenantAPI = {
  list: async (params = {}): Promise<TenantListResponse> => {
    return await hostControlClient.get('/tenants/', { params });
  },
  create: async (data: TenantCreate): Promise<Tenant> => {
    return await hostControlClient.post('/tenants/', data);
  },
  update: async (id: string, data: TenantUpdate): Promise<Tenant> => {
    return await hostControlClient.put(`/tenants/${id}`, data);
  },
  delete: async (id: string): Promise<void> => {
    await hostControlClient.delete(`/tenants/${id}`);
  },
  addMember: async (tenantId: string, userId: string, role: string): Promise<void> => {
    await hostControlClient.post(`/tenants/${tenantId}/members`, { user_id: userId, role });
  },
  removeMember: async (tenantId: string, userId: string): Promise<void> => {
    await hostControlClient.delete(`/tenants/${tenantId}/members/${userId}`);
  },
  listMembers: async (tenantId: string): Promise<UserTenant[]> => {
    const response = await hostControlClient.get<TenantMembersApiResponse>(`/tenants/${tenantId}/members`);
    return Array.isArray(response) ? response : (response.members ?? []);
  },
  get: async (id: string): Promise<Tenant> => {
    return await hostControlClient.get(`/tenants/${id}`);
  },
  getStats: async (id: string): Promise<unknown> => {
    return await hostControlClient.get(`/tenants/${id}/stats`);
  },
  getAnalytics: async (id: string): Promise<unknown> => {
    return await hostControlClient.get(`/tenants/${id}/analytics`);
  },
};

export const projectAPI = {
  list: async (tenantId: string, params = {}): Promise<ProjectListResponse> => {
    return await hostControlClient.get('/projects/', { params: { ...params, tenant_id: tenantId } });
  },
  create: async (tenantId: string, data: ProjectCreate): Promise<Project> => {
    return await hostControlClient.post('/projects/', { ...data, tenant_id: tenantId });
  },
  update: async (_tenantId: string, projectId: string, data: ProjectUpdate): Promise<Project> => {
    return await hostControlClient.put(`/projects/${projectId}`, data);
  },
  delete: async (_tenantId: string, projectId: string): Promise<void> => {
    await hostControlClient.delete(`/projects/${projectId}`);
  },
  get: async (tenantId: string, projectId: string): Promise<Project> => {
    return await hostControlClient.get(`/projects/${projectId}`, { params: { tenant_id: tenantId } });
  },
  getStats: async (projectId: string): Promise<unknown> => {
    return await hostControlClient.get(`/projects/${projectId}/stats`);
  },
};



export const providerAPI = {
  list: async (
    params: { include_inactive?: boolean | undefined; provider_type?: string | undefined } = {}
  ): Promise<ProviderConfig[]> => {
    return await api.get('/llm-providers/', { params });
  },
  get: async (id: string): Promise<ProviderConfig> => {
    return await api.get(`/llm-providers/${id}`);
  },
  listTypes: async (): Promise<ProviderTypeDescriptor[]> => {
    return await api.get('/llm-providers/types');
  },
  create: async (data: ProviderCreate): Promise<ProviderConfig> => {
    return await api.post('/llm-providers/', data);
  },
  update: async (id: string, data: ProviderUpdate): Promise<ProviderConfig> => {
    return await api.put(`/llm-providers/${id}`, data);
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/llm-providers/${id}`);
  },
  checkHealth: async (id: string): Promise<ProviderHealth> => {
    return await api.post(`/llm-providers/${id}/health-check`);
  },
  testConnection: async (data: ProviderConnectionProbe): Promise<ProviderHealth> => {
    return await api.post('/llm-providers/test-connection', data);
  },
  getUsage: async (
    id: string,
    params: {
      start_date?: string | undefined;
      end_date?: string | undefined;
      tenant_id?: string | undefined;
    } = {}
  ): Promise<ProviderUsageStats> => {
    return await api.get<ProviderUsageStats>(`/llm-providers/${id}/usage`, { params });
  },
  listTenantAssignments: async (
    tenantId: string,
    operationType?: 'llm' | 'embedding' | 'rerank'
  ): Promise<TenantProviderAssignment[]> => {
    return await api.get(`/llm-providers/tenants/${tenantId}/assignments`, {
      params: { operation_type: operationType },
    });
  },
  assignToTenant: async (
    id: string,
    tenantId: string,
    priority: number = 0,
    operationType: 'llm' | 'embedding' | 'rerank' = 'llm'
  ): Promise<unknown> => {
    return await api.post(`/llm-providers/tenants/${tenantId}/providers/${id}`, null, {
      params: { priority, operation_type: operationType },
    });
  },
  unassignFromTenant: async (
    id: string,
    tenantId: string,
    operationType: 'llm' | 'embedding' | 'rerank' = 'llm'
  ): Promise<void> => {
    await api.delete(`/llm-providers/tenants/${tenantId}/providers/${id}`, {
      params: { operation_type: operationType },
    });
  },
  getTenantProvider: async (
    tenantId: string,
    operationType: 'llm' | 'embedding' | 'rerank' = 'llm'
  ): Promise<ProviderConfig> => {
    return await api.get(`/llm-providers/tenants/${tenantId}/provider`, {
      params: { operation_type: operationType },
    });
  },
  // System-wide resilience status
  getSystemStatus: async (): Promise<SystemResilienceStatus> => {
    return await api.get('/llm-providers/system/status');
  },
  // Reset circuit breaker for a provider type
  resetCircuitBreaker: async (
    providerType: string
  ): Promise<{ message: string; new_state: unknown }> => {
    return await api.post(`/llm-providers/system/reset-circuit-breaker/${providerType}`);
  },
  getModelGuidance: async (
    providerType: string
  ): Promise<{
    provider_type: string;
    roles: Array<{
      role: 'primary' | 'fast' | 'embedding' | 'rerank' | 'voice';
      purpose_code: string;
      default_model: string | null;
      available: boolean;
      reason: string;
    }>;
    profiles: Array<{ id: string; roles: Record<string, { supported: boolean; reason: string }> }>;
  }> => {
    return await api.get(`/llm-providers/models/${providerType}/guidance`);
  },
  listModels: async (
    providerType: string
  ): Promise<{
    provider_type: string;
    models: {
      chat: string[];
      embedding: string[];
      rerank: string[];
    };
    source?: string;
  }> => {
    return await api.get(`/llm-providers/models/${providerType}`);
  },
  getProviderAutoConfig: async (provider: ProviderType): Promise<ProviderAutoConfig> =>
    api.get(`/llm-providers/models/auto-config/${provider}`),
  getModelCatalog: async (
    provider?: string,
    includeDeprecated: boolean = false,
    filters?: { capability?: string; modality?: string }
  ): Promise<{ total: number; models: ModelCatalogEntry[] }> => {
    return await api.get('/llm-providers/models/catalog', {
      params: { provider, include_deprecated: includeDeprecated, ...filters },
    });
  },
  searchModelCatalog: async (
    query: string,
    provider?: string,
    limit: number = 20,
    filters?: { capability?: string; modality?: string }
  ): Promise<{ query: string; total: number; models: ModelCatalogEntry[] }> => {
    return await api.get('/llm-providers/models/catalog/search', {
      params: { q: query, provider, limit, ...filters },
    });
  },
  detectEnvKeys: async (): Promise<{
    detected_providers: Record<string, DetectedEnvironmentProvider>;
  }> => {
    return await api.get('/llm-providers/env-detection');
  },
};

export default api;
