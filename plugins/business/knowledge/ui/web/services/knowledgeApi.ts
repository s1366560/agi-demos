import { httpClient as api } from '@/services/client/httpClient';
import { memoryCommandTransport } from './memoryCommandTransport';
import type {
  MemoryListResponse,
  MemorySearchResponse,
  MemoryQuery,
  Memory,
  GraphData,
  Entity,
  Relationship,
  SchemaEntityType,
  SchemaEdgeType,
  EdgeMapping,
} from '@/types/memory';

export const memoryAPI = {
  list: async (projectId: string, params = {}): Promise<MemoryListResponse> => {
    return await api.get('/memories/', { params: { ...params, project_id: projectId } });
  },
  create: memoryCommandTransport.create,
  update: memoryCommandTransport.update,
  delete: memoryCommandTransport.delete,
  search: async (projectId: string, query: MemoryQuery): Promise<MemorySearchResponse> => {
    return await api.post('/memory/search', { ...query, project_id: projectId });
  },
  get: async (_projectId: string, memoryId: string): Promise<Memory> => {
    return await api.get(`/memories/${memoryId}`);
  },
  getGraphData: async (projectId: string, options = {}): Promise<GraphData> => {
    return await api.get('/graph/memory/graph', { params: { ...options, project_id: projectId } });
  },
  extractEntities: async (projectId: string, text: string): Promise<Entity[]> => {
    return await api.post('/memories/extract-entities', { text, project_id: projectId });
  },
  extractRelationships: async (projectId: string, text: string): Promise<Relationship[]> => {
    return await api.post('/memories/extract-relationships', { text, project_id: projectId });
  },
  listShares: async (memoryId: string): Promise<unknown[]> => {
    const response = await api.get<{ shares: unknown[] }>(`/memories/${memoryId}/shares`);
    return response.shares;
  },
  createShare: async (
    memoryId: string,
    permissions: { view: boolean; edit: boolean },
    expiresAt?: string
  ): Promise<unknown> => {
    return await api.post(`/memories/${memoryId}/shares`, {
      permissions,
      expires_at: expiresAt,
    });
  },
  deleteShare: async (memoryId: string, shareId: string): Promise<void> => {
    await api.delete(`/memories/${memoryId}/shares/${shareId}`);
  },
  reprocess: async (_projectId: string, memoryId: string): Promise<Memory> => {
    return await api.post(`/memories/${memoryId}/reprocess`);
  },
};

export const schemaAPI = {
  // Entity Types
  listEntityTypes: async (projectId: string): Promise<SchemaEntityType[]> => {
    return await api.get(`/projects/${projectId}/schema/entities`);
  },
  createEntityType: async (projectId: string, data: unknown): Promise<unknown> => {
    return await api.post(`/projects/${projectId}/schema/entities`, data);
  },
  updateEntityType: async (
    projectId: string,
    entityId: string,
    data: unknown
  ): Promise<unknown> => {
    return await api.put(`/projects/${projectId}/schema/entities/${entityId}`, data);
  },
  deleteEntityType: async (projectId: string, entityId: string): Promise<void> => {
    await api.delete(`/projects/${projectId}/schema/entities/${entityId}`);
  },

  // Edge Types
  listEdgeTypes: async (projectId: string): Promise<SchemaEdgeType[]> => {
    return await api.get(`/projects/${projectId}/schema/edges`);
  },
  createEdgeType: async (projectId: string, data: unknown): Promise<unknown> => {
    return await api.post(`/projects/${projectId}/schema/edges`, data);
  },
  updateEdgeType: async (projectId: string, edgeId: string, data: unknown): Promise<unknown> => {
    return await api.put(`/projects/${projectId}/schema/edges/${edgeId}`, data);
  },
  deleteEdgeType: async (projectId: string, edgeId: string): Promise<void> => {
    await api.delete(`/projects/${projectId}/schema/edges/${edgeId}`);
  },

  // Edge Mappings
  listEdgeMaps: async (projectId: string): Promise<EdgeMapping[]> => {
    return await api.get(`/projects/${projectId}/schema/mappings`);
  },
  createEdgeMap: async (projectId: string, data: unknown): Promise<unknown> => {
    return await api.post(`/projects/${projectId}/schema/mappings`, data);
  },
  deleteEdgeMap: async (projectId: string, mapId: string): Promise<void> => {
    await api.delete(`/projects/${projectId}/schema/mappings/${mapId}`);
  },
};
