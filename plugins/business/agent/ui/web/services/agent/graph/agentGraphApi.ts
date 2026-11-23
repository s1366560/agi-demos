import { httpClient } from '@/services/client/httpClient';

export interface AgentGraphApiNode {
  node_id: string;
  agent_definition_id: string;
  label: string;
  instruction: string;
  config: Record<string, unknown>;
  is_entry: boolean;
  is_terminal: boolean;
}

export interface AgentGraphApiEdge {
  source_node_id: string;
  target_node_id: string;
  condition: string;
}

export interface AgentGraphApiResponse {
  id: string;
  tenant_id: string;
  project_id: string;
  name: string;
  description: string;
  pattern: string;
  nodes: AgentGraphApiNode[];
  edges: AgentGraphApiEdge[];
  shared_context_keys: string[];
  max_total_steps: number;
  metadata: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at?: string | null | undefined;
}

export const agentGraphApi = {
  getGraph: async (graphId: string): Promise<AgentGraphApiResponse> => {
    return await httpClient.get<AgentGraphApiResponse>(`/agent/graphs/${graphId}`);
  },
};
