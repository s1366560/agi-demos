import { httpClient } from './client/httpClient';

import type {
  SubAgentRunDTO,
  SubAgentRunListDTO,
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
};

export default traceAPI;
