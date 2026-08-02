export type RuntimeDeploymentsAuthority = 'cloud' | 'local';

export type RuntimeDeploymentsScope = Readonly<{
  authority: RuntimeDeploymentsAuthority;
  tenantId: string;
  instanceId: string | null;
}>;

export type RuntimeDeploymentsQuery = Readonly<{
  page?: number;
  pageSize?: number;
}>;

export type RuntimeDeploymentsNormalizedQuery = Readonly<{
  page: number;
  pageSize: number;
}>;

export type RuntimeDeploymentStatus =
  | 'pending'
  | 'running'
  | 'success'
  | 'failed'
  | 'cancelled';

export type RuntimeDeployment = Readonly<{
  id: string;
  instanceId: string;
  action: string;
  revision: number;
  status: RuntimeDeploymentStatus;
  imageVersion: string | null;
  replicas: number | null;
  startedAt: string | null;
  finishedAt: string | null;
  createdAt: string;
}>;

export type RuntimeDeploymentsPage = Readonly<{
  deployments: readonly RuntimeDeployment[];
  total: number;
  page: number;
  pageSize: number;
}>;

export type RuntimeDeploymentProgressEvent = Readonly<{
  type: string;
  status: string | null;
  deployId: string | null;
}>;

export type RuntimeDeploymentsRequestOptions = Readonly<{
  signal?: AbortSignal;
}>;

export type RuntimeDeploymentsClient = Readonly<{
  list(
    scope: RuntimeDeploymentsScope,
    query?: RuntimeDeploymentsQuery,
    options?: RuntimeDeploymentsRequestOptions,
  ): Promise<RuntimeDeploymentsPage>;
  get(
    scope: RuntimeDeploymentsScope,
    deploymentId: string,
    options?: RuntimeDeploymentsRequestOptions,
  ): Promise<RuntimeDeployment>;
  streamProgress(
    scope: RuntimeDeploymentsScope,
    deploymentId: string,
    onEvent: (
      event: RuntimeDeploymentProgressEvent,
    ) => void | Promise<void>,
    options?: RuntimeDeploymentsRequestOptions,
  ): Promise<void>;
}>;

export type RuntimeDeploymentsResourceState =
  | 'loading'
  | 'ready'
  | 'empty'
  | 'stale'
  | 'error'
  | 'forbidden'
  | 'conflict'
  | 'unavailable';

export type RuntimeDeploymentDetailState =
  | 'idle'
  | 'loading'
  | 'ready'
  | 'error'
  | 'forbidden'
  | 'conflict'
  | 'unavailable';

export type RuntimeDeploymentProgressState =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'stale'
  | 'complete'
  | 'unavailable';

export type RuntimeDeploymentsModel = Readonly<{
  scope: RuntimeDeploymentsScope;
  authority: RuntimeDeploymentsAuthority;
  state: RuntimeDeploymentsResourceState;
  reasonCode: string;
  retryVisible: boolean;
  allowedActions: readonly string[];
  deployments: readonly RuntimeDeployment[];
  total: number;
  query: RuntimeDeploymentsNormalizedQuery;
  selectedDeployment: RuntimeDeployment | null;
  detailState: RuntimeDeploymentDetailState;
  detailReasonCode: string | null;
  progressState: RuntimeDeploymentProgressState;
  progressReasonCode: string | null;
  progressRetryVisible: boolean;
  lastUpdatedAt: string | null;
}>;
