import { httpClient } from './client/httpClient';

const BASE_URL = '/clusters';

export interface ClusterCreate {
  name: string;
  tenant_id?: string; // Optional - backend derives from auth context
  compute_provider?: string;
  proxy_endpoint?: string;
  provider_config?: Record<string, unknown>;
  credentials_encrypted?: string;
}

export interface ClusterUpdate {
  name?: string;
  compute_provider?: string;
  proxy_endpoint?: string;
  provider_config?: Record<string, unknown>;
  credentials_encrypted?: string;
}

export interface ClusterResponse {
  id: string;
  name: string;
  tenant_id: string;
  compute_provider: string;
  proxy_endpoint: string | null;
  provider_config: Record<string, unknown>;
  credentials_encrypted: string | null;
  status: string;
  health_status: string | null;
  last_health_check: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface ClusterListResponse {
  clusters: ClusterResponse[];
  total: number;
  page: number;
  page_size: number;
}

export interface ClusterHealthResponse {
  status: string;
  node_count: number;
  cpu_usage: number | null;
  memory_usage: number | null;
  checked_at: string;
}

export const clusterService = {
  list: (params?: { page?: number; page_size?: number }) =>
    httpClient.get<ClusterListResponse>(BASE_URL, { params }),

  create: (data: ClusterCreate) => httpClient.post<ClusterResponse>(BASE_URL, data),

  getById: (id: string) => httpClient.get<ClusterResponse>(`${BASE_URL}/${id}`),

  update: (id: string, data: ClusterUpdate) =>
    httpClient.put<ClusterResponse>(`${BASE_URL}/${id}`, data),

  delete: (id: string) => httpClient.delete(`${BASE_URL}/${id}`),

  getHealth: (id: string) => httpClient.get<ClusterHealthResponse>(`${BASE_URL}/${id}/health`),
};
