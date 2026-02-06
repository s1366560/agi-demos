import { httpClient } from './client/httpClient';

// Use centralized HTTP client
const apiClient = httpClient;

// Types
export interface GraphNode {
  id: string;
  label: string;
  type: 'Entity' | 'Episodic' | 'Community';
  name: string;
  summary?: string;
  entity_type?: string;
  member_count?: number;
  tenant_id?: string;
  project_id?: string;
  created_at?: string;
  [key: string]: unknown;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  weight?: number;
  [key: string]: unknown;
}

export interface GraphData {
  elements: {
    nodes: Array<{ data: GraphNode }>;
    edges: Array<{ data: GraphEdge }>;
  };
}

export interface Entity {
  uuid: string;
  name: string;
  entity_type: string;
  summary: string;
  tenant_id?: string;
  project_id?: string;
  created_at?: string;
}

export interface Community {
  uuid: string;
  name: string;
  summary: string;
  member_count: number;
  tenant_id?: string;
  project_id?: string;
  formed_at?: string;
  created_at?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface EntityTypeStats {
  entity_types: Array<{ entity_type: string; count: number }>;
  total: number;
}

export interface EntityRelationships {
  relationships: Array<{
    relationship_type: string;
    target_entity_name?: string;
    target_entity_type?: string;
    source_entity_name: string;
    source_entity_type: string;
  }>;
  total: number;
}

export interface CommunityMembers {
  members: Entity[];
  total: number;
}

export interface TaskStatus {
  status: string;
  message?: string;
  task_id?: string;
}

export interface TaskList {
  tasks: Array<{
    id: string;
    status: string;
    created_at: string;
    task_type: string;
  }>;
  total: number;
}

export interface TaskCancel {
  status: string;
  message: string;
  task_id: string;
}

export interface SearchResults {
  results: unknown[];
  total: number;
  search_type: string;
  strategy?: string;
  time_range?: unknown;
  facets?: unknown;
}

export interface GraphStats {
  entity_count: number;
  episodic_count: number;
  community_count: number;
  edge_count: number;
}

export interface EpisodeData {
  name: string;
  content: string;
  project_id: string;
  source_type?: string;
  source_id?: string;
  url?: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
}

export interface EpisodeListData {
  episodes?: unknown[];
  items?: unknown[];
  total: number;
  limit?: number;
  offset?: number;
}

export interface DeleteResult {
  status: string;
  message: string;
}

export interface MaintenanceStatus {
  stats: {
    entities: number;
    episodes: number;
    communities: number;
    old_episodes: number;
  };
  recommendations: Array<{
    type: string;
    priority: 'low' | 'medium' | 'high';
    message: string;
  }>;
  last_checked: string;
}

export interface RefreshResult {
  status: string;
  message: string;
  task_id: string;
  episodes_to_process: number | string;
}

export interface DeduplicateResult {
  status?: string;
  message: string;
  task_id?: string;
  dry_run: boolean;
  duplicates_found?: number;
  duplicate_groups?: unknown[];
  merged?: number;
}

export interface InvalidateEdgesResult {
  dry_run: boolean;
  stale_edges_found?: number;
  deleted?: number;
  cutoff_date: string;
  message: string;
  stale_by_type?: Record<string, number>;
}

export interface OptimizeResult {
  operations_run: Array<{
    operation: string;
    result: unknown;
  }>;
  dry_run: boolean;
  timestamp: string;
}

export interface EmbeddingStatus {
  current_provider: string;
  current_dimension: number;
  existing_dimension: number | null;
  is_compatible: boolean;
  missing_embeddings: number;
}

export interface RebuildEmbeddingsResult {
  status: string;
  result: {
    nodes: number;
    errors: number;
  };
}

export interface OptimizeContentResult {
  content: string;
}

// Graph Service
export const graphService = {
  // Graph Data
  async getGraphData(params: {
    tenant_id?: string;
    project_id?: string;
    limit?: number;
    since?: string;
  }): Promise<GraphData> {
    const queryParams = new URLSearchParams();
    if (params.tenant_id) queryParams.append('tenant_id', params.tenant_id);
    if (params.project_id) queryParams.append('project_id', params.project_id);
    if (params.limit) queryParams.append('limit', params.limit.toString());
    if (params.since) queryParams.append('since', params.since);

    return await apiClient.get<GraphData>(`/graph/memory/graph?${queryParams.toString()}`);
  },

  async getSubgraph(params: {
    node_uuids: string[];
    include_neighbors?: boolean;
    limit?: number;
    tenant_id?: string;
    project_id?: string;
  }): Promise<GraphData> {
    return await apiClient.post<GraphData>('/graph/memory/graph/subgraph', params);
  },

  // Entities
  async getEntity(entityId: string): Promise<Entity> {
    return await apiClient.get<Entity>(`/graph/entities/${entityId}`);
  },

  async listEntities(params: {
    tenant_id?: string;
    project_id?: string;
    entity_type?: string;
    limit?: number;
    offset?: number;
  }): Promise<PaginatedResponse<Entity>> {
    const queryParams = new URLSearchParams();
    if (params.tenant_id) queryParams.append('tenant_id', params.tenant_id);
    if (params.project_id) queryParams.append('project_id', params.project_id);
    if (params.entity_type) queryParams.append('entity_type', params.entity_type);
    if (params.limit) queryParams.append('limit', params.limit.toString());
    if (params.offset) queryParams.append('offset', params.offset.toString());

    const response = await apiClient.get<{
      entities: Entity[];
      items: Entity[];
      total: number;
      limit?: number;
      offset?: number;
    }>(`/graph/entities/?${queryParams.toString()}`);
    return {
      items: response.entities || response.items || [],
      total: response.total,
      limit: response.limit ?? 50,
      offset: response.offset ?? 0,
      has_more:
        (response.offset ?? 0) + (response.entities || response.items || []).length <
        response.total,
    };
  },

  async getEntityTypes(params: { project_id?: string } = {}): Promise<EntityTypeStats> {
    const queryParams = new URLSearchParams();
    if (params.project_id) queryParams.append('project_id', params.project_id);

    return await apiClient.get<EntityTypeStats>(`/graph/entities/types?${queryParams.toString()}`);
  },

  async getEntityRelationships(
    entityId: string,
    params: { relationship_type?: string; limit?: number } = {}
  ): Promise<EntityRelationships> {
    const queryParams = new URLSearchParams();
    if (params.relationship_type) queryParams.append('relationship_type', params.relationship_type);
    if (params.limit) queryParams.append('limit', params.limit.toString());

    return await apiClient.get<EntityRelationships>(
      `/graph/entities/${entityId}/relationships?${queryParams.toString()}`
    );
  },

  // Communities
  async getCommunity(communityId: string): Promise<Community> {
    return await apiClient.get<Community>(`/graph/communities/${communityId}`);
  },

  async listCommunities(params: {
    tenant_id?: string;
    project_id?: string;
    min_members?: number;
    limit?: number;
    offset?: number;
  }): Promise<{ communities: Community[]; total: number; limit?: number; offset?: number }> {
    const queryParams = new URLSearchParams();
    if (params.tenant_id) queryParams.append('tenant_id', params.tenant_id);
    if (params.project_id) queryParams.append('project_id', params.project_id);
    if (params.min_members) queryParams.append('min_members', params.min_members.toString());
    if (params.limit) queryParams.append('limit', params.limit.toString());
    if (params.offset) queryParams.append('offset', params.offset.toString());

    return await apiClient.get<{
      communities: Community[];
      total: number;
      limit?: number;
      offset?: number;
    }>(`/graph/communities/?${queryParams.toString()}`);
  },

  async getCommunityMembers(communityId: string, limit = 100): Promise<CommunityMembers> {
    return await apiClient.get<CommunityMembers>(
      `/graph/communities/${communityId}/members?limit=${limit}`
    );
  },

  async rebuildCommunities(
    background = false,
    projectId?: string
  ): Promise<{
    status: string;
    message: string;
    communities_count?: number;
    edges_count?: number;
    task_id?: string;
    task_url?: string;
  }> {
    const params = new URLSearchParams();
    if (background) params.append('background', 'true');
    if (projectId) params.append('project_id', projectId);

    const queryString = params.toString();
    const url = `/graph/communities/rebuild${queryString ? '?' + queryString : ''}`;

    return await apiClient.post(url);
  },

  // Background Tasks
  async getTaskStatus(taskId: string): Promise<TaskStatus> {
    return await apiClient.get<TaskStatus>(`/tasks/${taskId}`);
  },

  async listTasks(status?: string): Promise<TaskList> {
    const queryParams = new URLSearchParams();
    if (status) queryParams.append('status', status);

    return await apiClient.get<TaskList>(`/tasks/?${queryParams.toString()}`);
  },

  async cancelTask(taskId: string): Promise<TaskCancel> {
    return await apiClient.post<TaskCancel>(`/tasks/${taskId}/cancel`);
  },

  // Enhanced Search
  async advancedSearch(params: {
    query: string;
    strategy?: string;
    limit?: number;
    focal_node_uuid?: string;
    reranker?: string;
    tenant_id?: string;
    project_id?: string;
    since?: string;
  }): Promise<SearchResults> {
    return await apiClient.post<SearchResults>('/search-enhanced/advanced', params);
  },

  async searchByGraphTraversal(params: {
    start_entity_uuid: string;
    max_depth?: number;
    relationship_types?: string[];
    limit?: number;
    tenant_id?: string;
  }): Promise<SearchResults> {
    return await apiClient.post<SearchResults>('/search-enhanced/graph-traversal', params);
  },

  async searchByCommunity(params: {
    community_uuid: string;
    limit?: number;
    include_episodes?: boolean;
  }): Promise<SearchResults> {
    return await apiClient.post<SearchResults>('/search-enhanced/community', params);
  },

  async searchTemporal(params: {
    query: string;
    since?: string;
    until?: string;
    limit?: number;
    tenant_id?: string;
  }): Promise<SearchResults> {
    return await apiClient.post<SearchResults>('/search-enhanced/temporal', params);
  },

  async searchWithFacets(params: {
    query: string;
    entity_types?: string[];
    tags?: string[];
    since?: string;
    limit?: number;
    offset?: number;
    tenant_id?: string;
  }): Promise<SearchResults & { limit: number; offset: number }> {
    return await apiClient.post<SearchResults & { limit: number; offset: number }>(
      '/search-enhanced/faceted',
      params
    );
  },

  async getSearchCapabilities(): Promise<unknown> {
    return await apiClient.get('/search-enhanced/capabilities');
  },

  // Data Export
  async exportData(params: {
    tenant_id?: string;
    include_episodes?: boolean;
    include_entities?: boolean;
    include_relationships?: boolean;
    include_communities?: boolean;
  }): Promise<unknown> {
    return await apiClient.post('/data/export', params);
  },

  async getGraphStats(tenant_id?: string): Promise<GraphStats> {
    const queryParams = tenant_id ? `?tenant_id=${tenant_id}` : '';
    return await apiClient.get<GraphStats>(`/data/stats${queryParams}`);
  },

  // Episodes (Enhanced)
  async addEpisode(data: {
    content: string;
    project_id: string;
    source_type?: string;
    source_id?: string;
    name?: string;
    url?: string;
    metadata?: Record<string, unknown>;
  }): Promise<EpisodeData> {
    return await apiClient.post<EpisodeData>('/episodes/', data);
  },

  async getEpisode(episodeName: string): Promise<EpisodeData> {
    return await apiClient.get<EpisodeData>(`/episodes/${encodeURIComponent(episodeName)}`);
  },

  async listEpisodes(params: {
    tenant_id?: string;
    project_id?: string;
    user_id?: string;
    limit?: number;
    offset?: number;
    sort_by?: string;
    sort_desc?: boolean;
  }): Promise<PaginatedResponse<unknown>> {
    const queryParams = new URLSearchParams();
    if (params.tenant_id) queryParams.append('tenant_id', params.tenant_id);
    if (params.project_id) queryParams.append('project_id', params.project_id);
    if (params.user_id) queryParams.append('user_id', params.user_id);
    if (params.limit) queryParams.append('limit', params.limit.toString());
    if (params.offset) queryParams.append('offset', params.offset.toString());
    if (params.sort_by) queryParams.append('sort_by', params.sort_by);
    if (params.sort_desc !== undefined)
      queryParams.append('sort_desc', params.sort_desc.toString());

    const response = await apiClient.get<EpisodeListData>(`/episodes/?${queryParams.toString()}`);
    // Map backend 'episodes' to frontend 'items'
    const items = response.episodes || response.items || [];
    return {
      items,
      total: response.total,
      limit: response.limit ?? 50,
      offset: response.offset ?? 0,
      has_more: (response.offset ?? 0) + items.length < response.total,
    };
  },

  async deleteEpisode(episodeName: string): Promise<DeleteResult> {
    return await apiClient.delete<DeleteResult>(`/episodes/${encodeURIComponent(episodeName)}`);
  },

  // Maintenance
  async getMaintenanceStatus(): Promise<MaintenanceStatus> {
    return await apiClient.get<MaintenanceStatus>('/maintenance/status');
  },

  async incrementalRefresh(params: {
    episode_uuids?: string[];
    rebuild_communities?: boolean;
  }): Promise<RefreshResult> {
    return await apiClient.post<RefreshResult>('/maintenance/refresh/incremental', params);
  },

  async deduplicateEntities(params: {
    similarity_threshold?: number;
    dry_run?: boolean;
  }): Promise<DeduplicateResult> {
    return await apiClient.post<DeduplicateResult>('/maintenance/deduplicate', params);
  },

  async invalidateStaleEdges(params: {
    days_since_update?: number;
    dry_run?: boolean;
  }): Promise<InvalidateEdgesResult> {
    return await apiClient.post<InvalidateEdgesResult>('/maintenance/invalidate-edges', params);
  },

  async optimizeGraph(params: {
    operations: string[];
    dry_run?: boolean;
  }): Promise<OptimizeResult> {
    return await apiClient.post<OptimizeResult>('/maintenance/optimize', params);
  },

  // Embedding Management
  async getEmbeddingStatus(projectId: string): Promise<EmbeddingStatus> {
    return await apiClient.get<EmbeddingStatus>(
      `/maintenance/embeddings/status?project_id=${projectId}`
    );
  },

  async rebuildEmbeddings(projectId: string): Promise<RebuildEmbeddingsResult> {
    return await apiClient.post<RebuildEmbeddingsResult>(
      `/maintenance/embeddings/rebuild?project_id=${projectId}`
    );
  },

  // AI Tools
  async optimizeContent(data: {
    content: string;
    instruction?: string;
  }): Promise<OptimizeContentResult> {
    return await apiClient.post<OptimizeContentResult>('/ai/optimize', data);
  },
};

// Legacy export for backward compatibility
export const graphitiService = graphService;

export default graphService;
