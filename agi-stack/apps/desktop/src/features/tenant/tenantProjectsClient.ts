export type TenantProjectsAuthority = 'cloud' | 'local';
export type TenantProjectsAvailability =
  | 'available'
  | 'degraded'
  | 'unavailable'
  | 'not_applicable';

export type TenantProjectsScope = Readonly<{
  authority: TenantProjectsAuthority;
  tenantId: string;
}>;

export type TenantProjectRecord = Readonly<{
  id: string;
  tenantId: string;
  name: string;
  description: string;
  ownerId: string;
  memberIds: readonly string[];
  allowedActions: readonly string[];
  isPublic: boolean;
  createdAt: string;
  updatedAt: string | null;
  stats: Readonly<Record<string, unknown>>;
}>;

export type TenantProjectsListQuery = Readonly<{
  page?: number;
  pageSize?: number;
  search?: string;
  visibility?: 'all' | 'public' | 'private';
  ownerId?: string;
}>;

export type TenantProjectsMutationInput = Readonly<{
  name: string;
  description: string;
  isPublic?: boolean;
}>;

export type TenantProjectsMutationAction = 'create' | 'update' | 'delete';

export function createTenantProjectsMutationKey(
  action: TenantProjectsMutationAction,
): string {
  return `desktop-project-${action}-${crypto.randomUUID()}`;
}

export type TenantProjectsListSnapshot = Readonly<{
  scope: TenantProjectsScope;
  authority: TenantProjectsAuthority;
  availability: TenantProjectsAvailability;
  reasonCode: string | null;
  serviceVersion: string;
  contractVersion: string;
  allowedActions: readonly string[];
  authorityRevision: number | null;
  projects: readonly TenantProjectRecord[];
  total: number;
  page: number;
  pageSize: number;
  ownerIds: readonly string[];
}>;

export type TenantProjectsRequestOptions = Readonly<{
  signal?: AbortSignal;
  idempotencyKey?: string;
}>;

export type TenantProjectsClient = Readonly<{
  list: (
    scope: TenantProjectsScope,
    query?: TenantProjectsListQuery,
    options?: TenantProjectsRequestOptions,
  ) => Promise<TenantProjectsListSnapshot>;
  get?: (
    scope: TenantProjectsScope,
    projectId: string,
    options?: TenantProjectsRequestOptions,
  ) => Promise<TenantProjectRecord>;
  create?: (
    scope: TenantProjectsScope,
    input: TenantProjectsMutationInput,
    options?: TenantProjectsRequestOptions,
  ) => Promise<TenantProjectRecord>;
  update?: (
    scope: TenantProjectsScope,
    projectId: string,
    input: TenantProjectsMutationInput,
    options?: TenantProjectsRequestOptions,
  ) => Promise<TenantProjectRecord>;
  delete?: (
    scope: TenantProjectsScope,
    projectId: string,
    options?: TenantProjectsRequestOptions,
  ) => Promise<void>;
}>;
