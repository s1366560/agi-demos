import { hostControlClient } from './client/hostControlClient';

const BASE_URL = '/tenants';

export interface RegistryRequest {
  name: string;
  registry_type: string;
  url: string;
  username?: string | null;
  password?: string | null;
  is_default: boolean;
}

export interface RegistryResponse {
  id: string;
  tenant_id: string;
  name: string;
  type: 'docker' | 'gcr' | 'ecr' | 'acr' | 'harbor' | 'custom';
  url: string;
  username?: string | null;
  is_default: boolean;
  status: 'connected' | 'disconnected' | 'error' | 'checking';
  last_checked?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface TestConnectionResponse {
  success: boolean;
  message: string;
}

export const registryService = {
  list: (tenantId: string) =>
    hostControlClient.get<RegistryResponse[]>(`${BASE_URL}/${tenantId}/registries`),

  create: (tenantId: string, data: RegistryRequest) =>
    hostControlClient.post<RegistryResponse>(`${BASE_URL}/${tenantId}/registries`, data),

  update: (tenantId: string, registryId: string, data: RegistryRequest) =>
    hostControlClient.put<RegistryResponse>(`${BASE_URL}/${tenantId}/registries/${registryId}`, data),

  remove: (tenantId: string, registryId: string) =>
    hostControlClient.delete(`${BASE_URL}/${tenantId}/registries/${registryId}`),

  testConnection: (tenantId: string, registryId: string) =>
    hostControlClient.post<TestConnectionResponse>(
      `${BASE_URL}/${tenantId}/registries/${registryId}/test`
    ),
};
