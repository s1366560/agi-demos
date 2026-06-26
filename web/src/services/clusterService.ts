import { httpClient } from './client/httpClient';

import type {
  ACPRunnerPool,
  ACPRunnerTokenResponse,
  UpsertACPRunnerPoolRequest,
} from '@/types/acp';

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
  checked_at: string | null;
}

export const clusterService = {
  list: (params?: { page?: number; page_size?: number }) =>
    httpClient.get<ClusterListResponse>(`${BASE_URL}/`, { params }),

  create: (data: ClusterCreate) => httpClient.post<ClusterResponse>(`${BASE_URL}/`, data),

  getById: (id: string) => httpClient.get<ClusterResponse>(`${BASE_URL}/${id}`),

  update: (id: string, data: ClusterUpdate) =>
    httpClient.put<ClusterResponse>(`${BASE_URL}/${id}`, data),

  delete: (id: string) => httpClient.delete(`${BASE_URL}/${id}`),

  getHealth: (id: string) => httpClient.get<ClusterHealthResponse>(`${BASE_URL}/${id}/health`),

  listAcpRunnerPools: (clusterId: string) =>
    httpClient.get<ACPRunnerPool[]>(`${BASE_URL}/${clusterId}/acp-runner-pools`),

  createAcpRunnerPool: (
    clusterId: string,
    data: UpsertACPRunnerPoolRequest & { poolKey: string }
  ) => httpClient.post<ACPRunnerPool>(`${BASE_URL}/${clusterId}/acp-runner-pools`, data),

  updateAcpRunnerPool: (
    clusterId: string,
    poolKey: string,
    data: UpsertACPRunnerPoolRequest
  ) => httpClient.put<ACPRunnerPool>(`${BASE_URL}/${clusterId}/acp-runner-pools/${poolKey}`, data),

  createAcpRunnerToken: (
    clusterId: string,
    poolKey: string,
    data?: { name?: string; expiresInHours?: number }
  ) =>
    httpClient.post<ACPRunnerTokenResponse>(
      `${BASE_URL}/${clusterId}/acp-runner-pools/${poolKey}/registration-token`,
      data ?? {}
    ),
};
