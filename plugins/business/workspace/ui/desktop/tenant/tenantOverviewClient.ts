export type TenantOverviewAuthority = 'cloud' | 'local';

export type TenantOverviewAvailability =
  | 'available'
  | 'degraded'
  | 'unavailable'
  | 'not_applicable';

export type TenantOverviewScope = Readonly<{
  authority: TenantOverviewAuthority;
  tenantId: string;
}>;

export type TenantOverviewField<T> = Readonly<{
  availability: TenantOverviewAvailability;
  reasonCode: string | null;
  value: T;
}>;

export type TenantOverviewStorage = Readonly<{
  used: number;
  total: number;
  percentage: number;
}>;

export type TenantOverviewProject = Readonly<{
  id: string;
  name: string;
  owner: TenantOverviewField<string | null>;
  memoryConsumed: TenantOverviewField<string | null>;
  status: string;
}>;

export type TenantOverviewProjects = Readonly<{
  availability: TenantOverviewAvailability;
  reasonCode: string | null;
  value: readonly TenantOverviewProject[];
  active: number;
  newThisWeek: number;
}>;

export type TenantOverviewMembers = Readonly<{
  total: number;
  newAdded: number;
}>;

export type TenantOverviewMemoryPoint = Readonly<{
  date: string;
  used: number;
  dailyAdded: number;
  memoryCount: number;
  percentage: number;
}>;

export type TenantOverviewSnapshot = Readonly<{
  scope: TenantOverviewScope;
  authority: TenantOverviewAuthority;
  availability: TenantOverviewAvailability;
  reasonCode: string | null;
  serviceVersion: string;
  contractVersion: string;
  allowedActions: readonly string[];
  authorityRevision: number | null;
  tenantInfo: Readonly<{
    organizationId: string;
    plan: string;
    region: TenantOverviewField<string | null>;
    nextBillingDate: TenantOverviewField<string | null>;
  }>;
  storage: TenantOverviewField<TenantOverviewStorage | null>;
  projects: TenantOverviewProjects;
  members: TenantOverviewField<TenantOverviewMembers>;
  memoryHistory: TenantOverviewField<readonly TenantOverviewMemoryPoint[]>;
}>;

export type TenantOverviewReadOptions = Readonly<{
  signal?: AbortSignal;
}>;

export type TenantOverviewClient = Readonly<{
  load: (
    scope: TenantOverviewScope,
    options?: TenantOverviewReadOptions,
  ) => Promise<TenantOverviewSnapshot>;
}>;
