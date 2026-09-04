import { PLUGIN_MODULE_CATALOG_V2, RuntimeV2Error, type ContextV2, type PluginDefinitionV2 } from '@agistack/plugin-runtime';

import type { DesktopRuntimeConfig } from '../types';
import type { TenantAdminRequestOptions } from '../features/tenant-admin/tenantAdminHttp';
import type { TenantAuditClient, TenantAuditExport, TenantAuditSnapshot } from '../features/tenant-admin/tenantAuditClient';
import type { DesktopRendererGenerationActionsV2, DesktopRendererServiceOperationLeaseAdmissionV2 } from './desktopRendererGenerationContextV2';
import { createDesktopTenantAuditHttpProjectionV2 } from './desktopTenantAuditHttpProjectionV2';
import { freezeTenantAuditConfigV2, prepareTenantAuditExportV2, prepareTenantAuditLoadV2, requireTenantAuditExportV2, requireTenantAuditSnapshotV2, type DesktopTenantAuditExportInputV2, type DesktopTenantAuditLoadInputV2 } from './desktopTenantAuditOperationContractV2';

export const DESKTOP_TENANT_AUDIT_AUTHORITY_MODULE_REF_V2 = 'builtin://memstack/desktop/tenant-audit-authority';
export const DESKTOP_TENANT_AUDIT_AUTHORITY_SERVICE_V2 = 'service:desktop-renderer.tenant-audit-authority';
export const DESKTOP_TENANT_AUDIT_AUTHORITY_VERSION_V2 = '1.0.0';
export interface DesktopTenantAuditAuthorityServiceV2 { bindOperation(config: DesktopRuntimeConfig): TenantAuditClient; }
export interface DesktopTenantAuditOperationsV2 {
  loadTenantAudit(input: DesktopTenantAuditLoadInputV2): Promise<TenantAuditSnapshot>;
  exportTenantAuditLogs(input: DesktopTenantAuditExportInputV2): Promise<TenantAuditExport>;
}
type Rejection = Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }> | Readonly<{ reasonCode: 'desktop_renderer_generation_actions_unavailable'; runtimeCode?: undefined }>;
export class DesktopTenantAuditAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode; readonly runtimeCode;
  constructor(rejection: Rejection) { super(rejection.reasonCode); this.name = 'DesktopTenantAuditAuthorityUnavailableErrorV2'; this.reasonCode = rejection.reasonCode; this.runtimeCode = rejection.runtimeCode; }
}
export function applyDesktopTenantAuditAuthorityV2(context: ContextV2, config: Readonly<Record<string, unknown>>): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') throw new RuntimeV2Error('desktop_tenant_audit_authority_config_invalid', 'desktop tenant audit authority requires desktop-api-fetch strategy');
  context.provide(DESKTOP_TENANT_AUDIT_AUTHORITY_SERVICE_V2, Object.freeze({ bindOperation: createDesktopTenantAuditHttpProjectionV2 }));
}
export const desktopTenantAuditAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({ moduleRef: DESKTOP_TENANT_AUDIT_AUTHORITY_MODULE_REF_V2, contractDigest: generatedDigest(), apply: applyDesktopTenantAuditAuthorityV2 });
export function createDesktopTenantAuditOperationsV2(resolve: () => DesktopRendererGenerationActionsV2 | null): DesktopTenantAuditOperationsV2 {
  return Object.freeze({
    loadTenantAudit(input: DesktopTenantAuditLoadInputV2) { const p = prepareTenantAuditLoadV2(input); return run(resolve, p, async (a) => requireTenantAuditSnapshotV2(await a.load(p.scope, p.query, options(p.signal)), p.scope)); },
    exportTenantAuditLogs(input: DesktopTenantAuditExportInputV2) { const p = prepareTenantAuditExportV2(input); return run(resolve, p, async (a) => requireTenantAuditExportV2(await a.exportLogs(p.scope, p.format, p.query, options(p.signal)), p.format)); },
  });
}
export function createDesktopTenantAuditClientV2(operations: DesktopTenantAuditOperationsV2, config: DesktopRuntimeConfig): TenantAuditClient {
  const frozen = freezeTenantAuditConfigV2(config);
  return Object.freeze({
    load: (scope, query, request) => operations.loadTenantAudit({ config: frozen, scope, ...(query === undefined ? {} : { query }), ...(request?.signal === undefined ? {} : { signal: request.signal }) }),
    exportLogs: (scope, format, query, request) => operations.exportTenantAuditLogs({ config: frozen, scope, format, ...(query === undefined ? {} : { query }), ...(request?.signal === undefined ? {} : { signal: request.signal }) }),
  });
}
async function run<T>(resolve: () => DesktopRendererGenerationActionsV2 | null, prepared: DesktopTenantAuditLoadInputV2, operation: (authority: TenantAuditClient) => Promise<T>): Promise<T> {
  const actions = resolve(); if (!actions) throw new DesktopTenantAuditAuthorityUnavailableErrorV2({ reasonCode: 'desktop_renderer_generation_actions_unavailable' });
  const admission = await actions.acquireServiceOperationLease<DesktopTenantAuditAuthorityServiceV2>({ service: DESKTOP_TENANT_AUDIT_AUTHORITY_SERVICE_V2, version: DESKTOP_TENANT_AUDIT_AUTHORITY_VERSION_V2, scope: Object.freeze({ kind: 'tenant', tenant_id: prepared.scope.tenantId }) });
  if (admission.status === 'rejected') throw new DesktopTenantAuditAuthorityUnavailableErrorV2(admission);
  let failed = false; let active = true;
  try { return await admission.useService(async (candidate) => {
    if (!record(candidate) || Object.keys(candidate).length !== 1 || typeof candidate.bindOperation !== 'function') throw invalidService();
    const raw = candidate.bindOperation(prepared.config);
    if (!record(raw) || Object.keys(raw).length !== 2 || typeof raw.load !== 'function' || typeof raw.exportLogs !== 'function') throw invalidService();
    const authority = Object.freeze({ load: (...args: Parameters<TenantAuditClient['load']>) => { assertActive(active); return raw.load(...args); }, exportLogs: (...args: Parameters<TenantAuditClient['exportLogs']>) => { assertActive(active); return raw.exportLogs(...args); } });
    const result = await operation(authority); assertActive(active); return result;
  }); } catch (error) { failed = true; throw error; } finally { active = false; try { await admission.release(); } catch (error) { if (!failed) throw error; } }
}
function options(signal?: AbortSignal): TenantAdminRequestOptions | undefined { return signal === undefined ? undefined : Object.freeze({ signal }); }
function assertActive(active: boolean) { if (!active) throw new RuntimeV2Error('desktop_tenant_audit_operation_released', 'desktop tenant audit operation released'); }
function record(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value); }
function invalidService() { return new RuntimeV2Error('desktop_tenant_audit_service_invalid', 'desktop tenant audit authority service invalid'); }
function generatedDigest() { const entry = PLUGIN_MODULE_CATALOG_V2.modules.find((item) => item.module_ref === DESKTOP_TENANT_AUDIT_AUTHORITY_MODULE_REF_V2); if (!entry) throw new RuntimeV2Error('desktop_tenant_audit_authority_catalog_missing', 'desktop tenant audit authority absent from catalog'); return entry.contract_digest; }
