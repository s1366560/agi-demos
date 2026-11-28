import type { GraphData } from '../web/services/graphService';
import { graphService as maintenance } from './optimize';

export const graphService = {
  ...maintenance,
  advancedSearch: (parameters: Record<string, unknown>) => search('advanced', parameters),
  searchByGraphTraversal: (parameters: Record<string, unknown>) => search('graph-traversal', parameters),
  searchByCommunity: (parameters: Record<string, unknown>) => search('community', parameters),
  searchTemporal: (parameters: Record<string, unknown>) => search('temporal', parameters),
  searchWithFacets: (parameters: Record<string, unknown>) => search('faceted', parameters),
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


function search(mode: string, parameters: Record<string, unknown>) {
  return window.memstack.invoke('search-project', { mode, parameters });
}
