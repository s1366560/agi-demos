import type { DesktopRuntimeConfig } from '../../types';
import {
  requireIdentifier,
  requireNonnegativeInteger,
  requireText,
  tenantAdminError,
  type TenantAdminRole,
} from './tenantAdminHttp';
import {
  authorityFor,
  isRecord,
  observeTenantManagementRole,
  requestNativeEquivalentJson,
  requireRecord,
  requireStringArray,
  requireTenantManagementScope,
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
  TenantEventsData &
  Readonly<{ authorityRevision: number }>;
export type TenantEventsClient = Readonly<{
  load: (
    scope: TenantManagementScope,
    options?: TenantManagementRequestOptions & Readonly<{ filters?: TenantEventFilters }>,
  ) => Promise<TenantEventsSnapshot>;
}>;

const ACTIONS = Object.freeze(['view', 'list', 'filter', 'paginate']);

export function createTenantEventsClient(config: DesktopRuntimeConfig): TenantEventsClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async load(scope, options) {
      const currentScope = requireTenantManagementScope(
        runtimeConfig,
        scope,
        'native_equivalent',
        TENANT_EVENTS_LOCAL_REASON,
      );
      const cloudRole =
        runtimeConfig.mode === 'cloud'
          ? await observeTenantManagementRole(runtimeConfig, currentScope, options)
          : null;
      const params = eventParams(currentScope, options?.filters);
      const eventPayload = await requestNativeEquivalentJson(
        runtimeConfig,
        `/api/v1/events?${params.toString()}`,
        options ?? {},
        TENANT_EVENTS_LOCAL_REASON,
      );
      const authorityRequest = hasSelectionFilters(options?.filters)
        ? requestNativeEquivalentJson(
            runtimeConfig,
            `/api/v1/events?${eventAuthorityParams(currentScope).toString()}`,
            options ?? {},
            TENANT_EVENTS_LOCAL_REASON,
          )
        : Promise.resolve(eventPayload);
      const [eventTypesPayload, authorityPayload] = await Promise.all([
        requestNativeEquivalentJson(
          runtimeConfig,
          `/api/v1/events/types?${new URLSearchParams({ tenant_id: currentScope.tenantId })}`,
          options ?? {},
          TENANT_EVENTS_LOCAL_REASON,
        ),
        authorityRequest,
      ]);
      const membershipRole =
        cloudRole ?? (await observeTenantManagementRole(runtimeConfig, currentScope, options));
      const page = parseEvents(eventPayload, currentScope);
      const authorityRevision = hasSelectionFilters(options?.filters)
        ? parseEvents(authorityPayload, currentScope).total
        : page.total;
      const data = Object.freeze({
        membershipRole,
        ...page,
        eventTypes: requireStringArray(eventTypesPayload, 'tenant_events_types_contract_invalid'),
      });
      return Object.freeze({
        scope: currentScope,
        authority: authorityFor(runtimeConfig),
        availability: 'available',
        reasonCode: null,
        contractVersion: '4.0.0',
        allowedActions: ACTIONS,
        authorityRevision,
        data,
        ...data,
      });
    },
  });
}

function eventParams(scope: TenantManagementScope, filters?: TenantEventFilters): URLSearchParams {
  const params = new URLSearchParams({
    tenant_id: scope.tenantId,
    page: String(filters?.page ?? 1),
    page_size: String(filters?.pageSize ?? 20),
  });
  if (filters?.eventType) params.set('event_type', filters.eventType);
  if (filters?.dateFrom) params.set('date_from', filters.dateFrom);
  if (filters?.dateTo) params.set('date_to', filters.dateTo);
  return params;
}

function eventAuthorityParams(scope: TenantManagementScope): URLSearchParams {
  return new URLSearchParams({
    tenant_id: scope.tenantId,
    page: '1',
    page_size: '1',
  });
}

function hasSelectionFilters(filters?: TenantEventFilters): boolean {
  return Boolean(filters?.eventType || filters?.dateFrom || filters?.dateTo);
}

function parseEvents(
  payload: unknown,
  scope: TenantManagementScope,
): Readonly<{
  events: readonly TenantEvent[];
  total: number;
  page: number;
  pageSize: number;
}> {
  if (!isRecord(payload) || !Array.isArray(payload.items)) {
    throw tenantAdminError('tenant_events_list_contract_invalid');
  }
  return Object.freeze({
    events: Object.freeze(payload.items.map((item) => parseEvent(item, scope))),
    total: requireNonnegativeInteger(payload.total, 'tenant_events_list_contract_invalid'),
    page: requireNonnegativeInteger(payload.page, 'tenant_events_list_contract_invalid'),
    pageSize: requireNonnegativeInteger(payload.page_size, 'tenant_events_list_contract_invalid'),
  });
}

function parseEvent(value: unknown, scope: TenantManagementScope): TenantEvent {
  if (!isRecord(value)) throw tenantAdminError('tenant_events_event_contract_invalid');
  const tenantId = requireIdentifier(value.tenant_id, 'tenant_events_event_contract_invalid');
  if (tenantId !== scope.tenantId) throw tenantAdminError('tenant_events_scope_mismatch', 409);
  return Object.freeze({
    id: requireIdentifier(value.id, 'tenant_events_event_contract_invalid'),
    tenantId,
    eventType: requireText(value.event_type, 'tenant_events_event_contract_invalid'),
    message: requireText(value.message, 'tenant_events_event_contract_invalid'),
    source: requireText(value.source, 'tenant_events_event_contract_invalid'),
    metadata: requireRecord(value.metadata, 'tenant_events_event_contract_invalid'),
    createdAt: requireText(value.created_at, 'tenant_events_event_contract_invalid'),
  });
}
