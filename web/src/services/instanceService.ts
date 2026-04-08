import { httpClient } from './client/httpClient';

const BASE_URL = '/instances';

export interface InstanceCreate {
  name: string;
  slug: string;
  tenant_id: string;
  cluster_id?: string | null;
  namespace?: string | null;
  image_version?: string;
  replicas?: number;
  cpu_request?: string;
  cpu_limit?: string;
  mem_request?: string;
  mem_limit?: string;
  service_type?: string;
  ingress_domain?: string | null;
  env_vars?: Record<string, unknown>;
  quota_cpu?: string | null;
  quota_memory?: string | null;
  quota_max_pods?: number | null;
  storage_class?: string | null;
  storage_size?: string | null;
  advanced_config?: Record<string, unknown>;
  llm_providers?: Record<string, unknown>;
  compute_provider?: string | null;
  runtime?: string;
  workspace_id?: string | null;
  hex_position_q?: number | null;
  hex_position_r?: number | null;
  agent_display_name?: string | null;
  agent_label?: string | null;
  theme_color?: string | null;
}

export interface InstanceUpdate {
  name?: string;
  slug?: string;
  description?: string;
  tenant_id?: string;
  cluster_id?: string | null;
  namespace?: string | null;
  image_version?: string;
  replicas?: number;
  cpu_request?: string;
  cpu_limit?: string;
  mem_request?: string;
  mem_limit?: string;
  service_type?: string;
  ingress_domain?: string | null;
  env_vars?: Record<string, unknown>;
  quota_cpu?: string | null;
  quota_memory?: string | null;
  quota_max_pods?: number | null;
  storage_class?: string | null;
  storage_size?: string | null;
  advanced_config?: Record<string, unknown>;
  llm_providers?: Record<string, unknown>;
  compute_provider?: string | null;
  runtime?: string;
  workspace_id?: string | null;
  hex_position_q?: number | null;
  hex_position_r?: number | null;
  agent_display_name?: string | null;
  agent_label?: string | null;
  theme_color?: string | null;
}

export interface InstanceMemberCreate {
  instance_id: string;
  user_id: string;
  role?: string;
}

export interface InstanceResponse {
  id: string;
  name: string;
  slug: string;
  tenant_id: string;
  cluster_id: string | null;
  namespace: string | null;
  image_version: string;
  replicas: number;
  cpu_request: string;
  cpu_limit: string;
  mem_request: string;
  mem_limit: string;
  service_type: string;
  ingress_domain: string | null;
  env_vars: Record<string, unknown>;
  quota_cpu: string | null;
  quota_memory: string | null;
  quota_max_pods: number | null;
  storage_class: string | null;
  storage_size: string | null;
  advanced_config: Record<string, unknown>;
  llm_providers: Record<string, unknown>;
  compute_provider: string | null;
  runtime: string;
  workspace_id: string | null;
  hex_position_q: number | null;
  hex_position_r: number | null;
  agent_display_name: string | null;
  agent_label: string | null;
  theme_color: string | null;
  status: string;
  health_status: string | null;
  current_revision: number | null;
  available_replicas: number | null;
  proxy_token: string | null;
  pending_config: Record<string, unknown> | null;
  created_by: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface InstanceListResponse {
  instances: InstanceResponse[];
  total: number;
  page: number;
  page_size: number;
}

export interface InstanceMemberUpdate {
  role: string;
}

export interface UserSearchResult {
  id: string;
  email: string;
  full_name: string | null;
}

export interface InstanceMemberResponse {
  id: string;
  instance_id: string;
  user_id: string;
  role: string;
  user_name: string | null;
  user_email: string | null;
  user_avatar_url: string | null;
  created_at: string;
}

export interface InstanceConfigResponse {
  env_vars: Record<string, unknown>;
  advanced_config: Record<string, unknown>;
  llm_providers: Record<string, unknown>;
}

export interface InstanceLlmConfigResponse {
  provider_id: string | null;
  model_name: string | null;
  has_api_key_override: boolean;
}

export interface InstanceLlmConfigUpdate {
  provider_id: string | null | undefined;
  model_name: string | null | undefined;
  api_key_override?: string | null | undefined;
}

export const instanceService = {
  list: (params?: { page?: number; page_size?: number; status?: string; search?: string }) =>
    httpClient.get<InstanceListResponse>(`${BASE_URL}/`, { params }),

  create: (data: InstanceCreate) => httpClient.post<InstanceResponse>(`${BASE_URL}/`, data),

  getById: (id: string) => httpClient.get<InstanceResponse>(`${BASE_URL}/${id}`),

  update: (id: string, data: InstanceUpdate) =>
    httpClient.put<InstanceResponse>(`${BASE_URL}/${id}`, data),

  delete: (id: string) => httpClient.delete(`${BASE_URL}/${id}`),

  scale: (id: string, replicas: number) =>
    httpClient.post<InstanceResponse>(`${BASE_URL}/${id}/scale`, { desired_replicas: replicas }),

  restart: (id: string) => httpClient.post<InstanceResponse>(`${BASE_URL}/${id}/restart`),

  getConfig: (id: string) => httpClient.get<InstanceConfigResponse>(`${BASE_URL}/${id}/config`),

  updateConfig: (id: string, data: InstanceConfigResponse) =>
    httpClient.put<InstanceConfigResponse>(`${BASE_URL}/${id}/config`, data),

  listMembers: (id: string) =>
    httpClient.get<InstanceMemberResponse[]>(`${BASE_URL}/${id}/members`),

  addMember: (id: string, data: InstanceMemberCreate) =>
    httpClient.post<InstanceMemberResponse>(`${BASE_URL}/${id}/members`, data),

  removeMember: (id: string, memberId: string) =>
    httpClient.delete(`${BASE_URL}/${id}/members/${memberId}`),

  updateMemberRole: (id: string, userId: string, data: InstanceMemberUpdate) =>
    httpClient.put<InstanceMemberResponse>(`${BASE_URL}/${id}/members/${userId}`, data),

  searchUsers: (id: string, query: string) =>
    httpClient.get<UserSearchResult[]>(`${BASE_URL}/${id}/members/search-users`, {
      params: { q: query },
    }),

  getLlmConfig: (id: string) =>
    httpClient.get<InstanceLlmConfigResponse>(`${BASE_URL}/${id}/llm-config`),

  updateLlmConfig: (id: string, data: InstanceLlmConfigUpdate) =>
    httpClient.put<InstanceLlmConfigResponse>(`${BASE_URL}/${id}/llm-config`, data),
};
