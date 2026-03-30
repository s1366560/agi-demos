/// <reference types="vite/client" />
import { httpClient } from './client/httpClient';

import type {
  ProjectCreate,
  ProjectUpdate,
  MemoryCreate,
  MemoryUpdate,
  MemoryQuery,
  TenantCreate,
  TenantUpdate,
  ProviderCreate,
  ProviderUpdate,
  User,
  Project,
  ProjectListResponse,
  Tenant,
  TenantListResponse,
  UserTenant,
  Memory,
  MemoryListResponse,
  MemorySearchResponse,
  GraphData,
  Entity,
  Relationship,
  UserProfile,
  TaskStats,
  QueueDepth,
  ProviderConfig,
  RecentTask,
  StatusBreakdown,
  SchemaEntityType,
  SchemaEdgeType,
  EdgeMapping,
  SystemResilienceStatus,
  ProviderUsageStats,
  ModelCatalogEntry,
} from '../types/memory';

// Use centralized HTTP client instead of creating a new axios instance
const api = httpClient;

// Token response from auth endpoint
interface TokenResponse {
  access_token: string;
  token_type: string;
  must_change_password?: boolean;
}

// Auth API types
interface LoginResponse {
  token: string;
  user: User;
  must_change_password: boolean;
}

// Backend user response (uses user_id instead of id)
interface BackendUserResponse {
  user_id: string;
  email: string;
  name: string;
  roles: string[];
  is_active: boolean;
  created_at: string;
  profile?: UserProfile;
}

// Share response types
interface ShareListResponse {
  shares: unknown[];
}

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

export const authAPI = {
  login: async (email: string, password: string): Promise<LoginResponse> => {
    const formData = new FormData();
    formData.append('username', email);
    formData.append('password', password);
    const tokenResponse = await api.post<TokenResponse>('/auth/token', formData, {
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
    });
    // Backend returns { access_token, token_type, must_change_password } - user is fetched separately
    const token = tokenResponse.access_token;
    const must_change_password = tokenResponse.must_change_password;

    // Fetch user details
    const userResponse = await api.get<BackendUserResponse>('/auth/me', {
      headers: { Authorization: `Bearer ${token}` },
    });

    // Map backend response (user_id) to frontend format (id)
    const user: User = {
      id: userResponse.user_id,
      email: userResponse.email,
      name: userResponse.name,
      roles: userResponse.roles,
      is_active: userResponse.is_active,
      created_at: userResponse.created_at,
      profile: userResponse.profile,
      must_change_password,
    };

    return { token, user, must_change_password: must_change_password ?? false };
  },
  verifyToken: async (_token: string): Promise<User> => {
    const userResponse = await api.get<BackendUserResponse>('/auth/me');
    // Map backend response (user_id) to frontend format (id)
    return {
      id: userResponse.user_id,
      email: userResponse.email,
      name: userResponse.name,
      roles: userResponse.roles,
      is_active: userResponse.is_active,
      created_at: userResponse.created_at,
      profile: userResponse.profile,
    };
  },
  updateProfile: async (data: Partial<UserProfile>): Promise<User> => {
    return await api.put('/users/me', data);
  },
  changePassword: async (
    oldPassword: string,
    newPassword: string
  ): Promise<{ success: boolean; message: string }> => {
    return await api.post('/auth/force-change-password', {
      old_password: oldPassword,
      new_password: newPassword,
    });
  },
};

export const tenantAPI = {
  list: async (params = {}): Promise<TenantListResponse> => {
    return await api.get('/tenants/', { params });
  },
  create: async (data: TenantCreate): Promise<Tenant> => {
    return await api.post('/tenants/', data);
  },
  update: async (id: string, data: TenantUpdate): Promise<Tenant> => {
    return await api.put(`/tenants/${id}`, data);
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/tenants/${id}`);
  },
  addMember: async (tenantId: string, userId: string, role: string): Promise<void> => {
    await api.post(`/tenants/${tenantId}/members`, { user_id: userId, role });
  },
  removeMember: async (tenantId: string, userId: string): Promise<void> => {
    await api.delete(`/tenants/${tenantId}/members/${userId}`);
  },
  listMembers: async (tenantId: string): Promise<UserTenant[]> => {
    return await api.get<UserTenant[]>(`/tenants/${tenantId}/members`);
  },
  get: async (id: string): Promise<Tenant> => {
    return await api.get(`/tenants/${id}`);
  },
  getStats: async (id: string): Promise<unknown> => {
    return await api.get(`/tenants/${id}/stats`);
  },
  getAnalytics: async (id: string): Promise<unknown> => {
    return await api.get(`/tenants/${id}/analytics`);
  },
};

export const projectAPI = {
  list: async (tenantId: string, params = {}): Promise<ProjectListResponse> => {
    return await api.get('/projects/', { params: { ...params, tenant_id: tenantId } });
  },
  create: async (tenantId: string, data: ProjectCreate): Promise<Project> => {
    return await api.post('/projects/', { ...data, tenant_id: tenantId });
  },
  update: async (_tenantId: string, projectId: string, data: ProjectUpdate): Promise<Project> => {
    return await api.put(`/projects/${projectId}`, data);
  },
  delete: async (_tenantId: string, projectId: string): Promise<void> => {
    await api.delete(`/projects/${projectId}`);
  },
  get: async (_tenantId: string, projectId: string): Promise<Project> => {
    return await api.get(`/projects/${projectId}`);
  },
  getStats: async (projectId: string): Promise<unknown> => {
    return await api.get(`/projects/${projectId}/stats`);
  },
};

export const memoryAPI = {
  list: async (projectId: string, params = {}): Promise<MemoryListResponse> => {
    return await api.get('/memories/', { params: { ...params, project_id: projectId } });
  },
  create: async (projectId: string, data: MemoryCreate): Promise<Memory> => {
    return await api.post('/memories/', { ...data, project_id: projectId });
  },
  update: async (_projectId: string, memoryId: string, data: MemoryUpdate): Promise<Memory> => {
    return await api.patch(`/memories/${memoryId}`, data);
  },
  delete: async (_projectId: string, memoryId: string): Promise<void> => {
    await api.delete(`/memories/${memoryId}`);
  },
  search: async (projectId: string, query: MemoryQuery): Promise<MemorySearchResponse> => {
    return await api.post('/memory/search', { ...query, project_id: projectId });
  },
  get: async (_projectId: string, memoryId: string): Promise<Memory> => {
    return await api.get(`/memories/${memoryId}`);
  },
  getGraphData: async (projectId: string, options = {}): Promise<GraphData> => {
    return await api.get('/memory/graph', { params: { ...options, project_id: projectId } });
  },
  extractEntities: async (projectId: string, text: string): Promise<Entity[]> => {
    return await api.post('/memories/extract-entities', { text, project_id: projectId });
  },
  extractRelationships: async (projectId: string, text: string): Promise<Relationship[]> => {
    return await api.post('/memories/extract-relationships', { text, project_id: projectId });
  },
  listShares: async (memoryId: string): Promise<unknown[]> => {
    const response = await api.get<ShareListResponse>(`/memories/${memoryId}/shares`);
    return response.shares;
  },
  createShare: async (
    memoryId: string,
    permissions: { view: boolean; edit: boolean },
    expiresAt?: string
  ): Promise<unknown> => {
    return await api.post(`/memories/${memoryId}/shares`, {
      permissions,
      expires_at: expiresAt,
    });
  },
  deleteShare: async (memoryId: string, shareId: string): Promise<void> => {
    await api.delete(`/memories/${memoryId}/shares/${shareId}`);
  },
  reprocess: async (_projectId: string, memoryId: string): Promise<Memory> => {
    return await api.post(`/memories/${memoryId}/reprocess`);
  },
};

export const schemaAPI = {
  // Entity Types
  listEntityTypes: async (projectId: string): Promise<SchemaEntityType[]> => {
    return await api.get(`/projects/${projectId}/schema/entities`);
  },
  createEntityType: async (projectId: string, data: unknown): Promise<unknown> => {
    return await api.post(`/projects/${projectId}/schema/entities`, data);
  },
  updateEntityType: async (
    projectId: string,
    entityId: string,
    data: unknown
  ): Promise<unknown> => {
    return await api.put(`/projects/${projectId}/schema/entities/${entityId}`, data);
  },
  deleteEntityType: async (projectId: string, entityId: string): Promise<void> => {
    await api.delete(`/projects/${projectId}/schema/entities/${entityId}`);
  },

  // Edge Types
  listEdgeTypes: async (projectId: string): Promise<SchemaEdgeType[]> => {
    return await api.get(`/projects/${projectId}/schema/edges`);
  },
  createEdgeType: async (projectId: string, data: unknown): Promise<unknown> => {
    return await api.post(`/projects/${projectId}/schema/edges`, data);
  },
  updateEdgeType: async (projectId: string, edgeId: string, data: unknown): Promise<unknown> => {
    return await api.put(`/projects/${projectId}/schema/edges/${edgeId}`, data);
  },
  deleteEdgeType: async (projectId: string, edgeId: string): Promise<void> => {
    await api.delete(`/projects/${projectId}/schema/edges/${edgeId}`);
  },

  // Edge Mappings
  listEdgeMaps: async (projectId: string): Promise<EdgeMapping[]> => {
    return await api.get(`/projects/${projectId}/schema/mappings`);
  },
  createEdgeMap: async (projectId: string, data: unknown): Promise<unknown> => {
    return await api.post(`/projects/${projectId}/schema/mappings`, data);
  },
  deleteEdgeMap: async (projectId: string, mapId: string): Promise<void> => {
    await api.delete(`/projects/${projectId}/schema/mappings/${mapId}`);
  },
};

export const taskAPI = {
  getStats: async (): Promise<TaskStats> => {
    return await api.get('/tasks/stats');
  },
  getQueueDepth: async (): Promise<QueueDepth> => {
    return await api.get('/tasks/queue-depth');
  },
  getRecentTasks: async (
    params: {
      limit?: number | undefined;
      offset?: number | undefined;
      status?: string | undefined;
      task_type?: string | undefined;
      search?: string | undefined;
    } = {}
  ): Promise<RecentTask[]> => {
    return await api.get('/tasks/recent', { params });
  },
  getStatusBreakdown: async (): Promise<StatusBreakdown> => {
    return await api.get('/tasks/status-breakdown');
  },
  retryTask: async (taskId: string): Promise<unknown> => {
    return await api.post(`/tasks/${taskId}/retry`);
  },
  stopTask: async (taskId: string): Promise<unknown> => {
    return await api.post(`/tasks/${taskId}/stop`);
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
  create: async (data: ProviderCreate): Promise<ProviderConfig> => {
    return await api.post('/llm-providers/', data);
  },
  update: async (id: string, data: ProviderUpdate): Promise<ProviderConfig> => {
    return await api.put(`/llm-providers/${id}`, data);
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/llm-providers/${id}`);
  },
  checkHealth: async (id: string): Promise<unknown> => {
    return await api.post(`/llm-providers/${id}/health-check`);
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
  listModels: async (
    providerType: string
  ): Promise<{
    provider_type: string;
    models: {
      chat: string[];
      embedding: string[];
      rerank: string[];
    };
  }> => {
    return await api.get(`/llm-providers/models/${providerType}`);
  },
  getModelCatalog: async (
    provider?: string,
    includeDeprecated: boolean = false
  ): Promise<{ total: number; models: ModelCatalogEntry[] }> => {
    return await api.get('/llm-providers/models/catalog', {
      params: { provider, include_deprecated: includeDeprecated },
    });
  },
  searchModelCatalog: async (
    query: string,
    provider?: string,
    limit: number = 20
  ): Promise<{ query: string; total: number; models: ModelCatalogEntry[] }> => {
    return await api.get('/llm-providers/models/catalog/search', {
      params: { q: query, provider, limit },
    });
  },
  detectEnvKeys: async (): Promise<{
    detected_providers: Record<
      string,
      {
        provider_type: string;
        api_key: string | null;
        base_url: string | null;
        llm_model: string | null;
        llm_small_model: string | null;
        embedding_model: string | null;
        reranker_model: string | null;
      }
    >;
  }> => {
    return await api.get('/llm-providers/env-detection');
  },
};

export default api;
