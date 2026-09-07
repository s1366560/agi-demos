import type { TenantAdminAuthoritySnapshot } from './tenantAdminController';
import type {
  TenantAdminRequestOptions,
  TenantAdminRole,
  TenantAdminScope,
} from './tenantAdminHttp';

export const TENANT_AUDIT_ROUTE_ID = 'tenant-tenant-audit-logs' as const;
export const TENANT_AUDIT_LOCAL_REASON = 'cloud_tenant_audit_authority_not_applicable' as const;
export type TenantAuditExportFormat = 'csv' | 'json';
export type TenantAuditExport = Readonly<{
  suggestedName: string;
  mimeType: 'text/csv' | 'application/json';
  blob: Blob;
}>;
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
  TenantAuditData & Readonly<{ authorityRevision: number }>;
export type TenantAuditClient = Readonly<{
  load: (scope: TenantAdminScope, query?: TenantAuditQuery, options?: TenantAdminRequestOptions) => Promise<TenantAuditSnapshot>;
  exportLogs: (scope: TenantAdminScope, format: TenantAuditExportFormat, query?: TenantAuditQuery, options?: TenantAdminRequestOptions) => Promise<TenantAuditExport>;
}>;
