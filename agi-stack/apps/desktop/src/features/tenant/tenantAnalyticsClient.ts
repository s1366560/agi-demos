export type TenantAnalyticsAuthority = 'cloud' | 'local';
export type TenantAnalyticsPeriod = '7d' | '30d' | '90d';
export type TenantAnalyticsAvailability =
  | 'available'
  | 'degraded'
  | 'unavailable'
  | 'not_applicable';

export type TenantAnalyticsScope = Readonly<{
  authority: TenantAnalyticsAuthority;
  tenantId: string;
  period: TenantAnalyticsPeriod;
}>;

export type TenantAnalyticsField<T> = Readonly<{
  availability: TenantAnalyticsAvailability;
  reasonCode: string | null;
  value: T;
}>;

export type TenantAnalyticsMemoryPoint = Readonly<{
  date: string;
  count: number;
}>;

export type TenantAnalyticsProjectStorage = Readonly<{
  name: string;
  storageBytes: TenantAnalyticsField<number | null>;
  memoryCount: TenantAnalyticsField<number | null>;
}>;

export type TenantAnalyticsSnapshot = Readonly<{
  scope: TenantAnalyticsScope;
  authority: TenantAnalyticsAuthority;
  availability: TenantAnalyticsAvailability;
  reasonCode: string | null;
  serviceVersion: string;
  contractVersion: string;
  allowedActions: readonly string[];
  authorityRevision: number | null;
  memoryGrowth: TenantAnalyticsField<readonly TenantAnalyticsMemoryPoint[]>;
  projectStorage: TenantAnalyticsField<readonly TenantAnalyticsProjectStorage[]>;
  summary: Readonly<{
    totalMemories: TenantAnalyticsField<number | null>;
    totalStorageBytes: TenantAnalyticsField<number | null>;
    totalProjects: TenantAnalyticsField<number | null>;
    periodDays: number;
  }>;
}>;

export type TenantAnalyticsReadOptions = Readonly<{
  signal?: AbortSignal;
}>;

export type TenantAnalyticsClient = Readonly<{
  load: (
    scope: TenantAnalyticsScope,
    options?: TenantAnalyticsReadOptions,
  ) => Promise<TenantAnalyticsSnapshot>;
}>;
