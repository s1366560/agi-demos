import type { DesktopRuntimeConfig } from '../../types';
import type { TenantAdminAuthoritySnapshot } from './tenantAdminController';
import {
  isRecord,
  observeTenantMembership,
  optionalText,
  requestTenantAdminJson,
  requireCloudTenantScope,
  requireIdentifier,
  requireNonnegativeInteger,
  requireText,
  tenantAdminError,
  type TenantAdminRequestOptions,
  type TenantAdminRole,
  type TenantAdminScope,
} from './tenantAdminHttp';

export const TENANT_AUDIT_ROUTE_ID = 'tenant-tenant-audit-logs' as const;
export const TENANT_AUDIT_LOCAL_REASON = 'cloud_tenant_audit_authority_not_applicable' as const;
export const TENANT_AUDIT_FILE_REASON = 'tenant_audit_export_file_ipc_unavailable' as const;

export type TenantAuditEntry = Readonly<{
  id: string;
  timestamp: string;
  actor: string | null;
  actorName: string | null;
  action: string;
  resourceType: string;
  resourceId: string | null;
  tenantId: string | null;
  details: Readonly<Record<string, unknown>> | null;
  ipAddress: string | null;
  userAgent: string | null;
}>;
export type TenantAuditQuery = Readonly<{
  action?: string;
  resourceType?: string;
  actor?: string;
  fromDate?: string;
  toDate?: string;
  limit?: number;
  offset?: number;
}>;
export type TenantAuditRuntimeSummary = Readonly<{
  total: number;
  actionCounts: Readonly<Record<string, number>>;
  executorCounts: Readonly<Record<string, number>>;
  familyCounts: Readonly<Record<string, number>>;
  isolationModeCounts: Readonly<Record<string, number>>;
  latestTimestamp: string | null;
}>;
export type TenantAuditData = Readonly<{
  membershipRole: TenantAdminRole;
  entries: readonly TenantAuditEntry[];
  total: number;
  limit: number;
  offset: number;
  runtimeSummary: TenantAuditRuntimeSummary;
  query: Required<Pick<TenantAuditQuery, 'limit' | 'offset'>> & TenantAuditQuery;
}>;
export type TenantAuditSnapshot = TenantAdminAuthoritySnapshot<TenantAdminScope, TenantAuditData> &
  TenantAuditData &
  Readonly<{ authorityRevision: number }>;
export type TenantAuditClient = Readonly<{
  load: (
    scope: TenantAdminScope,
    query?: TenantAuditQuery,
    options?: TenantAdminRequestOptions,
  ) => Promise<TenantAuditSnapshot>;
}>;

const CONTRACT_VERSION = '4.0.0' as const;
const ACTIONS = Object.freeze(['view', 'filter', 'inspect-runtime-hooks']);

export function createTenantAuditClient(config: DesktopRuntimeConfig): TenantAuditClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async load(scope, query = {}, options) {
      const currentScope = requireCloudTenantScope(runtimeConfig, scope, TENANT_AUDIT_LOCAL_REASON);
      const membershipRole = await observeTenantMembership(runtimeConfig, currentScope, options);
      const normalized = normalizeQuery(query);
      const pageRequest = requestTenantAdminJson(
        runtimeConfig,
        auditListPath(currentScope, normalized),
        options,
      );
      const authorityRequest = isFilteredQuery(normalized)
        ? requestTenantAdminJson(
            runtimeConfig,
            `${tenantPath(currentScope)}/audit-logs?limit=1&offset=0`,
            options,
          )
        : pageRequest;
      const [pagePayload, summaryPayload, authorityPayload] = await Promise.all([
        pageRequest,
        requestTenantAdminJson(
          runtimeConfig,
          `${tenantPath(currentScope)}/audit-logs/runtime-hooks/summary`,
          options,
        ),
        authorityRequest,
      ]);
      const page = parseAuditPage(pagePayload, currentScope.tenantId);
      const authorityRevision = isFilteredQuery(normalized)
        ? parseAuditPage(authorityPayload, currentScope.tenantId).total
        : page.total;
      const runtimeSummary = parseRuntimeSummary(summaryPayload);
      const data = Object.freeze({
        membershipRole,
        entries: page.entries,
        total: page.total,
        limit: page.limit,
        offset: page.offset,
        runtimeSummary,
        query: normalized,
      });
      return Object.freeze({
        scope: currentScope,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: TENANT_AUDIT_FILE_REASON,
        contractVersion: CONTRACT_VERSION,
        allowedActions: ACTIONS,
        authorityRevision,
        data,
        ...data,
      });
    },
  });
}

function auditListPath(scope: TenantAdminScope, query: TenantAuditData['query']): string {
  const params = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  if (query.action) params.set('action', query.action);
  if (query.resourceType) params.set('resource_type', query.resourceType);
  if (query.actor) params.set('actor', query.actor);
  if (query.fromDate) params.set('start_time', query.fromDate);
  if (query.toDate) params.set('end_time', query.toDate);
  return `${tenantPath(scope)}/audit-logs${
    isFilteredQuery(query) ? '/filter' : ''
  }?${params.toString()}`;
}

function isFilteredQuery(query: TenantAuditData['query']): boolean {
  return Boolean(
    query.action || query.resourceType || query.actor || query.fromDate || query.toDate,
  );
}

function tenantPath(scope: TenantAdminScope): string {
  return `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}`;
}

function normalizeQuery(query: TenantAuditQuery): TenantAuditData['query'] {
  const limit = query.limit ?? 20;
  const offset = query.offset ?? 0;
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 200) {
    throw tenantAdminError('tenant_audit_limit_invalid', 422);
  }
  if (!Number.isSafeInteger(offset) || offset < 0) {
    throw tenantAdminError('tenant_audit_offset_invalid', 422);
  }
  return Object.freeze({
    limit,
    offset,
    ...optionalQuery('action', query.action),
    ...optionalQuery('resourceType', query.resourceType),
    ...optionalQuery('actor', query.actor),
    ...optionalQuery('fromDate', query.fromDate),
    ...optionalQuery('toDate', query.toDate),
  });
}

function optionalQuery<Key extends string>(
  key: Key,
  value: string | undefined,
): Readonly<Partial<Record<Key, string>>> {
  if (value === undefined || !value.trim()) return Object.freeze({});
  if (value !== value.trim()) throw tenantAdminError('tenant_audit_filter_invalid', 422);
  return Object.freeze({ [key]: value }) as Readonly<Partial<Record<Key, string>>>;
}

function parseAuditPage(
  payload: unknown,
  tenantId: string,
): Readonly<{
  entries: readonly TenantAuditEntry[];
  total: number;
  limit: number;
  offset: number;
}> {
  if (!isRecord(payload) || !Array.isArray(payload.items)) {
    throw tenantAdminError('tenant_audit_list_contract_invalid');
  }
  return Object.freeze({
    entries: Object.freeze(payload.items.map((item) => parseAuditEntry(item, tenantId))),
    total: requireNonnegativeInteger(payload.total, 'tenant_audit_list_contract_invalid'),
    limit: positiveInteger(payload.limit, 'tenant_audit_list_contract_invalid'),
    offset: requireNonnegativeInteger(payload.offset, 'tenant_audit_list_contract_invalid'),
  });
}

function parseAuditEntry(value: unknown, tenantId: string): TenantAuditEntry {
  if (!isRecord(value)) throw tenantAdminError('tenant_audit_entry_contract_invalid');
  const observedTenant = optionalText(value.tenant_id, 'tenant_audit_entry_contract_invalid');
  if (observedTenant !== null && observedTenant !== tenantId) {
    throw tenantAdminError('tenant_audit_entry_scope_mismatch', 409);
  }
  const details = value.details;
  if (details !== null && details !== undefined && !isRecord(details)) {
    throw tenantAdminError('tenant_audit_entry_contract_invalid');
  }
  return Object.freeze({
    id: requireIdentifier(value.id, 'tenant_audit_entry_contract_invalid'),
    timestamp: requireText(value.timestamp, 'tenant_audit_entry_contract_invalid'),
    actor: optionalText(value.actor, 'tenant_audit_entry_contract_invalid'),
    actorName: optionalText(value.actor_name, 'tenant_audit_entry_contract_invalid'),
    action: requireText(value.action, 'tenant_audit_entry_contract_invalid'),
    resourceType: requireText(value.resource_type, 'tenant_audit_entry_contract_invalid'),
    resourceId: optionalText(value.resource_id, 'tenant_audit_entry_contract_invalid'),
    tenantId: observedTenant,
    details: details === null || details === undefined ? null : Object.freeze({ ...details }),
    ipAddress: optionalText(value.ip_address, 'tenant_audit_entry_contract_invalid'),
    userAgent: optionalText(value.user_agent, 'tenant_audit_entry_contract_invalid'),
  });
}

function parseRuntimeSummary(payload: unknown): TenantAuditRuntimeSummary {
  if (!isRecord(payload)) throw tenantAdminError('tenant_audit_summary_contract_invalid');
  return Object.freeze({
    total: requireNonnegativeInteger(payload.total, 'tenant_audit_summary_contract_invalid'),
    actionCounts: countRecord(payload.action_counts),
    executorCounts: countRecord(payload.executor_counts),
    familyCounts: countRecord(payload.family_counts),
    isolationModeCounts: countRecord(payload.isolation_mode_counts),
    latestTimestamp: optionalText(
      payload.latest_timestamp,
      'tenant_audit_summary_contract_invalid',
    ),
  });
}

function countRecord(value: unknown): Readonly<Record<string, number>> {
  if (!isRecord(value)) throw tenantAdminError('tenant_audit_summary_contract_invalid');
  const entries = Object.entries(value).map(([key, count]) => [
    key,
    requireNonnegativeInteger(count, 'tenant_audit_summary_contract_invalid'),
  ]);
  return Object.freeze(Object.fromEntries(entries));
}

function positiveInteger(value: unknown, reasonCode: string): number {
  const result = requireNonnegativeInteger(value, reasonCode);
  if (result === 0) throw tenantAdminError(reasonCode);
  return result;
}
