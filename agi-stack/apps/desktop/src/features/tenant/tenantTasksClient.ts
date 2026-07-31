export type TenantTasksAuthority = 'cloud' | 'local';

export type TenantTasksScope = Readonly<{
  authority: TenantTasksAuthority;
  tenantId: string;
  projectId: string;
}>;

export type TenantTasksQuery = Readonly<{
  search?: string;
  status?: string;
  limit?: number;
  offset?: number;
}>;

export type TenantTaskRecord = Readonly<{
  id: string;
  projectId: string | null;
  workspaceId: string | null;
  conversationId: string | null;
  taskType: string;
  name: string;
  status: string;
  createdAt: string;
  completedAt: string | null;
  error: string | null;
  duration: string | null;
  entityId: string | null;
  entityType: string | null;
  revision: number | null;
  canRetry: boolean;
  canStop: boolean;
}>;

export type TenantTaskStats = Readonly<{
  total: number;
  pending: number;
  processing: number;
  completed: number;
  failed: number;
  throughputPerMinute: number;
  errorRate: number;
}>;

export type TenantTaskQueuePoint = Readonly<{
  timestamp: string;
  depth: number;
}>;

export type TenantTasksSnapshot = Readonly<{
  scope: TenantTasksScope;
  authority: TenantTasksAuthority;
  availability: 'available' | 'degraded' | 'unavailable';
  reasonCode: string | null;
  serviceVersion: string;
  contractVersion: string;
  allowedActions: readonly string[];
  authorityRevision: number | null;
  stats: TenantTaskStats;
  queue: Readonly<{
    current: number;
    history: readonly TenantTaskQueuePoint[];
  }>;
  tasks: readonly TenantTaskRecord[];
  total: number;
  limit: number;
  offset: number;
  hasMore: boolean;
}>;

export type TenantTasksRequestOptions = Readonly<{
  signal?: AbortSignal;
}>;

export type TenantTasksRetryPendingResult = Readonly<{
  submitted: number;
  skipped: number;
  limit: number;
  taskIds: readonly string[];
}>;

export type TenantTasksClient = Readonly<{
  load: (
    scope: TenantTasksScope,
    query?: TenantTasksQuery,
    options?: TenantTasksRequestOptions,
  ) => Promise<TenantTasksSnapshot>;
  retryTask: (
    scope: TenantTasksScope,
    task: TenantTaskRecord,
    options?: TenantTasksRequestOptions,
  ) => Promise<void>;
  stopTask: (
    scope: TenantTasksScope,
    task: TenantTaskRecord,
    options?: TenantTasksRequestOptions,
  ) => Promise<void>;
  retryPending: (
    scope: TenantTasksScope,
    limit: number,
    options?: TenantTasksRequestOptions,
  ) => Promise<TenantTasksRetryPendingResult>;
}>;
