import { httpClient } from './client/httpClient';

import type {
  SubAgentRunDTO,
  SubAgentRunListDTO,
  TenantActiveRunCountDTO,
  TenantSubAgentRunListDTO,
  TraceChainDTO,
  DescendantTreeDTO,
  ActiveRunCountDTO,
} from '../types/multiAgent';

const BASE_URL = '/agent/trace/runs';

export interface ListRunsParams {
  status?: string | undefined;
  trace_id?: string | undefined;
}

export const traceAPI = {
  listRuns: async (
    conversationId: string,
    params: ListRunsParams = {}
  ): Promise<SubAgentRunListDTO> => {
    return await httpClient.get<SubAgentRunListDTO>(
      `${BASE_URL}/${encodeURIComponent(conversationId)}`,
      { params }
    );
  },

  listTenantRuns: async (
    tenantId: string,
    params: { status?: string | undefined; limit?: number | undefined } = {}
  ): Promise<TenantSubAgentRunListDTO> => {
    return await httpClient.get<TenantSubAgentRunListDTO>(
      `${BASE_URL}/tenant/${encodeURIComponent(tenantId)}`,
      { params }
    );
  },

  getRun: async (conversationId: string, runId: string): Promise<SubAgentRunDTO> => {
    return await httpClient.get<SubAgentRunDTO>(
      `${BASE_URL}/${encodeURIComponent(conversationId)}/${encodeURIComponent(runId)}`
    );
  },

  getTraceChain: async (conversationId: string, traceId: string): Promise<TraceChainDTO> => {
    return await httpClient.get<TraceChainDTO>(
      `${BASE_URL}/${encodeURIComponent(conversationId)}/trace/${encodeURIComponent(traceId)}`
    );
  },

  getDescendants: async (conversationId: string, runId: string): Promise<DescendantTreeDTO> => {
    return await httpClient.get<DescendantTreeDTO>(
      `${BASE_URL}/${encodeURIComponent(conversationId)}/${encodeURIComponent(runId)}/descendants`
    );
  },

  getActiveRunCount: async (conversationId?: string): Promise<ActiveRunCountDTO> => {
    return await httpClient.get<ActiveRunCountDTO>(`${BASE_URL}/active/count`, {
      params: conversationId ? { conversation_id: conversationId } : undefined,
    });
  },

  getTenantActiveRunCount: async (tenantId: string): Promise<TenantActiveRunCountDTO> => {
    return await httpClient.get<TenantActiveRunCountDTO>(
      `${BASE_URL}/tenant/${encodeURIComponent(tenantId)}/active/count`
    );
  },
};

export default traceAPI;
