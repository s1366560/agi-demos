export type RuntimeInstancesAuthority = 'cloud' | 'local';

export type RuntimeInstancesScope = Readonly<{
  authority: RuntimeInstancesAuthority;
  tenantId: string;
}>;
export type RuntimeInstancesQuery = Readonly<{
  page?: number;
  pageSize?: number;
  search?: string;
  status?: string | 'all';
}>;

export type RuntimeInstancesNormalizedQuery = Readonly<{
  page: number;
  pageSize: number;
  search: string;
  status: string | 'all';
}>;

export type RuntimeInstanceProjection = 'cloud' | 'local_sidecar';

export type RuntimeInstanceSummary = Readonly<{
  id: string;
  name: string;
  status: string;
  healthStatus: string | null;
  imageVersion: string | null;
  replicas: number | null;
  availableReplicas: number | null;
  clusterId: string | null;
  createdAt: string | null;
  updatedAt: string | null;
  projection: RuntimeInstanceProjection;
}>;

export type RuntimeInstancesPage = Readonly<{
  instances: readonly RuntimeInstanceSummary[];
  total: number;
  page: number;
  pageSize: number;
}>;

export type RuntimeInstancesRequestOptions = Readonly<{
  signal?: AbortSignal;
}>;

export type RuntimeInstancesClient = Readonly<{
  list(
    scope: RuntimeInstancesScope,
    query?: RuntimeInstancesQuery,
    options?: RuntimeInstancesRequestOptions,
  ): Promise<RuntimeInstancesPage>;
  restart(
    scope: RuntimeInstancesScope,
    instanceId: string,
    options?: RuntimeInstancesRequestOptions,
  ): Promise<void>;
  delete(
    scope: RuntimeInstancesScope,
    instanceId: string,
    options?: RuntimeInstancesRequestOptions,
  ): Promise<void>;
}>;

export type RuntimeInstancesResourceState =
  | 'loading'
  | 'ready'
  | 'empty'
  | 'stale'
  | 'error'
  | 'forbidden'
  | 'unavailable';

export type RuntimeInstancesMutationState =
  | 'idle'
  | 'error'
  | 'conflict'
  | 'forbidden'
  | 'unavailable';

export type RuntimeInstancesModel = Readonly<{
  scope: RuntimeInstancesScope;
  authority: RuntimeInstancesAuthority;
  state: RuntimeInstancesResourceState;
  reasonCode: string;
  mutationState: RuntimeInstancesMutationState;
  mutationReasonCode: string | null;
  busyInstanceId: string | null;
  retryVisible: boolean;
  allowedActions: readonly string[];
  instances: readonly RuntimeInstanceSummary[];
  total: number;
  query: RuntimeInstancesNormalizedQuery;
  lastUpdatedAt: string | null;
}>;
