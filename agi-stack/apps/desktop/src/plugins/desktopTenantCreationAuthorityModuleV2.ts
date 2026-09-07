import { PLUGIN_MODULE_CATALOG_V2, RuntimeV2Error, type ContextV2, type PluginDefinitionV2 } from '@agistack/plugin-runtime';

import type { TenantCreationClient } from '../features/tenant-creation/tenantCreationClient';
import type { TenantCreationInput, TenantCreationRecord } from '../features/tenant-creation/tenantCreationModel';
import type { DesktopRuntimeConfig } from '../types';
import { createDesktopTenantCreationHttpAuthorityV2 } from './desktopTenantCreationHttpProjectionV2';
import { prepareDesktopTenantCreationOperationV2, requireDesktopTenantCreationRecordV2, type DesktopTenantCreationOperationInputV2, type PreparedDesktopTenantCreationOperationV2 } from './desktopTenantCreationOperationContractV2';
import type { DesktopRendererGenerationActionsV2, DesktopRendererServiceOperationLeaseAdmissionV2 } from './desktopRendererGenerationContextV2';

export const DESKTOP_TENANT_CREATION_AUTHORITY_MODULE_REF_V2 = 'builtin://memstack/desktop/tenant-creation-authority';
export const DESKTOP_TENANT_CREATION_AUTHORITY_SERVICE_V2 = 'service:desktop-renderer.tenant-creation-authority';
export const DESKTOP_TENANT_CREATION_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantCreationAuthorityV2 {
  readonly create: (input: TenantCreationInput, signal?: AbortSignal) => Promise<TenantCreationRecord>;
}
export interface DesktopTenantCreationAuthorityServiceV2 {
  readonly bindOperation: (config: DesktopRuntimeConfig) => DesktopTenantCreationAuthorityV2;
}
export interface DesktopTenantCreationOperationsV2 {
  readonly createTenant: (input: DesktopTenantCreationOperationInputV2) => Promise<TenantCreationRecord>;
}
type RejectionV2 = Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }> |
  Readonly<{ reasonCode: 'desktop_renderer_generation_actions_unavailable'; runtimeCode?: undefined }>;

export class DesktopTenantCreationAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: RejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;
  constructor(rejection: RejectionV2) {
    super(rejection.reasonCode); this.name = 'DesktopTenantCreationAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode; this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantCreationAuthorityV2(context: ContextV2, config: Readonly<Record<string, unknown>>): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error('desktop_tenant_creation_authority_config_invalid', 'desktop tenant creation authority requires desktop-api-fetch strategy');
  }
  context.provide(DESKTOP_TENANT_CREATION_AUTHORITY_SERVICE_V2, Object.freeze({ bindOperation: createDesktopTenantCreationHttpAuthorityV2 }));
}

export const desktopTenantCreationAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TENANT_CREATION_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopTenantCreationAuthorityV2,
});

export function createDesktopTenantCreationOperationsV2(resolveActions: () => DesktopRendererGenerationActionsV2 | null): DesktopTenantCreationOperationsV2 {
  return Object.freeze({
    createTenant(input: DesktopTenantCreationOperationInputV2) {
      const prepared = prepareDesktopTenantCreationOperationV2(input);
      const actions = resolveActions();
      if (actions === null) throw new DesktopTenantCreationAuthorityUnavailableErrorV2({ reasonCode: 'desktop_renderer_generation_actions_unavailable' });
      return runOperationV2(actions, prepared);
    },
  });
}

export function createDesktopTenantCreationClientV2(operations: DesktopTenantCreationOperationsV2, config: DesktopRuntimeConfig): TenantCreationClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({ create: (input, options) => operations.createTenant({ config: operationConfig, input, ...(options?.signal === undefined ? {} : { signal: options.signal }) }) });
}

async function runOperationV2(actions: DesktopRendererGenerationActionsV2, prepared: PreparedDesktopTenantCreationOperationV2): Promise<TenantCreationRecord> {
  const admission = await actions.acquireServiceOperationLease<DesktopTenantCreationAuthorityServiceV2>({
    service: DESKTOP_TENANT_CREATION_AUTHORITY_SERVICE_V2, version: DESKTOP_TENANT_CREATION_AUTHORITY_VERSION_V2, scope: Object.freeze({ kind: 'root' }),
  });
  if (admission.status === 'rejected') throw new DesktopTenantCreationAuthorityUnavailableErrorV2(admission);
  let failed = false; let active = true;
  try {
    return await admission.useService(async (candidate) => {
      const service = requireServiceV2(candidate);
      const authority = requireAuthorityV2(service.bindOperation(prepared.config));
      if (!active) throw releasedV2();
      const result = await authority.create(prepared.input, prepared.signal);
      if (!active) throw releasedV2();
      return requireDesktopTenantCreationRecordV2(result);
    });
  } catch (error) { failed = true; throw error; }
  finally { active = false; try { await admission.release(); } catch (error) { if (!failed) throw error; } }
}

function requireServiceV2(value: unknown): DesktopTenantCreationAuthorityServiceV2 {
  if (!plainV2(value) || Object.keys(value).length !== 1 || typeof value.bindOperation !== 'function') throw invalidServiceV2();
  return value as unknown as DesktopTenantCreationAuthorityServiceV2;
}
function requireAuthorityV2(value: unknown): DesktopTenantCreationAuthorityV2 {
  if (!plainV2(value) || Object.keys(value).length !== 1 || typeof value.create !== 'function') throw invalidServiceV2();
  return value as unknown as DesktopTenantCreationAuthorityV2;
}
function plainV2(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) && [Object.prototype, null].includes(Object.getPrototypeOf(value));
}
function invalidServiceV2(): RuntimeV2Error { return new RuntimeV2Error('desktop_tenant_creation_service_invalid', 'desktop tenant creation authority service is invalid'); }
function releasedV2(): RuntimeV2Error { return new RuntimeV2Error('desktop_tenant_creation_operation_released', 'desktop tenant creation operation has been released'); }
function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find((item) => item.module_ref === DESKTOP_TENANT_CREATION_AUTHORITY_MODULE_REF_V2);
  if (!entry) throw new RuntimeV2Error('desktop_tenant_creation_authority_catalog_missing', 'desktop tenant creation authority is absent from the generated catalog');
  return entry.contract_digest;
}
