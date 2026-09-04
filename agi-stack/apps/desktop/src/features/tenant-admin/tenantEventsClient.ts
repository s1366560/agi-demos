import {
  type TenantAdminRole,
} from './tenantAdminHttp';
import {
  type TenantManagementAuthoritySnapshot,
  type TenantManagementRequestOptions,
  type TenantManagementScope,
} from './tenantManagementHttp';

export const TENANT_EVENTS_ROUTE_ID = 'tenant-tenant-events' as const;
export const TENANT_EVENTS_LOCAL_REASON = 'local_event_ledger_authority_unavailable' as const;

export type TenantEvent = Readonly<{
  id: string;
  tenantId: string;
  eventType: string;
  message: string;
  source: string;
  metadata: Readonly<Record<string, unknown>>;
  createdAt: string;
}>;
export type TenantEventFilters = Readonly<{
  eventType?: string;
  dateFrom?: string;
  dateTo?: string;
  page?: number;
  pageSize?: number;
}>;
export type TenantEventsData = Readonly<{
  membershipRole: TenantAdminRole;
  events: readonly TenantEvent[];
  eventTypes: readonly string[];
  total: number;
  page: number;
  pageSize: number;
}>;
export type TenantEventsSnapshot = TenantManagementAuthoritySnapshot<
  TenantManagementScope,
  TenantEventsData
> &
  TenantEventsData;
export type TenantEventsClient = Readonly<{
  load: (
    scope: TenantManagementScope,
    options?: TenantManagementRequestOptions & Readonly<{ filters?: TenantEventFilters }>,
  ) => Promise<TenantEventsSnapshot>;
}>;
