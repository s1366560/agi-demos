import { httpClient } from './client/httpClient';

const BASE_URL = '/tenants';

export interface GenePolicyRequest {
  policy_key: string;
  policy_value: Record<string, unknown>;
  description?: string | null;
}

export interface GenePolicyResponse {
  id: string;
  tenant_id: string;
  policy_key: string;
  policy_value: Record<string, unknown>;
  description: string | null;
  created_at: string;
  updated_at: string | null;
}

export const genePolicyService = {
  list: (tenantId: string) =>
    httpClient.get<GenePolicyResponse[]>(`${BASE_URL}/${tenantId}/gene-policies`),

  upsert: (tenantId: string, policyKey: string, data: GenePolicyRequest) =>
    httpClient.put<GenePolicyResponse>(`${BASE_URL}/${tenantId}/gene-policies/${policyKey}`, data),

  remove: (tenantId: string, policyKey: string) =>
    httpClient.delete(`${BASE_URL}/${tenantId}/gene-policies/${policyKey}`),
};
