import { httpClient } from './client/httpClient';

const BASE_URL = '/deploys';

export interface DeployCreate {
  instance_id: string;
  image_version?: string;
  config_snapshot?: Record<string, unknown>;
  triggered_by?: string | null;
  description?: string | null;
}

export interface DeployResponse {
  id: string;
  instance_id: string;
  image_version: string;
  config_snapshot: Record<string, unknown>;
  status: string;
  triggered_by: string | null;
  description: string | null;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
  created_at: string;
}

export interface DeployListResponse {
  deployments: DeployResponse[];
  total: number;
  page: number;
  page_size: number;
}

export const deployService = {
  list: (params?: { page?: number; page_size?: number; instance_id?: string }) =>
    httpClient.get<DeployListResponse>(BASE_URL, { params }),

  create: (data: DeployCreate) => httpClient.post<DeployResponse>(BASE_URL, data),

  getById: (id: string) => httpClient.get<DeployResponse>(`${BASE_URL}/${id}`),

  markSuccess: (id: string) => httpClient.post<DeployResponse>(`${BASE_URL}/${id}/success`),

  markFailed: (id: string, message?: string) =>
    httpClient.post<DeployResponse>(`${BASE_URL}/${id}/failed`, { message }),

  cancel: (id: string) => httpClient.post<DeployResponse>(`${BASE_URL}/${id}/cancel`),

  getLatestForInstance: (instanceId: string) =>
    httpClient.get<DeployResponse>(`${BASE_URL}/instances/${instanceId}/latest`),
};
