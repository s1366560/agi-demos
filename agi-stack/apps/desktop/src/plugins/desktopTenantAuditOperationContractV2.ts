import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { DesktopRuntimeConfig } from '../types';
import type {
  TenantAuditExport,
  TenantAuditExportFormat,
  TenantAuditQuery,
  TenantAuditSnapshot,
} from '../features/tenant-admin/tenantAuditClient';
import type { TenantAdminScope } from '../features/tenant-admin/tenantAdminHttp';

export type DesktopTenantAuditLoadInputV2 = Readonly<{
  config: DesktopRuntimeConfig; scope: TenantAdminScope; query?: TenantAuditQuery; signal?: AbortSignal;
}>;
export type DesktopTenantAuditExportInputV2 = DesktopTenantAuditLoadInputV2 &
  Readonly<{ format: TenantAuditExportFormat }>;
const CONFIG_KEYS = ['apiBaseUrl', 'deviceAuthorizationBaseUrl', 'apiKey', 'localApiToken', 'tenantId', 'projectId', 'workspaceId', 'mode', 'workspaceRoot'] as const;

export function prepareTenantAuditLoadV2(input: DesktopTenantAuditLoadInputV2) {
  return Object.freeze(common(input));
}
export function prepareTenantAuditExportV2(input: DesktopTenantAuditExportInputV2) {
  const prepared = common(input);
  if (input.format !== 'csv' && input.format !== 'json') throw invalidInput();
  return Object.freeze({ ...prepared, format: input.format });
}
export function freezeTenantAuditConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (!record(config) || Object.keys(config).length !== CONFIG_KEYS.length || CONFIG_KEYS.some((key) => !Object.hasOwn(config, key)) || (config.mode !== 'cloud' && config.mode !== 'local')) throw invalidInput();
  for (const key of CONFIG_KEYS) if (key !== 'mode' && typeof config[key] !== 'string') throw invalidInput();
  identifier(config.tenantId);
  return Object.freeze({ ...config });
}
export function requireTenantAuditSnapshotV2(value: unknown, scope: TenantAdminScope): TenantAuditSnapshot {
  if (!record(value) || !record(value.scope) || value.scope.authority !== scope.authority || value.scope.tenantId !== scope.tenantId || value.authority !== 'cloud' || value.availability !== 'available' || value.reasonCode !== null || value.contractVersion !== '4.0.0' || !Array.isArray(value.allowedActions) || !Number.isSafeInteger(value.authorityRevision) || Number(value.authorityRevision) < 0 || !record(value.data) || value.entries !== value.data.entries || value.runtimeSummary !== value.data.runtimeSummary || value.query !== value.data.query || !Array.isArray(value.data.entries) || !record(value.data.runtimeSummary) || !record(value.data.query)) throw invalidResponse();
  return value as unknown as TenantAuditSnapshot;
}
export function requireTenantAuditExportV2(value: unknown, format: TenantAuditExportFormat): TenantAuditExport {
  const mime = format === 'csv' ? 'text/csv' : 'application/json';
  if (!record(value) || Object.keys(value).length !== 3 || value.suggestedName !== `audit-logs.${format}` || value.mimeType !== mime || !(value.blob instanceof Blob) || value.blob.type !== mime || value.blob.size > 16 * 1024 * 1024) throw invalidResponse();
  return value as unknown as TenantAuditExport;
}
function common(input: DesktopTenantAuditLoadInputV2) {
  if (!record(input)) throw invalidInput();
  const config = freezeTenantAuditConfigV2(input.config);
  if (!record(input.scope) || Object.keys(input.scope).length !== 2 || input.scope.authority !== config.mode || input.scope.tenantId !== config.tenantId) throw invalidInput();
  identifier(input.scope.tenantId);
  const query = input.query === undefined ? undefined : freezeQuery(input.query);
  if (input.signal !== undefined && (!record(input.signal) || typeof input.signal.aborted !== 'boolean' || typeof input.signal.addEventListener !== 'function')) throw invalidInput();
  return { config, scope: Object.freeze({ ...input.scope }), ...(query === undefined ? {} : { query }), ...(input.signal === undefined ? {} : { signal: input.signal }) };
}
function freezeQuery(query: TenantAuditQuery): TenantAuditQuery {
  if (!record(query) || Object.keys(query).some((key) => !['action', 'resourceType', 'actor', 'fromDate', 'toDate', 'limit', 'offset'].includes(key))) throw invalidInput();
  for (const key of ['action', 'resourceType', 'actor', 'fromDate', 'toDate'] as const) if (query[key] !== undefined && (typeof query[key] !== 'string' || query[key] !== query[key]?.trim())) throw invalidInput();
  if (query.limit !== undefined && (!Number.isSafeInteger(query.limit) || query.limit < 1 || query.limit > 200)) throw invalidInput();
  if (query.offset !== undefined && (!Number.isSafeInteger(query.offset) || query.offset < 0)) throw invalidInput();
  return Object.freeze({ ...query });
}
function identifier(value: unknown) { if (typeof value !== 'string' || !value || value !== value.trim()) throw invalidInput(); return value; }
function record(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value); }
function invalidInput() { return new RuntimeV2Error('desktop_tenant_audit_operation_input_invalid', 'desktop tenant audit operation input invalid'); }
function invalidResponse() { return new RuntimeV2Error('desktop_tenant_audit_operation_response_invalid', 'desktop tenant audit operation response invalid'); }
