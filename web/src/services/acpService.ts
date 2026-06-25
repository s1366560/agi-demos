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

type TenantExternalACPAgentListResponse =
  | TenantExternalACPAgent[]
  | {
      agents?: TenantExternalACPAgent[] | undefined;
      items?: TenantExternalACPAgent[] | undefined;
      externalAgents?: TenantExternalACPAgent[] | undefined;
    };

function normalizeAgentList(
  response: TenantExternalACPAgentListResponse
): TenantExternalACPAgent[] {
  if (Array.isArray(response)) {
    return response;
  }
  if (Array.isArray(response.agents)) {
    return response.agents;
  }
  if (Array.isArray(response.items)) {
    return response.items;
  }
  if (Array.isArray(response.externalAgents)) {
    return response.externalAgents;
  }
  return [];
}

export const acpService = {
  getStatus(tenantId: string): Promise<TenantACPStatus> {
    return httpClient.get<TenantACPStatus>(`${BASE_URL}/${tenantId}/status`);
  },

  async listAgents(tenantId: string): Promise<TenantExternalACPAgent[]> {
    const response = await httpClient.get<TenantExternalACPAgentListResponse>(
      `${BASE_URL}/${tenantId}/external-agents`
    );
    return normalizeAgentList(response);
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
