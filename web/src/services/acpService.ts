import { httpClient } from '@/services/client/httpClient';

import type {
  ACPExternalSession,
  ExternalACPPromptResult,
  ExternalACPSessionResult,
  TenantACPStatus,
  TenantACPTestRequest,
  TenantACPTestResponse,
  TenantExternalACPAgent,
  TenantACPSessionRequest,
  UpsertTenantACPAgentRequest,
} from '@/types/acp';

const BASE_URL = '/acp/tenants';

export const acpService = {
  getStatus(tenantId: string): Promise<TenantACPStatus> {
    return httpClient.get<TenantACPStatus>(`${BASE_URL}/${tenantId}/status`);
  },

  listAgents(tenantId: string): Promise<TenantExternalACPAgent[]> {
    return httpClient.get<TenantExternalACPAgent[]>(`${BASE_URL}/${tenantId}/external-agents`);
  },

  createAgent(
    tenantId: string,
    data: UpsertTenantACPAgentRequest & { agentKey: string }
  ): Promise<TenantExternalACPAgent> {
    return httpClient.post<TenantExternalACPAgent>(`${BASE_URL}/${tenantId}/external-agents`, data);
  },

  updateAgent(
    tenantId: string,
    agentKey: string,
    data: UpsertTenantACPAgentRequest
  ): Promise<TenantExternalACPAgent> {
    return httpClient.put<TenantExternalACPAgent>(
      `${BASE_URL}/${tenantId}/external-agents/${agentKey}`,
      data
    );
  },

  deleteAgent(tenantId: string, agentKey: string): Promise<{ ok: boolean }> {
    return httpClient.delete<{ ok: boolean }>(
      `${BASE_URL}/${tenantId}/external-agents/${agentKey}`
    );
  },

  testAgent(
    tenantId: string,
    agentKey: string,
    data: TenantACPTestRequest
  ): Promise<TenantACPTestResponse> {
    return httpClient.post<TenantACPTestResponse>(
      `${BASE_URL}/${tenantId}/external-agents/${agentKey}/test`,
      data
    );
  },

  listSessions(tenantId: string): Promise<ACPExternalSession[]> {
    return httpClient.get<ACPExternalSession[]>(`${BASE_URL}/${tenantId}/sessions`);
  },

  createSession(
    tenantId: string,
    agentKey: string,
    data: TenantACPSessionRequest
  ): Promise<ExternalACPSessionResult> {
    return httpClient.post<ExternalACPSessionResult>(
      `${BASE_URL}/${tenantId}/external-agents/${agentKey}/sessions`,
      data
    );
  },

  promptSession(
    tenantId: string,
    agentKey: string,
    sessionId: string,
    prompt: Array<Record<string, unknown>>,
    messageId?: string
  ): Promise<ExternalACPPromptResult> {
    return httpClient.post<ExternalACPPromptResult>(
      `${BASE_URL}/${tenantId}/external-agents/${agentKey}/sessions/${sessionId}/prompt`,
      { prompt, messageId }
    );
  },

  cancelSession(tenantId: string, agentKey: string, sessionId: string): Promise<{ ok: boolean }> {
    return httpClient.post<{ ok: boolean }>(
      `${BASE_URL}/${tenantId}/external-agents/${agentKey}/sessions/${sessionId}/cancel`
    );
  },

  closeSession(tenantId: string, agentKey: string, sessionId: string): Promise<{ ok: boolean }> {
    return httpClient.delete<{ ok: boolean }>(
      `${BASE_URL}/${tenantId}/external-agents/${agentKey}/sessions/${sessionId}`
    );
  },
};
