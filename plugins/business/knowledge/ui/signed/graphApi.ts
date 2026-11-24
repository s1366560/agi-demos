import type { GraphData } from '../web/services/graphService';
import { graphService as maintenance } from './optimize';

export const graphService = {
  ...maintenance,
  getGraphData({ limit = 100 }: { limit?: number }) {
    return window.memstack.invoke('read-graph', { limit }) as Promise<GraphData>;
  },
  getSubgraph({ node_uuids, include_neighbors = false, limit = 100 }: {
    node_uuids: string[];
    include_neighbors?: boolean;
    limit?: number;
  }) {
    return window.memstack.invoke('read-subgraph', { node_uuids, include_neighbors, limit }) as Promise<GraphData>;
  },
};
