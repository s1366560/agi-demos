export type RuntimeClustersAuthority = 'cloud' | 'local';

export type RuntimeClustersScope = Readonly<{
  authority: RuntimeClustersAuthority;
  tenantId: string;
}>;

export type RuntimeClustersQuery = Readonly<{
  page?: number;
  pageSize?: number;
  search?: string;
  status?: string | 'all';
}>;

export type RuntimeClustersNormalizedQuery = Readonly<{
  page: number;
  pageSize: number;
  search: string;
  status: string | 'all';
}>;

export type RuntimeClusterSummary = Readonly<{
  id: string;
  name: string;
  computeProvider: string;
  proxyEndpoint: string | null;
  status: string;
  healthStatus: string | null;
  lastHealthCheck: string | null;
  createdAt: string;
  updatedAt: string | null;
}>;

export type RuntimeClusterHealth = Readonly<{
  status: string;
  nodeCount: number;
  cpuUsage: number | null;
  memoryUsage: number | null;
  checkedAt: string | null;
}>;

export type RuntimeClustersPage = Readonly<{
  clusters: readonly RuntimeClusterSummary[];
  total: number;
  page: number;
  pageSize: number;
}>;

export type RuntimeClustersRequestOptions = Readonly<{
  signal?: AbortSignal;
}>;

export type RuntimeClustersClient = Readonly<{
  list(
    scope: RuntimeClustersScope,
    query?: RuntimeClustersQuery,
    options?: RuntimeClustersRequestOptions,
  ): Promise<RuntimeClustersPage>;
  getHealth(
    scope: RuntimeClustersScope,
    clusterId: string,
    options?: RuntimeClustersRequestOptions,
  ): Promise<RuntimeClusterHealth>;
}>;

export type RuntimeClustersResourceState =
  | 'loading'
  | 'ready'
  | 'empty'
  | 'stale'
  | 'error'
  | 'conflict'
  | 'forbidden'
  | 'unavailable';

export type RuntimeClustersHealthState =
  | 'idle'
  | 'loading'
  | 'ready'
  | 'error'
  | 'conflict'
  | 'forbidden'
  | 'unavailable';

export type RuntimeClustersModel = Readonly<{
  scope: RuntimeClustersScope;
  authority: RuntimeClustersAuthority;
  state: RuntimeClustersResourceState;
  reasonCode: string;
  healthState: RuntimeClustersHealthState;
  healthReasonCode: string | null;
  selectedClusterId: string | null;
  retryVisible: boolean;
  allowedActions: readonly string[];
  clusters: readonly RuntimeClusterSummary[];
  visibleClusters: readonly RuntimeClusterSummary[];
  health: RuntimeClusterHealth | null;
  total: number;
  query: RuntimeClustersNormalizedQuery;
  lastUpdatedAt: string | null;
}>;
