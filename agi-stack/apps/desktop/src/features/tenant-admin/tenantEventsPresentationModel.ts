import type { TenantAdminRole } from './tenantAdminHttp';
import type {
  TenantManagementPresentationInput,
  TenantManagementViewState,
} from './tenantManagementController';
import type { TenantManagementScope } from './tenantManagementHttp';
import type { TenantEvent, TenantEventsData } from './tenantEventsClient';

export type TenantEventsViewModel = Readonly<{
  state: TenantManagementViewState;
  scope: TenantManagementScope;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
  allowedActions: readonly string[];
  membershipRole: TenantAdminRole | null;
  events: readonly TenantEvent[];
  eventTypes: readonly string[];
  total: number;
  page: number;
  pageSize: number;
}>;

export function buildTenantEventsPresentation(
  input: TenantManagementPresentationInput<TenantManagementScope, TenantEventsData>,
): TenantEventsViewModel {
  return Object.freeze({
    state: input.state,
    scope: input.scope,
    reasonCode: input.reasonCode,
    retryVisible: input.retryVisible,
    busyAction: input.busyAction,
    allowedActions: input.snapshot?.allowedActions ?? Object.freeze([]),
    membershipRole: input.snapshot?.data.membershipRole ?? null,
    events: input.snapshot?.data.events ?? Object.freeze([]),
    eventTypes: input.snapshot?.data.eventTypes ?? Object.freeze([]),
    total: input.snapshot?.data.total ?? 0,
    page: input.snapshot?.data.page ?? 1,
    pageSize: input.snapshot?.data.pageSize ?? 20,
  });
}
